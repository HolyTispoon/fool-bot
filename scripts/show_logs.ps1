[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$RepoPath,

    # Whose logs: the bot, the Codex bot, the web app, the tunnel, or
    # all four.
    [Parameter(Position = 0)]
    [ValidateSet('all', 'bot', 'codex', 'webapp', 'tunnel')]
    [string]$Name = 'all',

    # How many of the last lines of each log to show.
    [ValidateRange(1, 1000000)]
    [int]$Tail = 40,

    # Then keep printing whatever is written, until Ctrl+C -- which
    # stops this and nothing else; the processes keep running.
    [switch]$Follow
)

# Show the logs the deploy scripts write. update_main_bot.ps1,
# run_codex_bot.ps1, run_web_app.ps1 and run_tunnel.ps1 each start
# their process hidden,
# with its stdout and stderr redirected to data\<name>.stdout.log and
# data\<name>.stderr.log, so this is the only window onto them. The
# console logging goes to stderr; stdout is mostly empty. A restart
# deletes both and starts them afresh; a stop leaves them. See
# "Keeping it running" in docs/design/collaboration.md.
#
# Each heading says whether the pid file names a live process. That is
# what the deploy scripts started, not everything running: a process
# started by hand writes no pid file, and the tunnel writes its own only
# once it has connected.

$ErrorActionPreference = 'Stop'

$resolvedRepoPath = (Resolve-Path -LiteralPath $RepoPath).Path
$runtimeFolder = Join-Path $resolvedRepoPath 'data'

# The file names are the four scripts' own; ProcessNames is what the
# pid file's process must be called, so a pid Windows has since handed
# to something else does not read as running.
$processes = [ordered]@{
    bot    = @{ Label = 'Fool bot'; Prefix = 'foolbot-main'; ProcessNames = @('python', 'pythonw') }
    codex  = @{ Label = 'Codex bot'; Prefix = 'codexbot'; ProcessNames = @('python', 'pythonw') }
    webapp = @{ Label = 'web app'; Prefix = 'webapp'; ProcessNames = @('python', 'pythonw') }
    tunnel = @{ Label = 'tunnel'; Prefix = 'tunnel'; ProcessNames = @('cloudflared') }
}

$selected = @(
    if ($Name -eq 'all') { $processes.Keys } else { $Name }
)

function Get-ProcessState {
    param(
        [Parameter(Mandatory = $true)]
        [hashtable]$Process
    )

    $pidFile = Join-Path $runtimeFolder "$($Process.Prefix).pid"
    if (-not (Test-Path -LiteralPath $pidFile)) {
        return 'no pid file'
    }
    $rawPid = (Get-Content -LiteralPath $pidFile -Raw).Trim()
    $savedPid = 0
    if ([int]::TryParse($rawPid, [ref]$savedPid)) {
        $running = Get-Process -Id $savedPid -ErrorAction SilentlyContinue
        if ($null -ne $running -and $Process.ProcessNames -contains $running.ProcessName) {
            return "running, process $savedPid"
        }
    }
    return "not running -- the pid file names $rawPid"
}

# Both logs of every selected process, stderr first.
$logs = @(
    foreach ($key in $selected) {
        foreach ($stream in @('stderr', 'stdout')) {
            [pscustomobject]@{
                Key      = $key
                Stream   = $stream
                Path     = Join-Path $runtimeFolder "$($processes[$key].Prefix).$stream.log"
                Position = [long]0
            }
        }
    }
)

foreach ($key in $selected) {
    $process = $processes[$key]
    Write-Host ''
    Write-Host "== $($process.Label) ($(Get-ProcessState -Process $process)) ==" -ForegroundColor Cyan
    foreach ($log in @($logs | Where-Object { $_.Key -eq $key })) {
        if (-not (Test-Path -LiteralPath $log.Path)) {
            Write-Host "-- $($log.Path): no file" -ForegroundColor DarkGray
            continue
        }
        $log.Position = (Get-Item -LiteralPath $log.Path).Length
        if ($log.Position -eq 0) {
            Write-Host "-- $($log.Path): empty" -ForegroundColor DarkGray
            continue
        }
        Write-Host "-- $($log.Path)" -ForegroundColor DarkGray
        Get-Content -LiteralPath $log.Path -Tail $Tail -Encoding UTF8
    }
}

if (-not $Follow) {
    return
}

# Get-Content -Wait follows one file; this follows them all, by reading
# whatever each has grown by every half second. Only whole lines are
# printed -- a line still being written waits for its newline -- and a
# log that has shrunk was deleted by a restart and is read from the top.
function Read-NewLines {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Log
    )

    if (-not (Test-Path -LiteralPath $Log.Path)) {
        $Log.Position = 0
        return
    }
    $share = [System.IO.FileShare]::ReadWrite -bor [System.IO.FileShare]::Delete
    try {
        $file = [System.IO.File]::Open(
            $Log.Path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, $share)
    } catch {
        return
    }
    try {
        if ($file.Length -lt $Log.Position) {
            $Log.Position = 0
        }
        $count = [int][Math]::Min($file.Length - $Log.Position, [long]16MB)
        if ($count -le 0) {
            return
        }
        $bytes = New-Object byte[] $count
        $file.Seek($Log.Position, [System.IO.SeekOrigin]::Begin) | Out-Null
        $read = $file.Read($bytes, 0, $count)
        if ($read -le 0) {
            return
        }
        $lastNewline = [Array]::LastIndexOf($bytes, [byte]10, $read - 1)
        if ($lastNewline -lt 0) {
            return
        }
        $Log.Position += $lastNewline + 1
        $text = [System.Text.Encoding]::UTF8.GetString($bytes, 0, $lastNewline + 1)
        $label = "[$($Log.Key)$(if ($Log.Stream -eq 'stdout') { ':stdout' })]"
        foreach ($line in ($text.TrimEnd("`r", "`n") -split "`r?`n")) {
            Write-Host "$label $line"
        }
    } finally {
        $file.Dispose()
    }
}

Write-Host ''
Write-Host 'Following -- Ctrl+C stops this, not the processes.' -ForegroundColor DarkGray
while ($true) {
    foreach ($log in $logs) {
        Read-NewLines -Log $log
    }
    Start-Sleep -Milliseconds 500
}

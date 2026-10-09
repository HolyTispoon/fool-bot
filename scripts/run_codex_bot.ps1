[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$RepoPath,

    [string]$Branch = 'main',

    # Restart on the tree already there. deploy.ps1 passes it, since
    # update_main_bot.ps1 has just pulled (and pulled -Branch, which a
    # second pull of main here would undo).
    [switch]$SkipPull,

    # Stop it and start nothing -- the way to take the Codex bot down on
    # purpose, since it has no Ctrl+C once it is running hidden. No pull
    # and no install either: there is nothing to start them for.
    [switch]$StopOnly
)

# Pull, install and (re)start the Codex bot -- `python codexbot.py` --
# out of this checkout, beside fool-bot and the web app. See "The Codex
# bot" in docs/design/collaboration.md, and docs/design/codex.md.
#
# Modelled line for line on run_web_app.ps1. The pull and the install
# are pull_checkout.ps1's, shared with run_web_app.ps1, and come first,
# before anything is stopped. The checkout and its .venv are fool-bot's
# and the web app's too, so pulling here leaves them running the code
# they started on until they are restarted -- pull_checkout.ps1 warns
# when it brought anything, and deploy.cmd restarts all four. The Codex
# bot is its own process with its own token and its own files, so
# either may be restarted alone.

$ErrorActionPreference = 'Stop'

$resolvedRepoPath = (Resolve-Path -LiteralPath $RepoPath).Path
$codexBotScript = Join-Path $resolvedRepoPath 'codexbot.py'
$venvPython = Join-Path $resolvedRepoPath '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $codexBotScript)) {
    throw "No Codex bot found at $codexBotScript"
}
if (-not (Test-Path -LiteralPath $venvPython)) {
    throw ("The virtual environment is missing at $venvPython. Run " +
        "update_main_bot.ps1 first -- it creates the .venv every process shares.")
}

if (-not $SkipPull -and -not $StopOnly) {
    & (Join-Path $PSScriptRoot 'pull_checkout.ps1') `
        -RepoPath $resolvedRepoPath -Branch $Branch -ProcessName 'the Codex bot'
}

$runtimeFolder = Join-Path $resolvedRepoPath 'data'
New-Item -ItemType Directory -Path $runtimeFolder -Force | Out-Null

$pidFile = Join-Path $runtimeFolder 'codexbot.pid'
$stdoutLog = Join-Path $runtimeFolder 'codexbot.stdout.log'
$stderrLog = Join-Path $runtimeFolder 'codexbot.stderr.log'

# Every `codexbot.py` run by THIS checkout's venv python, however it
# was started, plus whichever pid we wrote last time.
#
# Every one, for the same reason update_main_bot.ps1 stops every
# foolbot: a bot started by hand is invisible to a pid file, and two
# processes on one token is the "one bot per token" failure -- each
# answers some of the interactions, and each loads and rewrites the
# Codex games file over the other's.
#
# Matched on `codexbot\.py` in the command line and on the venv's
# python, so a Codex bot run out of a different checkout is left
# alone. The name carries no `foolbot.py`, so update_main_bot.ps1's
# `foolbot\.py` filter neither stops nor counts it, and this filter
# never matches a foolbot or `-m webapp`. As with the web app, the venv
# python is a redirector that runs the base interpreter as a child;
# this match catches the redirector, one per bot, and the interpreter
# dies with it.
function Get-RepositoryCodexBots {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PythonPath,

        [int]$AlsoIncludePid = 0
    )

    @(
        Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $null -ne $_.CommandLine -and
            $_.Name -match '^pythonw?\.exe$' -and
            $_.CommandLine -match 'codexbot\.py' -and
            (
                $_.ProcessId -eq $AlsoIncludePid -or
                (
                    $null -ne $_.ExecutablePath -and
                    [System.IO.Path]::GetFullPath($_.ExecutablePath) -eq $PythonPath
                )
            )
        }
    )
}

$normalizedPythonPath = [System.IO.Path]::GetFullPath($venvPython)

# As in update_main_bot.ps1, the pid we wrote last time is a second
# source beside the command-line match.
$savedPid = 0
if (Test-Path -LiteralPath $pidFile) {
    $rawPid = (Get-Content -LiteralPath $pidFile -Raw).Trim()
    if (-not [int]::TryParse($rawPid, [ref]$savedPid)) {
        $savedPid = 0
    }
}

$runningCodexBots = Get-RepositoryCodexBots `
    -PythonPath $normalizedPythonPath `
    -AlsoIncludePid $savedPid

foreach ($codexBot in $runningCodexBots) {
    Write-Host "Stopping Codex bot process $($codexBot.ProcessId)..."
    Stop-Process -Id $codexBot.ProcessId -Force -ErrorAction SilentlyContinue
    Wait-Process -Id $codexBot.ProcessId -Timeout 15 -ErrorAction SilentlyContinue
}

if ($runningCodexBots.Count -gt 1) {
    $stoppedCount = $runningCodexBots.Count
    Write-Warning (
        "Stopped $stoppedCount Codex bot processes -- there should only " +
        "ever be one per token."
    )
}

$survivingCodexBots = Get-RepositoryCodexBots `
    -PythonPath $normalizedPythonPath `
    -AlsoIncludePid $savedPid

if ($survivingCodexBots.Count -gt 0) {
    $survivorIds = ($survivingCodexBots | ForEach-Object { $_.ProcessId }) -join ', '
    throw ("Could not stop every Codex bot for this repository (still " +
        "running: $survivorIds). Not starting another one. Stop them " +
        "by hand and run this again.")
}

Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue

if ($StopOnly) {
    Write-Host 'Codex bot stopped.'
    return
}

# A checkout with no Codex token runs no Codex bot, as one with no
# tunnel token runs no tunnel (run_tunnel.ps1): one application, one
# token, one Codex bot, so a deploy on a checkout that has never been
# given it goes on to the web app rather than stopping here. Only
# whether it is there is read -- the bot reads its own value from .env.
$hasToken = [bool]$env:CODEX_DISCORD_TOKEN
$envFile = Join-Path $resolvedRepoPath '.env'
if (-not $hasToken -and (Test-Path -LiteralPath $envFile)) {
    foreach ($line in Get-Content -LiteralPath $envFile) {
        if ($line -match '^\s*(?:export\s+)?CODEX_DISCORD_TOKEN\s*=\s*(.*?)\s*$' -and
            $Matches[1].Trim('"', "'")) {
            $hasToken = $true
        }
    }
}
if (-not $hasToken) {
    Write-Warning ("No CODEX_DISCORD_TOKEN in $envFile -- not starting " +
        "the Codex bot. See 'The Codex bot' in docs/design/collaboration.md.")
    return
}

Remove-Item -LiteralPath $stdoutLog -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $stderrLog -Force -ErrorAction SilentlyContinue

Write-Host 'Starting the Codex bot...'
$codexProcess = Start-Process `
    -FilePath $venvPython `
    -ArgumentList @('-u', ('"{0}"' -f $codexBotScript)) `
    -WorkingDirectory $resolvedRepoPath `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdoutLog `
    -RedirectStandardError $stderrLog `
    -PassThru

Set-Content -LiteralPath $pidFile -Value $codexProcess.Id -Encoding ascii

# Long enough for the card catalog to load and the login to be tried: a
# missing CODEX_DISCORD_TOKEN or a refused one exits the process, which
# is the failure worth catching here.
Start-Sleep -Seconds 4
$codexProcess.Refresh()
if ($codexProcess.HasExited) {
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
    $errorTail = @()
    if (Test-Path -LiteralPath $stderrLog) {
        $errorTail = Get-Content -LiteralPath $stderrLog -Tail 30
    }
    throw "The Codex bot exited during startup.`n$($errorTail -join "`n")"
}

Write-Host "Codex bot running as process $($codexProcess.Id)."
Write-Host "Output log: $stdoutLog"
Write-Host "Error log:  $stderrLog"

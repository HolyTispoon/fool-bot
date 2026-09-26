[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$RepoPath,

    # Stop it and start nothing -- the way to take the web app down on
    # purpose, since it has no Ctrl+C once it is running hidden.
    [switch]$StopOnly
)

# (Re)start the D12 Ball web app -- `python -m webapp` -- out of this
# checkout, beside the bot. See "Running the web app" in
# docs/design/collaboration.md.
#
# It does not pull and does not install. The checkout and its .venv are
# the bot's too, and update_main_bot.ps1 is what moves them: pulling
# here would leave the bot running code older than the tree it was
# started from, which is the "fixed on the Mac, not on K:\" confusion
# with the two processes swapped. So an update is update_main_bot.ps1
# first (pull, install, restart the bot), then this (restart the web
# app on the same tree). The web app is its own process over its own
# files, so either may be restarted alone.

$ErrorActionPreference = 'Stop'

$resolvedRepoPath = (Resolve-Path -LiteralPath $RepoPath).Path
$webAppPackage = Join-Path $resolvedRepoPath 'webapp\__main__.py'
$venvPython = Join-Path $resolvedRepoPath '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $webAppPackage)) {
    throw "No web app found at $webAppPackage"
}
if (-not (Test-Path -LiteralPath $venvPython)) {
    throw ("The virtual environment is missing at $venvPython. Run " +
        "update_main_bot.ps1 first -- it creates the .venv both processes share.")
}

$runtimeFolder = Join-Path $resolvedRepoPath 'data'
New-Item -ItemType Directory -Path $runtimeFolder -Force | Out-Null

$pidFile = Join-Path $runtimeFolder 'webapp.pid'
$stdoutLog = Join-Path $runtimeFolder 'webapp.stdout.log'
$stderrLog = Join-Path $runtimeFolder 'webapp.stderr.log'

# Every `-m webapp` run by THIS checkout's venv python, however it was
# started, plus whichever pid we wrote last time.
#
# Every one, for the same reason update_main_bot.ps1 stops every
# foolbot: a web app started by hand is invisible to a pid file. Two
# web apps cannot both bind the port, so the second would die at
# startup -- but each loads data/d12ball_web_games.json once and writes
# the whole of it on every save, so one left over from before a restart
# on another port would overwrite the other's games with a stale copy
# (docs/design/web-app.md, "Its own process, its own file").
#
# Matched on the venv's python rather than a path in the command line,
# since `-m webapp` carries none; a web app run out of a different
# checkout, or by a different python, is left alone. The foolbot filter
# in update_main_bot.ps1 matches `foolbot\.py`, so neither script ever
# stops the other's process. The venv python is a redirector that runs
# the base interpreter as a child (see Get-FoolBotRoots there); this
# match catches the redirector alone, which is one per web app, and the
# interpreter dies with it.
function Get-RepositoryWebApps {
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
            $_.CommandLine -match '-m\s+webapp(\s|$)' -and
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

$runningWebApps = Get-RepositoryWebApps `
    -PythonPath $normalizedPythonPath `
    -AlsoIncludePid $savedPid

foreach ($webApp in $runningWebApps) {
    Write-Host "Stopping web app process $($webApp.ProcessId)..."
    Stop-Process -Id $webApp.ProcessId -Force -ErrorAction SilentlyContinue
    Wait-Process -Id $webApp.ProcessId -Timeout 15 -ErrorAction SilentlyContinue
}

if ($runningWebApps.Count -gt 1) {
    $stoppedCount = $runningWebApps.Count
    Write-Warning (
        "Stopped $stoppedCount web app processes -- there should only " +
        "ever be one. Each writes the whole of the web games file over " +
        "the others'."
    )
}

$survivingWebApps = Get-RepositoryWebApps `
    -PythonPath $normalizedPythonPath `
    -AlsoIncludePid $savedPid

if ($survivingWebApps.Count -gt 0) {
    $survivorIds = ($survivingWebApps | ForEach-Object { $_.ProcessId }) -join ', '
    throw ("Could not stop every web app for this repository (still " +
        "running: $survivorIds). Not starting another one. Stop them " +
        "by hand and run this again.")
}

Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue

if ($StopOnly) {
    Write-Host 'Web app stopped.'
    return
}

Remove-Item -LiteralPath $stdoutLog -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $stderrLog -Force -ErrorAction SilentlyContinue

Write-Host 'Starting the web app...'
$webProcess = Start-Process `
    -FilePath $venvPython `
    -ArgumentList @('-u', '-m', 'webapp') `
    -WorkingDirectory $resolvedRepoPath `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdoutLog `
    -RedirectStandardError $stderrLog `
    -PassThru

Set-Content -LiteralPath $pidFile -Value $webProcess.Id -Encoding ascii

# Long enough for the catalogs to load and the port to bind: a port
# already in use raises out of main, which is the failure worth
# catching here.
Start-Sleep -Seconds 4
$webProcess.Refresh()
if ($webProcess.HasExited) {
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
    $errorTail = @()
    if (Test-Path -LiteralPath $stderrLog) {
        $errorTail = Get-Content -LiteralPath $stderrLog -Tail 30
    }
    throw "The web app exited during startup.`n$($errorTail -join "`n")"
}

Write-Host "Web app running as process $($webProcess.Id)."
Write-Host "Output log: $stdoutLog"
Write-Host "Error log:  $stderrLog"

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$RepoPath,

    [string]$Branch = 'main',

    [switch]$SkipPull
)

$ErrorActionPreference = 'Stop'

function Invoke-CheckedCommand {
    param(
        [Parameter(Mandatory = $true)]
        [scriptblock]$Command,

        [Parameter(Mandatory = $true)]
        [string]$FailureMessage
    )

    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw $FailureMessage
    }
}

$resolvedRepoPath = (Resolve-Path -LiteralPath $RepoPath).Path
$botScript = Join-Path $resolvedRepoPath 'foolbot.py'
$requirementsFile = Join-Path $resolvedRepoPath 'requirements.txt'
$gitFolder = Join-Path $resolvedRepoPath '.git'

if (-not (Test-Path -LiteralPath $gitFolder)) {
    throw "No Git repository found at $resolvedRepoPath"
}
if (-not (Test-Path -LiteralPath $botScript)) {
    throw "foolbot.py was not found at $botScript"
}
if (-not (Test-Path -LiteralPath $requirementsFile)) {
    throw "requirements.txt was not found at $requirementsFile"
}

Set-Location -LiteralPath $resolvedRepoPath

if (-not $SkipPull) {
    $trackedChanges = & git status --porcelain --untracked-files=no
    if ($LASTEXITCODE -ne 0) {
        throw 'Could not inspect the main bot repository.'
    }
    if ($trackedChanges) {
        throw 'The main bot has uncommitted tracked changes. Update cancelled.'
    }

    Invoke-CheckedCommand -FailureMessage "Could not fetch origin/$Branch." -Command {
        git fetch origin $Branch
    }

    $currentBranch = & git branch --show-current
    if ($LASTEXITCODE -ne 0) {
        throw 'Could not determine the current Git branch.'
    }
    if ($currentBranch -ne $Branch) {
        Invoke-CheckedCommand -FailureMessage "Could not check out $Branch." -Command {
            git checkout $Branch
        }
    }

    Invoke-CheckedCommand -FailureMessage "Could not fast-forward $Branch." -Command {
        git pull --ff-only origin $Branch
    }
}

$venvPython = Join-Path $resolvedRepoPath '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) {
    $pythonLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($null -eq $pythonLauncher) {
        throw 'The virtual environment is missing and the py launcher was not found.'
    }

    Write-Host 'Creating the main bot virtual environment...'
    Invoke-CheckedCommand -FailureMessage 'Could not create the virtual environment.' -Command {
        py -3 -m venv (Join-Path $resolvedRepoPath '.venv')
    }
}

Write-Host 'Installing the current Python requirements...'
Invoke-CheckedCommand -FailureMessage 'Could not install Python requirements.' -Command {
    & $venvPython -m pip install --disable-pip-version-check -r $requirementsFile
}

$runtimeFolder = Join-Path $resolvedRepoPath 'data'
New-Item -ItemType Directory -Path $runtimeFolder -Force | Out-Null

$pidFile = Join-Path $runtimeFolder 'foolbot-main.pid'
$stdoutLog = Join-Path $runtimeFolder 'foolbot-main.stdout.log'
$stderrLog = Join-Path $runtimeFolder 'foolbot-main.stderr.log'

# Every foolbot.py belonging to THIS checkout, however it was started.
#
# It has to be *every* one of them. This used to stop a single process
# -- whichever the pid file named, or the first that matched -- and
# then start a fresh one, so a bot somebody had started by hand was
# invisible to the pid file and survived the restart. Two runs
# alongside one hand-started bot leaves three signed in on the same
# token, and Discord delivers each interaction to all of them: one
# answers and the rest fail with "Unknown interaction" (10062), out of
# the first line of whatever command was run. Four had accumulated on
# the live host before anybody worked out what they were looking at,
# each holding its own copy of the games and writing the whole of
# data/d12ball_games.json over the others.
#
# Matched on this repository's own venv python or the full path to its
# foolbot.py, so a bot run out of a different checkout is left alone --
# both developers run one. A hand-started bot has a bare "foolbot.py"
# on its command line and is only ever caught by the first of those.
function Get-RepositoryFoolBots {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PythonPath,

        [Parameter(Mandatory = $true)]
        [string]$ScriptPath,

        [int]$AlsoIncludePid = 0
    )

    @(
        Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $null -ne $_.CommandLine -and
            $_.Name -match '^pythonw?\.exe$' -and
            $_.CommandLine -match 'foolbot\.py' -and
            (
                $_.ProcessId -eq $AlsoIncludePid -or
                $_.CommandLine.Contains($ScriptPath) -or
                (
                    $null -ne $_.ExecutablePath -and
                    [System.IO.Path]::GetFullPath($_.ExecutablePath) -eq $PythonPath
                )
            )
        }
    )
}

# One bot is two of those processes. A Windows venv's python.exe is a
# redirector, not an interpreter (Python 3.7.2, bpo-34977): it reads
# pyvenv.cfg, starts the base python.exe with the same command line as
# its child, in a job that dies with it, and waits. The redirector
# matches above on the venv python, the interpreter on the full path to
# foolbot.py it was handed -- so every run of this script warned that
# it had stopped two bots when it had stopped one. A bot is counted as
# a process tree: a match whose parent is not itself a match. Every
# match is still stopped, since the interpreter is the one signed in.
function Get-FoolBotRoots {
    param(
        [object[]]$Processes = @()
    )

    $matchedIds = @($Processes | ForEach-Object { $_.ProcessId })
    @($Processes | Where-Object { $matchedIds -notcontains $_.ParentProcessId })
}

$normalizedPythonPath = [System.IO.Path]::GetFullPath($venvPython)
$normalizedBotScript = [System.IO.Path]::GetFullPath($botScript)

# The pid file is kept as a second source rather than as the answer.
# Win32_Process reports no CommandLine for a process owned by another
# user, and one we cannot read is one the filter above cannot match --
# so the pid we wrote ourselves is the way that bot still gets stopped.
$savedPid = 0
if (Test-Path -LiteralPath $pidFile) {
    $rawPid = (Get-Content -LiteralPath $pidFile -Raw).Trim()
    if (-not [int]::TryParse($rawPid, [ref]$savedPid)) {
        $savedPid = 0
    }
}

$runningFoolBots = Get-RepositoryFoolBots `
    -PythonPath $normalizedPythonPath `
    -ScriptPath $normalizedBotScript `
    -AlsoIncludePid $savedPid

$runningBots = Get-FoolBotRoots -Processes $runningFoolBots

foreach ($foolBot in $runningBots) {
    Write-Host "Stopping Fool bot process $($foolBot.ProcessId)..."
}
foreach ($foolBot in $runningFoolBots) {
    Stop-Process -Id $foolBot.ProcessId -Force -ErrorAction SilentlyContinue
    Wait-Process -Id $foolBot.ProcessId -Timeout 15 -ErrorAction SilentlyContinue
}

if ($runningBots.Count -gt 1) {
    # Interpolated, not -f: the format operator binds tighter than +,
    # so a placeholder in the first line of a concatenation is never
    # the string -f is applied to, and prints as "{0}".
    $stoppedCount = $runningBots.Count
    Write-Warning (
        "Stopped $stoppedCount Fool bot processes -- there should only " +
        "ever be one. A second bot signed in on the same token answers " +
        "the same interactions and overwrites the others' saved games."
    )
}

# Refuse to start rather than add to a pile. No bot at all is a state
# somebody notices and fixes; a second one is the failure this whole
# change is about, and it hides.
$survivingFoolBots = Get-RepositoryFoolBots `
    -PythonPath $normalizedPythonPath `
    -ScriptPath $normalizedBotScript `
    -AlsoIncludePid $savedPid

if ($survivingFoolBots.Count -gt 0) {
    $survivorIds = ($survivingFoolBots | ForEach-Object { $_.ProcessId }) -join ', '
    throw ("Could not stop every Fool bot for this repository (still " +
        "running: $survivorIds). Not starting another one -- two bots " +
        "on one token answer the same interaction and overwrite each " +
        "other's saved games. Stop them by hand and run this again.")
}

Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $stdoutLog -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $stderrLog -Force -ErrorAction SilentlyContinue

Write-Host 'Starting the Fool bot...'
$botProcess = Start-Process `
    -FilePath $venvPython `
    -ArgumentList @('-u', ('"{0}"' -f $botScript)) `
    -WorkingDirectory $resolvedRepoPath `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdoutLog `
    -RedirectStandardError $stderrLog `
    -PassThru

Set-Content -LiteralPath $pidFile -Value $botProcess.Id -Encoding ascii

Start-Sleep -Seconds 4
$botProcess.Refresh()
if ($botProcess.HasExited) {
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
    $errorTail = @()
    if (Test-Path -LiteralPath $stderrLog) {
        $errorTail = Get-Content -LiteralPath $stderrLog -Tail 30
    }
    throw "The Fool bot exited during startup.`n$($errorTail -join "`n")"
}

Write-Host "Fool bot updated and running as process $($botProcess.Id)."
Write-Host "Output log: $stdoutLog"
Write-Host "Error log:  $stderrLog"

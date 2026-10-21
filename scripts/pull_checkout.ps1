[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$RepoPath,

    [string]$Branch = 'main',

    # Which process is pulling, for the warning: "the Codex bot".
    [Parameter(Mandatory = $true)]
    [string]$ProcessName
)

# Pull and install for a script that restarts one process alone --
# run_codex_bot.ps1 and run_web_app.ps1 -- so restarting it picks up new
# code. The steps are update_main_bot.ps1's: refuse a checkout with
# uncommitted tracked changes, fetch, check out $Branch, fast-forward,
# then pip against requirements.txt, which touches nothing already
# satisfied. Throws on any failure, before the caller has stopped
# anything, so a failed pull leaves the running process running.
#
# The checkout and its .venv are shared by every process on it, so a
# pull here moves the tree under the others while they keep running the
# code they started on. That is the cost of restarting one alone; the
# warning at the end says so whenever the pull brought anything, and
# deploy.cmd is what restarts all four on it. See "Keeping it running"
# in docs/design/collaboration.md.

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
$gitFolder = Join-Path $resolvedRepoPath '.git'
$requirementsFile = Join-Path $resolvedRepoPath 'requirements.txt'
$venvPython = Join-Path $resolvedRepoPath '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $gitFolder)) {
    throw "No Git repository found at $resolvedRepoPath"
}
if (-not (Test-Path -LiteralPath $venvPython)) {
    throw ("The virtual environment is missing at $venvPython. Run " +
        "update_main_bot.ps1 first -- it creates the .venv every process shares.")
}

Set-Location -LiteralPath $resolvedRepoPath

$trackedChanges = & git status --porcelain --untracked-files=no
if ($LASTEXITCODE -ne 0) {
    throw 'Could not inspect the repository.'
}
if ($trackedChanges) {
    throw 'The checkout has uncommitted tracked changes. Update cancelled.'
}

$headBefore = & git rev-parse HEAD
if ($LASTEXITCODE -ne 0) {
    throw 'Could not read the current commit.'
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

$headAfter = & git rev-parse HEAD
if ($LASTEXITCODE -ne 0) {
    throw 'Could not read the current commit.'
}

Write-Host 'Installing the current Python requirements...'
Invoke-CheckedCommand -FailureMessage 'Could not install Python requirements.' -Command {
    & $venvPython -m pip install --disable-pip-version-check -r $requirementsFile
}

if ($headAfter -ne $headBefore) {
    Write-Warning ("Pulled new code for $ProcessName. Everything else on " +
        "this checkout is still running the code from before it; " +
        ".\scripts\deploy.cmd restarts all four on it.")
}

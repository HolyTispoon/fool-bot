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

# Google Drive writes a hidden desktop.ini into the folders it syncs,
# .git\refs\ and every folder under it included, and git reads every
# file under refs\ as a ref. The fetch then dies on the first of them
# ("fatal: bad object refs/desktop.ini", reported as "did not send all
# necessary objects") before anything here has been stopped. They are
# Drive's folder-icon metadata, nothing git wrote, and Drive writes them
# again, so they are removed before every fetch rather than once. The
# working tree's are left alone: untracked, and the dirty check before
# the fetch ignores untracked files. See "The K:\ drive is a mounted
# Google Drive letter" in docs/design/collaboration.md.
function Remove-GoogleDriveDesktopIni {
    param(
        [Parameter(Mandatory = $true)]
        [string]$GitFolder
    )

    $strays = @(Get-ChildItem -LiteralPath $GitFolder -Recurse -Force -File -Filter 'desktop.ini' -ErrorAction SilentlyContinue)
    foreach ($stray in $strays) {
        Write-Host "Removing $($stray.FullName) -- Google Drive's, which git would read as a ref."
        Remove-Item -LiteralPath $stray.FullName -Force
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

Remove-GoogleDriveDesktopIni -GitFolder $gitFolder

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

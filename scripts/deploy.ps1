[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$RepoPath,

    [string]$Branch = 'main',

    [switch]$SkipPull
)

# Deploy both processes on this checkout, in the order "Running the web
# app" in docs/design/collaboration.md calls for: update_main_bot.ps1
# first (pull, install, restart the bot), then run_web_app.ps1 (restart
# the web app on the same tree). Doing it the other way round would
# start the web app before the pull, leaving it on the tree from before
# this run -- the same "fixed on the Mac, not on K:\" confusion a
# missed restart causes, just for the wrong process.
#
# Nothing here duplicates either script's own logic (the process
# matching, the pid files, the exit-on-survivor checks) -- it only
# calls them in order and lets a failure in the first stop the second.

$ErrorActionPreference = 'Stop'

$resolvedRepoPath = (Resolve-Path -LiteralPath $RepoPath).Path
$scriptFolder = Join-Path $resolvedRepoPath 'scripts'

$updateArgs = @{
    RepoPath = $resolvedRepoPath
    Branch   = $Branch
}
if ($SkipPull) {
    $updateArgs['SkipPull'] = $true
}

& (Join-Path $scriptFolder 'update_main_bot.ps1') @updateArgs
& (Join-Path $scriptFolder 'run_web_app.ps1') -RepoPath $resolvedRepoPath

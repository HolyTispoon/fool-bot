[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$RepoPath,

    [string]$Branch = 'main',

    [switch]$SkipPull,

    # Stop all three and start nothing.
    [switch]$StopOnly
)

# Deploy everything on this checkout, in the order "Running the web
# app" in docs/design/collaboration.md calls for: update_main_bot.ps1
# first (pull, install, restart the bot), then run_web_app.ps1 (restart
# the web app on the same tree), then run_tunnel.ps1 (restart the
# connector that puts the web app on https://play.d12ball.com). Doing
# the first two the other way round would start the web app before the
# pull, leaving it on the tree from before this run -- the same "fixed
# on the Mac, not on K:\" confusion a missed restart causes, just for
# the wrong process. The tunnel goes last because it serves nothing
# until the web app is up, and a checkout with no tunnel token skips it.
#
# Nothing here duplicates any script's own logic (the process
# matching, the pid files, the exit-on-survivor checks) -- it only
# calls them in order and lets a failure in one stop the rest.

$ErrorActionPreference = 'Stop'

$resolvedRepoPath = (Resolve-Path -LiteralPath $RepoPath).Path
$scriptFolder = Join-Path $resolvedRepoPath 'scripts'

# Stopping goes the other way round -- the tunnel first, so nobody
# reaches a web app that is going away, and the bot last -- and tries
# every one even when an earlier one fails: a stop that gives up half
# way leaves the processes it never reached running, which is the one
# thing it was asked not to do. Each script's -StopOnly does its own
# matching; nothing is matched here.
if ($StopOnly) {
    $failures = @()
    foreach ($script in @('run_tunnel.ps1', 'run_web_app.ps1', 'update_main_bot.ps1')) {
        try {
            & (Join-Path $scriptFolder $script) -RepoPath $resolvedRepoPath -StopOnly
        } catch {
            Write-Warning "$script -StopOnly failed: $_"
            $failures += $script
        }
    }
    if ($failures.Count -gt 0) {
        throw "Could not stop everything ($($failures -join ', ') failed; see above)."
    }
    return
}

$updateArgs = @{
    RepoPath = $resolvedRepoPath
    Branch   = $Branch
}
if ($SkipPull) {
    $updateArgs['SkipPull'] = $true
}

& (Join-Path $scriptFolder 'update_main_bot.ps1') @updateArgs
& (Join-Path $scriptFolder 'run_web_app.ps1') -RepoPath $resolvedRepoPath
& (Join-Path $scriptFolder 'run_tunnel.ps1') -RepoPath $resolvedRepoPath

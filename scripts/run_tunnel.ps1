[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$RepoPath,

    # Stop it and start nothing -- the way to take the tunnel down on
    # purpose, since it has no Ctrl+C once it is running hidden.
    [switch]$StopOnly
)

# (Re)start the Cloudflare Tunnel connector -- `cloudflared tunnel run`
# -- for this checkout, so https://play.d12ball.com reaches the web app.
# See "Exposing the port" in docs/design/collaboration.md.
#
# The tunnel itself, and its public hostname, live in Cloudflare and
# outlive any machine; what dies with a reboot is the connector, this
# process. It is run the way run_web_app.ps1 runs the web app rather
# than as a Windows service: the web app cannot start before somebody
# logs in (K:\ is mounted per user), so a connector that could is no
# use, and a service needs an administrator to install and to start,
# which a deploy over SSH does not have. (On 2026-09-30 the service
# did not come back after a reboot, and play.d12ball.com answered
# 1033 for days.)
#
# The token is a credential. It is read from FOOLBOT_TUNNEL_TOKEN in
# the checkout's .env (or the environment) and handed to cloudflared as
# TUNNEL_TOKEN in its environment -- never on its command line, which
# any process on the machine can read. A checkout with no token runs no
# tunnel: one tunnel's connector belongs on the live host alone, the
# way one bot belongs to one Discord token.

$ErrorActionPreference = 'Stop'

$resolvedRepoPath = (Resolve-Path -LiteralPath $RepoPath).Path

$runtimeFolder = Join-Path $resolvedRepoPath 'data'
New-Item -ItemType Directory -Path $runtimeFolder -Force | Out-Null

# cloudflared writes this itself, and only after its first successful
# connection to Cloudflare -- so it is both the pid of the last one and
# the proof that it connected. Its path is also what identifies this
# checkout's connector on a command line (see Get-RepositoryTunnels).
$pidFile = Join-Path $runtimeFolder 'tunnel.pid'
$stdoutLog = Join-Path $runtimeFolder 'tunnel.stdout.log'
$stderrLog = Join-Path $runtimeFolder 'tunnel.stderr.log'

# Every cloudflared whose command line names THIS checkout's pid file,
# plus whichever pid that file holds. A connector run any other way --
# the Windows service, one started by hand, another checkout's -- is
# left alone: its command line names no file of ours.
function Get-RepositoryTunnels {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PidFilePath,

        [int]$AlsoIncludePid = 0
    )

    @(
        Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Name -eq 'cloudflared.exe' -and
            (
                $_.ProcessId -eq $AlsoIncludePid -or
                (
                    $null -ne $_.CommandLine -and
                    $_.CommandLine.Contains($PidFilePath)
                )
            )
        }
    )
}

$savedPid = 0
if (Test-Path -LiteralPath $pidFile) {
    $rawPid = (Get-Content -LiteralPath $pidFile -Raw).Trim()
    if (-not [int]::TryParse($rawPid, [ref]$savedPid)) {
        $savedPid = 0
    }
}

$runningTunnels = Get-RepositoryTunnels -PidFilePath $pidFile -AlsoIncludePid $savedPid

foreach ($tunnel in $runningTunnels) {
    Write-Host "Stopping tunnel process $($tunnel.ProcessId)..."
    Stop-Process -Id $tunnel.ProcessId -Force -ErrorAction SilentlyContinue
    Wait-Process -Id $tunnel.ProcessId -Timeout 15 -ErrorAction SilentlyContinue
}

$survivingTunnels = Get-RepositoryTunnels -PidFilePath $pidFile -AlsoIncludePid $savedPid

if ($survivingTunnels.Count -gt 0) {
    $survivorIds = ($survivingTunnels | ForEach-Object { $_.ProcessId }) -join ', '
    throw ("Could not stop every tunnel for this repository (still " +
        "running: $survivorIds). Not starting another one. Stop them " +
        "by hand and run this again.")
}

Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue

if ($StopOnly) {
    Write-Host 'Tunnel stopped.'
    return
}

# The token: the environment first, then the checkout's .env, read the
# way python-dotenv reads a plain KEY=value line.
$token = $env:FOOLBOT_TUNNEL_TOKEN
$envFile = Join-Path $resolvedRepoPath '.env'
if (-not $token -and (Test-Path -LiteralPath $envFile)) {
    foreach ($line in Get-Content -LiteralPath $envFile) {
        if ($line -match '^\s*(?:export\s+)?FOOLBOT_TUNNEL_TOKEN\s*=\s*(.*?)\s*$') {
            $token = $Matches[1].Trim('"', "'")
        }
    }
}
if (-not $token) {
    Write-Warning ("No FOOLBOT_TUNNEL_TOKEN in $envFile -- not starting " +
        "a tunnel. Only the live host runs one; see 'Exposing the port' " +
        "in docs/design/collaboration.md.")
    return
}

$cloudflared = $null
$onPath = Get-Command 'cloudflared.exe' -ErrorAction SilentlyContinue
if ($onPath) {
    $cloudflared = $onPath.Source
} else {
    # Where winget puts it, for a shell opened before the install
    # reached PATH.
    foreach ($folder in @(${env:ProgramFiles(x86)}, $env:ProgramFiles)) {
        if (-not $folder) { continue }
        $candidate = Join-Path $folder 'cloudflared\cloudflared.exe'
        if (Test-Path -LiteralPath $candidate) {
            $cloudflared = $candidate
            break
        }
    }
}
if (-not $cloudflared) {
    throw ("cloudflared is not installed. From an administrator " +
        "PowerShell: winget install --id Cloudflare.cloudflared")
}

# A Windows service from the old setup is a second connector to the
# same tunnel. Cloudflare takes both (they are replicas), so it is not
# an error -- but it is the thing that went quiet after a reboot, and
# two of them is how one comes to be forgotten.
$service = Get-Service -Name 'cloudflared' -ErrorAction SilentlyContinue
if ($service) {
    Write-Warning ("A cloudflared Windows service is installed too " +
        "($($service.Status)). This script replaces it; remove it from " +
        "an administrator PowerShell with: cloudflared.exe service uninstall")
}

Remove-Item -LiteralPath $stdoutLog -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $stderrLog -Force -ErrorAction SilentlyContinue

Write-Host 'Starting the tunnel...'
# Start-Process hands the child this process's environment, so the
# token goes in for the one call and comes straight back out.
$env:TUNNEL_TOKEN = $token
try {
    $tunnelProcess = Start-Process `
        -FilePath $cloudflared `
        -ArgumentList @('tunnel', '--no-autoupdate', '--pidfile', "`"$pidFile`"", 'run') `
        -WorkingDirectory $resolvedRepoPath `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdoutLog `
        -RedirectStandardError $stderrLog `
        -PassThru
} finally {
    Remove-Item Env:TUNNEL_TOKEN -ErrorAction SilentlyContinue
}

# Wait for it to connect: cloudflared writes the pid file once a
# connection to Cloudflare is up, and logs "Registered tunnel
# connection" for each one -- either will do, so a build that is quiet
# about one is not mistaken for a tunnel that never connected. Neither
# after this long is a tunnel that is not serving, whether or not the
# process is still alive.
function Test-TunnelConnected {
    if (Test-Path -LiteralPath $pidFile) {
        return $true
    }
    if (Test-Path -LiteralPath $stderrLog) {
        $logged = Select-String -LiteralPath $stderrLog `
            -SimpleMatch 'Registered tunnel connection' -Quiet `
            -ErrorAction SilentlyContinue
        if ($logged) {
            return $true
        }
    }
    return $false
}

$connected = $false
$deadline = (Get-Date).AddSeconds(30)
while ((Get-Date) -lt $deadline) {
    if (Test-TunnelConnected) {
        $connected = $true
        break
    }
    $tunnelProcess.Refresh()
    if ($tunnelProcess.HasExited) {
        break
    }
    Start-Sleep -Milliseconds 500
}

if (-not $connected) {
    $errorTail = @()
    if (Test-Path -LiteralPath $stderrLog) {
        $errorTail = Get-Content -LiteralPath $stderrLog -Tail 30
    }
    $tunnelProcess.Refresh()
    if ($tunnelProcess.HasExited) {
        throw "The tunnel exited before it connected.`n$($errorTail -join "`n")"
    }
    throw ("The tunnel has not connected after 30 seconds. It is still " +
        "running as process $($tunnelProcess.Id) and retrying; stop it " +
        "with run_tunnel.cmd -StopOnly.`n$($errorTail -join "`n")")
}

Write-Host "Tunnel connected, running as process $($tunnelProcess.Id)."
Write-Host "Error log:  $stderrLog"

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

$processToStop = $null
if (Test-Path -LiteralPath $pidFile) {
    $savedPid = 0
    $rawPid = (Get-Content -LiteralPath $pidFile -Raw).Trim()
    if ([int]::TryParse($rawPid, [ref]$savedPid)) {
        $candidate = Get-CimInstance Win32_Process -Filter "ProcessId = $savedPid" -ErrorAction SilentlyContinue
        if ($null -ne $candidate -and $candidate.CommandLine -match 'foolbot\.py') {
            $processToStop = $candidate
        }
    }
}

if ($null -eq $processToStop) {
    $normalizedPythonPath = [System.IO.Path]::GetFullPath($venvPython)
    $runningFoolBots = @(
        Get-CimInstance Win32_Process |
        Where-Object {
            $_.Name -match '^pythonw?\.exe$' -and
            $_.CommandLine -match 'foolbot\.py' -and
            $null -ne $_.ExecutablePath
        }
    )

    $processToStop = $runningFoolBots |
        Where-Object {
            [System.IO.Path]::GetFullPath($_.ExecutablePath) -eq $normalizedPythonPath
        } |
        Select-Object -First 1

    if ($null -eq $processToStop -and $runningFoolBots.Count -eq 1) {
        $processToStop = $runningFoolBots[0]
    }
    elseif ($null -eq $processToStop -and $runningFoolBots.Count -gt 1) {
        throw 'Multiple foolbot.py processes are running and none matches this repository virtual environment. Stop the main bot manually once, then retry.'
    }
}

if ($null -ne $processToStop) {
    Write-Host "Stopping Fool bot process $($processToStop.ProcessId)..."
    Stop-Process -Id $processToStop.ProcessId -Force
    Wait-Process -Id $processToStop.ProcessId -Timeout 15 -ErrorAction SilentlyContinue
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

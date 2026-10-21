#!/usr/bin/env bash

set -euo pipefail

usage() {
    cat <<'EOF'
Usage:
  ./scripts/update-main-bot.sh USER@WINDOWS_PC 'C:\path\to\fool-bot' [branch]

You can also set these environment variables instead of passing arguments:
  FOOLBOT_MAIN_TARGET   SSH target, such as Admin@foolbot-pc
  FOOLBOT_MAIN_REPO     Full Windows path to the repository
  FOOLBOT_MAIN_BRANCH   Branch to deploy (default: main)

The Windows PC must have OpenSSH Server enabled and Git available in PATH.
EOF
}

target="${1:-${FOOLBOT_MAIN_TARGET:-}}"
repo_path="${2:-${FOOLBOT_MAIN_REPO:-}}"
branch="${3:-${FOOLBOT_MAIN_BRANCH:-main}}"

if [[ -z "$target" || -z "$repo_path" ]]; then
    usage >&2
    exit 2
fi

for required_command in ssh iconv base64 sed; do
    if ! command -v "$required_command" >/dev/null 2>&1; then
        echo "Required command not found: $required_command" >&2
        exit 1
    fi
done

escape_powershell_string() {
    printf '%s' "$1" | sed "s/'/''/g"
}

escaped_repo_path="$(escape_powershell_string "$repo_path")"
escaped_branch="$(escape_powershell_string "$branch")"

read -r -d '' powershell_command <<EOF || true
\$ErrorActionPreference = 'Stop'
\$repoPath = '$escaped_repo_path'
\$branch = '$escaped_branch'

if (-not (Test-Path -LiteralPath (Join-Path \$repoPath '.git'))) {
    throw "No Git repository found at \$repoPath"
}

Set-Location -LiteralPath \$repoPath

\$trackedChanges = & git status --porcelain --untracked-files=no
if (\$LASTEXITCODE -ne 0) {
    throw 'Could not inspect the main bot repository.'
}
if (\$trackedChanges) {
    throw 'The main bot has uncommitted tracked changes. Update cancelled.'
}

& git fetch origin \$branch
if (\$LASTEXITCODE -ne 0) {
    throw "Could not fetch origin/\$branch."
}

\$currentBranch = & git branch --show-current
if (\$LASTEXITCODE -ne 0) {
    throw 'Could not determine the current Git branch.'
}
if (\$currentBranch -ne \$branch) {
    & git checkout \$branch
    if (\$LASTEXITCODE -ne 0) {
        throw "Could not check out \$branch."
    }
}

& git pull --ff-only origin \$branch
if (\$LASTEXITCODE -ne 0) {
    throw "Could not fast-forward \$branch."
}

\$restartScript = Join-Path \$repoPath 'scripts\update_main_bot.ps1'
if (-not (Test-Path -LiteralPath \$restartScript)) {
    throw "The restart helper was not found at \$restartScript"
}

& \$restartScript -RepoPath \$repoPath -Branch \$branch -SkipPull
EOF

encoded_command="$({
    printf '%s' "$powershell_command" \
        | iconv -f UTF-8 -t UTF-16LE \
        | base64 \
        | tr -d '\r\n'
})"

echo "Updating and restarting the Fool bot on $target..."
ssh "$target" \
    "powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand $encoded_command"

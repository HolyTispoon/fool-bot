@echo off
rem Restart the Codex bot: run_codex_bot.cmd [-StopOnly]
rem Runs scripts\run_codex_bot.ps1 with -ExecutionPolicy Bypass, so Windows
rem does not refuse it for being unsigned (the checkout is on the
rem Google Drive letter, which RemoteSigned treats as remote). It
rem lifts the policy for this one run and changes no setting. The
rem checkout is the folder above this one; pass the script's other
rem options after it. See docs/design/collaboration.md.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_codex_bot.ps1" -RepoPath "%~dp0.." %*
exit /b %ERRORLEVEL%

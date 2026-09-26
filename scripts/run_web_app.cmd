@echo off
rem Restart the web app: run_web_app.cmd [-StopOnly]
rem Runs scripts\run_web_app.ps1 with -ExecutionPolicy Bypass, so Windows
rem does not refuse it for being unsigned (the checkout is on the
rem Google Drive letter, which RemoteSigned treats as remote). It
rem lifts the policy for this one run and changes no setting. The
rem checkout is the folder above this one; pass the script's other
rem options after it. See docs/design/collaboration.md.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_web_app.ps1" -RepoPath "%~dp0.." %*
exit /b %ERRORLEVEL%

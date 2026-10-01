@echo off
rem Update and restart everything: deploy.cmd [-Branch name] [-SkipPull]
rem Runs update_main_bot, run_web_app and run_tunnel, in that order --
rem see "Running the web app" in docs/design/collaboration.md. Stops at
rem the first that fails, so the web app is never restarted onto a
rem half-updated tree.
rem Runs scripts\deploy.ps1 with -ExecutionPolicy Bypass, so Windows
rem does not refuse it for being unsigned (the checkout is on the
rem Google Drive letter, which RemoteSigned treats as remote). It
rem lifts the policy for this one run and changes no setting. The
rem checkout is the folder above this one; pass the script's other
rem options after it. See docs/design/collaboration.md.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy.ps1" -RepoPath "%~dp0.." %*
exit /b %ERRORLEVEL%

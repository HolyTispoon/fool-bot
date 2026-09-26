@echo off
rem Pull, install and restart the bot: update_main_bot.cmd [-Branch name] [-SkipPull]
rem Runs scripts\update_main_bot.ps1 with -ExecutionPolicy Bypass, so Windows
rem does not refuse it for being unsigned (the checkout is on the
rem Google Drive letter, which RemoteSigned treats as remote). It
rem lifts the policy for this one run and changes no setting. The
rem checkout is the folder above this one; pass the script's other
rem options after it. See docs/design/collaboration.md.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0update_main_bot.ps1" -RepoPath "%~dp0.." %*
exit /b %ERRORLEVEL%

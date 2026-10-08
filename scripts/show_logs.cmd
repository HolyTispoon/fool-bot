@echo off
rem Show the logs: show_logs.cmd [all|bot|webapp|tunnel] [-Tail n] [-Follow]
rem Prints the last lines of each process's stderr and stdout logs in
rem data\, under a heading saying whether it is running; -Follow then
rem keeps printing until Ctrl+C, which stops only this.
rem Runs scripts\show_logs.ps1 with -ExecutionPolicy Bypass, so Windows
rem does not refuse it for being unsigned (the checkout is on the
rem Google Drive letter, which RemoteSigned treats as remote). It
rem lifts the policy for this one run and changes no setting. The
rem checkout is the folder above this one; pass the script's other
rem options after it. See docs/design/collaboration.md.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0show_logs.ps1" -RepoPath "%~dp0.." %*
exit /b %ERRORLEVEL%

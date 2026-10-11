# Running the bot on Windows

These are the `.cmd` launchers that run the bot, the Codex bot, the web
app and the tunnel on the Windows host. Run them from the checkout's root folder,
in PowerShell or `cmd.exe`. Always use the `.cmd` and never the `.ps1`
beside it: the launcher is what gets the script past Windows' execution
policy. (The Python tools in this folder are something else; each one
explains itself with `--help`.)

Every process runs hidden, so Ctrl+C can't stop any of them. Stop them
with `-StopOnly` and read their output with `show_logs.cmd`.

## Start and update

| Command | What it does |
| --- | --- |
| `.\scripts\deploy.cmd` | Pulls `main`, installs requirements, and restarts the bot, then the Codex bot, then the web app, then the tunnel |
| `.\scripts\deploy.cmd -SkipPull` | Restarts all four on the code already there, e.g. after a reboot |
| `.\scripts\deploy.cmd -Branch <name>` | Deploys another branch instead of `main` |
| `.\scripts\update_main_bot.cmd` | The bot alone: pulls, installs, restarts (takes `-SkipPull` and `-Branch` too) |
| `.\scripts\run_codex_bot.cmd` | The Codex bot alone: pulls, installs, restarts it (takes `-SkipPull` and `-Branch` too; `-WithFoolBot`, which `deploy.cmd` passes, leaves the change list in #logs to fool-bot). Starts nothing on a checkout whose `.env` has no `CODEX_DISCORD_TOKEN`. The other processes keep running the old code until restarted |
| `.\scripts\run_web_app.cmd` | The web app alone: pulls, installs, restarts it (takes `-SkipPull` and `-Branch` too). The other processes keep running the old code until restarted |
| `.\scripts\run_tunnel.cmd` | The tunnel alone: restarts the connector that puts the web app on play.d12ball.com. Starts nothing on a checkout whose `.env` has no `FOOLBOT_TUNNEL_TOKEN` |

Every start stops this checkout's old copy first, so running one twice
leaves one process, not two.

## Stop

| Command | What it does |
| --- | --- |
| `.\scripts\deploy.cmd -StopOnly` | Stops all four: the tunnel, then the web app, then the Codex bot, then the bot |
| `.\scripts\run_codex_bot.cmd -StopOnly` | Stops the Codex bot alone |
| `.\scripts\update_main_bot.cmd -StopOnly` | Stops the bot alone |
| `.\scripts\run_web_app.cmd -StopOnly` | Stops the web app alone |
| `.\scripts\run_tunnel.cmd -StopOnly` | Stops the tunnel alone |

Stopping leaves the logs in place. Starting a process again deletes its
old logs.

## Check and read the logs

| Command | What it does |
| --- | --- |
| `.\scripts\show_logs.cmd` | For each of the four: whether it is running, then the last 40 lines of its logs |
| `.\scripts\show_logs.cmd bot` | Just one of them: `bot`, `codex`, `webapp` or `tunnel` |
| `.\scripts\show_logs.cmd -Tail 200` | More lines |
| `.\scripts\show_logs.cmd bot -Follow` | Keeps printing new lines until Ctrl+C. Ctrl+C stops only the viewer, not the bot |

The logs are files in `data\`, two per process:

| Process | Files |
| --- | --- |
| Bot | `foolbot-main.stderr.log`, `foolbot-main.stdout.log` |
| Codex bot | `codexbot.stderr.log`, `codexbot.stdout.log` |
| Web app | `webapp.stderr.log`, `webapp.stdout.log` |
| Tunnel | `tunnel.stderr.log`, `tunnel.stdout.log` |

What a process logs goes to `stderr.log`, so `stdout.log` is usually
empty.

"Running" means the process named in the `.pid` file next to its logs is
alive. A process started by hand writes no `.pid` file, and the tunnel
writes its own only after it has connected. If the heading and what you
see disagree, list every bot, web app and tunnel process there is:

```powershell
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'foolbot\.py|-m webapp' -or $_.Name -eq 'cloudflared.exe' } | Select-Object ProcessId, ParentProcessId, Name, CommandLine | Format-List
```

The bot shows up as two `python.exe` processes, the venv's launcher and
the interpreter it starts, and that is still one bot.

## More

Why each of these works the way it does is in
[docs/design/collaboration.md](../docs/design/collaboration.md), under
"Keeping it running" and "Exposing the port".

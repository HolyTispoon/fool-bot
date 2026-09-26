# Collaboration, and the live bot

Design notes for fool-bot; the map is [CLAUDE.md](../../CLAUDE.md), the rules are [living-rules.md](../living-rules.md).

## Collaboration

Two people develop on this repo in parallel, on different machines and
different operating systems.

- **Every task starts on a fresh branch off an up-to-date `main`.** Pull
  `main` fast-forward first, then branch; never edit on `main`, and never
  continue on the previous task's branch -- it is usually merged already
  (so the new work would sit on a stale base) or still in review (so the
  new work would land in somebody else's PR).
- **Never force-push a branch that has been pushed.** The other developer may
  have it checked out and be testing against it.
- Feature branches are short-lived and land on `main` via a pull request. Don't
  set up long-lived tracking branches for code that is only being tested.
- To test someone else's branch without creating a local branch:
  ```bash
  git fetch origin <branch>
  git checkout --detach FETCH_HEAD
  # ... test ...
  git checkout main
  ```
- Assume either developer may be running the bot from the working tree at any
  time. Stop the bot before switching branches, and restart it after.

**Two of those machines are the same person's, and only one of them is the
real bot.** The Windows PC serves the live bot out of
`K:\My Drive\Prophetic Fools Games\Discord Bots\fool-bot`; the Mac is that
person's development checkout. So:

- **A traceback from a `K:\` path is the live bot, and a fix on the Mac has not
  reached it.** A change is not deployed until that checkout has pulled and the
  bot has been restarted there -- see "Fonts" in [board-image.md](board-image.md) and `render.py`'s import-time
  loading for why a restart is not optional.
- **They are two checkouts, so everything that is per checkout is separate**:
  `.env` (which is what decides whether a bot posts to `#logs` at all),
  `data/d12ball_games.json`, `data/d12ball_web_games.json` (the web app's,
  which is its own process -- see [web-app.md](web-app.md), "Its own process,
  its own file") and `data/bot_state.json`. The Mac's saved games
  are not the live bot's, so `scripts/render_sample.py --game` cannot reproduce
  a board from a game played on the server.
- **The `K:\` drive is a mounted Google Drive letter**, which is the checkout
  the swallowed-save handling in [gotchas.md](gotchas.md) was written for -- when the mount
  goes away mid-game every `save_games` raises.

**One bot per token, and `scripts/update_main_bot.ps1` is what enforces it.**
Discord lets a token hold more than one gateway session and delivers every
interaction to all of them, so a second bot on the same token is not a spare:
one of them answers and the rest fail on their own first line with
`404 ... (error code: 10062): Unknown interaction`, whichever command was run.
They also each hold their own copy of `self.games` and write the whole of
`data/d12ball_games.json` over one another, and each refresh the same board
message -- through a gate whose whole five-in-five arithmetic assumes one
writer per game (see "Discord's rate limits" in [rate-limits.md](rate-limits.md)).

- **They accumulate silently, which is how four of them ended up on the live
  host.** The updater used to stop exactly one process -- whichever the pid
  file named, or the first that matched -- and then start a fresh one, so a
  bot started by hand was invisible to it and survived every restart. It stops
  **every** foolbot belonging to that checkout now, and **refuses to start**
  if any survive: no bot at all is a state somebody notices, where a second one
  hides.
- **A hand-started bot is only ever caught by the venv path.** Its command line
  is a bare `foolbot.py` with no directory in it, so matching the full path to
  `foolbot.py` misses it -- and matching `foolbot.py` alone would stop the
  *other* developer's bot if they ran one on the same machine. The pid file is
  kept as a second source rather than as the answer, because `Win32_Process`
  reports no `CommandLine` for a process owned by another user.
- **The web app is not a foolbot to it.** `python3 -m webapp` is its own
  process with no token, so the updater's match on `foolbot.py` neither stops
  nor counts it; it is restarted on its own.
- **Read a 10062 as this first.** It is raised out of a command's first line,
  before anything of ours has run, so it can never be a bug in that command --
  see `defer_or_report` in `cogs/debug.py`, which says so in #logs rather than
  raising a traceback that names only the symptom. The other cause is a bot too
  busy to acknowledge inside three seconds; `Get-CimInstance Win32_Process`
  tells the two apart in one command.

## Running the web app

The web app is the second process on the `K:\` checkout (decision 2 of
[../web-app-next.md](../web-app-next.md)): `python3 -m webapp`, no
token, no bot, over its own files. What it is and why it is its own
process is [web-app.md](web-app.md), "Running it" and "Its own process,
its own file"; this is how it is run on the live host.

**Nothing in this section has been run on the `K:\` host or through a
tunnel.** It was written from the code and `update_main_bot.ps1` in a
Linux sandbox with no PowerShell; `scripts/run_web_app.ps1` has not
been executed anywhere, and the tunnel steps are each provider's
documented shape rather than something tried. Step 5's playtest in the
worksheet is what checks it; correct this section from what that finds.

### What it shares with the bot, and what it does not

- **Shared: the checkout, its `.venv` and `data/`.** One `git pull`
  moves both; one `pip install` serves both.
- **Separate: every file in `data/` it writes** --
  `d12ball_web_games.json`, `d12ball_web_rooms.json`,
  `d12ball_web_chat.json`, and its own `webapp.pid` and
  `webapp.*.log` -- against the bot's `d12ball_games.json`,
  `d12ball_hubs.json`, `bot_state.json` and `foolbot-main.*`. Neither
  process opens the other's files, which is what lets two processes
  share one folder safely (each store rewrites its whole file on every
  save, so two writers on one file would lose games).
- **Separate restarts.** `update_main_bot.ps1` stops and starts
  `foolbot.py` and matches nothing else, so it neither stops nor counts
  the web app; `run_web_app.ps1` matches `-m webapp` and never touches
  the bot. A web restart drops nobody from a Discord game and the
  reverse. A restart of either *after a pull* is what deploys it: a
  process runs the code it was started with, so pulling for the bot
  and not restarting the web app leaves it on the old tree.

### The `.env`

The same `.env` the bot reads (both call `load_dotenv()`), with four
more lines; the table in [web-app.md](web-app.md), "Running it", is
the reference for each.

```ini
FOOLBOT_WEB_PORT=8080
FOOLBOT_WEB_HOST=127.0.0.1
FOOLBOT_WEB_URL=https://<the tunnel's public name>
FOOLBOT_WEB_SECRET=<64 random hex characters>
```

- **`FOOLBOT_WEB_SECRET` must be set.** A person is a signed cookie and
  nothing else -- no account, nothing stored server-side
  (`webapp/identity.py`). Without a configured secret one is made per
  process, so **every restart signs everybody out and every seat's
  holder becomes a stranger to it** (an admin can hand the seat back,
  but a mid-game restart for a deploy should not need one). Make it
  once and never change it: changing it is the same as losing it.
  `python -c "import secrets; print(secrets.token_hex(32))"` makes
  one. It is a credential: `.env` is per checkout and untracked, and
  it stays that way.
- **`FOOLBOT_WEB_HOST=127.0.0.1`** when a tunnel runs on the same
  machine: the tunnel reaches the port locally, and nothing on the
  LAN can reach it over plain HTTP around the tunnel. Leave it unset
  (every interface) only to play from another device on the home
  network without a tunnel.
- **`FOOLBOT_WEB_URL` is the tunnel's public HTTPS name**, with no
  trailing slash. The server cannot learn its own public address from
  behind a tunnel, so every link it hands out (a room's, the rematch's)
  is built from this. It comes from the tunnel: the hostname chosen or
  assigned in its setup below. Left at the default, links point at
  `http://localhost:8080`, which works only on the host itself.

### Only ever over HTTPS

The cookie **is** the identity: whoever holds it holds the seat, and
it is good for a year. Over plain HTTP anybody on the path can read
it, so the page is served only through the tunnel's HTTPS name, never
by opening the port on the router, and a link is only ever shared
with the `https://` address.

**A gap the code has today:** the cookie is marked `Secure` only when
`request.secure` is true (`webapp/identity.py`, `set_cookie`), and
behind a tunnel the process sees plain HTTP from the tunnel on
localhost -- aiohttp reads a forwarded scheme only when told to, and
nothing tells it. So behind a tunnel the cookie goes out without
`Secure`, and a browser would send it on a plain `http://` request to
the same name. Until that is settled, turn on the tunnel's own
HTTP-to-HTTPS redirect where it has one (Cloudflare: "Always Use
HTTPS"; Funnel and ngrok serve HTTPS only), and never share an
`http://` link.

### Keeping it running

`scripts/run_web_app.ps1` is `update_main_bot.ps1`'s process handling
for the web app, and nothing else:

```powershell
.\scripts\update_main_bot.ps1 -RepoPath 'K:\...\fool-bot'   # pull, install, restart the bot
.\scripts\run_web_app.ps1     -RepoPath 'K:\...\fool-bot'   # restart the web app on the same tree
.\scripts\run_web_app.ps1     -RepoPath 'K:\...\fool-bot' -StopOnly
```

- **It does not pull or install.** The checkout and the `.venv` are the
  bot's too, and moving them is the updater's; a web script that pulled
  would leave the bot on a tree older than the one on disk. So a deploy
  is the two lines above, in that order, and a web-only restart is the
  second alone. It refuses to start if the `.venv` does not exist yet.
- **It stops every web app of this checkout before starting one**, and
  refuses to start if any survive -- the updater's reasoning: a process
  started by hand is invisible to a pid file, and two over one games
  file overwrite each other. It matches `-m webapp` run by this
  checkout's own venv python (the command line carries no path to
  match), plus the pid it wrote last.
- It starts the process hidden, logs to `data/webapp.stdout.log` and
  `data/webapp.stderr.log` (the console logging goes to the second),
  and fails loudly if the process has exited four seconds later -- a
  port already in use raises out of `main`, and that is the likeliest
  way it does.
- **Nothing restarts it on a crash or a reboot**, the same as the bot.
  To have it come back after a reboot, a Task Scheduler task "At log
  on" running `powershell -ExecutionPolicy Bypass -File
  <checkout>\scripts\run_web_app.ps1 -RepoPath <checkout>` is the
  obvious shape -- at log on rather than at startup, because the `K:\`
  Google Drive letter is mounted per user and is not there before
  somebody logs in.

### Exposing the port

The port is never forwarded on the router. A tunnel client on the
same machine dials out to a provider, which gives it a public HTTPS
name and forwards to `http://127.0.0.1:<FOOLBOT_WEB_PORT>`. Which
provider is the author's choice (worksheet step 5, "Which tunnel");
the three the worksheet names, in outline -- each provider's own docs
are the reference, and none of this has been tried:

- **Cloudflare Tunnel** needs a domain on a Cloudflare account.
  `cloudflared tunnel login`, `cloudflared tunnel create d12ball`,
  `cloudflared tunnel route dns d12ball <play.example.com>`, a config
  whose ingress sends `<play.example.com>` to
  `http://localhost:8080`, then `cloudflared service install` so it
  runs as a Windows service. `FOOLBOT_WEB_URL=https://<play.example.com>`.
- **Tailscale Funnel** needs the machine on a tailnet with Funnel
  allowed in its policy. `tailscale funnel --bg 8080` serves
  `https://<machine>.<tailnet>.ts.net` to the world and persists
  across restarts of the Tailscale service.
  `FOOLBOT_WEB_URL=https://<machine>.<tailnet>.ts.net`.
- **ngrok** needs an account and its (free) static domain, since a
  name that changes every run would break every shared room link.
  `ngrok http --url=<name>.ngrok-free.app 8080`, kept running the way
  the web app is (ngrok can install itself as a Windows service).
  `FOOLBOT_WEB_URL=https://<name>.ngrok-free.app`.

Whichever it is: set `FOOLBOT_WEB_URL` to the name it gives, restart
the web app (the variable is read per link, but the `.env` only at
startup), open that address from a phone off the home Wi-Fi, and
check the room link the page hands out starts with it.

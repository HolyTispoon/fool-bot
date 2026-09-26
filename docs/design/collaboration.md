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

**One bot per token, and `scripts/update_main_bot.ps1` is what enforces it**
(run on the host as `scripts\update_main_bot.cmd`; see "Keeping it
running" below for why through the launcher).
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
- **One bot is two `python.exe` processes, and it counts trees, not
  processes.** A Windows venv's `python.exe` is a redirector, not an
  interpreter (since Python 3.7.2): it reads `pyvenv.cfg`, starts the base
  `python.exe` with the same command line as its child, in a job that dies
  with it, and waits. The redirector matches on the venv path and the
  interpreter on the full path to `foolbot.py` it was handed, so the updater
  used to warn on every run that it had stopped two bots when it had stopped
  one. `Get-FoolBotRoots` counts a match whose parent is not itself a match;
  the warning and the pid file are the redirector's, and every match is still
  stopped. The web app script never had the false count only because its
  match is the venv path alone, which the interpreter does not carry.
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
been executed anywhere, and the Cloudflare steps are Cloudflare's
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
FOOLBOT_WEB_URL=https://play.d12ball.com
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
  is built from this. It is the public hostname given the tunnel in
  "Exposing the port" below: `https://play.d12ball.com`. Left at the default, links point at
  `http://localhost:8080`, which works only on the host itself.

### Only ever over HTTPS

The cookie **is** the identity: whoever holds it holds the seat, and
it is good for a year. Over plain HTTP anybody on the path can read
it, so the page is served only through the tunnel's HTTPS name, never
by opening the port on the router, and a link is only ever shared
with the `https://` address.

**The cookie is `Secure`, and that rests on the tunnel's word.** A
`Secure` cookie is one a browser never sends over plain HTTP, so even
a mistyped `http://` address cannot leak it. But behind the tunnel the
process sees only the last hop -- `cloudflared` on this machine to the
web app, plain HTTP -- so `request.secure` is false for every visitor.
The tunnel says what the browser really used in `X-Forwarded-Proto`,
and `identity.came_over_https` believes it **only from this machine**
(a loopback address): anybody who can reach the port directly could
write that header, and with `FOOLBOT_WEB_HOST=127.0.0.1` nothing but
the tunnel can. That is why the host line in the `.env` matters twice.
Chosen over marking the cookie `Secure` whenever `FOOLBOT_WEB_URL`
starts with `https://` (the author, 2026-09-26), because it answers
per request what the browser actually did. Cloudflare's "Always Use
HTTPS" is still worth turning on (below): it sends a person who typed
`http://` to the page they meant, where before it was also the only
thing between that request and the cookie.

### Keeping it running

`scripts/run_web_app.ps1` is `update_main_bot.ps1`'s process handling
for the web app, and nothing else:

From the checkout's root folder, through the two launchers beside the
scripts:

```powershell
.\scripts\update_main_bot.cmd          # pull, install, restart the bot
.\scripts\run_web_app.cmd              # restart the web app on the same tree
.\scripts\run_web_app.cmd -StopOnly
```

(The same lines work in `cmd.exe`, without the comments.)

- **Run them through the `.cmd` launchers, never as `.\x.ps1`.** The
  checkout is on the Google Drive letter, and on that host the shell's
  policy is `RemoteSigned` (set per window; every other scope is
  `Undefined`, so a plain window is `Restricted` and runs no script at
  all). `RemoteSigned` treats `K:\` as remote and refuses both scripts
  as unsigned (`... is not digitally signed. You cannot run this script
  on the current system`). A launcher runs its script with
  `powershell -ExecutionPolicy Bypass -File`, which lifts the policy for
  that one run and changes no setting on the machine -- the way
  `scripts/update-main-bot.sh` has always launched the updater over
  SSH. That is why it is preferred over `Set-ExecutionPolicy` (every
  script for the account, forever) and over signing (a certificate,
  and a re-sign on every change to either script).
- A launcher fills in `-RepoPath` with the folder above `scripts\`,
  so it is not passed; every other option goes after it
  (`update_main_bot.cmd -Branch <name>`, `-SkipPull`). It exits with
  the script's own code, so a failed start fails the caller.
- `.gitattributes` holds `*.cmd` to CRLF, since `cmd.exe` misreads a
  batch file with bare LF endings and the Mac checkout would otherwise
  commit them that way.

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
  on" running `<checkout>\scripts\run_web_app.cmd` is the obvious
  shape -- at log on rather than at startup, because the `K:\`
  Google Drive letter is mounted per user and is not there before
  somebody logs in.

### Exposing the port: Cloudflare Tunnel on `d12ball.com`

The tunnel is Cloudflare's, on the author's own `d12ball.com` (the
author, 2026-09-26). The port is never forwarded on the router:
`cloudflared` on the PC dials out to Cloudflare, Cloudflare answers
`https://play.d12ball.com` with its own certificate, and passes each
visit down that connection to `http://127.0.0.1:8080`. A subdomain
rather than `d12ball.com` itself, so the bare domain stays free for
whatever the game's public face turns out to be.

Cloudflare's dashboard moves its menus around; the names below are
the shape, not a promise.

1. **Check the domain is on Cloudflare.** In the dashboard,
   `d12ball.com` is listed as a site and shows *Active* (bought
   through Cloudflare, it is; bought elsewhere, its nameservers have
   to be pointed at Cloudflare's first).
2. **Install `cloudflared`** on the PC, from an administrator
   PowerShell: `winget install --id Cloudflare.cloudflared`.
3. **Create the tunnel in the dashboard:** Zero Trust -> Networks ->
   Tunnels -> *Create a tunnel* -> *Cloudflared*, named `d12ball`.
   Pick Windows; it shows a `cloudflared.exe service install <token>`
   command. Run that in an administrator PowerShell: it installs the
   tunnel as a Windows service, which starts with the machine (it
   needs nothing from `K:\`, so unlike the web app it can start before
   anybody logs in). **The token is a credential** -- whoever has it
   can run your tunnel -- so it goes nowhere else, and never in the
   repository.
4. **Give it the public hostname:** on the same tunnel, *Public
   Hostname* (a *published application*, in newer dashboards) ->
   subdomain `play`, domain `d12ball.com`, service URL
   `http://127.0.0.1:8080` -- **`http`, not `https`**: the web app
   speaks plain HTTP, the HTTPS is Cloudflare's, and an `https://`
   service URL gets a 502 from a process that has no certificate.
   Written as `127.0.0.1`, not
   `localhost`: Windows can answer `localhost` with the IPv6 `::1`,
   and the web app bound to `127.0.0.1` would refuse it. Cloudflare
   creates the DNS record itself.
5. **Turn on "Always Use HTTPS"** for `d12ball.com` (SSL/TLS -> Edge
   Certificates).
6. **Set `FOOLBOT_WEB_URL=https://play.d12ball.com`** in `.env` and
   restart the web app with `run_web_app.ps1` (the variable is read per
   link, but the `.env` only at startup).
7. **Check it from outside**: open `https://play.d12ball.com` on a
   phone off the home Wi-Fi, give a name, open a room, and check the
   room link the page hands out starts with `https://play.d12ball.com`.
8. **Check the cookie is `Secure`**, which is the one thing that
   proves Cloudflare sends `X-Forwarded-Proto` the way
   `came_over_https` expects: in Chrome on a computer, F12 ->
   Application -> Cookies -> `https://play.d12ball.com` ->
   `d12ball_coach` has a tick under *Secure*. No tick means the header
   did not arrive and the cookie is back to riding on the redirect
   alone -- say so on the worksheet rather than working around it.

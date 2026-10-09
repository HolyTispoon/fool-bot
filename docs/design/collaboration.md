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
  - **Drive also writes a hidden `desktop.ini` into the folders it syncs,
    `.git\refs\` and every folder under it included, and git reads every
    file under `refs\` as a ref.** The deploy of 2026-10-09 failed on the
    fetch with `did not send all necessary objects` -- git's report of its
    connectivity check dying on `fatal: bad object refs/desktop.ini` --
    while `git fsck --full` found every object sound and seven refs named
    `desktop.ini` with an `invalid sha1 pointer` of zeros. Nothing had
    been stopped: the fetch comes first. The three scripts that fetch
    (`update_main_bot.ps1`, `pull_checkout.ps1`, and the inline copy of
    the steps in `update-main-bot.sh`) delete every `desktop.ini` under
    `.git` before the fetch, every time rather than once, because Drive
    writes them again; they are its folder-icon metadata, nothing git
    wrote. The working tree's are left where they are: untracked, and the
    dirty check ignores untracked files. By hand, when a fetch fails that
    way from a shell: `Get-ChildItem -LiteralPath .git -Recurse -Force
    -Filter desktop.ini | Remove-Item -Force`.

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
- **The web app is not a foolbot to it, and neither is the Codex bot.**
  `python3 -m webapp` is its own process with no token, and `codexbot.py` is
  its own process with its own token, so the updater's match on `foolbot.py`
  neither stops nor counts either; each is restarted on its own (see "The
  Codex bot" below).
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
  `d12ball_web_chat.json`, `d12ball_web_journal.json`, and its own
  `webapp.pid` and `webapp.*.log` -- against the bot's `d12ball_games.json`,
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

The same `.env` the bot reads (both call `load_dotenv()`), with five
more lines; the table in [web-app.md](web-app.md), "Running it", is
the reference for the four the web app reads. The fifth,
`FOOLBOT_TUNNEL_TOKEN`, is read by `run_tunnel.ps1` alone, and only on
the host that serves `play.d12ball.com` -- "Exposing the port" below.

```ini
FOOLBOT_WEB_PORT=8080
FOOLBOT_WEB_HOST=127.0.0.1
FOOLBOT_WEB_URL=https://play.d12ball.com
FOOLBOT_WEB_SECRET=<64 random hex characters>
FOOLBOT_TUNNEL_TOKEN=<the tunnel's token, from the Zero Trust dashboard>
```

- **`FOOLBOT_WEB_SECRET` should be set.** A person is a signed cookie
  and nothing else -- no account (`webapp/identity.py`). A changed
  secret **signs everybody out and makes every seat's holder a
  stranger** (an admin can hand the seat back, but a mid-game restart
  for a deploy should not need one). Without one in the environment
  the web app makes one and keeps it in `data/d12ball_web_secret`,
  which survives a restart but not a new checkout; the `.env` line is
  the one to keep. A cookie that fails its signature is logged at
  WARNING in `data/webapp.stderr.log`, naming who it claimed to be --
  the line to look for when somebody says they came back as an
  observer. Make it
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
per request what the browser actually did.

**A request the tunnel carried over `http://` is redirected to
`https://`** by the web app itself (`server.https_only`), and every
HTTPS response carries `Strict-Transport-Security`. On 2026-09-27
`http://play.d12ball.com` was answering in full: "Always Use HTTPS"
(below) was not on, and a browser there sent no `Secure` cookie and
was handed a second person -- a coach in their own room became an
observer in the same browser. The redirect makes that impossible
whatever the dashboard says; "Always Use HTTPS" is still worth turning
on, so the request never reaches this machine.

### Keeping it running

`scripts/run_web_app.ps1` is `update_main_bot.ps1`'s process handling
for the web app, with the pull and the install in front of it through
`scripts/pull_checkout.ps1`:

From the checkout's root folder, through the launchers beside the
scripts, or the one that runs them all in order:

```powershell
.\scripts\update_main_bot.cmd          # pull, install, restart the bot
.\scripts\update_main_bot.cmd -StopOnly
.\scripts\run_codex_bot.cmd            # pull, install, restart the Codex bot
.\scripts\run_codex_bot.cmd -StopOnly
.\scripts\run_web_app.cmd              # pull, install, restart the web app
.\scripts\run_web_app.cmd -StopOnly
.\scripts\run_tunnel.cmd               # restart the tunnel's connector
.\scripts\run_tunnel.cmd -StopOnly

.\scripts\deploy.cmd                   # all four, in that order
.\scripts\deploy.cmd -StopOnly         # stop all four, in the reverse order

.\scripts\show_logs.cmd                # the last 40 lines of each one's logs
.\scripts\show_logs.cmd bot -Follow    # or codex, webapp, tunnel; -Tail n
```

(The same lines work in `cmd.exe`, without the comments.)

[`scripts/README.md`](../../scripts/README.md) is the same list as a
short reference for whoever is at the machine, without the reasons; a
new option goes in both.

`deploy.ps1`/`deploy.cmd` call the four scripts above in order and add
no logic of their own -- no new process matching, no new pid file. It
takes `update_main_bot`'s options (`-Branch`, `-SkipPull`) and passes
them through, and passes `-SkipPull` to the Codex bot's and the web
app's scripts whatever it was given: the updater has just pulled, and
their own pull, of `main` by default, would undo a `-Branch` deploy. `$ErrorActionPreference = 'Stop'` means a failed
pull, install or bot start stops it before the web app is touched, so
the web app is never restarted onto a tree the first half failed to
update. The tunnel goes last: it serves nothing until the web app is
up, and it is the one step a checkout may skip (see "Exposing the
port").

`-StopOnly` is each script's own stop and nothing else: the same
matching as a restart, then no start -- the three that pull skip the
pull and the install too, having nothing to start them for. It exists because
a process started hidden has no Ctrl+C. `deploy.cmd -StopOnly` runs
the three the other way round, the tunnel first so nobody reaches a
web app that is going away, and unlike a deploy it carries on past a
failure: a stop that gives up half way leaves running exactly what it
was asked to stop. A stop leaves the logs; only a start deletes them.

`show_logs.cmd` is the window onto those logs, since a hidden process
has no console: the last lines of each process's `data\<name>.stderr.log`
(where the console logging goes) and `.stdout.log`, under a heading
saying whether its pid file names a live process -- which is what the
scripts started, not everything running, since a hand-started process
writes no pid file and the tunnel writes its own only once connected.
`-Follow` follows every log it showed, not one, so it polls rather
than using `Get-Content -Wait`, and reads a log that a restart deleted
from the top again; Ctrl+C there stops the viewer and nothing else.

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

- **It pulls and installs first, unless told `-SkipPull`** (and takes
  `-Branch`), as does `run_codex_bot.ps1`: both call
  `scripts/pull_checkout.ps1`, the updater's steps -- refuse a dirty
  tree, fetch, check out the branch, fast-forward, pip against
  `requirements.txt` -- before anything is stopped, so a failed pull
  leaves the running process running. Until 2026-10-09 neither pulled,
  because the checkout and the `.venv` are the bot's too: a pull here
  leaves the bot, and the other of the two, running code older than
  the tree on disk until they are restarted. The author chose the other
  cost (2026-10-09): restarting one alone was never picking up new code,
  so a restart looked like an update and was not. `pull_checkout.ps1`
  warns whenever the pull brought anything, naming `deploy.cmd` as what
  restarts all four on it; with nothing new, the pip run touches
  nothing already satisfied, so it is safe beside the processes still
  running out of the same `.venv`. `update_main_bot.ps1` keeps its own
  copy of the steps rather than calling the shared one, since it is the
  script every deploy goes through and this change was written where
  only a parse and a run against a scratch clone could check it. It
  refuses to start if the `.venv` does not exist yet.
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
- **Nothing restarts it on a crash or a reboot**, the same as the bot
  and the tunnel. After a reboot all three are down until a deploy:
  `deploy.cmd -SkipPull` brings them back on the tree already there.
  To have that happen by itself, a Task Scheduler task "At log on"
  running `<checkout>\scripts\deploy.cmd -SkipPull` is the obvious
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
   command. **Do not run it.** Copy the token out of it -- the long
   string after `install` -- into the checkout's `.env` as
   `FOOLBOT_TUNNEL_TOKEN=<token>`, and run `.\scripts\run_tunnel.cmd`
   (or a deploy, which ends with it). **The token is a credential** --
   whoever has it can run your tunnel -- so it goes in the `.env` and
   nowhere else, never in the repository. The tunnel and its hostname
   live in Cloudflare; this machine only runs its *connector*, and the
   token is what that connector proves itself with. A lost token is
   not a new tunnel: the tunnel's page in the dashboard shows it again.

   **Why not the Windows service the dashboard offers.** It was the
   first setup, and on 2026-09-30 it had not come back after a reboot
   days before: Zero Trust showed the tunnel *Down* and
   `play.d12ball.com` answered Cloudflare's 1033, while every deploy in
   between restarted the bot and the web app and never touched it. A
   service can start before anybody logs in, but the web app cannot
   (`K:\` is not mounted yet), so that buys nothing; and it takes an
   administrator to install and to start, which a deploy over SSH is
   not. `run_tunnel.ps1` runs the connector the way `run_web_app.ps1`
   runs the web app instead: hidden, out of this checkout, stopped
   and started on every deploy, its log in `data/tunnel.stderr.log`.
   The token reaches `cloudflared` as `TUNNEL_TOKEN` in its
   environment, never on its command line, which any process on the
   machine can read. The script waits for `cloudflared` to report its
   first connection -- the pid file it writes only then
   (`data/tunnel.pid`), or the "Registered tunnel connection" line in
   the log -- and fails the deploy if neither comes within 30 seconds,
   so a tunnel that is not serving is a red deploy rather than a 1033
   somebody finds days later. A checkout with no
   `FOOLBOT_TUNNEL_TOKEN` skips it with a warning: one connector
   belongs on the live host, the way one bot belongs to one Discord
   token. If the service from the first setup is still installed, the
   script says so on every run; remove it once from an administrator
   PowerShell with `cloudflared.exe service uninstall`.
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
   restart the web app with `run_web_app.cmd` (the variable is read per
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

### Cloudflare keeps what the web app does not say about

Cloudflare caches a response by its file extension: a `.js`, `.css`
or `.png` the origin sent with no `Cache-Control` is kept at the edge
for four hours, and handed to browsers with `max-age=14400`, while an
HTML page is always fetched fresh. `/static/` is served under
unversioned names, so on 2026-09-26, after redesign step 11 was pulled
onto `K:\`, every visitor got the new `game.html` under the old
`app.js` and `app.css`, and a room drew nothing but its empty shapes --
on a phone and a computer alike, for everybody, with the origin
serving the right files. So the web app says: every response whose
handler set no `Cache-Control` goes out `no-cache`
(`revalidate_by_default` in `webapp/server.py`) -- the edge and the
browser keep their copy and check its ETag first, which an unchanged
file answers with a 304. The cards, emoji and fonts set their own and
keep them.

A copy cached before that fix, or anything else stale at the edge, is
cleared from the dashboard: `d12ball.com` -> Caching -> Configuration
-> *Purge Everything* (or *Custom Purge* with the URLs). A browser that
already holds a copy under the old `max-age` still needs a hard reload
(Cmd/Ctrl+Shift+R; on a phone, clearing the site's data) until it
expires.

## The Codex bot

The third process on the `K:\` checkout is a second Discord bot:
`codexbot.py`, Sirlin Games' *Codex*, with its own token
(`CODEX_DISCORD_TOKEN`) and its own application in the Developer Portal.
What it is and why it is its own process is
[codex.md](codex.md), "Its own process, its own token"; this is how it
is run beside fool-bot.

**What it shares with fool-bot**: the checkout, the `.venv`
`update_main_bot.ps1` makes, the `.env` (its `CODEX_LOG_*` variables
fall back to the `FOOLBOT_LOG_*` ones, so it mirrors into the same
#logs channel and every notice there names its bot), and `data/` as a
folder. **What is separate**: every file it writes --
`data/codex_bot_state.json` (its command-tree fingerprint and the last
build it announced, which in one shared file each bot would overwrite,
re-syncing on every start), `data/codexbot.pid` and its two logs, and
the games file a later step adds -- and its restart,
`scripts/run_codex_bot.ps1` (`run_codex_bot.cmd`), modelled line for
line on `run_web_app.ps1`: the pull and the install first, through
`pull_checkout.ps1` (`-SkipPull` and `-Branch` as the updater's), every `codexbot.py`
run by this checkout's venv python stopped, a refusal to start while
any survives, a hidden start, and a failure if the process has exited
after four seconds. A checkout with no `CODEX_DISCORD_TOKEN` starts no
Codex bot, as one with no tunnel token starts no tunnel, so a deploy on
the Mac or before the token is in `.env` goes on to the web app.
`deploy.ps1` runs it straight after `update_main_bot.ps1`.

**One application, one token, one Codex bot.** The author created the
Codex application on 2026-10-07 and there is no test application beside
it (2026-10-08), so a developer testing from the Mac stops the live
host's Codex bot first (`run_codex_bot.cmd -StopOnly` there) or tests
before the live host runs one at all -- two processes on one token are
the 10062 failure above. The author creates the applications and
invites them; nothing in this repository can.

**What its console says about the host.** A few seconds after it
starts, the Codex bot logs how long the host's disk took to hand over
every picture it draws from ("Codex pictures read into memory: 447
files, 44 MB, in 0.1 s" on the Mac; the checkout is on the Google Drive
letter, so the host's number is the one to know), and every picture a
click puts up logs what it cost to draw and to send -- the board, the
panel, a hand, a codex view, a card. Both are INFO, console-only
(`show_logs.cmd`): read them before guessing why something was slow
([codex.md](codex.md), "The board on Discord").

**Nothing in this section has been run on the `K:\` host.** It was
written in a Linux sandbox with no PowerShell; `run_codex_bot.ps1` has
not been executed anywhere. Correct this section from the first deploy.

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
  `data/d12ball_games.json`, and `data/bot_state.json`. The Mac's saved games
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
- **Read a 10062 as this first.** It is raised out of a command's first line,
  before anything of ours has run, so it can never be a bug in that command --
  see `defer_or_report` in `cogs/debug.py`, which says so in #logs rather than
  raising a traceback that names only the symptom. The other cause is a bot too
  busy to acknowledge inside three seconds; `Get-CimInstance Win32_Process`
  tells the two apart in one command.

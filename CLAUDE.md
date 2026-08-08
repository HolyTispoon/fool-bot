# fool-bot

A Discord bot for playing and testing Prophetic Fool prototypes. The active
prototype is **D12 Ball**, a board game whose state is rendered to a PNG and
posted into a Discord channel.

## Running it

```bash
pip install -r requirements.txt     # needs a .env with DISCORD_TOKEN
python3 foolbot.py
```

```bash
python3 -m unittest discover -s tests
```

## Where things live

| Path | What it is |
| --- | --- |
| `foolbot.py` | Bot entry point; generic deck/dice commands. Loads the cogs. |
| `botlog/` | Console logging setup, and the #logs channel mirror — see below |
| `cogs/d12ball.py` | All D12 Ball slash commands and Discord interaction flow |
| `cogs/d12ball_helpers.py` | Constants and free functions shared by the cog and its views — emoji lookups, player/team formatting, channel naming |
| `cogs/d12ball_views.py` | The `discord.ui.View` classes, one per prompt a player can be shown |
| `cogs/debug.py` | Maintenance commands, including the PBD channel-and-count reset |
| `d12ball/components.py` | Game state model — `MatchState`, `BoardState`, `TeamSetup`, `PlayerCatalog` |
| `d12ball/game.py` | `D12BallGame` (per-channel game record), `Team`, `GameMode` |
| `d12ball/render.py` | Board image rendering (Pillow) |
| `d12ball/data/` | `players.json`, `basic_rules.json` |
| `d12ball/images/` | Card art and emoji |
| `d12ball/fonts/` | Bundled DejaVu — see "Fonts" below |
| `gamesaves/d12ball/storage.py` | Persistence to `data/d12ball_games.json` |
| `scripts/` | CLI tools used repeatedly (not one-off scratch work) |
| `docs/` | The game rules, and how they got that way -- see below |

## The rules

**Read [docs/living-rules.md](docs/living-rules.md) before changing anything that models the
game.** It is the whole ruleset as it currently stands and the single thing to check a
mechanic against: it states each rule once, settled, with no history and no upstream
wording to reconcile.

The rules themselves live in two upstream places, neither complete on its own, plus a third
body that has only ever existed in the author's head:

- a [Notion page](https://propheticfools.notion.site/D12-Ball-6c9e1ea7ca61825391e881ec5fbfdca5)
  for the narrative rules. It is a JS app, so a plain fetch returns an empty shell -- render
  it in a browser to read it.
- a [Google Sheet](https://docs.google.com/spreadsheets/d/1PKPpTseisPmM-tH6PMLbtsrYsZ_zG8smluP5VmHKcMw)
  for component data. The share URL is not fetchable but `export?format=csv&gid=<gid>` is,
  which is how `scripts/import_d12ball_players.py` works.

[docs/rules-log.md](docs/rules-log.md) is the other half: every rules change with its date and
where it came from, what is still unanswered, and what the answers unblock. Two parts of it
earn their keep when upstream moves:

- **Where upstream is behind** lists every point at which the living rules already differ from
  Notion or the sheet, so a fresh pull can tell old news from a real change.
- The **change log** is the running record. The rules are a live prototype and move: when they
  do, update the living rules and add a dated entry as its own commit, so each rules change
  stays a reviewable diff.

**Take rules questions to the author rather than inferring them from the code** -- several
mechanics exist only in the code, so there a bug and a deliberate decision look identical.
Asking as inline comments on a docs PR has worked far better than asking in chat, and it
leaves the answers versioned.

## Logging and the #logs channel

**Use `logging`, not `print`.** Every module gets its own logger
(`LOGGER = logging.getLogger(__name__)`) and `botlog.configure_logging()`
in `foolbot.py` sets the root logger up once, before anything logs. That is
also why `bot.run` is called with `log_handler=None`: discord.py otherwise
configures its own logger inside `run`, and with a root handler already
attached every library line would print twice.

Records at ERROR and above are mirrored into a Discord channel, so a crash
shows up in the server instead of only on the console of whoever is hosting
the bot. The bot finds or creates a channel called `#logs` on startup, posts
the record with its traceback in a code fence, and posts a one-line notice
naming the build it is running whenever that build changes.

Everything is optional and lives in `.env` next to `DISCORD_TOKEN`:

| Variable | Default | What it does |
| --- | --- | --- |
| `FOOLBOT_LOG_LEVEL` | `INFO` | Console threshold |
| `FOOLBOT_LOG_CHANNEL_LEVEL` | `ERROR` | Discord threshold; `off` disables the mirror |
| `FOOLBOT_LOG_CHANNEL_ID` | — | Mirror into exactly this channel |
| `FOOLBOT_LOG_CHANNEL_NAME` | `logs` | Channel to find or create, when no id is set |
| `FOOLBOT_LOG_GUILD_ID` | first server | Which server hosts the channel |
| `FOOLBOT_DEPLOY_NOTICE` | on | `off` stops the "now running this build" notice |
| `FOOLBOT_HOST_NAME` | machine name | What the deploy notice calls this host |

Three things to know before changing any of it:

- **The level you log at decides who sees it.** ERROR reaches the server;
  WARNING and INFO are console-only. So an error means "someone needs to
  fix this", not "something unexpected happened" — a missing application
  emoji is an INFO, a game whose channel the bot is not allowed to move is
  an ERROR. The test is whether anyone can act on it: a finished game whose
  channel was deleted, or whose server the bot has left, is an INFO however
  much it looks like a failure, because there is nothing to fix and the
  startup sweep would repeat it on every reconnect.
- **The sink must never log its own failures.** A failed send that logged
  would hand itself the record it just failed to send. `botlog/handler.py`
  prints those to stderr, deliberately.
- **The build notice is keyed on the commit sha**, remembered in the
  untracked `data/bot_state.json`. `on_ready` fires again on every gateway
  reconnect and either of us restarts the bot constantly while testing;
  keying on the commit is what keeps that from being a stream of identical
  "restarted" posts. It reads HEAD out of the checkout with `git log`, so
  the notice is only as accurate as the deployed tree — and degrades to
  saying nothing at all if git is not on PATH.
- **The notices are one stream per machine, not one per repository.** That
  state file is local, so when we both deploy into the same `#logs` the
  posts interleave: the same commit gets announced once by each host, and
  neither stream is the repository's history. Each notice names its host so
  they can be told apart. Don't read the channel as a changelog.
- **A merge is listed only when it resolved a conflict.** A clean merge
  repeats commits the notice already lists, so it is dropped and its pull
  request named in the heading instead; a conflict resolution exists in the
  merge commit and nowhere else, so dropping it would drop work. The test
  for which is an empty combined diff — `--name-only` and `--stat` both
  report a clean merge of two branches that touched one file as if it
  carried changes, so `merges_with_content` reads the patch.

The channel is created with whatever permissions the server's defaults give
it. Tracebacks name game ids, channel names and command arguments, so lock
the channel down server-side if that matters.

## Working on the board image

The board image is the bot's main output, so look at it. Don't rely on the
test suite to tell you a rendering change is right — it only asserts the
output is a PNG of the expected dimensions.

```bash
python3 scripts/render_sample.py --home purple --visiting teal --out board.png
python3 scripts/render_sample.py --list-games
python3 scripts/render_sample.py --game <game_id>      # reproduce a real board
```

`--game` renders a real saved game from your own `data/d12ball_games.json`,
which is how to reproduce a board someone reported a problem with rather than
guessing at the state. Saved games are local to each machine, so a fresh clone
lists none until the bot has been run.

### Fonts

Fonts are bundled in `d12ball/fonts/` and loaded by absolute path. **Do not go
back to looking them up by bare filename.** `ImageFont.truetype("Arial.ttf")`
searches the host's font directories, and the same typeface is filed under a
different name on macOS, Windows and Linux, so no list of bare names works
everywhere. When every name misses, Pillow's `load_default()` returns a face
pinned to size 10 that ignores the requested size, and every label on the
board silently collapses to tiny text. That was a real bug; the tests in
`D12BallFontTests` exist to keep it from coming back.

`render.py` builds its font objects at **import time**, so a running bot keeps
whatever it resolved at startup. Restart after any render change.

## Game channels

Every game gets its own private channel, named by `build_game_channel_name` in
`cogs/d12ball_helpers.py`: `d12ball-pbd<number>`, then the game's name if
`/d12ball create_game` was given one (`game_name`, carried on the game record
and reused by the rematch button), or the two sides otherwise —
`d12ball-pbd12-the-cup-final`, `d12ball-pbd12-username-vs-dinky-ai`.

- **The number stays immediately after the `d12ball-pbd` prefix.** It is the
  only part read back off a channel, by `CHANNEL_NAME_PATTERN`, and the suffix
  in that pattern is optional so channels created before names existed still
  match. Anything that changes the shape of the name has to keep both true.
- **Names are slugged, not passed through.** Discord lowercases a channel name
  and rewrites spaces itself, so `slugify_channel_part` does it first and the
  saved name matches what the server shows. Punctuation is dropped, letters
  outside ASCII are kept (they are legal, and a wholly non-Latin display name
  would otherwise slug to nothing), and the whole name is cut to Discord's
  100-character limit without ending on a dash.
- **Archiving moves the channel between categories and never renames it**, so
  a game's channel keeps the name it was created with for the rest of its life.
  Nothing renames a channel when a player's display name changes.

## Gotchas

- **`data/d12ball_games.json` is runtime state and is deliberately untracked.**
  The bot rewrites it on every game action. It used to be committed, which
  meant it showed as modified more or less permanently and was a standing
  source of merge conflicts. Don't re-add it. Each developer's saved games are
  local to their own machine, and `data/` is created at startup if missing.
- **Startup drops finished games whose channel was deleted.** The archiving
  sweep in `on_ready` prunes a finished game when Discord answers its channel
  lookup with a 404, because there is nothing left to archive and the record
  would report the same failure on every reconnect. Two edges are deliberate:
  a game whose *guild* is missing is only skipped, since a Discord outage
  looks identical and the games would be gone for good; and only the channel
  lookup counts, so a 404 from the category or the move is an error and keeps
  the game. Deleting a channel by hand now also deletes the game record, and
  since `get_next_game_number` is `max + 1` over the guild's saved games,
  pruning the newest ones lets a PBD number be handed out twice.
- **Known unfixed issue:** meeple name labels overflow their space borders and
  collide when two meeples share a space. `draw_meeple_group` in `render.py`
  clamps label positions and offsets stacked names by a fixed 23px, both tuned
  for a smaller `FONT_MEEPLE` than the current one.
- **The "View full image" button dies after 24 hours, by design.** Discord
  signs attachment URLs and stops honouring a signature a day after issuing it,
  so the link baked into a board or maneuver-reference message goes dead once
  the message sits untouched that long. The next board update re-cuts it. This
  is an accepted trade for a one-tap link; the alternative was a callback
  button that fetches a fresh URL on click at the cost of an extra tap. See
  `add_full_image_button` in `cogs/d12ball.py`.

## Collaboration

Two people develop on this repo in parallel, on different machines and
different operating systems.

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

## Notes for Claude

- **Keep this file current with the code.** When a change alters the
  architecture or the structure — a new module or cog, a responsibility moving
  between them, a new persisted field on a game record, a change to how
  channels are named or state is stored, a new environment variable — update
  the relevant section here in the same commit, unless it already says so.
  Add the reasoning, not just the fact: this file exists to explain the
  decisions the code cannot. Leave it alone for ordinary changes that fit the
  structure already described.
- **Don't commit one-off diagnostic scripts.** If something is scaffolding for
  a single investigation, hand it over as a file instead. `scripts/` is for
  tools worth running more than once.
- **Verify git and environment behaviour before asserting it.** This repo has
  enough quirks (a tracked file that is rewritten at runtime, fonts resolved
  at import) that reasoning from first principles produces confident wrong
  answers. Reproducing takes a minute and is usually decisive.
- The two developers run on different operating systems. Before concluding
  "it works here but not there", establish what actually differs between the
  hosts rather than assuming a deployment or staleness problem.

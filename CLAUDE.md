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
| `cogs/d12ball.py` | All D12 Ball slash commands and Discord interaction flow |
| `d12ball/components.py` | Game state model — `MatchState`, `BoardState`, `TeamSetup`, `PlayerCatalog` |
| `d12ball/game.py` | `D12BallGame` (per-channel game record), `Team`, `GameMode` |
| `d12ball/render.py` | Board image rendering (Pillow) |
| `d12ball/data/` | `players.json`, `basic_rules.json` |
| `d12ball/images/` | Card art and emoji |
| `d12ball/fonts/` | Bundled DejaVu — see "Fonts" below |
| `gamesaves/d12ball/storage.py` | Persistence to `data/d12ball_games.json` |
| `scripts/` | CLI tools used repeatedly (not one-off scratch work) |

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

## Gotchas

- **`data/d12ball_games.json` is runtime state and is deliberately untracked.**
  The bot rewrites it on every game action. It used to be committed, which
  meant it showed as modified more or less permanently and was a standing
  source of merge conflicts. Don't re-add it. Each developer's saved games are
  local to their own machine, and `data/` is created at startup if missing.
- **Known unfixed issue:** meeple name labels overflow their space borders and
  collide when two meeples share a space. `draw_meeple_group` in `render.py`
  clamps label positions and offsets stacked names by a fixed 23px, both tuned
  for a smaller `FONT_MEEPLE` than the current one.

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

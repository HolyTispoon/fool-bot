# Repo analysis — fool-bot

**Date:** 2026-07-25
**Analyzed at commit:** `fd391c5` ("d12 command sadded")
**Scope:** Read-only pass over the full repo. No code changed.

This is a working note from an outside read of the codebase, written before
contributing any code. It records what the repo contains, how it is organized,
and which questions could not be answered from the source alone. Observations
below describe the code as it stands; they are not a verdict on it, and several
"open questions" likely have obvious answers to the author.

---

## 1. Snapshot

A Discord bot for **D12 Ball** ("pbd" = play-by-Discord), a tabletop game in the
Foolish / Prophetic Fools setting. Python 3, `discord.py` 2.7.1, slash commands.

Three commits, Jul 21 → Jul 25 2026, single author. No issues, no PRs, no
README, no tests, no CI, no linter config, no packaging.

```
foolbot.py           entrypoint: bot class + 6 slash commands defined inline
cogs/d12ball.py      GroupCog: /d12ball create_game + coin-flip button View
cogs/_init_.py       empty (see 5.1)
connection_test.py   standalone login smoke test; not imported anywhere
requirements.txt     pip freeze output
.vscode/settings.json
.gitignore           .env, .venv/, __pycache__/, game_state.json, .DS_Store
```

Secrets: clean. No token has ever been committed; `.env` has never been tracked.

Runtime config is a single environment variable, `DISCORD_TOKEN`, read from
`.env` via `python-dotenv`. There is no `.env.example`, so this is currently
only discoverable by reading the source.

---

## 2. Architecture: two eras side by side

The repo is mid-transition between two designs that do not yet know about each
other. This is the most important thing to understand before adding code.

### Era 1 — `foolbot.py` (commits 1–2)

A generic tabletop helper. One module-level `GameState` (`foolbot.py:33`)
holding one deck, one discard pile, and one dict of units, flushed to
`game_state.json` on every mutation.

Commands: `/newdeck`, `/draw`, `/roll`, `/place`, `/move`, `/board`.

Commit 2 re-themed the deck from a standard 52-card deck to a 72-card Foolish
deck — 6 suits (`$ ⚔ 〠 ⚒ ☯ 🃟`) × 12 ranks (`1`–`10`, `L`, `R`).

### Era 2 — `cogs/d12ball.py` (commit 3)

D12 Ball as an actual game, with real structure:

- A proper `commands.GroupCog` under the `d12ball` command group.
- `/d12ball create_game` provisions a private channel per game, named
  `d12ball-pbd{N}`, where `N` is derived by scanning existing channel names
  (`d12ball.py:82-95`).
- Permission overwrites lock the channel to the two players plus the bot
  (`d12ball.py:187-209`).
- Supports player-vs-player or player-vs-"AI opponent".
- An interactive `discord.ui.View` button for the coin toss (`d12ball.py:13-75`).
- Careful input validation, guard clauses, and `discord.Forbidden` /
  `HTTPException` handling around Discord API calls.

### The gap between them

**Era 1's state is global.** Not per-guild, not per-channel, not per-game.
`state` is a single module-level object shared across every server the bot is
in. If two `d12ball-pbd*` games run at once and both players call `/draw`,
they draw from the same deck and mutate the same board.

Era 2 builds isolated game rooms. Era 1 has no concept that rooms exist.

Any code that gives D12 Ball real per-game state has to resolve this. The two
plausible directions — scope Era 1's commands per channel, or absorb their
functionality into the cog and retire `foolbot.py`'s command set — lead to very
different work. **See 6.3.**

### Where the code stops

`create_game` builds the room, flips the coin, announces a winner — and ends.
There is no turn loop, no board representation, and no game state in the cog.
That is the live edge of the project and the most likely place for new code.

---

## 3. House style

The two files follow noticeably different conventions. `cogs/d12ball.py` is
newer and more deliberate; new code should match it.

| | `foolbot.py` | `cogs/d12ball.py` |
|---|---|---|
| Imports | `import os, random, json` on one line | one per line, stdlib / third-party grouped |
| Type hints | interaction only | `Optional[discord.Member]`, annotated returns |
| Call formatting | compact | multi-line, trailing commas |
| Error handling | none | guard clauses, `ephemeral=True` replies, API exception catches |
| Blank lines | sparse | generous |

Patterns worth preserving from `d12ball.py`: early-return guard clauses for
invalid input, ephemeral replies for errors so game channels stay clean, and
explicit `discord.Forbidden` / `discord.HTTPException` handling around any call
that touches the Discord API.

---

## 4. Verified facts

- All three Python files compile cleanly (`python -m py_compile`).
- No secrets in git history (scanned all commits).
- `docs/` did not exist before this note.
- Dependencies are **not** installed in this environment; the bot has not been
  run as part of this analysis.

---

## 5. Observations

### 5.1 Likely bugs

- **`cogs/_init_.py` is misnamed** — single underscores instead of
  `__init__.py`. It works only by accident: PEP 420 namespace packages let
  `cogs.d12ball` import without it. The file as written does nothing.
- **`foolbot.py:122-124` prints token material to stdout** on every startup —
  length and first 6 characters. Debug leftover.
- **`foolbot.py:126` calls `bot.run(TOKEN)` with no `None` guard.**
  `connection_test.py:11` has exactly that guard. Without it, a missing `.env`
  produces a confusing discord.py traceback instead of a clear message.
- **`setup_hook` performs a global `tree.sync()` on every start**
  (`foolbot.py:48`). Global syncs are rate-limited and can take up to an hour to
  propagate. Guild-scoped sync is the usual development pattern.
- **Global `state` with write-on-every-command and no locking.** Concurrent
  command invocations can interleave writes to `game_state.json`.

### 5.2 Papercuts

- `/draw` (`foolbot.py:74`) moves drawn cards straight into `discard` — there
  are no hands. Reads as a placeholder.
- `requirements.txt` is a `pip freeze` dump pinning transitive dependencies
  (`frozenlist`, `propcache`, `yarl`, …), so upgrading `discord.py` is manual.
- No `.env.example`.
- `foolbot.py` has no trailing newline.
- The "AI opponent" (`d12ball.py:60`) is a display string with no
  implementation behind it.

---

## 6. Open questions

### 6.1 Rules questions

These could not be answered from the source. The canonical rules live at
<https://propheticfools.notion.site/D12-Ball-6c9e1ea7ca61825391e881ec5fbfdca5>
and should be exported to `docs/d12ball-rules.md` so they are versioned
alongside the code.

1. **What do ranks `L` and `R` mean?** They sit where J/Q/K would in a standard
   deck. If they are directional (Left/Right), the deck is coupled to board
   geometry, which changes how a card should be modeled.
2. **Is `🃟` a real suit or a wild suit?** The other five (`$ ⚔ 〠 ⚒ ☯`) read as
   thematic factions; `🃟` is the joker glyph. If it is wild, `/newdeck`'s
   uniform 6×12 construction (`foolbot.py:60`) may be wrong.
3. **How does the d12 relate to the deck?** 12 ranks per suit and a 12-sided die
   is unlikely to be coincidence. Does drawing substitute for rolling, or are
   both used?
4. **Is the board bounded?** `/place` and `/move` (`foolbot.py:96,102`) accept
   any integers with no bounds checking — a unit can sit at (-9999, 500000).
   Pitch dimensions would determine whether that is a missing validation or an
   intentionally unbounded space.
5. **What happens after the coin toss?** Turn structure and win condition.

### 6.2 Project questions

- Is the "AI opponent" intended to become a real opponent, and if so — a rules
  engine or an LLM?
- Is `connection_test.py` still used, or superseded by the startup logging in
  `foolbot.py`?

### 6.3 The decision that gates most other work

**Is `foolbot.py`'s command set the future, or scaffolding to be absorbed into
the cog?** Whether new code extends those commands or replaces them follows
directly from this, and it is the highest-leverage unanswered question in the
repo.

---

## 7. Recommended next steps

1. **Commit the rules** to `docs/d12ball-rules.md`, with the Notion URL recorded
   as upstream. D12 Ball is still prototyping, so rules will keep moving —
   versioning them alongside the code makes each change a reviewable diff and
   removes the network dependency for future sessions.
2. **Reconcile the rules against the code** and answer §6.1. Several may turn
   out to be real bugs rather than open questions.
3. **Resolve §6.3** with the author before writing game logic.
4. **Then write `CLAUDE.md`.** Deliberately not written yet: the mechanical
   content (layout, run instructions, the global-state hazard, house style) is
   already captured here, and the domain content that would make it genuinely
   useful depends on answers above. A CLAUDE.md full of TBDs would mislead more
   than it helps.
5. **Keep rules-derived constants in one marked place** — deck composition,
   board dimensions, turn order. Given active prototyping, a rules change should
   be a small, obvious edit rather than a scattered one.

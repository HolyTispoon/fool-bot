# Gotchas: saves, migrations, and quiet failures

Design notes for fool-bot; the map is [CLAUDE.md](../../CLAUDE.md), the rules are [living-rules.md](../living-rules.md).

## Gotchas

- **A new field on `MatchState` goes in `MATCH_SAVED_FIELDS`, and the
  suite fails until it does.** That table in `d12ball/components.py` is
  a field's key, what a save older than it comes back as, and its
  copies in either direction; `to_dict` and `from_dict` both walk it,
  so the two cannot gain a field the other does not know about. It
  replaced 44 fields written out three times over — once on the
  dataclass and once in each half of the save — where landing in two
  of the three is invisible while the bot is up (the live game is the
  one in memory) and shows only as state quietly missing after a
  restart.
  - **`MATCH_EXPLICIT_FIELDS` is the other half of the guard, not a
    dumping ground.** It names the eighteen `to_dict`/`from_dict`
    still handle themselves, each because it says something a table
    cannot: the board and the two setups rebuild objects, the maneuver
    keys go through `legacy_maneuver_key`, `exhaustion` and
    `exhausted` are both filtered against `injured`, and the five
    coaching fields carry their `pending_substitution_*` fallbacks.
    `MatchStateSerializationTests` walks `dataclasses.fields` and
    fails on anything in neither place, so a forgotten field is a red
    suite rather than a bug in a game.
  - **`default` and `factory` are split the way `dataclasses.field`
    splits them.** A shared `[]` handed to every game that predates a
    field is the same bug here as anywhere else, and there is a test
    for it.
  - **The wire format is not the table's to change.** Every fallback
    in it exists because a half-finished game outlives the commit that
    added the field — see the rest of this section — so adding an
    entry is free and changing a key is not.
- **The team board is saved as `team_board` and read under either name.** It
  was called a player board until 2026-08-10 — `TeamBoardState`, `team_board`
  on `TeamSetup`, and the key in `basic_rules.json` and in every saved match.
  `TeamSetup.from_dict` falls back to `player_board`, because a game saved
  before the rename outlives it: both developers run the bot from their own
  tree against their own saves, and there were real games under the old key
  when it changed. Nothing writes the old name, so it dies out on its own —
  don't add a migration, and don't drop the fallback until you know no
  half-finished game predates the rename.
- **A game saved before the 2026-08-17 eight-team reshuffle is migrated
  on load, the same tolerant way.** Its players are named by the old
  `{color}_{slug(name)}` id and its two sides by the old color alone --
  both stopped matching the reshuffled catalog outright, which is what
  turned `/d12ball resume` into `ValueError('The setup does not match
  the team roster.')` on a real in-progress game.
  `gamesaves.d12ball.storage.migrate_legacy_game_data` fixes it inside
  `load_games`, before a `D12BallGame` is even constructed: it walks
  the whole saved dict once, replacing any string that is a
  reconstructed legacy id (built from the *current* catalog -- a
  player's species names the color they used to be fielded under
  exclusively, so nothing here is a hardcoded table of 36 pairs) with
  the player's new id, then remaps a legacy color's Team value to its
  **paired species team**, not the color itself -- that species roster
  is the one whose membership the old save actually matches, since the
  reshuffled color of the same name now holds different players. A
  game already in the new shape is left untouched, detected by whether
  the walk actually found a legacy id rather than by trusting a team
  value's name -- "orange" is a legal `Team` both before and after the
  reshuffle, just for a different roster. Don't add a migration for
  this a second time, and don't drop it until no half-finished game
  can predate the reshuffle.
  - **A rename is the one thing the reconstruction cannot derive, so
    `LEGACY_RENAMED_NAMES` writes those down.** A legacy id carries the
    name the player had when the game was saved; everything else about
    it is still derivable from the catalog, which is why that table is
    three entries and not thirty-six. Three orange players were renamed
    in 36250a9 on 2026-08-17 -- a day before the reshuffle and
    separately from it -- so a game older than *that* commit was
    already failing `TeamSetup.validate`, and the reshuffle migration
    shipped mapping six of its nine ids and leaving three. Add to the
    table whenever a player is renamed.
  - **A migration that fires and cannot finish is worse than one that
    does not fire**, which is what that half-mapped side was: the save
    still fails to load and the traceback names nobody.
    `_unmapped_legacy_ids` is the answer -- anything still shaped like
    `{legacy color}_{name}` after the remap goes to #logs at ERROR,
    naming the game and the ids, because the leftovers *are* the
    diagnosis and somebody has to add the entry. It reads the match
    state alone, since that is the only part of a save holding player
    ids and a game's own name could carry anything.
- **`data/d12ball_games.json` is runtime state and is deliberately untracked.**
  The bot rewrites it on every game action. It used to be committed, which
  meant it showed as modified more or less permanently and was a standing
  source of merge conflicts. Don't re-add it. Each developer's saved games are
  local to their own machine, and `data/` is created at startup if missing.
  `data/d12ball_games.tmp` — the file `save_games` writes and then renames over
  the JSON — had been committed by accident and was doing exactly the same
  thing. Both are ignored now; neither belongs in a commit.
- **Saving a match is `GameService.persist(game, match)`, not two lines** -- and from a running game it is the service's own `run` that calls it, once per click, so nothing in `cogs/` writes a match at all (see [game-service.md](game-service.md)).
  Writing the match onto its record and saving it is one step, and it
  appeared as `game.match_state = match.to_dict()` followed by
  `save_games(...)` at 111 sites. Separating the halves fails silently:
  a `save_games` with no `to_dict` above it writes whatever the record
  was already carrying, so the file keeps a state the game has moved
  past and nothing shows it until a restart reads it back.
  `save_games` on its own is still right for the forty-odd callers
  saving the *game* record alone — a message id, a tutorial flag, the
  finished status — which have no match to write. `send_turn_prompt`
  is the one deliberate exception, batching its `to_dict` with
  `turn_message_id` into a single later save.
- **`save_games` never raises, and a save failure never fails the turn.**
  It is called from around a hundred and fifty places, most of them part-way
  through resolving a turn, so a raise lands in whichever callback is running
  and `SafeView.on_error` tells the coach the click went wrong — after the
  maneuver has been announced and the board redrawn, so clicking again applies
  the turn twice. The live game is the one in memory; the file is what a
  restart reads. So an `OSError` is caught, logged, and swallowed. This is not
  hypothetical: one developer's checkout is on a mounted Google Drive letter,
  and when the mount went away mid-game every save raised `FileNotFoundError`
  from `mkdir` walking the path up to a drive root that no longer existed.
  `botstate.write_key` does the same for the same reason — silently, since it
  is on the startup path and its whole job is to keep #logs quiet.
  - **Only the first failure of a run reaches #logs.** The condition is one
    thing wrong repeated once or twice a click, and someone has to go and
    remount the drive; the ones behind it are console-only, and so is the
    line that says saving is working again. See "The level you log at decides
    who sees it".
  - **A file this run could not read is never written over** (`_load_unreadable`).
    The other half of the same mount going away is the bot *starting* while it
    is gone: `load_games` comes back empty, and once the mount returns the
    first save would replace every saved game with the one played since.
    Saving is blocked until the process is restarted, which is what wants
    doing anyway. "There is no file yet" is not that case, so a fresh clone
    saves normally.
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
- **Meeple name labels are sized per space, not once for the board.**
  `fit_meeple_labels` in `render.py` picks the largest size whose names all fit
  the space's width and whose lines fit between the tokens and the edge of the
  space, and `shorten_to_width` truncates anything still too wide. That replaced
  a fixed `FONT_MEEPLE` and a fixed 23px line offset, which overflowed the space
  borders whenever two meeples shared a space -- unavoidable once a formation
  can put four of a team's meeples on one.
- **The "View full image" button dies after 24 hours, by design.** Discord
  signs attachment URLs and stops honouring a signature a day after issuing it,
  so the link baked into a board or maneuver-reference message goes dead once
  the message sits untouched that long. The next board update re-cuts it --
  a few seconds after the board itself, during which the persistent message
  carries no link at all; see "Discord's rate limits" in [rate-limits.md](rate-limits.md) for why. This
  is an accepted trade for a one-tap link; the alternative was a callback
  button that fetches a fresh URL on click at the cost of an extra tap. See
  `add_full_image_button` in `cogs/d12ball.py`.
- **A bundled file's name is case-sensitive on one developer's machine and not
  on the other's.** `d12ball/images/emoji/exhaust.png` was tracked as
  `Exhaust.png` against a lowercase path in `render.py`: it opened on macOS,
  missed on Linux, and every icon loader swallows the `OSError` and returns
  None so the render can go on -- so the board simply came out with no
  exhaustion token, on one host only, for as long as nobody looked. CI caught
  it because CI is Linux. `Path.exists()` is not the check, since it answers
  True on the wrong case; the test in `D12BallFontTests` compares each declared
  path against its directory's own listing, which fails on both. Same reasoning
  as "Fonts" in [board-image.md](board-image.md) -- a graceful fallback is what makes a missing
  file quiet.

# The web app: what is next

**This is a worksheet, not a specification.** The web app shipped with
step 10 of [architecture-migration.md](architecture-migration.md) as a
second frontend *inside the bot's process*, over the bot's own games,
so that a game could be played from a Discord channel on one side and
a browser on the other. **On 2026-09-25 the author reversed that**:
the web app and the bot are two parallel systems that share the model
of the game and nothing else. A web coach plays web coaches (or the
AI); a Discord coach plays Discord coaches (or the AI); no game is
ever on both. This file is the plan under that decision: what it
changes in the shipped design, the decisions taken in its review, the
steps in the order they pay off, and one prompt per step written to be
handed to a Claude Code session as it is. Strike a step when it lands
and move what it settled into `docs/design/web-app.md`, which is
rewritten by step 1. **Nothing in it is a rule.**

## The decision, and what it changes

**Decided, 2026-09-25 (the author).** The web app is completely
separate from Discord. The only connection is the model of the rules:
`d12ball/` and the service over it. Two user interfaces, two
populations of players, two sets of games. No mixed games, ever.

What that changes in what shipped:

| Shipped (step 10) | Under the decision |
| --- | --- |
| The server starts in the cog's `cog_load` when `FOOLBOT_WEB_PORT` is set, on the bot's event loop. | **Its own process**, `python3 -m webapp`, with no Discord token and no bot. |
| One `games` dict and one save file, `data/d12ball_games.json`, shared by both frontends. | **Its own games and its own file**, `data/d12ball_web_games.json`, in the same format. Neither process writes the other's file. The one read across the line is the statistics (below): the bot reads the web file read-only when a coach asks for the numbers. |
| The cog's `GameService`, `RulesEngine` and `GameLocks`, handed in. | **Its own service, engine and locks**, built from the same model loaders the cog uses. |
| A coach is a Discord account; `/d12ball web_link` hands them a link. | **A room with a link; the first two in are its coaches, the rest observers, and a seat may change hands** (decision 1 below); the slash command goes. |
| `GameService.listeners` so a page sees a turn taken on Discord. | Kept, for the same reason one step over: a page sees the turn the *other web coach* took, and an observer sees both. |
| "One process, one service, a lock per game" (decision 5 of [web-app.md](web-app.md)), because two processes over one file would clobber each other. | **One process per file.** The reasoning stands; the file is what it was about. Two processes over two files do not touch. |
| The web app inherits `DiscordBatching` through the cog's service. | Gone with the shared service: the web app's service takes the default `Batching()`. |

What it costs, said plainly:

- **The thing the split was measured by is dropped.** Cross-frontend
  play was the proof that both frontends were over one model; a web
  coach could not tell whether the other coach was on Discord. The
  proof stands in the tests (`tests/test_web_app.py` presses every
  prompt fixture through the same service) and no longer in play.
- **Two populations of games**, and one report over both. The author
  wants the numbers from every web game visible on Discord, cut by
  source or taken together (review of 2026-09-25); that is step 6, and
  it is the one place the bot reads the web file. The archive export
  and the hub still see the bot's games only. Anything else the web
  app wants of the slash commands it builds over the model for itself
  (steps 9 and 11).
- **Two deployments on one machine.** The bot and the web app both
  run on the Windows checkout at `K:\` (decision 2), each with its own
  `data/` file, each restarted on its own.

What it buys:

- A bot restart does not touch a web game, and the reverse.
- No lock shared with `SafeView`, no listener cross-wiring, no
  mirroring of web turns into a channel, no stale-prompt problem
  between frontends. The web app's concurrency is two coaches and
  some observers on one room, which `gamelocks.GameLocks` already
  handles.

## A second repository?

**Still no.** Separate at runtime does not mean separate in source:
the web app imports `d12ball/`, `gamesaves/d12ball/service.py`,
`gamesaves/d12ball/storage.py` and `gamelocks.py`, and a rules change
(one commit to `docs/living-rules.md` and the model) has to reach both
frontends at once. A second repository means packaging the model and
versioning it, and every rules change becomes two PRs and a release.
One repository, two entry points (`foolbot.py`, `python3 -m webapp`),
and two fences: `webapp/` imports nothing from `cogs/` or `discord`
(`tests/test_web_purity.py`, already there), and `cogs/` imports
nothing from `webapp/` (step 1 adds it). If a separate repository is
ever wanted, the model becomes a package first and this file is not
the place that decides it.

## Decisions taken in review, 2026-09-25

Taken by the author as inline comments on PR #294, and recorded here
so nobody re-opens them.

1. **Rooms and seats, like Screentop.gg or playingcards.io.** A room
   is created and has a link of its own that stays good; the room is
   saved. Two coaching seats, **Coach 1** and **Coach 2**, renamed
   Home and Visitors once the coin has settled it and the game has
   started (the author revised the seat names on 2026-09-25 after
   the Charter's "Winning the toss" was raised: the winner of the
   coin chooses, so no seat is Home before it). **The first two
   people into a room are seated**: the creator is Coach 1, the next
   to arrive is Coach 2, and everyone after that is an **Observer**.
   A coach may leave a seat and take it again, before or during the
   game, so a person can jump in and out from different devices. An
   **admin** may kick a seat whose holder's device is gone; anyone in
   the room may become admin, but it is a deliberate act of its own,
   and a kick is gated by an "Are you sure?" confirmation.
   - **Underneath a seat is still a name and a signed cookie**, the
     recommendation the author took for the identity: on first visit
     the page asks for a name, the server issues an id (an `int` the
     record takes the way it takes a Discord id) and sets a cookie
     carrying `{id, name}` with an HMAC under `FOOLBOT_WEB_SECRET`,
     stored nowhere. A seat holds that id in the room's record
     (`player_1_id` or `player_2_id`); coming back with the cookie
     finds the seat still yours. A cookie is per device, which is why
     "from another device" is leave-and-take (or kick-and-take): the
     new device is a new identity, and the seat takes it. With no
     secret set, identities die with the process, which is the same
     safe default the links had.
   - **What the record has to learn.** Its lobby moves as written
     take seat 2 only, shift the other coach into seat 1 when the
     creator leaves, refuse the only coach leaving, and refuse every
     move once the game has started. A room needs a seat to change
     hands at any time, without the other seat moving: two record
     methods, `take_seat` (whichever seat is free, or the named one)
     and `vacate_seat`, allowed before and after kickoff, refusing
     with `RuleRefusal` when the seat is held by somebody else or
     there is none free. Safe mid-game because everything the match
     keeps about a side is by player *number* (`home_player_number`,
     `coin_winner_player_number`), never by id, and
     `refresh_player_names` already re-reads the names. `player_1_id`
     becomes `Optional[int]`, `None` only after a vacate, so every
     existing save loads unchanged. The Discord lobby keeps its own
     moves untouched. Its own commit, reviewed as a change to the
     record's rules.
   - **Roles are the frontend's.** Who is admin in a room, and who is
     watching, is web state in the web app's own file
     (`data/d12ball_web_rooms.json`), never on the game record: the
     save format is the contract and a room role is not a fact about
     the game. A kick is the frontend's authorisation (the admin) over
     the record's rule (`vacate_seat` for the seated id), the way a
     Discord helper's `manage_channels` gates a click the record then
     judges (ARCHITECTURE.md, "Keep Discord authorization ... in the
     Discord frontend").
2. **Where the web process runs: the same Windows machine as the bot,
   the `K:\` checkout.** One `git pull` updates both, one `data/`
   folder holds both files, and the tunnel is on a machine that
   already runs all day. Step 5 is written for it.
3. **The wire tree stays, and the page reads it.** `_state` answers
   with `result.to_dict()` and `prompt.to_dict()` and `present.py`
   reads the dicts, so `tests/test_wire_shapes.py` is testing a
   format with a consumer. Step 10.

## The steps

In the order they pay off. Each is one branch off an up-to-date
`main`, one PR against the template, the suite green, the six
safety-net tests untouched unless the step says why. None changes the
save format. None adds a rule to `webapp/`. Until step 3 lands there
is nothing a web coach can play, since step 1 removes the only way in
that existed; steps 1 to 3 are one sprint.

| # | Step | Size |
| --- | --- | --- |
| ~~1~~ | ~~Cut the cord: its own process, file, service and engine~~ -- landed; what it settled is in `docs/design/web-app.md` | medium |
| ~~2~~ | ~~Rooms, seats and observers~~ -- landed; what it settled is in `docs/design/web-app.md`, "Rooms, seats and who holds them" (and the AI in either seat, `ai_seats`) | medium |
| ~~3~~ | ~~The room's table: setup, kickoff, the rematch~~ -- landed; what it settled is in `docs/design/web-app.md`, "The room's table" | large |
| ~~4~~ | ~~Chat in the room~~ -- landed; what it settled is in `docs/design/web-app.md`, "Chat" | small |
| ~~5~~ | ~~Run it for real, and write down how~~ -- the how landed: `docs/design/collaboration.md`, "Running the web app", and `scripts/run_web_app.ps1`; the playtest below is the author's to run | a day, little code |
| ~~6~~ | ~~The web games' numbers on Discord, cut by source~~ -- landed; what it settled is in `docs/design/clock-and-records.md`, "What the statistics are, and what they are not" (the source cut, and the read across the line), and `docs/design/web-app.md`, "Its own process, its own file" | small |
| ~~7~~ | ~~The dice on the page~~ -- landed; what it settled is in `docs/design/web-app.md`, "The dice", and `docs/design/board-image.md`, "The matchup image" (the briefs below the renderer) | medium |
| ~~8~~ | ~~The prompt's pictures~~ -- landed; what it settled is in `docs/design/web-app.md`, "The prompt's pictures", and `docs/design/board-image.md`, "The matchup image" (the rest of both briefs below the renderer) | medium |
| 9 | What Discord has that the page lacks: my rooms, resume, abandon, stats | medium |
| 10 | The page as a thing to play on; the wire tree; the tests the survey found missing | medium |
| 11 | The reading room: the rulebooks and the player aids | medium |
| -- | Later, and not now | -- |

### Claiming a step

**Claim a step before starting it**, whoever you are: either developer,
a Claude Code session, or the cloud routine that starts the next step
when the last one merges (`trig_01TfqdFJ3jQjC4XTFh7qqwZe`). Two people
building the same step is a whole step thrown away.

```bash
python3 scripts/claim_web_step.py <n>
```

A claim is the branch `web-step-<n>` on origin: one empty commit on
top of main naming who claimed it. It is pushed with
`--force-with-lease=refs/heads/web-step-<n>:`, which git reads as
"this branch must not exist yet", so of two claims made at once
exactly one lands and the other is rejected. It is the branch you work
on, too. The script refuses a step that is struck below, or already
claimed.

**What counts as a claim**, and what the routine checks before it
starts anything:

- a branch on origin named `web-step-<n>` or `web-step-<n>-<anything>`;
- an open PR, draft or not, titled `Web app step <n>: ...`.

Work done on a branch named anything else is invisible, so claim
first. A step whose last PR was closed without merging is treated as
rejected: the routine does not pick it up again until somebody claims
it by hand. If you stop working on a step, release it with
`python3 scripts/claim_web_step.py <n> --release` (your own claim
only). A step lands when its PR strikes its number in the table
below, and the next unstruck number is the next step.

### 1. Cut the cord

**Landed** (branch `web-step-1-cut-the-cord`). What it settled is in
`docs/design/web-app.md`, "Running it", "What it may not do" and "Its
own process, its own file"; the prompt below is kept for the record.

**What it is.** `webapp/` becomes a program of its own. It builds a
`RulesEngine` from the same four loaders the cog uses
(`load_player_catalog`, `load_basic_ruleset`, `load_maneuver_catalog`,
`build_ai_strategies`), loads its own games from
`data/d12ball_web_games.json` through `storage.load_games`, hands
`GameService` its own dict, the default `Batching()` and a `save` that
writes that file, makes its own `GameLocks`, and runs the aiohttp app
on its own loop from `python3 -m webapp`. The cog's `start_web_app`,
`cog_unload`'s stop, the `web_app` attribute and `/d12ball web_link`
are deleted.

**The one model-side change.** `storage.py` hard-codes `GAMES_FILE`
and keeps two module globals (`_save_failing`, `_load_unreadable`)
about *that* file. It grows a path parameter, `load_games(path=...)`
and `save_games(games, path=...)`, defaulting to the bot's file so
nothing the bot does changes, and the two flags become per path. The
save *format* does not change; the migrations run on both files.
Its own commit, reviewed as a change to the store. Step 6 reads the
web file through the same parameter.

**Two fences.** `tests/test_web_purity.py` already ratchets that
`webapp/` imports no `cogs` or `discord`. It grows the reverse: no
module under `cogs/`, and not `foolbot.py`, imports `webapp`. The bot
must start and run with the `webapp/` directory deleted.

**What must not happen.** The web app writing the bot's file, or the
bot writing the web app's. The default path stays the bot's, so the
web app passes its own explicitly, and a test asserts the two
constants differ and that `webapp` never names the bot's.

**Done when** `python3 -m webapp` serves the page with no
`DISCORD_TOKEN` in the environment, `python3 foolbot.py` runs with
`webapp/` removed, `tests/test_web_app.py` passes unchanged in what it
asserts about play, and `docs/design/web-app.md` is rewritten for the
decision.

**Prompt.**

```text
Read CLAUDE.md, docs/web-app-next.md (the decision at the top, and
step 1), docs/design/web-app.md, docs/design/game-service.md and
docs/design/gotchas.md ("the swallowed save"). Branch off an
up-to-date main.

Decision (2026-09-25): the web app is a separate system from the bot.
They share the model and nothing at runtime: not a process, not a
games file, not a service. No mixed games. Make it so, in four
commits.

1. storage.py takes a path. gamesaves/d12ball/storage.py hard-codes
   GAMES_FILE and keeps _save_failing and _load_unreadable about it.
   Add `path: Path = GAMES_FILE` to load_games and save_games, keep
   both flags per path (a small dict keyed by path, or a GameStore
   class with the two module functions kept as thin calls on a
   default instance), and change nothing about the format, the
   migrations, the temp-file rename or the never-raise contract.
   tests/test_game_storage.py's cases run against a second path too.
   Add WEB_GAMES_FILE = DATA_FOLDER / "d12ball_web_games.json" beside
   GAMES_FILE. Own commit, reviewed as a change to the store.
2. The web app stands alone. webapp/__main__.py (and a `main()` in
   webapp/server.py) that: loads .env the way foolbot.py does; builds
   a RulesEngine from load_player_catalog, load_basic_ruleset,
   load_maneuver_catalog and build_ai_strategies exactly as
   cogs/d12ball/core.py builds the cog's (read lines ~439-485 there
   and copy nothing Discord); loads games from WEB_GAMES_FILE; builds
   GameService(engine, games, save=lambda g: save_games(g,
   WEB_GAMES_FILE)) with the default Batching(); builds its own
   GameLocks; starts WebApp and runs the loop until interrupted.
   FOOLBOT_WEB_PORT defaults to 8080 when unset; say so in the docs.
   Logging: console only, through botlog's console setup if it
   imports without discord, otherwise logging.basicConfig; the #logs
   mirror is the bot's.
3. The bot forgets the web app. Delete start_web_app, the stop in
   cog_unload and the web_app attribute from cogs/d12ball/core.py,
   and /d12ball web_link from cogs/d12ball/slash_commands.py, with
   their tests. Grep cogs/, foolbot.py and tests/ for "webapp" and
   "web_app" and leave nothing but the web app's own tests.
4. Fences and docs. tests/test_web_purity.py grows the reverse
   ratchet: no module under cogs/ and not foolbot.py imports webapp
   (same AST walk). tests/test_web_app.py: its module docstring's
   "a turn taken on Discord reaches a page" becomes "the other
   coach's turn reaches a page", and the test that plays the other
   side through the service stays as it is (it never imported the
   cog). The listeners docstring in service.py loses its Discord
   sentence. Rewrite docs/design/web-app.md: "Running it" (the
   command, the variables, the file), "What it may not do" (both
   fences), "One process, one service" becomes "Its own process, its
   own file" with the reasoning from docs/web-app-next.md's table,
   and "What a page is handed" loses the Discord sentence. Update the
   CLAUDE.md rows for webapp/, gamelocks.py, gamesaves/d12ball/
   storage.py and the "Running it" block at the top. Check
   docs/design/collaboration.md and docs/design/recovery.md for
   sentences that assume the web app is in the bot's process.

Verify by hand and say so in the PR: `python3 -m webapp` with no
DISCORD_TOKEN serves / and a 404 for a game id; `python3 foolbot.py`
imports with the webapp/ directory moved aside (it will fail on the
token; the import is the check). Full suite green. PR against the
template; the "Architecture change" line applies.
```

### 2. Rooms, seats and observers

**Landed** (branch `web-step-2`). What it settled is in
`docs/design/web-app.md`, "Who is on the other end" and "Rooms, seats
and who holds them"; the prompt below is kept for the record. **The
author's review added to it** (2026-09-26): an empty seat is not the
AI's (`D12BallGame.ai_seats`), the AI may hold either seat, anybody
seated may put it in an empty one, an admin may kick it out for a
person to take over, and an admin may give the role up.

**Why now.** Step 1 deletes `/d12ball web_link`, the only way a
person was ever named to the web app. Nothing on the web can be
played until the page knows who is reading it and which seat they
hold.

**What it is, under decision 1.** Four pieces:

- **The identity**: `webapp/identity.py`, a `Coach(id: int, name:
  str)` in a signed cookie, `coach_for(request)` that reads and
  verifies it, and `POST /api/me` that takes a name and sets it (a
  new id the first time; a rename keeps the id).
- **The room**: a game record, which already has everything a room
  needs (an id, a number, a name, two seats, a status, settings), and
  a link `/room/{game_id}` that stays good for as long as the record
  exists. `POST /api/rooms` creates one through `create_game` with
  `in_lobby=True`, the creator in seat 1 as today.
- **The seats**: the record's two new methods, `take_seat` and
  `vacate_seat` (decision 1), through two service doors. Arriving at
  a room with a seat free takes it, so the second person in is Coach
  2; anyone after is an observer, who sees everything both coaches
  are shown except a side's secrets (the other hand, the shootout
  orders, which `present.py` already withholds from anyone but that
  seat) and answers nothing. Leave and take work before and after
  kickoff. Seats are labelled Coach 1 and Coach 2 until the coin, and
  Home / Visitors from the moment the record's `home_player_number`
  says so. `Viewer` becomes "which seat of *this* room is this coach
  in, if either", by comparing the cookie's id with the record's two
  ids, the same comparison `SafeView.may_act_for` makes with a
  Discord id.
- **The roles**: `webapp/rooms.py`, the web app's own state per room
  (admin ids, observers seen) in `data/d12ball_web_rooms.json`, its
  own file, never the save. "Become admin" is a button of its own with
  a confirmation; an admin sees a "Kick" on each held seat, gated by
  "Are you sure?", which calls `vacate_seat` for the seated id.

**What must not happen.** A second gate. What a seat may *answer* is
still `asked_sides`, read by `present.py`; the identity says which
seat, never whether the seat may act. A rule about seats in
`webapp/`: who may take, whether a held seat refuses, are the
record's (`take_seat`/`vacate_seat` refuse with `RuleRefusal`) and the
page shows the sentence. And a room role on the game record.

**Prompt.**

```text
Read CLAUDE.md, docs/web-app-next.md (decision 1 and step 2),
docs/design/web-app.md (as rewritten by step 1), docs/design/
hub-and-lobby.md, docs/design/permissions.md and docs/design/
game-service.md ("setup and the lobby"). Branch off an up-to-date
main. Decision 1 as recorded: rooms with a persistent link; the
first two in are seated as Coach 1 and Coach 2 and everyone after is
an observer; a seat may be left and taken again before or during the
game (so a person can change devices); an admin may kick a seat
behind a confirmation, and anyone may become admin by a deliberate
act; the seats read Home / Visitors once the coin has settled it.
Four commits.

1. webapp/identity.py: Coach(id: int, name: str); serialise it into
   one cookie (base64 JSON + HMAC-SHA256 under keys.secret(), compared
   with compare_digest); coach_for(request) -> Optional[Coach], None
   for no cookie, a bad signature or a malformed payload; issue(name)
   -> Coach with a fresh id (a random positive int that fits the
   record's int the way a Discord id does; say in a comment why it is
   not a sequence: nothing stores the last one). A name is 1-32
   characters after strip; refuse otherwise with a 400 and a
   sentence. Routes: POST /api/me {name} sets the cookie (Secure when
   the request is HTTPS, HttpOnly, SameSite=Lax, a year) and answers
   {id, name}; GET /api/me answers the coach or null. A rename keeps
   the id.
2. A seat that changes hands. Read D12BallGame.lobby_join,
   lobby_observe and lobby_leave (d12ball/game.py) and leave them as
   they are: the Discord lobby depends on the creator's seat shifting
   and on the moves closing at start. Add two methods beside them,
   with no require_lobby: take_seat(user_id, user_name, seat=None)
   takes the free seat (or the named one) and refuses with
   RuleRefusal when both are held, when the seat named is held by
   somebody else, when the person already holds a seat, or on a
   one-player game (test_game, tutorial) for seat 2, the way
   lobby_join does; vacate_seat(user_id) empties whichever seat that
   id holds and refuses if it holds none. Neither shifts the other
   seat. player_1_id becomes Optional[int]; None is written only by
   vacate_seat, so every existing save loads unchanged. Check every
   predicate that reads player_1_id or player_2_id (game_participant_
   ids, is_solo_game, may_act_for, the startup sweep, stats.game_
   category, coin_winner_player_number's legacy fallback) copes with
   None and with an id that changed mid-game; the match keeps its
   sides by player number, so a changed id must change nothing about
   the position -- add a test that takes seat 2 with a new id
   mid-match and the next prompt is unchanged, and that
   refresh_player_names picks the new name up. Service doors:
   GameService.take_seat and vacate_seat, load, one change, save
   once. Own commit, reviewed as a change to the record's rules; say
   in the PR body which predicates you checked.
3. Rooms, seats and roles on the web. POST /api/rooms -> create_game
   with in_lobby=True and the creator in seat 1, answering the room
   id; the page goes to /room/{id}, which serves game.html. On a
   coach's first GET of a room with a free seat, the server takes it
   for them (the second person in is Coach 2) -- through
   GameService.take_seat, so the record still judges it; anyone after
   is an observer. POST /api/room/{id}/seat/{take|leave} over
   take_seat / vacate_seat with the cookie's id and name, RuleRefusal
   -> 409 with the sentence. webapp/rooms.py: the web app's own state
   per room -- admin ids and observers seen -- in
   data/d12ball_web_rooms.json, written on change, read at start,
   never the save (see gotchas.md on data/ and do what the journal
   will do in step 10). POST /api/room/{id}/admin makes the caller an
   admin (the page confirms first: "Take the admin role for this
   room?"); POST /api/room/{id}/seat/kick {seat} is refused unless
   the caller is an admin, and calls vacate_seat for the seated id;
   the page's Kick button confirms "Are you sure?" before posting.
   _state gains "room": both seats (name or null, "yours" for the
   viewer's), the observers' count, whether the viewer is admin, and
   the viewer's role: "observer", "coach" (and, once the coin has
   settled it, "home" or "visiting", read off the record's
   home_player_number / visiting_player_number, never worked out
   here). A viewer who is nobody yet is shown the name form first.
   Seat labels: "Coach 1" / "Coach 2" until the coin, then "Home Team
   Coach" / "Visitors Team Coach". An observer is offered no controls
   (asked_sides already does this) and never a side's secrets
   (present.py already withholds them; add a test that an observer's
   MANEUVER_ACTION and shootout payloads carry neither side's).
4. Tests in tests/test_web_app.py (replacing the key-based ones): a
   cookie round-trips; a tampered cookie is nobody; the creator is
   Coach 1 and the second arrival is seated as Coach 2 with their own
   controls; a third arrival is an observer with none; leaving seat 2
   frees it and a new cookie (a "second device") takes it and gets
   the same controls, before kickoff and again mid-match; a seat
   held by somebody else refuses a take with the record's sentence;
   a kick by a non-admin is 403, by an admin vacates the seat; the
   room link and the admin role answer after a restart (load both
   files again and open the room).

Docs: docs/design/web-app.md gains "Rooms, seats and who holds them"
with the cookie derivation, why nothing is stored, why a seat may
change hands mid-game and what keeps that safe (sides by number),
why the roles are the frontend's file and not the record's, and why
the seat names follow the coin. PR against the template; the "New
persisted field" line applies to player_1_id's None (an old save
never carries it; say so).
```

### 3. The room's table: setup, kickoff, the rematch

**Landed** (branch `web-step-3`). What it settled is in
[design/web-app.md](design/web-app.md), "The room's table": the front
door's two lists, the table drawn off readings on
the record (`open_settings`, `teams_open_to`, `coin_is_owed`,
`home_choice_owed_by`, `home_choice_rail`), the rematch as
`GameService.rematch`, and why there is no separate Begin -- the
match has no reading of "dealt, not begun", so `begin` runs in the
request that deals it, and the author settled on 2026-09-26 that no
Begin button is needed. The tutorial is a training game however it is
made (`D12BallGame.pin_tutorial`, the author, the same day).

**The author reversed the front door's "two ways in" on 2026-09-25**:
`POST /api/rooms` no longer takes `ai` or `tutorial` -- every room
opens the same way, in its lobby, and both are the table's own
settings from there (`seat_ai`/the `ai` seat route, and the `tutorial`
setting), the way a two-coach room always worked. The front door's
button reads "Create a new game room" rather than naming Dinky or a
checkbox. The same review renamed a web room's board title from `PBD`
to `PBW` (`WebApp._title`, `webapp/static/*.js`) -- `PBD` stays
Discord's -- made a room's own row in "Your rooms" clickable end to
end rather than only its name, and gave identity a rename and a leave
(`DELETE /api/me`, `identity.clear_cookie`) beyond the front door's
name form: "Change name" and "Leave the app" in a room, "Save name"
and "Leave" at the front door. Leaving forgets the cookie only -- a
seat held under it stays held, the way another device already left it
alone.

**What it is.** Everything between two seats claimed and the first
prompt, and the rematch at the end, all of it over service methods
that exist: `start_lobby`, `configure`, `pick_team`, `flip_coin`,
`choose_home_or_visiting`, `begin`, and `discard_game`. Each is a thin
door over a rule on `D12BallGame` that refuses with `RuleRefusal`;
`tests/test_game_service_setup.py` walks the whole path with no
channel and is the script for this step.

Three pieces:

- **The front door** (`/`): my rooms (the web file's games naming my
  id, by status), open rooms (a room with a seat free), and two
  buttons: open a room, play the AI now. The tutorial is a checkbox
  on either, since `create_game` takes `tutorial=`. A room against
  the AI has one seat and Dinky in the other.
- **The table**, in the prompt's place before kickoff: the settings
  (`GAME_SETTINGS` and their values), both seats, which teams this
  seat may pick (asked of the record), the coin, home or visiting,
  and Begin. Every question is the record's or the service's; if one
  is not exposed, it grows a method both frontends read. Observers
  see the table and press nothing on it.
- **The rematch**: `present.py` gains the one builder it lacks,
  `GAME_OVER`, whose control does what `RematchView` does through the
  service and sends everyone in the room to the new room.

**What must not happen.** A lobby rule in `webapp/`. The record
refuses and the page shows the sentence. A page that greys a team
because it worked out the pairing exclusions itself is the failure
mode; `excluded_teams` is the record's.

**Prompt.**

```text
Read CLAUDE.md, docs/web-app-next.md (step 3), docs/design/web-app.md,
docs/design/game-service.md ("setup and the lobby"),
docs/design/hub-and-lobby.md, docs/design/coaching-choice.md and
docs/design/tutorial.md. Read tests/test_game_service_setup.py end to
end: it is the path this step puts on the web. Branch off an
up-to-date main. Assumes step 2 (rooms and seats) has landed. Three
commits.

1. The front door and the AI room. GET /api/rooms answers this
   coach's rooms by status and the rooms with a seat free, each as
   {id, number, name, status, seats, observers, tutorial}; the index
   page draws it: my rooms, open rooms, "Open a room", "Play Dinky",
   a tutorial checkbox. "Play Dinky" is POST /api/rooms with
   {ai: true}: create_game with this coach in seat 1 and no lobby,
   which the service already fills with the default AI (do not name
   Dinky in webapp/). DELETE /api/room/{id} over discard_game for a
   room that never started (its ValueError is the service's; map it
   to 409).
2. The table. POST /api/room/{id}/table/{start|configure|pick_team|
   flip_coin|choose} over start_lobby, configure, pick_team,
   flip_coin and choose_home_or_visiting, building Team and
   HomeChoice from the wire in the route (d12ball/wire.py's reason
   for Action.from_dict), and POST /api/room/{id}/begin over begin.
   _state before kickoff gains "table": GAME_SETTINGS with their
   current values and whether this viewer may change them; both
   seats with team or null; the teams this seat may pick, asked of
   the record (excluded_teams and the pool -- if no method answers
   "which may this seat pick" in one call, add it to D12BallGame and
   make the cog's setup view read it too); whether the coin may be
   tossed and by whom; whether home/visiting is owed and by whom;
   whether begin is available. The page draws the table in the
   prompt's place from "table" and nothing else; an observer sees it
   with every control disabled.
3. The rematch. present.py gains the GAME_OVER builder: one control,
   "Rematch", posting to POST /api/room/{id}/rematch, which does what
   cogs/d12ball_views/setup.py's RematchView does through the service
   (a new room with the finished game's settings and the same two
   seats, or the AI) and answers the new room id; every page in the
   old room follows it (put the new id in the old room's state).
   Remove the GAME_OVER exemption in tests/test_web_app.py.

Tests, over HTTP: two coaches arrive and are seated, start, both
pick, one tosses, the winner chooses, begin opens the pre-kickoff
Coaching Choice and the first prompt, and the seat labels read Home /
Visitors from the coin on; an AI room reaches the first prompt with the AI's
pick drawn by the engine; a refused pick (excluded pairing) is a 409
carrying the record's sentence and writes nothing; an observer's
table presses are 403; a finished game (the GAME_OVER fixture)
rematches into a new room the same two coaches hold. Suppress saves.

Docs: docs/design/web-app.md "What it does not do yet" loses "It does
not create games" and gains "The room's table" with why every
question on it is the record's. PR against the template.
```

### 4. Chat in the room

**Landed.** The room's chat is `webapp/chat.py`, in its own file
(`data/d12ball_web_chat.json`), posted to `POST /api/room/{id}/chat`
under the cookie's name and riding on the poll; what it settled is
`docs/design/web-app.md`, "Chat" (under "What a page is handed").

**Why here, and why at all.** On Discord the channel is the chat, and
the game's own messages sit in it between the coaches' own. A room
on the web has nothing of the kind: two coaches and their observers
have no way to say "one moment" or "good goal" without another app
open. The author asked for it (2026-09-25). It comes before the
playtest because a playtest with three people and no way to talk in
the room is a playtest of the wrong thing.

**Partly done by the page's rebuild (2026-09-25).** The chat panel
is on the page, under the journal, and works: `POST
/api/game/{id}/chat`, anybody reading may post (a coach under their
name off the record, anybody else as "Observer"), plain text, riding
on the poll with a `chat_since` cursor, bounded at 200 messages. It is
in memory, like the journal, and keyed by game rather than room. What
this step still owes is the rest of what is below: the room's own
file, and the name on a person's cookie in place of the seat's.

**What it is.** A chat panel beside the journal, one message list
per room, everyone in the room may post (coaches and observers, by
the name on their cookie), and the messages ride on the poll the
page already makes. It is frontend state like the room roles: kept
in the web app's own file (`data/d12ball_web_chat.json`, or a
section of the rooms file), bounded per room the way the journal is,
never on the game record, never read by the model. A message is
plain text, escaped on the way out; nothing in it is rendered as
markdown or tokens, because it is not the model's voice.

**What it must not do.** Say anything about the game. A chat line
that reads "X scored" is the journal's, and the journal already
says it; the chat is people talking. And it must not become a second
transport: the poll carries it, with a `since` cursor like the
journal's, and a websocket stays in "Later".

**Prompt.**

```text
Read CLAUDE.md, docs/web-app-next.md (step 4), docs/design/web-app.md
(as rewritten by steps 1 and 2, "What a page is handed" and "Rooms,
seats and who holds them") and docs/design/gotchas.md ("data/ is
untracked runtime state"). Branch off an up-to-date main. Assumes
step 2 (rooms, seats and the cookie identity) has landed. Two
commits.

1. webapp/chat.py: a Chat per room -- a deque of Message(id, coach_id,
   name, text, at) with a bound (CHAT_LENGTH, 200 like the journal) --
   held by the WebApp, written on every post to
   data/d12ball_web_chat.json (or a "chat" section of the rooms file
   from step 2, whichever step 2 chose; one file for all room state
   is fine), read at startup; a write failure is logged and never
   fails the request, like save_games. A message's text is 1-500
   characters after strip, refused otherwise with a 400. Nothing in
   webapp/chat.py imports the model beyond the game id.
2. Routes and page. POST /api/room/{id}/chat {text} posts as the
   cookie's coach (403 with no cookie; anyone in the room may post,
   observers included). GET /api/room/{id} (the state) gains
   "chat": the messages since a `chat_since` cursor the page sends,
   each {id, name, text, at, yours}, so the chat rides on the poll
   the page already makes; no new endpoint for reading and no
   websocket. The page: a panel beside the journal (below it on one
   column) with the messages, the poster's name in the seat's colour
   where they hold one and plain for an observer, a one-line input
   and Send (Enter sends); it scrolls to the newest like the journal;
   text is set with textContent, never innerHTML -- nothing in a
   chat line is markdown or a token.
3. Tests in tests/test_web_app.py: a coach posts and both coaches and
   an observer see it on their next poll; an observer may post; no
   cookie is 403; a 501-character message is 400; the cursor returns
   only newer messages; the bound holds; the chat survives a restart
   (reload the file); a message containing "<b>" arrives escaped on
   the page's wire and is never in the game's save. A full test run
   must not create data/.

Docs: docs/design/web-app.md gains "Chat" under "What a page is
handed": why it is frontend state, why it rides on the poll, why it is
never rendered as the model's voice. PR against the template.
```

### 5. Run it for real, and write down how

**Landed** (the written half): how the web app is run on the `K:\`
host -- the `.env`, why the secret and HTTPS, the restart script beside
the updater, and the Cloudflare Tunnel on `play.d12ball.com` -- is in
[design/collaboration.md](design/collaboration.md), "Running the web
app", with `scripts/run_web_app.ps1`; the cookie is `Secure` behind
the tunnel on its forwarded scheme (`identity.came_over_https`). None
of it has been run on that host or through the tunnel yet; the
playtest checklist at the end of this section is the part only people
can do.

**Why here.** After step 4 a web game can be played end to end and
the people in the room can talk, and
nothing below is worth building until two people have played one
through, because that is what says which gap actually stops play.

**What it is.** On the `K:\` checkout (decision 2): `.env` with
`FOOLBOT_WEB_PORT`, `FOOLBOT_WEB_SECRET` (identities die with the
process without it) and `FOOLBOT_WEB_URL`; the port behind something
that terminates TLS and gives it a public name; `python3 -m webapp`
kept running the way the bot is (the same PowerShell wrapper as
`update_main_bot.ps1`, or a scheduled task); two people play a game
through from a room link and note where it broke. The cookie is the
credential, so the page must only ever be served over HTTPS, which is
the tunnel's job.

**Which tunnel.** Hosting, not code, and not verified from here. A
Cloudflare Tunnel, Tailscale Funnel or ngrok each gives a Windows host
a public HTTPS name without opening a port on the router; pick the
one whose account the author already has. **Taken, 2026-09-26: a
Cloudflare Tunnel, on the author's `d12ball.com`**, at
`play.d12ball.com`.

**Prompt.**

```text
Read CLAUDE.md, docs/design/web-app.md ("Running it") and
docs/design/collaboration.md. We are deploying the D12 Ball web app
for the first time as its own process on the Windows checkout at K:\,
beside the bot. Little or no Python.

1. Write a "Running the web app" section into
   docs/design/collaboration.md: the command (python3 -m webapp), the
   FOOLBOT_WEB_* variables and what each is for, why
   FOOLBOT_WEB_SECRET must be set (cookies die with the process
   otherwise), why the page must only be served over HTTPS (the
   cookie is the identity), how the process is kept running beside
   the bot on that machine (read update_main_bot.ps1 and mirror it),
   that the two processes share the checkout and the data/ folder but
   have separate files and separate restarts, and the exact steps to
   expose the port through <TUNNEL> including where FOOLBOT_WEB_URL
   comes from. Say what you could not verify from here.
2. If keeping it running needs a script, add scripts/run_web_app.ps1
   beside update_main_bot.ps1; nothing one-off.
3. Add a "Playtest checklist" under step 5 of docs/web-app-next.md:
   one person opens a room and shares the link, the other arrives and
   is seated as Coach 2, a third person arrives as an observer; setup
   through kickoff, a goal, a loose ball, a coaching window; one
   coach leaves the seat on a laptop and takes it again on a phone
   mid-game; the observer becomes admin and kicks a seat whose device
   was closed, and the kicked coach takes it back; the end and a
   rematch; for each, note whether all three pages agreed about whose
   turn it was and what happened, and what each coach wished the page
   had shown.
4. PR against the template; docs and one script, say so under
   Testing.
```

#### Playtest checklist

Three people, three devices, one room, on the public HTTPS name. For
each line note two things: **whether all three pages agreed** -- whose
turn it was, what had just happened, the score and the clock -- and
**what each coach wished the page had shown** at that moment. Where a
page disagreed, note which one and reload it before going on: a page
that is right after a reload is a push that went missing, one that is
still wrong is a reading that differs.

1. **The room.** Coach 1 opens a room from the front door and shares
   its link (check it starts with `FOOLBOT_WEB_URL`).
2. **The second arrival.** Coach 2 opens the link on their own device
   and is seated as Coach 2 without asking for it.
3. **The observer.** A third person opens the same link and arrives
   as an observer: sees the table and the board, is offered no
   control that answers the match.
4. **Setup through kickoff.** Settings, teams, the coin, home or
   visiting, the deal -- every question asked of the right coach, and
   the observer seeing each answer land.
5. **A goal.** Both coaches' and the observer's scores and logs agree
   on who scored and the kickoff that follows.
6. **A loose ball.** Where it landed, who is asked, and the contest,
   on all three pages.
7. **A coaching window** (a time out, or halftime): the window offered
   to the coach it belongs to, and the other page showing it waiting.
8. **Changing devices mid-game.** One coach leaves the seat on a
   laptop and takes it again on a phone, mid-turn if possible; the
   prompt they were owed is waiting for them on the phone.
9. **A kick.** That coach closes the phone without leaving the seat.
   The observer is made admin and kicks the seat; the kicked coach
   comes back and takes it again. Nobody else's page lost its place.
10. **A restart.** Once, mid-game, run `run_web_app.ps1` again: every
    page comes back to the same position and nobody is signed out
    (this is what `FOOLBOT_WEB_SECRET` is for).
11. **The end and a rematch.** Full time (or the shootout), the final
    board, and the rematch opening a room of its own -- note who lands
    in it and in which seat.

Line 10 is not in the step's prompt; it is the one check of the
secret, and it costs a minute.

### 6. The web games' numbers on Discord, cut by source

**Landed.** `stats.game_source` and the `SOURCE_*` cut, and a `source`
option on the four scoped `/d12ball stats` commands that reads
`WEB_GAMES_FILE` at call time and never writes it: see
`docs/design/clock-and-records.md`, "What the statistics are, and what
they are not", and `docs/design/web-app.md`, "Its own process, its own
file". Whether the web cuts are gated to a role is still the author's
call.

**Why here, and why on Discord.** The author wants the statistics
from every web game visible on Discord, collected with the bot's own
so both can be read together or either alone (review of 2026-09-25).
`d12ball/stats.py` is already a fold over `MatchState.events` with no
Discord in it, and `/d12ball stats` already cuts by kind (Dinky, test,
two players, every game). This adds a second, orthogonal cut: the
**source**, Discord or web or both.

**What it is.** The bot reads `WEB_GAMES_FILE` read-only, through the
path parameter step 1 gave `load_games`, at the moment a coach asks
(never at startup, never cached across commands: the file is the web
process's and changes under the bot). Same machine, per decision 2,
so the file is local; the web app's save is a temp file renamed over
the real one, so a read never sees a half-written file. A game's
source is a fact already on the record: `guild_id is None` is a web
game. `stats.py` grows `SCOPE_SOURCE_*` beside the kind scopes and a
`game_source(game)`; `/d12ball stats` grows a `source` option
(default: this server's games, as today), and the heading says which.

**What it must not do.** Write the web file, ever; or hold it open.
And the guild rule stands for Discord games: `stats_matches` scopes
the bot's games to the server the command was run in, and that does
not loosen. Web games belong to no server, so the `web` and `both`
cuts show them in whichever server asks; if that is a disclosure the
author does not want, the option is gated to a role, and that is the
author's call in review.

**Prompt.**

```text
Read CLAUDE.md, docs/design/clock-and-records.md ("what the
statistics are and are not"), docs/design/web-app.md and
docs/design/gotchas.md. Branch off an up-to-date main. Assumes step 1
of docs/web-app-next.md (storage.load_games takes a path;
WEB_GAMES_FILE exists).

Goal: /d12ball stats can report the web app's games beside the bot's,
or either alone. Two commits.

1. d12ball/stats.py: a second axis beside the kind scopes.
   SOURCE_DISCORD, SOURCE_WEB, SOURCE_BOTH with labels; game_source
   (game) -> SOURCE_WEB when game.guild_id is None, else
   SOURCE_DISCORD (say in a comment that this is the one reading of
   which system a game was played on, and why a field is not needed);
   games_in_scope takes the source too. Tests on records with and
   without a guild.
2. cogs/d12ball/slash_commands.py: the stats command gains a `source`
   choice (This server, The web app, Both), default This server.
   stats_matches, for web or both, loads the web games with
   load_games(WEB_GAMES_FILE) at call time, read-only, never cached
   on the cog and never written; a missing or unreadable file is
   "no web games yet" in the reply, not an error (load_games already
   logs and returns {}; do not log again). The guild scoping on the
   bot's games stays exactly as it is. The heading names the source
   and the kind. The report's shape does not change. Nothing under
   cogs/ imports webapp (the reverse purity ratchet); the constant
   lives in gamesaves/d12ball/storage.py.

Tests: a cog test with a bot game in the guild and a web game in a
temp file asserts each cut reports the right count and "both" sums
them; a test that the web file is not written by the command (patch
save_games and assert no call). Docs: docs/design/clock-and-records.md
gains a paragraph on the source cut and the read-only read across the
line; docs/design/web-app.md's table row for the files names it. PR
against the template.
```

### 7. The dice on the page

**Landed** (2026-09-26). The two briefs are `d12ball/dice_brief.py`,
hash-verified byte-identical (`docs/design/board-image.md`, "The
matchup image"); the page draws every roll in the log, in the Discord
view's order, off the roll's shape (`docs/design/web-app.md`, "The
dice"). Volatile's ignition die and the scorer's portrait are still
the bot's alone ("What it does not do yet").

**Why now.** The rolls are the drama of the game and the page shows a
sentence where Discord shows a picture. Everything needed is on the
wire: `GameResult.detail` and `Narration.detail` carry the five roll
dataclasses (`ContestDice`, `ShotDice`, `OwnGoalRoll`, `MindPullRoll`,
`InjuryRoll`, with `IgnitedRoll` inside), and the renderers are
`render.py`'s with no Discord in them.

**The one thing in the way.** `render_contest_dice` in
`cogs/d12ball_views/base.py` turns a `ContestDice` into the tuple list
`render_skill_test_dice` takes, and `challenge_side` in
`cogs/d12ball/presentation.py` builds a `ChallengeSide` for the shot
and challenge images. Both are a rendering brief over the model's
values and the web app may not import them. Move each below
`render.py`, verified by SHA-256 on every image the cog produces
through them, per board-image.md.

**Why Pillow and not HTML dice.** One picture, two frontends: the
model's voice is one and so is its picture of a roll. HTML dice would
be a second rendering to keep right, and the ignition die and the
blaze are not trivial to redraw. If the PNGs prove slow on a phone,
that is measured in step 10, not assumed here.

**Prompt.**

```text
Read CLAUDE.md, docs/design/web-app.md, docs/design/board-image.md
and docs/design/model-discord-split.md. Branch off an up-to-date main.

Goal: the web page shows the dice. GameResult.detail and
Narration.detail already carry the five roll dataclasses (ContestDice
and ShotDice in d12ball/flow/rolls.py, OwnGoalRoll in flow/effects.py,
MindPullRoll in flow/arrivals.py, InjuryRoll in flow/injuries.py, with
IgnitedRoll from engine.py inside them); nothing in webapp/ reads
them.

1. Move the rendering briefs out of cogs/. render_contest_dice in
   cogs/d12ball_views/base.py and challenge_side in
   cogs/d12ball/presentation.py read only the model and the catalog.
   Move them below render.py (into render.py, or d12ball/dice_brief.py
   if render.py should not import from flow/), re-point every caller,
   and verify by SHA-256 that every dice image and the shot and
   challenge images the cog produces are byte-identical before and
   after; put the hashes in the PR body. Own commit.
2. webapp/server.py keeps each result's detail on the journal Entry
   that carried it (the answer's own, and each group's). Entry.to_dict
   says whether the entry has a picture. GET
   /api/room/{game_id}/detail/{entry_id}.png renders it with the same
   render.py function the matching roll view calls, in
   asyncio.to_thread, cached the way the boards are. Pick the
   renderer by the detail's shape (the `shape` its to_dict writes),
   never by the prompt kind.
3. app.js draws the picture between the lines the way the cog does:
   find where each roll view places the image relative to the
   narration and match it.
4. Tests: for one fixture per detail shape, apply the roll through
   the route and GET the detail PNG; assert a PNG of the renderer's
   size. Both purity ratchets still pass.

Update docs/design/web-app.md ("The pictures, and the voice" gains the
dice; "What it does not do yet" loses them). PR against the template;
the board-image checklist line applies to the move.
```

### 8. The prompt's pictures

**Landed, narrowed by the author on 2026-09-26.** What it settled is
in `docs/design/web-app.md`, "The prompt's pictures": the shot and the
challenge in the question area, keyed on the kind, and gone with the
question; **no field strip and no half-field**, since the board is
beside the prompt; **no picture in the log**, which says the
challenge in words instead (`WEB_BATCHING` gives the walk-in a group
to carry its challenger on); step 7's dice moved out of the log into
the question box, up until the next thing happens. Both briefs moved
below the renderer, byte-identical (`docs/design/board-image.md`, "The
matchup image").

**What it is.** What a coach looks at while choosing: the field strip
under the seven distance prompts, the hand of cards on the maneuver
pick, the shot image on a score attempt, the coach's half-field on
the hub, and the challenge image on the walk-in. Each is keyed on the
`PromptKind` in `D12Ball.render_prompt` (`FIELD_PROMPT_KINDS`, the
coaching kinds) and drawn by `render_field_image`,
`cards.render_maneuver_hands`, `render_score_attempt`,
`render_coaching_image` and `render_maneuver_challenge`, none of which
import Discord. The kind is the key, as it is in the cog; a page that
looked at `match.challenger_id` to decide would be a second reading.

**Partly done by the page's rebuild (2026-09-25).** The hand is on the
page: the maneuver prompt's buttons are the printed maneuver cards
(`cards.render_maneuver_card`, served by `webapp/pictures.py`), red for
the offense and green for the defense, and pressing one plays it. And
the board beside the prompt is now drawn in the bot's layout with the
cards on it, so the field strip matters less on the web than it does
in a channel where the board is far up the scroll. What is left is the
strip, the shot image, the half-field and the challenge image, and the
first item below drops the hand.
An observer gets the field strip and the half-field and never a hand.

**Prompt.**

```text
Read CLAUDE.md, docs/design/web-app.md, docs/design/maneuver-prompt.md,
docs/design/cards.md and docs/design/model-discord-split.md ("one
picture per kind"). Branch off an up-to-date main. Assumes step 7 of
docs/web-app-next.md has landed.

1. _state's prompt gains "picture": a URL or null, from a table in
   webapp/present.py from PromptKind to a renderer (the web half of
   D12Ball.render_prompt in cogs/d12ball/core.py):
   - the seven FIELD_PROMPT_KINDS: render.render_field_image;
   - SCORE_ATTEMPT: render.render_score_attempt with sides from the
     moved challenge_side;
   - COACHING_HUB and COACHING_OFFER: render.render_coaching_image for
     the asked side, titled with engine.coaching_title.
   (MANEUVER_ACTION is not on the list: its hand is already drawn,
   as the cards themselves, by the page's rebuild.)
   Serve it at GET /api/room/{game_id}/prompt.png?v=<board version>,
   rendered in asyncio.to_thread, cached with the boards.
2. The challenge image is an entry picture: the group tagged
   AUTO_RESOLVE_CHALLENGER carries challenger_id in
   Narration.arguments. Keep it on the journal Entry beside the dice
   detail and serve it through the detail route.
3. app.js draws the prompt picture above the controls and the
   challenge image inside its entry.
4. Tests: one fixture per kind above, GET the picture, assert a PNG
   of the renderer's size. Both purity ratchets
   still pass.

Update docs/design/web-app.md. PR against the template.
```

### 9. What Discord has that the page lacks

**What it is.** The slash commands that are not about Discord, each
over a model function the web app may call: resume and abandon
(`GameService.resume` is already a route; `abandon_game`'s model half
is the record's status change), `/d12ball stats` for the web games on
the page itself (`d12ball/stats.py`, with step 6's source axis). A
finished game's board is not on the list, though Discord posts one
with the game-over prompt: the page's own board already shows the
final position, and coaches can see the field (the author,
2026-09-26, at step 8). Each is a read-only route and a page section,
and none goes near the driver except resume. The rules commands and
the reference cards were on this list; they are step 11, with the
rulebooks beside them. Reading the code says which of
those are model functions and which have logic still in the cog; the
latter move first, the way `cyborg_condition_ids` moved for the board.

**Prompt.**

```text
Read CLAUDE.md, docs/design/web-app.md, docs/design/clock-and-records.md
(stats) and docs/design/recovery.md (resume and abandon). Branch off
an up-to-date main.

For each of these, find the model function under the slash command
in cogs/d12ball/slash_commands.py, move to the model whatever logic
the command still holds that is not Discord (say what moved in the
PR), add a read-only route and a page section, and a test:
1. My rooms with resume and abandon: the front door lists a coach's
   rooms by status; an in-progress one opens; POST /api/room/{id}/
   abandon does what /d12ball abandon_game does through the service
   (if abandoning is a record method, call it; if it is cog logic,
   move it to GameService first); a seat may abandon, an observer may
   not. /api/room/{id}/resume already exists; the page offers it
   where "owed" is true, which it does.
2. Stats: GET /api/room/{id}/stats over d12ball/stats.py for this
   game, and GET /api/stats?kind=&source=web over the web file for
   all of them, a page section at the end of a finished game and a
   link from the front door. The web page never reads the bot's
   file.
(The rules and the reference cards are step 11, not this step.)
Nothing under webapp/ imports cogs; nothing under cogs/ imports
webapp. Docs: docs/design/web-app.md gains "Beyond the game". PR
against the template.
```

### 10. The page as a thing to play on, the wire tree, and the missing tests

**What it is.** Three things the playtest in step 5 orders:

- ~~**Layout.**~~ Done by the page's rebuild (2026-09-25), in the
  shape the author asked for then: Discord's colours, the board with
  its cards and the prompt under it, and on the right the jumbotron,
  the game log and a chat. Two columns on a laptop, one on a phone
  with the board scaled to the width; a tap on the board opens it
  full size. No framework, no build step. See
  `docs/design/web-app.md`, "The page, and why it looks like Discord".
- **Your turn.** A mark in the tab title when the prompt is this
  seat's (done by the rebuild), and one notification per prompt that
  is theirs, asked for once (not yet). `prompt.yours` is already on
  the wire.
- **The journal survives a restart.** Each room's journal written to
  `data/d12ball_web_journal.json` on every `add` (frontend state, its
  own file, never the save) and read at start, bounded as in memory.
  An entry is kept with its words, its roll's `detail` -- which the
  question box draws the dice from, since the log draws no picture
  (step 8) -- and its board snapshot, which `board.png?entry=` serves
  though no page draws it (kept, the author, 2026-09-26); and the journal's `showing_roll`, so the
  dice a restart finds up are still up after it. A room's link is
  good after a restart (step 2); this makes its transcript good too.

And two loose ends: decision 3 on the wire tree, taken as "keep it and
read it", and the tests the 2026-09-25 survey found missing (no test
on `POST /resume`, on the `?entry=` board snapshot route, on a seat's
payload leaving the other side's secrets out beyond "no controls", or
on the entry point's wiring).

**Prompt.**

```text
Read CLAUDE.md, docs/design/web-app.md, docs/design/gotchas.md
("data/ is untracked runtime state") and docs/design/testing.md.
Branch off an up-to-date main. Four commits, each reviewable alone.
(The layout, once item 1, landed with the page's rebuild.)

2. Your turn. app.js already prefixes the title with a mark while
   state.prompt.yours is true. Add: if Notification permission was
   granted (ask once, on the first control pressed, never on load),
   fire one notification per prompt naming the ask.
3. The journal survives a restart. Journal writes itself on every add
   to data/d12ball_web_journal.json (keyed by game id, the same
   JOURNAL_LENGTH bound, entries with their words, snapshots and
   roll details, and showing_roll -- the roll the question box
   shows) and reads it at startup; the log still draws no picture
   (docs/design/web-app.md, "The page"); a write failure is logged and never fails
   the request, like save_games; a room the journal knows and the
   service does not is dropped on load. A full test run must not
   create data/ (see tests/save_patches.py and do the same here).
4. Decision 3 of docs/web-app-next.md, as taken: _state answers with
   result.to_dict() / prompt.to_dict() and present.py's builders read
   the dicts; tests/test_wire_shapes.py stays and now tests a format
   with a consumer. Say in docs/design/web-app.md's "The wire" that
   the page is the consumer.
5. Tests: POST /resume on an owed fixture answers resumed=true and
   the next prompt, 403 for an observer; GET board.png?entry=<id> is
   a PNG for an entry with a snapshot and 404 without; seat 1's state
   on the MANEUVER_ACTION and shootout fixtures carries no hand and
   no order for seat 2 (assert on the JSON); webapp.__main__'s wiring
   builds a service over WEB_GAMES_FILE and never GAMES_FILE (assert
   on the constants).

Update docs/design/web-app.md ("What a page is handed": the journal
is persisted and why it is still not the save; "What it does not do
yet" loses what this closes). PR against the template.
```

### 11. The reading room: the rulebooks and the player aids

**What it is.** Everything a Discord coach can pull up beside a game
without it being a turn, on the page: the two rulebooks, and the
player aids the reference commands post. Asked for by the author on
2026-09-26. Every one is a drawing or a text the model already has;
what the page adds is a place to open them.

| On Discord | What it is, and whose | Which one a game gets |
| --- | --- | --- |
| `/d12ball rules_full`, `rules_search` | The living rules, `rules_doc.load_rules_document` over `docs/living-rules.md` | -- |
| none (printed only) | The Charter and the Learn to Play as PDFs, `rulebooks.build_book` | -- |
| `/d12ball maneuver_reference` | The hexagon, `render.render_maneuver_reference_image` | The gambit tier where `engine.gambits_apply(game)`, basic everywhere else: `D12Ball.reference_tier`, **which is in the cog** |
| `/d12ball role_abilities_reference` | The role card, `role_cards.render_role_card` over `player_catalog.role_profiles` | One card for every mode |
| `/d12ball species_abilities_reference` | The species card's two faces, `species_cards.render_species_card` over `CARD_FACES[0]`, **chosen in the cog** (`build_species_reference_files`) | Where `engine.species_abilities_apply(game)` |
| `/d12ball team_reference` | A team's player cards in catalog order, `player_cards.render_player_card`, or `render_player_card_back` where `engine.personal_abilities_apply(game)` | The seat's own team first; both for an observer |

**Two findings from reading the code**, which is why this is a step
and not a page section:

- **Two choices are in `cogs/` and the web app may not import them.**
  `reference_tier` asks `gambits_apply` and maps it to a tier; the
  species reference picks the first card's two faces because "a
  channel has no table to lay a card on", which is as true of a page.
  Neither is Discord. Both move below the cog first --
  `RulesEngine.maneuver_reference_tier(game)` and a
  `species_cards.REFERENCE_FACES` beside `CARD_FACES` -- and the cog
  is re-pointed at them, the way `cyborg_condition_ids` moved for the
  board.
- **The living rules carry no Law numbers; the Charter's are given at
  build time** (`rulebooks.number_blocks`, rulebooks.md), and the
  Learn to Play cites them as *(Law 6.4)*. A page that rendered
  `docs/living-rules.md` as it stands, which is what step 9 said
  before this step took it over, would be a Charter without the
  numbers the other book points at. So the page reads the rules
  through `rules_doc` for its sections and search (the same
  `RulesDocument.search` `rules_search` answers from) and heads each
  section with its number from `number_blocks(...).headings`. The two
  agree on a slug already: `rulebooks.Heading.slug` is
  `rules_doc.slugify_heading`.

**The books as PDFs, and only as PDFs.** The printed layout is
`rulebooks.py`'s and the figures are laid out for it; an HTML Learn to
Play would be a second layout of the book to keep right, the mistake
`webapp/pictures.py` exists to avoid for the cards. The page serves
what `scripts/build_rulebooks.py` prints, built in the web process
and held in memory, never written to `print/`. The in-page reading is
the Charter's text, searchable, for a coach mid-turn; the PDFs are the
books.

**What is shown where.** In a room, the aids that game plays: the
hexagon at its tier, the species card only where species abilities
apply, the player cards in the face the game plays. At the front
door, with no game to ask, all of them: both hexagons named by tier,
the species card, both faces offered for a team's cards. The rules
and the books are in both places. The page shows what the model
answers; it never reads `game.mode` to choose (CLAUDE.md, "Nothing
reads `game.advanced_maneuvers`...").

**Where it sits.** It depends on step 2 only for the room's route
prefix, touches neither the driver nor the save, and can be claimed
beside any other step. The routine takes steps in number order, so
claim it by hand to take it sooner.

**Prompt.**

```text
Read CLAUDE.md, docs/design/web-app.md, docs/design/cards.md,
docs/design/rulebooks.md, docs/design/rules-and-data.md ("how
/d12ball rules_* serve the living rules") and
docs/design/species-abilities.md (gambits_apply,
species_abilities_apply, personal_abilities_apply). Branch off an
up-to-date main. Assumes step 2 of docs/web-app-next.md has landed
(the room's routes); if it has not, use the /api/game/ prefix
webapp/server.py has today.

Goal: a coach or an observer can open, from the room and from the
front door, the rules, the two rulebooks and every player aid the
Discord reference commands post (maneuver_reference,
role_abilities_reference, species_abilities_reference,
team_reference, rules_full, rules_search), each the model's own
drawing or text.

1. Move the two choices out of cogs/, own commit. D12Ball.reference_tier
   (cogs/d12ball/core.py) becomes RulesEngine.maneuver_reference_tier(game),
   over gambits_apply, same docstring reasoning; the species reference's
   choice of CARD_FACES[0] (build_species_reference_files in
   cogs/d12ball/presentation.py) becomes a named constant in
   d12ball/species_cards.py. Re-point the cog. Verify by SHA-256
   that every image the four reference commands post is byte-identical
   before and after; put the hashes in the PR body.
2. The rulebooks' PDFs as bytes. d12ball/rulebooks.py gains a function
   that sets a book into a BytesIO and returns the bytes (reportlab's
   doc templates take a file-like object); build_book writes those
   bytes, so scripts/build_rulebooks.py is unchanged. No discord and
   no async in it (the purity ratchet).
3. Routes, all read-only, all GET, every render in asyncio.to_thread
   and cached for the process the way the boards are:
   - /rules: the Charter's text, one section per RulesSection from
     d12ball/rules_doc.load_rules_document, each headed with its
     number from rulebooks.number_blocks(parse_markdown(...)).headings
     by slug (unnumbered where the Charter leaves it unnumbered: front
     matter, Parts, Appendices), rendered with present.py's markdown
     pass (extend it if the rules use more of rulebooks.py's subset
     than it handles). /api/rules?q= answers RulesDocument.search.
     A missing rules file is logged at ERROR and answered 503, as
     load_rules does on Discord. No second copy of the rules text.
   - /books/charter.pdf and /books/learn-to-play.pdf: from item 2,
     keyed on the source file's mtime so an edit to the rules is
     picked up without a restart; served inline (Content-Disposition:
     inline) so a browser opens them in a tab. Letter only.
   - /aids/maneuvers/{tier}.png (render_maneuver_reference_image),
     /aids/roles.png (render_role_card), /aids/species/{n}.png (the
     faces from item 1), and a team's cards through the player-card
     route webapp/pictures.py already serves. In a room the page asks
     the model which: maneuver_reference_tier(game),
     species_abilities_apply(game), personal_abilities_apply(game);
     the room's state carries those three answers so app.js never
     decides one.
4. The page: a "Rules & aids" button in the room's header and on the
   front door opens a panel with the rules (search box over
   /api/rules), the two books as links, and the aids as images that
   open full size on a tap, like the board. In a room: the hexagon at
   the game's tier, the species card only where it applies, the
   seat's own team's cards first and the other team's a tab away
   (both for an observer). At the front door: both hexagons named by
   tier, the species card, and a team picker. The maneuver prompt
   links to the hexagon -- a link, never a picture inline, since the
   question box already carries the challenge over the hand (step 8).
   Nothing in the panel goes in the log. Nothing in it takes a lock or
   touches the
   service beyond reading the game.
5. Tests, on the routes and never on the pictures or the books
   (CLAUDE.md: nothing printed is tested): each route answers 200
   with its content type; the PDF route is tested with the builder
   patched to return fixed bytes, so the suite does not set a book;
   the room's state carries the three answers from item 3 and they
   change with the game's mode and settings; every RulesSection that
   the Charter numbers gets a number (the slug agreement is the
   thing a test holds). An observer may open every aid. Both purity
   ratchets and tests/test_web_purity.py still pass; nothing under
   webapp/ imports cogs, nothing under cogs/ imports webapp.

Docs: docs/design/web-app.md gains "The rules and the player aids"
(why PDFs and not an HTML book, why the numbers come from the
Charter build, why the choices moved below the cog); "What it does not
do yet" loses them. docs/design/cards.md notes that the species
reference's faces are species_cards.py's now. Strike step 11 in
docs/web-app-next.md. PR against the template.
```

### Later, and not now

Written down so nobody starts them by accident.

- **A websocket in place of the poll.** The design doc's reason has
  not changed: a few clicks a minute, and a re-read is always right.
  Observers make the poll heavier by a page each; measure before
  changing it.
- **More than one web process.** The web app is one process over one
  file, for the reason the bot is. The day it has to scale past one
  host, `storage.py`'s whole-file save becomes a store with a row per
  game and the lock becomes one both processes honour, reviewed as a
  change to persistence with the save format still the contract.
- **Retiring the two old worksheets.** `docs/web-app.md` and
  `docs/architecture-migration.md` are kept only because about a
  hundred and thirty code comments cite them by step and finding
  number; re-pointing those is its own change, and this file joins
  them when its steps are struck.
- **Rolling the dice with an animation** (the author, 2026-09-26: "at
  some point"). Today the question box shows the bot's own picture of
  the roll the moment it is rolled. An animation is the page's to
  draw, ending on that same picture -- never a second drawing of the
  numbers, and never before the service has rolled them.
- **Discord playing web coaches, or the reverse.** Decided against on
  2026-09-25; not to be re-opened by a step here. The statistics
  (step 6) are a read across the line, not a game.

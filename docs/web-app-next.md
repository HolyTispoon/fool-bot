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
| A coach is a Discord account; `/d12ball web_link` hands them a link. | **A room with a link, and seats claimed in it** (decision 1 below); the slash command goes. |
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
  source or taken together (review of 2026-09-25); that is step 5, and
  it is the one place the bot reads the web file. The archive export
  and the hub still see the bot's games only. Anything else the web
  app wants of the slash commands it builds over the model for itself
  (step 8).
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
   saved. Whoever opens the link comes in as an **Observer**, the
   default role. The two coaching seats are claimed in the room. The
   author named the seats **Home Team Coach** and **Visitors Team
   Coach**.
   - **Underneath a seat is still a name and a signed cookie**, the
     recommendation the author took for the identity: on first visit
     the page asks for a name, the server issues an id (an `int` the
     record takes the way it takes a Discord id) and sets a cookie
     carrying `{id, name}` with an HMAC under `FOOLBOT_WEB_SECRET`,
     stored nowhere. Claiming a seat writes that id into the room's
     record (`player_1_id` or `player_2_id`, through the service's
     lobby moves); coming back to the room with the cookie finds the
     seat still yours. With no secret set, identities die with the
     process, which is the same safe default the links had.
   - **One thing to settle before step 2 names the seats.** The
     Charter's "Winning the toss" (Setting up a game) says one coach
     flips the coin and *the winner chooses whether to be home or the
     visitors*. A seat that is Home before the coin is flipped is a
     rules change. Two readings, and the plan below takes the first
     until the author says otherwise: **(a)** the two seats are the
     two coaches, labelled Home and Visitors from the moment the coin
     settles it and "Coach" until then, so the room plays the Charter
     as written; **(b)** the seat claimed *is* the side, a web game
     skips the toss, and that is a dated entry in `docs/rules-log.md`
     and a line in the living rules, in their own commit, before step
     2 lands.
2. **Where the web process runs: the same Windows machine as the bot,
   the `K:\` checkout.** One `git pull` updates both, one `data/`
   folder holds both files, and the tunnel is on a machine that
   already runs all day. Step 4 is written for it.
3. **The wire tree stays, and the page reads it.** `_state` answers
   with `result.to_dict()` and `prompt.to_dict()` and `present.py`
   reads the dicts, so `tests/test_wire_shapes.py` is testing a
   format with a consumer. Step 9.

## The steps

In the order they pay off. Each is one branch off an up-to-date
`main`, one PR against the template, the suite green, the six
safety-net tests untouched unless the step says why. None changes the
save format. None adds a rule to `webapp/`. Until step 3 lands there
is nothing a web coach can play, since step 1 removes the only way in
that existed; steps 1 to 3 are one sprint.

| # | Step | Size |
| --- | --- | --- |
| 1 | Cut the cord: its own process, file, service and engine | medium |
| 2 | Rooms, seats and observers | medium |
| 3 | The room's table: setup, kickoff, the rematch | large |
| 4 | Run it for real, and write down how | a day, little code |
| 5 | The web games' numbers on Discord, cut by source | small |
| 6 | The dice on the page | medium |
| 7 | The prompt's pictures | medium |
| 8 | What Discord has that the page lacks: my rooms, resume, abandon, stats, the rules | medium |
| 9 | The page as a thing to play on; the wire tree; the tests the survey found missing | medium |
| -- | Later, and not now | -- |

### 1. Cut the cord

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
Its own commit, reviewed as a change to the store. Step 5 reads the
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

**Why now.** Step 1 deletes `/d12ball web_link`, the only way a
person was ever named to the web app. Nothing on the web can be
played until the page knows who is reading it and which seat they
hold.

**What it is, under decision 1.** Three pieces:

- **The identity**: `webapp/identity.py`, a `Coach(id: int, name:
  str)` in a signed cookie, `coach_for(request)` that reads and
  verifies it, and `POST /api/me` that takes a name and sets it (a
  new id the first time; a rename keeps the id).
- **The room**: a game record, which already has everything a room
  needs (an id, a number, a name, two seats, a status, settings), and
  a link `/room/{game_id}` that stays good for as long as the record
  exists. `POST /api/rooms` creates one through `create_game` with
  `in_lobby=True` and *no seat taken*, since the creator is an
  observer until they claim one. That is a small change to
  `create_game`, which today seats the creator as player 1: it gains
  the case of a room with both seats empty, which `D12BallGame`'s
  lobby rules have to accept (`lobby_join` seats whichever is free).
  Reviewed as a change to the record's rules, its own commit.
- **The seats**: claimed and released through the service's lobby
  moves (`lobby_join`, `lobby_leave`), and named as decision 1(a)
  says: "Coach" until the coin, then Home and Visitors. Everyone else
  in the room is an observer, sees everything both coaches are shown
  except a side's secrets (the other hand, the shootout orders, which
  `present.py` already withholds from anyone but that seat), and
  answers nothing. `Viewer` becomes "which seat of *this* room is
  this coach in, if either", by comparing the cookie's id with the
  record's two ids, the same comparison `SafeView.may_act_for` makes
  with a Discord id.

**What must not happen.** A second gate. What a seat may *answer* is
still `asked_sides`, read by `present.py`; the identity says which
seat, never whether the seat may act. And a rule about seats in
`webapp/`: who may claim, who may leave, whether a full room refuses,
are the record's (`lobby_join`/`lobby_leave` refuse with
`RuleRefusal`) and the page shows the sentence.

**Prompt.**

```text
Read CLAUDE.md, docs/web-app-next.md (decision 1 and step 2),
docs/design/web-app.md (as rewritten by step 1), docs/design/
hub-and-lobby.md, docs/design/permissions.md and docs/design/
game-service.md ("setup and the lobby"). Branch off an up-to-date
main. Decision 1 as recorded: rooms with a persistent link, Observer
by default, two claimable coaching seats over a signed-cookie
identity; the seats are "Coach" until the coin and Home / Visitors
after (reading (a)) unless the author has since chosen (b).

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
2. A room with both seats empty. GameService.create_game seats the
   creator as player 1 today. Add the case of a lobby with no seat
   taken (player_1_id None), which means D12BallGame.lobby_join seats
   whichever seat is free, lobby_leave frees it, and every predicate
   that reads player_1_id copes with None; player_1_id's type becomes
   Optional[int] with None as the default written only by this path,
   so every existing save still loads unchanged. Read
   tests/test_game_service_setup.py and extend it. Own commit,
   reviewed as a change to the record's rules; say in the PR body
   which predicates you checked.
3. Rooms and seats on the web. POST /api/rooms -> create_game with
   in_lobby=True and no seat, answering the room id; the page goes to
   /room/{id}, which serves game.html. POST /api/room/{id}/seat/
   {claim|leave} over lobby_join / lobby_leave with the cookie's id
   and name, RuleRefusal -> 409 with the sentence. _state gains
   "room": both seats (name or null, and "yours" for the viewer's),
   the observers' count, and the viewer's role: "observer",
   "coach" (and, once the coin has settled it, "home" or
   "visiting", read off the record's home_player_number /
   visiting_player_number, never worked out here). A viewer who is
   nobody yet is shown the name form first. Seat labels: "Coach"
   until the coin, then "Home Team Coach" / "Visitors Team Coach".
   An observer is offered no controls (asked_sides already does
   this) and never a side's secrets (present.py already withholds
   them; add a test that an observer's MANEUVER_ACTION and shootout
   payloads carry neither side's).
4. Tests in tests/test_web_app.py (replacing the key-based ones): a
   cookie round-trips; a tampered cookie is nobody; two coaches claim
   the two seats and each gets their own controls; a third visitor is
   an observer with none; leaving a seat frees it; a full room refuses
   a third claim with the record's sentence; the room link answers
   after a service restart (load the file again and open it).

Docs: docs/design/web-app.md gains "Rooms, seats and who holds them"
with the cookie derivation, why nothing is stored, and why the seat
names follow the coin. PR against the template; the "New persisted
field" line applies to player_1_id's None (an old save never carries
it; say so).
```

### 3. The room's table: setup, kickoff, the rematch

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

Tests, over HTTP: two coaches claim seats, start, both pick, one
tosses, the winner chooses, begin opens the pre-kickoff Coaching
Choice and the first prompt, and the seat labels read Home / Visitors
from the coin on; an AI room reaches the first prompt with the AI's
pick drawn by the engine; a refused pick (excluded pairing) is a 409
carrying the record's sentence and writes nothing; an observer's
table presses are 403; a finished game (the GAME_OVER fixture)
rematches into a new room the same two coaches hold. Suppress saves.

Docs: docs/design/web-app.md "What it does not do yet" loses "It does
not create games" and gains "The room's table" with why every
question on it is the record's. PR against the template.
```

### 4. Run it for real, and write down how

**Why here.** After step 3 a web game can be played end to end, and
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
one whose account the author already has.

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
3. Add a "Playtest checklist" under step 4 of docs/web-app-next.md:
   one person opens a room and shares the link, the other arrives as
   an observer and claims the second seat, a third person watches as
   an observer; setup through kickoff, a goal, a loose ball, a
   coaching window, the end and a rematch; for each, note whether
   all three pages agreed about whose turn it was and what happened,
   and what each coach wished the page had shown.
4. PR against the template; docs and one script, say so under
   Testing.
```

### 5. The web games' numbers on Discord, cut by source

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

### 6. The dice on the page

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
that is measured in step 9, not assumed here.

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

### 7. The prompt's pictures

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
An observer gets the field strip and the half-field and never a hand.

**Prompt.**

```text
Read CLAUDE.md, docs/design/web-app.md, docs/design/maneuver-prompt.md,
docs/design/cards.md and docs/design/model-discord-split.md ("one
picture per kind"). Branch off an up-to-date main. Assumes step 6 of
docs/web-app-next.md has landed.

1. _state's prompt gains "picture": a URL or null, from a table in
   webapp/present.py from PromptKind to a renderer (the web half of
   D12Ball.render_prompt in cogs/d12ball/core.py):
   - the seven FIELD_PROMPT_KINDS: render.render_field_image;
   - MANEUVER_ACTION: cards.render_maneuver_hands with this seat's
     hand only, off the prompt's options (the rows the page already
     sends), never off the match; null for an observer;
   - SCORE_ATTEMPT: render.render_score_attempt with sides from the
     moved challenge_side;
   - COACHING_HUB and COACHING_OFFER: render.render_coaching_image for
     the asked side, titled with engine.coaching_title.
   Serve it at GET /api/room/{game_id}/prompt.png?v=<board version>,
   rendered in asyncio.to_thread, cached with the boards.
2. The challenge image is an entry picture: the group tagged
   AUTO_RESOLVE_CHALLENGER carries challenger_id in
   Narration.arguments. Keep it on the journal Entry beside the dice
   detail and serve it through the detail route.
3. app.js draws the prompt picture above the controls and the
   challenge image inside its entry.
4. Tests: one fixture per kind above, GET the picture, assert a PNG
   of the renderer's size; assert seat 2's MANEUVER_ACTION picture is
   seat 2's hand and an observer's is null. Both purity ratchets
   still pass.

Update docs/design/web-app.md. PR against the template.
```

### 8. What Discord has that the page lacks

**What it is.** The slash commands that are not about Discord, each
over a model function the web app may call: resume and abandon
(`GameService.resume` is already a route; `abandon_game`'s model half
is the record's status change), `/d12ball stats` for the web games on
the page itself (`d12ball/stats.py`, with step 5's source axis),
`rules_full` and `rules_search` (`d12ball/rules_doc.py` reads
`docs/living-rules.md`), the maneuver and role references (the
printed cards are `cards.py`'s and `role_cards.py`'s), and a finished
game's board. Each is a read-only route and a page section, and none
goes near the driver except resume. Reading the code says which of
those are model functions and which have logic still in the cog; the
latter move first, the way `cyborg_condition_ids` moved for the board.

**Prompt.**

```text
Read CLAUDE.md, docs/design/web-app.md, docs/design/clock-and-records.md
(stats), docs/design/rules-and-data.md (the rules commands) and
docs/design/recovery.md (resume and abandon). Branch off an
up-to-date main.

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
3. The rules: GET /rules and GET /api/rules?q= over
   d12ball/rules_doc.py, rendered with webapp/present.render_text's
   markdown pass (extend it if the rules use more of the subset than
   it handles; the rulebooks' markdown subset in rulebooks.py is the
   reference). No second copy of the rules text anywhere.
4. References: the maneuver cards and the role cards as PNGs from
   cards.py / role_cards.py, served read-only and cached, linked from
   the maneuver prompt.
Nothing under webapp/ imports cogs; nothing under cogs/ imports
webapp. Docs: docs/design/web-app.md gains "Beyond the game". PR
against the template.
```

### 9. The page as a thing to play on, the wire tree, and the missing tests

**What it is.** Three things the playtest in step 4 orders:

- **Layout.** Two columns on a laptop, one on a phone with the board
  scaled to the width and the prompt pinned at the bottom; a tap on
  the board opens it full size. No framework, no build step.
- **Your turn.** A mark in the tab title when the prompt is this
  seat's, and one notification per prompt that is theirs, asked for
  once. `prompt.yours` is already on the wire.
- **The journal survives a restart.** Each room's journal written to
  `data/d12ball_web_journal.json` on every `add` (frontend state, its
  own file, never the save) and read at start, bounded as in memory,
  with the board snapshots and details its entries draw. A room's
  link is good after a restart (step 2); this makes its transcript
  good too.

And two loose ends: decision 3 on the wire tree, taken as "keep it and
read it", and the tests the 2026-09-25 survey found missing (no test
on `POST /resume`, on the `?entry=` board snapshot route, on a seat's
payload leaving the other side's secrets out beyond "no controls", or
on the entry point's wiring).

**Prompt.**

```text
Read CLAUDE.md, docs/design/web-app.md, docs/design/gotchas.md
("data/ is untracked runtime state") and docs/design/testing.md.
Branch off an up-to-date main. Five commits, each reviewable alone.

1. Layout. game.html and app.css: two columns from 900px up (board
   left; scoreboard, seats, prompt and journal right), one column
   below with the board at full width and the prompt sticky at the
   bottom; a click on the board opens it at full size in a <dialog>.
   Check in a real browser at 360px and 1280px and put screenshots in
   the PR. No framework, no build step, no CDN.
2. Your turn. app.js: when state.prompt.yours turns true, prefix the
   title with a mark and, if Notification permission was granted (ask
   once, on the first control pressed, never on load), fire one
   notification per prompt naming the ask; clear the mark when the
   prompt changes.
3. The journal survives a restart. Journal writes itself on every add
   to data/d12ball_web_journal.json (keyed by game id, the same
   JOURNAL_LENGTH bound, entries with their snapshots and details)
   and reads it at startup; a write failure is logged and never fails
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
- **Discord playing web coaches, or the reverse.** Decided against on
  2026-09-25; not to be re-opened by a step here. The statistics
  (step 5) are a read across the line, not a game.

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
changes in the shipped design, the decisions still to take, the steps
in the order they pay off, and one prompt per step written to be
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
| One `games` dict and one save file, `data/d12ball_games.json`, shared by both frontends. | **Its own games and its own file**, `data/d12ball_web_games.json`, in the same format. The bot's file is never opened by the web app and the reverse. |
| The cog's `GameService`, `RulesEngine` and `GameLocks`, handed in. | **Its own service, engine and locks**, built from the same model loaders the cog uses. |
| A coach is a Discord account; `/d12ball web_link` hands them a link. | **A web identity of its own** (decision 1 below); the slash command goes. |
| `GameService.listeners` so a page sees a turn taken on Discord. | Kept, for the same reason one step over: a page sees the turn the *other web coach* took. |
| "One process, one service, a lock per game" (decision 5 of [web-app.md](web-app.md)), because two processes over one file would clobber each other. | **One process per file.** The reasoning stands; the file is what it was about. Two processes over two files do not touch. |
| The web app inherits `DiscordBatching` through the cog's service. | Gone with the shared service: the web app's service takes the default `Batching()`. |

What it costs, said plainly:

- **The thing the split was measured by is dropped.** Cross-frontend
  play was the proof that both frontends were over one model; a web
  coach could not tell whether the other coach was on Discord. The
  proof stands in the tests (`tests/test_web_app.py` presses every
  prompt fixture through the same service) and no longer in play.
- **Two populations of games.** `/d12ball stats`, the archive export
  and the hub see the bot's games only. Anything the web app wants of
  those it builds over the model for itself (step 7). Playtest data
  lives in two files.
- **Two deployments.** The bot runs on the Windows checkout; the web
  app runs wherever it is put, with `data/` of its own, and each is
  restarted on its own.

What it buys:

- A bot restart does not touch a web game, and the reverse.
- The web app can be hosted on any machine with the repository
  checked out, not only the machine the bot's token lives on.
- No lock shared with `SafeView`, no listener cross-wiring, no
  mirroring of web turns into a channel, no stale-prompt problem
  between frontends. The web app's concurrency is two coaches on one
  page, which `gamelocks.GameLocks` already handles.

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

## Decisions to take first

Each is the author's. Take them as inline comments on the PR that
adds this file.

1. **Who is a web coach?** The record stores `player_1_id: int` and
   `player_2_id`, and every rule about seats reads them; on the web
   there is no account behind a seat. The recommendation is **a
   signed cookie, no account store**: on first visit the page asks
   for a name, the server issues an id (an `int` the record takes the
   way it takes a Discord id) and sets a cookie carrying `{id, name}`
   and an HMAC of it under `FOOLBOT_WEB_SECRET`. Nothing is stored:
   the cookie is the identity, the way the link was the credential in
   the shipped design (`webapp/keys.py`, derived, never stored). A
   coach's games are the games in the web file that name their id.
   With no secret set, identities die with the process, as the links
   did, which is the same safe default. The alternatives are a
   registry file of coaches (`data/d12ball_web_coaches.json`, id,
   name, token) if names must be unique or a coach must be found by
   name, or real accounts, which nothing here needs. **Step 2 cannot
   start until this is taken.**
2. **Where does the web process run?** It no longer has to be the
   Windows checkout. The same machine is simplest (one `git pull`
   updates both, the model is one checkout, and the tunnel is on a
   machine that already runs all day). Anywhere else needs its own
   checkout and its own `.env` with `FOOLBOT_WEB_SECRET`. Step 4 is
   written for the same machine; say if not.
3. **The wire tree.** Either `_state` answers with `result.to_dict()`
   and `present.py` reads the dicts, or the `to_dict` tree on the
   option shapes goes and `tests/test_wire_shapes.py` with it. The
   recommendation is to keep the tree and make the page read it: a
   wire format with a consumer is one that gets kept right. Step 8.

## The steps

In the order they pay off. Each is one branch off an up-to-date
`main`, one PR against the template, the suite green, the six
safety-net tests untouched unless the step says why. None changes the
save format. None adds a rule to `webapp/`. Until step 3 lands there
is nothing a web coach can play, since step 1 removes the only way in
that existed; steps 1 to 3 are one sprint.

| # | Step | Needs decision | Size |
| --- | --- | --- | --- |
| 1 | Cut the cord: its own process, file, service and engine | none | medium |
| 2 | Who is a web coach | 1 | small |
| 3 | Open a game on the web: the front door, the lobby, setup, kickoff, the rematch | 1 | large |
| 4 | Run it for real, and write down how | 2 | a day, little code |
| 5 | The dice on the page | none | medium |
| 6 | The prompt's pictures | none | medium |
| 7 | What Discord has that the page lacks: my games, resume, abandon, stats, the rules | none | medium |
| 8 | The page as a thing to play on; the wire tree; the tests the survey found missing | 3 | medium |
| -- | Later, and not now | -- | -- |

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
Its own commit, reviewed as a change to the store.

**Two fences.** `tests/test_web_purity.py` already ratchets that
`webapp/` imports no `cogs` or `discord`. It grows the reverse: no
module under `cogs/`, and not `foolbot.py`, imports `webapp`. The bot
must start and run with the `webapp/` directory deleted.

**What must not happen.** The web app opening the bot's file. The
default path stays the bot's, so the web app passes its own
explicitly and a test asserts the two constants differ and that
`webapp` never names the bot's.

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
   FOOLBOT_WEB_PORT is now required (default 8080 when unset is fine;
   say which). Logging: console only, through botlog's console setup
   if it imports without discord, otherwise logging.basicConfig; the
   #logs mirror is the bot's.
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

### 2. Who is a web coach

**Why now.** Step 1 deletes `/d12ball web_link`, the only way a
person was ever named to the web app. Nothing on the web can be
played until the page knows who is reading it.

**What it is, under decision 1 as recommended.** `webapp/identity.py`:
a `Coach(id: int, name: str)`, a cookie that carries it signed under
the same secret `keys.py` uses, `coach_for(request)` that reads and
verifies it, and one route, `POST /api/me`, that takes a name and
sets the cookie (a new id the first time; a rename keeps the id).
`Viewer` becomes "which seat of *this* game is this coach in, if
either", worked out by comparing the coach's id with the record's two
ids, the same comparison `SafeView.may_act_for` makes with a Discord
id. `keys.py`'s per-seat links go, or stay as a *spectator* link if
one is wanted (a game is otherwise visible to its two coaches only).

**What must not happen.** A second gate. What a coach may *answer* is
still `asked_sides`, read by `present.py`; the identity says which
seat, never whether the seat may act.

**Prompt.**

```text
Read CLAUDE.md, docs/web-app-next.md (decision 1 and step 2),
docs/design/web-app.md (as rewritten by step 1, "Who is on the other
end") and docs/design/permissions.md. Branch off an up-to-date main.
Decision 1 has been taken as: <a signed cookie, no store | a coach
registry file | ...>. Below assumes the signed cookie.

1. webapp/identity.py: Coach(id: int, name: str); serialise it into
   one cookie (base64 JSON + HMAC-SHA256 under keys.secret(), compared
   with compare_digest); coach_for(request) -> Optional[Coach], None
   for no cookie, a bad signature or a malformed payload; issue(name)
   -> Coach with a fresh id (a random positive int that fits the
   record's int the way a Discord id does; document why it is not a
   sequence: nothing stores the last one). A name is 1-32 characters
   after strip; refuse otherwise with a 400 and a sentence.
2. Routes: POST /api/me {name} sets the cookie (Secure when the
   request is HTTPS, HttpOnly, SameSite=Lax, a year) and answers
   {id, name}; GET /api/me answers the coach or null. A rename keeps
   the id. Every existing route reads coach_for; Viewer is built by
   comparing the coach's id with game.player_1_id / player_2_id
   (mirror SafeView.may_act_for's reading; do not add a rule). A game
   is visible to its two coaches; anyone else gets 403 (a spectator
   link is not this step -- if the author wants one, keys.link_for
   stays for it, otherwise delete webapp/keys.py's link functions and
   keep secret()).
3. The page: on first visit with no cookie, a name form in place of
   everything else; after, the name in the footer with a rename.
4. Tests in tests/test_web_app.py (replace the key-based ones): a
   cookie round-trips; a tampered cookie is nobody; a coach in seat 1
   gets seat 1's controls and seat 2's coach gets seat 2's; a third
   coach gets 403; the prompt fixtures still press every control
   through apply_action.

Docs: docs/design/web-app.md "Who is on the other end" rewritten for
the cookie, with why nothing is stored. FOOLBOT_WEB_SECRET's line in
"Running it" says identities die with the process without it. PR
against the template.
```

### 3. Open a game on the web

**What it is.** Everything between arriving with a name and the first
prompt, and the rematch at the end, all of it over service methods
that exist: `create_game`, `lobby_join`/`lobby_observe`/`lobby_leave`,
`configure`, `start_lobby`, `pick_team`, `flip_coin`,
`choose_home_or_visiting`, `begin`, and `discard_game`. Each is a thin
door over a rule on `D12BallGame` that refuses with `RuleRefusal`;
`tests/test_game_service_setup.py` walks the whole path with no
channel and is the script for this step.

Three pages' worth:

- **The front door** (`/`): my games (the web file's games naming my
  id, by status), open lobbies (`in_lobby` games with a seat free),
  and two buttons: play the AI now, open a lobby. The tutorial is a
  checkbox on either, since `create_game` takes `tutorial=`.
- **The lobby and setup**, in the prompt's place before kickoff: the
  settings (`GAME_SETTINGS` and their values), both seats, which
  teams this coach may pick (asked of the record), the coin, home or
  visiting, and Begin. Every question is the record's or the
  service's; if one is not exposed, it grows a method both frontends
  read.
- **The rematch**: `present.py` gains the one builder it lacks,
  `GAME_OVER`, whose control does what `RematchView` does through the
  service and sends the coach to the new game.

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
up-to-date main. Three commits.

1. Creating and joining. Routes, each authenticated by the cookie
   (step 2), each calling one service method under the game's lock,
   each mapping RuleRefusal to a 409 whose body carries the sentence
   and the state, and answering the state otherwise:
   POST /api/games {mode?, tutorial?, lobby: bool} -> create_game
   with this coach as player 1, in_lobby as asked, guild_id and
   channel_id None (the AI is the service's default for a non-lobby
   game with no second player; do not name Dinky here);
   POST /api/game/{id}/lobby/{join|observe|leave|start} over the four
   lobby methods; DELETE /api/game/{id} over discard_game for a
   setup game with no match (its ValueError is the service's; map it
   to 409). GET /api/games answers this coach's games by status and
   the open lobbies (in_lobby, a seat free), each as
   {id, number, name, status, coaches, tutorial}. The index page
   becomes the front door drawn from that: my games, open lobbies,
   "Play Dinky", "Open a lobby", a tutorial checkbox.
2. Setup and kickoff. POST /api/game/{id}/setup/{configure|
   pick_team|flip_coin|choose} over configure, pick_team, flip_coin
   and choose_home_or_visiting, building Team and HomeChoice from the
   wire in the route (d12ball/wire.py's reason for Action.from_dict),
   and POST /api/game/{id}/begin over begin. _state before kickoff
   gains "setup": GAME_SETTINGS with their current values and whether
   this coach may change them; both seats (name, team or null); the
   teams this coach may pick, asked of the record (excluded_teams and
   the pool -- if no method answers "which may this seat pick" in one
   call, add it to D12BallGame and make the cog's setup view read it
   too); whether the coin may be tossed and by whom; whether
   home/visiting is owed and by whom; whether begin is available.
   The page draws the setup panel in the prompt's place from "setup"
   and nothing else.
3. The rematch. present.py gains the GAME_OVER builder: one control,
   "Rematch", posting to POST /api/game/{id}/rematch, which does what
   cogs/d12ball_views/setup.py's RematchView does through the service
   (a new game with the finished game's settings and the same two
   seats, or the AI) and answers the new game id; the page follows
   it. Remove the GAME_OVER exemption in tests/test_web_app.py.

Tests, over HTTP: two coaches open and join a lobby, start it, both
pick, one tosses, the winner chooses, begin opens the pre-kickoff
Coaching Choice and the first prompt; a solo game against the AI
reaches the first prompt with the AI's pick drawn by the engine; a
refused pick (excluded pairing) is a 409 carrying the record's
sentence and writes nothing; a third coach cannot join a full lobby
and cannot see a game they are not in; a finished game (use the
GAME_OVER fixture) rematches into a new game the same two coaches
can open. Suppress saves.

Docs: docs/design/web-app.md "What it does not do yet" loses "It does
not create games" and gains a section "Opening a game" with the
front door and why every question on the setup panel is the
record's. PR against the template.
```

### 4. Run it for real, and write down how

**Why here.** After step 3 a web game can be played end to end, and
nothing below is worth building until two people have played one
through, because that is what says which gap actually stops play.

**What it is.** On the machine decision 2 named: `.env` with
`FOOLBOT_WEB_PORT`, `FOOLBOT_WEB_SECRET` (identities die with the
process without it) and `FOOLBOT_WEB_URL`; the port behind something
that terminates TLS and gives it a public name; `python3 -m webapp`
kept running the way the bot is (a service, a scheduled task, or the
same PowerShell wrapper as `update_main_bot.ps1`, whichever the
Windows box uses); two people play a game through and note where it
broke. The cookie is the credential, so the page must only ever be
served over HTTPS, which is the tunnel's job.

**Which tunnel.** Hosting, not code, and not verified from here. A
Cloudflare Tunnel, Tailscale Funnel or ngrok each gives a Windows host
a public HTTPS name without opening a port on the router; pick the
one whose account the author already has.

**Prompt.**

```text
Read CLAUDE.md, docs/design/web-app.md ("Running it") and
docs/design/collaboration.md. We are deploying the D12 Ball web app
for the first time as its own process on <the Windows checkout | host>.
Little or no Python.

1. Write a "Running the web app" section into
   docs/design/collaboration.md: the command (python3 -m webapp), the
   FOOLBOT_WEB_* variables and what each is for, why
   FOOLBOT_WEB_SECRET must be set (cookies die with the process
   otherwise), why the page must only be served over HTTPS (the
   cookie is the identity), how the process is kept running beside
   the bot on that machine (read update_main_bot.ps1 and mirror it),
   that the two processes have separate data files and separate
   restarts, and the exact steps to expose the port through <TUNNEL>
   including where FOOLBOT_WEB_URL comes from. Say what you could not
   verify from here.
2. If keeping it running needs a script, add scripts/run_web_app.ps1
   (or .sh) beside update_main_bot.ps1; nothing one-off.
3. Add a "Playtest checklist" under step 4 of docs/web-app-next.md:
   two coaches open the page, name themselves, one opens a lobby and
   the other joins, setup through kickoff, a goal, a loose ball, a
   coaching window, the end and a rematch; for each, note whether
   both pages agreed about whose turn it was and what happened, and
   what each coach wished the page had shown.
4. PR against the template; docs and one script, say so under
   Testing.
```

### 5. The dice on the page

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
that is measured in step 8, not assumed here.

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
   /api/game/{game_id}/detail/{entry_id}.png renders it with the same
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

### 6. The prompt's pictures

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

**Prompt.**

```text
Read CLAUDE.md, docs/design/web-app.md, docs/design/maneuver-prompt.md,
docs/design/cards.md and docs/design/model-discord-split.md ("one
picture per kind"). Branch off an up-to-date main. Assumes step 5 of
docs/web-app-next.md has landed.

1. _state's prompt gains "picture": a URL or null, from a table in
   webapp/present.py from PromptKind to a renderer (the web half of
   D12Ball.render_prompt in cogs/d12ball/core.py):
   - the seven FIELD_PROMPT_KINDS: render.render_field_image;
   - MANEUVER_ACTION: cards.render_maneuver_hands with this coach's
     hand only, off the prompt's options (the rows the page already
     sends), never off the match;
   - SCORE_ATTEMPT: render.render_score_attempt with sides from the
     moved challenge_side;
   - COACHING_HUB and COACHING_OFFER: render.render_coaching_image for
     the asked side, titled with engine.coaching_title.
   Serve it at GET /api/game/{game_id}/prompt.png?v=<board version>,
   rendered in asyncio.to_thread, cached with the boards. The other
   coach on a MANEUVER_ACTION gets their own hand and never both.
2. The challenge image is an entry picture: the group tagged
   AUTO_RESOLVE_CHALLENGER carries challenger_id in
   Narration.arguments. Keep it on the journal Entry beside the dice
   detail and serve it through the detail route.
3. app.js draws the prompt picture above the controls and the
   challenge image inside its entry.
4. Tests: one fixture per kind above, GET the picture, assert a PNG
   of the renderer's size; assert seat 2's MANEUVER_ACTION picture is
   seat 2's hand. Both purity ratchets still pass.

Update docs/design/web-app.md. PR against the template.
```

### 7. What Discord has that the page lacks

**What it is.** The slash commands that are not about Discord, each
over a model function the web app may call: resume and abandon
(`GameService.resume` is already a route; `abandon_game`'s model half
is the record's status change), `/d12ball stats` (`d12ball/stats.py`,
a fold over `MatchState.events`, no Discord), `rules_full` and
`rules_search` (`d12ball/rules_doc.py` reads `docs/living-rules.md`),
the maneuver and role references (the printed cards are
`cards.py`'s and `role_cards.py`'s), and a finished game's board. Each
is a read-only route and a page section, and none goes near the
driver except resume. Reading the code says which of those are model
functions and which have logic still in the cog; the latter move
first, the way `cyborg_condition_ids` moved for the board.

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
1. My games with resume and abandon: the front door lists a coach's
   games by status; an in-progress one opens; POST /api/game/{id}/
   abandon does what /d12ball abandon_game does through the service
   (if abandoning is a record method, call it; if it is cog logic,
   move it to GameService first). /api/game/{id}/resume already
   exists; the page offers it where "owed" is true, which it does.
2. Stats: GET /api/game/{id}/stats over d12ball/stats.py, a page
   section at the end of a finished game and a link during it.
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

### 8. The page as a thing to play on, the wire tree, and the missing tests

**What it is.** Three things the playtest in step 4 orders:

- **Layout.** Two columns on a laptop, one on a phone with the board
  scaled to the width and the prompt pinned at the bottom; a tap on
  the board opens it full size. No framework, no build step.
- **Your turn.** A mark in the tab title when the prompt is this
  coach's, and one notification per prompt that is theirs, asked for
  once. `prompt.yours` is already on the wire.
- **The journal survives a restart.** Each game's journal written to
  `data/d12ball_web_journal.json` on every `add` (frontend state, its
  own file, never the save) and read at start, bounded as in memory,
  with the board snapshots and details its entries draw.

And two loose ends: decision 3 on the wire tree, and the tests the
2026-09-25 survey found missing (no test on `POST /resume`, on the
`?entry=` board snapshot route, on a coach's payload leaving the
other side's secrets out beyond "no controls", or on the entry
point's wiring).

**Prompt.**

```text
Read CLAUDE.md, docs/design/web-app.md, docs/design/gotchas.md
("data/ is untracked runtime state") and docs/design/testing.md.
Branch off an up-to-date main. Five commits, each reviewable alone.

1. Layout. game.html and app.css: two columns from 900px up (board
   left; scoreboard, prompt and journal right), one column below
   with the board at full width and the prompt sticky at the bottom;
   a click on the board opens it at full size in a <dialog>. Check
   in a real browser at 360px and 1280px and put screenshots in the
   PR. No framework, no build step, no CDN.
2. Your turn. app.js: when state.prompt.yours turns true, prefix the
   title with a mark and, if Notification permission was granted (ask
   once, on the first control pressed, never on load), fire one
   notification per prompt naming the ask; clear the mark when the
   prompt changes.
3. The journal survives a restart. Journal writes itself on every add
   to data/d12ball_web_journal.json (keyed by game id, the same
   JOURNAL_LENGTH bound, entries with their snapshots and details)
   and reads it at startup; a write failure is logged and never fails
   the request, like save_games; a game the journal knows and the
   service does not is dropped on load. A full test run must not
   create data/ (see tests/save_patches.py and do the same here).
4. Decision 3 of docs/web-app-next.md as taken: <either> _state
   answers with result.to_dict() / prompt.to_dict() and present.py's
   builders read the dicts, <or> the to_dict tree on the option
   shapes goes with tests/test_wire_shapes.py and docs/design/
   web-app.md's "The wire" says what remains and why.
5. Tests: POST /resume on an owed fixture answers resumed=true and
   the next prompt, 403 for a coach not in the game; GET
   board.png?entry=<id> is a PNG for an entry with a snapshot and 404
   without; seat 1's state on the MANEUVER_ACTION and shootout
   fixtures carries no hand and no order for seat 2 (assert on the
   JSON); webapp.__main__'s wiring builds a service over
   WEB_GAMES_FILE and never GAMES_FILE (assert on the constants).

Update docs/design/web-app.md ("What a page is handed": the journal
is persisted and why it is still not the save; "What it does not do
yet" loses what this closes). PR against the template.
```

### Later, and not now

Written down so nobody starts them by accident.

- **A websocket in place of the poll.** The design doc's reason has
  not changed: a few clicks a minute, and a re-read is always right.
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
  2026-09-25; not to be re-opened by a step here.

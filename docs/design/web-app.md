# The web frontend

The fourth part of [ARCHITECTURE.md](../../ARCHITECTURE.md): `webapp/`,
a browser frontend over the same model the Discord cog plays, **run as
a system of its own**. This note is the reasoning behind its shape; the
map in CLAUDE.md says where the pieces are. The worksheet it was built
from is [../web-app.md](../web-app.md), which is the review the split
was held to and the decisions taken in it; what outlives that review is
here. What is being built next is
[../web-app-next.md](../web-app-next.md).

**Separate from the bot, 2026-09-25 (the author).** The web app and the
bot share the model of the game -- `d12ball/`, the service over it and
the store's format -- and nothing at runtime: not a process, not a
games file, not a service. A web coach plays web coaches (or the AI); a
Discord coach plays Discord coaches (or the AI); no game is ever on
both. The web app shipped the other way, inside the bot's process over
the bot's games, so that a game could be played from a channel on one
side and a browser on the other; that was the proof the split worked,
and it now lives in the tests (`tests/test_web_app.py` presses every
prompt fixture through the same service) rather than in play.

**The whole of what it is:** say who the person is and which seat of
the room they hold, turn what they
pressed into an `Action`, call `apply_action`, render the `GameResult`.
It is the same four lines the cog is, with `discord.Interaction`
swapped for an HTTP request -- and it is the measure of whether the
model/Discord split worked, because everything it needed the bot
already had.

## Running it

```bash
python3 -m webapp
```

No Discord token and no bot: `webapp/__main__.py` calls
`webapp.server.main`, which reads `.env` the way `foolbot.py` does,
logs to the console at `FOOLBOT_LOG_LEVEL` (not through `botlog`,
which imports discord -- the #logs mirror is the bot's), builds its
own service over `data/d12ball_web_games.json` and serves until
interrupted. Four environment variables, all of the frontend's:

| Variable | What it does |
| --- | --- |
| `FOOLBOT_WEB_PORT` | The port, **8080 when unset**. It used to be the switch that started a server inside the bot; there is nothing to switch on now, since running the command is the switch. |
| `FOOLBOT_WEB_HOST` | What to bind, `0.0.0.0` by default. |
| `FOOLBOT_WEB_URL` | What a link points at, `http://localhost:8080` by default -- the address a coach's browser can reach, which the server cannot know about itself behind a tunnel or a proxy. |
| `FOOLBOT_WEB_SECRET` | What a person's cookie is signed under (`webapp/keys.py`). With none set one is made per process, and every cookie dies with it. |

A failure to bind raises out of `main`: nothing else is running in the
process to carry on with.

How it is run on the live host -- the `.env`, why the secret must be
set and the page served only over HTTPS, `scripts/run_web_app.ps1`
beside the bot's updater, and the tunnel -- is
[collaboration.md](collaboration.md), "Running the web app".

## What it may not do

**Two fences, one each way**, both in `tests/test_web_purity.py` and
both an AST walk, so a lazy import inside a function (which is exactly
where one would arrive) fails too:

- `webapp/` imports neither `discord` nor `cogs`. A web app that
  reaches into the Discord frontend is not a second frontend over the
  model, it is a second frontend over the first, and the first rule it
  borrowed is the end of the exercise (CLAUDE.md, principle 10).
- Nothing under `cogs/`, and not `foolbot.py`, imports `webapp`. The
  bot must start and run with the `webapp/` directory deleted: what
  the two share is below both of them, never one of them.

And a third, about the file: **nothing under `webapp/` names
`GAMES_FILE`.** `storage`'s default path is the bot's file, so a web
save that forgot to name its own would write over the bot's games;
the web app names `WEB_GAMES_FILE` every time, and
`webapp.server.build_service` takes the file with no default.

The rule with teeth is the positive one: **every control comes off
`PendingPrompt.options` and nothing else**, read as the wire writes
them ("The wire", below). `webapp/present.py` has
one builder per `PromptKind` -- the web app's half of
`D12Ball.view_for_prompt` -- and a candidate list, a distance or a
hand worked out there would be a second reading the driver cannot
see. `tests/test_web_app.py` presses every control of every fixture in
`tests/prompt_fixtures.py` through `apply_action` and asserts that
none is refused, which is principle 10 as a thing that can be run.

One thing it reads off the match and may: a *label*. The run back's
buttons are named with the distance each costs and the hub's with the
space a meeple is moving to, which the Discord views read the same
way. What is offered is the prompt's; how it is worded over the
position is the frontend's.

## The wire

`d12ball/wire.py` holds the one conversion, `jsonable`, and every
dataclass a frontend is handed has a `to_dict`: the options shapes,
`PendingPrompt`, `Narration`, `GameResult` and the five roll details.

**The page is its consumer** (decision 3 of
[../web-app-next.md](../web-app-next.md), taken as "keep it and read
it", step 10). `WebApp._state` hands a page the prompt read off
`prompt.to_dict()`, and every builder in `webapp/present.py` reads
that dict and nothing else of the prompt -- a side is `"home"`, a
formation its name, a zone its value. The journal reads each result
as `result.to_dict()` writes it, which is why it can keep an entry
in a file as it is, and the dice are drawn from a roll's own
`to_dict`. So `tests/test_wire_shapes.py` is testing a format
something reads: a field that goes missing from a `to_dict` is a
control or a die that goes missing on the page. Where a value off the
wire is asked about by a model function -- a zone for a space's
label, a side against the sides this viewer coaches -- it becomes the
model's own type at that call, the way the adapters build a `side` or
a `formation` from an action. Whose question a prompt is stays
`asked_sides` over the prompt itself: that is a reading of the model,
not of its wire shape.

Three decisions in it:

- **It is one-way.** Only `Action.from_dict` reads. A `from_dict` on a
  prompt would be the beginning of a frontend telling the model what
  it is waiting on; an action names the question it answers and the
  driver checks it against the match.
- **`jsonable` raises rather than falling back to `str(value)`.** A
  wire format that quietly sends the repr of an object is one nobody
  can read from the other end, and the raise is what caught every
  enum on the way out.
- **`GameResult.to_dict` leaves the position out** unless `match=True`
  is written at the call site. A result is what one *person* is shown,
  and the match holds what the game keeps from them -- the other
  side's maneuver pick, an unrevealed shootout order. A serialiser
  that hands the save to a browser has broken a rule of the game.

`Action.from_dict` builds the `PromptKind` rather than leaving it the
string a request carried: `answer` compares the kind by identity, so
every such action would be refused as a stale click -- a sentence
about the game for what is a malformed request. The two arguments
that are model types, `side` and `formation`, are built in the
adapters, which is where a value off a wire becomes one.

## Who is on the other end

A Discord interaction carries the account that clicked. A browser
carries nothing, so the web app issues its own: a name, an id and a
signed cookie (`webapp/identity.py`). Which seat of a room that person
holds is read by comparing the cookie's id with the record's two, the
comparison `SafeView.may_act_for` makes with a Discord id. Rooms and
seats have a section of their own below.

A seat names a coach and is not permission to do anything. What a
coach may *answer* is `d12ball.prompts.asked_sides`, the same reading
the service answers an AI side by -- so the web app's gate and the
bot's are one reading of whose question it is. A prompt nobody in
particular is asked (every roll, the tutorial's Continue) is either
coach's, which is what "nothing rolls dice on its own" looks like
from this side. An observer sees the board, the score and what has
been said, and answers nothing.

**A page may only send back a control it was offered**, checked in
`webapp/server.py` before the model sees it. That is the web
equivalent of a button Discord never drew, not a second reading of
the rules: what may be chosen is still the prompt's and the position
is still the driver's, which refuses again on its own reading. What
it buys is that no hand-made request reaches an adapter with an
argument no prompt ever offered -- which is the case finding 4 of the
worksheet left open, since a bad wire value is a bug rather than a
refusal.

## Rooms, seats and who holds them

Step 2 of [../web-app-next.md](../web-app-next.md), under its decision
1: a room is created and has a link of its own; the first two people
in are its coaches and everybody after watches; a seat may be left and
taken again, before the game or during it; an admin may kick a seat.
And, from the author's review of the step (2026-09-26): the AI may
hold either seat, anybody seated may put it in an empty one, an admin
may kick it out for a person to take over, and an admin may give the
role up.

**Who somebody is, is a cookie and nothing else.** On a first visit
the page asks for a name; `POST /api/me` answers with a `Coach(id,
name)` written into one cookie as base64 JSON and an HMAC-SHA256 under
`FOOLBOT_WEB_SECRET` (`keys.secret()`), compared with `compare_digest`
on the way back in. A rename keeps the id. **Nothing is stored**: no
table of people to migrate or back up, and the game record holds the
id in a seat the way it holds a Discord id, which is why the id is an
`int`. It is random rather than the next of a sequence because
nothing stores the last one -- a counter would restart with the
process and hand out ids already sitting in somebody's seat -- and it
stops at 2**53 because it goes to a browser, which rounds a larger
number into somebody else's. A cookie is per device, so another
device is another person as far as the room knows; that is why a seat
is left and taken again rather than shared. With no secret set,
identities die with the process, which is the safe default the old
per-game links had. **The cookie is `Secure` when the browser came
over HTTPS**, and behind the tunnel that is the tunnel's
`X-Forwarded-Proto`, believed only from this machine
(`identity.came_over_https`; why, and why not simply "whenever
`FOOLBOT_WEB_URL` is HTTPS", is [collaboration.md](collaboration.md),
"Only ever over HTTPS"). **Leaving the app** (`DELETE /api/me`,
`identity.clear_cookie`) is the reverse of the first visit: it forgets
the cookie and nothing else, so a seat held under it stays held --
leaving is not vacating a seat, the way closing the browser never was.
A rename (`POST /api/me` again) already kept the id. Both are the
front door's, as "Save name" / "Leave the app", and nowhere in a room:
who you are is the app's business, not a game's, and a room's top bar
carries a "Rooms" link back to the front door instead (the author,
2026-09-26).

**A room is a game record.** It already has everything a room needs:
an id, a number, two seats, a status, the settings. `POST /api/rooms`
is `create_game(in_lobby=True)` with the creator in seat 1, and
`/room/{id}` is its page for as long as the record exists. The first
time somebody with a name opens a room with a seat free, the server
takes it for them through `GameService.take_seat`, so the second
person in is Coach 2; everybody after is an observer. Only the *first*
time: somebody who has left their seat stays out of it until they take
one, rather than being sat back down by their next poll.

**A seat changes hands on the record's rule.** `D12BallGame.take_seat`
and `vacate_seat` are the room's two moves, beside the lobby's own
(which stay as they are: the Discord lobby depends on the creator's
seat shifting when they leave, and on the moves closing at start).
Neither moves the other seat, and both refuse with `RuleRefusal`,
which the page shows as the record's sentence. **Why a seat may change
hands mid-game, and what keeps it safe:** everything the match keeps
about a side is by player *number* -- `home_player_number`,
`coin_winner_player_number` -- never by id, so a new id in seat 1 is
the same side, asked the same question, with the same position
(`tests/test_game_seats.py` takes the seat mid-match and compares the
prompt). `player_1_id` became `Optional[int]` for it; `None` is
written only by `vacate_seat`, so a save made before the rooms never
carries it.

**A seat is held by a person, by the AI, or by nobody, and an empty
seat is not the AI's.** Before the rooms the record had two ways to
say seat 2 and three things to say: an id was a person, and no id was
the AI (`is_solo_game`, which `side_is_ai` read) -- so a person
leaving seat 2 would have handed that side to Dinky on the next turn.
A room says it outright with `D12BallGame.ai_seats`, the seats the AI
holds: a seat with no id is the AI's if it is listed and empty if it
is not, and a side whose seat is empty waits for whoever takes it.
`ai_holds(n)` is the one reading, per seat, and `is_solo_game`,
`side_is_ai`, `side_controlled_by_ai`, `coach_name`, the AI's team
pick and the AI's coin choice all ask it -- which is also what lets
Dinky hold seat 1, where everything used to say "the AI is player 2".
**The field is `None` on every game no room touched** -- every Discord
game and every save made before it -- and `None` is the old reading
exactly (the AI in seat 2 where nobody is), so nothing on Discord
changed. `to_dict` leaves it out while it is `None`, so those games
are saved byte for byte as they were, and a checkout older than the
field still reads every save the bot writes; only a web room's record
carries it (`POST /api/rooms` creates one with `ai_seats=[]`), and an
older checkout cannot read one that does, which is the web file's
cost to pay rather than the bot's. The record's AI moves are
`seat_ai` (an empty seat, never both sides, never a one-player game)
and `unseat_ai`, before the game or during it; `GameService.seat_ai`
also answers the question the seat's side is being asked right then,
the way `resume` answers one a restart left the AI holding, and picks
the AI's team if the other side already has. `start_lobby` refuses a
room with an empty seat rather than seating Dinky in it. A test
game's one coach holds both seats and may not leave them once it has
started.

**Roles are the frontend's, in its own file.** Who is admin in a room,
and who has been in, is `webapp/rooms.py`, in
`data/d12ball_web_rooms.json` beside the games: written on every
change, read at start, a room the games file has lost dropped on load,
and a failed write logged and swallowed the way `save_games` swallows
its own. Never on the game record, because the save format is the
contract and a room role is not a fact about the game -- no rule reads
it. Anybody may become admin, by a button of its own behind "Take the
admin role for this room?", and an admin may give it up again
(`DELETE /api/room/{id}/admin`), which may leave a room with none; a
kick is refused unless the caller is an admin, and is `vacate_seat`
for the seated id, or `unseat_ai` for the AI, behind "Are you sure?".
Putting the AI in an empty seat is open to anybody seated -- the
coach whose opponent has gone -- and to nobody watching.
That is the frontend's authorisation over the record's rule, the way a
Discord helper's `manage_channels` gates a click the record then
judges. **What is not here is a second gate**: the identity says which
seat, never whether the seat may act.

**The seat names follow the coin.** The winner of the toss chooses
home or visiting (the Charter's "Winning the toss"), so no seat is
Home before it: the seats are Coach 1 and Coach 2 until the record's
`home_player_number` says otherwise, then Home Team Coach and Visitors
Team Coach, read off the record and never worked out here. The
state's `room` carries both seats (their label, their holder's name
or the AI's, and which is yours), how many are watching, whether the
reader is an admin, and their role: `observer`, `coach`, or `home` /
`visiting` once the coin has settled it.

## The room's table

Step 3 of [../web-app-next.md](../web-app-next.md): everything between
two seats claimed and the first prompt, and the rematch at the end.

**The front door** (`/`) lists the reader's rooms by where each
stands -- the lobby, the rest of setup, playing, finished -- and the
rooms with a seat free (`GET /api/rooms`), and opens a room the one
way, "Create a new game room": `POST /api/rooms` is always
`create_game(in_lobby=True, ai_seats=[])`, the creator in seat 1. The
AI and the tutorial are the lobby's own choices from there, not the
front door's (the author reversed the original two-buttons-and-a-
checkbox front door on 2026-09-25, so both read the same on the web as
they do on Discord): whoever is seated puts the AI in the empty seat
(`POST /api/room/{id}/seat/ai`, `seat_ai`, "Put Dinky in" on the
page), and the table's `tutorial` setting
(`POST /api/room/{id}/table/configure`) pins Training on the 7-space
board (`D12BallGame.pin_tutorial`) while nobody else has joined -- a
tutorial room's Start seats the AI in the second seat that pin closed
off. A room that never started may be closed
(`DELETE /api/room/{id}`, `discard_game`, whose refusal answers 409)
by somebody seated or its admin. A room's own row in "Your rooms" is
renamed the same way, straight off the front door
(the table's `name` setting), and the whole row -- not just the
name -- opens it.

**The table is in the prompt's place until kickoff**, drawn from the
state's `table` and nothing else: the settings, both seats and the
teams this reader may pick for theirs, the coin, home or visiting, and
Start. **Every question on it is the record's**, and each is the same
reading the door behind the button refuses against: which settings
are open is `D12BallGame.open_settings` (which `configure` opens with),
which teams a seat is offered is `teams_open_to` (which the Discord
team picker greys by too, so the two cannot drift), whether the coin
is owed is `coin_is_owed`, who owes the choice is
`home_choice_owed_by`, and which side they may take is
`home_choice_rail`. A page that worked out a pairing exclusion or a
tutorial's pin for itself would be a second copy of a rule, which is
the failure the whole split exists to prevent; a press the record
refuses comes back as a 409 with its own sentence and nothing
written. What the web app decides is who may press: somebody seated,
as the Discord setup views let either player. An observer is sent the
same table with every control off, and a press from one is a 403.

Each move is `POST /api/room/{id}/table/{start|configure|pick_team|
flip_coin|choose}`, one service door each, with a value off the wire
built into the model's type in the route (`Team`, `HomeChoice`) -- a
value the record cannot read is a 400, a bug in the page and not a
rule. A test game's one coach holds both seats and names which one a
pick is for.

**There is no Begin button, and none is wanted** (the author,
2026-09-26: "no begin button necessary"). The match is dealt by the choice, or by
the toss where the AI won it and chose, and the route runs `begin` in
the same request -- which is what the cog does straight after either.
A separate Begin would need a reading of "dealt, and its pre-kickoff
window never opened", and the match has none: before `begin` it
already answers the kickoff's ball-handler prompt, so a Begin offered
off anything else could reopen the pre-kickoff window mid-game. The
choice's response is therefore the first prompt.

**The rematch** is the one control `GAME_OVER` has (`webapp/present.py`),
and the only control that is not an answer to the match: it carries a
`post` naming the room's own route, `_was_offered` never matches it,
and `POST /api/room/{id}/rematch` is `GameService.rematch` -- a new room
with the finished game's settings and the same two seats, or the AI
where it sat, opened at its Start so a seat left empty is filled
before the sides are settled. Either coach may press it; a second
press finds the first rematch. The old room's state carries
`rematch`, so every page open in it follows to the new one, and a page
opened on the finished game later is offered the link instead.

## Its own process, its own file, a lock per game

`gamesaves/d12ball/storage.py` rewrites the whole save file on every
call and reads it once at startup, so two processes over one file
would overwrite each other's games with a stale copy (finding 13 of
the worksheet). That is why the web app first ran *inside* the bot,
over the bot's own `games` dict. The reasoning stands; the file is
what it was about. **One process per file**: the web app is its own
process over `data/d12ball_web_games.json`, the bot is its own over
`data/d12ball_games.json`, and two processes over two files do not
touch. What it buys: a bot restart does not touch a web game and the
reverse, there is no lock shared with `SafeView`, and no turn is ever
mirrored between a channel and a page.

`webapp.server.build_service` is the whole of the wiring: a
`RulesEngine` from the same four loaders the cog builds its own from
(`load_player_catalog`, `load_basic_ruleset`, `load_maneuver_catalog`,
`build_ai_strategies`, with the tutorial script checked against the
catalog the same way), the games `load_games(WEB_GAMES_FILE)` reads, a
`GameService` with the web app's own `WEB_BATCHING` -- the default
but for the walk-in, which it closes into a group so the challenge
image has its challenger ("The prompt's pictures", below); the cog's
`DiscordBatching` is Discord's economy (principle 8), and a page has
no rate limit to batch for -- and a save that writes that file and no
other. Then its own `GameLocks`.

**The one read across the line is the bot's, of this file, for the
statistics.** `/d12ball stats` with `source` set to the web app or
both calls `load_games(WEB_GAMES_FILE)` at the moment a coach asks,
reads it and lets it go: never at startup, never cached, never written
-- the bot writes `data/d12ball_games.json` and nothing else, as the
web app writes its own and nothing else. A web game is told from a
bot game by the record alone (`stats.game_source`: no guild is the
web). See [clock-and-records.md](clock-and-records.md), "What the
statistics are, and what they are not".

The store's two failure flags (a save failing, a file it could not
read) are per file for the same reason: the bot reads the web file
for the statistics without owning it, and that file being unreadable
must not stop the bot saving its own. See [gotchas.md](gotchas.md), "the swallowed save".

Both run on the one Windows checkout at `K:\` (decision 2 of the next
worksheet), sharing the checkout and the `data/` folder, each restarted
on its own.

**What the lock is for is ordering, not the apply.**
`GameService.apply_action` is synchronous, so on one event loop it
cannot be interleaved -- load, answer, run and save happen with
nothing else running. What interleaves is everything a frontend does
afterwards: renders, uploads, message edits, a response built from a
board it drew. Two answers applied back to back can be *presented* in
either order, which is a turn arriving in a channel out of sequence.
So `gamelocks.GameLocks` is held from taking an action to having
finished showing what came back. Each process has its own; the web
app's orders two coaches and their observers in a room. The Discord
half takes the bot's in `SafeView._scheduled_task`, which overrides discord.py's own click
dispatch because that is the only place a callback can be wrapped
(`interaction_check` runs before it and cannot hold anything across
it); a view that belongs to no game -- the hub's two -- takes no lock,
since there is nothing to order its click against;
`tests/test_game_locks.py` ratchets that the method being
overridden still exists.

## What a page is handed

A poll every two and a half seconds, and the whole state each time:
the scoreboard, the board as a layout (`webapp/board.py`, below), the
prompt with its controls, and the narration since the entry the page
last saw -- each entry with its time, and words only (the log draws
no board, "The page", below) -- and the chat since the
message the page last saw ("Chat", below). There is no websocket
and no diffing -- a game of D12 Ball is a few clicks a minute, and
the simplest thing that is always right is a re-read.

**The journal is the frontend's memory and nothing to do with the
save.** `MatchState.events` is the game's record of what happened,
and nothing in the game may read it to decide a rule; the journal is
the run of messages a page shows, in the order a coach reads them.
Losing it would leave the board and the prompt right, which is the
difference between a transcript and a position.

**It survives a restart anyway** (step 10 of
[../web-app-next.md](../web-app-next.md)): `webapp/journal.py` writes
every game's journal to `data/d12ball_web_journal.json`
(`WEB_JOURNAL_FILE`) on every `add` and reads it at start, so a room's
transcript is as good after a restart as its link already was. It is
still not the save, and for the same reasons the rooms and the chat
are not: a transcript is not a fact about the game and no rule reads
it, so it is never on the record, and the save format is the contract.
What the file keeps of an entry is the whole of it -- its words with
the model's tokens as written (rendered at the door on the way out, as
ever), the position the run stopped at (which `board.png?entry=`
serves, though no page draws it), and its roll's numbers as the wire
writes them, which the question box draws the dice from. The journal's
`showing_roll` is kept too, so the dice a restart finds up are still
up after it, and its `board_version`, because a browser keeps a board
by its URL and a version that started again at 1 would hand it an old
picture for a new position. It is bounded as in memory
(`JOURNAL_LENGTH`), an entry's id keeps counting past the bound, a
game the games file has lost is dropped on load, a closed room's
journal goes with it, and a write that fails is logged and swallowed
the way `save_games` swallows its own -- a lost transcript line is a
nuisance, a failed click over it is worse. Like every store here the
file is rewritten whole on each write; a snapshot is a few KB early in
a game and some 20KB at the end, so a room is at most a few MB.

It is fed by `GameService.listeners`, which hands every result the
service produces to whoever is watching, after the save. **A game is
played from two pages**: a coach reading a page has no request to be
answered when the other coach clicks on theirs, so the result the
service produced for that click is the page's only way to see the
turn, and an observer's only way to see either. The listener formats
nothing and is not a second presenter; a listener
that raised would take somebody's click down with it, so each is
called inside its own guard.

Two things the page does differently from the bot, and both are
batching, which is the frontend's (principle 8):

- **The lines that open a prompt go in the transcript.** The cog
  posts them *with* the prompt as one message (`render_prompt`'s
  `lead_in`) because a Discord prompt is a message; the page has a
  panel under the board that says what is being asked, so the lines
  go where every other line goes.
- **The hub's four menus are on one page.** Discord walks a coach
  through a menu at a time because a message holds twenty-five
  buttons; a page has room for all four, so the two answers that take
  a pair of names are one control with two menus on it rather than
  two steps. The *answer* is the same one `Action`.

### Chat

**People in a room talking** (step 4 of docs/web-app-next.md, which
the author asked for on 2026-09-25): on Discord the channel is the
chat, and a room on the web had nothing of the kind. `webapp/chat.py`
keeps one message list per room -- a message is an id, the poster's
cookie id, the name on their cookie when they posted, the text and
the time -- bounded at `CHAT_LENGTH` (200, the journal's bound), the
oldest dropped. Anybody in the room with a name may post, coaches and
observers alike: `POST /api/room/{id}/chat {text}`, 403 without a
cookie, 400 for a message empty or over 500 characters after
stripping. It is a room route, beside the seats and the table,
because talking is something a person does in the room and not an
answer to the match.

**It is frontend state, like the room roles.** Who said what beside
a game is not a fact about the game, so it is never on the game
record, never handed to the service and never read by the model --
the save format is the contract, and a chat line would be the first
thing on it no rule reads. It is the web app's own file,
`data/d12ball_web_chat.json` (`WEB_CHAT_FILE`), beside the web games
and the rooms, written through on every post and read at start, so
unlike the journal it survives a restart. A separate file rather
than a section of the rooms file, so a room's roles and its talk are
written independently and a chat that fails to load costs no admins.
A write that fails is logged and swallowed, as `save_games` and the
rooms file swallow theirs; a room the games file has lost is dropped
on load, and a closed room's chat goes with it.

**It rides on the poll.** The room's state carries `chat` -- the
messages after the page's `chat_since` cursor, each `{id, name, text,
at, yours, colour}` -- and `chat_latest`; there is no endpoint for
reading and no websocket. Every answer that hands a page its state
reads the cursor (`_cursors` in `webapp/server.py`), a post's and an
action's included, so the poster sees their line at once and a page
that acts is not handed the whole chat again; the page also skips an
id it has drawn, since a post's answer and a poll can cross. `colour`
is read when the state is built, off the seat the poster holds now,
so a coach who leaves their seat is drawn plain from then on.

**It is never the model's voice.** A message is handed over exactly
as it was typed and the page sets it as text -- `<b>`, `**`, and a
`{team:orange}` are shown as those characters -- where the journal's
sentences are the model's, escaped and tokenised by `render_text`. A
chat line that reads "X scored" is the journal's to say; the chat
says nothing about the game.

## The page

**Two columns in Discord's colours** (2026-09-25, the author, after
seeing a page built as a Discord channel and finding it too much like
one). On the left, the board, and under it the prompt -- the ask and
its controls, marked when they are this coach's -- which is the page's
original shape, under the jumbotron bar across the top of it. On the
right, two panels: the game log and the chat. **A divider between the log and the chat** is
dragged (or moved with the arrow keys, and reset by a double-click) to
share the column between them (2026-09-26, the author): which of the
two a coach wants the room for changes over a game. Each keeps at
least 80px, a panel read to its newest line stays on it as it
resizes, and the share is remembered in that browser's
`localStorage` -- a convenience per viewer, never the room's state,
so a browser that refuses storage opens at the default.

**A phone is one screen, not a long page.** The jumbotron and the
board stay on it; under them three tabs -- Move, Log, Chat -- switch
what fills the rest, and only the tab showing scrolls. A tab that is
not showing is marked when something new arrives in it, gold on Move
when the prompt is this coach's. Stacking all five panels made a page
a coach scrolled past the board to answer and past the answer to read
what happened, which is the opposite of a table.

**Your turn reaches a coach who is not looking.** The tab's title
carries a mark while the prompt is theirs (`prompt.yours`), and where
the browser allows it one notification per prompt names the ask
(step 10 of [../web-app-next.md](../web-app-next.md)). Permission is
asked once, on the first control the coach presses, and never on
load: a browser asked before anybody has done anything is how a site
comes to be refused for good, and a click is the gesture a browser
wants the question behind. A prompt is one notification however many
polls see it -- it is keyed on its kind and its ask, so the Coaching
Choice redrawing after each move in it is not a new one -- and a
prompt that goes up while the page has the focus sends none, since
the coach is looking at it.

- **The jumbotron is one bar across the top of the play area**
  (2026-09-26, step 2 of [../web-app-redesign.md](../web-app-redesign.md),
  replacing the panel at the head of the sidebar). Each team in its
  colour with an arrow for the way it attacks, "Home · coached by ..."
  under it and a gold BALL mark while it has possession, its d12
  showing the ball's speed as the field's does; the score with D12 BALL
  under it; then the clock -- the minute in the board's yellow
  beside the half, a thirty-segment track to the second half's last
  minute with the first half's marked, a red LAST POSSESSION chip, and
  the note between and after the halves (Halftime, Full time, Shootout,
  Abandoned, and the result, with the shootout's goals apart as
  `shootout_score_line` reports them, since the scoreboard carries them
  too) -- and under it a time-out tile per team. Where the step's
  prompt and the design canvas differed in the small things (the
  canvas's upper-case names, its arrow after the visitors' name too,
  its tiles in a row under the clock), the canvas was followed. **Every value is the match's,
  read by `board.jumbotron`**: possession is `ball.possession`, a tile's
  held or spent is `may_take_time_out` (the half's own count, which
  halftime clears), the track's length and its halftime mark are the
  clock's constants, last possession the scoreboard's flag;
  `JumbotronTests` hold each against the match. The coach's name is the
  game's coaches, as it always was.
- **The time out is a tile, not a button.** The tile is outlined in the
  team's colour with a referee's T while the side holds its time out,
  dashed and struck through once spent, and lit gold -- "TIME OUT ·
  <team> · click to call it" -- when, and only when, the turn put to
  this viewer offers it. **Whether it is lit is the prompt's, not the
  bar's**: `present._turn` builds the time out as it always did, off
  `TurnOptions.actions`, and marks the control with a `place` (the tile,
  and the side the turn is put to, `asked_sides`); the page draws a
  placed control there instead of in the question box, and pressing the
  tile sends that control's `action`, which is checked against what was
  offered like any other. So a coach who is not asked, an observer, a
  railed time out or a position with none to call gets an unlit tile
  from the same reading that used to give them no button, and
  `test_the_lit_time_out_tile_is_the_time_out_button` holds that the
  tile plays exactly what the button did. `place` says where on the
  page, never what is answered; it is the shape step 4 can extend to
  the pieces on the board.
- **The benches open on demand.** Each team's bench and back bench
  is behind a button under the board: shown while the pointer is on
  it, kept open by a click. The board shows the field; a coach looks
  at a bench when they are thinking about a substitution, and the
  cards are the same cards either way.
- **The log is words only**: each entry a block with an edge, a new
  play's in blurple. It draws no board (2026-09-26, the author): the
  live board is beside it, and a snapshot in every stopped entry
  pushed the lines a coach reads off the panel. An entry's wire shape
  carries no `layout`; the journal still keeps the position the run
  stopped at, and `board.png?entry=` still serves it -- kept although
  no page asks for it now (the author, 2026-09-26). **It draws no
  picture of any kind** (2026-09-26, the author, at step 8): not the
  dice, not the challenge. A picture belongs to a question and goes
  with it ("The prompt's pictures", below); what the challenge image
  shows, the log says in words.
- **The chat is people talking** ("Chat", under "What a page is
  handed"): everybody in the room may post under the name on their
  cookie, a seated coach's name in their team's colour and an
  observer's plain, with a one-line input and Send.

**The buttons are Discord's**: four colours and one shape, and each
control carries its colour (`style`) from `webapp/present.py`, set to
what the Discord view puts on the same button -- Maneuver blurple,
Shoot to score red (the time out is the jumbotron's tile, above); a roll blurple and a shot's or an
own goal's red; yes blurple and no grey; Done green; the offense's
cards red and the defense's green. The colour is the frontend's
(principle 8), so it is set in the web app's builders beside the
labels, not read from the model. The Coaching Choice is a button per
menu, opened in place with a Back, because that is how the hub walks a
coach through it on Discord; the answers are the same `Action`s the
page always sent.

**The field is drawn from scratch** (2026-09-26, step 1 of
[../web-app-redesign.md](../web-app-redesign.md), off the design the
author reviewed; it replaces the board drawn in the bot's layout). A
dark stage: the zone names over a row of rounded spaces, a goal slab
at each end, and under them the two shooting ranges with a KICKOFF bar
between -- the side on the ball's range lit gold while it stands where
it may shoot from. An end zone's spaces carry the defending side's
colour faintly; the kickoff space a faint ring. Each space has two
lanes, the visitors' above and home's below.

- **The meeple is `render.MEEPLE_PATH`**, drawn from `meeple_geometry`
  at 50px on the stage (scaled with it), in the team's colour with its
  ink outline, the role letters on the body and, where
  `species_abilities_apply` says so, the species icon over them -- the
  icon tinted in the ink by the page, which is what `species_icon`'s
  tint does (keep the alpha, replace the colour).
- **The fan is `board.py`'s, not the page's.** Two or more of one team
  on a space overlap diagonally, leaning toward the goal they attack,
  the ball's holder in front and the rest in the board's order; the
  steps are the design's (a pair 30 across and 22 down, three 22/16,
  four 17/12, more no wider than four), so a four-fan stays in its
  space. `board.fan` hands back each piece's place and the names
  front first, and `FanTests` hold the layout to that -- the page
  only places what it is handed, so the rule is tested where it is
  decided and not in the HTML. The holder is whoever the match names
  (`ball_carrier_id`, else `active_player_id`); a space where nobody
  is named keeps the board's order and draws the ball on its front
  piece, which is a picture and decides nothing.
- **The badges are the bot's emoji**: the exhaustion token with its
  count (the drain token on a Cyborg) off the bottom right of a piece,
  the condition off the bottom left, all drawn over the whole fan.
  `board.py` names the emoji, making `draw_card`'s choice, so the page
  reads no flag to pick one. The ball is the d12 showing its speed:
  off a home holder's top right, a visiting holder's bottom left, or
  larger at the centre of an empty space.
- **A space clips**: nothing on it -- a name, a badge, a fan -- leaves
  it, and a name is nudged to stay inside before the clip has to cut it.
- **No cards on the field.** Hovering a meeple (or a bench card) shows
  its printed card beside it, `player_card_png` in the face the mode
  plays; a press and hold does it on a touch screen. Clicking the card
  pins it, clicking a pinned card or the meeple opens it full size,
  and Esc or a click elsewhere puts it away. The benches still open
  from their buttons (step 8 redraws them).
- **What a lit piece or goal looks like is built but not yet fed**: a
  gold outline, a gold name and a chip saying what clicking means,
  with any cost as the token image and a count; a goal's gold ring.
  Step 4 lights them from `PendingPrompt.options`.

Every picture beside the field is still the model's own drawing,
served by `webapp/pictures.py` in a worker thread and cached. The PNG
is still served, and a board opened full size links to it, as the
bot's "View full image" button does. The log draws no snapshot
(above); `board.png?entry=` draws the position the service stopped
at, which is what `Narration.board` carries, so its picture of a
loose ball is the position the ball was loose in, not the position
after it was won.
The cog's own `cyborg_condition_ids` moved onto the engine to make
the board possible at all: which players draw a Cyborg's condition
marks is `has_species_ability` asked of everybody a mark would be
drawn against, which is a rule and not a rendering brief.

**What the layout may carry is what the rules answer.** `board_layout`
reads the position the way `render_match_image` reads it and asks the
renderer's own functions, or the match's, for everything worked out
from the rules -- the space codes, the zone labels, the range bands,
whose marks are a Cyborg's, whether a meeple carries a species icon,
the kickoff space, whether the side on the ball may shoot from where
it stands. The
page lays out what it is handed; it decides nothing, which is
`tests/test_web_board.py`'s check: the layout against the match it
read.

**The tokens are rendered at this frontend's door**, the way the cog
renders them at its own, and with the same pictures: a team is its
team emoji, a role the role badge edged in the team's colour, a
condition its mark -- the PNGs the bot uploads as application emoji,
served from `d12ball/images/emoji/` -- and a coach their name off the
record. `render_text` escapes first, renders the narration's own
markdown second, and the tokens third, and the order is the whole of
what makes it safe -- rendering tokens first would put markup in
front of the escape, and running the markdown after them would read
an emitted attribute as emphasis. The markdown is rendered rather
than stripped because the model's sentences are written in it
(principle 5): Discord's client draws it for the bot, and this draws
it here, headlines at all three of the levels the model writes.

### The dice

**A roll's picture is the bot's own** (step 7 of
[../web-app-next.md](../web-app-next.md)): one picture for both
frontends, because the model's voice is one and so is its picture of a
roll; HTML dice would be a second drawing to keep right. Step 7 drew
it in the log. **Since step 8 it is drawn in the question box**
(2026-09-26, the author: no picture in the log, and the dice in the
question box), at the top, above whatever is asked next -- on Discord
the prompt a coach pressed *becomes* the dice, so the question area is
where they are read. The log keeps the roll's words.

- **Every roll's dice**, whatever rolled them -- a skill test, a loose
  ball, a score attempt, a shootout test, an own goal, an injury test,
  a Mind Pull (the author, 2026-09-26).
- **They stay up until the next thing happens in the game**, by
  either coach or the AI, and come down with it: the journal's
  `showing_roll` is the last roll of the latest result the service
  handed over, and `None` once a result comes with no roll in it,
  whether or not it said anything. The page is handed it as `roll`
  (its shape and its picture's URL), everybody in the room the same.
  A re-roll after a tie is a new roll, so it replaces the last.
- **Drawn apart from the prompt** on the page, since a tie can hand
  back the same question with a new roll behind it, and the prompt is
  only redrawn when it changes.
- **Not animated yet.** The author would like a roll to be rolled with
  an animation at some point ([../web-app-next.md](../web-app-next.md),
  "Later, and not now"); the picture is still the bot's own, drawn
  once.

- **The journal keeps the roll on the entry it rode on.** An entry
  made from a result's answer keeps `GameResult.detail`; one made from
  a group keeps `Narration.detail`, which is where an AI's answer
  carries its roll (the AI rolls no dice, but its Mind Pull is a
  choice that rolls one -- a die the cog's `post_ai_answer` does not
  draw today). A roll with no line beside it still makes an entry.
  The entry's wire shape says `dice` -- the roll's shape, or `null` --
  and `dice_after`.
- **`GET /api/room/{id}/detail/{entry}.png` draws it** with the same
  `render.py` function the Discord view for that roll calls, off the
  same numbers, in a worker thread, and keeps it (`DICE_CACHE`): an
  entry never changes. **The renderer is picked by the roll's shape**,
  the `shape` its `to_dict` writes (`webapp/pictures.py`, `DICE`),
  never by the prompt kind: the kind is the question and the shape is
  what was rolled, and an AI's Mind Pull and a tie that hands back the
  same question are where the two part. The four contests are
  `d12ball/dice_brief.py`'s `render_contest_dice` -- the brief the
  cog's views call too, moved below the renderer for this -- and the
  single dice are `render_own_goal_dice`, `render_mind_pull_die` and
  `render_injury_test_die` with the arguments the cog's `post_*`
  methods pass. The match is asked only which side a player is on;
  the own-goal die's colour is the roller's, which
  `OwnGoalRoll.player_id` carries because by the time the step
  returns the ball has changed hands (the reason `ShotDice` carries
  its shooter).
- **Where the picture goes among the lines is the Discord view's
  order**, which is batching and so the frontend's (principle 8):
  every roll's prompt becomes its dice and the verdict follows
  (`SkillTestView.roll`), so the picture comes first; the own-goal
  roll's breakdown is the text of the message its dice are attached
  to, so it is read above them and the verdict under them
  (`LINES_BEFORE_DICE`). The question box draws no lines beside the
  dice, so this now reads only for the wire's `dice_after`.
- **The URL carries the entry's time** as well as its id. A picture is
  served to be kept, and an entry id is only as lasting as the journal
  file it is in; the time keeps a browser from showing a roll it
  cached before under an id handed out again. The dice are drawn from
  the roll's wire dict, the shape the journal keeps and reads back
  after a restart, which is why the Mind Pull's `to_dict` carries its
  `target_label`: the die's band is worded once, by the model.

### The prompt's pictures

**A question is asked over the matchup it is about, where the cog
posts one with it** (step 8 of [../web-app-next.md](../web-app-next.md)):
the shot's composition over a score attempt's roll
(`D12Ball.begin_score_attempt`), and the challenge image over the
maneuver pick, which on Discord sits directly on top of it
(`announce_maneuver_challenge`). `webapp/present.py`'s
`PROMPT_PICTURES` is the table, **keyed on the kind**, and each is
drawn by the function the cog calls off the same brief --
`dice_brief.score_attempt_brief` and `maneuver_challenge_brief`, moved
below the renderer for this so the two frontends draw one picture
(`webapp/pictures.py`: `score_attempt_png`, `challenge_png`).

- **Deliberately not the field strip or the coach's half-field**
  (2026-09-26, the author): coaches can see the field, since the
  page's board is beside the prompt. The cog draws both because a
  channel's board has scrolled away by then; the page's has not.
- **It is in the question area and goes with the question.** It sits
  between the ask and the controls, as an attachment sits between a
  Discord message's text and its buttons, and the next question
  replaces it. Nothing of it goes in the log.
- **The challenge is the position's challenger.** The kind says there
  is a picture; who is in it is `match.challenger_id`, set when a
  challenger is sent and cleared by `reset_maneuver`, so an
  uncontested maneuver has none. That reads who is standing where, as
  the board does -- not what is asked, which is still the prompt's.
- **It is the same picture for a coach and an observer.** Both are
  pictures of the position and neither holds a hand.
- **`GET /api/room/{id}/prompt.png` draws the prompt the match is on
  now**, whatever the URL says, in a worker thread, and keeps it with
  the boards. The URL's `v` is the board version and its `p` the kind
  (and the challenger, for the maneuver pick): a browser keeps a
  picture by its URL.

**The log says the challenge in words.** On Discord the walk-in is
followed by the challenge image; the log draws none, so the entry for
the group tagged `AUTO_RESOLVE_CHALLENGER` ends on a line saying what
the picture shows -- who is on the ball, who challenges them, where,
and each one's skill -- worded from the same brief the picture is
drawn from, when the result is recorded (the same post-run position
the cog draws it from). It is the picture as a caption, which is the
frontend's (the tokens in it are the model's own, rendered at this
door); the walk-in's own lines, where there are any, come first.

**That takes one boundary of the web app's own**: `WEB_BATCHING` closes
the walk-in into a group of its own (`own_message`), where the default
`Batching()` carried its lines into whatever came next and so named no
challenger. It is batching and so the frontend's (principle 8), and it
is the only one: the web app stops nowhere the model does not and
carries every answer the default way, because it has no rate limit to
batch for.

## Beyond the game

Step 9 of [../web-app-next.md](../web-app-next.md): the slash commands
that are not about Discord, each over a model function both frontends
call. The rules and the reference cards are step 11's ("The rules and
the player aids", below).

**My rooms, resume and abandon.** The front door already listed a
coach's rooms by where each stands, and an in-progress one opens; an
abandoned room is listed under the finished, marked "Abandoned"
(`room_status` reads a finished game as finished even if it was
abandoned in its lobby). Resume was already a route, offered where the
state's `owed` is true. **Abandoning is `GameService.abandon`** -- the
record's `abandon`, which refuses a game already over, saved -- and
`POST /api/room/{id}/abandon` is it, for a seat and never an observer
(403) -- **nor an admin without a seat** (the author, 2026-09-26: an
admin may close a room nobody played in, but only a coach ends a game
that was) -- behind "Are you sure?" as the command is behind
"confirm". **The page offers it only once the game has kicked off**
(the author, 2026-09-26): before that the table's "Close this room" is
the way out, so the two buttons are never up together. The route still
takes an abandon in setup, as the command does; the page just never
asks for one. **An abandoned game offers the rematch**, as one played
to a result does (the author, 2026-09-26): it reads as finished, so
`pending` answers `GAME_OVER` and its one control is the rematch. It
was cog logic only in that the cog called the record and saved by
hand; the cog now calls the same door, after clearing its own two
message ids. The room stays: its number stays taken, its board and log
readable, its statistics count it as abandoned, and a game abandoned
before kickoff is sent no table.

**The statistics are the bot's tables.** `GET /api/room/{id}/stats`
is `/d12ball stats game` over `stats.game_tables`, open to anybody who
can open the room, and the page shows it under the prompt once the
game is over. `GET /api/stats?kind=` is every web game's numbers cut
by kind, `stats.report_tables` for each of the four scoped reports,
on a page of its own (`/stats`) linked from the front door. What the
cog held that was not Discord moved into `d12ball/stats.py` for it
(clock-and-records.md, "What the statistics are, and what they are
not"), so the two frontends post the same tables from the same
functions and differ only in how: a code fence per message there, a
`<pre>` per table here. **The page never reads the bot's file**: the
report is over this process's own games, the ones the service holds
from `WEB_GAMES_FILE`; `source` is accepted only as `web`, anything
else a 400 rather than a wider read, so the one read across the line
stays the bot's of this file and never the reverse. A heading is the
same `format_scope_heading` the bot's is.

## The rules and the player aids

Step 11 of [../web-app-next.md](../web-app-next.md): everything a
Discord coach can pull up beside a game without it being a turn --
`rules_full`, `rules_search`, `maneuver_reference`,
`role_abilities_reference`, `species_abilities_reference`,
`team_reference` -- and the two rulebooks, which Discord has only in
print. `webapp/aids.py` holds all of it and `webapp/static/aids.js`
draws it: a **Rules & aids** panel opened from the room's header and
from the front door, and `/rules` on a page of its own. Every route is
a read-only GET open to anybody -- an observer, or nobody with a
cookie -- takes no lock and touches the service no further than
reading the game; nothing in it goes in the log.

**The rules are `rules_doc`'s, numbered by the Charter's build.** The
living rules carry no Law numbers; the Charter gives them at build
time (`rulebooks.number_blocks`, [rulebooks.md](rulebooks.md)), and
the Learn to Play cites them as *(Law 6.4)*. A page that set
`docs/living-rules.md` as it stands would be a Charter without the
numbers the other book points at. So `/rules` is one section per
`RulesSection` of `rules_doc.load_rules_document` -- the same parse
`/d12ball rules_search` answers from, and `GET /api/rules?q=` is its
`RulesDocument.search` -- each headed with its number from
`number_blocks(parse_markdown(...)).headings`, looked up by slug. The
two already agree on a slug (`rulebooks.Heading.slug` is
`rules_doc.slugify_heading`), and `tests/test_web_aids.py` holds that
agreement: every heading the Charter numbers is a section with that
number, and the front matter, the Parts and the Appendices are
unnumbered on the page as in the book. A link to a heading reads
`text (6.4)`, as the book resolves it. Each section's text is read by
`rulebooks.parse_markdown` -- the books' own subset, which raises on a
line outside it -- and set as HTML after escaping, so the page and the
printed Charter fail on the same line; the Charter's one figure is
served from `docs/rulebooks/figures/`. There is no second copy of the
rules text: the page is re-rendered when `rules_doc` re-parses a
changed file, and a missing file is logged at ERROR and answered 503,
as `load_rules` refuses on Discord.

**The books as PDFs, and only as PDFs.** The printed layout is
`rulebooks.py`'s and the figures are laid out for it; an HTML Learn to
Play would be a second layout of the book to keep right, the mistake
`webapp/pictures.py` exists to avoid for the cards. `rulebooks.book_bytes`
sets a book into memory (`build_book` writes the same bytes, so
`scripts/build_rulebooks.py` is unchanged), and `/books/charter.pdf`
and `/books/learn-to-play.pdf` serve it inline, on letter paper, set in
a worker thread once per process and again when the source's mtime
changes -- never written to `print/`. The in-page reading is the
Charter's text, searchable, for a coach mid-turn; the PDFs are the
books.

**Which aids a room gets is the model's.** The room's state carries
`aids`: the hexagon at `RulesEngine.maneuver_reference_tier(game)`, the
species card only where `species_abilities_apply(game)`, the team cards
in the face `personal_abilities_apply(game)` says the game holds, and
the three answers themselves, so `app.js` decides none of them and
never reads `game.mode`. The seat's own team comes first and the other
a tab away; an observer gets both, seat 1's first. At the front door,
with no game to ask, `GET /api/aids` offers all of it: both hexagons
named by tier, the species card, every team with both faces. Every
picture is the one the reference command posts, drawn by the same
function (`render_maneuver_reference_image`, `render_role_reference`,
`player_cards`), in a worker thread and kept with the cards. The
species card is the one exception in shape: the page shows the two
`species_cards.REFERENCE_FACES` as two images, since it has no
attachment tiles to crop them, where Discord posts them side by side.
The maneuver pick carries `reference`, a **link** to the hexagon at the
game's tier, as the Discord prompt's reference button posts it --
never a picture inline, since the question box already carries the
challenge over the hand (step 8).

**Why the two choices moved below the cog.** Which hexagon a game gets
was `D12Ball.reference_tier`, and which two species faces a screen
shows was the cog's `CARD_FACES[0]`; the web app may import neither.
Neither is Discord's -- "a screen has no table to lay a card on" is as
true of a page as of a channel -- so they are
`RulesEngine.maneuver_reference_tier` and `species_cards.REFERENCE_FACES`,
and the cog asks them, the way `cyborg_condition_ids` moved for the
board. Every image the four reference commands post was byte-identical
before and after the move.

## What it does not do yet

- **The dice are not animated** ("The dice", above).

- **Two pictures around a roll are the bot's alone**: Volatile's
  ignition die, with its caption (`D12Ball.post_volatile_ignition`,
  one per side that ignited), and the scorer's portrait under a goal.
  Both ride on the same `detail` the page already keeps -- the
  ignites on a contest's, the scorer on a shot's -- so if they come to
  the page they go **in the question box beside the dice they came
  with**, and down with them; never in the log (2026-09-26, the
  author: no picture in the log).

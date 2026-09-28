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
| `FOOLBOT_WEB_SECRET` | What a person's cookie is signed under (`webapp/keys.py`). With none set, `serve` makes one once and keeps it in `data/d12ball_web_secret` (`keys.keep_secret_in`), saying so at WARNING, so a cookie still outlives a restart; only a process that never names the file -- a test, a script -- makes one that dies with it. |

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
role up. Since the author's lobby review of 2026-09-26 anybody seated
may also take the AI out -- the ✕ on its seat -- because whoever may
put it in may change their mind; a person is still kicked by an admin
alone.

**Who somebody is, is a cookie.** On a first visit nobody is asked
anything: `GET /api/me`, which every page calls first, finds no cookie
and makes somebody up -- a `Coach(id, name)` under
`identity.guest_name`, `adjective_creature_#####` (a kind word, an
animal or a fantasy creature, and five digits), written into one
cookie as base64 JSON and an HMAC-SHA256 under `FOOLBOT_WEB_SECRET`
(`keys.secret()`), compared with `compare_digest` on the way back in.
A name is asked for nowhere because it was a question standing between
a link and the game, and a made-up one is enough to seat somebody (the
author, 2026-09-27). The words are drawn with `secrets`, not
`engine.rng`: a name is nothing the game draws, and the tests seed
that one. There is no table of people to migrate or back up, and the
game record holds the id in a seat the way it holds a Discord id,
which is why the id is an `int`. It is random rather than the next of
a sequence because nothing stores the last one -- a counter would
restart with the process and hand out ids already sitting in
somebody's seat -- and it stops at 2**53 because it goes to a browser,
which rounds a larger number into somebody else's. A cookie is per
device, so another device is another person as far as the room knows;
that is why a seat is left and taken again rather than shared.
**A restart must never make a seated coach a stranger** (the author,
2026-09-27, after a coach came back to their own game as an
observer, in the same browser, more than once): so with no secret in
the environment the one `serve` made is kept in
`data/d12ball_web_secret` rather than dying with the process, as it
did while the per-game links were the model; and a cookie that fails
its signature -- the one way a returning browser is made somebody
new -- is said at WARNING with the name and id it claimed and the
new person it became, so the next time it happens the log says
whether the secret moved. **The cookie is `Secure` when the browser
came over HTTPS**, and behind the tunnel that is the tunnel's
`X-Forwarded-Proto`, believed only from this machine
(`identity.came_over_https`; why, and why not simply "whenever
`FOOLBOT_WEB_URL` is HTTPS", is [collaboration.md](collaboration.md),
"Only ever over HTTPS"). **So a browser the tunnel carried over plain
`http://` is sent to `https://` before anything answers it**
(`server.https_only`, a 308, to `FOOLBOT_WEB_URL`'s address where it
is `https://`): it sends no `Secure` cookie, so it used to be handed a
second, non-`Secure` person in the same browser -- the other way a
coach came back as an observer. Every response over the tunnel's
HTTPS carries `Strict-Transport-Security` for a year
(`STRICT_TRANSPORT`), so after one visit the browser never tries
`http://` again. A request with no tunnel in front of it is neither,
so a checkout on a laptop stays on `http://localhost`.

**No two people hold the same name at once** (the author,
2026-09-27), as written -- "Tom" and "tom" are two names, the
author's call the same day -- so the one thing kept about a person is
which name each id holds right now: `webapp/names.py`, over
`data/d12ball_web_names.json`. A cookie alone could not say it --
nothing sees every cookie -- which is why this is a file and not a
check. It is the one reading of a name: `WebApp._person` answers the
cookie's id under the file's name, and the cookie's own copy is only
what the name was when the cookie was set. A made-up name is drawn
again while somebody holds it; a rename to a held name is refused
with 409 ("Somebody is already called that."); a rename frees the old
name. An entry lasts as long as its cookie can -- `COOKIE_MAX_AGE`
from the last time it was set, dropped on load after that -- and the
file is written under a fingerprint of the secret, so a file written
under another secret, or under a per-process one that died with its
cookies, is started afresh rather than holding names nobody can still
carry. A cookie the file does not know (one set before it existed)
keeps its name at its next `GET /api/me` if nobody holds it, and is
given a made-up one if somebody does. **A name reaches the seats**:
`GameService.rename_coach` over `D12BallGame.rename_coach`, per game
under its lock, so a seat is never still named after somebody who is
now called something else -- and another person can then take the old
name without the rooms showing two of it. Chat lines keep the name
they were posted under; they are what was said, not who is here.

**The account menu** is the front door's alone -- `@name` at the
right of its top bar, and a click opens it: the name, edited and saved
there, and **"Delete all my games"** (`DELETE /api/me/games`), which
the page asks "are you sure" about first. It erases every game the
reader holds a seat in -- the "Your rooms" list, whatever each stands
at, finished games and their statistics included and for everybody in
them -- through `GameService.delete_game`, with each game's journal,
chat and room state, then gives the reader a new made-up name on the
same id. A page still open on a deleted game finds it gone at its
next poll and goes back to the front door. It replaced "Leave the
app", which forgot the cookie and nothing else (the author,
2026-09-27). `delete_game` is not `discard_game`: the Discord bot
abandons a played game and never erases one, and only the web app
calls it. Who you are stays the app's business, not a game's, so a
room's top bar carries a "Master Lobby" link back to the front door
instead (the author, 2026-09-26).

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

**A seat is taken over in one move** (the author, 2026-09-27): a coach
seated on one device who opens the room on another is, as far as the
room knows, somebody new -- an observer. So they become the room's
admin there and take the seat over: `D12BallGame.take_over_seat`,
through `GameService.take_over_seat` (`POST /api/room/{id}/seat/
takeover`), the kick and the take judged whole -- whoever holds the
seat, a person or the AI, out, and the reader in -- so a takeover the
record refuses leaves the seat as it was rather than empty, and the
match is written once. It refuses somebody already seated (they would
hold two seats), a one-player game's second seat, and wherever the
kick would be refused (a test game's seats once it has started), each
before anything moves. The route is an admin's, as a kick is; the
room offers it (`room.take_over`, asked of a copy) only to an admin
who is watching.

**Roles are the frontend's, in its own file.** Who is admin in a room,
who has been in and what each was last called (the table's sideline,
step 9 of [../web-app-redesign.md](../web-app-redesign.md)), is
`webapp/rooms.py`, in
`data/d12ball_web_rooms.json` beside the games: written on every
change, read at start, a room the games file has lost dropped on load,
and a failed write logged and swallowed the way `save_games` swallows
its own. Never on the game record, because the save format is the
contract and a room role is not a fact about the game -- no rule reads
it. Anybody may become admin, by a button of its own behind "Take the
admin role for this room?", and an admin may give it up again
(`DELETE /api/room/{id}/admin`), which may leave a room with none; a
kick is refused unless the caller is an admin -- or, for the AI's
seat, anybody seated -- and is `vacate_seat` for the seated id, or
`unseat_ai` for the AI, behind "Are you sure?".
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

**The front door** (`/`), which the author named **the Master
Lobby** on 2026-09-27, lists the reader's rooms by where each
stands -- the lobby, the rest of setup, playing, finished -- then
every other room still being played, those with a seat free above
the full ones (`GET /api/rooms`: `mine`, `open`, `full`), and opens a
room the one way. The full rooms are there because a coach on another
device is another person (the author, 2026-09-27: "if I'm in a game
in one browser, and want to jump in from a different device -- I
can't see the game"); they open it, become its admin and take their
seat over. Somebody else's finished room is not listed, and a room
nobody has had open for a day leaves both of the others' lists
(`OPEN_ROOM_IDLE`, below). A room is opened the one
way: `POST /api/rooms` is always `create_game(in_lobby=True,
ai_seats=[])`, the creator in seat 1. A room that never started may be
closed (`DELETE /api/room/{id}`, `discard_game`, whose refusal answers
409) by somebody seated or its admin. A room's own card in "Your
rooms" is renamed straight off the front door while it is in its
lobby (the table's `name` setting), and the whole card opens it.

**A dead room is cleared from its card** (the author, 2026-09-26, after
the cache outage left rooms opened by people who saw nothing): a card
in "Your rooms" carries **Close** while nothing has been played in it
and **Abandon** once the game is under way, each the room page's own
route. Abandon always asks "Are you sure?"; **Close asks only when
somebody else holds a seat** (`close_asks`, `others_seated`: a person
other than the reader, never the AI or a test game's one coach), on
the card and on the table's "Close this room" alike -- the author,
2026-09-26: a lobby with nobody else in it is nobody's loss -- the listing's
`may_close` is `_may_close`, the same reading as the table's, and
`may_abandon` is a seat in a game in progress, the room page's rule --
so the front door offers exactly what the room does, and the route
judges again. A card of the reader's own also carries **Leave seat** wherever
`vacate_seat` would stand (`may_leave`, asked of a copy) -- the same
route the room's menu calls, asked first while the game is under way,
since the side then waits, empty, for whoever takes it. A card in
the other two lists carries none of them: its reader holds no seat. **A room nobody has had open for a day leaves
the rooms with a seat free and the rooms in play** (`OPEN_ROOM_IDLE`): it is not closed, and
its coaches still see it in their own list, where its card closes it.
"Open" is any poll of the room's state, kept in memory
(`_looked_at`), so a restart counts every room from the restart --
which puts off hiding a room and never hides one early -- and nothing
about it is written to any file.

**The front door is row 1 of the design canvas** (2026-09-26, step 9
of [../web-app-redesign.md](../web-app-redesign.md)), as the author
reworded it on 2026-09-27: on the left "New to the game? Start by
playing the tutorial!" -- a link that opens a room with only the
tutorial set, the same as ticking "the tutorial" alone under a new
room -- a line on opening a room or joining one and sending its link,
a dashed gold "+ A new room" card ("Create a game! Invite a friend to
join you or play vs. the AI.") and the reading room -- the name is
not on the left but `@name` in the top bar, and the account menu
under it; on the right the rooms as cards -- `#pbw<n>`, the room's
name or its two teams, a status chip, both seats with their team's dot, and
the mode, the board and the clock. **A card with a gold edge is
waiting on the reader** (`your_move` on the listing): at the table, a
move on it is theirs (`_table_moves` -- Start once `start_lobby` would
take it, the coin, the choice of ends, a team for a seat of theirs
with none); in the game, the question up is theirs to answer
(`still_to_answer`, the same reading that marks the question box and
the tab's title). The clock is the jumbotron's own words
(`board.clock_note`, or the minute and the half), so a card and the
room never word the same moment two ways.

**The two ticks under "+ A new room" are the table's own moves, made
in sequence by the page** -- "Dinky in the other seat" is
`POST /api/room/{id}/seat/ai` for seat 2 (`seat_ai`) and "the
tutorial" is the table's `tutorial` setting through `configure` --
straight after the room is created and before the page goes to it.
The author had reversed an earlier two-buttons-and-a-checkbox front
door on 2026-09-25 because it made the AI and the tutorial the front
door's rather than the lobby's; the ticks put them back on the front
door without doing that, because nothing new decides them: no field
on the record, no second way of creating a room, and the record still
judges each (a refused tick leaves the room open, where the table
offers the same move again). **Dinky goes first**: the tutorial makes
the room a game for one, and `seat_ai` refuses one of those, while the
tutorial's toggle is still open with the AI seated -- the AI's seat
holds no id, so nobody has joined.

**The table is in the prompt's place until kickoff**, drawn from the
state's `table` and `room` and nothing else. **Every question on it is
the record's**, and each is the same reading the door behind the
control refuses against: which settings are open is
`D12BallGame.open_settings` (which `configure` opens with), which
teams a seat is offered is `teams_open_to` (which the Discord team
picker greys by too, so the two cannot drift), whether the coin is
owed is `coin_is_owed`, who owes the choice is `home_choice_owed_by`,
and which side they may take is `home_choice_rail`. A page that worked
out a pairing exclusion or a tutorial's pin for itself would be a
second copy of a rule, which is the failure the whole split exists to
prevent; a press the record refuses comes back as a 409 with its own
sentence and nothing written. What the web app decides is who may
press: somebody seated, as the Discord setup views let either player.
An observer is sent the same table with every control off, and a press
from one is a 403.

**Its shape is row 1 of the design canvas** (step 9 of
[../web-app-redesign.md](../web-app-redesign.md)). Before kickoff the
jumbotron and the board give way to it, since there is no match to
draw yet, and the in-game room panel gives way to its seat cards and
its sideline.

- **Two seat cards**: the label, the holder's name large (or "Empty
  seat · click to sit"), YOU and AI chips, the picked team's line, and
  while team selection is open **both** held seats' swatches -- the
  colour teams and the species teams, a row each. An empty seat draws
  neither the team line nor the swatches: the pick opens once
  somebody, or Dinky, holds the seat (the author, 2026-09-27), though
  the server still sends its teams, as nobody may press them. **The teams are picked in
  the lobby, beside the seats, before Start** (the author, 2026-09-26,
  off the canvas; the record's `picks_teams_in_lobby`, which only a web
  room's record answers yes -- "A web room picks its teams in its
  lobby" in [game-service.md](game-service.md)). Each swatch carries
  three answers: `offered` (`teams_open_to` for that seat; a pair
  greyed where it says so), `open` (the reader may press it) and
  `picked`. Which seats a reader picks for is `pick_seats`: their own,
  the AI's where they are seated -- **a seated coach may pick Dinky's
  team, and if nobody does, Dinky draws its own at the whistle**
  (`picks_itself` on its seat) -- and in a game for one (a test game,
  the tutorial) the second seat as well, which that one coach answers
  for. The route refuses any other seat; whether a pick stands is still
  `pick_team`'s.
- **The seat moves are drags, each with a click beside it**: the
  reader's own name dragged off the sideline into an empty seat (or
  the seat clicked) takes it; the Dinky chip dragged in (or "play
  against AI" in the empty seat, beside "invite your friends to play
  with this room link", the link copying itself) is `seat_ai`; the
  reader's name dragged out of their seat (or its ✕) leaves it; and an
  admin dragging somebody else out (or their ✕), or anybody seated
  taking Dinky out, kicks them. **Every kick goes through one function that asks "Are
  you sure?" first** -- the card's ✕, the drag and the in-game Kick
  alike, which `RedesignedTableTests` reads the page for. A drag
  carries only which of those it is; the drop makes the request the
  click makes. Only one's own name and Dinky are dragged *in*, because
  a seat is taken by the person who sits in it: the cookie says who,
  and nobody seats somebody else.
- **The top bar's topic renames the game** before kickoff, for
  whoever may change the name: the topic is the button, a dashed
  underline and a pencil beside it, and a click swaps it for a field
  that saves on Enter or when left and is dropped on Escape -- the
  same `configure("name")`, and the only place the name is changed:
  the settings carry no Name row, and on a phone the topic stays in the
  top bar, cut short, for that reason (the author, 2026-09-27).
  Clearing it gives the room back its "X vs. Y".
- **The settings are pills**: the current value gold, the others
  outlined. **What a setting is, is the model's** (`definition`):
  `describe_game_mode` for the mode, and `SETTING_DEFINITIONS` in
  `d12ball/formatting.py` for the test game -- "one coach plays both
  sides", its defining feature, with being kept out of the statistics
  said second (the author, 2026-09-26) -- and the tutorial. **A
  setting's note is the record's own sentence**: each
  value `configure` would refuse right now is asked of a copy of the
  record, the way the whistle's note is `start_lobby` asked of one
  (`_configure_refusal`, `_start_refusal`), so a dark pill says why --
  "Someone has already joined -- they would have to leave first." --
  in the words the press would be refused with. **What a mode plays is
  the model's definition too** (`describe_game_mode`, moved out of the
  cog for it, at the author's word on 2026-09-26): each mode pill
  carries the definition of the mode it would pick, and the row's note
  is the current mode's, unless the record has a refusal to say there.
  A definition and a refusal are shown side by side, never one
  instead of the other. A change that takes something away carries the
  model's `warning` (`configure_warning`: turning the test game on with
  Dinky seated kicks Dinky), and the page confirms it before sending.
- **The question box** asks one thing at a time: the coin -- the
  bot's own gold coin (the `3_gold_fortune` and `3_gold_doom` emoji,
  served) -- dark with `start_lobby`'s refusal until both seats are
  held and every side a person plays has a team, and clicked to flip.
  **There is no whistle: the coin starts the game** (the author,
  2026-09-27). Flipped in the lobby, `flip_coin` runs `start_lobby`
  and the toss in one request; the `start` move stays on the route for
  what else calls it, but the page no longer offers it. Then the face it
  came up large and the other small and dim, and "Click the goal you
  want to defend" over a miniature field whose two ends are
  `choose_home_or_visiting`'s two answers. **Which end is which is the
  board's** (`board.DEFENDED_ENDS`, off `ZONES`), so the goal clicked
  is the goal the field then draws on that side.
- **The sideline strip**: who is watching, by the name each was last
  seen under -- the web app's rooms file (`Room.names`), never the
  game's, and a name only, since who somebody is stays the cookie's --
  Dinky waiting wherever the record would seat it (`room.ai_seats`:
  `seat_ai` asked of a copy, offered only to somebody seated), and
  Copy the room's link / Become admin / Close this room as neutral
  controls.

**The top bar says who the reader is as one pill**, their name first
(the author, 2026-09-27): "<name> · Coach 1" (gold edge) before the
toss, "<name> · Home coach · <team>" (the team's colour) after it,
"<name> · Observer" otherwise, with "Take the free seat" beside it
when there is one -- all off `room.role`, the record's
`home_player_number` read. **The pill is the room's menu**: a click
opens everything the reader may do to the room from anywhere in it
-- take the free seat, take a seat over (an admin who is watching),
leave their own, kick the other (an admin; the AI, anybody seated),
put Dinky in an empty seat, become or give up admin, copy the link,
and the way out -- Close before kickoff, Abandon after. Which of them
is offered is the server's (`room.may_leave`, `room.take_over`,
`room.may_abandon`, the table's `may_close`), each route judges
again, and a kick is still asked first. An observer who is not an
admin is told how a seat on another device is taken back. **On a
phone held upright the pill fits the bar**: the name is cut short,
never away; the team's name and "coach" are dropped for the team's
emoji and the edge; "Take the free seat" is only in the menu; and
the pill takes at most half the bar, so the room's number and a stub
of its topic -- where the game is renamed -- stay. The room's number and its
topic (`game.topic`: the room's name, or the coaches and their teams)
share a baseline.

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
serves, though no page draws it), its roll's numbers as the wire
writes them, which the question box draws the dice from, and what the
log's edge and minute heading are read from -- the minute and half the
result left, and whether it was a goal or the clock ("The page",
below). The journal's
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
right, the sidebar.

**The tab icon is the bot's d12 emoji in periwinkle**, `static/favicon.png`,
which every page links (the author, 2026-09-27). It is the stroke art of
the `d12dice` and `d12dicecream` emoji, inked periwinkle and drawn a
little heavier so it holds together at 16 pixels. The author picked it over
the cream cut, which is lost on a light or orange tab bar. It is a
committed file rather than drawn by a build: the emoji are application
emoji the Developer Portal holds, with no copy in the repository, and
the web app renders no picture it does not have to.

**The sidebar is four tabs** (2026-09-27, step 10 of
[../web-app-redesign.md](../web-app-redesign.md)): Log, Chat, Teams and
Rules across the head of one 380px panel, the one showing under them.
A tab that is not showing gets a dot when something new arrives in it
-- red for news, gold where it is this coach's move -- which goes when
the tab is opened; the gold is the phone's, on Move, since a wider
screen has no Move tab and the question box is always in sight (the
author, 2026-09-27: no mark on a wide screen). It
replaces the log and the chat stacked with a divider between them
(the author's of 2026-09-26): with the teams and the rules beside
them, four panels do not share one column, and a coach reads one of
them at a time -- the author kept the log and the chat as separate
tabs on the step's PR (2026-09-27).

- **Teams** is both rosters as tables, `board.py`'s `rosters`: a row a
  player -- the field in the side's own order, then the bench, then
  the back bench, the record's three lists -- with the role and the
  name, OFF and DEF as the card prints them (`card_profile`, the same
  numbers the card and the field carry), the exhaustion as one token
  image a point (the drain token on a Cyborg), the condition emoji,
  and the space's code, "bench" or "back bench", with "· ball" on the
  holder. Hovering a row shows the card, and clicking it (or Enter)
  opens it. The page adds nothing to a number: `TeamsTabTests` hold
  every row to the card and the space the layout already hands over.
- **Rules** is "The rules and the player aids", below.

**A phone is one screen, not a long page** (2026-09-27, step 11 of
[../web-app-redesign.md](../web-app-redesign.md), the two phone
artboards of row 4 of the canvas; at 960px and under). The score and
the field stay on it; five tabs -- Move, Log, Chat, Teams, Rules --
switch what fills the rest, and only the tab showing scrolls. A tab
that is not showing is marked when something new arrives in it, gold
on Move when the prompt is this coach's. Stacking all five panels made
a page a coach scrolled past the board to answer and past the answer
to read what happened, which is the opposite of a table. The phone has
two shapes, by which way it is held:

- **Upright, the field is kept horizontal and whole, fitted to the
  width.** The seven spaces between narrow goals, the zone names over
  them and the ranges under them, laid out at the screen's own width
  rather than the desktop's 1200px scaled down -- scaled, a meeple
  would be 15px. A meeple is 30px with its role and species and no
  name; its badges and the ball scale with it; a hold on it opens its
  card, which carries the name. **The fans are still `board.py`'s**:
  each space carries `narrow_fans` beside `fans`, the same pieces in
  the same order leaning the same way, at `NARROW_FAN_STEPS` measured
  against `NARROW_MEEPLE_WIDTH` -- a space is about forty pixels across
  at 390px, room for one piece and a pixel's lean a step, so the
  narrow fan steps down its lane rather than across it. The page draws
  whichever it is handed and works neither out (`FanTests`).
  Pinching zooms; a tap on the field away from a piece opens the whole
  board at the desktop's size, as it did.
- **Upright, the move is a bottom sheet**: the Move tab's pane, edged
  in the state tag's colour, over the rest of the screen, with the
  tabs along its foot. It opens on the question -- the tag, the ask,
  what is lit -- and the box's own controls; the outcome and the
  reveal of what just happened come after them there, where on a
  wide screen they come first, because in half a phone's height the
  outcome at full size pushed the question out of sight. **Every
  thing lit on the field is on the sheet again**, large enough to tap:
  "LIT ON THE FIELD", each lit meeple at the desktop's 50px with its
  name and chip, each lit space, the ball, a goal, the ✕, a bench or a
  time-out tile as a gold object with its chips, and a piece picked up
  in a Coaching Choice, to put back. It is `readLit`'s index read a
  second time, each entry pressed exactly as its object on the field
  is, so nothing is on the sheet that is not lit on the field and
  nothing lit is missing from it -- **except in a Coaching Choice's
  hub**, where every player is lit to pick up: repeated, that was nine
  meeples above the substitution and swap controls, and the hub is
  answered on the field -- a click on a meeple, or a drag between the
  field and the bench -- so the sheet repeats nothing there (the
  author, 2026-09-28). The Coaching Offer lights only the bench tile
  and keeps its repeat. The sideline is on the sheet too,
  under the question, since the narrow field has no room under it.
  The compact jumbotron is one line: the teams, the score, the ball's
  d12 beside the side that has it, the minute over the half; the
  coaches, the track and the tiles are the wide screen's, and a time
  out that may be called is on the sheet with everything else lit.
- **On its side, the desktop field whole** (the 1200px stage scaled to
  the width, sideline and all), with the jumbotron's one line laid
  over the middle of the top bar -- the teams, the score, the minute,
  the half, and a time-out tile only where it may be called -- and the
  move one slim strip at the foot of the screen: the tag, the ask cut
  to a line, and the tabs as pills. The page scrolls under the top bar
  and the strip stays at the foot; the box, or the tab a pill opens,
  is under the field, and a tap on the strip's ask brings the box up.
  The field is large enough there to answer on, so the strip repeats
  nothing.
- The top bar is the room's number and the seat, the team's emoji for
  its name.

**A tablet on its side is a third shape: two columns** (2026-09-27).
A touch screen held on its side and wider than a phone -- 961px to
1400px across with a coarse pointer anywhere (`any-pointer: coarse`):
an iPad, a Surface -- got the desktop's layout, which stacks the
field, the question box and the sidebar; at 1180x820 the team names
were cut short and the question was under the fold, so every answer
took a scroll. There the jumbotron runs whole across the top, the
desktop field and its sideline fill the left column, and the right is
the phone's tabs -- Move, Log, Chat, Teams, Rules -- with only the one
showing filling the column and scrolling. The box opens on the
question as the upright sheet does (the ordering is one block shared
by the two), since in a column the outcome at full size would push the
answers down. The field is large enough to answer on, so nothing is
repeated. It is keyed on touch rather than width alone so that a
laptop at the same width keeps the desktop's page, which the author
reviewed; `any-pointer` rather than `pointer` so that an iPad does not
change shape when a trackpad is attached. Before kickoff it is the
desktop's table, which fits as it is. A tablet held upright is 960px
or under and is the phone's upright shape already. `TABLET` in
`app.js` is the same query, for the one thing the page does with it:
a refusal's Law opens the Rules tab.

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
  team's colour while the side holds its time out, dashed and struck
  through once spent, and lit gold -- "TIME OUT · <team> · click to
  call it" -- when, and only when, the turn put to this viewer offers
  it. The words are the whole of it: the prototype led them with a
  referee's T, and the author had it taken off on 2026-09-26 because
  "TIME OUT" says it. **Whether it is lit is the prompt's, not the
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
  page, never what is answered; step 4 extended it to every object on
  the board ("The answer is the thing on the board", below).
- **The sideline is under the field** (2026-09-26, step 6 of
  [../web-app-redesign.md](../web-app-redesign.md), with step 8 folded
  in; it replaces the benches that opened on demand). Each team has two
  boxes edged in its colour -- BENCH, "may come on", and BACK BENCH,
  "off for the game" -- home's under the home end and the visitors'
  under theirs, holding the meeples the field draws, badges and the
  hover card included. **Which player is on which is the record's**:
  `team_board.bench` and `back_bench`, the two rows the popover had,
  each entry the card and the piece (`board.py` hands both, so a
  benched player is the same `meeple` on the sideline as on a space);
  the page groups nobody. The benches were behind a button because a
  bench was a thing looked up; once the Coaching Choice is played by
  putting a bench meeple on the field, the bench has to be on the page
  the field is on. A Coaching Offer lights a side's sideline as a
  whole, and a substitute lights the meeples that may come on.
- **The log is words only**: each entry a block with an edge coloured
  by its kind (step 10 of the redesign) -- a new play blurple, a goal
  gold, a roll grey, the clock faint, a line the panel's line -- and
  the minute as a small heading when it changes. **The kind is the
  journal's reading of facts the model handed over, never of the
  words**: a goal is the entry the score went up in (the roll's, since
  every goal is rolled), a new play the group's `new_play`, a roll an
  entry with a roll's detail, the clock a group whose step is the
  whistle or a stage between the halves (`CLOCK_STEPS`); the minute is
  the clock the result left. All four are kept with the entry in the
  journal's file, so the log reads the same after a restart. It draws no board (2026-09-26, the author): the
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

**The question box** (2026-09-26, step 3 of
[../web-app-redesign.md](../web-app-redesign.md)) is the panel under the
field, in the canvas's shape: a state tag, the outcome, the ask at
17px, a muted line for what is lit on the board, the controls, and on
the right the picture the question is asked over.

- **The tag is the server's reading, never the page's.** Four:
  YOUR MOVE (gold, and the box's left edge gold), WAITING ON <NAME>
  (grey), NOW (blurple) and FULL TIME (green). **WAITING names who**
  (the author, 2026-09-27: an observer read "the other side" as
  Dinky's turn when it was a person's): the prompt's `waiting_on` is
  `present.waiting_on`, the coach of each side `asked_sides` names
  that this viewer does not coach, as `coach_name` calls them -- the
  AI by its name -- joined with "and". It never reads a pick: on the
  maneuver pick an observer is told both names until the question
  resolves, since whether the other card is down is that side's
  secret (the survey test holds the key list). With nobody to name --
  a test game's one coach -- the tag says "the other side". The prompt's
  `state` is `_box_state` in `webapp/server.py`: `full_time` for
  `GAME_OVER`, `now` where `asked_sides` is empty -- a note or a roll
  either coach may take, which is the reading "nothing rolls dice on
  its own" gives -- and otherwise `yours` where `controls_for` offered
  this viewer the controls and `waiting` where it did not, an observer
  included. The page used to work it out from `yours` and `is_coach`,
  which called a roll "your move" and an observer's view of a turn
  "now"; `QuestionBoxTests` hold every prompt fixture to the reading.
  `yours` stays beside it, for the tab title and the notification,
  which are about whether *this* coach has something to press -- a
  roll is NOW and still theirs to press.
- **The outcome comes first and stays until the next thing happens**:
  the dice at 180px ("The dice", below) beside the headline. The
  headline and the line under it are the model's narration, not the
  page's wording; where they come from is in "The outcome banner",
  below.
- **The lit line says what is lit, and what is dark.** A line per
  object lit outside the box -- a meeple, a space, the ball, a goal,
  the tile -- with what clicking it means and its cost, and muted, a
  railed one with the tutorial's note. It is `present.lit_line`, read
  off the controls this viewer was just handed, so it cannot name a
  thing that is not lit and an observer gets none. The turn is the one
  prompt that also says what is *not* offered, since its three objects
  are always on the page and a coach looks for the dark one: no shot
  from where the ball stands (a shot out of range is not offered at
  all, `TurnOptions`, and the range bar under the field shows why),
  or no time out to call. The box's own objects are not repeated.
- **The picture slot is on the right**, behind a rule: the shot or the
  challenge, `PROMPT_PICTURES` as before ("The prompt's pictures").
  On a narrow screen it goes under the question.
- **A refusal rides on the question it refused**: a red-edged strip
  under the tag with the model's sentence and an outlined Dismiss. The
  page moves the one strip into whichever box is asking -- the question
  box, or the table before kickoff -- and above the box where neither
  is up (a dropped connection with nothing asked). **Under the sentence,
  its Law** where the model names one -- "See Law 14.5 · How many
  substitutions", opening the Rules tab there ("The rules and the
  player aids", below).
- **The owed step is a strip of its own above the box**, not a
  question in it: a restart caught the game mid-turn and nobody is
  asked anything, so there is no tag to give it. Its control is the
  whistle.

**The answer is the thing on the board; there are no coloured
buttons** (2026-09-26, step 4 of
[../web-app-redesign.md](../web-app-redesign.md)). A control names the
object it lights as its `place` -- `{"at": "player", "id"}`, `{"at":
"space", "zone", "space_index"}`, `ball`, `{"at": "goal", "side"}` (the
goal that side defends), `{"at": "out_of_play", "side"}`, `{"at":
"time_out_tile", "side"}`, `{"at": "bench", "side"}`, and in the
question box `die`, `{"at": "face", "value"}`, `whistle`, `note`,
`rematch`, `{"at": "card", "key", "side"}`, `{"at": "formation",
"name"}` -- with `also`, any further
object the same answer lights (a Set Up's shot is the goal and the
shooter, and clicking either sends it), a `chip` saying what clicking
it means and a `cost`
drawn as the token image and a count (a Cyborg's drain under its own,
`drain_wording`). The page lights that object gold and attaches the
click; what it sends is still the control's `action`, checked against
what was offered like any other, so **a place says where on the page
and never what is answered**.
`test_every_control_is_an_answer_the_driver_takes` presses every
control of every fixture as the page sends it -- a chooser opened from
the board with each of its answers -- through `_was_offered` and the
service; every control sent the same `Action` as the coloured button
it replaced (compared over all 230 controls of the 50 asked fixtures
when it landed). `ObjectTests` hold that every control names an object
the board draws or is the neutral style, and that none carries a
colour.

**Where nothing on the board can be the answer, it is the one neutral
control**: outlined in `#3f4147`, text `#dbdee1`, no fill -- `.btn`,
everywhere on the page, the table and the front door included, with a
setting's value as it stands edged in gold. The page's one colour for
"this is yours to press" is the gold the object is lit in, so a
coloured button would be a second signal. A button's colour was the
frontend's (principle 8) and so is its absence: nothing in the model
changed for it.

| Kind (option shape) | What lights, and its chip | The rest |
| --- | --- | --- |
| `ball_handler_selection`, `run_back_player`, `ball_recovery`, `halftime_extra_token`, `shooter_choice`, `shootout_pick` (`PlayerOptions`, `ShootoutOptions`) | each candidate's meeple -- "handles", "runs back", "picks it up · 2 spaces away", "clears one more", "shoots" | -- |
| `maneuver_challenge`, `loose_ball_pick` (`SendOptions`) | each candidate's meeple with its walk-in, a token a space ("on the ball" for a defender already there) | sending nobody is the ball itself -- "let it through" / "send nobody" -- only when `may_decline` |
| `player_action` (`TurnOptions`) | the ball for the maneuver, the goal the side attacks for the shot, the side's time-out tile -- each only where offered, dark where railed | the lit line says why the others are dark |
| `run_back_space` (`SpaceOptions`), `fly` (`FlyOptions`) | each space, with its price | Fly's Stay is neutral |
| `high_pass_choice`, `setup_pass_choice`, `setup_pass_push_back`, `dribble_advance_choice`, `dribble_burst_choice` (`DistanceOptions`) | the space each distance lands on (`landings`), with who stands there to take a pass, a burst's cost, or how far; Quantor's run a second chip on the same space | a pass with nowhere to go is the ✕ past the far end, clicked or with the ball dragged onto it |
| `low_pass_choice` (`LowPassOptions`) | each receiver's meeple -- or, where teammates share the landing space, the space, which asks "who receives it?" in the box | -- |
| `speed_delta_choice` (`SpeedOptions`) | a row of d12 faces in the box | -- |
| the six rolls (`RollOptions`) | the large die in the box; a ⚡ chip on each meeple that may declare Overdrive (with its drain) or Boost first | a score attempt's Back is neutral |
| `mind_pull`, `smooth`, `join_the_ball`, `force_test` | the meeple the prompt names, for the yes | the no is neutral, worded from the option ("Stay", "Let it stand", "X keeps the ball") |
| `set_up_attempt` | the goal and the player who may take the shot (the prompt's `player_id`), both for the shot (the author, 2026-09-26) | the decline is neutral |
| `coaching_offer` | the sideline of the side it is put to, for Coach (the author, 2026-09-26) -- its meeples still show their cards | Pass is neutral |
| `maneuver_action` (`ManeuverOptions`) | the printed cards of this coach's own hand, 150px, the gambits a row under the basic three | a gambit the side does not hold is dimmed and never offered; the other hand is a back ("The hand, the reveal and full time", below) |
| `coaching_hub` | the formation tiles in the box; a bench meeple, then the player it replaces; a player, then the teammate they change zones with or the space they move to; the whistle for Done, grey with `finish_refusal` under it ("The Coaching Choice on the board", below) | a move onto a space two teammates share asks which comes back, in the box |
| `shootout_order` | -- | neutral until step 7 |
| `tutorial_continue` | the note: anywhere on it | -- |
| `game_over` | the REMATCH mark, which posts to the room's own route | -- |

**A pickup's price is the prompt's.** The run back, the walk-in and Fly
charge a token a space, so their chips carry the token and the count.
The ball's recovery chip carries how far each candidate is and what the
pickup would charge them, off `PlayerOptions.costs` -- every pickup
charges a token a space, a time out's included, since the author's
2026-09-26 change (the time-out pickup was free until then, which is
why the price is carried rather than read off the distance).

**The whistle is one control for everything that ends a phase**: Done
on the hub, Start the game on the table, and Pick it up on the owed
strip (Lock the order joins it with step 7). A pea-whistle, gold on a
dark disc when the position allows it and grey when it does not, with
the reason under it: the hub's `finish_refusal`, or on the table the
record's own `start_lobby` refusal, asked of a copy of the record
(`server._start_refusal`), so the sentence the whistle is grey over is
the one pressing it would have been refused with.

**A distance names its landing because the model says so.** A
distance prompt carried only the distances, and each Discord view
worked out where its label's space was -- the ball's space moved
forward for a pass, back for the push back, the handler's for a
dribble. Which way a kind moves is a rule, and a page that lit a space
would have been a third copy of it, so `DistanceOptions.landings`
carries the space, off the measures the moves themselves take
(`ball_destination`, `relative_move_destination`), and the two Discord
views that measured it read it now (proposed as its own commit on step
4's PR, and accepted by the author there, 2026-09-26). A space in the
layout carries its `index` so a control can name it.

**The keyboard reads the same list.** Under the box, out of sight
until it has the focus, are the controls in the order the options
give: a number key presses that one, Enter the only one there is, and
Esc puts back a thing picked up on the board, backs out of an open
chooser, or puts a refusal away.

**The hand, the reveal and full time** (2026-09-26, step 5 of
[../web-app-redesign.md](../web-app-redesign.md), with step 12 folded in).

- **The hand is the printed cards**, `pictures.maneuver_card_png` at
  150px in the question box, each the answer as it was in step 4; hovered,
  a card lifts and its full-size face opens beside it. The cards offered
  are exactly the side's `maneuver_keys`. The basic three are a row and
  the gambits a row under them -- a card's tier is printed on it, so
  `card.gambit` is read off the catalog to lay it out and decides
  nothing.
- **A gambit the side does not hold is shown dimmed**, with "held only
  by the side behind", as a dead control the page cannot send (and the
  offer check refuses if it is sent anyway). Which gambits those are is
  a reading of the rules, so it is the model's:
  `ManeuverHand.withheld`, over `RulesEngine.withheld_gambits`, proposed
  as its own commit on step 5's PR and accepted by the author there
  (2026-09-26). Empty wherever being behind would
  not change the hand -- a game without the gambits, an unchallenged
  maneuver, a side that holds them -- so a standard game draws three cards
  and nothing else.
- **A side that has picked keeps its hand** (the author, 2026-09-26, on
  step 5's PR): it may change its card until the other side has picked
  too. That was already the rule the driver took
  (`maneuver_pick_refusal`) and the Discord row offered; what changed is
  `asked_sides`, which no longer narrows the pick to the sides still to
  choose (a model commit on the same PR) -- the prompt stands only
  while one side is still to pick, so every hand on it is asked. The
  card laid down is ringed in gold and dead, since the same card twice
  is refused, and the rest read "play this instead"; which card that is
  is the position (`offense_maneuver` / `defense_maneuver`), read for
  the viewer's own side only. **The box then says it is waiting on the
  other side** and the tab carries no mark: `present.still_to_answer`
  reads the hands' own `picked`, so a coach who may still change their
  card is not told it is their move.
- **The other hand is a back, `present.hand_table`**: every hand this
  viewer does not hold, as the cards' shared back
  (`pictures.maneuver_back_png`, at `maneuver_reference_tier`, served by
  `GET /api/game/{id}/maneuver-back.png`), with "turned over together".
  **The page draws only that line** (2026-09-27): the backs are still
  in the state but not put in the question box. **A back is drawn whether or not that side has picked**:
  on Discord whether the other coach has chosen is not said either, so
  a back that came up with the pick would publish it; the secret test
  holds the table the same before the other side picks and after. An
  observer is handed two backs and no face.
- **The reveal** (`present.reveal`, the state's `reveal`): once both
  cards are in and until the maneuver is over (`reset_maneuver`), both
  face up in the question box -- public once turned over, for a coach
  and an observer alike -- with what the cards said between them,
  `RulesEngine.cards_outcome`: TIE, or BEATS pointing at the card beaten,
  its winner ringed. What the maneuver came to -- an injury's forfeit,
  a forced test, the roll -- is the outcome banner's, the model's own
  headline, and the die under it is step 4's. An unchallenged card is
  shown alone. The challenge picture stays where step 8 of
  [../web-app-next.md](../web-app-next.md) put it, beside the hand.
- **Full time** is the outcome banner with the model's result
  (`full_time_headline`: the winner, the final score and the
  shootout's, and who scored the winner), and beside it each side's numbers
  (`present.full_time`, the state's `full_time`): goals, shots,
  maneuvers won, skill tests won of those taken, exhaustion taken and
  time outs, read by `stats.collect_sides` over the match's events --
  the bot's statistics split by side
  ([clock-and-records.md](clock-and-records.md)) -- in each team's
  colour. Under them, "Back to the rooms" and **the whole log as text**,
  `GET /api/room/{id}/log.txt`: every entry the journal holds, its lines
  with each token as the words a copy of the page reads
  (`present.plain_text`, the alt text `render_text` gives each
  picture), and the time it was said -- the model's narration as it was
  shown, bounded as the journal is (`JOURNAL_LENGTH`). The REMATCH mark
  posts `/rematch` and, once the rematch is made, is a link to the
  room the service made. The jumbotron's note already read "Final ·
  <score>, shootout <score>" (step 2). The bot's own tables
  (`stats.game_tables`) are still under the box, as every table of the
  game.
- **Who scored the winner is the model's line** (the author,
  2026-09-26: "the model should say it"): `formatting.winning_goal_line`
  under the final score, in the full-time summary and in its
  `Headline` alike, so the banner's line under the result names the
  scorer in the model's words ([clock-and-records.md](clock-and-records.md),
  "The goal log").

**A lit meeple that is drawn nowhere is answered from the box**, as
a neutral control with its card on hover. Since step 6 a benched
player is drawn on the sideline, so it is lit there like a meeple on a
space; the box's fallback is for a page with no board to draw on.

**The Coaching Choice on the board** (2026-09-26, step 6 of
[../web-app-redesign.md](../web-app-redesign.md)). Discord walks a
coach through four menus because a message holds twenty-five buttons;
the page plays the window on the pieces themselves, as the canvas's
"Coaching Choice (setup), on the board" does.

- **A move is two things, and still one control.** A substitute is a
  bench meeple put on the player it replaces, a zone change one player
  put on a teammate in another zone, a move within a zone a player put
  on a space. `present.py` builds **one control per pair the options
  allow** -- every `incoming_ids` by every `outgoing_ids`, every
  `swaps` partner, every `repositions` space -- each with `first`, the
  thing picked up, and `place`, the thing it is put on. The page lights
  every `first`; once one is picked up it lights the `place` of each
  control that starts from it, and clicking that sends the control's
  `action`. **None of them carries a `first_chip`** (the author,
  2026-09-26): a chip per way a player could go ("change zones",
  "move") made one meeple two things to pick up, and gold pills under
  every player on the field; without them one click picks the meeple
  up and lights the teammates it may trade zones with and the spaces
  in its own zone together. What may be done with it is said instead
  as it is picked up, in a toast at the foot of the window rather than
  over the field, where it would hide the next click ("Click another
  meeple to trade zones, or a lit space to move within the zone") --
  `pickHint` in `app.js`, read off the same controls.
  So the pair is the page's way of *choosing* a control, never a move
  of its own: what is sent is an `Action` a button was built with,
  checked by `_was_offered` exactly as before, and the page cannot put
  together a pair the options did not list. The alternative -- a
  generic "pick two players" the server checked afterwards -- would
  have been the page proposing moves and the server refusing them,
  which is the page having rules and being told off for it.
- **Dragging is the same answer.** A drag from a thing that may be
  picked up picks it up as it starts, so what it may land on lights,
  and a drop on one of those presses that control; a drop anywhere
  else leaves it picked up, to be clicked. Every drag has its click
  (the two in turn), and the keyboard list under the box has every
  pair as its own entry. What is picked up is the page's state, like
  an open chooser: Esc or clicking it again puts it back, a new
  question puts it back, and nothing is sent until the second thing.
- **The formations are tiles in the box**: each shape as dots per zone
  in the side's colour, left to right as the field is -- the counts
  are `RulesEngine.formation_shape`'s, handed on the control as
  `shape`, never read off the name -- and the one the side stands in
  marked "now" and dead, as the Discord menu greys it.
- **The lit line names none of what may be picked up** (the author,
  2026-09-26): the board lights it and the how-lines say what to do
  with it, so a list of names only repeated the board. It says **the
  window's allowance**, `CoachingHubOptions.allowance`: what
  the window has left in `substitution_allowance_label`'s words ("No
  substitution limit", "2 substitutions left"), dark once it is spent.
  The prompt carried only whether a substitute was possible and the
  Discord caption said the rest, so the options grew the field
  (proposed as its own commit on step 6's PR, and accepted by the
  author there, 2026-09-26); the page says the
  occasion's budget and never works one out.
- **The box reads top to bottom as a coach works through it**: the
  ask, a line per move made on the board ("Substitute: drag a bench
  meeple onto the player it replaces, or click the two in turn"), the
  section's `how` -- this frontend's words about its own controls, not
  the model's about the game -- then the formation tiles, a rule, the
  whistle, and under it the lit line (the allowance) and last the
  Spreadable reminder (the author, 2026-09-26). The reminder is the model's sentence
  (`RulesEngine.spreadable_note`, appended to the window's ask by
  `prompts._window`); `present.split_footnote` only takes it off the
  end of the ask so the page can say it under the whistle, as the
  prompt's `footnote`.
- **A Coaching Choice opening brings up the Teams tab**, once, as the
  offer or the window appears -- the rosters are what a coach decides
  from -- and a meeple shows **no hover card** while it is open: a
  card over the meeple being picked up and dropped confused more than
  it told (the author, 2026-09-26). The Teams tab's rows keep theirs.
- **There is no undo.** The service offers none: every move in the
  window is applied when it is made, as on Discord, and undoing one is
  making the opposite move, which the board offers like any other. A
  client-side undo would be a move the page made up.

**The shootout order in the box** (2026-09-26, step 7 of
[../web-app-redesign.md](../web-app-redesign.md)). Discord asks for the
secret order on an ephemeral menu, one click a name; the page asks for
it as the canvas's Shootout artboard does -- a numbered slot per
shooter, the players still to place beside them, Start again, and the
whistle to lock it.

- **The draft is the page's and nothing of it is posted until the
  whistle.** A meeple goes into the next empty slot on a click (or its
  number key), into a chosen slot on a drag, swaps on a drag between
  slots, and comes back out on a click or a drag back to the pool; Esc
  empties the draft. The whistle is dark until every slot is filled
  and then **sends each name in slot order as the `send` it was
  offered** -- the same `Action` `ShootoutOrderSelectView.pick` sends a
  click at a time, each checked by `_was_offered` against the controls
  the page is offered *then*, and each still refused by the driver on
  its own reading. There is no "set the whole order" answer: the model
  has none, and a page that grew one would be proposing an action. A
  refusal stops the run where it is, and the page shows the order as
  the game then holds it.
- **The slots are the order already sent, and as many empty ones as
  the options still list.** `section["order"]["placed"]` is
  `MatchState.shootout_order` read for the viewer's own seat only --
  the position, as the maneuver pick's laid-down card is (above), and
  what `restore_shootout_menus` puts back on a Discord menu through
  `shootout_order_text` -- so an order a lock left half sent (a
  dropped connection) comes back in the first slots and Start again
  (the `restart` control) takes it back. The count is those two added,
  never a six in the page. Who may still be placed is the options'
  `send` controls and nothing else.
- **The other side sees whether it is set, and nothing else**
  (`present.shootout_sides`, the prompt's `shootout`): a tag per side,
  "<team> has set its order" once its row in the options is empty and
  "is setting its order" until then -- the same for both coaches and
  every observer, and never a count of how far a coach has got. That
  is public where the maneuver pick's is not, because the model says
  it in public: "Orange (Home) has set their shooting order." is the
  line everybody's channel reads. Sudden death's pick has the same
  tags ("has chosen its shooter"); its answer is a lit meeple on the
  field, as since step 4.
- **The log keeps no coach's own block.** An answer to the order or
  the pick opens with a block for the coach alone -- the order as it
  stands, "You send out ..." -- which the cog puts on the coach's
  ephemeral menu and never posts (`D12Ball.post_ai_answer` says so of
  the AI's too). The journal kept the whole answer until this step, so
  every page in the room read a coach's order as it was built: a
  secret published by the log. `present.own_block_dropped` is the one
  cut, over `OWN_FIRST_BLOCK`; the journal applies it to the answer of
  a click on this page, whose kind `WebApp.act` names for the length
  of the call (`_answering`, set and cleared under the game's lock --
  the listener hears the result and not the action), and to every AI
  answer by its group's `action`. A group left with nothing to say is
  not kept.

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
  and Esc or a click elsewhere puts it away. The benches are the
  sideline under the field (step 6, above).
- **A lit piece or goal**: a gold outline, a gold name and a chip
  saying what clicking means, with any cost as the token image and a
  count; a goal's gold ring; a space dashed in gold with its chip at
  its foot; the ball ringed in gold. What lights them is the prompt's
  (above, "The answer is the thing on the board"); clicking a piece
  that is not lit still opens its card.

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
question box), at the top, above whatever is asked next -- since step 3
of the redesign in the outcome block, 180px high beside the headline --
on Discord
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

### The outcome banner

**The canvas puts an outcome large and first** -- HIGH PASS WINS,
SAVED, STEAL · TURNOVER, HALFTIME · 1 : 1 -- in the winner's colour,
the arithmetic under it and the dice beside it, and the redesign's rule
is that the headline and the arithmetic are the model's narration and
never the page's wording.

**The narration does not split into a headline and a detail**, which
is what step 3 found. The model does write headlines -- `## **Deflect**
wins!`, `# GOAL!`, `# Missed attempt!`, `# Turnover!` -- but as a
markdown line somewhere inside a block, not as the first line of a
group: a reveal is "X chose ... / Y chose ... / ## **X** wins!", and
the lines the loop carries are joined on a space, so under the
default batching a turnover's heading lands mid-line ("... (Midfield).
# Turnover!"). A page that went looking for the heading would be
reading the model's wording for a fact, and several headings share a
group (a turnover and "Players run back!"). Nothing says whose win it
is either, so the page has no winner's colour to draw. And the
arithmetic the canvas shows under a skill test is not a line the
model says at all: the numbers are in the roll's `detail`.

**So the model says its headline once more, on its own**
(`d12ball.flow.result.Headline`: proposed in its own commit on step 3's
PR, and accepted by the author there, 2026-09-26: "sounds fine"). A
step that announces an outcome hands back, beside its lines, the
heading it wrote without its marks (`**Pressure** wins!`) -- or, where
it announces the outcome in a sentence rather than under a heading
(who won a loose ball), that sentence -- the line under it where there
is one, and whose outcome it is (the side whose card won, that scored,
that kept the ball out, that took it). The step builds the words once
and uses them in both, so the two cannot differ, and **no line
changes** -- which is why the goldens do not move.

**Every outcome a run says is kept, in order.** `StepResult.headlines`
is a tuple, a step saying one at most; the driver carries them wherever
it carries the lines, adding each step's to those carried into it, so a
Steal won on the cards arrives as "Steal wins!" and then "Turnover!".
`Narration.headlines` and `GameResult.headlines` / `answer_headlines`
put them on the wire, the answer's going with the lines the frontend
keeps. The first cut kept only the first said; the author asked for
both, as the canvas's "STEAL · TURNOVER" has them.

**Where they are set**: the maneuver settled on the cards (and "lets it
stand", and the uncontested "succeeds"), the skill test's verdict, the
shot's GOAL! or Missed attempt!, a steal's Turnover!, and -- at the
author's word on the same PR ("these should be headlines", then "these
should all get a headline and arithmetic") -- Halftime, the result at
full time or after the shootout (`full_time_heading`, the heading
`build_full_time_summary` writes, with the final score under it), the
loose ball or the long pass's contest (Turnover! where the ball changed
hands, and who won it, with who has possession under it), the own-goal
roll (Own goal avoided! or Own goal!) and each shootout test (who
scores, or the tie, with the running shootout score under it). Each
heading is one constant or one variable, used in the line and the
headline alike (`TURNOVER_HEADING`, `HALFTIME_HEADING`,
`OWN_GOAL_AVOIDED` / `OWN_GOAL`).

**Every roll's arithmetic is written out, not only shown** (the author:
"the arithmetic needs explanation, it's not enough to just show the
math ... the model should write this with greater detail").
`Headline.working`, set by the skill test, the loose ball, the shot,
the own-goal roll and the shootout test, is each side as who rolled,
the face, every addend and the total, then how the two totals are read
("**16** beats **10**."; "**13** is lower than **15**: the attack does
not score."; "**13** is 7 or more: safe."). `rolls.roll_working` and
`contest_working` build it from the same detail lines the dice picture
is drawn with, so the words and the picture cannot disagree; the
own-goal roll's is its own breakdown line, which the narration already
said. It is on the headline and not in the narration: the bot posts the
dice picture that already says it, so no line moves and neither does a
golden. The shot's defenders are listed without the picture's running
total, which written out would read as one more addend.

**On the page** the journal keeps every headline of the latest result
as `showing_outcomes` (in its file, as `showing_roll` is), up until a
result comes with none. The state's `outcome` is their words through
`render_text`, one after the other with a dot between them as the
canvas joins them -- joining is presentation, the words are the
model's -- in the colour of the first that is a side's, with the first
line under one and the first working. The page sets them in the
outcome block -- the headline 46px in the display face, the line under
it 17px, the working under that at 15px -- beside the dice at 180px,
large enough to read the picture's own breakdown (the author: "make the
die larger"; the canvas's 84px dice were bare dice, where this is the
bot's picture with its words on it). The canvas's "HALFTIME · 1 : 1" is
the model's "Halftime": the score is the jumbotron's.
`OutcomeBannerTests` hold every headline to words the narration itself
says, word for word, and the working to the faces rolled, for a
resolved maneuver, a saved shot, a steal (both of its headlines), a
skill test, a loose ball, an own goal and a shootout test.

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
game is over -- beside each side's numbers at full time (step 5 of
[../web-app-redesign.md](../web-app-redesign.md), "The hand, the
reveal and full time", above). `GET /api/stats?kind=` is every web game's numbers cut
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

Step 11 of [../web-app-next.md](../web-app-next.md), redrawn by step 10
of [../web-app-redesign.md](../web-app-redesign.md) (2026-09-27):
everything a Discord coach can pull up beside a game without it being
a turn -- `rules_full`, `rules_search`, `maneuver_reference`,
`role_abilities_reference`, `species_abilities_reference`,
`team_reference` -- and the two rulebooks, which Discord has only in
print. `webapp/aids.py` holds all of it and `webapp/static/aids.js`
draws it twice: as the **Rules tab** in a room's sidebar, and as the
**Reading Room** at `/rules`, linked from the front door and from the
tab. Every route is a read-only GET open to anybody -- an observer, or
nobody with a cookie -- takes no lock and touches the service no
further than reading the game; nothing in it goes in the log.

**The rules are `rules_doc`'s, with the Charter's numbers the file
carries, grouped by its Laws.** Since 2026-09-26 `docs/living-rules.md`
carries the printed edition's numbers, written by
`scripts/build_rulebooks.py --renumber` ([rulebooks.md](rulebooks.md)),
and the Learn to Play cites them as *(Law 6.4)*. So every section is a
`RulesSection` of `rules_doc.load_rules_document` -- the same parse
`/d12ball rules_search` answers from, and `GET /api/rules?q=` is its
`RulesDocument.search` -- headed with `RulesSection.number`, the number
`rules_doc` split off the heading, and each paragraph opening with its
own as the file writes it. A section is named on the page by its
numberless `slug`, which a renumbering does not move -- the same slug
`RuleRefusal.law` cites -- and the file's links, which point at
GitHub's anchor for the numbered heading, are mapped back to it by
`page_anchors`. A link to a heading reads `text (6.4)`, the number
being the file's words after the link. `charter_numbers` is
`rulebooks.number_blocks` over the file with its numbers taken out
(`rulebooks.unnumber`), the text the book is built from, keyed by that
same slug; it is what names an Appendix by its letter and what turns a
*(Law 6.4)* in the Learn to Play into a link. `tests/test_web_aids.py`
holds that every heading the Charter numbers is a section with that
number. **What is a Law is what the build numbers as one**:
`aids.charter` (`GET /api/rules/charter`) groups the sections under the
level-2 headings the Charter numbers -- the 21 Laws, each with the Part
it is in, its own text and its sections, a heading below a section set
in that section's text as the book sets it -- then the Appendices,
which the Charter letters, and the front matter before the first Part.
Each section's text is read by `rulebooks.parse_markdown` -- the books'
own subset, which raises on a line outside it -- and set as HTML after
escaping, so the page and the printed Charter fail on the same line.
There is no second copy of the rules text: the page is re-rendered when
`rules_doc` re-parses a changed file, and a missing file is logged at
ERROR and answered 503, as `load_rules` refuses on Discord.
`CharterTests` read a heading through `rules_doc` and find it in what
the tab and the Reading Room are handed.

- **The Rules tab** is a search box, three chips -- THE CHARTER, LEARN
  TO PLAY, REFERENCES -- and the Laws by their headings, one opened to
  its text: its sections named in a row, then each under its number. A
  search is `RulesDocument.search`, except that "Law 12" or "6.4" goes
  straight to the heading the Charter numbers so; a link inside the
  rules opens its heading in the tab rather than leaving the room.
- **The Reading Room** is the canvas's: the Laws down the left, the Law
  text in the middle, the References on the right, with a search over
  everything and chips for the Learn to Play and the rosters. The
  Charter and the References are set on the server, so the page reads
  without a script; the Law being read is lit in the contents as it
  scrolls.
- **The Learn to Play is read in the page.** `aids.learn_to_play`
  (`GET /api/rules/learn`) reads `docs/learn-to-play.md` with the
  books' own parser, its figures served from
  `docs/rulebooks/figures/` like the Charter's, and turns every number
  in a *(Law 6.4)* into a link to the heading the build gives that
  number -- so the book's citations open the Charter, in the tab or the
  Reading Room, and a number the Charter does not give stays words.
- **No PDF anywhere** (the author, reviewing the redesign, 2026-09-26,
  and on the step's PR: the Learn to Play shown in the page rather than
  as a PDF is what was wanted).
  Step 11 of the earlier worksheet served both books as PDFs, set in
  memory, on the reasoning that an HTML Learn to Play would be a second
  layout of the book; the redesign settled the other way, because a
  coach mid-turn reads the rules in the page and never in a download.
  `/books/*.pdf` is gone, and nothing the pages link is a PDF
  (`NoPdfTests`). What keeps it from being a second layout is that it
  has none of its own: it is the book's markdown in the page's type,
  with the book's figures, and the printed layout stays
  `rulebooks.py`'s alone (`scripts/build_rulebooks.py` is unchanged).
- **The References are the model's own data.** The cards are the
  printed faces the hand shows (`pictures.maneuver_card_png`, served at
  `/aids/cards/{key}.png`): the six basic ones always, and the six
  gambits under them where the game's hexagon is the gambit one -- an
  advanced game that plays them (the author, 2026-09-27), which is
  `maneuver_reference_tier`'s answer, never `game.mode` read here. The
  roles table is `role_profiles` -- the role card's own numbers, its
  badge, and `short_ability`, the sheet's short column, never cut down
  here -- and the species table is `species.json`, the species card's
  data, each species team in its colour with its icon. In a room the
  species table is there only where `species_abilities_apply`.
- **A refusal cites its Law.** Which Law says no is a reading of the
  rules, so it is the model's: `RuleRefusal.law`, the slug of the
  living-rules heading, set at the raise site (proposed on this step's
  PR as a model change of its own, and accepted by the author there,
  2026-09-27; see
  [model-discord-split.md](model-discord-split.md)). The server turns
  it into `refusal_law` -- the heading, its Charter number and title,
  and the Law it is under (`aids.citation`) -- beside the sentence, on
  an action's answer and on the table's; the strip shows "See Law 14.5
  · How many substitutions", and clicking it opens the Rules tab at
  that heading. A refusal that cites nothing shows no link: **the page
  maps no sentence to a Law.**

**Which aids a room gets is the model's.** The room's state carries
`aids`: the cards at the game's tier and the hexagon at
`RulesEngine.maneuver_reference_tier(game)`, the species table and card
only where `species_abilities_apply(game)`, the team cards in the face
`personal_abilities_apply(game)` says the game holds, and the three
answers themselves, so `app.js` decides none of them and never reads
`game.mode`. The team cards come the seat's own team first (an
observer's seat 1's); a room no longer draws them as a gallery, since
the Teams tab is the rosters and a row's hover card is the card in the
face the game plays. In the Reading Room, with no game to ask, `GET
/api/aids` offers all of it: all twelve cards, both hexagons named by
tier, the species table, every team with both faces (the ROSTERS
chip). Every picture is the one the reference command posts, drawn by
the same function (`render_maneuver_reference_image`,
`render_role_reference`, `player_cards`), in a worker thread and kept
with the cards; the References draw the role and species *tables*
from the data those cards are drawn from, as the canvas has it, and
the role card and the two `species_cards.REFERENCE_FACES` stay served
at their routes for a link.
The maneuver pick carries `reference`, the cards' shared back at the
game's tier (`GET /api/game/{id}/maneuver-back.png`), which carries the
defeat cycle: the page writes "Maneuver rank reference" under the hand
and shows the back as the hover card while the pointer is on the words,
or after a press and hold -- never a picture inline, since the question
box already carries the challenge over the hand (step 8). **The fuller
reference, the hexagon, is the References'** (the author, 2026-09-27),
under the cards: `aids.maneuvers`, the one at the game's tier in a room
and both, named, in the Reading Room. The pick used to link to the
hexagon; that link is gone.

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
  ignition die, with its caption (`D12Ball.dice_file_with_ignitions`,
  one per side that ignited, drawn beside the roll's own dice), and the
  scorer's portrait under a goal.
  Both ride on the same `detail` the page already keeps -- the
  ignites on a contest's, the scorer on a shot's -- so if they come to
  the page they go **in the question box beside the dice they came
  with**, and down with them; never in the log (2026-09-26, the
  author: no picture in the log).

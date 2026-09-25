# The web frontend

The fourth part of [ARCHITECTURE.md](../../ARCHITECTURE.md): `webapp/`,
a browser frontend over the same `GameService` the Discord cog plays
through. This note is the reasoning behind its shape; the map in
CLAUDE.md says where the pieces are. The worksheet it was built from is
[../web-app.md](../web-app.md), which is the review the split was held
to and the decisions taken in it; what outlives that review is here.

**The whole of what it is:** authenticate the person, turn what they
pressed into an `Action`, call `apply_action`, render the `GameResult`.
It is the same four lines the cog is, with `discord.Interaction`
swapped for an HTTP request -- and it is the measure of whether the
model/Discord split worked, because everything it needed the bot
already had.

## Running it

Four environment variables, all of the frontend's:

| Variable | What it does |
| --- | --- |
| `FOOLBOT_WEB_PORT` | **The switch.** With none set no server is started, nothing is built (not even the service), and the bot is exactly what it was. |
| `FOOLBOT_WEB_HOST` | What to bind, `0.0.0.0` by default. |
| `FOOLBOT_WEB_URL` | What a link points at, `http://localhost:8080` by default -- the address a coach's browser can reach, which the server cannot know about itself behind a tunnel or a proxy. |
| `FOOLBOT_WEB_SECRET` | What the coaches' keys are derived under. With none set one is made per process, and every link dies with it. |

A failure to bind is an ERROR, so it reaches #logs: the port is
somebody's to free, and the bot carries on playing on Discord either
way.

## What it may not do

`webapp/` imports neither `discord` nor `cogs`, and
`tests/test_web_purity.py` ratchets it -- an AST walk, so a lazy
import inside a function (which is exactly where one would arrive)
fails too. A web app that reaches into the Discord frontend is not a
second frontend over the model, it is a second frontend over the
first, and the first rule it borrowed is the end of the exercise
(CLAUDE.md, principle 10).

The rule with teeth is the positive one: **every control comes off
`PendingPrompt.options` and nothing else.** `webapp/present.py` has
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
carries nothing, so **the link is the credential**: `webapp/keys.py`
derives one key per coach per game as an HMAC of the game id and the
player number under `FOOLBOT_WEB_SECRET`, and `/d12ball web_link`
hands a coach their own, ephemerally. Derived rather than stored,
because a web session is not a fact about the game and the save
format is a contract (principle 6); with no secret set, one is made
per process and every link dies with it, which is the safe default
for a checkout whose `.env` nobody has edited.

A key names a coach and is not permission to do anything. What a
coach may *answer* is `d12ball.prompts.asked_sides`, the same reading
the service answers an AI side by -- so the web app's gate and the
bot's are one reading of whose question it is. A prompt nobody in
particular is asked (every roll, the tutorial's Continue) is either
coach's, which is what "nothing rolls dice on its own" looks like
from this side. A viewer with no key sees the board, the score and
what has been said, and answers nothing.

**A page may only send back a control it was offered**, checked in
`webapp/server.py` before the model sees it. That is the web
equivalent of a button Discord never drew, not a second reading of
the rules: what may be chosen is still the prompt's and the position
is still the driver's, which refuses again on its own reading. What
it buys is that no hand-made request reaches an adapter with an
argument no prompt ever offered -- which is the case finding 4 of the
worksheet left open, since a bad wire value is a bug rather than a
refusal.

## One process, one service, a lock per game

`gamesaves/d12ball/storage.py` rewrites the whole save file on every
call and reads it once at startup, so a second process would
overwrite the first's file with a stale copy of every game (finding 13
of the worksheet). One process over one `games` dict is what makes two
frontends possible at all; a shared store with a row per game is the
day the web app has to outlive a bot restart, and not before. The cog
starts the server in `cog_load` when `FOOLBOT_WEB_PORT` is set,
handing it its own service and locks, and stops it in `cog_unload`.

**What the lock is for is ordering, not the apply.**
`GameService.apply_action` is synchronous, so on one event loop it
cannot be interleaved -- load, answer, run and save happen with
nothing else running. What interleaves is everything a frontend does
afterwards: renders, uploads, message edits, a response built from a
board it drew. Two answers applied back to back can be *presented* in
either order, which is a turn arriving in a channel out of sequence.
So `gamelocks.GameLocks` is held from taking an action to having
finished showing what came back. The Discord half takes it in
`SafeView._scheduled_task`, which overrides discord.py's own click
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
last saw -- each entry with its time and, where the run stopped to
draw a position, that position's layout too -- and the chat since the
message the page last saw. There is no websocket
and no diffing -- a game of D12 Ball is a few clicks a minute, and
the simplest thing that is always right is a re-read.

**The journal is the frontend's memory and nothing to do with the
save.** `MatchState.events` is the game's record of what happened,
and nothing in the game may read it to decide a rule; the journal is
the run of messages a page shows, in the order a coach reads them. A
restart empties it and the board and the prompt are still right,
which is the difference between a transcript and a position.

It is fed by `GameService.listeners`, which hands every result the
service produces to whoever is watching, after the save. **A game is
played from two sides and they need not be on the same frontend**: a
coach reading a page has no interaction to be replied to when the
other coach clicks a button in Discord, so the result the service
produced for that click is the page's only way to see the turn. The
listener formats nothing and is not a second presenter; a listener
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

## The page

**Two columns in Discord's colours** (2026-09-25, the author, after
seeing a page built as a Discord channel and finding it too much like
one). On the left, the board, and under it the prompt -- the ask and
its controls, marked when they are this coach's -- which is the page's
original shape. On the right, three panels: the jumbotron, the game
log and the chat.

**A phone is one screen, not a long page.** The jumbotron and the
board stay on it; under them three tabs -- Move, Log, Chat -- switch
what fills the rest, and only the tab showing scrolls. A tab that is
not showing is marked when something new arrives in it, gold on Move
when the prompt is this coach's. Stacking all five panels made a page
a coach scrolled past the board to answer and past the answer to read
what happened, which is the opposite of a table.

- **The jumbotron has its own panel.** It is the board's jumbotron --
  both teams in their colours, the score, the minute and the half,
  in the board's typefaces -- with the coach behind each team under
  it, taken off the board so the field has the room.
- **The benches open on demand.** Each team's bench and back bench
  is behind a button under the board: shown while the pointer is on
  it, kept open by a click. The board shows the field; a coach looks
  at a bench when they are thinking about a substitution, and the
  cards are the same cards either way.
- **The log is the original one**: each entry a block with an edge,
  a new play's in blurple, and a position the run stopped at drawn
  small inside its entry, opening full size.
- **The chat is people talking** (step 4 of the worksheet, in
  memory for now): anybody reading the page may post, a coach under
  their name off the record in their team's colour and anybody else
  as an observer. It rides on the poll with its own cursor
  (`chat_since`), is bounded like the journal, and goes nowhere near
  the service. A message is plain text, handed over as written and
  drawn as text -- never the model's markdown or tokens, because it
  is not the model's voice. A restart empties it, as it empties the
  journal.

**The buttons are Discord's**: four colours and one shape, and each
control carries its colour (`style`) from `webapp/present.py`, set to
what the Discord view puts on the same button -- Maneuver blurple,
Shoot to score red, Time out grey; a roll blurple and a shot's or an
own goal's red; yes blurple and no grey; Done green; the offense's
cards red and the defense's green. The colour is the frontend's
(principle 8), so it is set in the web app's builders beside the
labels, not read from the model. The Coaching Choice is a button per
menu, opened in place with a Back, because that is how the hub walks a
coach through it on Discord; the answers are the same `Action`s the
page always sent.

**The board is drawn in HTML, in the bot's layout** (the jumbotron
and the team boards moved beside it, as above) --
[board-image.md](board-image.md), "The web page's board". It is not
the PNG because the cards on it have to be cards: each is the board's
own face of that player (`render.build_player_card`), which opens as
the printed card with its whole ability on a click
(`player_cards.render_player_card`, its advanced face in a game with
the species abilities on), and previews under a pointer. A maneuver
prompt's hand is the printed maneuver cards, and pressing one plays
it. Every one of those pictures is the model's own drawing, served by
`webapp/pictures.py` in a worker thread and cached; the page draws no
card of its own. The PNG is still served, and a board opened full size
links to it, as the bot's "View full image" button does. A snapshot
entry is drawn from the layout of the position the service stopped
at, which is what `Narration.board` carries, so a page's picture of a
loose ball is the position the ball was loose in, not the position
after it was won.
The cog's own `cyborg_condition_ids` moved onto the engine to make
the board possible at all: which players draw a Cyborg's condition
marks is `has_species_ability` asked of everybody a mark would be
drawn against, which is a rule and not a rendering brief.

**What the layout may carry is what the PNG reads.** `board_layout`
reads the position the way `render_match_image` reads it and asks the
renderer's own functions for everything the PNG works out from the
rules -- the space codes, the zone labels, the range bands, whose
marks are a Cyborg's, whether a meeple carries a species icon. The
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

## What it does not do yet

- **It does not create games.** A game is opened in a channel, and a
  finished one's rematch is the cog's; the web app plays a game that
  exists. The service has the setup methods (step 8), so the page
  that does it is work rather than a question.
- **It does not draw most of the pictures a prompt rides on** -- the
  field strip, the challenge image, the coach's half-field, the dice.
  They are `D12Ball.render_prompt`'s, keyed on the kind, and the web
  page shows the ask, the controls and the live board beside them
  instead. The hand of cards is the one it draws, as the cards
  themselves. The numbers behind a roll are on the wire
  (`GameResult.detail`) for the page that draws them.
- **It keeps its journal in memory**, so a restart is a page with a
  board, a prompt and no history.

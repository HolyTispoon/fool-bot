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
the scoreboard, a board URL whose version changes when anything a
board draws has moved, the prompt with its controls, and the
narration since the entry the page last saw. There is no websocket
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

## The pictures, and the voice

The board is the bot's own picture: `render_match_image` with
`RulesEngine.cyborg_condition_ids`, in a worker thread, read-only, so
it never goes near the driver (ARCHITECTURE.md, "State-changing and
read-only operations"). A group the run stopped to draw is drawn from
the snapshot the service took at that stop, which is what
`Narration.board` carries -- so a page's picture of a loose ball is
the position the ball was loose in, not the position after it was
won. The cog's own `cyborg_condition_ids` moved onto the engine to
make that possible: which players draw a Cyborg's condition marks is
`has_species_ability` asked of everybody a mark would be drawn
against, which is a rule and not a rendering brief.

**The tokens are rendered at this frontend's door**, the way the cog
renders them at its own: a team is the ring `render.py` draws it in,
a role a badge, a coach their name off the record. `render_text`
escapes first, renders the narration's own markdown second, and the
tokens third, and the order is the whole of what makes it safe --
rendering tokens first would put markup in front of the escape, and
running the markdown after them would read an emitted attribute as
emphasis. The markdown is rendered rather than stripped because the
model's sentences are written in it (principle 5): Discord's client
draws it for the bot, and this draws it here.

## What it does not do yet

- **It does not create games.** A game is opened in a channel, and a
  finished one's rematch is the cog's; the web app plays a game that
  exists. The service has the setup methods (step 8), so the page
  that does it is work rather than a question.
- **It does not draw the pictures a prompt rides on** -- the hand of
  cards, the field strip, the challenge image, the dice. They are
  `D12Ball.render_prompt`'s, keyed on the kind, and the web page
  shows the ask and the controls instead. The numbers behind a roll
  are on the wire (`GameResult.detail`) for the page that draws them.
- **It keeps its journal in memory**, so a restart is a page with a
  board, a prompt and no history.

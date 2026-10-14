# D12 Ball in Godot

**This is a worksheet, not a specification.** It was written on
2026-10-04 from the author's ask -- build D12 Ball in Godot on the
model the game already has -- and the shape the author gave it the
same day: "the rules stay in Python, in a server or a local background
process, and the engine only draws and sends actions. Godot has HTTP
and JSON built in." This file is the plan under that decision: what a
spike measured, what the code and the engine's documentation say, the
decisions the plan is built on, the questions only the author can
answer, and fourteen steps in the order they pay off, each with a
prompt written to be handed to a Claude Code session as it is. Strike
a step when it lands and move what it settled into
`docs/design/godot.md`, the design note step 2 creates. **Nothing in
it is a rule.**

## The shape

```text
                 HTTP + JSON, one cookie
 Godot ───────────────────────────────────────►  python3 -m webapp
   draws the state it is handed                    │   (webapp/server.py)
   lights what the prompt offers                   ├─► GameService ─► driver.apply
   sends back the control that was pressed         └─► the save
        │
        ├─ offline: starts that server itself, as a background
        │  process on the player's machine, over the player's own files
        └─ online: names https://play.d12ball.com instead
```

**Godot is a second client of the web app's server, not a third
system.** The web app is already the thing the author described: a
Python process that holds the rules behind HTTP and JSON, with a page
that only draws and sends actions. The Godot game is a second such
page. It keeps the page's place in
[ARCHITECTURE.md](../../ARCHITECTURE.md) -- "a frontend only
translates user input into an action and displays the result" -- and
takes on principle 10 of CLAUDE.md whole: the moment the Godot client
has a rule of its own, this whole exercise has failed.

What Godot rebuilds is the page's `webapp/static/` -- `app.js` is
3,774 lines and `app.css` 2,943 -- and nothing above it. What it adds
is what a page cannot be: a program of its own that runs with no
network, motion, sound, and the die as a solid.

## What was tried, 2026-10-04

Before any of this was written down it was run, on the author's Mac
(an M3 Pro) with Godot 4.7.2 -- the latest stable release, 2026-08-18
-- against the web app at `3288c52d`, **unmodified**. The scratch it
was run with is in [spike/](spike/); "Running the spike again" at the
foot of this section is how.

![A position of a real game against Dinky, drawn by Godot from the web app's JSON: the field with its zones and goals, the meeples in their team colours with species icons and role letters, the two players a Low Pass may go to outlined in gold, the ball showing its speed, the ball holder's card, and a d12 as a solid.](first-picture.png)

*The first picture: a real game against Dinky five minutes in, drawn
by Godot from the server's JSON and nothing else. The spaces, the
zones, the fans, every team's colour and the meeple's outline are the
wire's;
the two meeples in gold are the two answers the prompt offered; the
card is the model's own, served; the solid is built from the
dodecahedron's twenty vertices. Laid out for one window size, with the
web app's greys. It is evidence, not a design.*

1. **Godot starts the server as a background process and plays through
   it.** A Godot script started `python3` over a pipe
   (`OS.execute_with_pipe`), read the port the server announced as one
   line of JSON, and had its first answer **under half a second**
   after starting it (unfrozen, the system's Python 3.14.7). When
   Godot closed the pipe the server left on its own: it watches its
   stdin and exits at end of file, which is also what happens when
   Godot is killed.
2. **A headless Godot played seventy answers of a real game against
   Dinky, twice, with nothing but what the wire handed it**: became
   somebody (`GET /api/me`), opened a room, seated the AI, picked a
   team, flipped the coin, and then answered whatever it was asked by
   sending back a control it had been offered. Thirteen of the
   thirty-six kinds of prompt came up across the two runs -- the
   Coaching Choice, the maneuver pick, the challenge, the turn's
   action, a Low Pass's receiver, a run back, the halftime token, a
   Mind Pull, the offer of a Coaching Choice, and four different rolls
   -- through halftime, one run to 0-2 at minute 25. **Every answer
   was accepted and none was refused.** 151 requests, a median of
   34 ms each and the slowest 41 -- which is the frame loop of the
   client that polled them, not the server.
3. **The whole of what a non-browser client has to do for itself is
   resend one cookie.** Godot keeps no cookie jar; the spike reads
   `Set-Cookie` off the first answer and puts it on every request. No
   CSRF token, no `Origin` check, no CORS in the way.
4. **Drawing works from code alone.** No scene file anywhere in the
   spike: every node is made in GDScript. The meeple is the outline
   the wire serves (`render.MEEPLE_PATH`, through
   `board.meeple_geometry`), drawn by Godot's own SVG rasteriser at
   three times the size shown. The species icons, the card and both
   bundled typefaces were fetched from the server's own picture and
   font routes. A 3D solid sits in a transparent viewport over the 2D
   page. Both of Godot's renderers drew it (Forward+ over Metal, and
   Compatibility).

And the traps, each found by falling into it:

- **Godot's JSON reads every number as a float and writes `3` back as
  `3.0`.** A control sent back as Godot's `JSON.stringify` writes it
  -- `{"distance": -1.0}`, `{"space_index": 0.0}` -- passes the
  server's was-this-offered check (`0.0 == 0` in Python) and then
  answers **500 Internal Server Error** from inside the model. The
  spike's `Wire.whole` puts whole numbers back; the server should
  refuse instead of falling over (step 1).
- **Sentences arrive as HTML.** `prompt.ask`, every log line, the
  outcome's headline: `<img class="emoji" src="/emoji/team_orange.png"
  alt="Orange" ...> Voltus <img class="emoji badge" ...>`. The spike
  strips the tags to show a question at all, which throws away
  exactly the icons a sentence is drawn with.
- **A headless run draws nothing.** `--headless` never produces a
  frame, so a picture needs a real window. And twice a windowed run
  that waited for a drawn frame never got one, with the screen
  unlocked and the cause not established (a covered window is the
  likeliest); asking for the frame instead
  (`RenderingServer.force_draw`) has not failed.
- **Anti-aliasing on the solid's viewport draws nothing under
  Compatibility.** With `msaa_3d` on, the transparent viewport came
  out empty in the Compatibility renderer and right in Forward+;
  without it both draw the solid. (The picture above is Forward+, with
  it on.)
- **Nobody reads the child's stderr.** It is a pipe, and a full pipe
  stops the server in the middle of a write. The spike sends the
  server's log to a file.
- **A script error does not stop a Godot script.** It abandons the
  function that raised and the program carries on waiting, so an
  automated run needs a watchdog and must treat any `SCRIPT ERROR` in
  the output as a failure.
- **The web app does not start without `reportlab`.** `webapp/aids.py`
  imports `d12ball/rulebooks.py`, which imports it at module level --
  found because the Mac's `venv/` is behind `requirements.txt`
  (no reportlab, qrcode or numpy) and the server died on import. The
  system Python has everything and is what the spike used. It matters
  twice: it is one more library a bundled server would carry, and the
  spike's launcher had announced its port before importing, so the
  failure was silent.

### Running the spike again

```bash
python3 -m pip install -r requirements.txt   # the interpreter that will run the server
godot --headless --path docs/godot/spike --script res://play.gd -- \
    "$(which python3)" "$PWD" "$(mktemp -d)" 70
godot --path docs/godot/spike --resolution 1280x720 --script res://board.gd -- \
    "$(which python3)" "$PWD" "$(mktemp -d)" /tmp/first-picture.png
```

`godot` is the editor's own binary -- on this Mac
`~/Downloads/Godot.app/Contents/MacOS/Godot`. The folder after the
checkout is where the server keeps its files; it is never the
checkout's `data/`.

## What was found, and what it settles

**The wire is usable as it stands.** Every route a client needs
exists: who you are (`/api/me`), the rooms and a new one
(`/api/rooms`), a seat and the AI in one (`/api/room/{id}/seat/…`),
the table before kickoff (`…/table/…`), the state
(`GET /api/game/{id}`), an answer (`POST …/action`), chat, the
statistics, every picture the page draws, the bundled fonts. A state
is the whole of what a reader is shown -- 12 KB in the lobby, 44 KB in
the middle of a game -- and a page learns of the other coach's move by
asking again every two and a half seconds. There is no second way in
and the plan does not add one.

**What the wire lacks for a reader that is not the page**, each of
them step 1's:

- *Sentences are HTML* in eight places: `prompt.ask`,
  `prompt.footnote`, a situation player's `label`, the outcome's
  `headline`, `under` and `working`, every `entries[].lines[]`, and a
  cited Law's `title`. `present.render_text` makes them, and no route
  sends the model's tokens any other way.
- *Numbers are trusted to be the type they were sent as* (the 500
  above).
- *Nothing says which wire this is.* The page is served by the server
  it talks to, so it can never be out of step with it. A Godot build
  on somebody's disk can be weeks behind `play.d12ball.com`.
- *The server cannot be told where to keep its files.*
  `python3 -m webapp` takes no arguments; the six files default into
  the checkout's `data/`. `landing/capture.py` gets round it with a
  five-line launcher that calls `serve(...)` with six paths, and the
  spike copied it.
- *It cannot pick its own port and say which.* Port 0 binds, and the
  port is reported nowhere.
- *The idle sweep is wrong for one player's machine.* At start and
  every hour it deletes a room nobody played in after a day and
  abandons a started game after fourteen. Somebody who comes back to
  their own game after three weeks would find it abandoned.
- *An answer to a click forgets who clicked.* `act`, its not-offered
  409 and `resume` build the state without the reader, so in those
  answers `you.coach` is null and `room.admin`, `room.may_leave` and
  `room.take_over` read as nobody's; the next poll puts them right.
  The page never notices. A client that draws from every answer would.

**What the wire has that is the page's own, and stays**: the fans'
offsets are in pixels of a meeple fifty wide (thirty on a phone), so a
client scales them; a few captions describe the page's gestures ("drag
a bench meeple onto the player it replaces, or click the two in
turn"), so the Godot client keeps those gestures and the captions stay
true; the outcome carries the first headline's working only, and a
roll its faces without the totals, which is what the page shows and
what Godot shows too.

**The model plays on the standard library alone**: twenty-five modules
of `d12ball/`, no Pillow, no numpy, Python 3.10 at the oldest. The
server over it wants aiohttp, and Pillow for the pictures it draws on
request. A whole game is about 180 answers for the two coaches
together, the tutorial 41.

**What a port would be, costed once so nobody costs it again.** The
modules a game imports are 32,074 lines of Python. Thirty-one of the
thirty-six players have a special ability, and each is code, not data.
Every draw comes from one `random.Random`, so a port held to the
goldens would have to reproduce CPython's Mersenne Twister, its
`randint`, `choice` and `shuffle`, and the order of every call --
measured: a `Random` that makes its draws one step differently plays a
different game from the same seed (167 answers and no shootout, where
`tests/test_driver_full_game.py`'s game is 181 and one). Then every
rules change is made twice, in two languages, for ever. That is the
second copy of the rules this repository exists not to have.

**There is nothing to hear and nothing solid.** The repository holds
106 pictures (36 portraits, the tokens, the coins, the badges, the
species icons, 12 MB) and no sound at all, no 3D model, and no card or
board art as files -- cards and boards are drawn in code. The
portraits are around 400 pixels across: right at card size, soft at
anything larger. `d12ball/dice.py` holds the dodecahedron's geometry
and only ever draws it to pixels. The bundled typefaces' licences
(Apache 2.0, OFL) allow shipping them in a game.

**What the engine's documentation says** (read on 2026-10-04, none of
it run here except where "What was tried" says so):

- Godot never cleans up a process it started and can only kill one
  outright, so the server has to leave by itself. The spike's
  end-of-file watch is the pattern.
- Python inside Godot (py4godot, godot-python) is not ready: nothing
  has a stable release for Godot 4. A separate process is the way.
- A server frozen with PyInstaller should be a folder, not a single
  file: one-file is two processes, and killing the first orphans the
  second.
- On macOS a frozen Python tree inside an exported `.app` has to be
  signed after the export -- Godot's exporter skips the `.so` files in
  it -- and Pillow ships no universal wheel while Godot's macOS
  templates are universal only. None of that was tried.
- Phones and the browser cannot run a second process at all.
- Steam wants macOS builds notarized, and a child process left
  running keeps Steam showing the game as running.

## The decisions

These are the ones the plan is built on. Each is the recommendation
and its reason; the author overrules any of them by saying so on the
PR, and the step's prompt is rewritten rather than argued with.

0. **The rules stay in Python, and Godot only draws and sends
   actions** (the author, 2026-10-04). In a server, or in a local
   background process. Everything below is under this.

1. **One wire, and it is the web app's.** Not a new protocol and not a
   second server: the Godot client talks to `webapp/server.py` as the
   page does. The server already does everything a second one would
   have to do again -- who somebody is, rooms and seats, the AI in a
   seat, the table before kickoff, the log, the pictures, the rules --
   and seventy answers went through it untouched. **What it costs:**
   `webapp/present.py` was written for one reader and now has two, so
   its shape stops being a detail of the page and becomes something a
   change can break at a distance. Decision 11 is what that costs.

2. **Offline is the same server on the player's machine.** Not a
   cut-down one and not the model called some other way:
   `python3 -m webapp`, frozen, started by the game as a background
   process, bound to `127.0.0.1` on a port it picks, over files in the
   player's own data folder. Online is the same client naming
   `https://play.d12ball.com`. **The two differ by one address**, so
   there is one client to build and one wire to keep, and "one process
   per file" (web-app.md) holds on a player's machine as it does on
   the host.

3. **A Godot coach is a web coach.** Online, a Godot client is in the
   web app's rooms: it may play somebody in a browser, and neither can
   tell. The decision of 2026-09-25 was that the bot and the web app
   share nothing at runtime, and that stands -- no game is ever on
   Discord and anywhere else. This is the web system gaining a client,
   and it costs nothing: the server cannot tell the two readers apart
   except by what they ask for. An empty lobby of Godot-only rooms
   would be the alternative. (Asked of the author below.)

4. **Desktop first: Windows, macOS, Linux, and so the Steam Deck.**
   Those are where a second process can run. **Not a browser export**:
   the web app is the browser version. **Not phones in this plan**: a
   phone cannot start a process, so a phone build is an online-only
   client, and the web page already has a phone layout. If phones are
   ever to play offline the way is CPython inside the app (official on
   iOS and Android since 3.13) behind this same wire, **never a
   port**.

5. **The client holds nothing of the game.** No roster, no card text,
   no number, no sentence, no picture of a player. Names, colours,
   costs, labels, what is lit and what pressing it sends all arrive on
   the wire, and the pictures -- cards, portraits, tokens, icons, the
   meeple's outline -- from the server's own routes, as the page gets
   them. So a roster revised in the sheet reaches the Godot game the
   way it reaches the page, with no Godot change. What the project
   does carry is its own: its layout, its palette, the bundled
   typefaces (copied from `d12ball/fonts/` by a script, never a second
   committed copy), its shaders, its sounds, the die's mesh. **A test
   holds it** (decision 10).

6. **The play area is the redesign's, and what is new gets looked at
   before it is built on.** The author settled the field, the meeple,
   the fans, the badges, the goals, the jumbotron bar, the benches,
   the question box and "the answer is the thing on the board, lit in
   gold" on the canvas of 2026-09-26
   ([web-app-redesign.md](../web-app-redesign.md)); Godot draws that,
   so the first six drawing steps have a reviewed design to match.
   Three things have no design yet -- the shell around the game (the
   title, the menus, with no Discord chrome to borrow), how things
   move, and what the die looks like -- and each of their steps stops
   on something the author looks at before the next one starts.

7. **GDScript, scenes built in code, one pinned Godot.** GDScript
   because it needs no second toolchain and is the engine's own. Built
   in code because the board is drawn from data anyway, a script is a
   text diff a reviewer can read, and nothing then depends on the
   editor having been open: the spike has no scene file and neither
   does a step unless it says why. The version is written down once
   (`godot/.godot-version`, 4.7.2 today) and a tool finds the binary
   through `GODOT` or `--godot`, never a typed path.

8. **The Compatibility renderer.** A flat board and one small solid do
   not need Vulkan, and Compatibility runs on old laptops and on a
   machine with no graphics card at all, which is what a CI runner is.
   If the die cannot be made to look right in it, step 9 says so with
   two pictures and the author chooses.

9. **In this repository, under `godot/`**, for the reason the web app
   is here ([web-app-next.md](../web-app-next.md), "A second
   repository?"): a change to the wire and the client that reads it
   have to be one PR. `godot/` is to the Godot game what
   `webapp/static/` is to the page.

10. **What holds it together is tested without Godot, and what Godot
    does is tested with it.** In the Python suite, always: the wire's
    new shapes (step 1); that `godot/` names no player, no maneuver
    and no special ability from the catalogs (decision 5 as a thing
    that can be run -- a client that says `"zenith"` has a rule in
    it); that every place `present.py` can light is one the client
    either draws or lists as drawn plainly on purpose; that the
    client's wire number is the server's. With a Godot binary, where
    one is found, and skipped with a line saying so where not: the
    client's own unit tests, every control of every prompt fixture
    turned into exactly the body the page would post, and **a whole
    game and the tutorial played through the client's own code against
    a real local server** -- `tests/test_driver_full_game.py`'s
    promise, one layer further out. None of it sees the window.
    **How it looks is checked by looking**: `scripts/capture_godot_views.py`
    stages a position, starts the server over a temporary folder, runs
    the game in a real window at three sizes and saves the pictures,
    and a step that changes what is drawn puts them in its PR, in
    standard and in advanced mode.

11. **Being out of step with the server is designed for, because
    online it is the normal case.** The state carries the wire's
    number and the client refuses, in words, a server whose number it
    does not know. Below that line, three habits make most changes
    harmless: **a place the client does not know is drawn as a plain
    control** -- every control carries its label and its action, so a
    new prompt or a new thing to light costs an old client its looks
    and never its game; a run of text it does not know is drawn as its
    `alt`; and a field it does not know is ignored. Offline there is
    nothing to be out of step with: the server in the box is the one
    the client was built against.

12. **A control goes back as it came.** The client never builds an
    action: it sends the `action` of a control it was handed, numbers
    made whole, a chooser's fields filled from the choices it listed.
    That is the page's rule ("a page may only send back a control it
    was offered") and the reason a client can be built without knowing
    what any argument means.

## Questions for the author

Each step's PR carries a `## Questions to the author` section; these
are the ones known before any step starts. A step whose prompt needs
the answer says what it builds until it has one.

1. **Where is this going -- itch.io, Steam, both, or to friends by
   hand?** Nothing before step 14 depends on it, and step 14 does not
   start without it: a macOS build people can open needs an Apple
   Developer ID, Steam needs a store page and its own build of the
   box. Until answered, step 3's builds are unsigned and handed over
   as a zip.
2. **May a Godot coach play a browser coach** (decision 3)? Built as
   yes.
3. **Two coaches at one machine.** The wire already allows it without
   a rule being touched: a client that holds two cookies is two
   people, and each one's state already leaves out the other's
   maneuver pick. It needs a curtain between turns and it is not in
   these steps. Wanted for the first release, or later?
4. **Sound.** There is none in the repository. Step 11 uses CC0
   sounds, each listed with where it came from, and the author keeps
   or replaces them by listening -- unless the author would rather buy
   or make them, which changes that step and nothing else.
5. **The shell's look.** The field has a design; the title screen and
   the menus do not, and the page's greys are Discord's. Step 4 builds
   the front door in the box art's night palette, which is what the
   landing pages took for a screen, behind a sketch on a canvas the
   author sees first. A different direction is one sentence here.
6. **The opponent.** Dinky is the only AI, and offline it is the whole
   of the game for one player. Nothing here changes that; it is
   written down because it is the first thing somebody who downloads
   the game will meet.
7. **Godot itself.** It is running from `~/Downloads` on the Mac, and
   macOS runs an app in Downloads from a randomised, read-only copy.
   Moving it to `/Applications` is the author's to do; the tools take
   `GODOT` either way.

## The wire, as a client reads it

Enough to read a step's prompt against. The reference is
[web-app.md](../design/web-app.md) and `webapp/present.py`; this is a
map of it, taken from two states the spike saved.

| In the state | What it is | Drawn in step |
| --- | --- | --- |
| `you`, `room`, `game` | Who is reading, which seat, who else is here, the room's name and status | 4 |
| `table` | Before kickoff: `settings[]` (each with its `choices` and whether it may change), `seats[]` (each with the `teams` it may pick), `start`, `coin`, `sides` | 4 |
| `board.layout` | `jumbotron`, `zones[]`, `spaces[]` (each with its two `fans` and the `ball`), `goals`, `bands[]`, `team_boards[]`, `rosters[]`, and `meeple` -- the outline and where the icon and the letters sit on it | 5 |
| `prompt` | `kind`, `ask`, `footnote`, `state` (`yours`, `waiting`, `now`, `full_time`), `controls[]` in sections, `lit[]`, and by kind `situation`, `hand`, `shootout` | 6, 7 |
| a control | `type` (`button` or `chooser`), `label`, `disabled`, `place` and `also` (what it lights), `chip`, `cost`, `card`, `first` (a two-object answer), `fields` (a chooser's), and `action` -- what pressing it sends | 6 |
| `place.at` | `player`, `space`, `ball`, `goal`, `die`, `whistle`, `time_out_tile`, `bench`, `out_of_play`, `note`, `card`, `formation`, `coin`, `face`, `rematch` -- or none, the one plain control | 6, 7 |
| `entries[]`, `latest` | The log since the reader's `since`: lines, the minute, and a `kind` (`goal`, `new_play`, `roll`, `clock`, `line`) | 8 |
| `outcome`, `roll`, `reveal`, `full_time` | The headline and its arithmetic; the dice as faces, colours and haloes; the two cards turned over; the final table | 7, 8, 9 |
| `aids` | The reference rows a game's mode plays by, and the reference pictures | 8 |
| `owed` | The bot owes a step (after a restart): offer `resume` | 6 |
| `chat[]`, `chat_latest` | What people in the room have said | 13 |

## The steps

In the order they pay off. Each is one branch off an up-to-date
`main`, one PR against the template, the suite green, the six
safety-net tests untouched. **None changes the save format. None adds
a rule anywhere.** Where a step needs the wire to say more, that is a
change under `webapp/` in its own commit with its own test, and the
page gets it too; where it would need the *model* to say more, the
step stops and asks.

Every step ends on a **stop**: the thing the author looks at before
the next step is worth starting.

| # | Step | Size | Stop |
| --- | --- | --- | --- |
| 1 | The wire answers a client that is not the page | medium | The page, unchanged, in its three pictures; the spike's play-through with no workaround left in it |
| 2 | The skeleton: `godot/`, the wire's client, the local server, the tools | large | The game opens, starts its own server, and says who you are |
| 3 | A build somebody else can run | large | The author opens it on the Mac; the other developer on Windows |
| 4 | The front door and the table | medium | A room against Dinky, set up to kickoff |
| 5 | The field, the jumbotron and the benches | large | A position, in six pictures |
| 6 | Answering on the board | large | A whole game played in the window |
| 7 | The cards and the windows | large | The hand, the reveal, a Coaching Choice, a shootout, full time |
| 8 | What was said | medium | A turn read back: the log, the outcome, the situation |
| 9 | The dice | medium | A clip of a roll |
| 10 | Motion | large | A clip of a turn, and of a run back |
| 11 | Sound | medium | The author listens |
| 12 | Settings, and coming back to a game | small | Quit in the middle of a turn; open it again |
| 13 | Online | medium, half of it in a dashboard | A Godot coach and a browser coach in one room |
| 14 | Signing and release | medium, half of it the author's | Somebody who is neither developer downloads it and plays |

After step 8 the Godot game does everything the page does for a
match. Steps 9 to 11 are what a page cannot do. Step 3 is early on
purpose: freezing the server and starting it from an exported game is
the part of this plan nobody has run, and every step after it then
ends on something that can be handed to a person.

### Claiming a step

`scripts/claim_web_step.py --series godot <n>` claims step `n`: it
pushes an empty commit to `godot-step-<n>` and refuses if the branch,
an open PR titled `Godot step <n>:`, or a struck row already exists.
The series does not exist yet: **step 1's prompt adds it** -- one
entry in `SERIES`
(`"godot": ("docs/godot/README.md", "godot-step", "Godot step")`),
plus the `--series` help string and the module docstring, which both
list the series by hand.

**No cloud routine is set up for this series** until step 2 has said
whether the routine's machine can draw a frame. Most of these steps
stop on a picture, and a machine that cannot take one cannot finish
them.

---

## Preamble

Every step's prompt begins with this block. A session given a step
reads it first, then the step's own prompt below.

```text
You are working in the fool-bot repository on D12 Ball in Godot, the
plan in docs/godot/README.md. Read CLAUDE.md first, then that
worksheet, then docs/design/godot.md if it exists, then
docs/design/web-app.md ("What it may not do", "The wire", "Who is on
the other end", "What a page is handed", and "The page" for the part
of the page your step draws). Do not read the rest of docs/design/
unless your step names a file.

Start on a fresh branch off an up-to-date main (the claim script has
made it: git fetch && git checkout godot-step-<n>), in a worktree of
your own if another session may be using the checkout. Never work on
main.

Hard rules for every step:
- The rules are in Python and stay there. The Godot client decides no
  rule, words no sentence and names no player, maneuver or ability:
  everything it shows is the wire's. If a design needs something the
  wire does not carry, the wire grows a field under webapp/ in its own
  commit with its own test, and the page gets it too. If it would need
  the model to say more, stop and ask under "Questions to the author".
  Never work a candidate list, a distance, a range, a cost or a total
  out in GDScript.
- A control goes back as it came: the action of a control the state
  offered, numbers made whole, a chooser's fields from its own
  choices. A place the client does not know is drawn as a plain
  control with its label; a run of text it does not know as its alt.
- Nothing rolls before the server has rolled. A die lands on the face
  the wire gave; a piece stops where the wire's layout puts it. An
  animation is how a position is shown, never what it is.
- Team colours come from the wire and nowhere else. The client's own
  colours are in one file.
- GDScript with static types; scenes built in code. No .tscn, no
  addon, no C# and no GDExtension unless your step says so. The Godot
  binary is found through GODOT or --godot, never a typed path, and
  the version is the one in godot/.godot-version.
- The client reads nothing from the repository at runtime: not
  d12ball/data, not d12ball/images, not docs/. What it needs of the
  game it asks the server for.
- Nothing under webapp/ changes how the page looks. Where your step
  touches webapp/, python3 scripts/capture_web_views.py before and
  after, and say on the PR that the three pictures did not change.
- Look at it. The suite cannot see the window. A step that changes
  what is drawn runs python3 scripts/capture_godot_views.py --out
  <dir> and puts its pictures in the PR at all three sizes, in
  standard and in advanced mode, and training too where it differs.
  A step that changes how something moves puts a clip in the PR.
- Run python3 -m unittest discover -s tests before the PR, and the
  Godot tests through it (tests/test_godot_client.py runs them where
  a Godot is found; say on the PR that it ran, not skipped).
- Do not touch docs/living-rules.md, the save format, or the six
  safety-net tests.
- One PR per step, against the template, with a "Questions to the
  author" section ("None." when empty). The PR strikes this step's
  row in docs/godot/README.md, writes what the step settled into
  docs/design/godot.md with the reasoning, and adds a row to
  CLAUDE.md's tables only for a new module or a new hard rule.
```

---

### 1. The wire answers a client that is not the page

Python only. Nothing under `godot/` exists yet and no Godot is needed
for the suite; the spike is the only thing that reads the result.

```text
Step 1 of docs/godot/README.md. Read "What was found" there for what
the wire lacks, and tests/test_web_app.py and tests/test_web_table.py
for how the wire is tested today.

Six changes, each its own commit with its own test. The page must not
change: take python3 scripts/capture_web_views.py before the first
commit and after the last, and say on the PR that they match.

1. Sentences as runs. webapp/present.py gains render_runs(text, game):
   the passes render_text makes today -- the model's markdown, then
   its tokens -- answering a list of runs instead of a string of HTML:
     {"text": "...", "bold"?: true, "italic"?: true, "headline"?: 1|2|3}
     {"icon": "/emoji/team_orange.png", "alt": "Orange",
      "kind": "team" | "role" | "condition" | "species" | "coin"}
     {"text": "<the coach's name>", "kind": "coach"}
   The icon's address and its alt are the ones the HTML carries today
   (the role badge in its colour team's file, drain as the Cyborg's
   token, the coin's metal and value); a client is handed them and
   works out none. A newline stays a newline inside a text run.
   render_text becomes the HTML written from those runs, so there is
   one reading of a sentence and two ways to write it. It must be
   byte-identical to today's: before deleting the old path, compare
   the two over every prompt fixture's ask and every line of
   tests/golden/service_tutorial_transcript.txt, and say so on the PR.
   A request carrying ?text=runs is answered with runs wherever a
   field is HTML today: prompt.ask, prompt.footnote, a situation
   player's label, outcome.headline (the " · " between headlines a
   text run), outcome.under, outcome.working, entries[].lines[] and
   refusal_law.title. Without it nothing changes. The rules routes
   (/api/rules/charter, /api/rules/learn) stay HTML: they are
   documents, not sentences.

2. The wire's number. WIRE_VERSION = 1 beside the code that shapes the
   state; every state carries "wire"; GET /api/wire answers
   {"wire": 1} to anybody and issues no cookie. Write the rule for
   raising it into docs/design/web-app.md: raised when a field a
   client reads is taken away or changes its meaning; never for a new
   field, a new place or a new kind of run, which a client is
   required to survive.

3. Numbers. _was_offered matches a posted number only against an
   offered number of the same type, so a float where an integer was
   offered is the existing 409 ("That is not one of the controls this
   page is offering") and never reaches the model. The test posts the
   two bodies the spike sent -- {"distance": -1.0} and
   {"space_index": 0.0} against controls that offered -1 and 0 -- and
   asserts 409, where today they are 500.

4. The reader in every answer. act, its not-offered 409 and resume
   build the state with coach=, as every other route does, so
   you.coach and the room's admin, may_leave and take_over are right
   in the answer to a click. If the omission turns out to be
   deliberate, stop and ask instead.

5. python3 -m webapp --local <folder> [--seed N]: the web app as a
   background process on one person's machine. With --local it
   - keeps all six of its files in <folder> (the games, the rooms,
     the chat, the journal, the names, the secret), created if
     missing, and never reads .env;
   - binds 127.0.0.1 on a port the system picks, and once it is
     listening prints one line of JSON on stdout,
     {"port": N, "wire": 1}, and nothing else on stdout ever;
   - logs to <folder>/webapp.log, not to stderr;
   - never runs the idle sweep: nobody's own game is abandoned for
     being left alone;
   - leaves when its stdin reaches end of file, which is how it
     follows the process that started it out;
   - with --seed, seeds engine.rng, for a test that has to play the
     same game twice.
   Without --local nothing changes: no arguments, the environment's
   host and port, the checkout's data/. Test it by starting it as a
   subprocess over a temporary folder, reading the line, asking
   /api/wire, closing its stdin and seeing it gone; and that a full
   run of the suite still creates no data/.

6. scripts/claim_web_step.py: the "godot" series, as "Claiming a
   step" in the worksheet says.

Then make the spike honest: docs/godot/spike/sidecar.py becomes one
line that runs python3 -m webapp --local, wire.gd asks for ?text=runs
and loses nothing by it, board.gd's plain() goes and the question is
drawn from its runs with the icons in it, and play.gd's last request
expects 409. Run both and put board.gd's picture in the PR.

docs/design/web-app.md: "The wire" gains its second reader -- why
runs and not raw tokens (a client handed {role:fullback:orange} would
need the page's table of which file that is), why a number, why
--local is one flag and not six.
```

### 2. The skeleton: `godot/`, the wire's client, the local server, the tools

Everything the later steps fill in, and the proof that the tools run
on a clean checkout.

```text
Step 2 of docs/godot/README.md. Step 1 has landed.

Create godot/, a Godot 4.7.2 project (godot/.godot-version says so,
and a tool that finds a different version says so and stops):

- project.godot: the Compatibility renderer; stretch mode
  canvas_items with aspect expand over a 1920x1080 base, so one
  layout serves 16:9 and the Steam Deck's 16:10; a 1280x720 window by
  default and 1024x576 at the smallest. The main scene is the one
  .tscn in the project -- a bare Control with main.gd on it -- because
  the engine wants one; everything else is built in code.
- Four autoloads, each a script and nothing else:
  Wire -- the address it talks to; the cookie, kept per address under
  user:// and never logged (it is who the player is); one request at a
  time for the API so answers arrive in the order they were asked,
  and a small pool beside it for pictures; ?text=runs and the since
  and chat_since cursors on everything that answers a state; whole
  numbers on the way out (the spike's Wire.whole, and why);
  state_changed, refused and unreachable as signals; the poll at the
  page's two and a half seconds, slower while the window is not in
  front. It refuses a server whose "wire" it does not know, in words.
  LocalServer -- starts python3 -m webapp --local over a folder under
  OS.get_user_data_dir(), reads the port, waits for /api/wire, and
  closes the pipe on the way out; if the server leaves by itself it
  starts it again and the game re-reads its state, since the save is
  the server's and nothing is lost. In the editor and in tests the
  Python is the checkout's: GODOT_PYTHON, or python3 on the path.
  Pictures -- a texture for an address, fetched once, kept in memory
  and under user://cache by address; the meeple's outline through
  Image.load_svg_from_string at the size it is shown.
  Text -- runs into a RichTextLabel: text with its weight, an icon
  through add_image at the line's height (a picture fetched at
  runtime has no res:// path, so [img] cannot name it), a run it does
  not know as its alt.
- godot/ui/palette.gd: the client's own colours, the one file that
  holds any. No team colour is in it.
- The first screen: starts the local server, says who you are (the
  name /api/me gives) and lists your rooms as plain lines. No design
  yet; step 4 draws it.
- The fonts: scripts/build_godot_assets.py copies the bundled faces
  and their licences from d12ball/fonts/ into godot/fonts/, which is
  gitignored -- one copy in the repository, as the landing build takes
  Racing Sans One. The tools below run it; README says to run it once
  before opening the editor.
- .gitignore: godot/fonts/, and Godot's own .godot/ (already there).
  The .uid files the engine writes beside each script are committed:
  run godot --headless --import once and commit what it makes.

The tests, in two halves:
- With no Godot, in the suite always: tests/test_godot_purity.py --
  no text file under godot/ names a player's id or name, a maneuver's
  key or name, or a special ability, read from the catalogs (decision
  5); godot/wire/version.gd's number is webapp's WIRE_VERSION; every
  place present.py can give a control is in godot/wire/places.gd,
  either as a binder or under PLAIN_ON_PURPOSE (give present.py one
  tuple that lists its places if it has none, in its own commit).
- With one: godot/tests/run.gd, a runner of our own (a hundred lines:
  no addon), started by tests/test_godot_client.py, which finds Godot
  through GODOT, the path, /Applications and ~/Downloads, skips with
  a line saying so where there is none, and fails on a non-zero exit,
  on a timeout, and on any "SCRIPT ERROR" in the output -- a script
  error does not stop a Godot script, it abandons the function. What
  it runs: Wire.whole; the cookie kept and resent; runs to text;
  every control of every prompt fixture turned into the body the page
  would post (scripts/build_godot_fixtures.py writes each fixture's
  state, as tests/prompt_fixtures.py builds it and the server would
  answer it with ?text=runs, into a temporary folder the test hands
  over); and a whole game against Dinky and the tutorial, played
  through Wire against a real --local --seed server to full time, a
  window finished by its whistle and otherwise the first control
  offered, no answer refused.
- .github/workflows/tests.yml: a second job that downloads the pinned
  Linux editor, imports, and runs the Godot half headless. If that is
  slow or flaky, say so on the PR rather than leaving it red.

The tools:
- scripts/capture_godot_views.py --out <dir> [--games-file F --game
  ID] [--mode standard|advanced|training] [--godot PATH]: stages a
  game as scripts/capture_web_views.py does (or copies a saved web
  games file, read and never written), starts the server over a
  temporary folder, and runs the game in a real window with --capture,
  as a coach so what is lit shows, at three sizes: 1280x720,
  1920x1080 and the Deck's 1280x800. The game's --capture mode opens
  that room, waits until its pictures have arrived, asks for the frame
  (RenderingServer.force_draw -- a covered window is never drawn, so
  there may be none to wait for), saves and quits. A run that draws
  nothing in twenty seconds stops and says the screen may be locked.
- Find out, and write down in the design note, whether a machine with
  no screen can take these: on Linux, xvfb-run with a software
  renderer. It decides whether a cloud routine can run this series.

Delete docs/godot/spike/: the project replaces it. Keep
docs/godot/first-picture.png; the worksheet shows it.

docs/design/godot.md: the design note. What the client is and is not,
the four autoloads and why each is one, why no scene files, why the
fonts are copied, the two halves of the tests and what neither sees,
how to take the pictures. CLAUDE.md: a row for godot/ in "Where
things live", a row in "Read this before touching", and the hard
rules a later change must not undo -- the client names nothing of the
game; a control goes back as it came; look at it at three sizes.

Stop: open the project, and put a picture of the first screen in the
PR.
```

### 3. A build somebody else can run

The part of this plan nobody has run. It is early so that if it
cannot be done the way decision 2 says, that is known before ten steps
are built on it.

```text
Step 3 of docs/godot/README.md. Step 2 has landed. Unsigned builds,
handed over as zips: signing is step 14 and waits on the author.

The server, frozen:
- First make it lighter. The web app must start with reportlab, numpy
  and qrcode refused: d12ball/rulebooks.py imports reportlab at module
  level and webapp/aids.py imports it for the rules pages, which need
  the markdown and the numbering and not the PDF. Move the PDF's
  imports to where a PDF is made, and add the server to
  tests/test_model_purity.py's subprocess check with those three
  refused. Its own commit; python3 scripts/build_rulebooks.py still
  builds both books.
- scripts/build_godot_server.py: PyInstaller, one folder (never one
  file: that is two processes, and stopping the first leaves the
  second), of python3 -m webapp, carrying d12ball/data, d12ball/images,
  d12ball/fonts, webapp/static, docs/living-rules.md,
  docs/learn-to-play.md and docs/rulebooks/figures -- what the server
  reads by path. PyInstaller goes in a requirements-build.txt, not in
  requirements.txt: the bot does not need it. Start the frozen server
  with --local over a temporary folder and play the Godot full-game
  test against it, so "it froze" means "it plays".
- Report on the PR, per system: the folder's size, the time from
  start to the announced port (cold, and again warm), and its memory
  after a whole game.

The game, exported:
- godot/export_presets.cfg, committed (it holds no secret), for
  Windows, macOS and Linux. LocalServer starts the frozen server when
  one is beside the game -- server/ next to the executable on Windows
  and Linux, inside the .app on macOS, since macOS runs a downloaded
  app from a randomised path and a server beside it would not be
  found -- and the checkout's Python only when there is none.
- A workflow that builds all three on their own runners (PyInstaller
  cannot build for a system it is not running on), on a tag and by
  hand, never on every push. On macOS, Pillow has no universal wheel
  and Godot's templates are universal only: build the server for each
  architecture and have LocalServer pick by
  Engine.get_architecture_name(), or merge the two wheels; take
  whichever works, and say which and what it cost in megabytes.
  On Linux build on the oldest runner there is, for its glibc.

What to try on a machine that has never seen it, and write down:
- Windows: does a console window flash; does the firewall ask about a
  server bound to 127.0.0.1; does Defender object to the frozen
  Python (PyInstaller's known trouble -- if it does, say what it
  said).
- macOS: unsigned, it opens only by right-click; does the server
  inside the .app start at all.
- All three: quit the game, and end it from the task manager -- is
  the server gone both times.

Stop: the author runs the macOS build and the other developer the
Windows one; each plays the first screen and says so on the PR. If
any system cannot be made to work, stop there and say exactly what
failed: decision 2 is then the author's to revisit, and no later step
starts.
```

### 4. The front door and the table

```text
Step 4 of docs/godot/README.md. Steps 1 to 3 have landed.

Before building: the shell has no design (question 5 in the
worksheet). Make one sketch of the front door and the table in the
box art's night palette (box_art.NIGHT_COVER, the palette the landing
pages took for a screen), show it to the author on a canvas, and build
what comes back. If the author has answered question 5 otherwise,
build that.

Then, all of it drawn from the wire:
- The front door: who you are, and renaming (POST /api/me; a name
  taken is the server's 409, shown in its words); your rooms by where
  each stands, the open rooms, a new room -- /api/rooms' three lists,
  as webapp/static/index.js draws them. "A new room" with the page's
  two ticks: Dinky in the other seat, and the tutorial.
- The table, from the state's "table": the settings as the wire lists
  them (each with its choices, whether it may change, its note and its
  warning -- the client knows no setting's name); the two seats, each
  with the teams it may pick in the colours the wire gives; the AI
  put in a seat and taken out; Start, with the refusal the wire gives
  for why not yet; the coin, which is the coin's own picture clicked
  to flip; the side, chosen by clicking the goal to defend. Every
  move is one POST to /api/room/{id}/table/{move} or .../seat/{move},
  answered with the state or with a 409 and its sentence.
- Playing against Dinky offline needs no network, and says so
  nowhere: it is simply what the game does. "Online" is a second
  address, off until step 13.

Tests: every table fixture state (tests/test_web_table.py's
positions, written out by build_godot_fixtures.py) builds without a
script error, and the full-game test now sets its table through this
screen's own code. Pictures: the front door and the table, three
sizes.
```

### 5. The field, the jumbotron and the benches

```text
Step 5 of docs/godot/README.md. Steps 1 to 4 have landed. The design
is the redesign's: docs/web-app-redesign.md, "What the prototype
settled", and its canvas. Read webapp/board.py and how
webapp/static/app.js draws its layout (stage, pitch, space, fanOf,
meepleArt, badges, ball, goal, drawJumbotron, sideline). You are
drawing the same layout from the same JSON; nothing is lit yet.

From state.board.layout, and nothing else:
- The field: the goals at each end as slabs bordered in the defending
  team's colour with GOAL in Racing Sans One and the d12 showing 12
  as its O; the zones' names over their spaces; each space with its
  number, the visitors' lane above and home's below, the outer zones
  tinted, the kickoff space ringed; the range bands under it.
- The meeple: layout.meeple's outline through Pictures, in the
  piece's colour with the ink outline, the role's letters in the
  piece's ink where the geometry puts them, and the species icon over
  them where layout.species_icons says so.
- The fans: each piece where the wire put it. The offsets are in
  units of a meeple fifty wide; scale them by the meeple you draw.
  Names under the fan in the order the wire gives.
- The badges: the exhaustion token's picture with its count, the
  condition's emoji, where the redesign puts each. The ball: the d12
  face-on showing its speed, at its holder's corner or loose in the
  middle of its space.
- The jumbotron, one bar: the teams in their colours, the score, the
  coaches, who has the ball, the minute, the thirty-segment track,
  last possession, a time-out tile a side.
- The benches: two boxes a team, bench and back bench, the same
  meeples. Hover any meeple for its card (the card route's full face,
  in the face the game's mode plays), and a button on a gamepad for
  the same.
- It fits: the field whole at every size from 1024x576 up, nothing
  leaving its space, nothing under another thing.

The client still names nothing: a zone is its label, a team its name
and colour, a role its letters, all as sent. Pictures: a kickoff, and
a position late in a game with a fan of three or four, an exhausted
player, an injured one and a loose ball (stage them from
tests/prompt_fixtures.py through --games-file), at three sizes, in
standard and in advanced; and training, whose meeples carry no
species icon.
```

### 6. Answering on the board

After this step a whole game can be played in the window.

```text
Step 6 of docs/godot/README.md. Steps 1 to 5 have landed. Read
webapp/present.py's control and place builders and lit_line, and
docs/design/web-app.md, "The page": "The question box", "The answer
is the thing on the board", "The lit line", "The whistle".

- The question box: the ask and the footnote as runs; the state's tag
  (yours, waiting and on whom, now, full time); the lit line, every
  entry as the wire words it, which is also the keyboard's and the
  gamepad's list of what may be pressed.
- A binder for each place in godot/wire/places.gd: player (on the
  field or the bench), space, ball, goal, die, whistle,
  time_out_tile, bench, out_of_play, note. Lit is gold (#f0b232, the
  redesign's) round the thing itself; "also" lights with it; a chip
  and a cost are drawn as sent. Pressing it posts the control's
  action through Wire. A disabled control is drawn and cannot be
  pressed, with its note.
- A control with "first" is two things in turn: pick up the first,
  put it on the place. Drag does the same. A chooser is its fields,
  each a list of the choices the wire gave, and its submit.
- Everything else is the one plain control, outlined, with its label:
  a place the client does not know, a control with no place, and --
  until step 7 draws them -- card, formation, coin, face and rematch,
  listed under PLAIN_ON_PURPOSE with step 7 as the reason.
- A refusal is the server's sentence, shown where the question is,
  with its Law as a link when the wire cites one (it opens the
  server's own /rules at that Law in the system's browser; step 8
  says why).
- "owed": the server owes a step after a restart. Offer Resume,
  which is POST .../resume, as the page does.
- A keyboard path (number keys down the lit line, Enter, Esc) and a
  gamepad path (the stick moves among what is lit, one button
  presses), since a Steam Deck has no mouse.

The fixtures test from step 2 now goes through the binders, so every
control of every one of the thirty-six kinds is reachable from a
thing on the screen or the plain control, and posts what the page
would. The full-game test presses through the binders too. Pictures:
one prompt of each place, lit, at three sizes; and say on the PR that
you played a whole game against Dinky in the window, and how it went.
```

### 7. The cards and the windows

```text
Step 7 of docs/godot/README.md. Steps 1 to 6 have landed. Read
docs/design/web-app.md, "The page": "The hand, the reveal and full
time", "The sideline is under the field", "The Coaching Choice on the
board", "The shootout order in the box"; and the same steps of
docs/web-app-redesign.md (5, 6, 7) for the design each was built to.

What step 6 left as plain controls, drawn as what it is:
- The hand: prompt.hand and the card controls -- the maneuver cards
  as the server's own pictures (/api/game/{id}/maneuver/{key}.png),
  the other side's as backs, a pick that only its coach sees, the
  gambit and the confirm. The reveal: state.reveal's two cards turned
  over, what stands between them, and the winner. Nothing is turned
  before the wire says it is.
- The formation tiles (the control's "shape"), the coin, a die face
  (place "face").
- The Coaching Choice on the board: the bench lit, a substitution by
  dragging a bench meeple onto the player it replaces or by clicking
  the two in turn -- the wire's own caption says both, so both must
  work -- a swap, a reposition onto a lit space, the whistle to
  finish.
- The shootout order: the section's "order" -- who is placed, how
  many slots -- filled a slot at a time, one POST each, as the page
  sends them; the other side's shown only as done or not, which is
  all the wire sends.
- Full time: state.full_time's table, the final board, and the
  rematch, which is the one control that posts to the room's own
  route ("post") and sends everybody on to the new room by the
  state's "rematch".
- The tutorial's notes behind Continue, with nothing special about
  them: a prompt like any other.

PLAIN_ON_PURPOSE is empty at the end of this step, or says why not.
Pictures: the hand before and after a pick, the reveal, a Coaching
Choice mid-substitution, a shootout order half filled, full time; in
standard and advanced (the hand differs: a gambit's cards), three
sizes.
```

### 8. What was said

```text
Step 8 of docs/godot/README.md. Steps 1 to 7 have landed. Read
docs/design/web-app.md, "The outcome banner", "The situation", "The
page" on the sidebar's four tabs, and "The rules and the player
aids".

- The outcome: state.outcome, large and first -- the headline in the
  winning side's colour, what is under it, its working -- above the
  next question. The words are the wire's runs; the client adds none.
- The situation: prompt.situation -- its title and where, each side's
  players with their portraits (the portrait route), skills,
  modifiers and bands, the roll's target, and the notes for an
  ability from somebody not rolling.
- The log: state.entries, newest last, under minute headings, each
  kind (goal, new play, roll, clock, line) with the edge the page
  gives it; it keeps its place when read back; the whole of it as
  text is the server's /api/room/{id}/log.txt.
- The teams: layout.rosters, a row a player, with the card on hover.
- The references: state.aids' rows (the maneuvers, the roles, the
  species) as tables, its pictures as pictures. They are what the
  engine says this game's mode plays by; the client asks for no
  others.
- The Charter and the Learn to Play are documents, and the server
  already serves them as pages: a Rules button opens the server's own
  /rules in the system's browser (OS.shell_open), and a refusal's
  Law opens it at that Law. Offline that is the local server's page,
  which is why step 3 packed webapp/static and the two books. Drawing
  the Charter inside the game is under "not in these prompts".

Pictures: an outcome over the next question, a shot's situation, a
skill test's, the log after a turnover, the teams, the references;
standard and advanced, three sizes. After this step the Godot game
does for a match everything the page does: say on the PR what, if
anything, it still does not.
```

### 9. The dice

```text
Step 9 of docs/godot/README.md. Steps 1 to 8 have landed.
docs/web-app-next.md, "Later, and not now", is the rule: an animation
is the frontend's to draw, ending on the picture the server rolled,
and never before the service has rolled it.

- The die as a solid: the dodecahedron as a mesh made in code from
  its twenty vertices (d12ball/dice.py holds the same solid), its
  twelve numerals on its faces as a real d12 has them -- opposite
  faces adding to thirteen -- in a transparent 3D viewport over the
  page. One mesh, any colour: state.roll.dice gives each die its
  face, its colour, its halo (an Overdrive) and whether it counts.
- The roll: when a state arrives with a roll the client has not
  shown, each die tumbles and comes to rest with the wire's face up:
  turn the die to the orientation that shows that face, and play
  towards it. No physics decides anything. The lit die a coach
  presses to roll is the same solid at rest.
- The ball and the goal's 12 stay the flat d12 the redesign drew:
  they are marks on a board, and a row of solids on the field is a
  different design.
- How it looks is the author's: one resin die in the colours
  d12ball/dice.py gives its pairs, in both renderers if
  Compatibility cannot carry it (two pictures side by side, and the
  author chooses -- decision 8).
- Reduced motion (step 12's setting, a constant until then): the die
  appears at rest on its face.

A clip in the PR -- the capture tool gains --clip, which runs the
game with Godot's --write-movie over a staged roll -- of a contest, a
shot and an Overdrive. Test: for each of the twelve faces, the
orientation the code turns to puts that face's direction straight up.
```

### 10. Motion

```text
Step 10 of docs/godot/README.md. Steps 1 to 9 have landed.

The wire first, its own commit: the journal keeps the position each
entry stopped at and serves it only as a picture (board.png?entry=).
GET /api/game/{id}/layout?entry=N answers that position as the
layout board.py gives -- the same function, over the entry's own
position, so nothing is worked out twice; an entry's "board" already
says whether it has one. Positions are public: nothing in a layout is
anybody's secret, and the test says which fields it checked.

Then:
- Between two layouts, a piece that is in both moves from where it
  was to where it is; the ball goes with its holder or flies to
  where it lands; a piece that left or arrived fades. The client
  compares two layouts by id and knows nothing about why anything
  moved.
- A cascade is shown in the order it was said: for each new entry
  with a position, move to it, with its lines arriving in the log as
  it does; then the outcome; then the question. The AI's turn and a
  run back read as what they are, a thing at a time.
- It never keeps a coach waiting: a click skips to the end, the next
  question can always be answered, and a state that is already three
  entries behind is caught up at once.
- What kind of movement it is comes only from what the wire says: an
  entry's kind (a goal is a goal) and no table of maneuvers. If a
  pass and a carry should look different and the wire does not say
  which it was, stop and ask: that is the model saying more
  (NarrationGroup's step is already there to be sent).
- Reduced motion: every position simply appears.

Clips in the PR: one whole turn, a run back, a goal. Before the
polish, show the author the first turn moving and build what comes
back.
```

### 11. Sound

```text
Step 11 of docs/godot/README.md. Steps 1 to 10 have landed. Read the
author's answer to question 4 in the worksheet; with none, CC0 sounds.

- Buses for the interface, the game and the crowd; nothing plays
  before the first click.
- What plays is keyed on what the wire says happened and on what the
  player did, never on a rule: an entry's kind (a goal, a new play, a
  roll, the clock), a die coming to rest, a card turned, a piece set
  down, something lit under the pointer, a refusal.
- godot/sounds/README.md: every file, where it came from, its
  licence, and what plays it. Nothing without a row.
- Volume is step 12's setting; until then one constant, and quiet.

Stop: the author plays a half with the sound on and says what stays.
```

### 12. Settings, and coming back to a game

```text
Step 12 of docs/godot/README.md. Steps 1 to 11 have landed.

- Settings, kept under user://: the three volumes, window or full
  screen, the size of the interface, reduced motion (steps 9 and 10
  already obey it).
- Coming back: the game opens on the front door with the room that
  was open named first. A game left in the middle of a turn is
  exactly where it was -- the save is the server's, written before
  the answer came back -- and the test quits the client in the middle
  of a cascade, starts it again and finds the same question.
- When the server is not there: starting, not found, stopped. Each
  says what happened in a sentence and what the game is doing about
  it; the local one is started again and the state read again. The
  server's log is one click away, since it is the first thing anyone
  will be asked for.
- Quitting closes the pipe and waits for the server to go.
```

### 13. Online

Half of this is the author at Cloudflare; the prompt does the
repository's half and writes the checklist.

```text
Step 13 of docs/godot/README.md. Steps 1 to 12 have landed, and
play.d12ball.com is up (docs/design/collaboration.md, "Exposing the
port"). If it is not, stop and say so.

- The front door gains its second address: play online. The client
  asks GET /api/wire first and, where it does not know the number,
  says the game needs updating and plays offline; it never guesses.
- The cookie for that address is who the player is there for a year.
  It is kept under user://, per address, readable by the player
  alone, never written to a log or a report.
- A room by its link: paste a play.d12ball.com room link, or its id,
  and arrive in it as the page would -- seated if a seat is free,
  watching if not. Chat: the room's messages and a line to say one,
  through the room's own route; a message is shown as the characters
  it is, never as runs.
- With somebody in a browser in the other seat, play a game to full
  time, and a rematch.
- Find out from a network that is not the host's own whether
  Cloudflare lets the client through: it sends "GodotEngine/4.7.2..."
  as its User-Agent and is no browser. If it is challenged, the fix
  is a rule at Cloudflare for /api/, /emoji/, /species/ and /fonts/
  -- written into collaboration.md as a checklist for the author --
  and never the client pretending to be a browser.
- docs/design/web-app.md: the server now has readers it did not ship
  with. Write down what that asks of a change to present.py: the
  number, and the three things an old client survives.
```

### 14. Signing and release

```text
Step 14 of docs/godot/README.md. Steps 1 to 13 have landed, and the
author has answered question 1 in the worksheet. Without the answer,
stop.

For wherever it is going:
- macOS: sign every binary in the frozen server from the inside out,
  then the .app, with the hardened runtime; notarize; staple. Godot's
  exporter signs single helper files and not the .so files of a
  folder, so this is a script after the export
  (scripts/sign_godot_macos.sh), run where the author's Developer ID
  is. The checklist for what the author does at Apple goes in the
  design note, in the shape of collaboration.md's tunnel section.
- Windows: unsigned unless the author has bought a certificate; say
  on the PR what a new machine shows, and what Defender says.
- itch.io: butler, a channel a system, pushed from the release
  workflow on a tag.
- Steam, if that is the answer: its own step, written then -- the
  store page, the depots, the Linux runtime, the Deck's checks, and
  the server leaving on its own (a child still running keeps Steam
  showing the game as running).
- The landing page's "Ways to play" gains a card
  (docs/landing-pages.md's rules: the copy is the author's).
- This worksheet is cut down to docs/design/godot.md and its
  CLAUDE.md rows, and goes.
```

## What is not in these prompts, on purpose

- **A port of the rules to GDScript or C#.** Costed under "What was
  found": 32,000 lines, a random number generator reproduced to the
  bit, and every rules change made twice for ever.
- **Python inside the engine.** py4godot and godot-python are not
  ready, and a second process is simpler to start, to stop and to
  sign.
- **A browser export.** The web app is the browser version.
- **Phones.** Online-only when wanted, as its own plan; offline on a
  phone is CPython inside the app behind this same wire.
- **A second protocol, or a socket in place of the poll.** A game of
  D12 Ball is a few clicks a minute and a re-read is always right
  (web-app.md). Measure before changing it.
- **Two coaches at one machine.** Question 3: the wire allows it, and
  it is a curtain and a second cookie, not a rule.
- **A better opponent than Dinky.** A change to the model, for both
  frontends and the bot, and not this plan's.
- **New art.** Larger portraits, a meeple as a solid, a table in
  three dimensions. The field stays flat and the die is the one
  solid.
- **The Charter drawn inside the game.** It opens the server's own
  reading room. Drawing documents natively wants block runs on the
  wire and a text layout of its own.
- **Other languages.** Every sentence is the model's, in English; a
  second language is a change to the model's voice, not to a client.
- **Achievements, cloud saves, a workshop, a launcher.**
- **Discord in any of it.** The bot is its own system and stays one.
- **A test of how anything looks.** The author's rule for everything
  drawn: take the picture and look.

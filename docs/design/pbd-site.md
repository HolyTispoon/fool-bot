# The Codex games on the web

Design notes for fool-bot; the map is [CLAUDE.md](../../CLAUDE.md). The
worksheet this is built from is [docs/pbd-site.md](../pbd-site.md); what a
step settles moves here as it lands.

The site shows every Codex game being played on the Discord, and an archive
of the rest: each game's current board, its log beside it and its history
turn by turn, as the bot pins it. It is its own Cloudflare Pages project,
`codex-pbd.pages.dev`, off the studio's domain because the board is Sirlin
Games' art. The bot uploads to a private R2 bucket; the site's one Pages
Function reads it.

Step 1 landed what the publisher writes, as pure functions with tests,
before anything is uploaded: `cogs/codex_publish/` -- `record.py`, the
publisher's own file; `keys.py`, the bucket's keys; `shapes.py`, the JSON;
`segments.py`, a line as the web draws it.

Step 2 landed how it is sent: `botkit/objectstore.py`, the store (R2, and
a fake for the tests); `cogs/codex_publish/queue.py`, the queue; and
`cogs/codex_publish/config.py`, the `CODEX_PUBLISH_*` variables that turn
it on.

Step 3 landed the hooks: `cogs/codex_publish/publisher.py`, which the
Codex cog builds in `cog_load` and calls from its own methods, so every
change the channel sees reaches the bucket.

Step 4 landed the site: `pbd/`, the Pages project's root -- the two pages,
the viewer and the one Function -- and `scripts/serve_pbd.py`, which serves
it locally.

## What the publisher is, and is not

**The publisher is a frontend, like the cog**, and a second door out of the
same cog: what Discord is shown, the web is shown too. It decides no rule,
words nothing and draws nothing. Nothing under `codex/` or
`gamesaves/codex/` learns it exists.

It is a package the cog calls, not a mixin, because it holds no Discord
state: no message, no channel, no interaction. That keeps it out of the
cog's method resolution order and lets its shapes be tested with no cog
built at all.

It runs only where `CODEX_PUBLISH_*` is set (step 2), the `K:\` checkout
alone, so a developer's test games never reach the live site.

## It reads two things, and nothing secret

The publisher reads **the turn's lines** (`Codex.turn_lines`) and **the
board's bytes** (`render_match_png`). Both are already public: the lines
are the turn message's ([codex.md](codex.md), "What the narration may
say"), and the board is the turn message's picture, which draws only the
counts of the hidden zones and never a tech or stash choice. Everything
secret reaches a player through an ephemeral message, and the publisher
reads none of them -- never a hand, a panel's text, a tech choice, or
`with_turn_log`'s copy of the lines over a hand.

The shapes keep to that: a list entry is the seats' names off the record,
each seat's team by `team_name`, the turn, whose turn it is, and the
winner. A seat's specs are read to name its team, which the turn's
heading already says in public.

## The bucket's layout

Every key is under `codex/` in the bucket `pbd`, and `cogs/codex_publish/keys.py`
builds each of them; nothing else spells one.

| Key | Written by | What |
| --- | --- | --- |
| `codex/index.json` | `shapes.index` over `index_entry` | The games being played, newest activity first |
| `codex/archive.json` | `shapes.archive` over `archive_entry` | Two sections, `finished` and `abandoned`, each newest first: the same fields, `status` and `winner` |
| `codex/games/<id>/live.json` | `shapes.live` | The game as the lists name it, the current turn's `heading` and `lines`, the current `board`'s key, `history_version` and the history's key |
| `codex/games/<id>/history.json` | `shapes.history` | `version`, and `turns`: one entry per finished turn -- `turn`, `heading`, `lines`, `board` |
| `codex/games/<id>/board-<sha256>.webp` | `keys.board_key` | A board |
| `codex/emoji/<name>.png` | `keys.emoji_key` | A glyph's picture, by its file's name under `codex/images/emoji/` |

- **A key in the JSON is the whole key**, `codex/` included, so the page
  fetches `/data/` plus what it was handed and builds no key of its own.
  The Function's patterns (step 4) are then the one other place a key's
  shape is written, and step 4's test holds the two together.
- **`<id>` is the game's `game_id`, never its number.** `game_number` is
  counted per guild and taken again after `/codex admin reset_channels`;
  the uuid4 hex is the only key never reused.
- **Whose turn is a list** (`turn_seats`): a two-headed dragon's turn is
  both teammates'. A list entry also carries `sides` -- a dragon's two
  teams, every other game's seats one a side -- so the page can say "ann
  and bo against cy and di" without knowing the variants.
- **Only a game that started is on the site** (`shapes.on_site`; the
  author, 2026-10-16). A lobby is not listed, and a game abandoned in its
  lobby was never on the site, so it is not archived: it has no board and
  no turn to show, and an archive of lobbies nobody played would bury the
  games that were. A game abandoned after its Start is archived.
- **The archive is two sections, `finished` and `abandoned`** (the
  author, 2026-10-16: "a finished game needs to go a finished games
  section in the archive"). A game played out is read for how it was
  won; an abandoned one has no ending to read. The split is made here,
  not in the page, so the page builds no reading of a status of its own.
  A finished game's page is the same shape as any other: its last turn
  is its current turn, with the final board, and the turns before it its
  history.
- **`winner` is a list of seats, or `null`**: one seat, a dragon's two
  (`seats.dragon_of`), and `null` for an abandoned game.
- **`history.json` is an object, not a bare list**, so it carries its
  `version` beside its turns and the page can tell the copy it holds from
  the one `live.json` names.
- **A history entry passes through any field it carries** besides the
  four, so a later per-action history adds one rather than changing the
  shape (the worksheet's decision 5).

### Why a board is named by its hash

A board's key is its bytes' SHA-256. The same picture is then the same key
whenever it is drawn -- `render_match_png` hands back the last drawing's
bytes when nothing moved, and an undo can return to a board already up --
so the record's list of uploaded keys says whether to upload at all, with
no listing of the bucket. A key names one picture for good, so it is served
`immutable` for a year and a browser never asks for it twice, and a key
cannot be guessed, so nothing is reached that a page does not link to.

## A line is segments, not HTML

The model's lines carry tokens (`codex/tokens.py`), and every frontend
draws them at its own door: `CodexTokens` for Discord, `plain_text` for a
label, and now `segments.segments` for the web. A line becomes a list of
segments:

| Token | Segment |
| --- | --- |
| text between tokens | `{"text": ...}` |
| `{player:n}`, `{to:n}` | `{"player": n, "name": ...}` -- `seat_label`, the record's name or "Player n" |
| `{card:slug}` | `{"card": slug, "name": ...}` |
| `{hero:slug}` | `{"card": slug, "name": ..., "hero": true}` |
| `{gold:n}` | `{"glyph": "gold", "n": n, "key": ..., "alt": "n gold"}` |
| `{exhaust}`, `{target}`, `{codex}` | `{"glyph": kind, "key": ..., "alt": ...}` |
| `{arrow}` | text, `->`, as on Discord |

and Discord's `**bold**` and `*italic*` become `"bold": true` and
`"italic": true` on every segment inside them.

- **The page builds every line with `textContent`**, so nothing in a line
  is ever markup. A display name is a segment's `name`, filled in after the
  line's emphasis is read, so a name holding `<` or `**` is text and
  cannot open a tag or turn the rest of the line bold.
- **A mention is a name on the web.** `{to:n}` is a ping on Discord; on a
  page anyone with the link can read, it is the seat's name, and no
  Discord id is written anywhere.
- **A glyph carries its picture's key.** The token-to-file map is
  `TOKEN_EMOJI` in `cogs/codex_helpers.py` -- `exhaust`'s file is
  `codex_exhaust.png`, since `exhaust` is D12 Ball's -- and the segment
  carries the key, so the page holds no second copy of the map.
- **A card carries its slug**, so a later step can show the card's picture
  on hover without changing the JSON.
- **The tokens are found by `codex.tokens.render`**, as `CodexTokens` finds
  them, never by a pattern of the publisher's: each token is held as a
  placeholder while the emphasis is read, then becomes its segment. The
  emphasis is paired in order, `**` with `**` and `*` with `*`; a marker
  left over is a literal asterisk.

## The log is the publisher's file, not the game's

The turn's lines live in memory alone (`Codex.turn_lines`), and a finished
turn's only in its pinned message, folded to Discord's 2000 characters. The
site needs both whole, so the publisher keeps its own record,
`data/codex_pbd.json` (`PublishRecord`), keyed by `game_id`: per game the
current turn's number, heading and lines, the history, the current board's
key, the board keys already up, the history's version, whether the import
from the pins has run, and when it last changed. **The bucket is the copy;
the file is the source**: a restart loses neither the log nor the record of
what is up, so nothing is uploaded twice.

It is not the games file, and not a field on the match, for three reasons.
The save format is the contract (CLAUDE.md, principle 6), and a log is not
the game: nothing in the rules reads it. The games file is written by
`GameService` once per click, and the publisher must never fail or delay a
turn. And the publisher runs on one checkout alone, so a field it alone
fills would sit empty on every other.

The lines are kept with their tokens intact, as the model said them, and
resolved into segments only when the JSON is written: a name read off the
record at that moment, the card's name off the catalog.

The file's handling is `gamekit.storage`'s, as both games files' is: the
temporary file renamed over the real one, a save that never raises, and the
two failure flags -- here `record.py`'s own -- so a file that was there but
could not be read is never written over. Nothing makes `data/` on a load. A
game's entry is `PublishedGame`, a small class with `to_dict` and
`from_dict`, because `save_games` calls `to_dict` on every value; its
`from_dict` reads every field with its default where it is missing or the
wrong shape, so a hand-edited entry loads as much as it holds.

## The store

`botkit/objectstore.py` is a store with two calls, `put(key, body,
content_type, cache_control)` and `delete(key)`, both `async`, both raising
on a failure. Nothing reads or lists: the publisher's record says what is
up, so the bot never needs to ask the bucket.

- **`R2Store` is R2 over its S3 API, through boto3**, pinned in
  `requirements.txt`. boto3 blocks, so every call runs in
  `asyncio.to_thread`. It is imported in the constructor, never at module
  level, so a checkout without it imports everything and runs with the
  publisher off. The client asks for a checksum only where an operation
  requires one (`request_checksum_calculation="when_required"`): botocore
  1.36 began sending one on every request, and R2 is S3-compatible rather
  than S3. That is a precaution, not a measured failure; nothing in this
  repository has talked to R2 yet (step 5).
- **`MemoryStore` is the tests'**: the objects in a dict, every call in
  order, failures on demand, and a gate that holds a call in flight.
- **In `botkit/`, not the publisher's package**, because nothing in it
  knows Codex: a D12 Ball publisher would take the same store.

**A delete costs nothing.** R2's pricing page, read 2026-10-16: "Free
operations include `DeleteObject`, `DeleteBucket` and
`AbortMultipartUpload`" (<https://developers.cloudflare.com/r2/pricing/>).
So deleting the boards the game has moved past is free, and keeps the
bucket at the worksheet's 15 to 20 MB a game ("What it costs").

## The queue

`PublishQueue` (`cogs/codex_publish/queue.py`) takes **a change as a flag,
not a payload**: the caller changes `PublishRecord`, then names the game
(`game_changed(game_id, boards)`), handing over the bytes of any board the
change named, since the record keeps only keys. The queue builds the JSON
from the record when it sends. A burst of changes is one upload, and the
newest state is always the one sent, with no pending payload to merge.

**Per game, one send in flight**, a task a game while there is something
to send. A change during a send is sent after it. Everything a send puts
is built before its first `await`, so a change made while it is in flight
goes whole into the next send rather than half into this one.

**The order is the page's guarantee** (decision 9). A send puts every board
the JSON names that is not up yet -- the current board, then any the history
keeps -- then `history.json`, then `live.json`, and a failed put stops the
send before anything that would name what failed. A poll that lands between
two puts then never names an object that is not there.

- **A board goes up once.** The record's `uploaded` is what is there; it
  is changed only after a put or a delete succeeds, and the record is
  saved when it changes. A restart uploads nothing twice.
- **A board nothing names is deleted**, after the `live.json` that stopped
  naming it is up: what is named is the current board and every board the
  history keeps, at the send and in the record as it is now (a change
  waiting to be sent would only put the board back). This is the
  "What it costs" rule with no special case: a board replaced as current
  goes unless a turn ended on it, a turn's board dropped by an undo to the
  previous turn goes unless it is current again, and a delete that failed
  is tried again on the next send. An undo back to a deleted board puts it
  up again, since every change hands over the current board's bytes.
- **The JSON goes up only when it changed** from what this process last
  put under that key, by digest. That keeps an unchanged `history.json`
  off every action without a version check, and a restart puts each once.
- **A board the JSON needs and the queue does not have** -- a current
  board neither up nor handed over, which only a failed upload before a
  restart leaves -- holds the game's send, with a WARNING, until a change
  hands it over: the site keeps the older board with the older lines
  rather than naming a picture that is not there. A history board in the
  same state is sent without it, with a WARNING, since nothing would ever
  hand it over again.
- **A lobby, and a game the record has no entry for, send nothing**
  (`shapes.on_site`).

**`index.json` and `archive.json` have one queue of their own**
(`lists_changed()`), rebuilt from the games and the record when sent:
every game changes them, and two games' sends finishing out of order
would otherwise put back the older list. One task, so the last list put
is the newest. The lists are built from the bot's games, not from the
record, so a game that started before the publisher saw it is listed
anyway. A match is read off its record once per saved state: the record's
`match_state` dict is replaced on every save, so the queue keeps the dict
it read and compares by identity.

**Nothing raises out of it.** A failed call is a WARNING (console-only)
and is retried with the next change: the boards a failed send held are
kept for it. A **run** of failures -- `FAILURE_RUN` (ten) in a row, or a
run older than `FAILURE_WINDOW` (five minutes), whichever comes first --
is one ERROR, which reaches #logs because somebody must act: a revoked
token or a deleted bucket fails every call from then on, and a WARNING on
a console nobody watches would leave the site stale for good. A success
resets the run, and says so at INFO if the ERROR had been logged. The run
is counted across the whole queue, since one bucket and one token serve
every game.

**`close()`** takes nothing new and cancels what is in flight, for the
cog's unload. A put already handed to its thread finishes there; the
record says only what was confirmed, so the next start sends the rest.

## Turning it on

`cogs/codex_publish/config.py`'s `store_from_env` reads the `.env` once,
as the cog loads: `CODEX_PUBLISH_ACCOUNT_ID`, `CODEX_PUBLISH_ACCESS_KEY_ID`,
`CODEX_PUBLISH_SECRET_ACCESS_KEY` and `CODEX_PUBLISH_BUCKET` (default
`pbd`). With any of the first three missing, or boto3 not installed, the
publisher is off and says so once at INFO. They are a credential, in the
`.env` of the `K:\` checkout alone ([collaboration.md](collaboration.md),
"The Codex bot"), so a developer's test games never reach the live site.

## The hooks

`Publisher` (`cogs/codex_publish/publisher.py`) is built in the cog's
`cog_load` where `store_from_env` hands back a store, and is `None`
everywhere else; every call site reads `if self.publisher is not None`.
It is called from the cog's own methods and **never from
`BoardRefresher`**, which D12 Ball shares and which the Codex cog does
not send every turn message through (the worksheet's "What was found").

| Cog method | Hook | What the site gets |
| --- | --- | --- |
| `refresh_match_image` | `current` | The turn's lines now, and the board drawn: every action, an undo within the turn, **Swap view**, `/codex side_by_side` |
| `post_turn_message` | `current`, with the bytes posted | The turn current: the game's start, a turn's end, an undo to the previous turn, `/codex resume`, **Show board** |
| `roll_over` | `turn_ended`, with the bytes the standing message carries | The ended turn's history entry: its lines and the closing lines whole, its heading, its board -- never a second drawing |
| `_previous_turn_back` | `previous_turn_back` | The restored turn's entry, and any after it, dropped; the history's version counted up |
| `_own_undo` | `turn_undone` | The lines back to the turn's head (below) |
| `note_turn_head` | `head_noted` | The turn's head, kept in the record's `head` |
| `finish_game`, `abandon_command` | `game_over` | The last lines and board, and the game moved to `archive.json` |
| `reset_channels` | `dropped` | The dropped games off the record and both lists, then their objects deleted |

Start needs no hook of its own: its first turn message goes through
`post_turn_message`, which lists the game.

**A hook changes the record at once and awaits nothing.** The turn's
lines are the cog's at the moment of the call -- `finish_game` and the
abandon forget them a line later, and `roll_over` replaces them -- so
they are read then. Drawing a board where the hook had none, saving the
record and naming the game to the queue are the game's own task, one a
game, so a burst of hooks is one save and one send. A board drawn for a
change a newer one overtook is dropped: a post that handed over its
bytes while a drawing was under way keeps its board current. Every hook
is wrapped, so a bug in it is logged and never reaches the click.

**The board is `render_match_png`'s**, the same call the gate makes, so
an action's board is the drawing the gate made or is about to make, and
the cache (`boards_drawn`) keeps it one drawing. Where the cog hands
bytes over -- a post, a turn's end, the game's end -- nothing is drawn.

**`updated` moves only when what the site shows moves**: the turn, its
heading, its lines or its board. **Show board** posts the same board and
lines again, so it changes nothing on the site and writes nothing.

### The lines after a restart

`Codex.turn_lines` is in memory, so a restarted process has not seen the
current turn's lines. Until it says something more of the turn, the site
keeps the record's lines, as the gate keeps the message's text
(`turn_text_or_none`). When it does -- an action re-armed by the
restart, or `/codex resume`, which resets `turn_lines` to nothing or the
opening lines -- the cog's lines are only the end of the turn. So the
publisher starts with every game's record lines **carried** for that
turn, and the site's lines are the carried lines followed by
`turn_lines`, never `turn_lines` alone, until the turn ends.

An undo within the turn sets `turn_lines` to the turn's head and what
the undo said. The head is the cog's `turn_heads`, also in memory, so the
record keeps its own copy (`PublishedGame.head`), and remembers what it
carried when the head was noted: after an undo, the site's lines are
that carried part, then `turn_lines`. An undo to the previous turn takes
the restored turn's head from the cog where it has it; after a restart
it does not, and the site shows what Discord shows.

A turn that ends with no `roll_over` -- `/codex resume` running the end
the bot owed at the restart -- is noticed by the next `current`, whose
turn is past the record's: the record's turn, as it stood, becomes its
history entry, with the last board the site had for it.

### Startup

`cog_load` starts a task, since the views are re-armed in `__init__` and
a click may land before it is done. It puts the four glyphs' pictures,
then gives every game the site does not have a board for one: a game
being played the record never saw, or whose board did not go up before
the restart; and a finished or abandoned game that started and the
record has no entry for, with its last board and no `updated`, so it
sorts below the games the site saw end. A game whose current board is up
is not drawn: the next change sends a new one. Then both lists.

**The glyphs go up once a start**, not once ever: four small pictures,
four writes a restart, and the record holds games and nothing else. The
queue's own digest keeps them from going up twice in one process.

### What a reset deletes

`/codex admin reset_channels` drops games through neither ending, so it
has a hook of its own: the games come off the record and so off both
lists, and then **out of the bucket** -- every board the record had up,
`live.json` and `history.json` (the author, 2026-10-16). The deletes run
on the lists' queue, after both lists without the games are up, so no
list ever links to a game whose objects are gone. A delete that fails is
tried again with the lists' next change; deletes cost nothing ("The
store"). A game's send still in flight is cancelled first, and its
record entry is gone, so nothing puts it back.

## The page

`pbd/` is the Pages project's root (the worksheet's decision 1), and nothing
under it is built: Pages serves `pbd/public/` as it stands and finds
`pbd/functions/`. Plain HTML, CSS and JavaScript, no framework, no CDN and no
web font -- the system's sans -- because the landing pages' reason holds
here too ([landing-pages.md](landing-pages.md), "Python and plain HTML, no
framework") and a page anyone can open should call no other host.

- **`index.html`** is the games being played, then the archive in its two
  sections, finished and abandoned, from `index.json` and `archive.json`,
  read every minute while the tab is visible. Each entry names the game's
  number, its mode and variant, the sides ("ann vs bo vs cy", a dragon's
  "ann and bo vs cy and di", off `sides`), and where it stands: whose turn,
  who won, or the turn it was abandoned on.
- **`game.html`** is one game at `/game/<game_id>`: `_redirects` rewrites
  the address onto `/game` with a 200, and the page reads the id off
  `location.pathname`. Pages serves `game.html` at `/game` and redirects
  the `.html` name there, which is why the rewrite names `/game`. Every
  file is named by absolute path, so a trailing slash breaks nothing.
- **The board fills what the log leaves**, in the viewer; the log is a
  column beside it, which **Hide log** takes away, remembered in
  `localStorage` (wrapped, so a browser that refuses storage shows the log).
  The column is the current turn's heading and lines, then the earlier
  turns newest first, each its heading, its lines and its board as a
  thumbnail that opens in the viewer under a caption with **Back to the
  current board**. While an old board is open, a new current board is
  neither fetched nor swapped in until **Back to the current board**.
- **Polling** is `live.json` every 15 seconds while the tab is visible,
  stopped while it is hidden and taken up again when it shows; the board is
  fetched only when its key changes, and `history.json` only when
  `history_version` does. A game that is no longer `playing` says how it
  ended and stops polling. A `404` is not final: the lists are on a queue
  of their own, so `index.json` can name a game before its first
  `live.json` is up, and a deploy can miss a poll -- the page says the game
  is not on the site yet and keeps asking. The browser revalidates the JSON with its
  `ETag` on its own, since the objects are `no-cache`.
- **Every line is built with `textContent`** from its segments (`codex.js`,
  `segmentNode`): a name, a card and a glyph each a node, bold and italic
  wrapped round whatever segment carries the flag. A glyph is its picture
  with its `alt`, and its word where the picture does not load. No file
  under `pbd/public/` uses `innerHTML` (the test).
- **What a mode and a variant are called** is a copy in `codex.js` of
  `cogs/codex_views/lobby.py`'s `MODE_LABELS` and `codex/game.py`'s
  `VARIANT_LABELS`, held to both by the test: five words are not worth a
  field in every list entry. A free-for-all's seats are joined with ", ",
  a duel's and a dragon's sides with " vs ", as `/codex games` joins them.
- **The look is the night palette's values**, typed into `codex.css`'s
  `:root` from `box_art.NIGHT_COVER`: this is not the landing build, so it
  borrows the values rather than the generated `colours.css`.
- **On a phone, and a tablet held upright** (at most 960px wide), the board
  is on top and the log under it, the page scrolling. The viewer is as tall
  as the board at the screen's width (`--board-aspect`, set by the viewer
  when a board loads) and never taller than the screen, so a stacked board
  does not sit in black bands.

### The viewer

`viewer.js`, `BoardViewer`, is decision 6 by hand: pointer events and a CSS
transform on the picture. The wheel (a trackpad's pinch is a wheel with
`ctrlKey`) and a two-finger pinch zoom toward the pointer; a drag pans; a
double click or a double tap switches between fit and full size about the
point (never one on a button, so a fast **+ +** is two zooms); the **-**, **Fit** and **+** buttons and the `+`, `-` and `0` keys do
the same. The zoom runs from the smaller of fit and full size to twice
full size or the fit, whichever is larger: the picture's own pixels are the
limit. A board narrower than the frame sits in its middle; a wider one
cannot be dragged past its edge.

**A new board keeps the viewer's zoom and position** where it is as wide as
the one it replaces and the viewer is not fitted; a fitted viewer stays
fitted. Only the width is compared: a board's height moves with what is on
the table (a row of units more, measured 1986 against 2362 pixels in one
staged game), and refitting on that would throw the viewer's zoom away most
turns. A new width is **Swap view** between stacked and side by side, a new
picture, and is fitted afresh. The new picture is loaded off screen and
swapped in whole, so the viewer never shows half a board; one that fails
to load is asked for again on the next poll.

### The Function

`pbd/functions/data/[[path]].js` answers `GET` and `HEAD` under `/data/`
and nothing else (a `405` otherwise). The key is the address after `/data/`
as written -- `codex/` included, since the JSON carries whole keys -- and is
answered only where it matches one of `KEYS`, six regex literals at the top
of the file: the two lists, a game's `live.json` and `history.json` under a
32-character lowercase hex id, a board under a 64-character hex hash, and a
glyph named by letters, digits and underscores. Anything else is a `404`
before the bucket is asked, so the bucket cannot be walked. The patterns
allow no character a browser encodes, so nothing is decoded first, and no
`..` can reach a key the publisher did not write.

It reads with `env.PBD.get(key, {onlyIf: request.headers})` (a `HEAD` with
`head`), passes the object's own metadata through (`writeHttpMetadata`: the
`Content-Type` and `Cache-Control` the publisher put it with) and its
`httpEtag`, and answers `304` where the `If-None-Match` matched -- a get
whose precondition fails hands back the object without a body. Every
answer, a `404` included, carries `X-Robots-Tag: noindex`.
`_routes.json` sends only `/data/*` to it, so the static files never count
against the Functions quota. It has been run against a fake binding only;
step 5 is the first time it meets R2.

**The patterns are the one other place a key's shape is written**, beside
`keys.py`. `tests/test_pbd_site.py` reads them out of the `.js` (each a
plain literal on a line of its own, which compiles as a Python regex) and
holds every key `keys.py` writes to one of them and a list of near misses
to none. A pattern is matched with `fullmatch` there, because Python's `$`
also matches before a final newline and JavaScript's does not.

### Looking at it

`scripts/serve_pbd.py` serves the site as Pages would: `pbd/public/` with
its rewrite and its `_headers`, and `/data/` from a folder in the bucket's
layout (`--data <dir>`), refusing every key the Function refuses -- it reads
the same patterns out of the same file. `--stage <dir>` first writes a
sample there through the publisher's own shapes and `codex.render`'s boards:
a duel being played with three turns behind it and a seat whose name holds
markup, a free-for-all finished, and a duel abandoned. Nothing in it talks
to Cloudflare or writes into `data/`.

The page is looked at in a browser at desktop (1440x900), iPad on its side
(1180x820, touch) and phone (390x844, touch), the log open and closed,
zoomed in and fitted, and with an old turn's board open; the test does not
see it.

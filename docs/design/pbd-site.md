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

After the steps, the free plan: `cogs/codex_publish/budget.py`, the
bucket measured and reported against R2's free plan at every start, and
the games taken off the site -- downloaded first -- once it nears the
free storage ("The free plan").

Step 6 landed the old turns: `cogs/codex_publish/pins.py`, a pinned turn
read back into the model's tokens, and the publisher's import after its
startup publish, so a game played before the site went live has its
history from its channel's pins.

After the steps, a card on hover: the board's map -- where each card is
on a board, from `codex/render.py` (`render_board_mapped`) -- uploaded
beside the board, every card's picture uploaded once
(`cogs/codex_publish/cards.py`), and `pbd/public/preview.js`, which shows
a card named in the log on hover and, with Space, the card or the tech
building's codex under the mouse on the board ("The board's map", "The
cards' pictures", "Showing a card").

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
| `codex/games/<id>/board-<sha256>.json` | `keys.board_map_key`, `shapes.board_map` | The board's map, by the board's own hash: where each card is on it ("The board's map") |
| `codex/emoji/<name>.png` | `keys.emoji_key` | A glyph's picture, by its file's name under `codex/images/emoji/` |
| `codex/cards/<slug>.jpg` or `.png` | `keys.card_key`, `cards.key` | A card's picture, the file the board draws it from ("The cards' pictures") |

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

### The board's map

**A board's map says where its cards are**: `codex.render.render_board_mapped`
draws the board and hands back, beside its bytes, a box in the picture's
pixels for every card it shows face up -- a hero on the field or in the
command zone, a unit, a building card or upgrade, a card in the future,
a patroller, an add-on -- with the card's slug (the face it shows: a
Squirrel's under Polymorph), and a box for each tech building with the
codex cards it opens: **Tech I**, the tech I cards of every spec the
player has; **Tech II and III**, the whole codex of the spec chosen at
Tech II, or the basic game's one spec, which nobody chooses (UMR pp.
8-9); none for a Tech II whose spec is not chosen yet. **In a basic
game's duel every building opens the one spec's whole codex**, Tech I
too (the author, 2026-10-18): one spec a side, so the whole codex is
what a player wants to read. Elsewhere Tech I's list leaves the spells
out (the author, 2026-10-18) -- a spell prints no tech level -- so it is
the units and buildings printed tech I, two a spec in every spec today.

- **The boxes are carried, never worked out again.** A part drawn on its
  own marks its boxes on the picture (`render.mark`), and every paste and
  turn the board is composed by -- `place`, `turned_round` -- carries
  them, so the far panel's turned boxes and a dragon's reversed row come
  out right by construction rather than from a second copy of the
  layout's numbers. Only a picture drawn afresh is marked; a cached one
  never is. **The pixels are the same with or without it**: the sample
  script's 55 pictures were byte-identical before and after (SHA-256).
- **It is named by the board's hash** (`keys.board_map_key`): the same
  drawing is the same map, so it is `immutable` like the board, goes up
  once, and is deleted with the board.
- **The cog keeps the maps of the boards it drew lately** (`Codex.board_map`,
  by the bytes' SHA-256, `BOARD_MAPS_KEPT`), and the publisher takes a
  board's map **as the board is handed over** (`Publisher._take_maps`),
  while the cog still holds it. A board read back off a pin has none, so
  an imported turn has no hover; nor does a board that went up before this
  change, until the game's next one.
- **The queue puts a map right after its board** and before the JSON, and
  `live.json` and a history entry name it (`board_map`) only once it is up
  or goes up in the same send -- otherwise `null`, and the page shows no
  card for that board.
- **It shows nothing secret.** A box is a card the board already shows,
  and a tech building's codex is the spec's printed cards
  (`CardCatalog.by_spec`), never what is left in a player's own codex or
  what they teched.

### The cards' pictures

**Every card's picture is in the bucket once**, under `codex/cards/`: the
file the board draws it from (`Card.picture`, `Hero.picture`) -- the
database's art as `.jpg`, the module's tokens, buildings and worker cards as `.png` --
330 and 32 files, about 39 MB, under 0.4% of the free storage. The startup
puts each one the start's listing of the bucket lacks at its size
(`Publisher._put_cards`), so the art goes up at the first start after this
change and not again; where the listing failed, every one is put, 362
writes. They are cached a day, as the glyphs are, since the art may be
imported again. `cogs/codex_publish/cards.py` is the one place a card's
picture and key are read: a line's card, a map's card and a codex's all
carry the same key.

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
| `{card:slug}` | `{"card": slug, "name": ..., "key": ...}` |
| `{hero:slug}` | `{"card": slug, "name": ..., "hero": true, "key": ...}` |
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
- **A card carries its slug and its picture's key** (`cards.key`), so the
  page shows the picture on hover and builds no key of its own; a card
  with no picture on disk has no `key`, and the page shows its name.
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

`botkit/objectstore.py` is a store with `put(key, body, content_type,
cache_control)` and `delete(key)`, and -- for the free plan alone --
`list(prefix)`, every key and its size, and `get(key)`, an object's bytes;
all `async`, all raising on a failure. Publishing never reads or lists:
the publisher's record says what is up. The one listing is the start's,
which measures the bucket, and the gets are a game being downloaded
before it comes off the site ("The free plan").

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

## The free plan

The bucket has to stay inside R2's free plan (the author, 2026-10-17:
"I want to make sure we never exceed the limits of the free plan on
R2"). Cloudflare's pricing page, read 2026-10-17, gives 10 GB-month of
Standard storage, 1 million Class A operations (a put, a listing) and 10
million Class B operations (a get, a head) a month; a delete is free.
`cogs/codex_publish/budget.py` holds those numbers and what the bot does
about them.

**Every start says what the bucket uses, in #logs.** The startup task
lists the bucket first -- the whole bucket, not `codex/` alone, since the
allowance counts everything in it -- and once the startup publish has
settled, `budget.report` goes out through `botlog.post_notice` (and at
INFO on the console): the storage against the free 10 GB with the share
and the object count, the month's writes against the free million, and
why the reads are not counted. It is a notice and not an ERROR, since a
report is not something to fix; like every notice it reaches #logs only
where `CODEX_LOG_MIRROR` (or `FOOLBOT_LOG_MIRROR`) is on.

- **Storage is measured, not estimated.** One listing gives every key's
  size (`Usage.listed`); after it, every put sets its key's size and every
  delete takes it away, so the meter follows the bucket between starts
  with no further listing. A GB is taken as 10^9 bytes, the smaller
  reading, because the page does not say which. The storage is billed on
  the month's average of each day's peak, which the current size bounds
  as long as it never passes the mark.
- **Writes are counted by the bot**, since it is the bucket's one writer
  (the site's Function only reads): every put tried, a failed one too --
  the count that never undercounts -- and each listing as a write per
  thousand keys (`list_pages`, S3's page). The count is kept in
  `data/codex_pbd_usage.json` with its month, `YYYY-MM` in UTC, and starts
  again at zero when the month changes. Boto3's own retries are not seen,
  so it is a floor in a run of failures. At `WRITES_ALARM` (80%) of the
  free million it is one ERROR: taking games off frees storage, not
  writes, so somebody has to decide. At two or three writes an action,
  that is several hundred games in a month.
- **Reads are not counted here**, because every one goes through the
  Pages Function, and the Workers free plan stops that at 100,000
  requests a day -- at most about 3.1 million a month, under the free 10
  million, as long as the account is on that plan.

**Near the free storage, games come off the site, downloaded first.**
From `OFFLOAD_AT` (80%, 8 GB) the publisher takes games off until the
bucket is down to `OFFLOAD_TO` (70%, 7 GB): a margin, so one offload is
not followed by another a game later. At 15 to 20 MB a game, that is
about 50 games taken off at a time, after about 400 on the site.

- **The order is the author's**: the abandoned games first, then the
  finished ones (`OFFLOAD_ORDER`), each the longest untouched first by
  its `updated` -- a game the site never saw change, with none, before
  any. **A game being played never comes off.** Where nothing finished or
  abandoned is left and the bucket is still past the mark, that is one
  ERROR, said again only after an offload succeeds.
- **A game is downloaded whole before anything of it is deleted**: every
  key the listing has under `codex/games/<id>/` -- the bucket's word, not
  the record's, so nothing is left behind -- each checked against its
  listed size, written into `data/codex_pbd_offloaded/` in the bucket's
  layout. A failed download or write leaves the game on the site. The
  folder serves as it stands: `python3 scripts/serve_pbd.py --data
  data/codex_pbd_offloaded` opens a game at `/game/<game_id>`, though the
  lists there are not written.
- **Then it is marked, listed nowhere, and deleted**:
  `PublishedGame.offloaded` is set and the record saved, so the queue
  leaves it off both lists and never sends it again, and the hooks pass
  it by; its keys go through `games_dropped`, the reset's path, so they
  are deleted only after the lists without it are up. A delete that
  failed is retried with the lists' next change, and at the next start,
  which finds the game's keys in its listing and deletes them again (it
  was downloaded before it was marked). What is on its way out is not
  counted towards taking more off (`budget.leaving`).
- **When it is checked**: once at the start, after the report -- nothing
  comes off before the report has said what the bucket holds -- and
  after every put that succeeded (`PublishQueue.grown`), which costs a
  comparison while the bucket is under the mark. One offload at a time.
  What came off is one notice in #logs: how many, how much, which games
  by number, and any whose download failed.
- **Only this bucket is seen.** The token is scoped to `pbd`, so another
  bucket on the account, which shares the allowance, is not in the
  meter. There is none today.

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

**The turn message links the game's page**: **View live board**, a link
button on `TurnMessageView` to `keys.game_page` (`/game/<game_id>` on
`keys.SITE`), beside the full-image link the gate puts after it. It is
there only where `cog.publisher` is set, since elsewhere the page would
not follow the game, and it rides on the view the gate keeps, so it costs
no request of its own. The finished turns' pins lose their buttons as
before, and the link with them.

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
a click may land before it is done. It puts the four glyphs' pictures and
whichever cards' pictures the bucket lacks ("The cards' pictures"), then
gives every game the site does not have a board for one: a game
being played the record never saw, or whose board did not go up before
the restart; and a finished or abandoned game that started and the
record has no entry for, with its last board and no `updated`, so it
sorts below the games the site saw end. A game whose current board is up
is not drawn: the next change sends a new one. Then both lists, and then,
once the games' sends and the queue are idle, the old turns' import
(below).

**The glyphs go up once a start**, not once ever: four small pictures,
four writes a restart, and the record holds games and nothing else. The
queue's own digest keeps them from going up twice in one process.

### The old turns

A game played before the site went live -- one still being played, and
every finished or abandoned game in **Codex Archive** -- has its finished
turns in its channel's pins and nowhere else (decision 10). So the
startup task, after the startup publish, imports them once a game:
`PublishedGame.imported` says whether it has run, and a second start
lists nothing.

- **Every started game the bot has**, not only the ones the record
  already had: the startup publish has just given each an entry with
  its current turn.
- **One listing per channel**, for every game in it -- a Rematch's
  earlier game, or several games in one `here` channel -- one channel at
  a time, after `wait_until_ready`, since the task starts in `cog_load`
  before the cache is filled. A channel the cache does not have -- an
  archived thread -- is fetched first. Pins come 50 to a request
  (`PIN_PAGE`, Discord's cap on the endpoint), paged by `pinned_at`.
- **A pin is the game's by its board's file name and its author**:
  the bot's own message carrying `codex-<number>-board.webp` exactly
  (`pins.board_of`), never the prefix alone, which starts every
  ephemeral picture's name too; and the text's first line is a turn's
  heading, "**Turn n**". A turn pinned twice -- undone to and played
  again, its first pin deleted with its message on Discord but not if
  the delete failed -- is its later pin.
- **Only the turns before the earliest the record holds** -- its
  history's first, or the current turn -- are written, before the
  history, and the bound is read again once the boards are downloaded,
  since a turn may end meanwhile. A finished game's last turn is pinned
  too, and is the record's current turn, so it is not imported twice.
  A turn past Discord's pin cap was never pinned and is not there: the
  history starts where the pins do.
- **The text is read back into the model's tokens** (`pins.as_tokens`),
  so the history's lines go through `segments` as every other line
  does: a mention becomes `{to:n}` for the seat its user holds -- the
  seat's name on the web, never `<@id>` -- a glyph's emoji its token,
  `{gold:n}` with the amount after it, and a hero's emoji with the bold
  name after it `{hero:slug}`. What Discord drew as plain text stays
  text: a `{player:n}` is already the seat's name, and a card is its
  bold name, since the catalog is read by slug and never by name. A
  turn folded at 2000 characters keeps its "*and n more*": what was
  folded is not there to read.
- **Each board is downloaded** and handed to the game's task as any
  other board is, so the queue puts it before the `history.json` that
  names it. A board that fails to download leaves the game's import
  undone, for the next start, rather than a history with a hole in it.
- **A channel that is gone, or that the bot may not read** (`NotFound`,
  `Forbidden`), marks the import done with nothing imported, for good
  (the author, 2026-10-17): no later start would find more, and a
  `here` game in a channel the bot may not read the pins of is not
  worth a request every start. Any other failure leaves it for the next
  start.
- **The requests are counted** -- the fetch, each listing, each download
  -- and said once a channel at INFO, with the turns imported.

These are the only Discord requests the publisher makes. A listing and a
download are reads, on routes of their own, never the messages' edit
bucket ([rate-limits.md](rate-limits.md)), and they run at startup
behind the queue, never during a click.

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
  current board**. **The divider between the board and the log is
  dragged** to set the log's width (`GamePage.splitter`), by mouse or
  finger -- its grip is wider under a coarse pointer -- or with the arrow
  keys once focused, and double-clicked to put the width back. The width
  is remembered in `localStorage` beside the toggle, and the log keeps at
  least 240px while leaving the board at least 240px, a remembered width
  given way to as the window narrows (`max-width` in `codex.css`). The
  viewer watches its own size, so a fitted board refits as it is dragged.
  The divider is not there in the stacked layout below, where the log is
  under the board. While an old board is open, a new current board is
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
- **A card is shown on demand** (`preview.js`, `CardPreview`; "Showing a
  card" below).
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

### Showing a card

`preview.js`'s `CardPreview` is one floating box beside the pointer, built
from image sources and `textContent`: one card large, or a codex as a grid
of six (four on a phone) under its title, kept inside the window.

- **In the log**, a card's name shows its picture while the mouse is over
  it; a tap or a click shows it on a touch screen, and a tap elsewhere or
  a scroll takes it away.
- **On the board**, Space shows what the board's map says is under the
  mouse: the card, or a tech building's codex. It stays until Space again,
  Escape, the mouse leaving that card, a press on the board, or a new
  board. The point is read through the viewer's own zoom and pan
  (`BoardViewer.boardPoint`); a map whose width is not the board's is not
  used. The keys `+`, `-` and `0` stay the viewer's zoom, which is why the
  codex is Space too. A finger has no hover, so the board's cards are
  desktop-only, and the hint beside the zoom buttons ("Point at a card and
  press Space") shows only under a fine pointer that hovers.
- **A map is fetched once per board**, with the browser's cache, since its
  key never names another; a finished turn's board opened from the log
  brings its own.

### The Function

`pbd/functions/data/[[path]].js` answers `GET` and `HEAD` under `/data/`
and nothing else (a `405` otherwise). The key is the address after `/data/`
as written -- `codex/` included, since the JSON carries whole keys -- and is
answered only where it matches one of `KEYS`, eight regex literals at the top
of the file: the two lists, a game's `live.json` and `history.json` under a
32-character lowercase hex id, a board and its map under a 64-character hex
hash, a glyph named by letters, digits and underscores, and a card's
picture by its slug, lowercase letters, digits and underscores, as `.jpg`
or `.png`. Anything else is a `404`
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

## Deploying

The site is a Cloudflare Pages project built from `main` by Cloudflare's
Git integration, as the two landing sites are
([landing-pages.md](landing-pages.md), "Deploying"); nothing is uploaded
from a machine. **The project, its binding and the bucket are the author's
Cloudflare account's; the one secret is the R2 token, and it is in the
`K:\` checkout's `.env` alone** ("Turning it on"). A developer's checkout
has none, so its test games never reach the bucket.

The address is `https://codex-pbd.pages.dev/`, the name the worksheet
chose, which Cloudflare gave without a suffix (the author, 2026-10-17, the
site live with the games being played and the archive). Written with a
trailing dot (`codex-pbd.pages.dev.`) it does not open in a phone's
browser -- Chrome as well as Safari -- though it answers `curl`; the
address to hand out is the one without.

### What the repository guarantees the build

- **There is nothing to build.** Pages serves `pbd/public/` as it stands
  and compiles `pbd/functions/` itself, so the build command only has to
  succeed. No Python, no `requirements.txt`, no `PYTHON_VERSION`.
- **Only `pbd/` feeds the site.** The pages, the viewer and the Function
  read nothing else in the repository; what the bot writes reaches them
  through the bucket, never through a build. A merge that touches nothing
  under `pbd/` is a build that would change nothing.
- **The binding is `PBD`** -- the name the Function reads (`env.PBD`) --
  and the bucket is `pbd`, `CODEX_PUBLISH_BUCKET`'s default. A bucket by
  another name is that variable set on `K:\` and the binding pointed at it.

### The checklist

Written 2026-10-17 and run by the author the same day. Cloudflare's dashboard moves
its menus around; the names below are the shape, not a promise.

1. **Turn R2 on**: dashboard -> R2 Object Storage. If it asks for a
   payment method, this is where; it charges only past the free tier.
2. **Create the bucket** `pbd`, location automatic, Standard storage (the
   free tier covers Standard alone). **Leave it private**: no custom
   domain, the `r2.dev` address off, no CORS policy. The Function is the
   only way in (decision 1).
3. **The token**: R2 -> Manage API tokens -> Create, *Object Read &
   Write*, **this bucket only**. Copy the access key id, the secret and the
   account id into the `K:\` checkout's `.env` as
   `CODEX_PUBLISH_ACCESS_KEY_ID`, `CODEX_PUBLISH_SECRET_ACCESS_KEY` and
   `CODEX_PUBLISH_ACCOUNT_ID`. The secret is shown once; a lost one is a
   new token. Scoped to the one bucket, a leaked token reaches the site's
   data and nothing else on the account.
4. **Create the Pages project** `codex-pbd`: Workers & Pages -> *Create*
   -> *Pages* -> *Connect to Git* -> `HolyTispoon/fool-bot`.
   - Production branch: `main`. Framework preset: *None*.
   - Root directory: `pbd`. Build command: `exit 0` (a blank one may be
     refused). Build output directory: `public`.
   - The root directory is what makes Pages find `pbd/functions/`: it
     looks for `functions/` there, not at the repository's root.
   - If `codex-pbd` is taken, Cloudflare offers the name with a suffix;
     take it and write the address it gives into this file.
5. **On the project** (Settings):
   - *Bindings* (or *Functions* -> *R2 bucket bindings* in older
     dashboards): variable name `PBD`, bucket `pbd`, for Production. The
     binding is read when a deployment is made, so **retry the deployment
     after adding it**; until then `env.PBD` is undefined and every `/data/`
     request the Function would answer fails with an error.
   - *Build* -> *Branch control*: automatic production deployments on,
     **preview deployments *None***, as on the two landing projects.
     Otherwise every pushed branch builds and gets a public
     `*.codex-pbd.pages.dev` address.
   - *Build watch paths*, include: `pbd/*`.
   - No custom domain: the site stays off the studio's domain because the
     board is Sirlin Games' art (decision 1).
6. **Check the Function was found**: the deployment's log names the
   Function it compiled. A log that says no `functions` directory was
   found means the root directory is wrong.
7. **Restart the Codex bot** with `run_codex_bot.cmd`; its log says
   "Codex games are published to the R2 bucket pbd." at INFO, or names
   the variable that is missing. Play an action in a game, then open the
   address on a phone off the home Wi-Fi and see the board change.
   `https://<address>/data/codex/index.json` answers the list;
   `https://<address>/data/anything-else` answers `404`.
8. **Watch the bucket's size** after a game or two: R2 -> the bucket ->
   Metrics, which the start's report in #logs should agree with ("The
   free plan"). A game should be tens of MB, not a hundred (the worksheet's
   "What it costs"); more means superseded boards are not being deleted
   ("The queue": a board nothing names is deleted). And the Functions requests a day: Workers
   & Pages -> the project -> Metrics, against the free plan's 100,000.

`scripts/run_codex_bot.ps1` is not changed: its one skip is a checkout
with no `CODEX_DISCORD_TOKEN`, which runs no Codex bot at all. Missing
`CODEX_PUBLISH_*` is not a skip -- the bot runs and publishes nothing -- and
the bot's own INFO line in step 7 is where that is said.

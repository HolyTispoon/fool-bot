# The Codex games on the web: `codex-pbd.pages.dev`

**This is a worksheet, not a specification.** It was written on
2026-10-16 from the author's ask: a website that shows the current board
of every Codex game being played on the Discord, broadly modelled on
<https://asyncti4.com/> but simpler. Clicking a game shows its board,
which updates whenever the bot's board does, with the game's log in a
column beside it that can be toggled. Each step below has a prompt a
Claude Code session is started with. Strike a step when it lands and move
what it settled into `docs/design/pbd-site.md`, the design note step 1
creates. **Nothing in it is a rule.**

asyncti4.com could not be reached from the session that wrote this (DNS
refused), so the model is the author's description of it, not the site
itself.

## What was found, and what it settles

**The board is already drawn once per change.**
`PresentationMixin.render_match_png` (`cogs/codex/presentation.py`)
draws the board as WebP and hands back the last drawing's bytes when
nothing it is drawn from has moved (`board_key`, one cached drawing a
game in `boards_drawn`, in memory). Every picture the turn message
carries comes from it, so the site's picture is those same bytes,
uploaded a second time. Nothing is drawn for the web.

Not every write reaches the gate, though. `refresh_match_image` (the
gate, `BoardRefresher`) carries an action, an undo within the turn,
**Swap view** and `/codex side_by_side`. A new turn message is sent by
`post_turn_message` (`cogs/codex/presentation.py`) -- at the game's
start, after a turn ends, after an undo to the previous turn, on
`/codex resume` and on **Show board** -- and a finished turn is edited by
`stand_turn_message`, both outside the gate. So the publisher hangs off
the two places a turn message's picture is made, `refresh_match_image`
and `post_turn_message`, and off the turn's end, not off the gate alone.

`roll_over` (`cogs/codex/turns.py`) draws the ended turn's own board
afresh (`render_match_png(game, ended)`, off the `BEGIN_TECH` group's
snapshot) and hands those bytes to `stand_turn_message`. Those are the
bytes the history keeps; they are never drawn a second time.

**The log is not saved anywhere.** The turn's lines are in memory alone,
`Codex.turn_lines` (`cogs/codex/core.py`, keyed by `game_id`, the
model's lines with their tokens intact), and a restart loses them; so
does `turn_heads`, the last three turns' headings beside it. A
finished turn's lines live only in its pinned Discord message, folded to
fit Discord's 2000 characters ("*and n more*", `turn_text`). So the site
cannot read a log back from the bot; the publisher keeps its own.

**The turn's history is already the pins.** `stand_turn_message`
(`cogs/codex/turns.py`) edits each finished turn's message a last time
with its lines and its own last board, takes its buttons off, and pins it
(the author, 2026-10-09: "the pins are the game's history turn by turn").
That is exactly what the site's history should hold, one entry per
finished turn. An undo to the previous turn deletes that turn's standing
message (`_previous_turn_back`), so the site's history has to drop the
entry too.

The pins are not a clean record of one game, though. A pin past
Discord's cap is only a logged warning, so a long game's earliest turns
may not be pinned at all. A **Rematch** reuses its channel with a new
number, so a channel's pins can hold several games' turns. A game in the
`here` venue (`CodexGame.venue`) shares a channel the bot does not own,
and its pins sit among people's own. The board's file name tells them
apart: `codex-<number>-board.webp` (`match_file_from_png`). The prefix
alone, `BOARD_IMAGE_FILENAME_PREFIX` (`"codex-"`), also starts every
ephemeral picture's name and the unpinned final-result post's.

**A game's number is not an address.** `game_number` is counted per
guild and taken again after `/codex admin reset_channels` drops games.
`game_id`, a uuid4 hex string, is the only key that is never reused, so
the bucket's paths and the page's address both use it.

**Discord's image links cannot be reused.** Discord's attachment URLs
are signed and expire (since 2023-24), so the page cannot point at the
image in the channel. The bot has to put a copy somewhere that keeps it.

**Hidden information is not a problem if the publisher reads only two
things.** The board and the turn's lines are already public in the
channel ([codex.md](design/codex.md), "What the narration may say": a
result's lines are public). Everything secret -- a hand, the codex, a
tech choice -- reaches a player through an ephemeral message. The
publisher reads `turn_lines` and the board's bytes and nothing else;
never `with_turn_log`'s copy over a hand, never a panel's text. The
board itself draws only counts of the hidden zones (hand, deck, discard,
codex) and never a tech or stash choice. The turn message's board is the
same for every viewer: its layout is `CodexGame.board_layout`, on the
record, and the near side is always `match.active`.

**The board is Sirlin Games' art, so it stays off the studio's
domain.** The board is drawn from the card pictures and the Screentop
module's sheets (`scripts/import_codex_cards.py`). Inside a Discord
server that is a group of people playing. On `propheticfools.com`, the
studio's own public site, it would read as the studio publishing another
company's art, unlisted or not. So the site is on a host that is not the
studio's (the author, 2026-10-16), and nothing about it lives under
`landing/` or `propheticfools.com`; `d12ball.com` is the studio's game's
public face and is ruled out for the same reason.

**A third Pages project can carry a Function without touching the two
landing sites.** Cloudflare Pages looks for a `functions/` folder at the
root of the project, and the root is a per-project setting ("Root
directory"). The two landing projects build from the repository's root,
so a `functions/` there would deploy to both. A project whose root is
`pbd/` finds `pbd/functions/` and nothing else, and the landing projects
never see it. A Pages project with no custom domain is served at
`<project>.pages.dev`, Cloudflare's own hostname, at no cost.

## The decisions

Taken with the author on 2026-10-16.

1. **The bot uploads to a private Cloudflare R2 bucket; a Pages
   project of its own serves the page and reads the bucket.** R2 is
   Cloudflare's file storage, its version of Amazon S3, on the account
   `d12ball.com` and `propheticfools.com` are already on (the author: no
   account on another service). The site is the Pages project
   `codex-pbd`, at `https://codex-pbd.pages.dev` -- on a host that is
   not the studio's (the author, 2026-10-16); if the name is taken
   Cloudflare adds a suffix, and the address is whatever the project is
   given. It is built from `pbd/` in this repository: static files in
   `pbd/public/`, and one Pages Function, `pbd/functions/data/`, which
   reads the bucket through an R2 binding and answers `GET /data/...`.
   - **The bucket is never public.** No custom domain, no `r2.dev`
     address, no CORS rule: the page and its data are one origin, and
     the only way into the bucket from the web is the Function, which
     reads and never writes, and answers only the keys the bucket's
     layout names. The bot writes through R2's S3 API with a token
     scoped to the bucket.
   - **Not the bucket's `r2.dev` address.** It needs no Function, but
     Cloudflare rate-limits it and says it is for development, not
     production.
   - **Not the tunnel.** Cloudflare Tunnel would need the bot to run a
     web server of its own, and the site would go down with the PC.
     With R2 the site keeps the last board and the whole history while
     `K:\` is off; only updates wait for it, and with the bot off nothing
     moves anyway.
   - **Not a domain of its own, for now.** It would cost a registration
     a year for a page nobody is meant to find. A Pages project takes a
     custom domain later as a setting, with nothing in the repository
     changed.
2. **Unlisted, not private** (the author). Nothing on
   `propheticfools.com` or `d12ball.com` links to the site. The pages
   carry `<meta name="robots" content="noindex">`, `pbd/public/_headers`
   sends `X-Robots-Tag: noindex` on every static file, and the Function
   sends it on every answer, since JSON and pictures carry no meta tag.
   There is no `robots.txt` disallowing anything, for two reasons. A
   crawler barred from a page never reads its `noindex`, so a linked URL
   can still be indexed by its address alone. And a `robots.txt` is
   public, so it would print what it hides. Anyone with the link can see
   the site, as with an unlisted video. The Function answers only named
   keys, so the bucket cannot be listed, and the images' names are their
   hashes, so nothing is reached that the page does not link to.
3. **Finished and abandoned games go to an archive** (the author), as
   the D12 Ball web app's `/archive` does: one list for the games being
   played, one for the rest, every game's page the same shape either way.
   **Only a game that started is on the site** (the author, 2026-10-16):
   a lobby is not listed, and a game abandoned in its lobby is never
   archived (`shapes.on_site`).
4. **The site mirrors the turn message** (the author). Its board is
   whatever the turn message carries, including **Swap view** (which
   flips `board_layout` on the record, not the near side) and the
   stacked board seen from the active player's side. The publisher takes
   `render_match_png`'s bytes, the same as the gate.
5. **History is turn by turn** (the author): each finished turn keeps
   what the bot pins -- its last board and its lines. The site holds the
   lines **whole**, not folded at 2000 characters, since it has no such
   limit. A history entry is a dict, not a pair, so a later per-action
   history ("perhaps more granular", the author) adds a field rather than
   changing the shape.
6. **The board can be zoomed and panned.** Hand-written, about a hundred
   lines of plain JavaScript (pointer events and a CSS transform), in
   keeping with the landing pages' no-framework rule
   ([landing-pages.md](design/landing-pages.md), "Python and plain HTML,
   no framework"): the wheel and pinch zoom toward the pointer, drag
   pans, a double click or tap switches between fit and full size, a
   button resets. **A new board keeps the viewer's zoom and position**,
   so somebody zoomed into their patrol zone stays there while the
   opponent plays. The limit is the picture's own pixels -- 1625 to 2608
   wide for two players -- sharp to about full size; a sharper web-only
   render would draw every board twice on `K:\` and is not done.
7. **Polling, not push.** The game page reads a small `live.json` about
   every 15 seconds while the tab is visible, and fetches a new image or
   the history only when their names change. The lists read their index
   every minute. Push (a Durable Object, websockets) is more than a board
   that changes every few minutes needs.
8. **One publisher per bucket**, the way one bot belongs to one token.
   It runs only where `CODEX_PUBLISH_*` is set in the `.env`, which is
   the `K:\` checkout alone; a developer's test games never reach the
   live site.
9. **Publishing never fails a turn.** Uploads go on a queue per game,
   the latest state replacing anything not sent yet, off the click's
   path. A failure is a WARNING on the console (console-only, per
   [logging.md](design/logging.md)), the site goes stale, and the next
   change sends everything again.
   - **Within a game, the order is the page's guarantee.** A board goes
     up before the `live.json` that names it, and `history.json` before
     the `live.json` whose history version changed. Then a poll that
     lands between two puts never names an object that is not there yet.
   - **`index.json` and `archive.json` have one writer of their own.**
     Every game changes them, so they are not on the per-game queues:
     two games' uploads in flight at once could finish out of order and
     put back the older list. A single queue rebuilds both from the
     record when it sends, coalescing the same way.
   - **A failure that does not stop is an ERROR, once.** A revoked
     token or a deleted bucket fails every put from then on, and a
     WARNING on a console nobody watches leaves the site stale for good.
     After a run of consecutive failures (ten, or a few minutes' worth)
     the publisher logs one ERROR, which reaches #logs because somebody
     must act, and logs it again only after a success has reset the
     run.
10. **The old turns are imported once, from the pins** (the author). A
    game already in progress when the site goes live, and every finished
    game already in **Codex Archive**, gets its history from its
    channel's pins: one listing per channel, and each pinned board
    downloaded and uploaded. It is the last step, so everything before it
    is in place when it runs. Its pins are told apart by the board's own
    file name, `codex-<number>-board.webp`, never by the prefix alone
    ("What was found", the pins). A turn past the pin cap was never
    pinned, so it is not imported, and the history says where it starts.
11. **The players are named as they are on Discord** (the author,
    2026-10-16): every list and every log line names a seat by the
    display name its player had when they joined (`seat_name`, on the
    record), on a page anyone with the link can read.

## What it costs

From Cloudflare's R2 pricing page, read on 2026-10-16
(<https://developers.cloudflare.com/r2/pricing/>):

| | Free each month | Past that |
| --- | --- | --- |
| Storage | 10 GB | $0.015 per GB-month |
| Writes (Class A) | 1 million | $4.50 per million |
| Reads (Class B) | 10 million | $0.36 per million |
| Downloads (egress) | free | free |

The Pages project and its `pages.dev` address are free; no domain is
bought and no tunnel is used. **The Function is the one other quota.**
Pages Functions requests count toward the Workers free plan's 100,000
requests a day, shared across the account and reset at midnight UTC;
past it Cloudflare answers Error 1027 rather than billing, until the next
day (<https://developers.cloudflare.com/pages/functions/pricing/>, read
2026-10-16). Static files do not count: `pbd/public/_routes.json` sends
only `/data/*` to the Function. An open game page polls `live.json` 240
times an hour, about 5,800 a day, so the quota holds roughly fifteen
pages open around the clock -- far more than a few games' players
checking in. If it ever runs short, the poll interval is the dial, or
the Workers paid plan removes the limit.

Measured on 2026-10-16 with `scripts/render_codex_sample.py`: a
two-player board is 0.35 to 0.75 MB, a five-player one about 1 MB. A
30-turn game with every finished turn's board kept is about 15 to 20 MB,
so the free storage holds about 500 games. **That holds only if a board
is deleted once nothing names it.** Every action uploads a new board
(a new hash), and a game is several hundred actions, so a bucket that
kept them all would hold 75 to 150 MB a game, and the free tier would
cover 65 to 130 games. So the queue deletes the board it replaces as the
current one, unless the history names it (the board a turn ended on).
The record knows which keys are up, so this needs no listing.
R2 does not charge for a delete: "Free operations include
`DeleteObject`, `DeleteBucket` and `AbortMultipartUpload`" (the pricing
page, read 2026-10-16 when step 2 was built).

Writes are two or three per action, so a game is roughly a thousand to
fifteen hundred. An open game page reads `live.json` 240 times an hour.
All of it should cost nothing; storage past the free 10 GB is $0.15 a
month per 10 GB.

**Not confirmed:** whether Cloudflare asks for a payment method before
R2 can be turned on. It is believed to, charging only past the free
tier; the author checks when enabling it (step 5).

## The bucket's layout

Under `codex/` in the private bucket `pbd`, read by the Function at
`https://codex-pbd.pages.dev/data/codex/...` -- the key after `/data/`,
the object's own `Cache-Control` and `ETag` passed through, a `304` for
a matching `If-None-Match`, and a `404` for any key that is not one of
these shapes:

| Key | What | Cache-Control |
| --- | --- | --- |
| `index.json` | The games being played: id, number, mode and variant, seats (name and team), turn, whose turn (a list of seats: a two-headed dragon's turn is two), updated | `no-cache` |
| `archive.json` | The finished games and the abandoned ones, each a section of its own (`finished`, `abandoned`), the same fields and the winner | `no-cache` |
| `games/<id>/live.json` | The game's status, heading, the current turn's lines, the current board's key, and the history's version | `no-cache` |
| `games/<id>/history.json` | One entry per finished turn: `turn`, `heading`, `lines`, `board` | `no-cache` |
| `games/<id>/board-<sha256>.webp` | A board. Named by its bytes, so it never changes | `public, max-age=31536000, immutable` |
| `emoji/<name>.png` | The glyphs the lines carry (`codex/images/emoji/`), uploaded once | `public, max-age=86400` |

`<id>` is the game's `game_id`, never its number ("What was found"). The
number is shown on the page and in the lists. It is never a key.

A line is not HTML. It is the model's line with its tokens resolved into
**segments** -- `{"text": ...}`, `{"card": slug, "name": ...}`,
`{"player": n, "name": ...}`, `{"glyph": "gold", "n": 3}` -- and Discord's
`**bold**` and `*italic*` as flags on a text segment. The page builds the
line with `textContent`, so a display name can never be markup. A
mention (`{to:n}`) is the seat's name on the web, never `<@id>`. The
glyphs are the ones that have a picture -- `gold`, `codex`, `target` and
`exhaust`, whose file is `codex_exhaust.png` (`CodexTokens`' emoji map,
`cogs/codex_helpers.py`). `{arrow}` is a character on Discord, so it is
a text segment here too.

The publisher's own record is `data/codex_pbd.json` on the host --
untracked runtime state, like every file in `data/` -- holding each
game's history and current lines and which board keys are already up, so
a restart does not lose the log and nothing is uploaded twice. The
bucket is the copy; the file is the source.

## The steps

Every step is one branch off an up-to-date `main`, one PR, the suite
green, and a `## Questions for the author` section on the PR even when
it is empty. A step lands by striking its row below, as the other
worksheets do (`| ~~n~~ | ~~title~~ -- landed; ... |`).

| # | Step | Size |
| --- | --- | --- |
| ~~1~~ | ~~The shapes: the record, the JSON, the segments, the design note~~ -- landed; `cogs/codex_publish/` (`record`, `keys`, `shapes`, `segments`) and [design/pbd-site.md](design/pbd-site.md) | ~~medium~~ |
| ~~2~~ | ~~The store and the queue: R2 behind `CODEX_PUBLISH_*`, a fake for the tests, the put order, the deletes, the lists' own queue~~ -- landed; `botkit/objectstore.py`, `cogs/codex_publish/queue.py` and `config.py`, [design/pbd-site.md](design/pbd-site.md), "The store" and "The queue" | ~~medium~~ |
| ~~3~~ | ~~The hooks: the Codex cog publishes every change, every turn's end, every undo, every ending~~ -- landed; `cogs/codex_publish/publisher.py`, [design/pbd-site.md](design/pbd-site.md), "The hooks" | ~~medium~~ |
| ~~4~~ | ~~The site: `pbd/`, the two lists, the game, the log column, the history, the viewer, the Function~~ -- landed; `pbd/public/`, `pbd/functions/data/[[path]].js`, `scripts/serve_pbd.py`, [design/pbd-site.md](design/pbd-site.md), "The page" | ~~medium~~ |
| ~~5~~ | ~~Deploy: the bucket, the token, the Pages project and its binding, the `.env` on `K:\`~~ -- landed; live at `https://codex-pbd.pages.dev/` (2026-10-17), [design/pbd-site.md](design/pbd-site.md), "Deploying" | ~~small, half of it in dashboards~~ |
| 6 | The old turns, from the pins | small |

Steps 1 to 4 need no Cloudflare: the store has a fake, and the site is
looked at through `scripts/serve_pbd.py`, which serves `pbd/public/` and
answers `/data/` from a local folder in the bucket's layout, as the
Function does. Nothing goes public until step 5. The author can run step
5's dashboard half at any time after step 2.

### Claiming a step

`scripts/claim_web_step.py --series pbd <n>` claims step `n`: it pushes
an empty commit to `pbd-step-<n>` and refuses if the branch, an open PR
titled `PBD step <n>:`, or a struck row already exists. The series does
not exist yet: **step 1's prompt adds it** -- one entry in `SERIES`
(`"pbd": ("docs/pbd-site.md", "pbd-step", "PBD step")`), plus the
`--series` help string and the module docstring, which both list the
series by hand. The docstring says "Five series share the one script",
which becomes six. The help string is missing a comma today
(`(docs/landing-pages.md) codex`), which step 1 fixes while it is
there.

## Preamble

Every step's prompt starts with this block.

```text
You are working in the fool-bot repository on the Codex games' web
page planned in docs/pbd-site.md. Read that worksheet first, then the
design note docs/design/pbd-site.md if it exists. Read
docs/design/codex.md only at the sections a step names -- it is long.
Do not read the rest of docs/design/ unless a step names a file.

Start on a fresh branch off an up-to-date main (the claim script has
made it: git fetch && git checkout pbd-step-<n>). Never work on main.

The publisher is the Codex bot's frontend, like the cog: it decides no
rule, and nothing under codex/ or gamesaves/codex/ learns that it
exists. It reads two things -- the turn's lines (`Codex.turn_lines`)
and the board's bytes (`render_match_png`) -- and nothing secret: never
a hand, a panel, a tech choice or `with_turn_log`'s copy. Publishing
never fails a turn, never blocks a click, and spends no Discord request
except in step 6. It runs only where CODEX_PUBLISH_* is set.

The site is its own Cloudflare Pages project, under pbd/ (static files
in pbd/public/, one Function in pbd/functions/), never under landing/
and never on the studio's domain: the board is Sirlin Games' art. Plain
HTML, CSS and JavaScript, no framework, no CDN, no build step. It builds
every line with textContent, never innerHTML.

Run python3 -m unittest discover -s tests before the PR; a full run must
not create data/. The PR carries a ## Questions for the author section,
even if empty, and strikes this step's row in docs/pbd-site.md. When the
step settles something the worksheet only proposed, write it into
docs/design/pbd-site.md with the reasoning, and add a row to CLAUDE.md's
tables only for a new module or a new hard rule.
```

### 1. The shapes: the record, the JSON, the segments, the design note

Everything the publisher writes, as pure functions with tests, before
anything is uploaded.

```text
Step 1 of docs/pbd-site.md.

Add the series: "pbd": ("docs/pbd-site.md", "pbd-step", "PBD step") in
scripts/claim_web_step.py's SERIES, and in its --series help string and
module docstring, which list the series by hand ("Five series" becomes
six; add the comma the help string is missing after
"(docs/landing-pages.md)").

Create cogs/codex_publish/ (a package, not a mixin: the cog calls it,
it holds no Discord state) with:
- record.py: PublishRecord, the publisher's own file,
  data/codex_pbd.json -- per game: the current turn's heading and lines,
  the history (a list of dicts: turn, heading, lines, board), the board
  keys already uploaded, the history's version, and whether step 6's
  import has run. Keyed by game_id, never the game's number, which is
  per guild and reused. Load and save through gamekit/storage.py's
  read_games_file and save_games, with the record's own two failure
  flag sets. save_games calls to_dict() on every value, so a game's
  entry is a small class with to_dict/from_dict, not a bare dict. A save
  failure is logged and never raised. No mkdir on load.
- shapes.py: index_entry(game, match), live(game, match, ...),
  history(...), each returning the dict written as JSON (the table in
  the worksheet's "The bucket's layout"). Seats by seat_label, teams
  by codex.formatting.team_name. A board's key is
  games/<id>/board-<sha256 of its bytes>.webp.
- segments.py: a line -- the model's, tokens intact -- to segments, the
  resolver the web gets beside CodexTokens: {player:n} and {to:n} the
  seat's name, never a mention; {card:slug} and {hero:slug} the card's
  name with its slug; {gold:n}, {exhaust}, {target}, {codex} as glyphs
  (exhaust's picture is codex_exhaust.png); {arrow} as text, as it is on
  Discord; **bold** and *italic* as flags. Use codex/tokens.py's
  find and render, as CodexTokens does, never a regex of your own.

Tests: tests/test_codex_publish_shapes.py -- the shapes of a staged
game (tests/codex_positions.py), a line with every token kind, a display
name holding < and ** coming through as text, the record surviving a
round trip and a corrupt file.

Create docs/design/pbd-site.md, the design note: what the publisher is
and is not, why it reads only the lines and the board, the bucket's
layout and why a board is named by its hash, and why the log is the
publisher's file and not the game's. Add the worksheet and the package
to CLAUDE.md's map.
```

### 2. The store and the queue

```text
Step 2 of docs/pbd-site.md.

Add botkit/objectstore.py: ObjectStore, put(key, bytes, content_type,
cache_control) and delete(key); R2Store over R2's S3 API through boto3,
every call in asyncio.to_thread; MemoryStore for the tests. boto3 is
pinned in requirements.txt, so the K:\ checkout gets it on its next
pull. Both Pages builds install requirements.txt too, and a change to it
rebuilds both sites (their watch paths); say so in the PR. R2Store
imports boto3 inside its constructor, never at module level, so the
suite and a checkout without it run with the publisher off. The
Cache-Control per kind is the worksheet's table.

Add the queue in cogs/codex_publish/queue.py: one pending state per
game, a newer state replacing one not yet sent, one upload in flight
per game, a board uploaded only if its key is not already up. Within a
game the order is the board, then history.json, then live.json
(decision 9), and the board this one replaces as current is deleted
unless the history names it ("What it costs"). index.json and
archive.json go on one queue of their own, rebuilt from the record when
sent, never on a game's. A failed put is logged at WARNING and retried
with the next change. A run of consecutive failures logs one ERROR
until a success resets it (decision 9). Nothing raises out of it. It is
stopped cleanly when the cog unloads.

Configuration, read once at startup from the .env:
CODEX_PUBLISH_ACCOUNT_ID, CODEX_PUBLISH_ACCESS_KEY_ID,
CODEX_PUBLISH_SECRET_ACCESS_KEY, CODEX_PUBLISH_BUCKET (default "pbd").
With any missing the publisher is off and says so once at INFO. Write
them into docs/design/collaboration.md, "The Codex bot", beside
CODEX_DISCORD_TOKEN: a credential, the .env and nowhere else, the
K:\ checkout alone.

Tests: the queue coalescing three changes into one upload, a failing
store not raising and the next change sending again, a board not
uploaded twice, the order of a game's puts, a replaced board deleted
and a history board kept, two games' index changes ending with the newer
list, the ERROR once after a run of failures, the publisher off without
the variables or without boto3.
```

### 3. The hooks

```text
Step 3 of docs/pbd-site.md. Read docs/design/codex.md at "The turn
message, edited", "The requests per click", "The undos, and who may
take each", "The resume path" and "The end of a game".

Give the Codex cog a publisher (cogs/codex/core.py, built in
cog_load, off where step 2's configuration is missing), and call it
from the cog's own methods, never from BoardRefresher, which D12 Ball
shares. Not every turn-message write goes through the gate (the
worksheet's "What was found"), so the hooks are:
- refresh_match_image: the current lines and the board -- every
  action, the undos within a turn, Swap view, /codex side_by_side.
- post_turn_message: the new turn message's board and lines current --
  the game's start, a turn's end, an undo to the previous turn,
  /codex resume, Show board. Where the bytes are the ones already up,
  this is a live.json write at most.
- roll_over: the ended turn as a history entry -- its closing lines
  and the bytes it renders for stand_turn_message, never a second
  render -- then the new turn as current.
- _previous_turn_back: the restored turn's history entry dropped, the
  restored turn current.
- finish_game (a fallen base and every concession reach it through
  present) and abandon_command (cogs/codex/ending.py, where the abandon
  is written inline -- no method of its own): the game moved from
  index.json to archive.json with its last board and its winner, or
  none. A game abandoned in its lobby was never on the site and is not
  archived (shapes.on_site, decision 3).
- /codex admin reset_channels, which drops games through neither: the
  dropped games taken off index.json and archive.json, so a list never
  links to a game the record no longer has.
- The lobby's Start (LobbyMixin.start_game): the game added to
  index.json.
- On startup: views are re-armed in CoreMixin.__init__
  (restore_saved_views), before the loop runs. So schedule the startup
  publish from cog_load as a task. It writes index.json and archive.json
  from the record: every game being played, and every finished or
  abandoned game that started (shapes.on_site) and the publisher's
  record has no entry for yet, each
  with its last board, so a game that ended before the site existed is
  in the archive before step 6 gives it a history. It uploads the
  emoji if they are not up. It renders no board for a game whose
  current board the record already says is up: the site has it, and
  the next change sends a new one.

The lines are turn_lines; where this process has not seen the turn's
lines (after a restart, until /codex resume), the site keeps the lines
the record last had, as the gate keeps the message's text
(turn_text_or_none). /codex resume resets turn_lines to [] or the
opening lines (cogs/codex/slash_commands.py), so after a restart the
turn's lines on the site are the record's for that turn followed by
turn_lines, never turn_lines alone, until the turn ends. The publisher
remembers per game that it is in that state, and which turn it is for.

Tests, through tests/codex_cog_fakes.py and a MemoryStore: a seeded
whole game publishing one history entry per finished turn, each with
the board the pin carried; an undo to the previous turn dropping one;
a finished game moving to the archive, and an abandoned one; a
reset_channels drop leaving neither list; an action after a restart and
/codex resume adding to the record's lines for the turn, not replacing
them; the publisher off sending nothing; no extra Discord request per click (the request counts the
fakes log stay what they are).
```

### 4. The page

```text
Step 4 of docs/pbd-site.md. Read docs/design/landing-pages.md at "Python
and plain HTML, no framework" and "The night palette, because a page is
a screen" for the look; the site borrows the palette's values, not the
landing build.

Add pbd/, the Pages project's root (decision 1). Nothing under it is
built: Pages serves pbd/public/ as it stands and finds pbd/functions/.
Nothing under landing/ changes, and nothing under pbd/ is linked from
either landing site.

pbd/public/:
- index.html: the games being played, newest activity first, and the
  archive under them in its two sections -- the finished games, then
  the abandoned ones (the author, 2026-10-16) -- from
  /data/codex/index.json and /data/codex/archive.json, which carries the
  two sections as `finished` and `abandoned`.
- game.html: one game. _redirects rewrites /game/:id to /game with a 200,
  not a redirect (Pages serves game.html at /game and redirects the
  .html name there, so the rewrite names /game). The address is the
  game's id, never its number (the worksheet's "What was found"). The
  page reads the id off location.pathname.
- codex.js, viewer.js, codex.css, named by absolute path, so a trailing
  slash on an address breaks nothing.
- _headers: X-Robots-Tag: noindex on /*. Both pages also carry
  <meta name="robots" content="noindex">. No robots.txt (decision 2).
- _routes.json: {"version": 1, "include": ["/data/*"], "exclude": []},
  so only the data counts against the Functions quota ("What it costs").

pbd/functions/data/[[path]].js: GET and HEAD only. The key is "codex/"
plus the path, answered only where it is one of the bucket's layout's
shapes (a short list of patterns at the top of the file; games/<id>/ a
32-character hex id, a board a 64-character hex hash, an emoji name of
letters, digits and underscores) and a 404 otherwise. env.PBD.get(key,
{onlyIf: request.headers}), the object's writeHttpMetadata and httpEtag
passed through, a 304 where the precondition fails, X-Robots-Tag:
noindex on every answer. It never writes and never lists.

The game page: the board, as large as the window allows, in the
viewer (the worksheet's decision 6), and a log column beside it that a
button hides and shows, remembered in localStorage (wrapped in
try/catch). The column holds the current turn's lines and, under them,
the history newest first, each finished turn its heading, its lines and
its board as a thumbnail that opens in the viewer. Polling as decision
7 says, paused while the tab is hidden; a new board swaps in under the
viewer's current zoom and position. A game that is over says so and
stops polling.

Add scripts/serve_pbd.py, run more than once while the page is worked
on: it serves pbd/public/ with the rewrite and _headers, and answers
/data/ from a folder in the bucket's layout (--data <dir>), refusing the
keys the Function refuses. To look at it: stage a folder with step 1's
shapes and a render_codex_sample board, serve it, and take the page at
desktop, iPad (touch emulated) and phone widths, the log open and
closed, zoomed in and out. Put the pictures in the PR.

tests/test_pbd_site.py: the files are there; _routes.json includes
/data/* alone; _headers carries the noindex; _redirects' rewrite is a
200 onto a page that is there; every key step 1's shapes write matches
one of the Function's patterns and a key outside them matches none (read
the patterns out of the .js, which are plain enough to compile as
Python regexes, so the two cannot drift); nothing under landing/ names
pbd/ or the site's address.
```

### 5. Deploy

The repository half is small; the dashboard half is the author's.
Cloudflare moves its menus around, so the names are the shape, not a
promise.

1. **Turn R2 on**: dashboard -> R2 Object Storage. If it asks for a
   payment method, this is where; it charges only past the free tier.
2. **Create the bucket** `pbd`, location automatic, Standard storage
   (the free tier covers Standard alone). **Leave it private**: no
   custom domain, the `r2.dev` address off, no CORS policy (decision 1).
3. **The token**: R2 -> Manage API tokens -> Create, *Object Read &
   Write*, **this bucket only**. Copy the access key id, the secret and
   the account id into the `K:\` checkout's `.env` as step 2's
   variables. The secret is shown once; a lost one is a new token.
4. **Create the Pages project** `codex-pbd`: Workers & Pages -> *Create*
   -> *Pages* -> *Connect to Git* -> `HolyTispoon/fool-bot`.
   - Production branch: `main`. Framework preset: *None*.
   - Root directory: `pbd`. Build command: `exit 0` (there is nothing
     to build; a blank one may be refused). Build output directory:
     `public`.
   - If `codex-pbd` is taken, Cloudflare offers the name with a suffix;
     take it and note the address.
5. **On the project** (Settings):
   - *Bindings* (or *Functions* -> *R2 bucket bindings* in older
     dashboards): variable name `PBD`, bucket `pbd`, for Production.
     The binding is read when a deployment is made, so **retry the
     deployment after adding it**.
   - *Build* -> *Branch control*: preview deployments *None*, as on the
     two landing projects; otherwise every pushed branch gets a public
     `*.codex-pbd.pages.dev` address.
   - *Build watch paths*, include: `pbd/*`. Nothing else feeds the site.
   - No custom domain.
6. **Check the Function was found**: the deployment's log names the
   Function it compiled; a log that says no `functions` directory was
   found means the root directory is wrong.
7. **Restart the Codex bot** with `run_codex_bot.cmd` and play an
   action in a game; open the project's address on a phone off the home
   Wi-Fi and see the board change. `https://<address>/data/codex/index.json`
   answers the list; `https://<address>/data/anything-else` answers 404.
8. **Watch the bucket's size** after a game or two: R2 -> the bucket ->
   Metrics. A game should be tens of MB, not a hundred ("What it
   costs"); more means superseded boards are not being deleted. And the
   Functions requests a day: Workers & Pages -> the project -> Metrics,
   against the 100,000.

```text
Step 5 of docs/pbd-site.md.

The repository half: write the checklist above into
docs/design/pbd-site.md, "Deploying", as landing-pages.md's is written,
with the address the project was given, and the variables into
scripts/run_codex_bot.ps1's skip message if it names what is missing.
Nothing else; the dashboard half is the author's.
```

### 6. The old turns, from the pins

```text
Step 6 of docs/pbd-site.md. Read docs/design/codex.md at "The turn
message, edited" and "The end of a game".

On startup, after step 3's publishing, for every game the record holds
-- being played, finished or abandoned; every started game in
data/codex_games.json, not only the ones the publisher's record already
has -- whose publisher record says its import has not run: list its
channel's pins (or its thread's), keep the Codex bot's own messages
whose board is named exactly codex-<that game's number>-board.webp,
oldest first, and for each download the board and read the turn and
the heading off the text's first line. Never match on
BOARD_IMAGE_FILENAME_PREFIX alone: a Rematch reuses its channel, so a
channel's pins hold several games, and a game in the "here" venue
shares a channel with other people's pins (the worksheet's "What was
found", the pins). A turn that was never pinned (the pin cap) is not
there to import. The
text is as Discord shows it: a mention becomes the seat's name off the
record, an emoji its glyph segment, and a turn folded at 2000 characters
keeps its "and n more". Write the turns before the earliest the record
already holds into its history; mark the import done, also where the
channel is gone. One channel at a time, behind the queue, never during a
click; the requests it spends are logged at INFO with the count.

Tests: a fake channel's pins becoming history entries, the bot's own
messages alone, a rematch's earlier game's pins in the same channel
left out, a mention resolved, a deleted channel marked done, a second
startup importing nothing.
```

## Questions the author answered

Raised in review on 2026-10-16 and answered the same day.

1. **The players' names on the open web**: fine as they are -- the
   Discord display name on the record (decision 11).
2. **Codex's card art on the studio's domain**: not there -- on a host
   that is not the studio's, which made the site its own Pages project
   on `pages.dev` with a private bucket behind a Function (decision 1).
3. **A game abandoned in its lobby** (raised on step 1's PR): not
   archived. A game is on the site only once it has started (decision 3).

## What is not in these prompts, on purpose

- **D12 Ball's Discord games.** The same publisher could carry them
  later; the web app already shows its own.
- **Per-action history.** Decision 5 leaves room for it; nothing builds
  it.
- **Card pictures on hover in the log.** A segment carries the slug, so
  a later step can add it without changing the JSON.
- **A sharper board for the web.** Decision 6.
- **Who is looking.** The page has no sign-in and no names of its own;
  it is unlisted, not private.

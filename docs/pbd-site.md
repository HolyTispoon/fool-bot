# The Codex games on the web: `propheticfools.com/pbd/codex`

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
nothing it is drawn from has moved (`board_key`). Every write to the turn
message goes through it, so the site's picture is those same bytes,
uploaded a second time. Nothing is drawn for the web.

**The log is not saved anywhere.** The turn's lines are in memory alone,
`Codex.turn_lines` (`cogs/codex/core.py`), and a restart loses them. A
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

**Discord's image links cannot be reused.** Discord's attachment URLs
are signed and expire (since 2023-24), so the page cannot point at the
image in the channel. The bot has to put a copy somewhere that keeps it.

**Hidden information is not a problem if the publisher reads only two
things.** The board and the turn's lines are already public in the
channel ([codex.md](design/codex.md), "What the narration may say": a
result's lines are public). Everything secret -- a hand, the codex, a
tech choice -- reaches a player through an ephemeral message. The
publisher reads `turn_lines` and the board's bytes and nothing else;
never `with_turn_log`'s copy over a hand, never a panel's text.

**The landing site is static and has no secrets.** `propheticfools.com`
is the `propheticfoolsgames` Cloudflare Pages project, built from `main`
by `landing/build.py --only studio`
([landing-pages.md](design/landing-pages.md), "Deploying"). A page under
it can be added the same way; anything live has to come from elsewhere.

## The decisions

Taken with the author on 2026-10-16.

1. **The bot uploads to Cloudflare R2; the page is static and reads
   from there.** R2 is Cloudflare's file storage, its version of Amazon
   S3, on the account `d12ball.com` and `propheticfools.com` are already
   on (the author: no account on another service). It is a public bucket
   on a subdomain of its own, `pbd.propheticfools.com` (the author,
   2026-10-16); the page at
   `propheticfools.com/pbd/codex` fetches JSON from it, with a CORS rule
   allowing the studio's origin, and shows its images.
   - **Not the tunnel.** Cloudflare Tunnel routes by hostname, not by
     path, so `/pbd/codex` on the Pages domain would need a Worker in
     front, the bot would need a web server of its own, and the site
     would go down with the PC. With R2 the site keeps the last board
     and the whole history while `K:\` is off; only updates wait for it,
     and with the bot off nothing moves anyway.
   - **Not a Pages Function.** Both Pages projects build from the
     repository's root, so a `functions/` folder there would deploy to
     `d12ball.com` as well. It would also mean a writable public
     endpoint to maintain.
2. **Unlisted, not private** (the author). Nothing on
   `propheticfools.com` links to `/pbd/codex`; the page carries
   `<meta name="robots" content="noindex">`; both hosts' `robots.txt`
   disallow it. Anyone with the link can see it, as with an unlisted
   video. The bucket cannot be listed through its custom domain, and the
   images' names are their hashes, so nothing is reached that the page
   does not link to.
3. **Finished and abandoned games go to an archive** (the author), as
   the D12 Ball web app's `/archive` does: one list for the games being
   played, one for the rest, every game's page the same shape either way.
4. **The site mirrors the turn message** (the author). Its board is
   whatever the turn message carries, including **Swap view** and the
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
10. **The old turns are imported once, from the pins** (the author). A
    game already in progress when the site goes live, and every finished
    game already in **Codex Archive**, gets its history from its
    channel's pins: one listing per channel, and each pinned board
    downloaded and uploaded. It is the last step, so everything before it
    is in place when it runs.

## What it costs

From Cloudflare's R2 pricing page, read on 2026-10-16
(<https://developers.cloudflare.com/r2/pricing/>):

| | Free each month | Past that |
| --- | --- | --- |
| Storage | 10 GB | $0.015 per GB-month |
| Writes (Class A) | 1 million | $4.50 per million |
| Reads (Class B) | 10 million | $0.36 per million |
| Downloads (egress) | free | free |

The Pages project, the custom domain and DNS are already paid for or
free; no Worker and no tunnel is used.

Measured on 2026-10-16 with `scripts/render_codex_sample.py`: a
two-player board is 0.35 to 0.75 MB, a five-player one about 1 MB. A
30-turn game with every finished turn's board kept is about 15 to 20 MB,
so the free storage holds about 500 games. Writes are two or three per
action, so a game is roughly a thousand to fifteen hundred. An open game
page reads `live.json` 240 times an hour. All of it should cost nothing;
storage past the free 10 GB is $0.15 a month per 10 GB.

**Not confirmed:** whether Cloudflare asks for a payment method before
R2 can be turned on. It is believed to, charging only past the free
tier; the author checks when enabling it (step 5).

## The bucket's layout

Under `codex/` in the bucket `pbd`, served at
`https://pbd.propheticfools.com/codex/...`:

| Key | What | Cache-Control |
| --- | --- | --- |
| `index.json` | The games being played: id, number, mode and variant, seats (name and team), turn, whose turn, updated | `no-cache` |
| `archive.json` | The finished and abandoned games, the same fields and the winner | `no-cache` |
| `games/<id>/live.json` | The game's status, heading, the current turn's lines, the current board's key, and the history's version | `no-cache` |
| `games/<id>/history.json` | One entry per finished turn: `turn`, `heading`, `lines`, `board` | `no-cache` |
| `games/<id>/board-<sha256>.webp` | A board. Named by its bytes, so it never changes | `public, max-age=31536000, immutable` |
| `emoji/<name>.png` | The glyphs the lines carry (`codex/images/emoji/`), uploaded once | `public, max-age=86400` |
| `/robots.txt` | `Disallow: /` | |

A line is not HTML. It is the model's line with its tokens resolved into
**segments** -- `{"text": ...}`, `{"card": slug, "name": ...}`,
`{"player": n, "name": ...}`, `{"glyph": "gold", "n": 3}` -- and Discord's
`**bold**` and `*italic*` as flags on a text segment. The page builds the
line with `textContent`, so a display name can never be markup. A
mention (`{to:n}`) is the seat's name on the web, never `<@id>`.

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
| 1 | The shapes: the record, the JSON, the segments, the design note | medium |
| 2 | The store and the queue: R2 behind `CODEX_PUBLISH_*`, a fake for the tests | small |
| 3 | The hooks: the Codex cog publishes every change, every turn's end, every undo, every ending | medium |
| 4 | The page: the two lists, the game, the log column, the history, the viewer | medium |
| 5 | Deploy: the bucket, its domain, the token, the `.env` on `K:\` -- **the dashboard half is the author's** | small, half of it in dashboards |
| 6 | The old turns, from the pins | small |

Steps 1 to 4 need no Cloudflare: the store has a fake, and the page is
looked at against a local folder served with CORS standing in for the
bucket. Nothing goes public until step 5. The author can run step 5's
dashboard half at any time after step 2.

### Claiming a step

`scripts/claim_web_step.py --series pbd <n>` claims step `n`: it pushes
an empty commit to `pbd-step-<n>` and refuses if the branch, an open PR
titled `PBD step <n>:`, or a struck row already exists. The series does
not exist yet: **step 1's prompt adds it** -- one entry in `SERIES`
(`"pbd": ("docs/pbd-site.md", "pbd-step", "PBD step")`), plus the
`--series` help string and the module docstring, which both list the
series by hand.

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

The page is a static page of the studio site, under landing/studio/,
built by landing/build.py: plain HTML, CSS and JavaScript, no framework,
no CDN. It builds every line with textContent, never innerHTML.

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
module docstring, which list the series by hand.

Create cogs/codex_publish/ (a package, not a mixin: the cog calls it,
it holds no Discord state) with:
- record.py: PublishRecord, the publisher's own file,
  data/codex_pbd.json -- per game: the current turn's heading and lines,
  the history (a list of dicts: turn, heading, lines, board), the board
  keys already uploaded, the history's version, and whether step 6's
  import has run. Load and save the way gamekit/storage.py's guarded
  read and write do; a save failure is logged and never raised. No
  mkdir on load.
- shapes.py: index_entry(game, match), live(game, match, ...),
  history(...), each returning the dict written as JSON (the table in
  the worksheet's "The bucket's layout"). Seats by seat_label, teams
  by codex.formatting.team_name. A board's key is
  games/<id>/board-<sha256 of its bytes>.webp.
- segments.py: a line -- the model's, tokens intact -- to segments, the
  resolver the web gets beside CodexTokens: {player:n} and {to:n} the
  seat's name, never a mention; {card:slug} and {hero:slug} the card's
  name with its slug; {gold:n}, {exhaust}, {target}, {codex}, {arrow}
  as glyphs; **bold** and *italic* as flags. Use codex/tokens.py's
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
cache_control) and delete(key); R2Store over R2's S3 API through boto3
(pinned in requirements.txt -- note in the PR that the Pages builds
install it too), every call in asyncio.to_thread; MemoryStore for the
tests. The Cache-Control per kind is the worksheet's table.

Add the queue in cogs/codex_publish/queue.py: one pending state per
game, a newer state replacing one not yet sent, one upload in flight
per game, a board uploaded only if its key is not already up. A failed
put is logged at WARNING and retried with the next change; nothing
raises out of it. It is stopped cleanly when the cog unloads.

Configuration, read once at startup from the .env:
CODEX_PUBLISH_ACCOUNT_ID, CODEX_PUBLISH_ACCESS_KEY_ID,
CODEX_PUBLISH_SECRET_ACCESS_KEY, CODEX_PUBLISH_BUCKET (default "pbd").
With any missing the publisher is off and says so once at INFO. Write
them into docs/design/collaboration.md, "The Codex bot", beside
CODEX_DISCORD_TOKEN: a credential, the .env and nowhere else, the
K:\ checkout alone.

Tests: the queue coalescing three changes into one upload, a failing
store not raising and the next change sending again, a board not
uploaded twice, the publisher off without the variables.
```

### 3. The hooks

```text
Step 3 of docs/pbd-site.md. Read docs/design/codex.md at "The turn
message, edited", "The requests per click", "The undos, and who may
take each", "The resume path" and "The end of a game".

Give the Codex cog a publisher (cogs/codex/core.py, built in
cog_load, off where step 2's configuration is missing), and call it
from the cog's own methods, never from BoardRefresher, which D12 Ball
shares:
- refresh_match_image: the current lines and the board -- every
  action, the undos within a turn, Swap view.
- roll_over: the ended turn as a history entry -- its closing lines
  and its own last board, exactly what stand_turn_message pins -- then
  the new turn as current.
- _previous_turn_back: the restored turn's history entry dropped, the
  restored turn current.
- finish_game and the abandon path: the game moved from index.json to
  archive.json with its last board and its winner.
- The lobby's Start: the game added to index.json.
- On startup, after the cog has re-armed its views: every game being
  played published once, and the emoji uploaded if not up.

The lines are turn_lines; where this process has not seen the turn's
lines (after a restart, until /codex resume), the site keeps the lines
the record last had, as the gate keeps the message's text
(turn_text_or_none).

Tests, through tests/codex_cog_fakes.py and a MemoryStore: a seeded
whole game publishing one history entry per finished turn, each with
the board the pin carried; an undo to the previous turn dropping one;
a finished game moving to the archive; the publisher off sending
nothing; no extra Discord request per click (the request counts the
fakes log stay what they are).
```

### 4. The page

```text
Step 4 of docs/pbd-site.md. Read docs/design/landing-pages.md at "Python
and plain HTML, no framework", "The night palette, because a page is a
screen" and "Redirects".

Add landing/studio/pbd/codex/: index.html (the two lists: the games
being played, newest activity first, and the archive under them), and
game.html (one game), with codex.js, viewer.js and codex.css, built by
landing/build.py into the studio site and sharing base.css and the night
palette. A rewrite in REDIRECTS sends /pbd/codex/<number> to game.html
(a 200, not a redirect). Both pages carry <meta name="robots"
content="noindex">; the site's robots.txt disallows /pbd/; nothing
on the studio page links here.

The game page: the board, as large as the window allows, in the
viewer (the worksheet's decision 6), and a log column beside it that a
button hides and shows, remembered in localStorage (wrapped in
try/catch). The column holds the current turn's lines and, under them,
the history newest first, each finished turn its heading, its lines and
its board as a thumbnail that opens in the viewer. Polling as decision
7 says, paused while the tab is hidden; a new board swaps in under the
viewer's current zoom and position. A game that is over says so and
stops polling.

The bucket's address is one constant in build.py, written into the
page, so a local build can point at a folder. To look at it: stage a
folder in the bucket's layout with step 1's shapes and a
render_codex_sample board, serve it with CORS on one port and the built
site on another, and take the page at desktop, iPad (touch emulated)
and phone widths, the log open and closed, zoomed in and out. Put the
pictures in the PR.

tests/test_landing_build.py: the two pages are in the studio build,
the rewrite names a file that is there, nothing on index.html links to
/pbd/.
```

### 5. Deploy

The repository half is small; the dashboard half is the author's.
Cloudflare moves its menus around, so the names are the shape, not a
promise.

1. **Turn R2 on**: dashboard -> R2 Object Storage. If it asks for a
   payment method, this is where; it charges only past the free tier.
2. **Create the bucket** `pbd`, location automatic, Standard storage
   (the free tier covers Standard alone).
3. **Give it its domain**: the bucket -> Settings -> Custom Domains ->
   `pbd.propheticfools.com`. The zone is on the same account, so
   Cloudflare adds the DNS record. Leave the `r2.dev` address off.
4. **CORS**: the bucket -> Settings -> CORS policy, allowing `GET` from
   `https://propheticfools.com` and `https://www.propheticfools.com`.
5. **The token**: R2 -> Manage API tokens -> Create, *Object Read &
   Write*, **this bucket only**. Copy the access key id, the secret and
   the account id into the `K:\` checkout's `.env` as step 2's
   variables. The secret is shown once; a lost one is a new token.
6. **Restart the Codex bot** with `run_codex_bot.cmd` and play an
   action in a game; open `https://propheticfools.com/pbd/codex` on a
   phone off the home Wi-Fi and see the board change.

```text
Step 5 of docs/pbd-site.md.

The repository half: write the checklist above into
docs/design/pbd-site.md, "Deploying", as landing-pages.md's is written,
and the variables into scripts/run_codex_bot.ps1's skip message if it
names what is missing. Upload robots.txt to the bucket at startup if it
is not there. Nothing else; the dashboard half is the author's.
```

### 6. The old turns, from the pins

```text
Step 6 of docs/pbd-site.md. Read docs/design/codex.md at "The turn
message, edited" and "The end of a game".

On startup, after step 3's publishing, for every game the record holds
-- being played, finished or abandoned -- whose publisher record says
its import has not run: list its channel's pins (or its thread's), keep
the Codex bot's own messages whose board's file name starts with
BOARD_IMAGE_FILENAME_PREFIX, oldest first, and for each download the
board and read the turn and the heading off the text's first line. The
text is as Discord shows it: a mention becomes the seat's name off the
record, an emoji its glyph segment, and a turn folded at 2000 characters
keeps its "and n more". Write the turns before the earliest the record
already holds into its history; mark the import done, also where the
channel is gone. One channel at a time, behind the queue, never during a
click; the requests it spends are logged at INFO with the count.

Tests: a fake channel's pins becoming history entries, the bot's own
messages alone, a mention resolved, a deleted channel marked done, a
second startup importing nothing.
```

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

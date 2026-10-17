# The D12 Ball games on the web: `pbd.d12ball.com`

**This is a worksheet, not a specification.** It was written on
2026-10-17 from the author's ask: a website for D12 Ball's Discord games
"just like we have for Codex" ([docs/pbd-site.md](pbd-site.md)), except on
a domain of the studio's own; the author named the address,
`pbd.d12ball.com`, in review the same day. Every D12 Ball game being
played on the Discord, an
archive of the rest, and each game's current board -- zoomable, kept in
view as it updates -- with its log beside it and its history play by
play. Each step below has a prompt a Claude Code session is started with.
Strike a step when it lands and move what it settled into
`docs/design/d12ball-pbd-site.md`, the design note step 2 creates.
**Nothing in it is a rule.**

The Codex site is the model throughout, and its design note
([design/pbd-site.md](design/pbd-site.md)) is where most of the reasoning
already lives. This worksheet says what carries over unchanged, what D12
Ball does differently, and what its own domain changes. Where it says
"as the Codex site does", the Codex note's section of that name is the
reasoning.

## What was found, and what it settles

**A subdomain, because a path on `d12ball.com` cannot carry a
Function.** The `d12ball` Pages project serves `d12ball.com` and builds
from the repository's root ([design/landing-pages.md](design/landing-pages.md),
"Deploying": "Root directory: blank"), and so does the studio's. Pages looks
for `functions/` at a project's root, so a Function for this site at the
repository's root would be compiled into **both** landing sites, and on
`d12ball.com`, whose output has no `_routes.json`, it would answer every
path. A `_redirects` rule cannot proxy to another host either (a 200 rewrite
takes a path on the same site). So the site is a Pages project of its own,
rooted in its own folder as `pbd/` is, with the **custom domain
`pbd.d12ball.com`** -- a setting on the project, with the zone already on
the same account. `play.d12ball.com` is the tunnel's, for the web app, and
is not touched. The zone already has *Respect Existing Headers* on
(landing-pages.md, the 2026-09-30 run), so the JSON's `no-cache` reaches
the browser rather than the zone's `max-age=14400`.

**What kept Codex off the studio's domains does not apply.** The Codex site
is on `pages.dev` because its board is Sirlin Games' art, and
`d12ball.com` was ruled out for it by name ([pbd-site.md](pbd-site.md),
"What was found"). D12 Ball's board is the studio's own game drawn by the
studio's own renderer, so the game's own domain is where it belongs.

**The board is drawn, but not cached.** `D12Ball.render_match_png`
(`cogs/d12ball/presentation.py`) draws the board as PNG, 2200 x 1302 scaled
1.5x (`d12ball/render.py`), "nearly a megabyte"
([design/rate-limits.md](design/rate-limits.md)). The gate keeps only its
digests (`BoardRefreshState.png_digest`); nothing keeps the bytes, where
the Codex cog keeps its last drawing in `boards_drawn`. So the publisher
has to be handed the bytes where the cog draws them, or draw again.

Boards reach the channel by more than the gate. `refresh_match_image`
edits the persistent board message through `BoardRefresher`, and five paths
post a board as a new message: `post_new_play_board`, `announce_board_update`
(a loose ball, a hand edit), the maneuver's tail in `post_group`,
`announce_game_over`'s final board, and `/d12ball show_game`. Every one but
`show_game` hands the same bytes to the gate as well ("render once, upload
twice"). So the publisher can take the board from `refresh_match_image`
alone and miss nothing that changes the position.

**The log is kept nowhere.** The cog keeps no lines: a `GameResult`'s
groups are rendered (`D12Ball.rendered`) and posted by `present` and
`post_group`, and forgotten. `MatchState.events` is the statistics' record
-- kinds, times, sides, players -- not prose, and nothing may read it to
decide a rule anyway. So, as on the Codex site, the publisher keeps its
own log.

**The web app's journal is the log already, for the web's games.**
`webapp/journal.py` builds "what has been said in each game, as the log
reads it" from each `GameResult`, through `GameService.listeners` -- the
hook the service has for "a game played from two sides" -- with the tokens
intact, after the save and before anything is rendered. The bot's
`GameService` has the same hook, unused. A listener sees every result the
service runs: every click, every AI answer, every resume. It does not see
the setup and lobby moves, a refusal, or the cog's own posts (the abandon
notice), which the lifecycle hooks below cover.

**What a result says in public is a reading with two copies.** An answer's
first block is the answering coach's own for a shootout order and a
shootout pick (`webapp/present.py`, `OWN_FIRST_BLOCK`, `own_block_dropped`);
the cog's `post_ai_answer` drops the same block for the AI by a test of its
own, and posts nothing for a Coaching hub answer that is not **Done**; and
the views decide case by case which answer lines go out publicly
-- `ManeuverActionPromptView` sends "You chose **X**" ephemerally and the
answer's lines publicly. A listener is not told which prompt a click's
result answered (an AI answer's group carries it, `Narration.action`; for
a click the web app tracks it itself, `WebApp._answering`). A publisher
would be the third copy of that reading. Step 1 makes it one, in the model.

**Two things on a result must never reach the publisher's JSON.**
`GameResult.answer` for a shootout order or pick carries the secret first
block; and `Narration.board`, a drawn group's snapshot, is a whole
`MatchState.to_dict()` -- the picks before the reveal
(`offense_maneuver`, `defense_maneuver`), 2.0's decks and hands
(`maneuver_decks`), the shootout orders. The board drawn from that
snapshot is safe -- `render.py` draws no pick, hand or order -- but the
dict itself is never written anywhere. So, as on the Codex site, **the
publisher reads two things: the public lines and the board's bytes.**

**The history is the pins, and the pins are plays, not turns.**
`post_new_play_board` posts and pins a board at every new play -- kickoff,
halftime, the restart after a goal, an own goal, a missed shot or a ball
out of bounds -- with the group's last line as its caption; the final
board is not pinned (`cogs/d12ball/periods.py`). At Discord's 50-pin cap
the oldest board is unpinned (`pin_board_message`). The pins are a jump
list of boards with one line each; no log is pinned. A D12 Ball turn is too
small a unit for a history (several a minute of game clock); a play is the
unit a coach already scrolls by. So the site's history is **play by play**,
an entry a new play: its opening board (the one the bot pinned), its
heading and every line said until the next play.

**The game is on the record, whole.** D12 Ball saves the match
(`data/d12ball_games.json`), so the current board of every game -- being
played, finished or abandoned -- can be drawn at startup from the save,
with no Discord request. Only the log and the earlier plays' boards are
not there.

**A game's number is not an address**, as with Codex. `game_number` is per
guild and is taken again after `/debug reset_channels`; `game_id` is a
uuid4 hex string, the key the bucket and the page use.

**A D12 Ball channel is private; a Codex channel is not.**
`game_channel_overwrites` (`cogs/d12ball/slash_commands.py`) gives a game's
channel to its coaches and the bot, "and nobody else" (and the lobby's
observers). So the Codex site's argument -- the board and the lines are
already public in the channel -- does not carry over: here they are shown
to the two coaches. The author settled it in review (2026-10-17): every
D12 Ball game may be on the site, though its channel is not listed
(decision 3). The site does not change who sees the channel.

**What a game is.** `GameStatus` is `SETUP` (a lobby is `in_lobby` on
one), `IN_PROGRESS` and `FINISHED`; an abandoned game is a `FINISHED` game
with `abandoned=True`. A tutorial is an ordinary solo game against Dinky
whose first five turns are scripted, and a game against the AI has
`player_2_id=None`. A rematch is a new game -- new channel, number and
`game_id` -- and the old channel is archived. `/debug export_archived_games`
writes the archive's games to disk and deletes their channels.

**The coaches' names are on the record**: `player_1_name` and
`player_2_name`, the display names, refreshed on turn prompts;
`formatting.coach_name` reads them, and names the AI.

**What the Codex publisher gives that is not Codex's.** `botkit/objectstore.py`
(the store, R2 and the fake) and `gamekit/storage.py` (the guarded file)
know neither game. Of `cogs/codex_publish/`, `config.py` imports only the
store, and `record.py` only `gamekit.storage`; `keys.py` imports nothing
but spells `codex/`, the site and `.webp`. `queue.py`, `publisher.py`,
`shapes.py`, `segments.py` and `pins.py` import `codex.*` or
`cogs.codex_helpers`. So the leaves are shared already, and the shapes are
the game's own.

## The decisions

Proposed 2026-10-17; the author's answers in review the same day are
written in (decisions 1, 2, 3, 12 and 15). Each is the Codex site's where
it says so.

1. **A Pages project of its own, at `pbd.d12ball.com`, reading a bucket
   of its own.** The project `d12ball-pbd`, rooted in `pbd-d12ball/`
   (static files in `pbd-d12ball/public/`, one Function in
   `pbd-d12ball/functions/data/`), with the custom domain
   **`pbd.d12ball.com`** (the author, 2026-10-17). Its `pages.dev`
   address stays reachable; the pages' canonical link names
   `pbd.d12ball.com`, as the landing pages' name their own domains.
   - **A bucket of its own, `d12ball-pbd`, not a prefix in `pbd`.** The
     site on the game's own domain must not be able to serve Codex's art,
     and a Function bound to the Codex bucket could, given one wrong
     pattern. A bucket of its own makes that impossible rather than
     checked; it is a second token and a second binding, and costs the
     same (the free tier is the account's). Decision 8 of the Codex site,
     one publisher per bucket, then holds as it stands.
   - **Private, as the Codex bucket is**: no custom domain on the bucket,
     no `r2.dev`, no CORS; the Function reads and never writes, and answers
     only the layout's keys.
   - **Under `pbd-d12ball/`, never `pbd/` or `landing/`.** `pbd/` is the
     Codex project's root, and a second project rooted there would compile
     the Codex Function. A sibling folder keeps the two sites' builds apart
     as their watch paths (`pbd/*`, `pbd-d12ball/*`).
2. **Linked from `d12ball.com`** (the author, 2026-10-17: "It can be
   linked on the website"). The D12 Ball page gets a link to
   `pbd.d12ball.com` once the site is live (step 6), worded as the
   address it opens, as the page's other links are
   ([design/landing-pages.md](design/landing-pages.md), "The D12 Ball
   page"). Whether search engines index it is the one question left
   (below); the worksheet keeps the Codex site's `noindex` -- the meta
   tag, `_headers`, the Function -- until the author says otherwise,
   since a linked page is found without a search engine anyway.
3. **Every D12 Ball game is on the site** (the author, 2026-10-17: "All
   d12ball games can be on the website even if the channels aren't
   listed") -- a game against Dinky and a tutorial among them, with no
   opt-out. Only what has nothing to show is left off, as Codex's
   `on_site` leaves it: a lobby, which has no board yet, and a game
   abandoned in its lobby.
4. **The site mirrors the board message.** The board is the persistent
   board message's, the bytes `refresh_match_image` is handed or draws,
   taken in the cog's own forwarder and never in `BoardRefresher`, which
   both bots share (as the Codex site does). The other pictures a play
   posts -- the challenge and shot images, the dice, the field strip, the
   coaching image -- are not on the site at first; the log says what they
   showed.
5. **History is play by play**: an entry per new play, its board the one
   the bot pinned (the bytes `post_new_play_board` posts, never a second
   drawing), its heading, and its lines whole. The current play is the
   lines since the last new play and the current board. A history entry is
   a dict, so a later per-maneuver history adds a field (as Codex's
   decision 5).
6. **The board is PNG, as posted.** The bytes the channel has, named by
   their SHA-256, never re-encoded: a WebP would be a second encode of a
   3300-pixel picture on `K:\` for every board change. Step 3 measures a
   board and a game; if the bucket's size calls for it, WebP is a change
   to one function.
7. **The viewer, the polling and the Function are the Codex site's.**
   `viewer.js` copied byte for byte and held to the Codex copy by a test
   (two Pages roots cannot share a file without a build step, and this
   site has none); `live.json` every 15 seconds while the tab is visible;
   the Function's shape, patterns and headers, under `d12ball/`.
8. **The publisher is a listener and a handful of hooks.** The lines come
   from a listener on the bot's `GameService` (`listeners`), which sees
   every result with its tokens intact; the board from the cog's
   `refresh_match_image` and `post_new_play_board`; the lifecycle --
   Start, the game's end, abandon, rematch, the Archive button,
   `/debug reset_channels` -- from the cog's own methods. Nothing under
   `d12ball/` or `gamesaves/d12ball/` learns it exists.
9. **The public lines are one reading, in the model** (step 1). What a
   result says that every coach may read -- its groups, and its answer
   without the answering coach's own block -- is a function beside
   `pending` in `d12ball/prompts.py`, and `GameResult` names the prompt it
   answered. The web app's journal, `post_ai_answer` and the publisher
   all read it; `OWN_FIRST_BLOCK` moves there. That is the model growing a
   reading so a frontend has no rule of its own (CLAUDE.md, principle 10),
   not a change to the save.
10. **Publishing never fails a turn**, with the Codex site's queue: per
    game, coalesced, one send in flight, the board before `history.json`
    before `live.json`, the boards nothing names deleted, the lists on a
    queue of their own, one ERROR for a run of failures.
11. **It runs only where `FOOLBOT_PUBLISH_*` is set**: the `K:\`
    checkout's `.env`, beside `FOOLBOT_LOG_*` and `FOOLBOT_WEB_*`. A
    developer's test games never reach the site.
12. **The coaches are named as the bot names them** (the author,
    2026-10-17: their Discord names are fine): `coach_name` off the
    record, behind the team's mark, as a message names a side
    (CLAUDE.md, "A side is named by its coach").
13. **A game stays on the site when its channel goes.** The site is the
    archive that outlives `/debug export_archived_games`: the archive list
    is built from the publisher's record, so an exported game's entry,
    board and history stay. `/debug reset_channels`, which drops games
    from the record, takes them off the site and out of the bucket, as
    Codex's reset does.
14. **The look is `d12ball.com`'s.** The night palette's values and the
    bundled IBM Plex from `landing/shared/`, copied into the folder as
    `pbd/` copies the palette -- this is not the landing build -- so the
    page reads as the site that links to it.
15. **The old games are imported from the pins, as the last step** (the
    author, 2026-10-17). Every game played before the site went live
    gets its history from its channel's pinned new-play boards, each with
    its one-line caption, as the Codex site's import does (step 8).
16. **The web app's games are not on this site** (the author,
    2026-10-17: "it's separate"). The web app has its own `/archive`;
    nothing here reads `data/d12ball_web_games.json`, and nothing in
    `webapp/` learns this site exists -- the two systems share the model
    and nothing at runtime ([docs/web-app-next.md](web-app-next.md)).

## What it costs

From Cloudflare's R2 pricing page as the Codex worksheet read it on
2026-10-16 (<https://developers.cloudflare.com/r2/pricing/>): 10 GB of
storage, a million writes and ten million reads free each month, egress
free, deletes free. The free tier is the account's, so the two sites share
it.

**Not measured yet; step 3 measures.** A board is "nearly a megabyte" of
PNG. With superseded boards deleted, a game keeps one board per play plus
the current one. A play count per game is not recorded anywhere this
worksheet found; at an assumed 20 to 40 plays (two kickoffs, halftime,
every goal, every missed shot and ball out of bounds), a game is 20 to 40
MB, and the free storage holds a few hundred games. Writes are a few per
board change.

**The Functions quota is shared with the Codex site.** Pages Functions
requests count toward the Workers free plan's 100,000 a day across the
account (<https://developers.cloudflare.com/pages/functions/pricing/>, read
2026-10-16 for the Codex worksheet); past it Cloudflare answers Error 1027
until midnight UTC. An open game page is about 5,800 requests a day, so
the two sites together hold roughly fifteen pages open around the clock.
`_routes.json` keeps static files off the quota, as on the Codex site.

## The bucket's layout

Under `d12ball/` in the private bucket `d12ball-pbd`, read by the Function
at `https://pbd.d12ball.com/data/d12ball/...`; the Codex site's
rules on whole keys, `ETag`, `304` and `404` hold.

| Key | What | Cache-Control |
| --- | --- | --- |
| `index.json` | The games being played: id, number, name, mode and edition, both sides (coach and team), the score, the half and the clock, whose turn, updated | `no-cache` |
| `archive.json` | `finished` and `abandoned`, each newest first: the same fields, the final score and the winner (a side, or `null` for an abandoned game) | `no-cache` |
| `games/<id>/live.json` | The game as the lists name it, the current play's heading and lines, the current board's key, and the history's version and key | `no-cache` |
| `games/<id>/history.json` | `version`, and `plays`: one entry per finished play -- `heading`, `lines`, `board` | `no-cache` |
| `games/<id>/board-<sha256>.png` | A board, named by its bytes | `public, max-age=31536000, immutable` |
| `emoji/<name>.png` | The pictures the tokens draw as (`d12ball/images/emoji/`), uploaded once a start | `public, max-age=86400` |

Every game is settled -- a shootout decides a draw
([design/shootout.md](design/shootout.md)) -- so a finished game has a
winner; an abandoned one has `null`.

A line is segments, never HTML, as on the Codex site, with D12 Ball's
tokens (`d12ball/tokens.py`):

| Token | Segment |
| --- | --- |
| text between tokens | `{"text": ...}` |
| `{coach:n}` | `{"coach": n, "name": ...}` -- `coach_name`, never a mention |
| `{team:colour}` | `{"glyph": "team", "team": ..., "key": ..., "alt": ...}` |
| `{role:role:team}` | `{"glyph": "role", ..., "key": ..., "alt": "[FB]"}` -- the badge, with its bracketed spelling as the word |
| `{condition:kind}`, `{species:kind}`, `{coin:face}` | `{"glyph": ..., "key": ..., "alt": ...}` |

and `**bold**` and `*italic*` as flags. Which picture a token draws is
`DiscordTokens`' map (`cogs/d12ball_helpers.py`) and its fallbacks; the
segment carries the key, so the page holds no copy of the map. The
segments are found by `tokens.render`, never by a pattern of the
publisher's.

The publisher's own record is `data/d12ball_pbd.json`, keyed by `game_id`:
each game's current play (heading, lines, board key), its history, the
board keys already up, the history's version, whether step 8's import has
run, and when it last changed. The bucket is the copy; the file is the
source.

## The steps

Every step is one branch off an up-to-date `main`, one PR, the suite
green, and a `## Questions for the author` section on the PR even when it
is empty. A step lands by striking its row below
(`| ~~n~~ | ~~title~~ -- landed; ... |`).

| # | Step | Size |
| --- | --- | --- |
| 1 | The public lines: one reading of what a result says to everybody, in the model; the series added | small |
| 2 | The shapes: the record, the keys, the JSON, the segments, the play's heading, the design note | medium |
| 3 | The store, the queue and `FOOLBOT_PUBLISH_*`; a board and a game measured | medium |
| 4 | The hooks: the listener, the boards, the lifecycle, the startup publish, **View live board** | medium |
| 5 | The page: `pbd-d12ball/`, the two lists, the game, the viewer, the Function | medium |
| 6 | Deploy: the bucket, the token, the Pages project, its binding, `pbd.d12ball.com`, and the link from `d12ball.com` | small, most of it in dashboards |
| 7 | Look back once: what the two publishers turned out to share, moved to `botkit/` | small |
| 8 | The old plays, from the pins | small |

Steps 1 to 5 need no Cloudflare: the store has a fake, and the site is
looked at through `scripts/serve_pbd.py --site d12ball` (step 5). Nothing
goes public until step 6. Step 8 is last because the import runs behind
everything else -- the startup publish, the queue, the live site -- and is
the one step that spends Discord requests.

### Claiming a step

`scripts/claim_web_step.py --series d12pbd <n>` claims step `n` as the
branch `d12pbd-step-<n>` for a PR titled `D12 PBD step <n>: ...`. **Step
1's prompt adds the series**: one entry in `SERIES`
(`"d12pbd": ("docs/d12ball-pbd-site.md", "d12pbd-step", "D12 PBD step")`),
plus the `--series` help string and the module docstring, which list the
series by hand ("Six series" becomes seven).

## Preamble

Every step's prompt starts with this block.

```text
You are working in the fool-bot repository on the D12 Ball games' web
page planned in docs/d12ball-pbd-site.md. Read that worksheet first,
then the design note docs/design/d12ball-pbd-site.md if it exists, then
docs/design/pbd-site.md -- the Codex site this one is modelled on --
at the sections a step names. Do not read the rest of docs/design/
unless a step names a file.

Start on the branch the claim script made (git fetch && git checkout
d12pbd-step-<n>), off an up-to-date main. Never work on main.

The publisher is fool-bot's frontend, like the cog: it decides no rule,
words nothing and draws nothing, and nothing under d12ball/ or
gamesaves/d12ball/ learns that it exists. It reads two things -- the
public lines (step 1's reading over a GameResult) and the board's bytes
(the cog's render_match_png) -- and nothing secret: never a GameResult's
raw answer, never Narration.board's dict, never a pick, a hand or a
shootout order. Publishing never fails a turn, never blocks a click, and
spends no Discord request except in step 8. It runs only where
FOOLBOT_PUBLISH_* is set. The web app's games are not on the site: nothing
reads the web app's files, and nothing in webapp/ learns the site exists.

The site is its own Cloudflare Pages project rooted in pbd-d12ball/
(static files in pbd-d12ball/public/, one Function in
pbd-d12ball/functions/), never under pbd/ or landing/, served at
pbd.d12ball.com. Plain HTML, CSS and JavaScript, no
framework, no CDN, no build step. Every line is built with textContent,
never innerHTML.

Run python3 -m unittest discover -s tests before the PR; a full run must
not create data/. The four goldens and tests/test_model_purity.py stay
green unchanged unless the step says otherwise. The PR carries a
## Questions for the author section, even if empty, and strikes this
step's row in docs/d12ball-pbd-site.md. What a step settles goes into
docs/design/d12ball-pbd-site.md with the reasoning; a row in CLAUDE.md's
tables only for a new module or a new hard rule.
```

### 1. The public lines

```text
Step 1 of docs/d12ball-pbd-site.md. Read docs/design/game-service.md at
"The AI" and docs/design/model-discord-split.md at "Tokens".

Add the series: "d12pbd": ("docs/d12ball-pbd-site.md", "d12pbd-step",
"D12 PBD step") in scripts/claim_web_step.py's SERIES, its --series help
string and its module docstring ("Six series" becomes seven).

Make "what does this result say to everybody" one reading, in the model.
Today it is webapp/present.py's OWN_FIRST_BLOCK and own_block_dropped,
the cog's post_ai_answer dropping the same block by a rule of its own,
(and skipping a COACHING_HUB answer that is not "done"), and
webapp/server.py tracking which prompt a click answered (_answering)
because a GameResult does not say.
- GameResult (gamesaves/d12ball/service.py) names the prompt kind it
  answered, where it answered one: set in apply_action and wherever run
  answers for the AI, None for a run_step or a resume. Its to_dict
  writes it (d12ball/wire.py's rules: one-way, not a save).
- OWN_FIRST_BLOCK moves to d12ball/prompts.py beside asked_sides, with
  public_lines(result) or its equivalent over the answer and the groups,
  in order, tokens intact. webapp/present.py and webapp/journal.py read
  it (webapp may import the model); post_ai_answer reads it.
- Survey every view under cogs/d12ball_views/ that posts result.answer
  and check each posts publicly exactly what the reading calls public --
  list them in the PR. A view that posts something publicly the reading
  calls secret, or the other way round, is a question for the author,
  not a fix.

Nothing the bot or the web app sends changes: the three cog goldens,
test_golden_service.py and the web app's tests stay byte for byte. Add a
test over every PromptKind with an answer (tests/prompt_fixtures.py):
the shootout's first block left out, everything else kept.
```

### 2. The shapes

```text
Step 2 of docs/d12ball-pbd-site.md. Read docs/design/pbd-site.md at "The
bucket's layout", "A line is segments, not HTML" and "The log is the
publisher's file, not the game's".

Create cogs/d12ball_publish/ (a package the cog calls, not a mixin),
copying the shapes of cogs/codex_publish/ rather than importing them --
the worksheet's step 7 looks back once both exist:
- record.py: PublishRecord over data/d12ball_pbd.json through
  gamekit/storage.py, its own two failure flags; per game (PublishedGame,
  to_dict/from_dict, every field defaulted): the current play's heading,
  lines and board key, the history (a list of dicts: heading, lines,
  board), the board keys up, the history's version, imported, updated.
  Keyed by game_id. No mkdir on load; a save never raises.
- keys.py: every key under d12ball/, the board as board-<sha256>.png,
  the site's address as one constant, https://pbd.d12ball.com.
- shapes.py: on_site (every game that has started, a tutorial and a game
  against Dinky included; a lobby and a game abandoned in its lobby
  left off -- decision 3), index_entry, archive
  (finished and abandoned), live, history. Sides by coach_name and
  team_display_name, never a team's name alone where a coach holds the
  side; the score, the half and the clock as values; mode by
  GAME_MODE_NAMES, edition by its own name. Nothing from
  MatchState.to_dict passes through.
- segments.py: a line with D12 Ball's tokens (d12ball/tokens.py) as
  segments -- the worksheet's table -- found with tokens.render as
  DiscordTokens finds them; {coach:n} the coach's name, never a mention;
  a glyph carrying the key of the picture DiscordTokens draws, or its
  fallback word.
- The play's heading: what a history entry and the current play are
  headed with -- the half, the clock and the score at the new play, and
  what opened it (kickoff, halftime, a goal, a miss, out of bounds). It
  is wording, so it is the model's: a function in d12ball/formatting.py
  over the match, tested there, not built in the publisher. If the
  step finds the model has no way to say what opened a play without
  reading the event log, stop and ask.

Tests: tests/test_d12ball_publish_shapes.py -- a staged match's shapes
(tests/roster.py names players by role), a line with every token kind,
a coach's name holding < and ** coming through as text, a tutorial on
the site and a lobby off it, nothing in any shape that names a pick, a hand or a
shootout order, the record's round trip and a corrupt file.

Create docs/design/d12ball-pbd-site.md, the design note, and add the
worksheet, the package and the note to CLAUDE.md's map and its "Read
this before touching" table.
```

### 3. The store, the queue and the variables

```text
Step 3 of docs/d12ball-pbd-site.md. Read docs/design/pbd-site.md at "The
store", "The queue" and "Turning it on".

botkit/objectstore.py is used as it stands. Add
cogs/d12ball_publish/queue.py as cogs/codex_publish/queue.py is, copied
and changed only where the game differs: D12 Ball's statuses
(IN_PROGRESS; FINISHED with abandoned), PNG boards, plays rather than
turns. Every rule of the Codex queue holds -- one send in flight a game,
a change during a send sent after it, the board then history.json then
live.json, the JSON put only when its digest changed, a board nothing
names deleted after the live.json that stopped naming it, the lists on
one queue of their own, a WARNING a failure and one ERROR for a run.
The archive list is built from the publisher's record, not the bot's
games, so a game exported by /debug export_archived_games stays listed
(decision 13).

cogs/d12ball_publish/config.py: FOOLBOT_PUBLISH_ACCOUNT_ID,
FOOLBOT_PUBLISH_ACCESS_KEY_ID, FOOLBOT_PUBLISH_SECRET_ACCESS_KEY,
FOOLBOT_PUBLISH_BUCKET (default "d12ball-pbd"); off, said once at INFO,
where any is missing or boto3 is not installed. Never fall back to
CODEX_PUBLISH_*: a different bucket, a different token. Write them into
docs/design/collaboration.md beside the other FOOLBOT_* credentials.

Measure, and write the numbers into the design note and the worksheet's
"What it costs": a board's size from scripts/render_sample.py at each
board size and tier, and the plays in a whole game from
tests/test_driver_full_game.py's seeded game.

Tests: as the Codex queue's -- coalescing, a failing store not raising,
a board not uploaded twice, the order, a replaced board deleted and a
history board kept, two games' list changes ending with the newer list,
the ERROR once, off without the variables or boto3 -- and an exported
game still in archive.json.
```

### 4. The hooks

```text
Step 4 of docs/d12ball-pbd-site.md. Read docs/design/pbd-site.md at "The
hooks" and "Startup", docs/design/rate-limits.md, and
docs/design/game-service.md at "One door".

Build the publisher in the D12Ball cog's cog_load where config hands back
a store; None elsewhere, every call site reading `is not None`.
- The lines: a listener on the cog's GameService, attached where the
  service property builds it, so a service rebuilt over a new engine or
  games dict keeps it. It reads step 1's public lines and nothing else
  of the result, keeps them with their tokens, and starts a new play
  where a group is a new play (Narration.new_play). It awaits nothing:
  the record changes at once, the send is the game's own task.
- The boards: refresh_match_image (cogs/d12ball/presentation.py) hands
  the publisher the bytes it was given or draws -- the cog's forwarder,
  never BoardRefresher -- and post_new_play_board hands the new play's
  opening board. Where refresh_match_image would draw, the publisher
  takes those bytes; it never draws a board a second time on a click.
- The lifecycle, from the cog's own methods: Start (lobby_start), the
  game's end (announce_game_over, with the final board it posts), the
  abandon (/d12ball abandon_game), the rematch (start_rematch: the old
  game archived, the new one listed when it starts), /debug
  reset_channels (the dropped games off the lists and out of the bucket,
  after both lists are up). /debug export_archived_games changes nothing
  on the site (decision 13).
- Startup: a task from cog_load. Every game on the site the record has
  no current board for gets one, drawn from its saved match through the
  same render_match_png, one at a time in asyncio.to_thread; a game
  whose board is up is not drawn. Then the emoji, then both lists.
- View live board: a link button to the game's page on the persistent
  board message, where the publisher is on, riding on the view the gate
  keeps so it costs no request -- beside the full-image link, which is
  re-cut by the gate; check the two together in
  cogs/d12ball_helpers.py's add_full_image_button and the gate's
  settle_link.

Tests, through the real cog as EveryMatchupResolvesTests and
TutorialPlaythroughTests drive it, with a MemoryStore and
tests/save_patches.py: a seeded game publishing one history entry per
new play, each with the board the pin carried; the shootout's orders
never in any object; an AI game's answers in the log; a tutorial
published like any other game; a finished game and an abandoned one in
the archive; a reset taking games off; the publisher off sending
nothing; and the
requests a click spends unchanged.
```

### 5. The page

```text
Step 5 of docs/d12ball-pbd-site.md. Read docs/design/pbd-site.md at "The
page", "The viewer", "The Function" and "Looking at it", and
docs/design/landing-pages.md at "The night palette, because a page is a
screen" and "The D12 Ball page".

Add pbd-d12ball/, the Pages project's root, as pbd/ is: index.html (the
games being played, then the archive's finished and abandoned),
game.html at /game/<game_id> by a _redirects rewrite, d12ball.js,
viewer.js, d12ball.css, _headers (noindex), _routes.json (/data/* alone),
and functions/data/[[path]].js answering only the layout's keys under
d12ball/. viewer.js is pbd/public/viewer.js byte for byte. The look is
d12ball.com's: the night palette's values and IBM Plex copied from
landing/shared/, a header linking back to d12ball.com, each page's
canonical link on https://pbd.d12ball.com.

The game page: the board in the viewer; above it, the score, the half
and the clock as the jumbotron would say them, from live.json; the log
column -- the current play, then the earlier plays newest first, each
its heading, its lines and its board as a thumbnail -- with the Codex
page's toggle and divider.

Extend scripts/serve_pbd.py with --site codex|d12ball (codex the
default, so nothing that runs it today changes), and --stage writing a
D12 Ball sample through step 2's shapes and render.py's boards: a game
being played with plays behind it and a coach whose name holds markup,
a game finished on a shootout, one abandoned. Take the page at desktop,
iPad (touch emulated) and phone, the log open and closed, zoomed and
fitted, in standard and advanced, and put the pictures in the PR.

tests/test_d12ball_pbd_site.py: as tests/test_pbd_site.py -- the files,
the routes, the noindex, the rewrite, every key keys.py writes matching
one of the Function's patterns and near misses matching none, no
innerHTML -- and viewer.js identical to pbd/public/viewer.js, and no
pattern of the Function's matching a codex/ key.
```

### 6. Deploy

The repository half is small; the dashboard half is the author's, run as
the Codex site's checklist ([design/pbd-site.md](design/pbd-site.md),
"The checklist") with these differences:

1. **The bucket** is `d12ball-pbd`, private, Standard storage.
2. **The token** is a new one, *Object Read & Write*, **this bucket
   only**, into the `K:\` `.env` as `FOOLBOT_PUBLISH_*`. Never the Codex
   token: each reaches its own site's data and nothing else.
3. **The Pages project** `d12ball-pbd`: root directory `pbd-d12ball`,
   build command `exit 0`, output `public`, preview deployments *None*,
   build watch paths `pbd-d12ball/*`.
4. **The binding** `PBD` to the bucket `d12ball-pbd`, for Production, and
   the deployment retried after adding it.
5. **The custom domain**: Custom domains -> *Set up a custom domain* ->
   `pbd.d12ball.com`. The zone is on the same account, so Cloudflare adds
   the record; a record made by hand first gets a 522.
   `play.d12ball.com`'s record is the tunnel's and is not touched.
6. **Check** from a phone off the home Wi-Fi: `pbd.d12ball.com` loads, a
   game changes as it is played, `/data/d12ball/index.json` answers,
   `/data/codex/index.json` and `/data/anything-else` answer `404`, and
   `d12ball.com`, `play.d12ball.com` and `propheticfools.com` are as
   they were.
7. **Restart fool-bot** (`update_main_bot.ps1`); its log says the games
   are published, or names the missing variable.

```text
Step 6 of docs/d12ball-pbd-site.md.

Write the checklist into docs/design/d12ball-pbd-site.md, "Deploying",
as docs/design/pbd-site.md's is written.

Link the site from d12ball.com (decision 2): read
docs/design/landing-pages.md at "The D12 Ball page" and "Redirects", and
add a link to https://pbd.d12ball.com on the D12 Ball page, worded as
the address it opens, as the page's other links are. Build the site
(python3 scripts/build_landing.py --only d12ball) and look at it at
desktop and phone widths; tests/test_landing_build.py stays green. The
landing site's own rules hold: no rule worded, nothing drawn.

The dashboard half is the author's; the link lands only once the site
answers, so this step's PR merges after the checklist has been run.
```

### 7. Look back once

```text
Step 7 of docs/d12ball-pbd-site.md. Read docs/design/codex.md at "What
the two games share".

Compare cogs/codex_publish/ with cogs/d12ball_publish/. What turned out
the same apart from names -- most likely the queue's machinery, the
record's file handling, the config reader, serve_pbd.py's server, and
the pins' reading, which step 8 then writes against --
moves to botkit/publish/ (it knows neither game), each package keeping
its own names by re-export, both sites' tests unchanged. What differs by
game stays each game's. Byte for byte what each bucket receives is
unchanged; the queue tests of both prove it. If less than a module's
worth is shared, say so and move nothing.
```

### 8. The old plays, from the pins

The last step (decision 15): every game played before the site went
live gets a history from its pins. The pins hold boards with a one-line
caption and no log, so an imported play is its board and that line.

```text
Step 8 of docs/d12ball-pbd-site.md. Read docs/design/pbd-site.md at "The
old turns".

On startup, after step 4's publish, for every game on the site whose
record says its import has not run: list its channel's pins, keep the
bot's own messages whose board is named exactly d12ball-pbd<that game's
number>.png (board_image_filename), oldest first, and write each before
the earliest play the record holds, its caption read back into the
model's tokens (a mention as {coach:n}, an emoji as its token). The pin
cap means a long game's earliest plays may be gone; the history says
where it starts. A channel gone or unreadable marks the import done for
good, as on the Codex site. One channel at a time, behind the queue,
never during a click; the requests counted at INFO.
```

## Questions the author answered

Raised in this worksheet's review and answered on 2026-10-17.

1. **Which games go on the site**: every D12 Ball game, though its
   channel is private (decision 3).
2. **The address**: `pbd.d12ball.com` (decision 1), not a subdomain of
   `propheticfools.com`.
3. **Unlisted or linked**: linked from `d12ball.com` (decision 2).
4. **The coaches' Discord names**: fine (decision 12).
5. **The games already played**: imported from the pins, as the last
   step (decision 15).
6. **The web app's games**: not on this site; it is separate
   (decision 16).

## The question still open

1. **Search engines.** The site is linked from `d12ball.com`; should its
   pages be indexed? The worksheet keeps the Codex site's `noindex` until
   the author says otherwise -- coaches' Discord names on a page a search
   engine files are one step further than a page a link opens.

## What is not in these prompts, on purpose

- **The web app's board.** `webapp/board.py` lays the position out as
  HTML from the same rules the PNG asks; the site could draw that instead
  of a picture. It would tie this site to the web app's page, which is a
  system of its own; the PNG mirrors the channel, which is the ask.
- **The challenge, shot and dice images.** Decision 4; the log says what
  they showed.
- **Per-maneuver history.** Decision 5 leaves room for it.
- **Statistics.** `d12ball/stats.py` reads the event log for
  `/d12ball stats`; a page of them is a later step if wanted.
- **The web app's games.** Decision 16.
- **Who is looking.** No sign-in; linked, not private.

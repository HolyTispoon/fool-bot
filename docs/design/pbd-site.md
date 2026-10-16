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
| `codex/archive.json` | `shapes.archive` over `archive_entry` | The finished and abandoned games, the same fields, `status` and `winner` |
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

# The box, the sale sheet and the playtest card

Design notes for fool-bot; the map is [CLAUDE.md](../../CLAUDE.md), the rules
are [living-rules.md](../living-rules.md).

`d12ball/box_art.py` draws the five printed things that are *around* the game
rather than in it, and `scripts/render_box_art.py` is its CLI:

```bash
python3 scripts/render_box_art.py --out box/
python3 scripts/render_box_art.py --bleed --pdf
python3 scripts/render_box_art.py --only sale-sheet --contact "you@example.com"
```

| Panel | Size | What it is |
| --- | --- | --- |
| `box-cover.png` | 11.375in square | The lid: the title, four players, the ball, the facts |
| `box-side.png` | 11.375 x 2.75in | One wall -- and all four, since the box is square |
| `box-bottom.png` | 11.375in square | What is in the box, how a turn goes, a picture of the game |
| `sale-sheet.png` | letter | One page for a buyer or a convention table |
| `playtest-card-front/back.png` | 6 x 4in | The board on the front, the survey QR on the back |

`box/` is generated output and is gitignored, like `cards/`, `print/` and
`print-and-play/`. Run it again when the game under it changes; don't keep a
stale copy.

## Nothing here is a component, and that is the whole difference

The printed boards follow `cards.py` -- dark ink on a light face -- because a
board is printed at home and read at the table, and a dark board is the wrong
thing to hand a printer (see [printed-boards.md](printed-boards.md)). None of
these five is played off, so that reasoning does not carry, and the palette
splits along what each one is for:

- **The box is drawn in the bot's own night palette**: `ZONE_COLORS` and
  `TEAM_COLORS` imported from `render.py` rather than restated, so a cover and
  the board a coach sees in Discord are the same greys and the same four team
  hues by construction. A box is manufactured once and has to be found on a
  shelf; ink economy is somebody else's problem and the dark is the game's own
  look.
- **The sale sheet and the back of the playtest card are paper**, the
  maneuver cards' palette exactly as the boards borrow it, because both are
  things somebody prints on an office printer and hands over. The sale sheet's
  header band is the box's night, so the page and the box read as one game.

## The box is cut for the board, not chosen

`box_inches()` is the field board folded once plus a clearance: the board is
tabloid, folds across its long side to 11 x 8.5in, and the wider of those two
is what the box has to clear. That makes the footprint square at 11.375in --
`folded_board_inches` and `BOX_CLEARANCE_INCHES` are the whole derivation, and
`test_every_paper_the_boards_print_on_still_folds_into_a_box` holds it for
every paper `boards.py` prints on. The depth is the one measurement with
nothing to read it off; `BOX_DEPTH_INCHES` is the author's call and says so.

**The four faces are separate files with their own bleed, not a lid wrap.**
A wrap's die-line -- turn-ins, corner reliefs, how far the art folds over --
belongs to whichever manufacturer prints it, and a die-line drawn here would
be a guess at somebody else's template. What a printer is handed is a panel
per face at trim plus an eighth of an inch.

## A panel measures in inches, and the bleed moves the origin

`Panel` is the geometry: width and height in inches, and `x()`/`y()` from the
**trim** corner. With `bleed` the canvas grows by an eighth of an inch on
every side and the origin moves into it, so the art is drawn past the trim
rather than a border being added around a finished panel -- a flat margin
around a gradient is a visible seam where the knife lands. `Panel.pixels`
rounds the trim and the bleed separately, so the trimmed panel is the same
number of pixels whether a bleed was asked for or not.

The unit is the inch throughout, as on the team board and for the same reason:
`Sheet.u`'s thousandths of a sheet's width are right for a layout that scales
whole between paper sizes and wrong for a panel whose size is fixed by a box.
What is borrowed from `boards.py` is `Sheet` itself and the inch-measured type
(`print_font`, `draw_fitted`), not the unit.

## The box may not word a rule for itself

Every sentence on these panels that states a rule is **quoted from the Charter
or the Learn to Play, word for word**, and `BoxArtQuotesTests` fails if the
words drift out of either book. It is the same guarantee the printed boards
get from reading their layouts out of `basic_rules.json`, applied to sentences
instead of numbers -- the hook, the tagline, the three beats of a turn and the
four selling lines are all the books' own, and each beat cites the Law it is
taught under.

The rest is read the same way:

- **The component list is the Learn to Play's own "What is in the box"**,
  parsed out of the markdown. Its sentences addressed to the reader of that
  book -- "This book plays the 7-space board" -- are dropped, because a box is
  not the book and the sentence is false the moment it is read off one.
- **The blurb is Law 1**, which is the back of the box whether it meant to be
  or not.
- **Every number is `BoxFacts`**, read off the catalogs: the coaches are
  `len(TeamSide)`, because "how many coaches" and "how many sides" are the same
  question and only one of them has an answer in the code; the fielded six are
  the standard deal's own role counts.
- **The picture of the game is `render_match_image`'s own output** for a
  standard deal, not a photograph and not a second drawing of the board. What
  is printed on the box is what a coach actually sees, and a change to the
  board reaches the box by re-rendering.

## What the box deliberately does not say

**No playing time and no age rating.** Both are retail claims and nothing in
this repository measures either. The thirty minutes the game is played over is
fifteen space minutes a half on a clock that never stops -- it is not a wall
clock, and printing it as one would be the box lying about the product.
`RetailClaims` is where both go once somebody has sat at a table with a
stopwatch: pass `--play-minutes` and `--min-age` and the chips appear on the
cover and rows appear in the sale sheet's glance table; pass neither and they
are left off rather than guessed at. It is `fitted_print_font`'s rule about a
caption it cannot draw legibly, applied to a claim nobody can check.

**No contact details on the sale sheet unless given.** `--contact` fills the
answer panel; with nothing given it is ruled and empty. An address nobody has
supplied is the one thing on that page that could be wrong in a way none of
this could catch.

**The barcode is a reserved area, not a barcode.** `BARCODE_INCHES` is an
EAN-13 at its nominal 37.29 x 25.93mm, printed white and labelled. The number
belongs to whoever publishes the game, and a barcode that scans as something
else is worse than a blank.

## The cover's four

`COVER_CAST` is four player names with a facing, and it is the only art
direction written into the module. Everything else about them is read: the
portraits come from `load_player_portrait`, and each one's colour from the
first team whose sheet they are on (a player's colour team and their species
team share a hex, so which is found first cannot change the answer).

**Facing is why the names are written down.** The portraits carry squad
numbers, so the art cannot be mirrored to make somebody face the other way --
a flipped number is a number nobody wears. Two face each way, one player of
each of the four species, and `CoverCastTests` fails if a roster revision
renames one of them or if the four stop being two and two.

The back rank is **darkened rather than faded** (`into_the_dark`): a cut-out
at reduced opacity shows the sky through the middle of a player, where the
same one darkened reads as somebody standing further away in the same light.
Each figure's centre is clamped so its measured width stays inside the trim --
these cut-outs are as wide as they are tall, a share of the panel's width says
nothing about where an arm ends, and Pillow crops what falls off the canvas
without a word.

## The survey code

The playtest card's back carries a QR of `SURVEY_URL`, and the address is
**printed under it as well**: a code is one smudge away from being nothing, and
a card whose only route to the survey is optical fails quietly. The URL has no
spaces, so it is broken by `draw_hard_wrapped` -- `wrap_text` breaks on spaces
and, handed an address, returns one line and draws it off the edge of the
panel without a word.

- **The code is drawn module by module** onto the panel rather than generated
  as a PNG and scaled: a resize lands module edges between pixels and softens
  exactly the contrast a scanner is looking for. `test_what_is_drawn_is_what_
  was_encoded` reads every module back off the drawn panel at its own centre
  and compares it with the encoder's matrix, because a QR is unreadable to
  everyone who looks at the render.
- **`QR_MIN_MODULE_INCHES` is 0.4mm**, the floor a phone reads reliably off an
  office printer. The card's own code comes out at 0.86mm; a longer URL makes
  a denser code at the same printed size, so the test is what catches an
  address that has quietly grown past what the card can carry. Change the URL
  with `--survey-url`.
- **`qrcode` is imported inside the function**, not at the top of the module.
  It is pinned in `requirements.txt`, but the bot imports this package and the
  only thing in it that needs a QR encoder is a card nobody renders from the
  bot -- a checkout that has not reinstalled its requirements should still
  load everything else. A missing package raises with the install line in it.

## Looking at them

The suite checks claims and geometry; it cannot see a picture, exactly as it
cannot see the bot's board or the printed ones. **Look at the image** --
`scripts/render_box_art.py --out box/` writes all six files and reports the
box's own dimensions and the QR's module size.

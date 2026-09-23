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
| `box-cover-night.png` | 11.375in square | The same cover for a screen, not for the printer |
| `box-side.png` | 11.375 x 2.75in | One wall -- and all four, since the box is square |
| `box-bottom.png` | 11.375in square | What is in the box, how a turn goes, a picture of the game |
| `sale-sheet.png` | letter | One page for a buyer or a convention table |
| `playtest-card-front/back.png` | 6 x 4in | The board on the front, the survey QR on the back |

`box/` is generated output and is gitignored, like `cards/`, `print/` and
`print-and-play/`. Run it again when the game under it changes; don't keep a
stale copy.

## Everything is printed on white, and nothing is printed dark

The first cover was drawn in the bot's night palette, because that is
where the game's look already lives. **It is not printable.** A
full-bleed dark cover is a solid across every panel of the wrap at
once, which is the most expensive thing a print run can be asked for
and the first line a quote comes back high on -- the author's call,
made on the first render, and it is now the constraint the whole set
is drawn under.

So these five follow `boards.py` and `cards.py` after all: **dark ink
on a light ground**, and what carries the game's look is the art, the
four team colours and the type. `PrintedInWhiteTests` samples the four
corners of every printed panel and fails if any of them is inked,
because a gradient or a scrim creeping back in looks fine on a screen
and turns up on a quote.

**The ground is white, not the cards' and boards' cream.** `FACE_COLOR`
is what a component is printed on; a page is a page. It is deliberately
not imported here, and `PANEL` is a neutral grey rather than the cards'
warm one for the same reason. The one thing that keeps the cream is the
picture of the printed board, because that is the board, photographed
rather than restyled.

The gold the jumbotron's clock is drawn in (`#f0b429`) disappears into
white paper at text sizes, so `ACCENT` is the same hue taken down far
enough to be read on it.

**The night cover survives as one file, `box-cover-night.png`.** It is
the same layout in `NIGHT_COVER` rather than `PAGE_COVER` -- a
`CoverPalette` is the only difference between them, so a change to the
cover is a change to both -- and it is for a post, a store page or a
header, where ink costs nothing. The CLI says so as it writes it. The
two palettes differ in more than colour: the night cover carries the
glows behind the title, the ball and each figure, which are light and
therefore a screen's; and the back rank is washed towards the dark
rather than towards the page, at a full share rather than a half one,
because white haze eats a figure much faster than dark does.

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
- **The picture of the game is the printed field board**, with meeples on it
  at the standard deal and the ball on the kickoff space -- see "The picture
  of the game" below.

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

## The picture of the game

`board_photo` is `boards.render_field_board`'s own board with pieces set on
it. It was the bot's `render_match_image` at first, which was wrong twice
over: that board is a screen's -- dark, and therefore the same press problem
as the cover -- and what somebody buying this game will have on their table
is the printed one. So the box shows the printed one.

- **It is the real board, not a drawing of one.** The panel is rendered by
  `render_field_board` and pasted into a `Sheet` of its own size, which is
  what lets `FieldGeometry.for_sheet` say where every space is without a
  second copy of the layout. A layout change upstream moves the meeples with
  it.
- **The deal is `MatchState.standard`'s** and the sides are read with
  `side_for_player`, so the picture cannot show a formation the game does not
  deal. Home stands on the near half of a space and the visitors on the far
  half: a space belongs to nobody, and the only thing dividing it is which
  coach is reaching across the table.
- **The crop stops inside both zone-assignment rows.** The board is portrait
  and most of its length is those two card rows -- and the visiting coach's is
  printed upside down, which is right on a table and a mistake in a picture.
  `strip_only` cuts further, to the spaces and the range bracket alone, for a
  panel much wider than it is tall (the playtest card's front).

### The meeples

**A meeple is the piece, drawn as a piece**: the classic silhouette, in its
team's colour, with the player's role on its chest -- the same thing the
Screentop table puts on the board, which is what a coach recognises. The bot
draws a player as a coloured disc with a label in it, which is right on a
screen and wrong on a picture of a tabletop: a disc is a token, and what
stands on a printed board is a pawn.

The two letters are `ROLE_INITIALS`, the spelling every other drawing of a
role reads, and their colour is `high_contrast_ink`, because white
disappears on slime green. Drawn rather than bundled as art, so a meeple
comes out at whatever size a panel leaves and takes its colour from
`TEAM_COLORS` like everything else.

### The die

**The ball is a d12, so it is drawn as one**: `d12_art` builds a regular
dodecahedron, turns it, and fills the six faces that are towards the reader
by how square each one is. It replaced a flat twelve-sided polygon, which is
a badge rather than a die.

- **The face list is computed, not tabulated.** A face is the five vertices
  furthest along its own normal, wound around it; sixty indices written out
  would be sixty chances to transpose two of them with no way to notice.
- **The dual matters.** The twelve face normals are the `(0, ±φ, ±1)` family,
  not the `(0, ±1, ±φ)` one -- the same icosahedron turned, and against these
  vertices its "faces" are five points that are merely near each other. The
  first build used it and produced a lump nobody would call a die.
  `test_every_face_is_flat` is that bug as an assertion.
- **The number goes on whichever face is squarest to the reader**, sized to
  that pentagon, and on the board picture it shows the ball's **speed** read
  off `match.ball.speed` rather than a 12 -- which is the whole of what the
  face means (Law 7).

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

The suite checks claims, geometry, the corners for ink and the die for
flatness; it cannot see a picture, exactly as it cannot see the bot's board or
the printed ones. **Look at the image** --
`scripts/render_box_art.py --out box/` writes all seven files -- six printed
panels and the night cover -- and reports the box's own dimensions and the
QR's module size.

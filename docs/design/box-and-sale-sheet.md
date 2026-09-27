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

None of it has tests -- the print materials carry none (the author,
2026-09-23) -- so what follows is checked by rendering and looking; see
"Looking at them".

| Panel | Size | What it is |
| --- | --- | --- |
| `box-cover.png` | 11.375in square | The lid: the title, four players, the facts |
| `box-cover-night.png` | 11.375in square | The same cover for a screen, not for the printer |
| `box-cover-original.png` / `-night.png` | 11.375in square | The same two covers with the first cast on them |
| `banner.png` / `banner-night.png` | 3000 x 1200px | The same art laid out wide, for a Notion page |
| `screentop-banner.png` / `-night.png` | 1280 x 720px | The same again at the size a Screentop table asks for |
| `box-side.png` | 11.375 x 2.75in | One wall -- and all four, since the box is square |
| `sale-sheet.png` | letter | One page for a buyer or a convention table -- **and the box's underside, for now** |
| `playtest-card-front/back.png` | 6 x 4in | The board on the front; the box cover and the survey QR on the back |

Every piece that comes in two grounds follows one spelling: `<name>.png` is
the page one and `<name>-night.png` the screen one -- the cover, the wide
banner and the Screentop banner all come in both.

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
four team colours and the type. Check the corners of every printed panel
for ink after a change, because a gradient or a scrim creeping back in looks
fine on a screen and turns up on a quote.

**The ground is white**, `cards.PAPER` -- which the printed boards and
the rulebooks went to as well on 2026-09-27; they were the cards' cream
until then, and the box was white first. `PANEL` is `cards.PAPER_PANEL`,
a neutral grey rather than the cards' warm one, for the same reason. The
picture of the printed board is the board as printed, photographed
rather than restyled, so it is white now because the board is.

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
it has to hold for every paper `boards.py` prints on. The depth is the one measurement with
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
or the Learn to Play, word for word**, and a change to either book means
checking the quoted lines are still in it. It is the same guarantee the printed boards
get from reading their layouts out of `basic_rules.json`, applied to sentences
instead of numbers -- the hook, the tagline, the three beats of a turn and the
four selling lines are all the books' own, and each beat cites the Law it is
taught under.

The rest is read the same way:

- **One line is in the box's own voice, and it is named.** `STRAPLINE` -- "a
  fast playing fantasy sports game of some strategy, a lot of tactics, a
  little luck and a bucket of d12s" -- is the author's, and it is allowed
  because it states no rule: it says how the game plays. It is the exemption
  rather than a hole in the rule, so it is one constant with a date on it.
- **Every number is `BoxFacts`**, read off the catalogs: the coaches are
  `len(TeamSide)`, because "how many coaches" and "how many sides" are the same
  question and only one of them has an answer in the code; the fielded six are
  the standard deal's own role counts.
- **The picture of the game is the printed field board**, with meeples on it
  at the standard deal and the ball on the kickoff space -- see "The picture
  of the game" below.

## What the box says that this code cannot work out

**A playing time and an age rating are printed, and neither is measured
here.** Nothing in this repository can time a table or judge a ten-year-old,
and the thirty minutes the game runs over is fifteen space minutes a half on
a clock that never stops -- not a wall clock, and printing *that* as one
would be the box lying about the product. So the two live in one dated
constant, `DEFAULT_CLAIMS`: **two players, 30-45 minutes, ages 10+, the
author's own, 2026-09-23**. They are printed because somebody who has run the
table said so. `RetailClaims()` carries nothing and prints nothing, which is
what any *other* claim gets until a person supplies it, and
`--play-minutes` / `--min-age` override the defaults.

Those three are the whole of the cover's copy under the art:
`retail_chips` is how many players, how long, and how old, and nothing else.
What is in the box is on the sale sheet, which is the underside for now --
see "There is no underside" below.

**No contact details on the sale sheet unless given.** `--contact` fills the
answer panel; with nothing given it is ruled and empty. An address nobody has
supplied is the one thing on that page that could be wrong in a way none of
this could catch.

**There is no barcode any more.** It was a reserved area on the underside --
an EAN-13 at its nominal 37.29 x 25.93mm, printed white and labelled, since
the number belongs to whoever publishes the game and a barcode that scans as
something else is worse than a blank. It went with the panel that carried it
and wants a home when a real underside is drawn.

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

**A meeple is the piece, drawn as a piece**: the author's own outline, in its
team's colour, with the player's role on its chest -- the same piece the
Screentop table puts on the board, which is what a coach recognises. The bot
used to draw a player as a coloured disc with a label in it; since 2026-09-25
it draws this same piece too (see "A meeple is the Screentop piece" in
[board-image.md](board-image.md)).

**`MEEPLE_PATH` is the Screentop table's own SVG path**, and `flatten_path`
reads it. Both live in `render.py` and `box_art.py` imports them, so the box,
the bot and the table are one outline. The first version was a polygon traced by eye off a screenshot and
it looked like a gingerbread man -- the arms too straight, the piece as wide
as it was tall. Reading the path is not just more accurate, it is the only
way the two stay the same shape: retyping a curve as a list of points is how
the piece on the box comes to differ from the piece on the table.

- `flatten_path` covers the subset the path is written in -- absolute `M`,
  `L`, `C`, `S`, `Z` -- and samples each cubic into fourteen segments, which
  at any size these panels print at is under a printed dot. Pillow draws
  polygons, not curves.
- **`S` is the one command that is not self-contained**: its first control
  point is the previous curve's second one mirrored through the join. Read as
  if it carried its own, the outline kinks where the curves meet, which only
  shows at size -- and not on the meeple, whose own `S` follows two `L`s, so
  the reflection there is a no-op and a mistake in it would not show.
- The two letters are `ROLE_INITIALS`, the spelling every other drawing of a
  role reads, and their colour is `high_contrast_ink`, because white
  disappears on slime green. The piece takes its colour from `TEAM_COLORS`
  like everything else.

### The die

**The ball is a d12, so it is drawn as one**: `d12_art` builds a regular
dodecahedron, turns it, and fills the six faces that are towards the reader
by how square each one is. It replaced a flat twelve-sided polygon, which is
a badge rather than a die.

**And it is made of something.** The first solid was white, which is what a
d12 is in a dice shop and what nothing else in this game's art is -- the
balls in the players' own portraits are dark, dimpled, organic things, and a
white die on the cover read as a sticker laid over the picture. `DieMaterial`
is what it is made of instead: `BALL_MATERIAL` is dark leather, with a lit
face and a shadowed one, a grain over both, worn seams where the faces meet,
and bone numerals cut in. The author picked it from four the material was
tried in -- a stone grey, this, a tyre black and an ooze green.

- **The grain is hashed off each pixel's coordinates, not drawn from
  `random`.** A render of a panel is then the same bytes every time, which is
  what lets a drawing change be checked by hash ("Look at the image" in
  CLAUDE.md). Two scales
  of noise, because one is noise and two is a material.
- **A seam is lighter than the face and the silhouette is darker.** A worn
  edge on a cast piece catches the light; the outline of the object does not.
  Drawing every face outlined would give both the same weight, so the
  silhouette is the convex hull of the visible faces -- which for a convex
  solid is exactly its outline -- drawn once at its own width.
- Watch for a white die: it is the thing that was wrong with the first one,
  and a default colour is an easy thing to slip back in.

- **The face list is computed, not tabulated.** A face is the five vertices
  furthest along its own normal, wound around it; sixty indices written out
  would be sixty chances to transpose two of them with no way to notice.
- **The dual matters.** The twelve face normals are the `(0, ±φ, ±1)` family,
  not the `(0, ±1, ±φ)` one -- the same icosahedron turned, and against these
  vertices its "faces" are five points that are merely near each other. The
  first build used it and produced a lump nobody would call a die -- every
  face has to come out flat.
- **The number goes on whichever face is squarest to the reader**, sized to
  that pentagon.
- **Nothing here draws a ball on the board at all.** `draw_kickoff_marks` in
  `boards.py` already prints one on the kickoff space -- twelve-sided, with
  the ball's speed on it and "KICKOFF / ball at speed 1" under it -- and this
  module laid a second over it, which came out as two balls with the board's
  showing round the edge of the overlay. Covering it would mean a copy of
  that mark's own placement here, and the board is the thing being
  photographed, so the board's ball is the ball. The solid, `d12_art`, stays where it is the object rather than a piece on a
  space: the box's side and the sale sheet's header. The covers and the
  banners drew it too, until the cast changed -- see "The cover's four".
- **Every face is inset into the solid and what shows between two of them is
  the bevel.** A cast piece has no sharp edges; drawing the creases as lines
  gave a die with a wireframe over it. The inset is the rounded edge seen
  from straight on, which is why there is no seam colour drawn any more, only
  a face colour set into one.
- **The outline is the hull of *every* vertex, not of the visible faces.** A
  face seen edge-on still holds part of the silhouette, so a hull of the
  faces turned towards the reader cuts a flat notch out of the shape. Faces
  under a threshold are dropped from the *shading* for the neighbouring
  reason: a face barely off edge-on projects as a sliver and reads as a chip
  out of the solid.
- **It is turned less than it was.** Far enough and a dodecahedron's own
  silhouette goes lopsided -- correctly, it is the shape's outline -- and
  reads as a rock rather than a die.

## The banner

`render_banner` is the same art with the title **beside** the players rather
than above them, at two sizes: 3000 x 1200 (twice a Notion page cover, so it
survives being cropped there) and 1280 x 720, which is what a Screentop table
asks for.

**Two shapes, one composition, so the layout is written in shares of the
panel rather than in inches.** 16:9 is half again as tall for its width as
2.5:1; every measurement here is a fraction of the width or the height, and a
figure is sized against the height but capped by `BANNER_FIGURE_SHARE` of the
width -- without that cap, four players scaled to a 16:9 panel's height fill
it end to end and bury each other.

**The back rank stands further up the field** (`BANNER_BACK_LIFT`), and the
four are smaller than on the cover. These four are wider than they are tall,
and in the right half of a banner at the cover's sizes the outer figure on the
right is clamped to the trim straight behind the inner one and is lost -- the
first render of the new cast showed Synapse's tentacles and nothing else
(Synapse was in Gearclaw's place then).
Standing the back rank higher puts their heads over the front rank's
shoulders, which is also what further away looks like on a strip this short.

**No die is drawn on a banner.** It stood on the ground between the two
nearest players; with the new cast it was a second ball beside the one
Dravox's own art carries -- see "The cover's four".

**A banner is not a cropped cover.** A cover's title sits over the players
with a field of sky between them; crop that to a strip and what survives is
either the words or the art. So the two are one composition read two ways --
same cast, same palettes, same quoted tagline -- and the only thing that
moves is where the title goes. `BANNER_PLACES` puts the group in the right
half and the title block has the left to itself.

It defaults to the night palette, because a banner is read on a screen and
never printed; the page one is written beside it for a white page that wants
it. The tagline is one fitted line rather than a wrapped paragraph: on a
panel four inches tall, a second line runs under whoever is standing next to
it.

## The sale sheet is components, not prose

The first sale sheet was three columns of writing -- the game in Law 1's own
words, four quoted lines, the whole component list, an at-a-glance table. It
is a page nobody reads at a booth, and the author's call was blunt: more
components, far less text.

So the sheet is the printed board, a **fan of player cards**, and the three
facts a shopper checks. `sale_sheet_cards` picks which cards, from the four
colour teams in turn and from a different part of each roster -- a roster is
grouped by species, so the first player of all four teams is four of the same
monster, and the first fan came out four fire demons. The cards are `player_cards.render_player_card`'s
own, not a second drawing of a card.

**The fan holds maneuver cards too** (`sale_sheet_fan`): a player card is who
is on the field and a maneuver card is what they do, and they are the same
size, which is why they fan together at all.

**They are fanned rather than tiled.** A card small enough for eight to sit
side by side is a stamp; eight overlapped are eight cards, of which seven
show their name and their art -- which is what somebody looks at anyway. The
last one is whole, so at least one card is on the page in full.

**The foot carries a QR to the game's own page** (`PAGE_URL`,
`https://d12ball.com`), beside the line an address goes on. It is a second address rather than the survey's --
one asks how a game went, the other says what the game is -- and it is there
so that a sheet handed across a table is not a dead end when nobody has
filled the line in.

What is *not* on the sheet is anything that repeats the books -- the counts
under the fan and the Charter's line in the foot both went, on the same call
that took the prose out.

## There is no underside

`render_box_bottom` was drawn three times and scrapped: first crowded, then
white, then rewritten in the box's own voice with the Laws and the Charter's
precedence note taken off it. The author's call after the third was to stop
drawing it and **put the sale sheet on the bottom of the box for now**, so
`box-bottom.png` is not written any more.

What went with it is worth knowing, because a real underside will want most
of it back:

- **The component list read out of the Learn to Play's own "What is in the
  box"** (`box_contents`), with the sentences addressed to that book's reader
  -- "This book plays the 7-space board" -- dropped, since a box is not the
  book and the sentence is false the moment it is read off one. That is the
  shape to bring back: the list is the book's, not a second copy.
- **The three beats of a turn**, quoted, and the note on the two modes.
- **The barcode reserve**, above.

It is in the history rather than commented out, because a panel nobody
renders is a panel that stops being true. `git log -- d12ball/box_art.py` has
it.

## The cover's four

A `CoverCast` is four player names with a facing and the place each stands,
and the casts are the only art direction written into the module. There are
two (`COVER_CASTS`): **the website's four**, `WEBSITE_CAST`, which is
`COVER_CAST` -- what `box-cover.png`, the banners and the landing pages get --
and **the original four**, `ORIGINAL_CAST` (Voltus, Vorix, Inferno and
Slitheron, across the panel where they were first drawn), which the CLI writes as
`box-cover-original.png` and `-night.png` so the two can be set side by side
(the author asked for all four, 2026-09-27). Neither carries the die. The
banners are laid out for the website's four only (`BANNER_PLACES`), so they
take no cast.

The website's four are Goopkeeper, Flickerwing, Gearclaw and Dravox. They
started as the players the author picked for the D12 Ball page's species
cards, with Synapse where Gearclaw is; the author put Gearclaw on the box and
then on the page (2026-09-27). **The page reads its four from this cast**
(`species_face` in `landing/build.py`, [landing-pages.md](landing-pages.md)),
so there is one list and the two cannot differ: change a player here and the
page's card for that species changes with it. The build refuses a cast
without exactly one player of each species.

**There is no die in the middle of the cover** (the author, 2026-09-27). It
floated over the four, in front of them, as the thing they were playing for;
Dravox carries a ball in his own art -- a numbered d12 since the portraits'
balls were redrawn as dice -- so a second one hung in the air beside it was a
sticker on the picture rather than part of it.

The layout follows what the art is. Goopkeeper stands in his own goal, so he
is the back rank at the left edge, where the goal reads as the end of the
field; Flickerwing leaps in front of him, reaching right. Dravox, kicking left,
is the front rank on the right, and Gearclaw behind him at the edge. The
right-hand pair is not the left's mirror: Dravox is half again as wide as he is
tall, and Gearclaw's head is at the left of his art, facing into the group, so
on one line Dravox's crystals cover it. Dravox stands a little shorter and
nearer the middle, and the back rank stands further up the field
(`CoverCast.back_lift`, 1.8in per unit of depth) -- which puts Gearclaw's jaw
over Dravox's shoulder and Goopkeeper's goal at the back of the field. The
original cast stands raised the same way, for the reason below.

**The scene fills the panel from the strapline down** (the author,
2026-09-27). With the die gone, the first renders left a band of white
between the strapline and the players' heads. Both casts are now a fifth
taller than they were first drawn, and the field strip is 0.3in lower
(`COVER_FIELD_TOP`; the feet, the strip's foot and the chips are read off
it), so the tallest heads stop just under the strapline and the chips keep
their margin. A fifth is where it stops: at three tenths, Dravox's crystals
and Vorix's hood run into the strapline. Taller means wider, and in the
original cast the back rank -- Voltus and Inferno -- was lost behind the front
pair on one line, which is why it takes the same `back_lift` as the website's
four. Everything else about them is read: the
portraits come from `load_player_portrait`, and each one's colour from the
first team whose sheet they are on (a player's colour team and their species
team share a hex, so which is found first cannot change the answer).

**Facing is why the names are written down.** The portraits carry squad
numbers, so the art cannot be mirrored to make somebody face the other way --
a flipped number is a number nobody wears. Two face each way, one player of
each of the four species, and a roster revision that renames one of them, or
leaves the four no longer two and two, needs the cast re-picked. Goopkeeper
faces the reader rather than either way; he is counted as facing right
because the goal behind him is what has to be at an edge.

The back rank is **darkened rather than faded** (`into_the_dark`): a cut-out
at reduced opacity shows the sky through the middle of a player, where the
same one darkened reads as somebody standing further away in the same light.
Each figure's centre is clamped so its measured width stays inside the trim --
these cut-outs are as wide as they are tall, a share of the panel's width says
nothing about where an arm ends, and Pillow crops what falls off the canvas
without a word.

## Every printed address is the game's own site's

Both addresses on these panels are `d12ball.com`'s: `PAGE_URL` is the site
itself and `SURVEY_URL` its `/feedback` (the author's word, 2026-09-27),
which the site forwards to the form
behind it, `SURVEY_FORM_URL` (landing/build.py, `REDIRECTS`). Until the site
went up (2026-09-27, the landing pages' step 5) they were the two Notion
addresses. A printed card cannot be edited; a redirect can, so the form or
the page behind an address can move without anything being reprinted
([landing-pages.md](landing-pages.md), "Redirects"). `SURVEY_FORM_URL` is
never printed -- it is the form's address, which nobody chose. Cards printed
before carry the form's own address and keep working while it stays put;
they are not reprinted for this (the author, 2026-09-27), and the next print
run carries the new code.

**The landing build refuses a printed address the site does not serve**
(`PRINTED_ADDRESSES` in `landing/build.py`): one that is off `d12ball.com`,
or a path that is neither the page nor a redirect. A dead address on a card
is found by somebody holding the card, which is the worst place to find it.

The shorter addresses also make simpler codes: at the same printed size the
survey's modules went from 0.86mm to about 1.4mm, which is what let the code
shrink to 1.4in (`PLAYTEST_QR_INCHES`) when the box moved onto the card
(below) and still print at 0.96mm.

## The playtest card's back is in the author's words only

**Two lines, both the author's (2026-09-27), and nothing else** but the
address and the publisher: the headline, `PLAYTEST_HEADLINE`, which the
d12ball.com playtest panel carries too and the landing build reads from
here, so the two cannot drift; and `PLAYTEST_CARD_INTRO`, the card's own,
because it sends the reader to the code below it -- which a web page has no
code for. It used to carry copy written here (a heading, a paragraph, three
survey prompts, a "Take the survey" over the code) and the Charter line in
its foot; the author took all of it out. Beside the words and the code is
**the printed box cover**, so the card a table keeps looks like the box it
came out of. The front is unchanged.

## The survey code

The playtest card's back carries a QR of `SURVEY_URL`,
`https://d12ball.com/feedback`, and the address is **printed in its foot as
well**: a code is one smudge away from being nothing, and
a card whose only route to the survey is optical fails quietly. The URL has no
spaces, so it is broken by `draw_hard_wrapped` -- `wrap_text` breaks on spaces
and, handed an address, returns one line and draws it off the edge of the
panel without a word.

- **The code is drawn module by module** onto the panel rather than generated
  as a PNG and scaled: a resize lands module edges between pixels and softens
  exactly the contrast a scanner is looking for. A QR is unreadable to
  everyone who looks at the render, so check a change by scanning the
  printed card.
- **`QR_MIN_MODULE_INCHES` is 0.4mm**, the floor a phone reads reliably off an
  office printer. The card's own code comes out at 0.96mm; a longer URL makes
  a denser code at the same printed size, and the CLI reports the module size
  so an address that has quietly grown past what the card can carry shows
  there. Change the URL with `--survey-url`.
- **`qrcode` is imported inside the function**, not at the top of the module.
  It is pinned in `requirements.txt`, but the bot imports this package and the
  only thing in it that needs a QR encoder is a card nobody renders from the
  bot -- a checkout that has not reinstalled its requirements should still
  load everything else. A missing package raises with the install line in it.

## Looking at them

Nothing tests any of it, so the render is the only check. **Look at the
image** --
`scripts/render_box_art.py --out box/` writes all twelve files -- six printed
panels, the night cover, the original cast's two covers and the three
banners -- and reports the box's own
dimensions, the QR's module size, and that the playing time and the age are
the author's.

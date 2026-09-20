# The printed boards

Design notes for fool-bot; the map is [CLAUDE.md](../../CLAUDE.md), the rules are [living-rules.md](../living-rules.md).

## The printed boards

`d12ball/boards.py` draws the three boards the tabletop game is played on --
the **field board**, the **jumbotron board** and a coach's **team board** --
print-ready at 300dpi. **Tabloid (11 x 17) is the default now**, not A3 --
the field board portrait, the other two landscape; see `PAPERS` and
`DEFAULT_PAPER` for why tabloid rather than A3 is the one a home or copy-shop
printer actually stocks.

```bash
python3 scripts/render_boards.py --out print/          # every field size
python3 scripts/render_boards.py --teams --bleed --pdf
python3 scripts/render_boards.py --board-size 9        # just the one field
```

- **They follow `cards.py`, not `render.py`.** The palette is the maneuver
  cards' -- dark ink on a light face -- because a print goes on paper and the
  bot's dark board is the wrong thing to hand a printer. The zone tints are the
  bot's three hues lightened, so a coach reads one board as the other.
  Everything is measured in inches, with the same 1/8in bleed the cards carry.
  The boards keep `FACE_COLOR`'s cream where the cards went white: a board is
  one sheet a game.
- **The clock and the score are the jumbotron's, not the field's.** They were
  bands under the field, where sixteen minutes across a sheet that was already
  carrying the field left a cell an inch wide -- too small to stand a token in,
  which is the only thing those cells are for. On their own board the clock is
  rows of eight (`CLOCK_COLUMNS`), two a half, and every track clears
  `MIN_TOKEN_INCHES`;
  `cell_inches` is that measurement, reported by the CLI and asserted by
  `D12BallJumbotronTests`. The field board got the whole of that space back,
  which is what makes a space tall enough for two sides' meeples --
  `FieldGeometry.space_inches`, asserted the same way. It is the split the bot's
  own board already makes: a jumbotron is the state of the match, the field is
  the position.
- **The three token supplies are on the jumbotron for the neighbouring
  reason.** `TOKEN_SUPPLIES` is the exhaustion stock and the two markers it
  turns players into, as silos rather than as a tally: a player's own tokens are
  stacked on their card, which is where the bot draws them, so what had nowhere
  printed to live was the pile they come out of.
  - **A silo is `SILO_INCHES` and carries no words at all** -- a token wide,
    half again as tall, with the token's own art printed at the bottom as the
    base of the stack. It is a place to stand pieces rather than a cell to
    read, and a caption would be naming a piece the coach is holding a copy of.
    Being a fixed measurement rather than a share of the panel is the point: a
    piece does not get bigger because the sheet did. It is still capped by the
    room under the label, so a smaller paper shrinks it instead of running it
    off the panel, and `cell_inches` measures it against `MIN_TOKEN_INCHES`
    like the tracks.
  - **The art is `render.py`'s own token PNGs**, so a coach at the table and a
    coach reading a line of text in Discord see one icon -- see
    `scripts/render_condition_tokens.py`, which draws them, and note that the
    loaders in `render.py` thumbnail to 26px and cache there, which is why
    `load_token_art` opens the file itself. A missing file leaves the silo
    empty rather than failing the board.
- **No die value is printed anywhere, and since 2026-08-17 that is the rule
  rather than a divergence from it.** Maneuvers are chosen with the cards, so
  the two selection d6s are off the team board and the head coach cell lists
  the maneuvers by rank (O1, D2) instead of by face -- **a row is a rank with
  both its cards on it**, the basic name in ink and its gambit
  under it in grey. Three rows a column however many cards exist: listing them
  per card would print two O1s with nothing saying they are the same rank, in a
  panel sized for three. The author retired
  them from the rules outright, so the living rules no longer mention them
  either -- see the dated entry in the rules log.
  **The data and the code have not caught up.** `basic_rules.json` still
  defines `head_coach_dice`, `TeamBoardDefinition` still holds them,
  `maneuvers.json` still carries `die_values`, `ManeuverCatalog.offense_for_die`
  / `defense_for_die` still map a face to a maneuver, and `DinkyAI` still picks
  its maneuver by rolling a d6 through them. None of it reaches a coach, so
  retiring it is a code change and not a rules one -- but the sheet still has
  the column, so an import will keep writing it until the author drops it
  upstream. `draw_die_slot` reads `team_die` alone and says why, and a test
  greps the module for `offense_die`/`die_values` because the data is still
  right there to pick up again by accident.
- **The team board is landscape and holds two panels, not one.** Dropping the
  three zone areas onto the field board (see "The zone-assignment rows" below)
  left a single row -- the bench, the back bench and the head coach -- short
  enough that a match's two coaches share one sheet, cut in half, rather than
  each wanting a whole one: `render_team_board` draws the same panel twice,
  stacked over the sheet's own short side. **Landscape, not portrait**, and
  deliberately the opposite of the field board: stacking over the *short* side
  (11in) leaves every column a real card's width of room over the long side
  (17in), where stacking over the long side would leave the row only the short
  side to divide three ways -- not enough for a fanned poker card, measured.
  `card_slot_inches` is what says whether a panel holds a real card -- the CLI
  prints it, and `TeamBoardGeometry` sizes the header and the footer in fixed
  inches rather than as a share of the panel, which is what a header this much
  shorter than the design it came from needed: a title sized to the *sheet's*
  width came out taller than a header a third its old height, the day this
  landed. `D12BallTeamBoardTests` asserts a panel's slot clears a real card at
  A3 and at tabloid alike now -- both hold real cards, which is new: the three
  zone areas were what cost tabloid the 0.7in it used to come up short by.
- **A panel that has to fit divides what it is given.** The head coach cell
  sizes its three maneuver rows from the height left under the die rather than
  from a fixed measurement, because three rows that fit one sheet run off the
  bottom of another -- and that overflow is the one thing on these boards a
  reader would take for a bug rather than a layout that scaled.
- **Nothing on any board is written in the module.** The layouts, the
  formations, the standard deal and the coach's die come from
  `basic_rules.json`, the six maneuvers from `maneuvers.json`, and the roster
  from `players.json` -- so a printed board cannot claim a rule the bot does
  not play, and an import reaches the boards by re-running the script.
- **The geometry a board asserts is read off the same code the bot enforces.**
  `shooting_range_bands` walks `BoardState.is_in_shooting_range` a space at a
  time and `kickoff_marks` reads `kickoff_space_index`, rather than either
  restating where the middle of the board is. That is what puts two kickoff
  marks on board 6 (its midfield has no middle, so each side kicks off from
  the space nearer its own goal) and one on 7 and 9, and what leaves the
  bracket under the field agreeing with the living rules' own table.
- **Every field size is rendered by default.** A print run wants the 6-, 7- and
  9-space boards; `--board-size` narrows it to one. The sizes come from
  `rules.board_layouts`, so a fourth layout added upstream is printed without
  the script being touched.
- **Zones keep their real names on the field board's own assignment rows**,
  not the team board any more -- see "The zone-assignment rows". A coach's own
  goal is the home goal for one of them and the visitors goal for the other,
  and the field board is read by both, so the areas read HOME ZONE / MIDFIELD
  / VISITORS ZONE exactly as the bot's coaching image does -- HOME THIRD /
  VISITORS THIRD on the 9-space board, the only one where the three areas
  (H/M/V) are all equal (see "The field" in the living rules, and the
  2026-08-24 entry in the rules log; not to be confused with `FONT_GOAL_ZONE`,
  which labels the actual goal beyond the edge of the board). The team board's
  own formation strip is relative, and it says so. `--teams` colours a board
  per team and changes nothing else.
- **The formation strip lists the shapes and nothing else, and groups the ones
  only some boards play.** One team board is printed for every field size, so
  3-2-1 and 1-2-3 are on it under "9-SPACE BOARD ONLY" rather than left off --
  read from `board_sizes` rather than from a size written into the module. The
  `(2 / 3 / 1)` that used to follow each name restated the same three digits
  (a shape is named by its counts, which the ruleset loader checks) and five
  shapes with it no longer fit the strip. `draw_formation_strip` measures
  itself and shrinks to fit, because a sixth shape added upstream lands there
  without anybody measuring.
- **The clock and score tracks are printed aids, not components the rules
  name.** What they count is a rule -- fifteen space-minutes, a clock that
  stops there, a score a shootout can add six to -- but nothing upstream says
  a board carries a track, so don't read them as one.
- **`Sheet` measures in thousandths of the sheet's width** and does not
  supersample, unlike `cards.Pen`: a board is tens of megapixels at 300dpi,
  where a card is under one, and a stepped edge that small does not survive
  the print. Its canvas is allocated on first use, which is what lets
  `card_slot_inches` and `cell_inches` ask how a layout comes out without
  drawing it.
- `print/` is generated output and is gitignored, like `cards/`.

## End zones

`draw_end_zone` gives each goal its own zone, American-football style, beyond
H1 and beyond the board's last V space -- not squeezed into either one's own
space, because both are already full of meeples under the standard deal (see
"Formations and occupancy" in [formations-and-occupancy.md](formations-and-occupancy.md)). It is drawn in the margin between the board and
the canvas edge, so `GOAL_ZONE_WIDTH` is whatever that margin leaves once
`GOAL_ZONE_EDGE_MARGIN` (to the canvas edge) and `GOAL_ZONE_GAP` (to the
board's own outline) are taken out -- there is no spare canvas to grow it
into without widening the board itself.

- **"GOAL" runs the zone's length in the defending team's own color** --
  the home team's to the left of H1, the visitors' to the right of the
  board's last V space -- rotated 90°, the way a real end zone's lettering
  reads sideways on a field running left to right. Letters are spaced apart
  by `GOAL_ZONE_LETTER_SPACING`, on top of the font's own advance, because a
  four-letter word at a font size that fits the zone's width reads as a
  small cluster rather than something that fills a tall zone.
- **The visitors' end zone is rotated a further 180°** (`angle=270` on
  `draw_end_zone`, the author's call) from the home end zone's -- a real
  field's two ends face opposite directions rather than both reading the
  same way. The coordinate math for where the "O" (and the ball standing in
  for it) lands after rotation was verified empirically against Pillow's
  actual `rotate(90)`/`rotate(270)` output, not derived on paper -- a sign
  error here is silent, not a crash.
- **A blank d12 stands in for the "O" itself**, not a separate emblem placed
  over the whole word: the letter is left undrawn and its slot remembered,
  so the ball can be centered exactly there once the word is rotated. It is
  fully opaque and sized to the letter it replaces (`ball_radius`, computed
  from the "O"'s own advance and the word's cell height) rather than a fixed
  constant, so it cannot end up visibly smaller than the letters around it.
  The "12" on it is rotated the same angle as the word, so it reads in the
  same orientation rather than sideways against it.
- **The jumbotron and both team boards now span the field's full width,
  end zones included** (`FIELD_FAR_LEFT`/`FIELD_FAR_RIGHT`, `JUMBOTRON_LEFT`/
  `JUMBOTRON_RIGHT`), rather than stopping at the board's own edge and
  leaving the end zones looking like they belong to nobody.
- **`BENCH`/`BACK BENCH` position off the team name's own measured width**,
  not a fixed offset -- a species team's name (`Fire Demons`, `Telekinetics`)
  is wider than a color team's and was landing underneath "BENCH" rather
  than beside it. `TEAM_BOARD_BENCH_MIN_X`/`TEAM_BOARD_BACK_BENCH_MIN_X` are
  what a short name already left in place, so nothing shifts for the common
  case.
- **The printed field board carries its own end zones now**, `draw_field_end_zones`
  in `boards.py` -- the print counterpart of `draw_end_zone`, not a second
  drawing of the same pixels: it is a different rendering stack (`Sheet`
  rather than a raw canvas) at a different resolution (300dpi rather than the
  bot's fixed 2200px), so the geometry and the font-fit are worked out fresh
  rather than shared. `FieldGeometry` narrows the strip itself to
  `strip_left`/`strip_right`, reserving `end_zone_width` plus a gap on each
  side for it; `left`/`right` stay the full content width for the header, the
  direction arrows and the shooting-range bracket, which read the wide pair
  same as the bot's own jumbotron and team boards span its end zones. **It is
  drawn in ink, not a team's colour** -- the field board is a template for the
  tabletop game with no match to read a team from, unlike the bot's own board,
  which always has one.
  - **`end_zone_width` is a tight fit, not a generous one**, and tighter still
    since the field board went portrait to make room for the zone-assignment
    rows (below): the strip now divides an 11in width instead of a 17in one,
    so every inch an end zone takes is an inch a space cannot have. Don't grow
    it without checking `test_a_space_is_big_enough_to_stand_meeples_on`, whose
    width floor is 1.0in now, not the 1.5in a landscape sheet could promise.

## The zone-assignment rows

A card row for each zone -- HOME ZONE, MIDFIELD, VISITORS ZONE (HOME THIRD /
VISITORS THIRD on the 9-space board) -- above the strip for the visiting
coach and below it for home, on the field board itself
rather than on the team board, which used to carry them. `draw_zone_assignment_rows`
and `draw_zone_assignment_cell` in `boards.py` draw them; `FieldGeometry`'s
`visiting_zone_top`/`_bottom` and `home_zone_top`/`_bottom` are where.

- **That is the whole reason the field board is portrait (11 x 17) rather than
  landscape.** A zone row needs a real 3.5in card's worth of height, twice
  over (once for each coach), which the sheet's 17in length holds without
  crowding the strip; the strip's own spaces pay for it instead, coming out
  under an inch wide on the 9-space board rather than the 1.5in two meeples
  side by side would ask for on a landscape sheet. The author's own call,
  made knowing that cost -- see `FieldGeometry`'s own docstring.
- **The visiting row is rotated 180 degrees cell by cell, not the row
  reordered.** The two coaches sit on opposite sides of the table, so a row
  that reads upright to home reads upside down to visiting -- rotating each
  cell the other 180 degrees turns it upright *for them* without touching
  which column is which: HOME ZONE (or THIRD) is still the leftmost cell in
  both rows, directly under and over the strip's own Home column, so a coach
  reading either row left to right reads the same zone order the strip does.
  `draw_zone_assignment_cell` draws the whole cell upright on its own small
  canvas and rotates the finished picture when it is the visiting row, rather
  than working out where flipped text and flipped dashes land by hand.
- **The dashed guides inside a row are a visual cue, not a slot count.** This
  is a staging area a coach fans any number of cards across before assigning
  them to numbered spaces, not a fixed set of areas the way the strip's own
  spaces are -- `CARDS_PER_AREA` (three) is borrowed from the team board's own
  areas for the guide only, and nothing here enforces it.
- **The caption is dropped rather than shrunk past legibility.** "cards
  assigned to this zone" fits next to MIDFIELD's own width; HOME ZONE/THIRD
  and VISITORS ZONE/THIRD are narrower, and `draw_zone_assignment_cell` measures whether
  it fits before drawing it rather than shrinking the font until it does --
  a caption nobody can read is a worse failure than one left off.
- **The header was rebuilt to stack rather than sit side by side**, in the
  same change: `draw_field_header`'s title on the left and its note on the
  right used to overlap in the middle on anything narrower than the old
  landscape sheet, which the portrait sheet always is. Both are wrapped to
  the sheet's own content width and stacked in one left-aligned column now,
  which cannot overlap regardless of paper size or how long the wording runs.

# The printed boards

Design notes for fool-bot; the map is [CLAUDE.md](../../CLAUDE.md), the rules are [living-rules.md](../living-rules.md).

## The printed boards

`d12ball/boards.py` draws the three boards the tabletop game is played on --
the **field board**, the **jumbotron board** and a coach's **team board** --
print-ready at 300dpi. **Only the field board is tabloid (11 x 17)**, and it
is portrait; the jumbotron is a letter sheet portrait (`JUMBOTRON_PAPER`) and
the team board half a letter sheet (`TEAM_BOARD_PAPER`). See `PAPERS` and
`DEFAULT_PAPER` for why tabloid rather than A3 is the big size a home or
copy-shop printer actually stocks, and "The jumbotron's own paper" for why
only one board still needs it.

```bash
python3 scripts/render_boards.py --out print/          # every field size
python3 scripts/render_boards.py --teams --bleed --pdf
python3 scripts/render_boards.py --board-size 9        # just the one field
python3 scripts/render_boards.py --no-halves           # tabloid sheets only
python3 scripts/render_boards.py --jumbotron-paper a4  # its own sheet size
```

- **They follow `cards.py`, not `render.py`.** The palette is the maneuver
  cards' -- dark ink on a light face -- because a print goes on paper and the
  bot's dark board is the wrong thing to hand a printer. The zone tints are the
  bot's three hues lightened, so a coach reads one board as the other.
  Everything is measured in inches, with the same 1/8in bleed the cards carry.
  The boards keep `FACE_COLOR`'s cream where the cards went white: a board is
  one sheet a game.
- **The jumbotron is a letter sheet of its own, portrait**, and the team
  board half a letter one: the field board is the only board still drawn on
  tabloid, because its spaces are the only thing on any of them that cannot
  be made smaller. See "The jumbotron's own paper".
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
  the two selection d6s are off the team board, and what a coach needs on the
  board is which maneuver beats which rather than which face rolls it -- the
  back of the maneuver card itself, printed in the head coach's cell (see "The
  team board"). The author retired the selection dice from the rules outright,
  so the living rules no longer mention them either -- see the dated entry in
  the rules log.
  **The data and the code have not caught up.** `basic_rules.json` still
  defines `head_coach_dice`, `TeamBoardDefinition` still holds them,
  `maneuvers.json` still carries `die_values`, `ManeuverCatalog.offense_for_die`
  / `defense_for_die` still map a face to a maneuver, and `DinkyAI` still picks
  its maneuver by rolling a d6 through them. None of it reaches a coach, so
  retiring it is a code change and not a rules one -- but the sheet still has
  the column, so an import will keep writing it until the author drops it
  upstream. `team_reminders` reads `team_die` alone and says why, and a test
  greps the module for `offense_die`/`die_values` because the data is still
  right there to pick up again by accident.
- **The team board is its own paper: half a letter sheet, and two files.**
  `TEAM_BOARD_PAPER` is letter rather than the tabloid the field and the
  jumbotron are drawn on, because letter is the size a printer in the house
  actually has in it and a coach's board is the one board of the three that
  gets printed twice. `render_team_board` is one board, 8.5 x 5.5in;
  `render_team_board_sheet` is the letter page carrying two of them with a
  dashed line down the seam, which is the sheet a match is cut from. The page
  pastes the board rather than rendering it twice, so the two halves are the
  same picture by construction -- `test_two_boards_are_a_page_and_they_are_the_same_board`
  checks each half against the board itself, everything but the seam the cut
  line is drawn down. See "The team board" below for what is on it.
- **Nothing on any board is written in the module.** The layouts, the
  formations, the standard deal and the coach's die come from
  `basic_rules.json`, the six maneuvers from `maneuvers.json`, and the roster
  from `players.json` -- so a printed board cannot claim a rule the bot does
  not play, and an import reaches the boards by re-running the script.
- **The geometry a board asserts is read off the same code the bot enforces.**
  `shooting_range_bands` walks `BoardState.is_in_shooting_range` a space at a
  time and `kickoff_marks` reads `kickoff_space_index`, rather than either
  restating where the middle of the board is. Both boards' midfields have a
  middle, so both print one kickoff mark for the two sides -- `kickoff_marks`
  is still a map rather than a space, because the rule is asked per side and a
  board without a middle would answer it twice. It is also what leaves the
  bracket under the field agreeing with the living rules' own table.
- **Every field size is rendered by default.** A print run wants the 7- and
  9-space boards; `--board-size` narrows it to one. The sizes come from
  `rules.board_layouts`, so a fourth layout added upstream is printed without
  the script being touched. **Each comes out three ways** -- whole on the
  tabloid sheet and as its own two letter halves; see "Printing a board on
  two small sheets".
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
  name.** What they count is a rule -- fifteen space-minutes a half, a clock
  that runs past them, a score a shootout can add six to -- but nothing
  upstream says a board carries a track, so don't read them as one.
- **A clock cell is captioned only where the caption is a rule.** The first
  half's 15 and the second's 30 are bordered and say "last possession",
  because reaching one is the only thing on this panel that changes what a
  coach may do; 00 and the second half's own kickoff cell were captioned
  "kickoff" and "second-half kickoff" until 2026-09-22 and are now plain,
  since where a half starts is already what the band over the row says.
  **A cell is captioned for its own band, not for its number**: since the
  second half starts at 15 (the author, 2026-09-22) there is a 15 in each
  band, and only the first half's is a last minute.
  **The minute is sized to clear its own border, not to fill the cell**:
  a captioned cell has to hold a number and a caption between two edges of a
  border thick enough to be read as one, and a number drawn to the cell
  instead of to that space crossed it -- which on 15 and 30 is the border
  doing the telling.
- **The clock panel's two label lines are centred in their strips, not hung
  off the top of them.** `CLOCK · SPACE MINUTES` and `FIRST HALF · 00-15`
  are different things -- a panel's name and a band's -- and hung from the
  top of their strips they cleared each other by two hundredths of an inch
  and read as one paragraph. Centred, and a size down from the panel titles
  elsewhere on the board, each sits in its own space. The score panel's
  title is still hung, because the row under it is tall enough that nothing
  crowds it.
- **`Sheet` measures in thousandths of the sheet's width** and does not
  supersample, unlike `cards.Pen`: a board is tens of megapixels at 300dpi,
  where a card is under one, and a stepped edge that small does not survive
  the print. Its canvas is allocated on first use, which is what lets
  `card_slot_inches` and `cell_inches` ask how a layout comes out without
  drawing it. **The team board is the exception and measures in inches**
  throughout -- see "The team board".
- `print/` is generated output and is gitignored, like `cards/`.

## The jumbotron's own paper

`JUMBOTRON_PAPER` is **letter, portrait** -- one sheet, not the field board's
tabloid. Like the team board it has a paper of its own for the plain reason
that letter is what a printer in the house has in it, and it is a board that
can be fitted onto one: it carries no field, so nothing on it has to be wide
enough to stand two sides' meeples on. After this, the field board is the
only board that still wants a big sheet, and even it prints on letter as two
halves (above).

- **Portrait rather than landscape is the clock's doing, not a preference.**
  Letter landscape is 11 x 8.5, and its width fits the clock only if the
  track runs thirteen cells to a row. `CLOCK_COLUMNS` is eight precisely so
  that halftime lands at the end of a row and each half is two whole bands
  rather than a colour change half way along one -- that is a rule about the
  track, and `test_the_clock_is_the_game_and_the_halves_are_whole_rows`
  asserts it as `(HALFTIME_MINUTE + 1) % CLOCK_COLUMNS == 0`. Turning the
  sheet costs nothing and keeps it, so the sheet turned. The clock is the
  four rows of eight it always was; `test_the_smaller_sheet_did_not_reach_the_clock`
  is that in the suite.
- **The score track is what paid for the smaller sheet.** Thirteen cells in
  one row wants ten inches of track and a letter sheet has seven and
  three-quarters between its margins once the HOME/VISITORS label column is
  out -- which would have put a score cell at two-thirds of an inch, under
  the token this whole board exists to give a cell to. So it **wraps rather
  than shrinks**, `SCORE_COLUMNS` cells to a row and two rows a side, which
  is the same answer the clock already gives and for the same reason. Seven
  is the widest wrap that clears `MIN_TOKEN_INCHES` with room over, and it
  splits 0-12 into 0-6 and 7-12 -- one short second row rather than two
  ragged ones.
  - **A side's label sits beside its whole block, not beside its first row.**
    The word names the side; hung off the top row it read as a label for that
    row alone once there were two of them.
  - `test_both_sides_tracks_fit_inside_the_score_panel` is the fault this
    invites: a panel that went from two rows to four on a sheet that got
    smaller is exactly where a row comes to be drawn below the panel it
    belongs to, and a crop is silent -- the same failure the team board's
    footer records below.
- **The header, the footer and the gaps paid the rest.** They are the only
  things on this board that are not a cell, so the nine rows of cells the
  sheet now carries came out of them: every one is a smaller share than the
  tabloid board used. It is the same trade the tabloid switch made when the
  score and supply cells went under the floor by a sliver, one rank further
  along -- and `test_every_cell_can_hold_a_token` reads `cell_inches()` on
  this board's own paper, so it is still the thing that catches a share
  redivided too far.
- **Every measurement on this board is a share of the sheet's width**, so
  halving the sheet halved the type with it. That is the cost, and it is
  real: the footer line is about eight point now where it was fifteen. The
  cells did not shrink with it, because the panel shares were redivided
  rather than scaled -- a clock cell is 0.96 x 0.81in against the tabloid
  board's 1.93 x 0.85, so it lost its width and kept its height.

## Printing a board on two small sheets

`render_field_board_halves` writes the field board a second way: two letter
sheets, `field-board-7-top.png` and `field-board-7-bottom.png`, which taped
along the cut are the tabloid board. So a print run comes out with two
ledger-size field boards and four letter-size halves, and a house with a
letter printer and no tabloid one can still put the real board on the table.
`--no-halves` leaves them out.

- **A half is a cut of the finished picture, never a second layout.**
  `halve_sheet` crops the rendered board in two and that is the whole of it.
  Re-laying the board out for the smaller paper would have printed a
  *different game* -- a space is the width the sheet's own arithmetic gives
  it (`FieldGeometry.space_width`), and a board laid out on letter would have
  narrower ones. `test_the_two_halves_are_the_board` pastes the two back
  together and compares the result with the board pixel for pixel, the same
  check `test_two_boards_are_a_page_and_they_are_the_same_board` makes of the
  team board's page and for the same reason: two pictures that are supposed
  to be one should be one by construction, not by hoping two renders agree.
- **Half a tabloid sheet is exactly a letter sheet, turned the other way**,
  and that is the only reason any of this works: 11 x 17 halves into 11 x 8.5,
  which is letter landscape to the pixel at 300dpi, so nothing is scaled and
  the printed board is the size it says it is. `HALF_PAPERS` is that pairing
  as data -- tabloid into letter, A3 into A4 by the same ISO property -- and
  `test_every_paper_that_names_its_halves_really_halves_into_it` checks it in
  pixels rather than in inches, because the rounding is where a half-pixel
  would hide. A paper that halves into nothing standard is **absent from the
  table rather than approximated**: the halves still render, `half_paper`
  answers `None`, and the CLI says as much instead of naming a size a printer
  does not stock.
- **Where the cut lands is not a choice, so the layout is what is checked.**
  Both halves have to fit the paper below, and only the exact middle gives two
  that do -- so the seam falls wherever the board's bands happen to put it,
  which on the field board is across the strip, a little under half way down
  a space. Nothing is moved to dodge it, because moving it would change the
  board the tabloid sheet prints. What the suite guards instead is that the
  middle of the sheet keeps landing somewhere a seam is harmless:
  `test_the_cut_falls_across_the_strip_and_clear_of_its_words` fails if it
  ever crosses the header, a zone-assignment row or the strip's own labels.
  The strip is the safe place because it is tints and outlines -- its zone
  names and space codes are all hung from its top, which is what
  `FieldGeometry.strip_label_bottom` measures. That measurement moved onto the
  geometry from inside `draw_field_strip` for this: a band measured twice is
  the fault the team board's footer records below.
- **The board is halved before any bleed, and each half is bled on its own.**
  A half is a sheet a shop trims like any other, and trimming into the margin
  takes it back off the seam, so the two still butt together. Bleeding the
  sheet and then cutting it would have put half a margin down the middle of
  the field and none on two of the outer edges.
- **The jumbotron is not split, and does not need to be.** It is a letter
  sheet in its own right now -- see "The jumbotron's own paper" -- so the
  field board is the only one left that a letter printer cannot take whole.

## The team board

A coach's own board: a header, a row of three cells -- the bench, the back
bench and the head coach -- and a footer. It is printed as two files,
`team-board.png` (one board, 8.5 x 5.5in) and `team-board-2up.png` (a letter
page carrying two of them, cut across the middle). It was redrawn from
scratch in September 2026; what follows is why it is shaped the way it is,
and each point is a fault the board it replaced actually had.

- **Every size on it is an inch of printed paper.** `print_font` takes
  inches, `TeamBoardGeometry` measures every band in inches, and
  `TEAM_TITLE_INCHES` through `TEAM_SMALL_INCHES` are the six sizes the
  board uses and the only ones. The old board mixed the two units -- a band
  measured in inches holding type measured in thousandths of the sheet's
  width -- and that is the whole of what went wrong with it: the roster line
  was drawn through the rule under it, a caption landed on the next cell's
  title, and the maneuver names came out a third the height of the heading
  over them for no reason anybody chose. A board is one physical thing read
  at arm's length; what matters is how big a word comes off the printer.
- **The footer's own lines are measured by the geometry, not by the routine
  that draws them.** `footer_lines` is where the three blocks go, and the
  band is the sum of them. Two measurements of one band is how the standard
  deal and the closing reminder came to be drawn *below* the bottom edge of
  the old panel and cropped away -- on a render that looked fine, because
  the crop is silent. `test_every_band_is_in_order_and_inside_the_board` is
  that failure as a test.
- **A line that cannot be legible is dropped, not shrunk.**
  `fitted_print_font` answers with `None` below its floor and
  `draw_fitted` is for lines that have to be drawn whatever happens; a
  caption uses the first and is left off when it will not fit. It is the
  same call the field board's zone cells make (see "The zone-assignment
  rows"), and for the same reason: a caption nobody can read is a worse
  failure than one left off.
- **A cell's caption is a second line, not the right-hand end of the
  title's.** Sharing one line is what put "players who have yet to play"
  hard against the next cell's title, and a caption squeezed into what a
  title leaves has no width of its own to be legible in.
- **The head coach's cell is the back of the maneuver card, pasted.** It is
  the same picture `cards.render_maneuver_card_back` draws for the deck --
  the six ranks on one cycle, a solid arrow to what a rank beats and a
  dashed one to what it ties -- so a coach reading a matchup off the board
  and a coach reading it off the card in their hand are reading one picture.
  It replaced two columns of names that said which maneuver was which rank
  and nothing about what beat what. It is pasted rather than redrawn because
  a second drawing of the cycle is a second thing to keep true when a rank
  changes; its corners are cut to the card's own radius so the board's cream
  shows around it rather than four white squares.
- **The column is cut to the card, not the card fitted to a third of the
  row.** `reference` is the back at the height the row leaves it, capped at a
  real card (it is drawn at 300dpi and printing it larger would only soften
  it), and the two benches divide what is left. Equal thirds left a band of
  empty board beside the picture.
- **A bench holds one card guide, and it is under poker size.** Half a letter
  sheet does not leave 3.5 inches between a legible header, two legible cell
  labels and a footer, and the author's call was legible over life-size: the
  guide is a card's proportions at the height the row has, the cells are wider
  than a real card, and a bench stacks on the area rather than inside the
  guide. `card_slot_inches` reports it and the CLI says so in as many words.
  The three-card fan the old board drew across a five-inch column is gone with
  the column.
- **The die is in the footer, drawn.** It is the one component a coach keeps
  beside the cards, so it is a shape on the board rather than a word in a
  sentence -- and its faces are read from `basic_rules.json` like everything
  else here, so the board cannot claim a die the bot does not roll.
- **The cut line is on the seam of the two-up page and on neither board.**
  A dashed line down the middle of the sheet is the one mark on it that
  belongs to the page rather than to either coach.

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

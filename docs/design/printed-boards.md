# The printed boards

Design notes for fool-bot; the map is [CLAUDE.md](../../CLAUDE.md), the rules are [living-rules.md](../living-rules.md).

## The printed boards

`d12ball/boards.py` draws the boards the tabletop game is played on -- the
**field board**, the **jumbotron board**, and a coach's **team board** and
**zone board** -- print-ready at 300dpi. The boards carry no tests -- nothing
printed does (the author, 2026-09-23) -- so a change to one is checked by
rendering it and looking. **Only the field board is tabloid (11 x 17)**, and
it is landscape; the jumbotron is a letter sheet landscape (`JUMBOTRON_PAPER`)
and the team and zone boards half a letter sheet each (`TEAM_BOARD_PAPER`).
See `PAPERS` and `DEFAULT_PAPER` for why tabloid rather than A3 is the big
size a home or copy-shop printer actually stocks, and "The jumbotron's own
paper" for why only one board still needs it.

**The table is 17 x 22in** (the author, 2026-10-05): the field board across
the middle, and along each long side a coach's **strip** -- their zone board
on their left and their team board on their right, the two half-letter
boards end to end, seventeen inches together, the field's own length. It
replaced a portrait field board that carried both coaches' zone rows above
and below an eleven-inch strip; the author wanted a wider field. See "The
zone board".

```bash
python3 scripts/render_boards.py                     # every field size, into d12ball/print/boards/
python3 scripts/render_boards.py --bleed --pdf
python3 scripts/render_boards.py --board-size 9        # just the one field
python3 scripts/render_boards.py --no-halves           # no letter halves of the field
python3 scripts/render_boards.py --jumbotron-paper a4  # its own sheet size
```

The field board comes out twice: whole, and as two letter halves. See
"Printing a board on small sheets".

- **They follow `cards.py`, not `render.py`.** The palette is the maneuver
  cards' -- dark ink on a light face -- because a print goes on paper and the
  bot's dark board is the wrong thing to hand a printer. The zone tints are the
  bot's three hues lightened, so a coach reads one board as the other.
  Everything is measured in inches, with the same 1/8in bleed the cards carry.
- **The boards are printed on white** (the author, 2026-09-27). They kept the
  cards' cream (`FACE_COLOR`) for a while after the cards went white, on the
  argument that a board is one sheet a game; the author dropped it, since a
  tinted ground is still a full sheet of ink for nothing and the box was already
  white. The palette is `cards.PAPER` -- shared with the rulebooks and their
  figures, which went white the same day -- and the panels went neutral with it
  (`PAPER_PANEL`, the box art's own `#f1f3f5`), because the cards' warm beige
  reads as a stain on white paper. `PAPER_EDGE` is a step darker than the
  box's edge grey, at the old beige's weight: it also draws the dashed card
  guides on the zone rows, and the box's grey vanished into the home zone's blue
  tint.
- **The jumbotron is a letter sheet of its own, landscape**, and the team
  and zone boards half a letter one each: the field board is the only board
  still drawn on tabloid, because its spaces are the only thing on any of
  them that cannot be made smaller. See "The jumbotron's own paper".
- **The clock and the score are the jumbotron's, not the field's.** They were
  bands under the field, where sixteen minutes across a sheet that was already
  carrying the field left a cell an inch wide -- too small to stand a token in,
  which is the only thing those cells are for. On their own board the clock is
  rows of eight (`CLOCK_COLUMNS`), two a half, and every track clears
  `MIN_TOKEN_INCHES`;
  `cell_inches` is that measurement, reported by the CLI. The field board got
  the whole of that space back, which is what makes a space tall enough for
  two sides' meeples -- `FieldGeometry.space_inches`, reported the same way. It is the split the bot's
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
  back of the maneuver card itself, printed in the maneuvers cell (see "The
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
  upstream. Nothing on the team board reads a die at all since the d12 badge
  came off it (the author, 2026-09-28); don't reach for
  `offense_die`/`die_values` in the module, because the data is still right
  there to pick up again by accident.
- **The team board is its own paper: half a letter sheet, and two files.**
  `TEAM_BOARD_PAPER` is letter rather than the tabloid the field and the
  jumbotron are drawn on, because letter is the size a printer in the house
  actually has in it and a coach's board is the one board of the three that
  gets printed twice. `render_team_board` is one board, 8.5 x 5.5in;
  `render_team_board_sheet` is the letter page carrying two of them with a
  dashed line down the seam, which is the sheet a match is cut from. The page
  pastes each board rather than rendering it on the page, so the standard
  page's two halves are the same picture by construction -- everything but
  the seam the cut line is drawn down. See "The team board" below for what
  is on it.
- **A coloured page is two colour teams, one a half** (the author,
  2026-10-03): Teal over Orange (`team-board-2up-teal-orange.png`) and
  Purple over Slime (`team-board-2up-purple-slime.png`), `TEAM_BOARD_PAGES`.
  It was one team's board twice, which made the four colour teams four pages
  when a print run wants one board each -- two pages now. The pairs are a
  printing economy and nothing else; a match between Teal and Purple cuts
  its boards from both pages. The standard page is still the standard board
  twice, since the ink board is nobody's and either coach takes either half.
- **Nothing on any board is written in the module.** The layouts, the
  formations and the standard formation come from `basic_rules.json`, the six maneuvers from `maneuvers.json`, and the roster
  from `players.json` -- so a printed board cannot claim a rule the bot does
  not play, and an import reaches the boards by re-running the script.
- **The geometry a board asserts is read off the same code the bot enforces.**
  `shooting_range_bands` walks `BoardState.is_in_shooting_range` a space at a
  time and `kickoff_marks` reads `kickoff_space_index`, rather than either
  restating where the middle of the board is. Boards 7 and 9 have a midfield
  with a middle, so each prints one kickoff mark for the two sides --
  `kickoff_marks` is a map rather than a space because the rule is asked per
  side, and board 10's four-space midfield answers it twice (home space 5,
  the visitors space 6). It is also what leaves the
  bracket under the field agreeing with the living rules' own table.
- **Every field size but a playtest board is rendered by default.** A print
  run wants the 7- and 9-space boards; `--board-size` narrows it to one. The
  sizes come from `rules.board_layouts`, so a layout added upstream is printed
  without the script being touched -- unless it is in `PLAYTEST_BOARD_SIZES`
  (`d12ball/game.py`), which is board 10 since 2026-10-06: it is played on the
  bot and the web app while the author tries it out, and is printed only when
  asked for by name (`--board-size 10`), so the kit and the box carry the
  boards the game keeps. **Each comes out two ways** -- whole on the tabloid
  sheet, and as its own two letter halves; see "Printing a board on small
  sheets". So do the zone boards, which are per size too.
- **Zones keep their real names on the zone board**, as on the field -- see
  "The zone board". A coach's own goal is the Home Goal for one of them and
  the Visitors Goal for the other, and the field board is read by both, so
  the areas read HOME ZONE / MIDFIELD
  / VISITORS ZONE exactly as the bot's coaching image does -- HOME THIRD /
  VISITORS THIRD on the 9- and 10-space boards, whose outer zones are three
  spaces deep (see "The field" in the living rules, and the 2026-08-24 and
  2026-10-06 entries in the rules log; not to be confused with `FONT_GOAL_ZONE`,
  which labels the goal zone beyond the edge of the board). The team board's
  own formation strip is relative -- a shape is read from a coach's own goal --
  and no longer says so on the board: the author took "read from your own
  goal" off it (2026-09-28), since the standard formation printed under it
  already reads own goal to opponent goal.
- **The team board comes out five times: the standard board and one per colour
  team** (the author, 2026-09-28) -- on their own, five times; on the two-up
  pages, three, since a coloured page carries two teams. The standard board is in ink and names no
  team -- it said "TEAM" in the corner, which named nothing -- and each colour
  team's is in its `TEAM_COLORS` hex with its emoji in the corner. The species
  teams get no board of their own: the print game has no cards for them, and
  each shares its colour team's hex, so their board would be the colour team's
  with a different emoji in the corner. There is no flag for it; every run writes all
  five, and so the print-and-play kit carries them.
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
  name.** What they count is a rule -- fifteen a half, a clock
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
  off the top of them.** `CLOCK` and `FIRST HALF · 00-15`
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
- `d12ball/print/boards/` is generated output and is gitignored, like everything
  under `d12ball/print/` ([cards.md](cards.md), "Where printed output goes").

## The jumbotron's own paper

`JUMBOTRON_PAPER` is **letter, landscape** -- one sheet, not the field
board's tabloid. Like the team board it has a paper of its own for the plain reason
that letter is what a printer in the house has in it, and it is a board that
can be fitted onto one: it carries no field, so nothing on it has to be wide
enough to stand two sides' meeples on. After this, the field board is the
only board that still wants a big sheet, and even it prints on letter as two
halves (above).

- **Landscape, and only landscape** (the author, 2026-09-23). It was drawn
  portrait as well for a while, and portrait was the roomier of the two, but a
  board that sits across the table in front of two coaches is a landscape
  thing and a second orientation was a second picture to look at for nobody's
  benefit. What made landscape workable in the first place was moving the
  token supplies off their full-width band and down the side -- see "The
  supply strip" below.
- **The clock never moved for any of this.** Letter landscape has the width
  for the clock only if the track runs thirteen cells to a row, and
  `CLOCK_COLUMNS` is eight precisely so halftime lands at the end of a row
  and each half is two whole bands rather than a colour change half way along
  one -- a rule about the track,
  `(HALFTIME_MINUTE + 1) % CLOCK_COLUMNS == 0`. It is four rows of eight on
  both sheets.
- **The supply strip.** The three token silos are a **strip down the
  right-hand side**, not a band across the bottom. On a full-width band they
  left most of a row of the sheet empty either side of them, and a row of this
  sheet is what the score track needed. Beside the tracks the same three
  pieces take the width of a margin: `SUPPLY_STRIP` is that width,
  `tracks_right` is where the clock and the score stop, and everything
  measured off the cells reads the narrow pair while the header still spans
  the sheet.
  - **A silo's width is the piece; its height is stack room.** The width is
    fixed at `SILO_INCHES`, because a token does not get bigger because the
    sheet did -- but down the side there is height to spare, and a well a
    coach piles pieces into may as well be as deep as the strip allows. It is
    never shorter than `SILO_INCHES` makes it, so a narrower strip shrinks the
    well rather than squaring it.
- **The score track is what the strip paid for, and it has moved twice
  before.** On the move to letter it wrapped to two rows a side, because
  thirteen cells in one row wants ten inches of track. Then the author cut it
  from 12 to 6 (2026-09-22) to buy every cell the room. With the supplies off
  the bottom row it runs to **10** (2026-09-23), one row a side, eleven cells
  across the width the strip left it.
  - **What it still gives up is the shootout, knowingly.** Six pairings can be
    added to a score that was already level, so a match level at full time can
    finish past the end of this track and a coach has nowhere to stand the
    token. That was the whole argument for 12. It stays traded because the
    track is a printed aid and not a component the rules name -- running off
    the end costs a coach a note on the sheet, where a cell under
    `MIN_TOKEN_INCHES` costs them the use of the board.
  - **A side's label went from beside its rows to over them.** Beside, the
    HOME/VISITORS column was an inch of width that eleven cells needed; over
    them the label reads the way the clock's own band labels already do, which
    is why both now measure `band_label_height` rather than the clock alone.
    The score panel's own title is centred in its strip for the same reason
    the clock's is -- hung from the top at a fixed offset, "SCORE" reached
    past the strip and into "HOME".
  - **The wrap stayed even though nothing wraps**, because it is a
    measurement rather than a decision: a track that grows again breaks into
    rows on its own instead of shrinking its cells, exactly as the clock
    already does.
  - **Check that both sides' tracks fit inside the score panel** after a
    change to it: a panel whose row count is computed is where a row comes to
    be drawn below the panel it belongs to, and a crop is silent -- the same
    failure the team board's footer records below.
- **The chrome is measured in the sheet's own units, not as a share of its
  height, and that was a real bug.** The header band, the footer band and a
  panel's label strip used to be shares of the content height, while
  everything drawn in them is type and type here is sized in `u`, a share of
  the sheet's *width*. So a band held a different number of lines on every
  sheet, and on a landscape one it held fewer than there are: the clock
  panel's own title and the half's label landed in one strip and read as one
  paragraph -- the fault "The clock panel's two label lines" below records as
  already fixed once, arriving back by a different door.
  - `JUMBOTRON_HEADER` is **derived from the type that goes in it**, never
    chosen. It is the title alone now: the two notes that stood on its right
    went on 2026-09-28 (below). `PANEL_TITLE_SIZE` does the same for a
    panel's label strip, which used to be `header * 0.48` and so shrank
    whenever the header was trimmed for a reason that had nothing to do with
    type.
  - `JUMBOTRON_GAP` is the one number here still chosen rather than measured,
    because nothing is drawn in it. It is charged twice -- under the header
    and between the two tracks -- so on the landscape sheet it comes out of
    the cells directly.
- **The clock's notes are in the clock panel, under the second half, and there
  is no footer** (the author, 2026-09-28). The board used to carry two notes
  beside its title ("00-15 in the first half, 15-30 in the second" and when
  the second half starts) and a footer under everything about what a turn and
  a shot cost. The footer was fitted to one line and came out about eight
  point, too small to read across a table, and it had fallen behind the rules
  -- it still charged a shot a minute per space to the attacked end, where the
  Charter charges it 1 (5.4.2). Now:
  - the first header note is gone, since the band labels (`FIRST HALF ·
    00-15`) already say it;
  - when the second half starts is said **between the two halves**, on the
    right of the second half's own label strip (`draw_clock_half_bands`),
    where a coach moving the minute token at halftime is looking, and it costs
    no height;
  - `CLOCK_NOTES` -- what moves the clock, and when last possession is
    declared and who takes it -- are the author's own words, set at
    `CLOCK_NOTE_SIZE` and **wrapped to the track rather than fitted down**,
    at the bottom of the clock panel. They are Laws 16.2 and 16.3 said the way
    a coach at the table needs them, and are written in the module rather
    than read from the data, so a change to either Law is a change there.
  - **The block is measured by the geometry**, `clock_note_lines` and
    `clock_notes_height`, and the clock's cells are what is left above it --
    the same rule as the team board's footer: a band and the lines in it are
    one measurement.
- **A clock cell and a score cell are the same height by measurement, not by
  a chosen share.** `CLOCK_SHARE` was the one share left, picked so the two
  came out equal; with the notes in the clock panel a share would have had to
  be picked again every time a note was reworded. `for_sheet` now takes the
  two panels' titles, band labels and the notes off the height and divides
  the rest over the clock's four rows and the score's four (two a side).
- **Every measurement on this board is a share of the sheet's width**, so the
  smaller sheet took the type down with it -- which is why the clock notes
  have a size of their own and wrap rather than being fitted to a line. A
  clock cell is 1.08 x 0.82in against the tabloid board's 1.93 x 0.85, and a
  score cell 0.79 x 0.82 where eleven of them used to be thirteen at 1.05 x
  0.91; both stay above `MIN_TOKEN_INCHES`.

## Printing a board on small sheets

`render_field_board_halves` writes the field board a second way: two letter
sheets, portrait, `field-board-7-left.png` and `field-board-7-right.png`,
which taped along the cut are the tabloid board. So a print run comes out
with two ledger-size field boards and four letter sheets of halves, and a
house with a letter printer and no tabloid one can still put the real board
on the table. `--no-halves` leaves them out. The print-and-play kit's README
says how to print and tape them.

There used to be a third way -- the field whole on a letter sheet and the two
zone rows on another, cut at the portrait board's quarters
(`render_field_board_pieces`). It went with the zone rows (the author,
2026-10-05): with them off the board there is nothing to cut at a quarter,
and the field alone is a ledger sheet, which two letter sheets halve exactly.

- **A half is a cut of the finished picture, never a second layout.**
  `halve_sheet` crops the rendered board in two and that is the whole of it.
  Re-laying the board out for the smaller paper would have printed a
  *different game* -- a space is the width the sheet's own arithmetic gives
  it (`FieldGeometry.space_width`), and a board laid out on letter would have
  narrower ones. The two taped back together are the board pixel for pixel,
  as the team board's page is its two boards, and for the same reason: two
  pictures that are supposed to be one should be one by construction, not by
  hoping two renders agree.
- **Half a tabloid sheet is exactly a letter sheet, turned the other way**,
  and that is the only reason any of this works: 17 x 11 halves into 8.5 x 11,
  which is letter portrait to the pixel at 300dpi, so nothing is scaled and
  the printed board is the size it says it is. `HALF_PAPERS` is that pairing
  as data -- tabloid into letter, A3 into A4 by the same ISO property -- and
  a new pairing is checked in pixels rather than in inches, because the
  rounding is where a half-pixel would hide. A paper that halves into nothing standard is **absent from the
  table rather than approximated**: the halves still render, `half_paper`
  answers `None`, and the CLI says as much instead of naming a size a printer
  does not stock.
- **Where the cut lands is not a choice, so the layout is what to check.**
  Both halves have to fit the paper below, and only the exact middle gives two
  that do -- so the seam falls wherever the board's bands happen to put it,
  which on the landscape field board is down the middle of it: through the
  title's note, the gap between the two attack arrows, the MIDFIELD label,
  the middle space and its kickoff mark, and the kickoff bracket. Nothing is
  moved to dodge it, because moving it would change the board the tabloid
  sheet prints. Unlike the portrait board's seam, which ran across the
  strip under its labels, this one crosses words; taped edge to edge they
  read whole, and the halves are the fallback for a house with no tabloid
  printer, not the board.
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
bench and the maneuvers -- and a footer. It is printed as two files,
`team-board.png` (one board, 8.5 x 5.5in) and `team-board-2up.png` (a letter
page carrying two of them, cut across the middle -- two colour teams on a
coloured page). It was redrawn from
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
  formation and the closing reminder came to be drawn *below* the bottom edge of
  the old panel and cropped away -- on a render that looked fine, because
  the crop is silent, so look at the whole render after a change to a band.
- **A line that cannot be legible is dropped, not shrunk.**
  `fitted_print_font` answers with `None` below its floor and
  `draw_fitted` is for lines that have to be drawn whatever happens; a
  caption uses the first and is left off when it will not fit, because a
  caption nobody can read is a worse failure than one left off.
- **A cell's caption is a second line, not the right-hand end of the
  title's.** Sharing one line is what put "players who have yet to play"
  hard against the next cell's title, and a caption squeezed into what a
  title leaves has no width of its own to be legible in.
- **The header is the title, the team's emoji and the roster's counts.** The
  roster line is the nine cards by role and nothing else; "six of your 9 on
  the field, three on the bench" in front of it went (the author,
  2026-09-28). **The team is its emoji, not its name** (the author,
  2026-10-04): the ringed letter the bot puts beside a team in Discord and the
  player cards carry in their header's corner (`player_cards.team_emoji`), so
  the board and the cards laid on it are marked the same way. It stands as
  tall as the header's two lines, and the roster line is fitted to what it
  leaves. It replaced the team's name in capitals, which is why the board has
  five type sizes rather than six. The standard board has nothing in the
  corner -- see "The team board comes out five times" above.
- **The maneuvers cell is the back of the maneuver card, pasted.** It was
  titled HEAD COACH until the author renamed it MANEUVERS (2026-09-28), which
  is what is in it. It is
  the same picture `cards.render_maneuver_card_back` draws for the deck --
  the six ranks on one cycle, a solid arrow to what a rank beats and a
  dashed one to what it ties -- so a coach reading a matchup off the board
  and a coach reading it off the card in their hand are reading one picture.
  It replaced two columns of names that said which maneuver was which rank
  and nothing about what beat what. It is pasted rather than redrawn because
  a second drawing of the cycle is a second thing to keep true when a rank
  changes; its corners are cut to the card's own radius so the board's ground
  shows around it rather than four white squares.
- **The column is cut to the card, not the card fitted to a third of the
  row.** `reference` is the back at the height the row leaves it, capped at a
  real card (it is drawn at 300dpi and printing it larger would only soften
  it), and the two benches divide what is left. Equal thirds left a band of
  empty board beside the picture.
- **A bench's guide is three cards stacked sideways, and under poker size.**
  A bench holds three cards, and the guide draws them the way they lie: each
  card `TEAM_BENCH_CASCADE` (a fifth) of its width to the right of the one
  behind it, so the left edge of every card shows (the author, 2026-09-28).
  A card behind shows only its left edge and its top and bottom edges out to
  the card in front of it -- no line crosses a card's face. It replaced a
  single outline, which said nothing about there being three, and then a
  first cut that stacked the three downward. Side by side without overlapping
  does not fit, and neither does the stack at life size: a bench column is
  two and a half inches wide on half a letter sheet, and the author's call
  was legible over life-size, so the guide is a card's proportions at what
  the column and the row leave, and a bench stacks on the area, overhanging
  it. `card_slot_inches` reports one card of the stack and the CLI says so in
  as many words.
- **The footer is three lines: the formation strip, the standard formation
  and one reminder.** The d12 badge and "every roll in the game is a d12"
  came off it (the author, 2026-09-28), as did "read from your own goal" on
  the strip; the deal is worded "Standard Formation", since it is one of the
  shapes on the strip above it.
- **The cut line is on the seam of the two-up page and on neither board.**
  A dashed line down the middle of the sheet is the one mark on it that
  belongs to the page rather than to either coach.

## Goal zones

`draw_end_zone` draws each goal zone, American-football style, beyond space 1
and beyond the board's last space (see "The field" in the living rules) -- not
squeezed into either one's own space, because both are already full of
meeples under the standard deal (see
"Formations and occupancy" in [formations-and-occupancy.md](formations-and-occupancy.md)). It is drawn in the margin between the board and
the canvas edge, so `GOAL_ZONE_WIDTH` is whatever that margin leaves once
`GOAL_ZONE_EDGE_MARGIN` (to the canvas edge) and `GOAL_ZONE_GAP` (to the
board's own outline) are taken out -- there is no spare canvas to grow it
into without widening the board itself.

- **"GOAL" runs the zone's length in the defending team's own color** --
  the home team's to the left of space 1, the visitors' to the right of the
  board's last space -- rotated 90°, the way a real end zone's lettering
  reads sideways on a field running left to right. Letters are spaced apart
  by `GOAL_ZONE_LETTER_SPACING`, on top of the font's own advance, because a
  four-letter word at a font size that fits the zone's width reads as a
  small cluster rather than something that fills a tall zone.
- **The Visitors Goal is rotated a further 180°** (`angle=270` on
  `draw_end_zone`, the author's call) from the Home Goal's -- a real
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
  goal zones included** (`FIELD_FAR_LEFT`/`FIELD_FAR_RIGHT`, `JUMBOTRON_LEFT`/
  `JUMBOTRON_RIGHT`), rather than stopping at the board's own edge and
  leaving the goal zones looking like they belong to nobody.
- **`BENCH`/`BACK BENCH` position off the team name's own measured width**,
  not a fixed offset -- a species team's name (`Fire Demons`, `Telekinetics`)
  is wider than a color team's and was landing underneath "BENCH" rather
  than beside it. `TEAM_BOARD_BENCH_MIN_X`/`TEAM_BOARD_BACK_BENCH_MIN_X` are
  what a short name already left in place, so nothing shifts for the common
  case.
- **The printed field board carries its own goal zones now**, `draw_field_end_zones`
  in `boards.py` -- the print counterpart of `draw_end_zone`, not a second
  drawing of the same pixels: it is a different rendering stack (`Sheet`
  rather than a raw canvas) at a different resolution (300dpi rather than the
  bot's fixed 2200px), so the geometry and the font-fit are worked out fresh
  rather than shared. `FieldGeometry` narrows the strip itself to
  `strip_left`/`strip_right`, reserving a space's width plus `GOAL_GAP` on each
  side for it; `left`/`right` stay the full content width for the header, the
  direction arrows and the shooting-range bracket, which read the wide pair
  same as the bot's own jumbotron and team boards span its goal zones. **It is
  drawn in ink, not a team's colour** -- the field board is a template for the
  tabletop game with no match to read a team from, unlike the bot's own board,
  which always has one.
  - **A goal zone is a space wide** (the author, 2026-10-05), which was
    half of why the board went landscape. It was a sliver beside the strip
    -- a third of an inch, then 0.45in when the author asked for more room
    for the goals (2026-09-28) -- and the strip divided what it left. Now
    `FieldGeometry.for_sheet` divides the width by the spaces *and* the two
    goals, so a goal is exactly as wide as a space: 1.81in on the 7-space
    board and 1.48in on the 9-space one, each 7.67in tall (the portrait
    board's spaces were 1.35 and 1.05in wide). `GOAL_GAP` is the only thing
    between a goal and the strip's outline. "GOAL" is fitted to the zone,
    so it grew with it.

## The zone board

A coach's **zone board** is where their fielded cards are assigned to a zone
(Law 2.8): a cell per zone, tinted the field's own colour for that zone, each
guided for three cards. It is half a letter sheet, the team board's own size,
and the two are a coach's strip: laid end to end along their side of the
field, **zone board on the coach's left and team board on their right**,
seventeen inches together, the field's own length (the author, 2026-10-05).
`render_zone_board` is one; `render_zone_board_sheet` is the letter page both
coaches' are cut from, home over the visitors, with the team board's own
dashed cut line on its seam. Printed with the team board's two-up page, a
match is two letter sheets cut across the middle.

It replaced the **zone-assignment rows**, a card row per zone above the strip
for the visiting coach and below it for home, on the field board itself. Those
are what made the field board portrait: two 3.5in card rows wanted the 17in
length, and the strip paid for it in width -- a 9-space board's spaces came
out just over an inch wide. With the rows off the board, the strip has the
17in instead (a 9-space space is 1.48in wide, a 7-space one 1.81in, with
each goal zone as wide again -- see "Goal zones"), and the
zones went to each coach's own side of the table.

- **Per side and per board size.** The two coaches sit opposite each other,
  and each reads the field from their own end, so a coach's own zone is on
  their left: home's board runs HOME ZONE, MIDFIELD, VISITORS ZONE and the
  visitors' the other way round (`zone_order`). The 9- and 10-space boards'
  outer zones are thirds (`zone_labels`), so each size has its own pair. Both
  print upright -- each is a board of its own, picked up and laid at its
  coach's seat -- where the visiting row on the old field board was rotated
  180 degrees cell by cell to read upright across the table.
- **A zone is a card wide, and its three cards cascade down it.** Three
  cells across 8.5in leave each one 2.6in, a poker card and a hair, so the
  guide is three real-size cards each `ZONE_CASCADE` (a tenth) of a card's
  height below the one behind it -- the top of each card, its name, shows.
  The board's chrome is cut to pay for that height: a one-line header (the
  title, where the board goes, whose it is) and a one-line label per cell,
  no caption and no footer. `zone_slot_inches` reports the guide and the CLI
  says whether it is still a whole card; a longer label or a bigger margin
  will shrink it, and nothing else will tell you.
- **The dashed guides are a cue, not a slot count.** `CARDS_PER_AREA`
  (three) is what a zone holds under the widest formation, and nothing here
  enforces it; a coach may stack more.
- **The team board's reminder points at it**: "A card's zone is assigned on
  the zone board beside this one."
- **The field header stacks rather than sitting side by side.**
  `draw_field_header`'s title on the left and its note on the right used to
  overlap in the middle on the portrait sheet; both are stacked in one
  left-aligned column, which cannot overlap regardless of paper size or how
  long the wording runs. **The header has one note**, the two periods and
  who kicks off each. "The clock, the score and the token supplies are kept
  on the jumbotron board" came off (the author, 2026-09-28), and so did
  "shoot only from here" under each shooting-range bracket, whose label
  already names it. The header band and the bracket band are measured from
  what is in them (`FIELD_NOTE_TOP`, `FIELD_NOTE_LEADING`), and the strip
  got the height they gave up.
- **The field board's type is sized off its short side** (`field_sheet`),
  so turning the sheet landscape left every word the size it printed at on
  the portrait board rather than half again as big; `Sheet`'s unit is a
  thousandth of whatever `unit_width` names, the width by default.

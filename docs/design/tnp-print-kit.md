# The New Project's print-and-play kit

Design notes for fool-bot; the map is [CLAUDE.md](../../CLAUDE.md), the rules are [tnp-rules.md](../tnp-rules.md), the game on Discord is [tnp.md](tnp.md).

`python3 scripts/render_tnp_kit.py` builds **the basic game** for a
table -- Humans against Humans, Blue against Green, no technology cards
(TNP 8 is step 9's) -- into `tnpkit/print/` (gitignored), `--zip` beside
it. It was asked for by the author on 2026-11-06. Nothing in it is
tested for how it looks, by the standing rule that nothing printed is
(CLAUDE.md, "Tests"): render it and look.

## What is in it

| Sheet | Paper | What it is |
| --- | --- | --- |
| `map` | tabloid | Map 3.3, each territory's setup tokens as a pill, the two point contacts |
| `battle-mat` | tabloid | The round track, the initiative groups, the line's four rows in columns, the modifiers and hits |
| `track-sheet` | letter | The harvest track, 0 to 49, and four base cards to cut out |
| `<seat>-screen` | tabloid | Folded in three; its inside is the player aid |
| `<seat>-keywords` | letter | Every unit trait with the units that carry it, and every term the rules use |
| `<seat>-player-board` | 2 x letter | The four facilities, two a sheet |
| `<seat>-deployment-board` | letter | Attack spots A and B, a defense spot a territory and the base's, the available units |
| `<seat>-unit-counters` | letter | 80 counters, 1 in: every unit as many times as its supply |
| `tokens` | 3 x letter | 298 tokens, 3/4 in |
| `rules.pdf` | letter | docs/tnp-rules.md, set by D12 Ball's rulebook builder |

Three PDFs to print from: `print-letter.pdf`, `print-tabloid.pdf`, and
`print-tabloid-as-letter.pdf`, each tabloid sheet cut into two letter
halves. `sheets/` has each sheet as a PNG and a PDF. The README the
build writes says what each sheet is, the token counts, what a table
still needs (d12s, ten or more) and the setup.

## Its own package, on the bot's pictures

**`tnpkit/` is a package of its own, not part of `tnp/`**, because
`tnp/` lets one module import Pillow, `tnp/render.py`
(`tests/test_tnp_purity.py`). The kit draws with that module's
primitives -- `font`, `_icon`, `_shield`, `_pill`, `_wrap`, the palette,
the seat, type and rating colours -- and draws the map from the same
traced outlines with the same placement reading (`_fit_centre`,
`_anchor`), so a resource token, a control shield or a rating's cell is
the same picture on the table as on Discord, and a new map's outlines
reach the printed map by rebuilding it.

It does not call `render_map` or `render_board`. Those are laid out in
Discord's pixels for a live position -- the pool in the board's header,
supply left, a queue as a count -- and the table needs the empty
version of each, at 300 dpi, with places to put things: a queue box, a
square for each Built marker, a slot for a target chip.

**Every number is read from the data**: a unit's cost, ratings,
initiative, traits and supply from `humans.json`; caps, build costs,
upgrades, the conversion rates, the starting pool and units, the
Chopper Carrier's capacity and the deployed-together limit from
`human_board.json`; the territories, their tokens and the winning count
(more than half of them, 49 of 96) from `map.json`. The counts the kit
decides for itself -- materials and gold, control, Stranded and damage
tokens -- are `pieces.TOKEN_COUNTS`, and the README says a table that
runs out uses anything.

## The pieces

- **Units are counters, a counter a unit, as many as the supply.** The
  2018 deployment board ("territory defense spaces and attack cards
  1.2", in the Drive's *Battle and deployment boards*) says "Place Unit
  tokens in attack and defense spaces", so the physical game was always
  counters; the supply is "the most units of that kind a seat may have
  at once" (TNP 2.3), so printing exactly that many makes the limit
  physical. The supply adds to 80 a seat, which at 1 inch is one letter
  sheet of 8 x 10.
- **A counter is framed in its seat's colour and banded in its type's**
  (board v4's infantry green, armored red, air blue), with its seat's
  shield beside its traits. The band is inset so a white edge parts it
  from the frame: Green's infantry is green on green otherwise, which
  the first render showed.
- **Everything is one-sided.** Nothing in the basic game is turned
  over to show a second state -- a Tough unit's damage is a token on it
  (TNP 6.8), a hidden pile is behind the screen rather than face down --
  so no sheet needs duplex printing and nothing can come out misaligned.
- **A target chip, not a marker on a track.** Each attack spot needs to
  say what it attacks. A track of the sixteen targets with a marker on
  one was tried first: at 3/4 inch a marker covers a 1/2-inch cell's
  neighbours, and anything larger does not fit the board. A chip naming
  its target, laid in the spot's slot, is what the 2018 board did ("with
  territory cards"), and reads at a glance. **Two sets a seat**, 1 to 15
  and BASE, because A and B may attack the same territory -- the only
  way to harvest twice in a turn (TNP 5.8).
- **The defense spots are fixed, one a territory**, rather than generic
  spaces labelled with a chip: a seat may attack a territory it also
  defends, and a fixed spot needs no chip.
- **Built markers and the queue.** A facility or an upgrade bought in
  Infrastructure is finished at Production and Trade (TNP 5.2, 5.9), so
  the board has a queue in each facility: its units and the Built marker
  of whatever is being built go there, and move at Production -- the
  units to the available units, the marker onto its square. A seat has a
  marker for each facility that does not start built and each upgrade.
- **The harvest track** is the count TNP 1.3 checks at Cleanup: tokens
  taken off the map, whatever was done with them since, so a seat's
  pool cannot be counted instead.

## The screen is a summary that cites

The player aid is three panels -- the turn, a battle, the numbers --
and every paragraph names the section it condenses. **It is never a
second copy of the rules**: the kit carries docs/tnp-rules.md itself as
`rules.pdf`, and a reader with a question goes there. That is the same
line D12 Ball's reference cards hold. The rules PDF is set by
`d12ball.rulebooks.book_bytes` over a `Book` of its own, unnumbered,
since TNP's sections are numbered by hand.

The screen is printed on one side and folded so the print faces its
seat; the back is plain paper, and the pool stands in front of it,
where both seats see it (TNP 2.2).

## The keyword sheet

A seat's glossary, beside the screen (the author, 2026-11-06: "the
player aide with all the keywords"): **every trait a unit carries**, and
under each the units that carry it, and **every term the rules use**,
alphabetical, each with the section it is from. The traits are read
from the data -- a unit given a new trait appears under it on the next
build, and a trait `keywords.TRAITS` has no words for stops the build
(a `KeyError` naming it) rather than printing a bare name. The terms
are the kit's own list, `TERMS`, held to docs/tnp-rules.md by reading,
like the screen. One letter sheet: the entries are tried at falling
sizes (`SIZES`) and drawn at the largest that fits, about 7 pt today.

## Paper

300 dpi; letter and tabloid. **A tabloid sheet's letter halves are a
cut of the finished sheet, never a second layout**, as D12 Ball's field
board's are ([printed-boards.md](printed-boards.md)): 17 x 11 halves
into two 8.5 x 11 to the pixel, and the seam falls where it falls. The
cut sheets keep a 1/4-inch margin, which fits the 80 counters on one
sheet and is still inside what a home printer prints; every piece is
outlined, so each grey line is one cut between two pieces, with ticks
into the margin to line the first one up.

## Open

Taken as defaults on 2026-11-06, for the author to change:

- the token counts in `TOKEN_COUNTS`, materials and gold in 1s and 5s;
- the rules PDF opens with the bot's own preamble (which version, how
  the bot plays it), since it is docs/tnp-rules.md unedited;
- the advanced game's cards, and the third attack spot, are not in it.

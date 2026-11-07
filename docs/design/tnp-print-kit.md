# The New Project's print-and-play kit

Design notes for fool-bot; the map is [CLAUDE.md](../../CLAUDE.md), the rules are [tnp-rules.md](../tnp-rules.md), the game on Discord is [tnp.md](tnp.md).

`python3 scripts/render_tnp_kit.py` builds **the basic game** for a
table -- Humans against Humans, Blue against Green, no technology cards
(TNP 8 is step 9's) -- into `tnp/print/` (gitignored), `--zip` beside
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
| `<seat>-unit-traits` | letter | Every unit trait, with the units that carry it |
| `<seat>-keywords` | 2 x letter | Every term the rules use, with its section |
| `<seat>-territory-cards` | 2 x letter | One card a territory and the enemy base, 2.5 x 3.5 in: a pile goes on the card of what it attacks or defends |
| `<seat>-player-board` | 2 x letter | The four facilities, two a sheet |
| `<seat>-deployment-board` | tabloid | Attack spots A, B and C, three defense spots, the base's own spot, the available units |
| `<seat>-unit-counters` | 3 x letter | 80 counters, 1.5 in: every unit as many times as its supply |
| `tokens` | 2 x letter | 234 tokens, 3/4 in |
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
square for each Built marker, a slot for a territory card.

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
  physical. The supply adds to 80 a seat: three letter sheets of 5 x 6
  at 1.5 inches, the size the author asked for (2026-11-06: "tokens
  should be larger and have larger font").
- **Nothing coloured reaches a piece's edge** (the author, 2026-11-06:
  no "colored frames which would not be easy to cut well"). A counter
  and a territory card are white to the cut line, with a white margin
  inside it, so a cut a little off leaves no sliver of colour. **The
  player's shield says whose a piece is** -- in the corner of a
  counter's picture and of a card -- and that is enough. The first
  draft framed both in the seat's colour.
- **A counter is banded in its type's colour** (board v4's infantry
  green, armored red, air blue) with its name, type and initiative; then
  **room for the unit's picture**, `tnp/images/units/<slug>.png`, drawn
  once it exists and an empty outline until then; then its three
  ratings, each the d12 number it needs with **the rating's name --
  Strong, Fair, Weak, Poor -- under it** (the author, 2026-11-06); then
  its traits.
- **Everything is one-sided.** Nothing in the basic game is turned
  over to show a second state -- a Tough unit's damage is a token on it
  (TNP 6.8), a hidden pile is behind the screen rather than face down --
  so no sheet needs duplex printing and nothing can come out misaligned.
- **A territory card under every pile** (the author, 2026-11-06: "we
  need a deck of territory cards to go in the piles"). Each player has a
  deck, one card for each territory and the enemy base -- its number, a
  small map with it picked out, what it is adjacent to and holds, all
  from `map.json` -- and a pile in an attack or defense spot sits on the
  card of what it attacks or defends, as the 2018 board's "territory
  cards" did. They replaced the first draft's target chips. **One card a
  territory** is enough because a player never attacks a territory it
  defends (the author, 2026-11-06), so the deck also keeps a territory to
  one pile a turn. **A card is 2.5 x 3.5 in, a playing card** (the
  author, 2026-11-06), portrait, laid on its side on the sheet
  (`cut_sheet(turned=True)`) so eight fit a letter sheet and a deck is
  two; a stack of counters sits on it.
- **The deployment board is tabloid** so every spot holds a whole
  card. Each spot is just big enough for its card and its name, with no
  text in it (the author, 2026-11-06: "no need for all this empty space
  and text on the attack spots"): the three attack spots, A, B and
  **C, with the Command and Control CPU, an upgrade of the base** (the
  author, 2026-11-06; the rules and the bot still have it a tech, TNP
  2.5), over the three defense spots, and the base's spot and the
  available units beside both rows. A row's one line of rules is above it.
- **Three defense spots, and the base's** (the author, 2026-11-06:
  "there are only 3 defense spots ... you can't defend more than that at
  any given turn"). The base's spot is a fourth, its own; a territory
  where stranded units stand keeps one of the three. **docs/tnp-rules.md
  and the bot still give a spot to every held territory** (TNP 2.5): the
  rules change is in another PR, and the kit prints the new rule ahead
  of it, citing TNP 2.5.
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
since TNP's sections are numbered by hand. **The preamble is left out**
(the author, 2026-11-06: "definitely don't need this preamble"):
`kit.player_rules` keeps the title and everything from section 1 on, so
the PDF opens on the rules and is still built from the one file.

The screen is printed on one side and folded so the print faces its
seat; the back is plain paper, and the pool stands in front of it,
where both seats see it (TNP 2.2).

## The unit traits and the keywords

Each player's glossary, beside the screen (the author, 2026-11-06: "the
player aide with all the keywords"), in two parts the author asked to be
kept apart: **the unit traits**, a sheet of their own, each with the
units that carry it, and **the keywords**, every term the rules use,
alphabetical, each with the section it is from. The traits are read
from the data -- a unit given a new trait appears under it on the next
build, and a trait `keywords.TRAITS` has no words for stops the build
(a `KeyError` naming it) rather than printing a bare name. The terms
are the kit's own list, `TERMS`, held to docs/tnp-rules.md by reading,
like the screen. **The type is a size, never a fit** (the author,
2026-11-06: "larger font"): about 12 pt for the traits and 10 pt for the
terms, which flow over as many sheets as they take -- two today.

## The printed words

**A player, never a seat** (the author, 2026-11-06). The bot's code and
docs say seat; everything the kit prints says player. And no printed
sentence is a fragment: "the advanced game's" on its own is not a
sentence (the author, 2026-11-06).

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

The token counts in `TOKEN_COUNTS` are the author's (2026-11-06). Open:

- the rules PDF still carries the author's dated attributions
  ("the author, 2026-11-05"), the bot's notes ("The bot plays two
  seats"), the *step 9's* markers and the change log;
- the advanced game's cards are not in it;
- the Command and Control CPU upgrade is printed on the deployment
  board, but not yet on the player board, in the rules or in the bot.

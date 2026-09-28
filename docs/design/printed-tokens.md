# The 3D-printed tokens

`scripts/render_token_models.py` turns the condition-token art into
models for a 3D printer. It writes into `print/tokens-3d/` unless `--out`
names somewhere else -- gitignored, like the boards and the rulebooks
-- and nothing about it is tested -- it is checked with
`--preview` and by looking, like everything else that is printed.

## Three tokens, two faces each

| Token | One face | The other |
| --- | --- | --- |
| `exhaust` | the amber ZZZ triangle | the same triangle in Cyborg teal |
| `exhausted` | EXHAUSTED (blue) | INJURED (red) |
| `drained` | DRAINED (teal) | DAMAGED (amber) |

The author chose these pairings (2026-09-25). The exhaustion token has a
Cyborg side because a Cyborg's own count is drawn teal in the bot
(`exhaust_cyborg.png`). The other two put a human condition with the next one: an Exhausted
player who fails the check is Injured. Drained and Damaged are the Cyborg
names for the same two conditions ("Lithium Powered" in the living rules).

## The art is the bot's, traced

The triangle is traced from `exhaust.png` itself, and the teal side from
`recolor_exhaust_token.recolor` of it. The words are traced from
`render_condition_tokens.render_token`. So a token on the table, a
silo on the jumbotron and an icon in Discord are one picture -- which is
also why the words and the Zs went to Roboto Slab (2026-09-27) by
redrawing that art, and reach the 3MFs when this script is rerun. A
pixel counts as accent when it is past halfway from the ink to the accent
colour, which is the reading the recolour script uses.

**Three changes to the square art, all because of the nozzle.** At 19 mm
the PNG's ring is about 0.4 mm, one line from a 0.4 mm nozzle, and a ray is
thinner than that. So the re-render widens the ring and the black edge to
`MIN_FEATURE` (0.8 mm, two lines), drops the rays, and shrinks the word so
it sits inside the ring with a gap on both sides. Without that last change
the widened ring runs into the D. Then `BOLDEN` thickens the traced
colour by 0.05 mm, which cuts the share of EXHAUSTED under 0.4 mm from 18% to
under 1%. The script prints that measurement for every face each run, both
the colour and the black between the letters, so a change of size shows its cost.

## Size: the silo decides

`--size` defaults to 19 mm because a jumbotron silo is `SILO_INCHES[0]`
(20.3 mm) wide and holds one token's width. A bigger token would give
the letters more room, but the silos would then need reprinting to match.

## Two ways to print, because printers differ

- **One piece, flush** (`<token>.3mf`): a black body and a coloured inlay
  0.6 mm (three 0.2 mm layers) deep in each face. It needs a printer that changes
  filament on its own, because every layer of an inlay has two colours.
  The 3MF holds one object whose *components* are the three parts, and that
  is what makes PrusaSlicer, Bambu Studio and OrcaSlicer load them as parts
  of one object. The bottom inlay is mirrored, since it is seen from
  underneath.
- **Two halves, raised art** (`<token>_half_<face>.stl`): a 1.2 mm black
  slab with the art 0.4 mm proud. Each layer is a single colour, so one
  filament change at 1.2 mm is enough, and it works on any printer. The
  two halves are glued back to back. A flush face on a
  single-filament printer is not offered. That would need the art and the
  black in the first layer together, which means printing that layer in
  several passes with a swap between them, and that is too fiddly to ask
  of a coach.

The script needs `numpy scikit-image shapely trimesh manifold3d
mapbox-earcut`. The bot does not, which is why they are not in
`requirements.txt` -- except numpy, which is there for the landing
build's dice ([landing-pages.md](landing-pages.md)).

## Paper tokens: the kit's two sheets

The print-and-play kit carries the same three tokens on paper
(`d12ball/token_sheet.py`, CLI `scripts/render_token_sheet.py`), because
a kit that sends a table off to find poker chips is not a kit (the
author, 2026-09-27). Same pairings, same art -- the PNGs `render.py`
loads, as they are, rays and all, since paper has no nozzle -- and the
same 19 mm, so a paper token sits in a jumbotron silo like a printed one.

- **Printed duplex, as the author asked** (2026-09-27): two letter sheets,
  `front-sheet.png` with every token's front face and `back-sheet.png`
  with its back, printed on the two sides of one piece of paper. A
  duplex printer flips the paper about its long edge, so a back is at
  its front's position mirrored about the page's centre line -- the
  correction `player_cards.duplex_order` makes for the player cards, done
  on positions here, so a short last row mirrors exactly too. A
  fold-over pair (both faces joined on one edge, cut, folded and glued)
  was the first draft and was replaced by this.
- **Each face has a black margin, on both sides** (`BLEED_INCHES`, about
  a millimetre, the art's outline grown in the colour of its own edge,
  read off the art, since the triangle's black is a warm one). A home
  duplex printer puts the back a little off the front; a millimetre is
  a tenth of a 19 mm token, and without the margin that lands as white
  paper at the cut. With it, the cut runs through black on both sides.
- **The page is full, every kind is on it, and the triangles are the
  most** (`TOKEN_COUNTS`; the author, 2026-09-27: the exact count does not
  matter much, since a table that wants more prints the page again). Ten
  rows of eight on letter: 48 exhaustion, 16 Exhausted/Injured and 16
  Drained/Damaged -- all six faces. The white between two margins is 3 mm
  (`GAP_INCHES`), which is what gets a row to eight. The sheets refuse
  counts that do not fit rather than running off the page.
- `TOKEN_FACES` holds the pairings for paper, front first;
  `render_token_models.py`'s `TOKENS` holds them for the printer, with
  the accent colours it traces. A change to a pairing is a change to both.

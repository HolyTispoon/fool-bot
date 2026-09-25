# The 3D-printed tokens

`scripts/render_token_models.py` turns the condition-token art into
models for a 3D printer. It writes nothing into the tree (`--out` is
required, and printed output is not tracked, like the boards and the
rulebooks), and nothing about it is tested -- it is checked with
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
silo on the jumbotron and an icon in Discord are one picture. A
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
`requirements.txt`.

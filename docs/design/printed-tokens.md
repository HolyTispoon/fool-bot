# The 3D-printed tokens

`scripts/render_token_models.py` turns the condition-token art into
models for a 3D printer. It writes into `d12ball/print/tokens-3d/` unless `--out`
names somewhere else -- gitignored, like the boards and the rulebooks
-- and nothing about it is tested -- it is checked with
`--preview` and by looking, like everything else that is printed.

## Three tokens, two faces each

| Token | One face | The other |
| --- | --- | --- |
| `exhaust` | the amber ZZZ triangle | the same triangle in Cyborg teal |
| `exhausted` | EXHAUSTED (amber) | INJURED (red) |
| `drained` | DRAINED (teal) | DAMAGED (wine) |

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

## Plates: a table's worth in one file

Both ways also come as plates, because one token per file means
arranging dozens of copies by hand in the slicer (the author,
2026-10-09, asked for whole tokens as well as halves):

- `plate_<token>.3mf` (and `plate_<token>_body/_top/_bottom.stl`) is the
  whole one-piece token over and over. Each copy is its own object whose
  components are the same three parts moved into place, so the parts'
  meshes are written once and a slicer still sees body and inlays as one
  object a token. It still needs a printer that changes filament on its
  own.
- `plate_half_<face>.stl` holds one face's halves. **A half-plate holds
  one face alone**, because on one filament the whole plate changes to
  one colour at the slab's height; the token's other face is the next
  plate.

`--count` defaults to the paper sheet's `TOKEN_COUNTS` (48 exhaustion,
16 of each condition), so a plate of each is the kit's set in plastic and
the two counts are one number. `grid` lays them out as square as `--bed`
allows, 180 x 150 mm by default -- inside a Prusa Mini, an Ender 3, a
Bambu A1 mini and a Dremel 3D45 -- and refuses a count that does not fit
rather than running off the bed. The single-token files are unchanged.

The script needs `numpy scikit-image shapely trimesh manifold3d
mapbox-earcut`. The bot does not, which is why they are not in
`requirements.txt` -- except numpy, which is there for the landing
build's dice ([landing-pages.md](landing-pages.md)).

## Paper tokens: the kit's sheets, light and dark

The print-and-play kit carries the same three tokens on paper
(`d12ball/token_sheet.py`, CLI `scripts/render_token_sheet.py`), because
a kit that sends a table off to find poker chips is not a kit (the
author, 2026-09-27). Same pairings, same shapes -- a rounded triangle
point down for exhaustion, a rounded square for a condition -- and the
same 19 mm, so a paper token sits in a jumbotron silo like a printed one.

- **Printed duplex, as the author asked** (2026-09-27): two letter sheets,
  `<style>-front-sheet.png` with every token's front face and
  `<style>-back-sheet.png` with its back, printed on the two sides of one piece of paper. A
  duplex printer flips the paper about its long edge, so a back is at
  its front's position mirrored about the page's centre line -- the
  correction `player_cards.duplex_order` makes for the player cards, done
  on positions here, so a short last row mirrors exactly too. A
  fold-over pair (both faces joined on one edge, cut, folded and glued)
  was the first draft and was replaced by this.
- **Two styles, and the kit carries both** (`STYLES`; the author,
  2026-09-28). `dark` is the bot's art as it is, rays and all, since
  paper has no nozzle, each face on a black margin (`BLEED_INCHES`, a
  millimetre, the art's outline grown in the colour of its own edge) so
  a back printed a little out of line leaves black at the cut rather
  than white. `light` is drawn for paper, because a sheet of black
  tokens is a cartridge of ink -- and printing the art's black white
  was tried first and left colours chosen to glow on black too faint
  to read on white. A light face is a pale tint inside a ring with its
  word in a deep ink (`PAPER_FACES`: per face, the hue the bot's art
  uses, taken dark enough to read at 19 mm, and a tint light enough to
  cost little). A square is drawn from scratch (`paper_face`), the word
  squashed into one box so EXHAUSTED and INJURED read as a set, with no
  sunburst, which was there to fill a black face. **The triangle is
  not drawn: it is the dark art's own regions** (`triangle_regions`),
  its black face printed in the tint and everything else -- the black
  edge, the ring and the three Zs -- in the deep ink, because the author
  wants the Zs exactly where the dark token has them, and a redrawn
  set drifted. So its ring is the art's edge and ring together. The 3D
  tokens keep the bot's art; light is paper's alone.
- **A light front carries a cut line; its back does not.** Cutting on the
  ring's own edge would cut into a back printed a little out of line,
  so the front has a grey hairline `CUT_MARGIN_INCHES` (about a millimetre) outside the
  token. A home duplex printer puts the back a little off the front; a
  millimetre of white between the line and the token means the back's
  ring survives the cut, and a line on the back would only show as a
  stray grey edge where it missed.
- **The page is full, every kind is on it, and the triangles are the
  most** (`TOKEN_COUNTS`; the author, 2026-09-27: the exact count does not
  matter much, since a table that wants more prints the page again). Ten
  rows of eight on letter: 48 exhaustion, 16 Exhausted/Injured and 16
  Drained/Damaged -- all six faces, in either style. The white between
  two cut lines (or two black margins) is 2.5 mm (`GAP_INCHES`), which is what gets a row to eight. The sheets refuse
  counts that do not fit rather than running off the page.
- `TOKEN_FACES` holds the pairings for paper, front first, by the names
  `PAPER_FACES` and `DARK_ART` draw;
  `render_token_models.py`'s `TOKENS` holds them for the printer, with
  the accent colours it traces. A change to a pairing is a change to both.

## Role tokens: D12 Ball 2.0's, on paper

`d12ball/role_tokens.py` (CLI `scripts/render_role_tokens.py`, into
`d12ball/print/role-tokens/`) draws a token a coach lays on a player's
card to say which role they hold. In 2.0 a role is the formation's, not
the player's, and moves from card to card in a Coaching Choice
(rules-2.0 section 4), while the printed card still says its 1.0 role --
so the role has to be a loose piece (the author, 2026-10-24). The
players on the field are standees for the same reason
([standees.md](standees.md)).

- **19 mm, on the card** (the author, 2026-10-24), the condition tokens'
  size and rounded square (`SQUARE_CORNER`, `RING`). The trade was put to
  the author: on the zone board a zone's cards cascade 0.35in apart
  (`ZONE_CASCADE`), so a 19 mm token covers the next card or is covered
  by it, and a zone's cards have to be spread out where a token is on
  each. A tag small enough for the strip the cascade leaves showing
  (about 13 x 8 mm) was the other choice; the author took the 19 mm
  token.
- **A token is a zone's, front and back** (the author, 2026-10-24): the
  zone's unique role on the front and its standard role on the back --
  Fullback over Defender, Playmaker over Midfielder, Striker over
  Winger, `FORMATION_ZONE_ROLES`' pairs -- so turning one over is the
  trade between a zone's two roles. The cost, put to the author with
  the choice: a zone can show two unique roles by mistake. **So the two sides look
  different, not only read different**: a unique role's face is filled
  with the team's colour, its letters in `high_contrast_ink`, and a
  standard role's is white inside a ring of that colour, its letters in
  ink. Two filled tokens in a zone can be seen across the table.
- **Nine a team**: as many of a zone's tokens as any formation puts
  players in that zone (`tokens_per_zone`, read off the ruleset's
  formations -- 3-2-1, 2-3-1 and 1-2-3 each put three in one zone), so a
  new formation reaches the count by re-running the script.
- **A face is the bot's role badge at print size**: the initials
  `ROLE_INITIALS` gives the board, the card and the emoji, set at one
  size for all six, and the role's name under them at one size, because
  a coach new to 2.0 reads PLAYMAKER sooner than PM. The badge's colour
  rule -- the colour on the edge, the letters in ink -- is the standard
  face's; the unique face fills it, which the emoji could not afford at
  22px and a 19 mm token can.
- **Printed duplex like the condition tokens**, through the same
  `with_cut_line` (lifted out of `token_face` for this, the condition
  sheets byte-identical before and after): the front sheet the unique
  sides with the grey cut line, the back sheet the standard sides at the
  mirrored position. One style, since a white or team-coloured face is
  already paper's. Each colour team is a block, a zone a row from the
  coach's own goal forward, with its name over it on the front alone --
  on the back it would print mirrored, and it is cut away anyway. The
  four teams take two thirds of a letter page; a table needs one team's
  block a coach.

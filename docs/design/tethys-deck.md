# The Tethys deck

The card deck the bot's `/tethys` commands deal (`cogs/tethysdeck.py`),
drawn as pictures: six suits of twelve, half Fortune and half Doom. The
package is `tethysdeck/`, the CLI `scripts/render_tethys_deck.py`, and
everything it writes goes under `tethysdeck/print/`, which is gitignored
like `d12ball/print/`. Every decision here is the author's, taken in one
sitting on 2026-10-08 over a run of sketches; the dates are that day
unless said otherwise.

## What the deck is

Money, Might, Fiends, Tools, States, Fools (the order of the "Thetys
Deck" tab of the World Building sheet, which also holds the table below),
each the numbers 1 to 10 and two rulers, Left and Right. **The fate
rule** has two inputs per suit: the odd cards' fate, and which parity
Left sits with; Right is the other one. Money, Might and States are
Fortune on the odds; Tools, Fiends and Fools on the evens; Left sits with
the odds for Money, Tools and Might and with the evens for the rest. So
every suit is six and six, 36 and 36 in all. `deck.fate_of` is the one
reading of it and `tests/test_tethys_deck.py` holds the table.

## Why the cards are drawn by code

The first round was generated art: engraved scenes, one per card, from
the local FLUX model. The author looked at ten and turned the deck round:
"instead of this make a series of simple icons for each suit", a Fortune
and a Doom variant each, "simple playing cards -- no art, just the
symbol, number and some styling". Code draws those, and from then on
every change was a line edit and a re-run rather than a re-roll. The
model was tried once more, to give the drawn symbols the coin's metal,
and failed both ways: seeded with the flat drawing it only repainted it
flat (schnell quantises the init strength to whole steps, so there is no
"a little"), and left to itself it drew a coin medal with gibberish
lettering. `relief.py` does the metal instead.

## The symbols

One drawing per suit, **whole for Fortune and broken, cracked, split or
sagging for Doom**, each in its own material colours (`icons.COLOURS`):

- **Money** is the studio's own gold coin, its Fortune face (the sunrise)
  and its Doom face (the smoking tower), straight from
  `d12ball/images/emoji/`, numeral and all.
- **Might** is a longsword: a blade tapering from a ricasso to the point
  with a fuller and two bevel planes, curved quillons with finials, a
  wire-wrapped red grip, a disc pommel with its peen block. Doom's blade
  is snapped, the point fallen aside. (The author asked twice for less
  cartoon and more real: curves instead of blocks, then the structure a
  real one has -- langets and rivets on the axe, a velvet cap and pearls
  on the crown, a banded gem on the sceptre.)
- **Fiends** is a horned mask -- wide brow, hollow cheeks, pointed chin,
  long swept horns -- crimson with closed lids and a brow gem for
  Fortune; ash black with hollow sockets, ember pupils and fangs for
  Doom. (The first draft was a round face with horns; "the demons need
  to be a bit less silly".)
- **Tools** is a claw hammer crossed with a combination wrench, steel on
  oak. Doom is rusted, the handle snapped, the jaw cracked. ("The tools
  can be different tools but should be useful.") The pieces carry the
  same realism: grain on the handles, a wedge in the eye, a ferrule on
  the pick, a D-handle and treads on the spade, a hardy and a pritchel
  hole on the anvil.
- **States** is the yin-yang the sheet already uses for the suit, teal
  and aqua. Doom is the same circle split by a gold lightning bolt,
  purple and ash.
- **Fools** is a jester's cap. Fortune's three points curve up, red,
  purple and green, with ring-marks beside the bells; Doom's side points
  hang below a sagging band and the middle one flops over the front.

**Nothing is cream and every card is white**: Fortune in teal ink, Doom
in black ink with gold, the paper white either way. The first frames
were cream for Fortune and black for Doom, and the author struck both.

## The relief

`relief.emboss` lights a flat drawing as the stuff it is made of, the
way the coin art is lit (the author, 2026-10-09: "look more real in line
with the coin art as if they are real metal. And stone and such"). Each
drawing is rendered three times: in its colours, as a mask (white parts,
black ink lines) and as a material map -- `MATERIAL_OF` says what each
colour key is: the blade and the anvil steel, the guard and the bells
gold, the hafts wood, the grip leather, the yin-yang stone, the fiend's
face lacquer, the cap cloth. The height is built from each part's
distance to its own edge (`chamfer`, an exact two-sweep transform, since
there is no scipy here), scaled to the part's width so a blade is a
ridge, a haft a half-round and a block a bevelled slab (`SHAPE`), with
the material's surface on top -- hammered dents on gold, fine grain on
steel, streaks along wood, mottling on stone -- and every part bowed a
little so broad faces shade. The ink lines are the grooves between
parts, coloured as their neighbours and darkened, not a cartoon outline.
The normals are lit from the top left: metals reflect an environment
(sky above, ground below, a bright horizon) with a tight glint; wood,
leather, cloth and stone are matte with a soft sheen; gems glow at the
rim; velvet lights at grazing angles. Doom is lit lower (`LIGHT`), its
gold tarnished and Tools' steel rusted matte. The coin is not lit; it is
already a picture. It is slow -- about six seconds a drawing at the
2048-pixel working size -- so `IconSet` renders each once.

An earlier relief took the drawing's alpha alone as the height, one
bevel and one dome for everything, and lit the painted colours as they
were; the big steel faces came out as pewter and the gold as yellow
paint. What made the difference was each part rising on its own and
each material being lit its own way.

## Denominations, as the coins

A card's value is **made of pieces, the way the coins make a sum**: 1,
3, 6 and 12, the fewest pieces, largest first (`deck.pieces`), spread
over the face like pips (`cards.SPREAD`). A 7 is a 6-piece and a
1-piece; a 10 is 6, 3 and 1. **The two rulers share the suit's power
equally**: Left and Right are each worth 12 (the author, 2026-10-09,
"left and right ... equally sharing the power"), so each is one whole
12-piece under its own fate -- the Fortune ruler's whole, the Doom
ruler's broken -- and Money's two are each one gold coin, on its sunrise
face and its ruined one. (For a day a ruler was 12 when Fortune and 11
when Doom, the Doom ruler 6, 3, 1 and 1; before that Left was 11 and
Right 12.)

- **Money's pieces are the real coins**, worth their dinkies by the
  Coins tab (1B = 1, 3B = 3, 1S = 6, 1G = 12, 3S = 18, 3G = 36), each on
  its Fortune or Doom face per the table. The 1 is one bronze; the 6 one
  silver; Left, the Fortune ruler, one gold.
- **Might's four denominations are four instruments of power**: the
  sword for 1, a bearded axe for 3, a sceptre for 6, a crown for 12
  (`deck.VARIANTS`, `icons.DRAWINGS`). "Weapons but also
  scepters/crowns."
- **Tools' four are four tools, the heavier the worthier**: the claw
  hammer for 1, a pickaxe for 3, a spade for 6, an anvil for 12. The
  anvil is London pattern seen a little from above and the left -- the
  horn, the step down to the table, the face with the hardy and pritchel
  holes, the waist, the flared base -- because a flat side view "looks
  weird" (the author). The suit's own mark stays the hammer crossed with
  the wrench. Doom's
  pickaxe has a cracked head and a snapped haft, the spade's blade is
  cracked and its shaft broken, the anvil split.
- **Fiends, States and Fools are their one symbol at four sizes**
  (`cards.PIECE_SIZE`): "for states, use the smaller and larger sizes."
  Fools had a ladder of its own for a day (2026-10-09): the cap for 1, a
  marotte for 3, a tambourine for 6, a theatre mask for 12, laughing for
  Fortune and weeping for Doom. The author asked for it unsure ("not sure
  about the fools ladders of object. but let's try") and reverted it on
  seeing it, so the suit is its cap; the drawings are in the branch's
  history, and a ladder for Fools would be three drawings and a row in
  `deck.VARIANTS` again.

## The back

White, the same double frame, a faint teal lattice, and a ring of the
twelve suit marks -- each suit's Fortune straight across from its Doom,
all pointing outward, so the silhouette is the same either way up --
round a gold dodecagon (twelve sides, twelve ranks) holding **the orange
Doom d12**, the darker of the studio's orange pair, drawn at build time
by `d12ball.dice.die_mark` (under a second, so nothing is committed).
Nothing on the back is lettered.

## Print sheets

Two PDFs, both at 300 dpi with a page of backs after every page of
fronts, so a duplex print puts a back behind each front:

- `print_sheet.pdf`: letter upright, nine cards a page in a 3 x 3 block
  of 7.5 x 10.5 in, crop marks in the margins. Eight sheets of stock.
- `avery_95328.pdf`: **Avery Presta 95328**, the pre-cut rounded-corner
  poker cards the D12 Ball cards print on, with the geometry
  `d12ball.cards` holds (`avery_95328_pages`, `duplex_order`). Twelve
  sheets. "The Avery template" means this one; a web search for an
  Avery poker-card template found only 95272 business-card stock with
  no published layout.

## Running it

```bash
python3 scripts/render_tethys_deck.py            # everything, into tethysdeck/print/
python3 scripts/render_tethys_deck.py --only sheets   # just the contact sheets
```

Look at `deck_sheet.png` (all 72), `closeup_sheet.png` (six, large),
`icon_sheet.png` and the two ladders after any change to a drawing;
nothing printed is tested. The suite checks the rule only.

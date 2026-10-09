# The Tethys deck

The card deck the bot's `/tethys` commands deal (`cogs/tethysdeck.py`),
drawn as pictures: six suits of twelve, half Fortune and half Doom. The
package is `tethysdeck/`, the CLI `scripts/render_tethys_deck.py`, and
everything it writes goes under `tethysdeck/print/`, which is gitignored
like `d12ball/print/`. Every decision here is the author's, taken in one
sitting on 2026-10-08 over a run of sketches; the dates are that day
unless said otherwise.

## What the deck is

Money, Tools, Might, Fiends, States, Fools (the author's order, which
the table in the "Thetys Deck" tab of the World Building sheet and the
bot's `cogs/tethysdeck_helpers.SUITS` both follow), each the numbers 1 to
10 and two rulers, Left and Right. **The fate
rule** has two inputs per suit: the odd cards' fate, and Left's fate;
the evens and Right are the other one. Money, Might and States are
Fortune on the odds, Tools, Fiends and Fools on the evens; Left is
Fortune in Money, Fiends and States and Doom in Tools, Might and Fools.
So every suit is six and six, 36 and 36 in all, and the rulers are split
three and three. `deck.fate_of` is the one
reading of it and `tests/test_tethys_deck.py` holds the table.

Left used to sit with the odds or the evens as a second input, which
left it Fortune in four suits. The author wanted the rulers "split
between fortune and doom and not always match left to odds"
(2026-10-09). With six suits you can balance any two of these three but
never all three: the odds Fortune in three suits, Left Fortune in three,
Left with the odds in three. If the first two hold, Left sits with the
odds in an even number of suits -- twice the number where both the odds
and Left are Fortune -- so four here (Money, Tools, States, Fools) and
with the evens in two (Might, Fiends). The author kept the first two.

## Why the cards are drawn by code, and why the pieces are pictures

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

Then the drawings, even lit as real materials, were "still abysmal"
beside the coin art (the author, 2026-10-09), and the coins look real
because they are pictures. So the pieces are pictures too -- see "The
pieces are pictures" below. The card itself is still drawn by code: the
frame, the ranks, the spread, the back, the print sheets; what the model
makes is one object on white, which is the one thing it does well. The
drawings stay in `icons.py` as the fallback behind any piece without a
picture, and as the record of what each symbol is.

## The pieces are pictures

`scripts/generate_tethys_pieces.py` holds one prompt per piece and mark
(`SUBJECTS`, with the seed each was made with) and runs them through
FLUX.1-schnell on the author's Mac (`mflux-generate`, installed by hand;
a minute or two a render). What was learned making them:

- **One object, upright, on pure white, photographed.** "Playing card",
  "illustration" and "icon" make the model draw card furniture; a planet's
  name gets lettered onto the picture; a brand gets lettered onto a
  handle unless the handle is "plain" and "unmarked". The suffix
  `STUDIO` says all of that once.
- **Medieval throughout**: "if the weapons are medieval style, so should
  the tools be." A smith's forging hammer, a miner's pick, an oak spade
  shod with iron under a T handle, the anvil; the Tools mark is the
  hammer crossed with tongs, not a wrench.
- **Doom is ruin, never breakage**: "ruined or rusty or nasty or
  deserted or neglected or foul -- all are good for doom", and "no need
  for broken". `RUIN` is that vocabulary; the first Doom prompts asked
  for a snapped blade and the model mostly ignored them anyway.
- **The author approved the style on a sheet of four** -- the sword and
  the smith's hammer, whole and ruined -- before the rest were made,
  rejecting the first ruined hammer ("weird") and a wisp near the ruined
  sword's tip; those two were re-rolled with new seeds and "no smoke, no
  dust" in the suffix.
- **Keying.** The background is the near-white connected to the
  picture's border (a flood fill with a tight tolerance), grown a little
  over the faint shadow -- only over very light, unsaturated pixels,
  because a looser pass once took a polished blade's highlight for
  shadow and ate the blade. The edge is feathered a pixel and its white
  fringe un-blended. An elongated piece is stood upright by its long
  axis (the model lays swords diagonally however it is asked), with the
  end `WIDE_END` names at the top: a hammer's head, a sword's point.
  Compact things -- crown, anvil, mask, disc, cap, the crossed marks --
  are left as rendered.
- **Committed, not built.** The keyed PNGs live in `tethysdeck/images/`,
  named as `icons.icon_name` names a piece (`might_sword_fortune`, and a
  suit's mark is `might_fortune`), and `relief.IconSet` takes a picture
  over the drawing wherever one exists. Fiends, States and Fools have a
  picture for their one mark, at four sizes on the cards, so no suit is
  a drawing beside the others. Made once by hand, like the rulebooks'
  cover dice; never per build. `tests/test_tethys_deck.py` checks only
  that every picture is named as a piece the deck has.

## The symbols

These are the drawings `icons.py` makes. Since 2026-10-09 each has a
picture in front of it (above); the drawings are the fallback and the
record.

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

**Nothing is cream and every card is white**: Fortune in violet ink,
Doom in coal ink with orange, the paper white either way (`cards.PALETTE`,
and the back follows it). The first frames were cream for Fortune and
black for Doom, and the author struck both; then teal for Fortune and
black with gold for Doom, until "instead of the black and gold for doom,
make it coal and orange. instead of teal for fortune, make it violet"
(2026-10-09). The orange is the Doom die's; the violet is near the
studio's purple pair.

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
2048-pixel working size -- so `IconSet` renders each once, and only for
a piece that has no picture in `tethysdeck/images/`.

An earlier relief took the drawing's alpha alone as the height, one
bevel and one dome for everything, and lit the painted colours as they
were; the big steel faces came out as pewter and the gold as yellow
paint. What made the difference was each part rising on its own and
each material being lit its own way.

## Denominations, as the coins

A card's value is **made of pieces, the way the coins make a sum**: 1,
3, 6 and 12, the fewest pieces, largest first (`deck.pieces`), spread
over the face like pips (`cards.SLOTS`: a centre and the room each slot
has; a piece is cropped to what it shows and fills its value's size
across or 1.6 times that down, whichever binds, so a sword stands tall
where a crown sits wide -- the pictures made square slots shrink every
tall thing to a sliver). A 7 is a 6-piece and a
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

White, the same double frame, a faint violet lattice, and a ring of the
twelve suit marks -- each suit's Fortune straight across from its Doom,
all pointing outward, so the silhouette is the same either way up --
round an orange dodecagon (twelve sides, twelve ranks) holding **the orange
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
python3 scripts/generate_tethys_pieces.py generate might_axe_doom   # re-roll one piece (needs mflux)
python3 scripts/generate_tethys_pieces.py key might_axe_doom        # key it into tethysdeck/images/
python3 scripts/generate_tethys_pieces.py sheet                     # every picture on one sheet
```

A re-rolled piece is a new seed in `SEEDS` and the raw render set aside
first (`tethysdeck/print/pieces/raw/`, gitignored), since `generate`
skips what exists.

Look at `deck_sheet.png` (all 72), `closeup_sheet.png` (six, large),
`icon_sheet.png` and the two ladders after any change to a drawing;
nothing printed is tested. The suite checks the rule only.

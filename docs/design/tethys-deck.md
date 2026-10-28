# The Tethys deck

The card deck the bot's `/tethys` commands deal (`cogs/tethysdeck.py`),
drawn as pictures: six suits of twelve, values 2 to 24, half Fortune and
half Doom. The
package is `tethysdeck/`, the CLI `scripts/render_tethys_deck.py`, and
everything it writes goes under `tethysdeck/print/`, which is gitignored
like `d12ball/print/`. Every decision here is the author's, taken in one
sitting on 2026-10-08 over a run of sketches; the dates are that day
unless said otherwise.

## What the deck is

**Structure E** of the author's "2d12 Distribution Card Deck" document
(2026-10-27), which replaced the deck of 1 to 10, Left and Right on
2026-10-28 (the author: "Replace the current deck with the new Tethys deck
in both the bot and the print"). 72 cards whose values run 2 to 24 as
often as two d12 roll each, give or take -- 13 eight times, a full third
above its shoulders at 12 and 14, the tails one card each -- in six suits
of twelve, each worth 156. `tethysdeck/deck.py` is it. The suits are
Money, Tools, Might, Fiends, States, Fools (the author's order, which the
bot's `cogs/tethysdeck_helpers.SUITS` follows); the document numbers its
suits 1 to 6, and they are dealt to the suits in that order, Money first.

- **A card is its suit, value and fate** (`deck.Card`). A suit can hold
  one value two or three times, so (suit, value) does not name a card;
  and two cards of one suit, value and fate are the same card twice --
  one face, one name. Four such pairs are in the deck, so 68 faces make
  the 72.
- **The fates are six and six a suit, each half worth 78** (the author's
  choice, 2026-10-27, over keeping odd and even -- which in this deck
  puts eight odd cards in one suit and four in another -- and over high
  against low; the split below kept, 2026-10-28). Each suit has 16 to 32
  such splits, so `deck.py` names three more rules that pick one: the
  deck is its own mirror, Fortune at a value as many as Doom at the value
  across 13 (`26 - v`), so an all-Fortune hand is as likely as the same
  set all Doom; a suit's repeated values split between the fates where
  they can be, so as few cards as possible are the same card twice; and
  each half spread like the other. The search ran once and is not kept;
  the test holds the tables to the document and the first two rules.
  `deck.FORTUNE` and `deck.DOOM` are the one reading of a card's fate.

**The deck it replaced** was each suit's numbers 1 to 10 and two rulers,
Left and Right, each worth 12; its fates were the odd cards' fate and
Left's fate per suit, the evens and Right the other, so every suit was six
and six and the rulers three and three. Its sets ranked a Left and a Right
as a pair and either after 10 in a straight. It is in the history up to
PR #680; the World Building sheet's "Thetys Deck" tab still tables its
fates. A channel that shuffled it before the replacement plays on with
its cards named in words (see "On Discord").

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
frame, the values, the spread, the back, the print sheets; what the model
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

**Nothing is cream and every card is white**: Fortune in violet ink with green,
Doom in coal ink with orange, the paper white either way (`cards.PALETTE`,
and the back follows it). The first frames were cream for Fortune and
black for Doom, and the author struck both; then teal for Fortune and
black with gold for Doom, until "instead of the black and gold for doom,
make it coal and orange. instead of teal for fortune, make it violet"
(2026-10-09). The orange is the Doom die's; the violet is near the
studio's purple pair. Fortune's second ink, the grey that names the suit at the
top and the fate at the foot and draws the inner frame, was a light
grey (`#A6A4AD`) until the author found the suit's name "barely visible
when printed" (2026-10-11); a slate grey (`#5E5A68`) was still too
light -- "make it even darker", the words and the frame both -- and
after a charcoal grey (`#33303A`) and a run of greens set side by side,
the author chose a deep green (`#1E6B34`): dark enough for paper, and
a colour of its own beside the violet rather than a grey. Doom's orange was
never faint and stays. Both words grew with it, on every card: the
suit's name from 40 to 56, set a little higher to clear the pieces
under it, and the fate from 24 to 38, so they read at
arm's length as well as up close (the author, 2026-10-11).

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
1-piece; a 10 is 6, 3 and 1; a 24 two 12s. Values up to 24 make four
pieces on twelve faces and five on one, Tools' 23, where the deck of 1 to
10 never needed more than three: as three are, the largest across the top
and the rest in a row under it, clear of the corners and of the value. A
2x2 was tried first; its top left crowded the corner mark and every piece
came out one size, which hid the denominations. (The rulers of the deck
this replaced were each one whole 12-piece, Money's one gold coin -- "left
and right ... equally sharing the power", the author, 2026-10-09.)

- **Money's pieces are the real coins**, worth their dinkies by the
  Coins tab (1B = 1, 3B = 3, 1S = 6, 1G = 12, 3S = 18, 3G = 36), each on
  its Fortune or Doom face per the table, the fewest coins: a 5 is a
  three-bronze and two bronzes, a 13 a gold and a bronze, the 24 a
  three-silver and a silver. No Money card is more than three coins.
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
round an orange dodecagon (twelve sides, as the d12 has) holding **the orange
Doom d12**, the darker of the studio's orange pair, drawn at build time
by `d12ball.dice.die_mark` (under a second, so nothing is committed).
Nothing on the back is lettered.

## Tethys poker: the six-card sets

**Tethys poker** is the name (the author, 2026-10-09): a hand of six read
the way poker reads five, and what each set's chance is. `sets.py` is the
rule and the count; `sets_aid.py` draws it twice, the player aid and a
chart. The sets were made for the deck of 1 to 10, Left and Right, and
recounted for this one (the author, 2026-10-27: "recount for E").

- **All six cards count.** A "best five of six" reading was looked at and
  set aside.
- **A pair is two of one value**, a straight six values in a row that
  never wraps from 24 to 2, a flush six of one suit. (The deck it
  replaced had its rulers pair only with each other and follow 10 in a
  straight.)
- **The sets**, rarest first, which is the ranking -- the census's: six
  of a kind, five of a kind, 6-card flush, two triples, 6-card straight,
  three pairs, four of a kind, three of a kind, two pairs, one pair -- and
  no set last, though it is the commonest hand (44% mixed, against one
  pair's 41%). A hand is the first it makes. A three or a four with a pair
  is the three or the four, since every such hand is already that set and
  the pair adds nothing rarer. A flush can hold a pair or three of a kind
  and is a flush, being rarer than both. No suit holds six values in a
  row, so there is no straight flush and the set is not in the table.
- **Mixed and uniform.** Uniform is all six Fortune or all six Doom. The
  deck is its own mirror (`deck.py`), so the two are always equally likely
  and are counted and shown together; the aid says each alone is half. No
  five or six of a kind is uniform, since no value has five of one fate.
- **The count is exact**, not sampled: by value multiset with the Fortune
  count carried as a polynomial, and the 5,544 one-suit hands walked one
  by one, because a flush is the only set that reads suits. It was checked
  against a walk of all 156,238,908 hands one by one, all Fortune and all
  Doom counted apart -- equal in every set, as the mirror says; the test
  pins that table.
- **The aid is a player aid, not a statistics page**: each set with a
  one-line rule, a mixed example hand of the deck's own card faces, and
  its chance as a percentage, mixed and uniform. The chart is the
  statistics view: the same chances as dot (mixed) and diamond (uniform)
  on a log scale, because they run from half of all hands to a few in a
  hundred million.

## On Discord

The `/tethyscards` commands deal the deck by name -- `"13 of $ Money
(Doom)"`, `cogs/tethysdeck_helpers.build_deck` -- and since 2026-10-11 show the
cards as the deck's own faces (the author: "add the card pictures to
existing tethys deck commands"). A draw, a hand (yours, or another's
by `/tethyscards hand`) and the discard each answer with a line of
words and a picture of the cards under it, left to right in the
hand's order; an empty hand or discard is text alone.

- **The words name a card only where no picture shows it** (the
  author, the same day, of a draw listed twice above its picture: "No
  need to list the cards, just showing them is enough"). Over a
  picture the line is a caption -- "Drew 6 cards." and "HolyTispoon's
  hand (6 cards):", "Discard pile (6 cards):" -- and the picture is
  the list; the drawn cards are the last of the hand, so they are in
  it. The one list that stays is "Discarded: ...": the picture under
  it is the hand those cards left, not them. `TethysDeck.pictured(state)`
  is the one reading of whether a reply carries a picture, and the
  two text builders in `cogs/tethysdeck_helpers.py` take `listed`
  from it, so the words and the picture cannot disagree about which
  of them names the cards.

- **The faces are drawn once.** `tethysdeck/strips.Faces` draws all 68
  through `cards.deck_cards` and keeps them at 180 x 252 -- the printed
  card at 0.24, where the value and the pieces still read -- and the cog
  builds it in `cog_load` through `asyncio.to_thread` (about two
  seconds on the Mac). A picture after that is only pasting: a hand of
  seven in about 20 ms, the whole deck in about a quarter of a second
  and a megabyte. A row is nine cards, so a usual hand is one row and
  the whole deck eight; the cards sit on transparency, their white
  paper reading on either Discord theme.
- **A name carries its fate**: `"13 of $ Money (Doom)"`, because a
  suit can hold one value under both. A card the deck holds twice is the
  same name twice, so the discard menu's values are places in the hand
  rather than names (a menu's values must differ), and `remove_cards`
  takes one card per choice.
- **The saved names are not changed.** A channel's deck in progress is
  saved as those strings in `data/tethysdeck_decks.json`, and
  `tethysdeck_helpers.parse_card` is the one way from a name to the
  deck's `Card`; a test reads every name `build_deck` makes.
- **A channel that shuffled before the replacement plays on.** Its cards
  are the deck of 1 to 10, Left and Right, named with no fate (`"7 of ⚔
  Might"`), and `parse_card` reads such a name as None; a deck is
  shuffled whole, so any one card says which deck a channel holds
  (`shuffled_before_replacement`). Its draws, hands and discard are
  named in words, as with no faces, and it gets this deck at its next
  `/tethyscards new_deck`. Nothing is migrated and nothing new is saved,
  so `/tethyscards new_deck` is the command it always was.
- **If the faces cannot be drawn**, the cog logs it at ERROR (it
  reaches #logs: somebody must look) and every command answers in
  words, as it did before, until the bot restarts.

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

**The card's corner is the die cut's** (the author, 2026-10-10):
`cards.RADIUS` is 112 px, the 95328 cut's 0.375 in at 300 dpi, and each
frame inside it -- the two lines on a face and the back, and the back's
lattice -- is drawn at `RADIUS - inset`, concentric with the cut, so a
line keeps the same inset round the corner as along the sides. The
corner was 36 px with the frames at 24 and 16, and printed on the stock
the double frame ran out past the cut at every corner. The grid sheet's
crop marks are square, so its cards are trimmed at whatever corner the
cutter gives; the drawn corner is the Avery's because that stock's cut is
fixed. The D12 Ball cards keep their tighter `CORNER` and lose a sliver to
the same cut ([cards.md](cards.md)).

## Running it

```bash
python3 scripts/render_tethys_deck.py            # everything, into tethysdeck/print/
python3 scripts/render_tethys_deck.py --only sheets   # just the contact sheets
python3 scripts/render_tethys_deck.py --only sets     # the player aid and the chart
python3 scripts/generate_tethys_pieces.py generate might_axe_doom   # re-roll one piece (needs mflux)
python3 scripts/generate_tethys_pieces.py key might_axe_doom        # key it into tethysdeck/images/
python3 scripts/generate_tethys_pieces.py sheet                     # every picture on one sheet
```

A re-rolled piece is a new seed in `SEEDS` and the raw render set aside
first (`tethysdeck/print/pieces/raw/`, gitignored), since `generate`
skips what exists.

Look at `deck_sheet.png` (all 72), `closeup_sheet.png` (six, large),
`icon_sheet.png` and the two ladders after any change to a drawing;
and `sets_aid.png` and `sets_chart.png` after any change to the sets;
nothing printed is tested. The suite checks the rule only: the fates,
the pieces, and the sets' census.

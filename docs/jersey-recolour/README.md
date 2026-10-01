# Jersey recolour: the pilot, parked (2026-10-01)

The worksheet the colour-team portraits are being made from. **Nothing in it
is a rule**, and nothing in the game reads this folder yet.

## The job

Each portrait in `d12ball/images/player_images/<Name>.png` wears its
*species'* original kit. A colour team is three players of its own species
and two of each other species, so six players per team wear the wrong kit:
24 portraits to recolour.

| Team | Kit | The six to recolour, by the kit they wear now |
| --- | --- | --- |
| Orange | the Fire Demons' deep red (Blazebulk, Sizzifizik, Flickerwing) | Goopkeeper, Acidel (ooze); Spectra, Noxar (tele); Voltus, Synapse (cyborg) |
| Teal | teal | Inferno, Kindlefinger (fire); Ozul, Zorch (ooze); Zenith, Vorix (tele) |
| Purple | purple shirt, purple shorts | Hellguard, Emberdash (fire); Glompex, Gurgoth (ooze); Quantor, Tachyon (cyborg) |
| Slime | **black** | Scorchit, Brightburn (fire); Flux, Gearclaw (cyborg); Umbrik, Hexis (tele) |

The roster is as of the Viscor/Gurgoth swap (PR #414).

## The author's decisions

- **Two portraits per player.** The original stays, because it is right for
  the species team. The colour-team version is added and is the one used
  mostly. The lookup is not built: the plan is `<Name>_<team>.png`, falling
  back to `<Name>.png`, keyed on `match.team_for_player`, in
  `load_player_portrait` (`d12ball/render.py`) and `webapp/pictures.py`.
- **Recolour all clothing**: shirts, shorts, sleeves. **Never** masks or glasses.
- **Armour keeps its colour**: Quantor's thigh plate, Gearclaw's shoulder
  plate and elbow joint.
- **Shorts are decided player by player, with no team rule.** Ozul's are
  teal; Kindlefinger keeps his dark shorts.
- **Zenith's cut-off foot is rebuilt** from his other foot, turned and toned.
  That makes his picture taller, 323 → 364 px.

## Where the pilot stands

Seven portraits: two easy (Quantor, Gearclaw: cyborgs, whose teal is easy to
pick out), one middling (Ozul), and the hardest (Hellguard, Kindlefinger:
red on red; Zenith, Umbrik: purple on purple).

- **v1** was the first pass. The author's round-1 comments:
  - Quantor: the upper-leg area was ambiguous.
  - Gearclaw: the shirt stopped abruptly at the shoulders, and a teal patch was left inside it.
  - Ozul: the shorts were still black, and so were areas on his left arm.
  - Hellguard: the shorts bled onto the skin, and the sleeves under the armour and the neck were still red.
  - Kindlefinger: orange patches on the shorts, and a few on the shirt.
  - Zenith: teal bled onto the right leg; "build the bottom foot fully".
  - Umbrik: a little purple near the end of the shirt and on the shoulder.
- **v2** addressed each of those comments, and every fix is described in
  `v2/` (one script per player). What v2 left: dark-red flecks on
  Kindlefinger's shirt, and a hint of purple at Umbrik's right sleeve end.
- **The author's verdict on v2: it is not always better than v1.** The
  project needs to go player by player, fixing every problem area, taking
  from v1 or v2 whichever is better for each area. Pick it up there.

`v1_vs_v2.png` puts before, v1, v2 and a native teammate side by side for
each player. Redraw it with `python3 docs/jersey-recolour/kit/sheet.py`.

One difference between the versions is in the colour, not the masks.
v1's Ozul and Kindlefinger were made with the first teal model, which
picked up the cyan lights on the native players and reads slightly mint.
v2 uses teal sampled from the largest shirt area on Bulwark, Strider and
Pulsar. Measured on Zenith's shirt, that teal is Lab 31.5/−20.1/−1.8
against Bulwark's 33.1/−21.1/−1.6.

## What is in this folder

```
kit/kit.py          the recolour functions (below)
kit/refs.pkl        the kit colour models: orange, teal, purple, black
kit/grid.py         a portrait with a coordinate grid, for drawing polygons
kit/zoom.py         a gridded before/after crop, in the portrait's own coordinates
kit/sheet.py        draws v1_vs_v2.png
v1/run.sh           rebuilds v1/out/ from v1's scripts
v1/refs_first_teal.pkl   the models before teal was resampled (used by v1's first five)
v2/run.sh           rebuilds v2/out/ from v2's scripts
v1/out/, v2/out/    the recoloured portraits (Zenith's v2 with the foot is Zenith_teal_foot.png)
```

Run either `run.sh` from the repository root. Both rebuild their `out/`
byte for byte; that was checked when this folder was saved. They need
numpy, Pillow, scikit-image and opencv-python-headless, none of which
`requirements.txt` carries.

The v1 files were recovered by rerunning the session's own commands, after
v2 had overwritten them, and they match the v1 review sheet pixel for pixel.

## How the recolour works

All of it is in Lab colour space (scikit-image).

- **Lightness by rank.** Each garment pixel's lightness is replaced by the
  lightness at the same rank in the target kit's distribution, so the
  shading carries over and the overall brightness becomes the target kit's.
- **Colour from the target's curve.** a and b come from the target kit's
  median a and b at that lightness, sampled from native players' shirts
  (`refs.pkl`).
- **Per-pixel weights** decide how much each pixel changes:
  - `hue_weight` for closeness to the source kit's hue;
  - darkness, for black source kits;
  - `lowchroma`, for near-grey fabric.
- **Hand-drawn polygons** per garment, feathered at the edge, with exclusion
  polygons for eyes, mouths, faces, armour and lenses. Rectangles cut
  straight lines into a shirt; use a polygon or a circle that follows the
  part.
- **Numbers and crests** are protected with `number_mask`.
- **Small flecks** left in the old colour are filled from their surroundings
  with `cv2.inpaint` at a small radius. Restrict it to small blobs, or it
  smears.

Difficulty by the kit a player wears now, easiest first:
- Cyborgs: a teal colour pick finds almost exactly the shirt.
- Oozes: easy to mask, but black to a colour has no shading to carry over.
- Telekinetics: purple on purple.
- Fire Demons: red on red. Each needs a hand polygon and a narrow hue band.

## Next, when this is picked up

1. Go player by player through the seven, area by area, keeping the better
   of v1 and v2 and fixing what neither got right.
2. Turn the kit into a tool under `scripts/`, with each player's polygons
   saved as data rather than in a script each.
3. Build the two-portrait lookup.
4. Do the other 17 in batches by the kit they wear now (cyborgs, oozes,
   telekinetics, fire demons), reviewed on team sheets.

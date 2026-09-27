# Reverting the d12 portraits (PR #370)

How to put any of the 18 portraits changed by PR #370 back to the painting
it was before: one at a time, several, or all of them. Written 2026-09-27.

## The two reference points

| Name | Commit | What it is |
| --- | --- | --- |
| **before** | `d6a320e` | `main` when the branch was cut: every portrait as it was painted. |
| **after** | `7cc12a8` | The PR's first commit: the 18 new portraits, the `docs/design/cards.md` note, the `box_art.py` comment. A second commit regenerated rulebook figure 12 and added this guide. |

`d6a320e` is on `main`, so it survives however #370 is merged. The PR's own
commits survive a merge commit (this repo's usual way, "Merge pull request
#...") but not a squash or rebase merge. That is why every command below
restores **from `d6a320e`**, and never "undoes" a PR commit.

Each portrait is its own file, and nothing in one file depends on another. The
dice were baked into each image, including Umbrik's, whose die surface was
copied from Noxar's ball. So reverting one portrait never changes another.

---

## Reverting one portrait (or several)

Swap `<Name>` for the player: case-sensitive, and matching the file name.

**1. Start from an up-to-date `main` on a fresh branch** (CLAUDE.md: every task
starts this way):

```bash
git checkout main && git pull --ff-only
git checkout -b revert-<name>-portrait
```

If #370 is **not merged yet** and you only want it to go in without that
portrait, do this on the PR branch instead:

```bash
git checkout claude/player-art-d12ball-a3y7oi && git pull --ff-only
```

**2. Restore the file from `before`:**

```bash
git checkout d6a320e -- d12ball/images/player_images/<Name>.png
```

For several at once, list them all:

```bash
git checkout d6a320e -- d12ball/images/player_images/Umbrik.png d12ball/images/player_images/Acidel.png
```

(`git restore --source=d6a320e -- <path>` does the same.)

**3. Check it's the original, byte for byte.** The first 12 characters must
match the portrait's **before** hash in its section below:

```bash
git hash-object d12ball/images/player_images/<Name>.png | cut -c1-12
```

**4. Look at it.** The suite can't see a picture. Render the portrait's team
sheet, and check the file on a dark background, as the matchup image draws it:

```bash
python3 scripts/render_player_cards.py --out /tmp/cards --team <team> --sheets-only --fronts-only
```

Teams: `oozes`, `telekinetics`, `fire_demons`. The `--team` flag also takes
the colour teams, and each portrait also appears in its colour team's sheet.

**5. Run the portrait check, then the suite.** The originals already pass the
cut-out check, since `main` passed it before #370:

```bash
python3 -m unittest tests.test_d12ball_portrait_recut
python3 -m unittest discover -s tests
```

**6. Update the note in `docs/design/cards.md`.** Its bullet **"The ball in a
portrait is a d12, with real numbers on it"** lists what changed. Add a
sentence naming the reverted portrait, e.g. "**Umbrik still shows its round
ball**". If you
revert Kindlefinger, change the sentence about its glyphs to say they're back.
If you revert all 18, remove the bullet and its tint sub-bullet completely.

**7. Regenerate anything built from the portrait that you have committed or
printed.** Each section below lists what draws that player. The general list:

| Output | How to regenerate | Committed? |
| --- | --- | --- |
| Rulebook figure 12, `docs/rulebooks/figures/fig-12-coaching-choice.png` | `python3 scripts/build_rulebooks.py --figures` | **Yes** |
| Box cover, night cover, banners, playtest card back (the cover's cast) | `python3 scripts/render_box_art.py` | No, built on demand |
| Sale sheet (its card fan) | `python3 scripts/render_box_art.py` | No |
| Landing page player cards, and the print-and-play kit's player-card zips | `python3 scripts/build_landing.py` (into `landing/dist/`, gitignored), then redeploy | No |
| Player card print sheets | `python3 scripts/render_player_cards.py ...` | No |

> **Figure 12 draws six of these portraits** -- Dravox, Glompex, Emberdash,
> Viscor, Quillon and Zytheris -- and #370 regenerated it with their dice.
> Reverting any of the six means running `--figures` again and committing the
> new `fig-12-coaching-choice.png` in the same PR. `--figures` rewrites every
> figure, but only one that draws a changed portrait should come out
> different: if `git status` shows any other figure changed, something else
> has moved, so leave those files out and look into it.

**8. Commit, push, open a PR.** One commit is enough. Name the portrait and
say why, e.g. `Portraits: Umbrik back to its painted ball`.

**9. After it merges, restart whatever draws portraits.** `render.py` caches
each portrait for the life of the process (`_PLAYER_PORTRAIT_CACHE`), so a
running bot or web app keeps drawing the old file until restarted:

- **The live bot** is the Windows checkout at `K:\...\fool-bot`: pull there and
  restart (`scripts/update_main_bot.ps1`). A fix on the Mac hasn't reached it
  until then.
- **The web app** (`python3 -m webapp`, or `scripts/run_web_app.ps1`): restart
  it.

---

## Reverting all 18

- **Before #370 merges:** close the PR without merging and delete the branch
  `claude/player-art-d12ball-a3y7oi`. Nothing reached `main`.
- **After a normal merge commit:** revert the merge. This undoes everything
  #370 did together: the portraits, figure 12, the `cards.md` bullet, the
  `box_art.py` comment, and this guide with its row in `CLAUDE.md`:

  ```bash
  git checkout main && git pull --ff-only && git checkout -b revert-d12-portraits
  git log --oneline --merges --grep "#370" -1        # the merge commit's hash
  git revert -m 1 <that hash>
  ```

- **After a squash merge:** `git revert <the squash commit>` (no `-m`).
- **Or file by file,** which works however it was merged:

  ```bash
  git checkout d6a320e -- d12ball/images/player_images/{Acidel,Dravox,Emberdash,Glompex,Gurgoth,Hexis,Kindlefinger,Noxar,Ozul,Quillon,Slitheron,Spectra,Spritz,Umbrik,Viscor,Vorix,Zorch,Zytheris}.png
  ```

  Then regenerate figure 12 (step 7), remove the `cards.md` bullet (step 6),
  delete this guide and its row in `CLAUDE.md`, and restore the `box_art.py`
  docstring with `git checkout d6a320e -- d12ball/box_art.py`, but **only if**
  nothing else has changed that file since. Otherwise, edit the `DieMaterial`
  docstring back by hand to "the balls in the players' own portraits are dark,
  dimpled, organic things".

Then follow steps 4, 5, 7, 8 and 9 above. With all 18 reverted, the
regenerations to consider are figure 12 (always), the box art, the sale sheet
and the landing page.

---

## Each portrait

Hashes are the first 12 characters of the file's git blob id (step 3). "Faces
shown" lists the large numbers on the die; each die also has a small
foreshortened one on its top face and sometimes a sliver at one side.

### Ooze

#### Acidel
- **Before** `6b64c6581283` (197,086 bytes) → **after** `39c9dda29bfc` (197,925 bytes)
- **Changed:** round ball → ooze d12 (dark with lime seams, wearing the ball's
  own painted surface), faces 12, 9., 10. The slime toes curling over the ball
  were put back over the die. The ball was refitted once (centre 39,258,
  radius 42) to clear a leftover of its rim above the die, and the gap where
  the ball bulged past the die was filled from the slime around it.
- **Also drawn in:** Discord and the web app (cards, matchups, coaching image).
  No committed or printed extra.

#### Glompex
- **Before** `04f67793e1ae` (192,596) → **after** `567280a5262a` (193,862)
- **Changed:** ooze d12, faces 11, 3, 7. The slime dripping onto the ball's top
  was put back over the die, and the gap on the lower right was filled with
  slime.
- **Also drawn in:** **rulebook figure 12** (regenerate it, step 7), Discord,
  the web app.

#### Gurgoth
- **Before** `6e1a60d21b1b` (268,486) → **after** `9640f6985cab` (269,655)
- **Changed:** ooze d12, faces 5, 11, 3. Gaps filled from the surrounding
  slime.
- **Also drawn in:** **the sale sheet's card fan** (`render_box_art.py`),
  Discord, the web app.

#### Ozul
- **Before** `9d6d43f3b549` (241,727) → **after** `5aa8245c8a44` (242,273)
- **Changed:** ooze d12, faces 3, 11, 5. The gap on the right was filled with
  slime.
- **Also drawn in:** Discord, the web app.

#### Slitheron
- **Before** `b44f5ce0c5be` (179,601) → **after** `1c30501139df` (180,131)
- **Changed:** ooze d12, faces 4, 12, 11.
- **Also drawn in:** **the box cover's cast**, and so the night cover, the
  banners and the playtest card's back, which carries the cover. Regenerate
  with `render_box_art.py`. Also Discord and the web app.

#### Spritz
- **Before** `e534f97e1771` (220,865) → **after** `4769168d2ca6` (223,269)
- **Changed:** ooze d12, faces 2, 4, 8. The ball was refitted once (centre
  44,286, radius 42) to clear a sliver of rim on its right. Gaps filled with
  slime.
- **Also drawn in:** Discord, the web app.

#### Viscor
- **Before** `c948a15975ab` (266,874) → **after** `34dac6508c80` (269,677)
- **Changed:** ooze d12, faces 9., 12, 10. The gap on the right was filled
  with slime.
- **Also drawn in:** **rulebook figure 12**, Discord, the web app.

#### Zorch
- **Before** `b7dae2cf2125` (222,671) → **after** `5810e046f60f` (224,636)
- **Changed:** ooze d12, faces 5, 9., 6.
- **Also drawn in:** Discord, the web app.

### Telekinetic

#### Dravox
- **Before** `b134d2300077` (175,682) → **after** `74d2f83b67c3` (179,706)
- **Changed:** telekinetic d12 (silver with violet dimples and seams, a faint
  violet glow), faces 7, 9., 11. The ball was refitted (centre 53,244,
  radius 34).
- **Also drawn in:** **rulebook figure 12**; **the landing page's telekinetic
  player card** (`build_landing.py`, then redeploy); Discord; the web app.

#### Hexis
- **Before** `479db36c95a3` (163,640) → **after** `a4b32871a100` (168,413)
- **Changed:** telekinetic d12, faces 10, 4, 5.
- **Also drawn in:** Discord, the web app.

#### Noxar
- **Before** `41ca5c6e5383` (178,962) → **after** `0965f41a8cbd` (182,651)
- **Changed:** telekinetic d12, faces 8, 7, 11.
- **Note:** Umbrik's die wears a copy of Noxar's ball surface. It's baked into
  Umbrik's file, so reverting Noxar leaves Umbrik unchanged.
- **Also drawn in:** Discord, the web app.

#### Quillon
- **Before** `66a1ee80954d` (166,944) → **after** `2fd257890b72` (171,525)
- **Changed:** telekinetic d12, faces 6., 11, 3. The black specks where the
  original ball had holes in its cut-out were filled with the ball's own colour
  on the die.
- **Also drawn in:** **rulebook figure 12**, Discord, the web app.

#### Spectra
- **Before** `4824a333a72c` (157,060) → **after** `b2e0ba7945a6` (161,884)
- **Changed:** telekinetic d12, faces 1, 7, 4.
- **Also drawn in:** Discord, the web app.

#### Umbrik
- **Before** `46787aee964b` (293,175) → **after** `3a274b8434a0` (298,777)
- **Changed:** telekinetic d12, faces 7, 1; a third face is under the hand.
  The die was made slightly smaller (radius 30), and because the hand covered
  the painted ball, its surface was copied from Noxar's ball. The hand
  reaching over the ball was put back over the die.
- **Also drawn in:** Discord, the web app (Umbrik is a goalkeeper).

#### Vorix
- **Before** `5d87aa9e3177` (179,863) → **after** `081bee9c092c` (186,206)
- **Changed:** telekinetic d12, faces 11, 7, 12.
- **Also drawn in:** **the box cover's cast** (and so the night cover, the
  banners and the playtest card's back), **the sale sheet's card fan**, Discord
  and the web app. Regenerate with `render_box_art.py`.

#### Zytheris
- **Before** `711fdfe2024f` (151,418) → **after** `3337619341f7` (157,567)
- **Changed:** telekinetic d12, faces 10, 9., 5.
- **Also drawn in:** **rulebook figure 12**, Discord, the web app.

### Fire demon

#### Emberdash
- **Before** `e9c15fd3a43c` (131,784) → **after** `b5dc357a547a` (132,112)
- **Changed:** fire d12 (scorched red-brown, gold numbers, an orange glow),
  faces 9., 7, 12. The ball was refitted twice (last: centre 35,216, radius
  29), and the ring of flames around the ball was put back around and over the
  die's edge.
- **Also drawn in:** **rulebook figure 12**, Discord, the web app.

#### Kindlefinger
- **Before** `cb79a99ab4b8` (316,766) → **after** `e3744241c68c` (310,417)
- **Changed:** *not* a replaced ball. The painted d12 was kept; its seven
  glyphs were painted out, and six faces were numbered in gold with a dark
  outline: **12** on the front, **4, 8, 10, 2, 6.** around it. The seventh
  glyph, half under the flames at the bottom, was painted out and left blank.
- **Reverting it** brings the glyphs back, and the rest of the painting is
  unchanged. It is the only one of the 18 whose original already showed a d12,
  so after a revert it's a d12 without numbers rather than a round ball. Word
  step 6's note that way.
- **Also drawn in:** Discord, the web app.

---

## Not part of #370

- **Synapse**'s d12 was drafted during #370 and not taken; its ball became
  a d12 afterwards, in its own PR: **before** `b26371638600` (207,084) →
  **after** `1164b4efd982` (206,505). Cyborg d12 (the ball's own bronze panels
  and teal lens, dark teal seams), faces 12, 8, 4 with 7 and 3 on the sides.
  The ball was taken out inside its painted circle (centre 42.5,230, radius
  42). The arm's cuff ends on the ball's rim, so it was kept, and the die was
  turned 23.6 degrees so one flat side of its outline lies along the rim's
  tangent where the cuff ends (centre 46.2,228.3, reaching 43 px); the cuff
  was put back over the die and the kick's spark beside it. The painted
  ball's shadow and soft edge under and beside the die were cleared, and so
  were the spark's specks that had lain over the ball. Revert it as in steps 2-6: restore from `d6a320e` and
  change the "Synapse came later" sentence in the `cards.md` note. No
  committed figure, the box cover or the sale sheet draws Synapse; it appears
  on its player card, in Discord, in the web app, and on the landing page's
  Cyborgs card (rebuild and redeploy).
- The **17 portraits with no ball** (Blazebulk, Brightburn, Bulwark,
  Flickerwing, Flux, Gearclaw, Goopkeeper, Hellguard, Inferno, Pulsar, Quantor,
  Scorchit, Sizzifizik, Strider, Tachyon, Voltus, Zenith) were never changed.

## Redoing one later

The scripts that made the drafts were one-off work and are not in the
repository: each portrait's ball was located and masked by hand. To redo a
reverted portrait, draft it again the way #370's description explains, rather
than expecting a tool in `scripts/`.

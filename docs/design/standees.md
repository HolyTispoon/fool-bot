# The standees

Design notes for fool-bot; the map is [CLAUDE.md](../../CLAUDE.md), the rules are [living-rules.md](../living-rules.md) and [rules-2.1.md](../rules-2.1.md).

`d12ball/standees.py` draws every player of the four colour teams as a
standee for the print-and-play kit, a team a letter page; its CLI is
`scripts/render_standees.py`. Nothing printed is tested (the author,
2026-09-23), so a change is checked by rendering the pages and looking.

```bash
python3 scripts/render_standees.py                # into d12ball/print/standees/
python3 scripts/render_standees.py --team orange
```

## Why standees, and why now

The kit used to send a table off for nine meeples a team. That was
enough in 1.0, where a player's role is on their card and a meeple only
has to say which side it is on. **D12 Ball 2.0 takes the role off the
player** (rules-2.1 section 4): a role belongs to the formation and moves
from card to card in a Coaching Choice, so a meeple cannot be told apart
by role either, and nine identical meeples a side say nothing about who
is standing on a space (the author, 2026-10-24). A standee is the
player's own portrait -- the bot's art, the picture on their card -- so
the field and the cards on the zone board are read as one set of people.
The role itself is marked on the card, with a role token
([printed-tokens.md](printed-tokens.md), "Role tokens").

**Nothing on a standee belongs to an edition**: the portrait, the name,
the species' icon and the team's colour. No role, because 2.0 has none
on the player; no skills, because the advanced face of a card changes
them. So 1.0 plays with the same standees.

## Flat, for a slotted base

The author chose a flat standee pushed into a plastic base over a
fold-up paper tent (2026-10-24). One strip a player carries both faces
end to end, the fold at the top of the two portraits; it is cut out,
folded, glued back to back and its foot (`FOOT_HEIGHT`) pushed into a
1in (25 mm) slotted base. Two layers of paper are thinner than most
bases' slots, which is why the page and the kit's README suggest a
layer of thin card between the halves. A team wants six bases, one for
each player on the field, a substitute's standee going into the base of
the player they replace; they are meant to be 3D printed, and there is
no model for them yet (the author, 2026-10-24).

- **The back is drawn upside down above the fold**, so the fold stands
  it up the right way. It is the front's picture again, **not its mirror
  image**: the first draft mirrored it, as a flat figure seen from behind
  would be, and every jersey number and every d12's numbers came out
  backwards. A rectangle has no outline a mirror would keep true, so
  there was nothing to gain from it.
- **Printed one-sided.** Both faces are on the one strip, so unlike the
  cards and the tokens nothing has to land back to back through a duplex
  printer.
- **The colour bleeds past the cut line** (`BLEED_INCHES`, a millimetre),
  each face's own edge drawn outward, so a cut a little outside the grey
  line leaves colour rather than white paper.

## The size: the space decides

A face is `FACE_WIDTH` (1.25in) across because the narrowest space on a
printed field is 1.36in -- board 10's (`FieldGeometry.space_inches`);
board 9's is 1.48in and board 7's 1.81in. Two sides' standees on one
space stand along its length, which is 7.7in, not across it, so the
width only has to clear one space.

The paintings are mostly wider than they are tall (Umbrik is 477 x 312),
so the width decides how big a portrait prints, and `PORTRAIT_HEIGHT`
(1.15in) is what a typical one fills at that width; a tall one
(Kindlefinger) is fitted to the height instead. The first draft's 1.4in
left a band of empty tint over most of them. A portrait stands on the
name band, with no gap under it, and prints at 330dpi or better.

## The face

- **The ground is a pale tint of the team's colour** (`GROUND_TINT`), so
  which side a standee is on reads from across the table, and the
  painting -- a cut-out, see "The player cards" in [cards.md](cards.md) --
  stays in front of it.
- **The band is the team's colour** with the name in `high_contrast_ink`
  (black on Slime green, white on the rest), the same rule the card's
  header follows, and the species' icon at its left in the same ink (kept on the
  author's word, 2026-10-24),
  because a species ability is decided on the field (an Ooze's sharing a
  space, a Telekinetic's Mind Pull) and a coach looks for it there. The
  name is centred where it fits beside the icon and pushed right of it
  where it does not; "Flickerwing" and "Kindlefinger" are the long ones.
- **The foot is a deeper tint** (`FOOT_TINT`), so where the base begins
  shows.

## The page

A colour team is one letter page, portrait (`<team>-standees.png`), its
nine in roster order, five across: two rows of 3.4in strips fit with the
team's name and how to make them over the top, so the page carries its
own instructions when it has left the kit's README behind. The landing
page's kit carries the standees in each team pair's players zip, not
the first one, which they took over Cloudflare's 25 MB a file
([landing-pages.md](landing-pages.md), "The downloads").

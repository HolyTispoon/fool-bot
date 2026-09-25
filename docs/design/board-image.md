# Working on the board image

Design notes for fool-bot; the map is [CLAUDE.md](../../CLAUDE.md), the rules are [living-rules.md](../living-rules.md).

## Working on the board image

The board image is the bot's main output, so look at it. Don't rely on the
test suite to tell you a rendering change is right — it only asserts the
output is a PNG of the expected dimensions.

```bash
python3 scripts/render_sample.py --home purple --visiting teal --out board.png
python3 scripts/render_sample.py --home-formation 2-3-1 --board-size 9
python3 scripts/render_sample.py --coaching home       # a coach's own half
python3 scripts/render_sample.py --field               # the field on its own
python3 scripts/render_sample.py --list-games
python3 scripts/render_sample.py --game <game_id>      # reproduce a real board
```

`--game` renders a real saved game from your own `data/d12ball_games.json`,
which is how to reproduce a board someone reported a problem with rather than
guessing at the state. Saved games are local to each machine, so a fresh clone
lists none until the bot has been run.

**A refactor of drawing code is verified by hash, not by the suite, and
not by eye either.** The suite cannot see a pixel, and a change that moves
everything two pixels left looks fine on a screen. So the check is: render
every image the function feeds *before* touching it, keep the bytes,
re-render after each commit and compare SHA-256s -- byte-identical or it is
not done. The 2026-09-18 split of the rendering layer's oversized functions
(`draw_strip`, `render_matchup`, the card back and face, the reference
image, `draw_board` and the three verdict dice) was done that way against
107 images: every card on both tiers, the sheet, the hands and the bleed
cut, the boards at every size plus a stack and a species 9, both
coaching halves, the field strip, the print boards, and every branch of
every dice image. Cover both tiers and both board sizes at least --
`draw_strip` draws a basic card on the 7-space strip and an advanced one on
the 9, and `render_maneuver_card_back` draws a different hexagon per tier.
The renders are deterministic (two runs, identical hashes), which is what
makes this a check rather than a hope. The baseline script is throwaway
scaffolding and is not in `scripts/`; the recipe is the paragraph above.

- **The shape those splits settled on is `boards.py`'s**: a geometry or
  layout record computed once (`StripGeometry`, `MatchupLayout`,
  `VerdictRow`), and small `draw_*` functions taking the pen and that
  record, so the top-level function reads as the sequence of bands it
  draws. Every coordinate expression is copied verbatim in the same
  evaluation order -- `(a + b) + c` is not `a + (b + c)` in floating point,
  and a `round()` on the far side of one will flip on the one input that
  sits on a half.
- **`VerdictRow` is the die-portrait-verdict row the injury test, Mind Pull
  and Volatile share -- the row, not the proportions.** Each still passes
  its own radius, portrait size and gaps, which is what keeps Volatile's
  168px portrait and spread columns its own (see "The ignition die" in [species-abilities.md](species-abilities.md)); what
  is written once is the arithmetic that places a column. Volatile keeps
  its own width and column-gap sums beside it, since the explainer sizing
  the canvas is the one thing about its row that is not the same row.
- **`draw_end_zone` was left whole on purpose.** Its rotation maths was
  verified against Pillow's actual output rather than derived (see "End
  zones"), and a split that re-derives where the "O" lands is a sign error
  waiting to be silent.

**The first board of a game goes up when setup coaching ends**, not when the
match is created. `finish_setup_coaching` posts it; the coin toss and the
home/visiting choice leave the persistent message imageless, and an AI setup
window skips its own refresh while `pending_setup_stage` is set. Nothing has
been played before that point, so a board posted earlier shows a deal neither
coach has finished with and is redrawn twice over before anyone acts on it --
the one worth looking at is the line-up the game kicks off from.

**And it goes up through `post_new_play_board`, like every other new play's.**
A kickoff *is* a new play, so its board is its own message under the coaching
that produced it, pinned like the rest. It used to attach the board to the
persistent message instead, which put it in the right order but the wrong
place: Discord leaves an edited message where it was, so a board finished after
two coaching windows appeared above them, at the top of the channel, with the
timestamp of the home/visiting choice. Both developers read that as the change
never having landed. The persistent message still gets the same render in the
same breath -- `post_new_play_board` refreshes it from the `png=` it already
drew -- so this costs one message and one pin per *game*, not per turn.

**The last board of a game rides on the result, and is the one board that is
not pinned.** `announce_game_over` posts it under the whistle (or under the
shootout that settled it) for the reason a loose ball's board is posted with
its announcement: by full time the persistent message has scrolled hours up
the channel, and the final position is exactly the thing nobody should have to
go looking for. It is the usual render-once-upload-twice -- the persistent
message is settled from the same bytes, which is why neither `end_period` nor
`continue_shootout` refreshes it themselves any more. Pinning stays the new
play's alone: a pin here would be the one at the very bottom of a channel
nobody is playing in again.

**There are three board images. Two are drawn, and the third is cut out of
one of them.** `render_match_image` is the 2200px one everybody sees;
`render_coaching_image` is the 1280px half-field a
[Coaching Choice](coaching-choice.md#the-coaching-choice) keeps up, and those two do not share a
layout. The coaching image carries one row of meeples instead of two, so at the
match image's width it arrives in Discord as an unreadable sliver. **It is
deliberately not mirrored for the visiting coach**: the zones keep their real
names and the spaces their real numbers, so V1 is the same space on both images
and on the board the coaches are looking at.

**That half-field is the Coaching Choice's and nothing else's.** The ball is
left off because a Coaching Choice happens with play stopped and none of its
four actions turns on where the ball is, and only one side's row is drawn
because the flow is a coach arranging their own team. Both of those are wrong
for a prompt about a live position, which is why every
[distance prompt](maneuver-prompt.md#choosing-a-distance-and-the-field-under-it) and the run back carry the field strip
below instead -- a mistake worth naming, since the first build of those
prompts reached for this image and grew it a `show_ball` to make it fit.

**The half-field carries the clock**, right-aligned in its title row
(`draw_coaching_clock`): the minute and the period, so a coach arranging
their side can see how much of the half is left. It reads
`match.scoreboard.time`, and that is the minute the window opened on,
because nothing moves the clock while a window is open -- a time out charges
its minute in `finish_time_out`, after both windows close, and halftime puts
the clock on 15 before either window opens. So there is no saved "minute the
window opened"; if something ever charges time inside a window, this is the
image that would start showing the wrong minute.

**`render_field_image` is the third, and it is a crop rather than a third
layout.** The field alone -- both sides' meeples, the ball, the space codes and
the shooting range edges, with no title, jumbotron, assignment cards, team
boards or benches -- for the message under a coach's maneuver cards (see "The
maneuver cards"). It draws the match image's canvas, calls the same
`draw_board`, and cuts the board's rectangle plus `FIELD_MARGIN` out of it, so
it is made of the same pixels as the board both coaches are reading and cannot
drift from it: a change to a space, a meeple or the ball token reaches it
without being made twice. It is the one board image that is **not** upscaled --
`OUTPUT_SCALE` is there so a 2200px board holds up when a client blows it up,
and a strip a third of that height is shown at its own size or smaller.

Two things set its width, and both are three cards wide. A zone's **assigned
cards** are drawn under that zone, and midfield holds three under 2-3-1 and
1-3-2 (a goal zone does under board 9's 3-2-1 and 1-2-3, which is the same
three); a space has to fit a **stack**. `D12BallComponentTests` checks the
first, because the suite cannot see the image and an overflow here is silent.

**Nothing deals a stack any more, and the coaching image was sized for the
one that did.** The width was set on board 6's two-space midfield under 2-3-1
-- two meeples, 155px, into a 200px space. With the six-space board withdrawn
(2026-09-22 in [rules-log.md](../rules-log.md)) no shape overfills a zone, and
the narrowest space is board 9's 133px, so a stack a coach builds by hand with
space positioning is wider than the space it stands on. That was already true
of a hand-built stack on board 7 before the withdrawal; what changed is that
the case the width was chosen for is gone, so `COACHING_WIDTH`'s note now
states the meeple it does fit. Widening the image, or shrinking the tokens in
a stacked space, is an open rendering question rather than a regression.

**The cards and the two benches are on it for a reason.** Exhaustion counts and
the Exhausted and Injured badges are drawn nowhere else, and which pool a
player is in is the whole of who may come on -- so without them the flow would
be asking a coach to remember numbers off a board they cannot see while the
menu is up.

**A card carries its player's species icon, stacked under the role initials
on the stats row** -- the same pairing a meeple makes (below), so a coach
reading one is reading the other. It used to sit beside the role initials, in
the space to their right, which put it in the same right-edge column the
Exhausted, Injured, Drained and Damaged badges are drawn in afterward (see
`draw_card`) -- and on a wide role label (`WG`) that column left next to
nothing between them, so the badge covered the icon completely rather than
partially, on every one of those four conditions, not only some. Stacking
clears that column for a badge regardless of how wide a role's own initials
run, and costs neither element its own tested size: the icon keeps its 18px
floor (see "The species icons" in [cards.md](cards.md)) and a badge keeps the
26px `scripts/render_condition_tokens.py` was resized to on 2026-09-19,
because the card is not wide enough to hold both a floor-sized icon and a
floor-sized badge side by side, on the widest role label, and neither floor is
the one to give up. It is drawn in ink rather than in a colour, which is what
keeps `rendered_player_card`'s cache key honest: that key is the player and
their two skills, and a colour would be a third thing in it -- the shape is
the identity anyway, and the Oozes' green is the one colour a white card could
not carry.

**A meeple is the species icon over the role initials, and it is 76px
because it carries both -- in a game playing species abilities.** `draw_meeple_face` is the face; `draw_meeple_group`
composites it onto the canvas it now takes. (It is the Screentop meeple
now, not a disc -- see "A meeple is the Screentop piece" below; what follows
is how the disc got to 76px, which is the square the meeple fills.) It was a 56px disc with the
initials alone until 2026-09-18, when species abilities made what a card *is*
as much a fact of the position as what it does. Thirteen drawings were tried
and judged at the width Discord shows the field strip (~900px), not at the
2200px canvas -- which is what separated them:

- **The species colour is not the signal and cannot be.** Every species
  shares its colour team's hex (see "Team colors" in [teams-and-players.md](teams-and-players.md)), so a species-coloured
  ring on an Orange token is just orange. The icon is drawn in the same ink
  as the initials and the outline, and the *shape* is the whole of it -- the
  four silhouettes were drawn to survive 18px for exactly this (see "The
  species icons").
- **A mark added to a 56px disc vanishes at that width.** A corner badge, a
  watermark behind the initials, an icon at the name's height and a species
  word on a second line were each drawn and each turned to noise. What
  survives downscaling is a big flat mark, so the disc grew and the icon is
  the larger of the two things on it; the initials are also in every name
  label a coach reads, where the icon is not.
- **The icon *as* the face, with the role moved into the label, read best
  and was not chosen**: the meeple is where a coach matches a role to the
  card and the printed card (see "Naming a player" in [naming-and-wording.md](naming-and-wording.md)), and the author kept it
  there.
- **The two rows moved to make room.** `VISITING_MEEPLE_TOP` and
  `HOME_MEEPLE_TOP` are the offsets, the ball token reads the same two, and
  the home row moved up 15px so each row keeps about the same space for
  names (54px and 51px). A two-meeple stack is 155px, which the match
  image's ~330px spaces hold and the coaching image's no longer does --
  see "Nothing deals a stack any more" above.
  `test_a_meeple_carries_its_species_over_its_role` holds the sizes that
  are still checked.
- **The icon is drawn only in a game playing species abilities** (the
  author, 2026-09-18). In a basic game, or an advanced one that opted the
  module out, species is a name on the card and nothing a coach acts on, so
  the disc carries the initials alone -- `FONT_TOKEN_SOLO`, sized to fill
  the 76px it still is; the disc does not shrink back, or the two rows and
  the ball would move with the mode. `species_icons` is the flag on all
  three render entry points (`render_match_image`, `render_field_image`,
  `render_coaching_image`), defaulting to **off** so a caller that forgets
  it draws a basic game rather than an advanced one, and the cog's three
  call sites answer it from `RulesEngine.species_abilities_apply(game)` --
  the renderer never reads the game's own bools, which is the same rule
  every ability site follows (see "Species abilities in the bot" in [species-abilities.md](species-abilities.md)).
  `test_every_cog_render_asks_the_engine_whether_to_draw_species` greps
  those three calls, because a site that forgets the flag draws every
  advanced game without its species and nothing else in the suite can see
  it. `scripts/render_sample.py` draws the advanced look by default (it is
  the one worth checking), `--basic` for the other, and a `--game` the way
  its own record says.
- **A missing icon falls back the same way** -- initials alone, filling the
  body -- because the loader is silent (see "A bundled file's name is
  case-sensitive...").

**A meeple is the Screentop piece, not a disc** (the author, 2026-09-25).
The token is `MEEPLE_PATH` -- the Screentop table's own SVG outline, the
one the box art and the sale sheet stand on the printed board -- read by
`flatten_path` and fitted by `meeple_points`. It is **copied, not traced**:
a second drawing of the piece is how the bot's meeple would come to differ
from the table's, and the path and its reader moved from `box_art.py` into
`render.py` so there is one of each (box art imports them; all ten box
panels hashed identical across the move).

- **It fills the square the disc did.** The piece is as wide as
  `MEEPLE_SIZE` (it is a little wider than tall) and stands on the
  square's floor, so the two rows, the ball token and the names are placed
  exactly as before -- nothing else on the board moved.
- **The initials sit on the body, and the icon crosses the neck.** The
  head is too small to carry anything at 76px, so the species icon (24px)
  is on the chest and the initials under it, above the notch between the
  legs, which would otherwise cut the letters. The icon's top crosses the
  neck line into the head (the author, 2026-09-25): centred lower, it sat
  close enough to the initials that the two read as one mark. The heights are in the path's own units
  (`MEEPLE_ICON_CENTER`, `MEEPLE_ROLE_CENTER`, `MEEPLE_SOLO_CENTER`, read
  by `meeple_y`), so they follow the piece rather than the square.
  `test_a_meeple_carries_its_species_over_its_role` checks the icon clears
  the initials and the initials clear the notch.
- **The solo initials are 20px, down from 26.** The body is narrower than
  the disc was, and 20 is the size at which "WG", the widest pair, stays
  between the arms.
- The icon went from 38px to 24 to fit the chest. The four silhouettes
  were drawn to survive 18px (see "The species icons" in
  [cards.md](cards.md)), so 24 is above the floor -- but it is smaller
  than it was, and worth a look at the width Discord shows the strip.

**The ball token hangs off the possessing side's meeples, except when they have
none there.** `ball_token_x` is the whole of the placement: normally it tucks
against that side's group on the open end of the row, which keeps it next to
whoever is holding it however many of them share the space. An empty group
reports the whole space as its bounds, so anchoring to its edge drew the ball a
radius *outside* the space, under the next space's tokens -- which meant
[a loose ball](loose-balls.md#loose-balls-and-the-board), the one position whose whole
question is where the ball is lying, was the one thing the board did not show.
With nobody of that side there it is centred in the space instead. The suite
cannot see the image, so `D12BallComponentTests` asserts the placement rule
rather than the pixels.

## The matchup image

`render_matchup` draws a contest about to happen, and one layout serves two:
the maneuver challenge (one against one) and the score attempt (one against a
wall of defenders). See "What a shot is up against" in [shooting.md](shooting.md) for the badges only the
second one carries.

**Its width is content, not a canvas.** Each side is a group as wide as it
needs to be, held between `CHALLENGE_MIN_GROUP_WIDTH` and
`CHALLENGE_MAX_GROUP_WIDTH`, and the image is the two plus `CHALLENGE_GUTTER`.
Discord scales the whole thing down to the message's width, so every pixel of
empty black is spent making the writing smaller — which is what a 300px
minimum was doing on a maneuver challenge, where both groups are a two-word
name and a skill line. The minimum is now little more than the portrait it
sits under, and it is a floor for a group *carrying an ability*: a wall of
defenders has none, and packs to its own content.

- **The sum overrides the maximum.** A total broken over two lines with the
  number stranded on the second is unreadable however narrow it makes the
  image, so `group_width` floors on it. The maximum caps the *names*, which
  can wrap.
- **A matchup has its own fonts** (`FONT_CHALLENGE_TITLE`, `_BODY`,
  `_ABILITY`, `_TOTAL`) rather than borrowing `FONT_SMALL` and
  `FONT_DICE_TOTAL`, which size the board and the dice and are not on this
  image at all. The heading is the one line nobody needs to read — it names a
  picture a coach is already looking at — so it is set *below* the body, and
  the room that frees goes to the names, skills and abilities. Changing a size
  here changes the width: the text is what the groups are measured from.
- **Look at it.** The suite checks it is a PNG and nothing about how it reads.
  There is no sample script for this one; render a `ChallengeSide` pair
  through `render_maneuver_challenge` and `render_score_attempt` (three
  defenders, one of them halved, is the widest case) and open the result.

## Fonts

Fonts are bundled in `d12ball/fonts/` and loaded by absolute path. **Do not go
back to looking them up by bare filename.** `ImageFont.truetype("Arial.ttf")`
searches the host's font directories, and the same typeface is filed under a
different name on macOS, Windows and Linux, so no list of bare names works
everywhere. When every name misses, Pillow's `load_default()` returns a face
pinned to size 10 that ignores the requested size, and every label on the
board silently collapses to tiny text. That was a real bug; the tests in
`D12BallFontTests` exist to keep it from coming back.

**A second family, Racing Sans One, is bundled the same way** for the goal
zone's own "GOAL" lettering (`load_goal_zone_font`) -- an uppercase, slightly
slanted display face, picked over several others tried in the same slot
(DejaVu Bold read as too plain, Anton's condensed width didn't leave room to
also space the letters out, Bungee read as too blocky) for the author's own
taste, over the same bundled-path-first fallback chain and falling back to
DejaVu Bold rather than Pillow's built-in face. Its OFL license is
`RacingSansOne-OFL.txt` in the same directory, alongside the DejaVu one.

`render.py` builds its font objects at **import time**, so a running bot keeps
whatever it resolved at startup. Restart after any render change.

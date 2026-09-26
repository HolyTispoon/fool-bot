# The web app redesign

**This is a worksheet, not a specification.** On 2026-09-26 the author
reviewed a redesign of the web app as a design prototype, the canvas at
https://claude.ai/artifact/Mq7Mw592x9WYKjrN3Muo9V (31 artboards, every
screen and state, revised over some forty comments), and asked for it
to be built. This file is the plan: what the prototype settled, the
steps in the order they build on each other, and one prompt per step
written to be handed to a Claude Code session as it is. Strike a step
when it lands and move what it settled into `docs/design/web-app.md`.
It supersedes steps 9 to 11 of [web-app-next.md](web-app-next.md):
"my rooms" and the statistics are steps 9 and 12 here, the reading
room is step 10, and the tests the survey found missing come with the
step that touches each area. **Nothing in it is a rule.**

## What the prototype settled

Decided in review of the canvas, 2026-09-26 (the author), and binding
on every step:

- **The chrome stays Discord's; the play area is drawn from scratch.**
  The page keeps the greys and text colours `webapp/static/app.css`
  already has. The field, the jumbotron, the question box and the
  sidebar are new. Nothing a web-app user sees names Discord.
- **No coloured buttons.** The answer to a prompt is the thing on the
  board it concerns, lit in gold: a meeple, a space, the ball, a goal,
  the die, the whistle, the time-out tile, a card. The question box
  says what is lit and why. Where nothing on the board can be the
  answer, one neutral outlined control. Every click has a keyboard
  path.
- **The meeple is the Screentop piece**, `render.MEEPLE_PATH`, in the
  team's colour with the ink outline, the role initials on the body
  and, in basic and advanced mode, the species icon over them as the
  bot draws it (`meeple_geometry`). Not in training mode.
- **Fans.** Two or more of one team on a space overlap diagonally: a
  home fan from the bottom left at the back to the top right at the
  front, a visiting fan from the top right at the back to the bottom
  left at the front; the ball's holder is always the front piece. A
  pair steps 30px across and 22px down, three 22/16, four 17/12, so a
  four-fan stays inside its space. Names one per line under the fan,
  each centred under its own piece, the front piece's name first; a
  cost chip on its own line under the name. Nothing leaves its space.
- **Badges.** Exhaustion is the token image with its count, off the
  bottom right of every piece (the drain token on a Cyborg); never the
  word "token" alone. Exhausted and Injured are the emoji at the bottom
  left. The ball is the d12 showing its speed: off the top right of a
  home holder, almost touching; off the bottom left of a visiting
  holder, overlapping the edge. A loose ball sits at the centre of its
  empty space. All drawn above the fan.
- **The goals** are 70px slabs bordered in the defending team's
  colour with GOAL upright in Racing Sans One at 62px, the d12 showing
  12 as the O, the four items evenly spread and centred, the word
  turned along the goal. A goal lights when it is the answer.
- **Outcomes are large and first**: a 46px headline in the winner's
  colour, the arithmetic under it, the dice at 84px beside it, above
  the next question. The headline and the arithmetic are the model's
  narration, never the page's wording.
- **The shot brief** reads as the Score attempt Law scores it: attack
  d12 + offence + ball speed; defence d12 + every defender in the way,
  listed with what each adds; equal or higher scores.
- **The jumbotron is one bar** over the field: teams, score, coaches,
  possession, the 30-minute track, last possession, and a TIME OUT
  tile per team that is solid gold when it may be called.
- **The bench is two boxes per team**, bench and back bench, with the
  hover card. **Hover any meeple for its card**; hold on touch.
- **Four sidebar tabs**: Log, Chat, Teams, Rules. The Charter and the
  references are read in the page from the same files the bot reads;
  no PDF anywhere. A refusal cites its Law.
- **The phone keeps the field horizontal and whole**, fitted to the
  width, with the move as a bottom sheet that repeats the lit options
  large enough to tap; landscape shows the desktop field.
- **The front door** is the rooms as cards and one "+ A new room"
  card with two ticks (Dinky in the other seat, the tutorial); the
  table's seats are cards with the swatches; the coin is the bot's
  gold coin art, clicked to flip; the side is chosen by clicking the
  goal to defend; the identity reads "You are Coach 1", "You are the
  Home coach", "You are an observer".

## The steps

In the order they build on each other. Each is one branch off an
up-to-date `main`, one PR against the template, the suite green, the
six safety-net tests untouched unless the step says why. None changes
the save format. None adds a rule to `webapp/`. Two places may need
the model to say more than it does (a headline on a narration group,
step 3; a Law on a refusal, step 10): each is proposed inside its
step as its own commit for the author to accept or refuse, never
slipped in.

**Answered by the author, 2026-09-26**, on the plan's PR: the two
proposed model changes are decided when each step's PR arrives, not in
advance, so a step that carries one opens as a draft with the change
in its own commit and the question under `## Questions for the author`.
The routine that ran `docs/web-app-next.md`
(`trig_01TfqdFJ3jQjC4XTFh7qqwZe`) is disabled for good; the routine
for this plan is `trig_01FzyzX3xSLWMPKYy2if5uuK`.

| # | Step | Size |
| --- | --- | --- |
| ~~1~~ | ~~The field, drawn from scratch~~ -- landed; what it settled is in docs/design/web-app.md, "The page" ("The field is drawn from scratch") | large |
| ~~2~~ | ~~The jumbotron bar and the time-out tiles~~ -- landed; what it settled is in docs/design/web-app.md, "The page" ("The jumbotron is one bar", "The time out is a tile") | medium |
| ~~3~~ | ~~The question box and the outcome banner~~ -- landed; what it settled is in docs/design/web-app.md, "The page" ("The question box") and "The outcome banner" | medium |
| 4 | Answering on the board: the objects, no coloured buttons | large |
| 5 | The hand, the reveal and the challenge | medium |
| 6 | The Coaching Choice on the board | large |
| 7 | The shootout order | medium |
| 8 | The bench | small |
| 9 | The front door and the table | large |
| 10 | The sidebar tabs and the reading room | large |
| 11 | The phone | medium |
| 12 | Full time | small |
| -- | Later, and not now | -- |

### Claiming a step

**Claim a step before starting it**, whoever you are: either
developer, a Claude Code session, or the cloud routine that starts the
next step when the last one merges. Two people building the same step
is a whole step thrown away.

```bash
python3 scripts/claim_web_step.py --series redesign <n>
```

A claim is the branch `redesign-step-<n>` on origin: one empty commit
on top of main naming who claimed it, pushed create-only, so of two
claims made at once exactly one lands. It is the branch you work on,
too. The script refuses a step that is struck above, or already
claimed. What counts as a claim, and what the routine checks before it
starts anything: a branch on origin named `redesign-step-<n>` or
`redesign-step-<n>-<anything>`, or an open PR, draft or not, titled
`Redesign step <n>: ...`. A step whose last PR was closed without
merging is treated as rejected: the routine does not pick it up again
until somebody claims it by hand. Release your own claim with
`python3 scripts/claim_web_step.py --series redesign <n> --release`.
A step lands when its PR strikes its number in the table above, and
the next unstruck number is the next step.

**Every PR carries a `## Questions for the author` section**, reading
`None.` when empty, so the author can see at a glance whether anything
waits on them.

---

## Preamble

Every step's prompt begins with this block. A session given a step
reads it first, then the step's own prompt below.

```text
You are working in the fool-bot repository (a Discord bot and a web app
for the board game D12 Ball). Read CLAUDE.md first, then
docs/design/web-app.md and docs/web-app-next.md, and the design doc for
any other area you touch. Start on a fresh branch off an up-to-date
main (git checkout main && git pull --ff-only && git checkout -b <topic>).
Run python3 -m unittest discover -s tests before you open the PR; the
purity tests (tests/test_web_purity.py, tests/test_model_purity.py) must
stay green: webapp/ imports nothing from cogs/ or discord, and nothing
in d12ball/ or gamesaves/d12ball/ grows a discord import, an async def
or a PIL import.

Hard rules for every step of this redesign:
- The web app is a frontend over GameService and the flow. It computes
  no rule of its own: every control is built from PendingPrompt.options
  and nothing else (webapp/present.py), every value the board draws is
  asked of the same function the PNG asks (webapp/board.py), every
  refusal is the model's. If the design needs something the prompt does
  not carry, the options grow a field in d12ball/prompts.py, both
  frontends read it, and that is its own commit reviewed as a model
  change. Never re-derive a candidate list, a distance or a range in
  JavaScript.
- No coloured buttons. The answer to a prompt is the thing on the board
  it concerns (a meeple, a space, the ball, a goal, the die, the
  whistle, a card, a tile), lit in gold (#f0b232). The question box
  says what is lit and why. Where nothing on the board can be the
  answer, use the one neutral outlined control style. Keep a keyboard
  path (number keys, Enter, Esc).
- Colours are Discord's chrome as webapp/static/app.css already has
  them (page #313338, panel #2b2d31, deep #1e1f22, text #dbdee1, muted
  #949ba4, line #3f4147) plus TEAM_COLORS from d12ball/render.py, read
  through board.py, never restated. The two typefaces are Racing Sans
  One (already bundled under d12ball/fonts/, serve it) for display and
  a humanist sans for body.
- Every image the page needs is the model's own, served by
  webapp/pictures.py: player cards, maneuver cards, the emoji
  (exhaust, exhausted, injured, drain, drained, damaged), the coins
  (3_gold_fortune, 3_gold_doom), the species icons through
  render.species_icon. Draw nothing twice.
- The design is the canvas at https://claude.ai/artifact/Mq7Mw592x9WYKjrN3Muo9V.
  Match it; where the prompt below and the canvas disagree, the prompt
  wins, and say so in the PR.
- Keep the map and the design docs current: update docs/design/web-app.md
  in the same commit for any decision this step settles, with the
  reasoning. Do not touch docs/living-rules.md.
- One PR per step, with a short description of what changed and what
  you deliberately left for a later step.
```

---

### 1. The field, drawn from scratch

**Landed** (2026-09-26). What it settled is in
[design/web-app.md](design/web-app.md), "The page" ("The field is drawn
from scratch"), and [design/board-image.md](design/board-image.md),
"The web page's board": the fan is `board.py`'s and tested there
(`FanTests`), the marks and the lit range are the model's answers, the
field carries no cards, and the lit look of a piece or a goal is built
for step 4 to feed.

**Prompt.**

```text
Rebuild the board in webapp/static (HTML/CSS/JS) and webapp/board.py to
match row 2 of the canvas ("A turn, screen by screen") and the
"Crowded spaces" board in row 5. board.py stays the one place that asks
the rules for a value; the page only draws what board.py hands it.

The field:
- A dark stage (#1e1f22, 14px radius). Seven spaces (nine on the 9
  board) in one row, each a rounded box at least 320px tall, numbered
  top-left in the current space code (space_label; the flat numbering
  experiment is on). Zone names above the row (HOME ZONE, MIDFIELD,
  VISITORS ZONE in Racing Sans One, letter-spaced) and the shooting
  ranges below as two bars plus a KICKOFF bar in the middle; a range bar
  lights gold when the side to move is in range (board.py asks
  can_attempt_score / the range the engine exposes; do not compute it).
  The kickoff space carries a faint centre ring.
- The two end spaces of each zone are tinted with the defending team's
  colour at ~12% alpha; midfield stays the panel grey.
- A goal at each end: a 70px-wide slab, #0c141c, bordered in the
  defending team's colour, carrying the word GOAL in that colour at
  62px Racing Sans One, upright (no italic), with the d12 showing 12
  standing in for the O (56px, drawn upright), the four items spread
  evenly (22px gaps) and centred; the whole word rotated -90° on the
  home end (reads upward) and +90° on the visitors' end. A goal lights
  gold (ring plus glow) when it is the answer to a prompt.
- Each space has two lanes: the visitors' in the top half, home's in
  the bottom half.

Meeples:
- The piece is render.MEEPLE_PATH as an inline SVG (board.py already
  hands meeple_geometry), 50px wide on the desktop, team fill, ink
  outline (high_contrast_ink), and gold outline when lit.
- The role initials on the body; in basic and advanced mode the
  species icon (render.species_icon in the ink colour) over the
  initials with its top across the neck into the head, at the offsets
  meeple_geometry gives (icon_center, role_center, solo_center). Not in
  training mode. Ask board.py whether species apply; do not read the
  mode in JS.
- The name centred under the piece, 12px bold, gold when the piece is
  lit; a lit piece also carries a chip under the name saying what
  clicking it means, with any cost drawn as the exhaustion token image
  and a count ("×1"), never the word "token".
- Exhaustion: the emoji image with the count, floating off the bottom
  right of every piece (drain for a Cyborg). Exhausted / Injured (and
  the Cyborg pair) as the emoji at the bottom left. Both drawn above
  everything else in the space.
- The ball: the d12 showing its speed (30px on a dark ring). On a home
  holder it hangs off the top right of the piece, its lower edge almost
  touching the shoulder; on a visiting holder, the bottom left,
  overlapping the edge by the foot. A loose ball sits dead centre of
  its empty space, larger (36px).

Fans (two or more of one team on a space):
- Pieces overlap diagonally. A home fan runs from the bottom left at
  the back to the top right at the front; a visiting fan from the top
  right at the back to the bottom left at the front. The ball's holder
  is always the front piece.
- Steps: a pair 30px across and 22px down; three 22/16; four 17/12, so
  a four-fan stays inside its space. Badges and the ball are drawn on
  top of the whole fan.
- Names: one per line under the fan, each centred under its own piece
  (so they step with the fan), the front piece's name first. Nothing
  may spill outside the space; the space clips.

Hover: hovering any meeple (field or bench) shows its player card,
served by pictures.player_card_png in the face the mode plays; press
and hold on touch; click the card to pin it; Esc or clicking away
dismisses it. Keep the existing full-card dialog.

Done when: the board renders every state tests/test_web_board.py
covers, a new test in that file checks the fan layout rules (order,
front piece, steps) from board.py's output and not from the HTML, and
scripts/render_sample.py --game <id> and the page agree on every value
they both show. Look at it in a browser at three board states
(kickoff, a crowded space, a loose ball) and put screenshots in the PR.
```

---

### 2. The jumbotron bar and the time-out tiles

**Landed** (2026-09-26). What it settled is in
[design/web-app.md](design/web-app.md), "The page" ("The jumbotron is
one bar across the top of the play area", "The time out is a tile, not
a button"): every value on the bar is `board.jumbotron`'s reading of
the match (`JumbotronTests`), and the tile is lit by the turn's own
time-out control carrying a `place`, so pressing it is the old button's
answer (`test_the_lit_time_out_tile_is_the_time_out_button`).

**Prompt.**

```text
Replace the sidebar jumbotron with one bar across the top of the play
area, as on every play screen of the canvas.

Left: the home team's name in its colour (Racing Sans One, 26px) with
"▶" for its direction, "Home · coached by <name>" under it, and a
gold "BALL" mark with a small d12 when it has possession. Centre: the
score at 44px with "D12 BALL" under it. Right: the visitors the same
way, mirrored. Then a rule, and the clock column: the minute at 30px in
the clock yellow (#f5d76e) beside "1st half" / "2nd half", a 30-segment
track filling gold as the clock advances with 0 / 15 · halftime / 30
under it, a red LAST POSSESSION chip when the model says so, and one
TIME OUT tile per team.

The tile: outlined in the team's colour with a referee's T when the
side still holds its time out this half; dashed grey and struck
through once spent; and solid gold with a glow reading "TIME OUT ·
<team> · click to call it" when, and only when, the pending prompt's
options include the time out for the viewer's side (TurnOptions
actions). Clicking it answers that prompt. Everything the bar shows
comes from the wire state and board.py; the page decides nothing.

A note for halftime, the shootout and the final board goes under the
clock ("Halftime", "Shootout", "Final · 2 : 2, shootout 1 : 0").

Done when: the bar shows correctly for a fixture at kickoff, mid-half,
last possession, halftime, the shootout and full time
(tests/prompt_fixtures.py has these), and tests/test_web_app.py
presses the lit tile and gets the same result as the old Time out
button.
```

---

### 3. The question box and the outcome banner

**Landed** (2026-09-26): the box, its four tags off `asked_sides`, the
refusal strip, the owed strip and the picture slot are in
docs/design/web-app.md, "The page" ("The question box"). The narration
did not split into a headline and a detail, so the banner's words ride
on a proposed model change, `d12ball.flow.result.Headline`, in its own
commit on the step's PR for the author to accept or refuse -- see "The
outcome banner" there.

**Prompt.**

```text
Rework the prompt panel under the field into the question box on the
canvas.

- A state tag at the top: YOUR MOVE (gold, and a gold left edge on the
  box), WAITING ON THE OTHER SIDE (grey), NOW (blurple, for a note or a
  roll either coach may take), FULL TIME (green). The box tells the
  viewer which it is from asked_sides; it does not decide.
- The ask in 17px, then a line in muted text saying what is lit on the
  board and why (this replaces the row of buttons for every prompt that
  has an object on the board; step 4 does the objects).
- The outcome banner, first in the box whenever the last result carried
  one: a 46px Racing Sans One headline in the winning side's colour
  (HIGH PASS WINS, SAVED, STEAL · TURNOVER, A TIE: SKILL TEST, HALFTIME
  · 1 : 1, PURPLE WINS 3 : 2), the arithmetic at 17px under it, and
  the dice at 84px beside it in the roller's colour. The headline and
  the arithmetic are the model's narration lines, not the page's
  wording: take the group the driver tagged and show its first line
  large. If the narration does not split cleanly into a headline and a
  detail, say so in the PR and propose the smallest change to
  d12ball/flow/result.py (a NarrationGroup carrying a headline), as a
  separate commit for review; do not paraphrase in the frontend.
- The picture slot on the right for the challenge and the shot
  pictures (PROMPT_PICTURES as now).
- A refusal rides on the question it refused: a red-edged strip inside
  the box with the model's text and a Dismiss. See step 10 for the Law
  citation.
- The owed step (a restart caught the game mid-turn) is its own strip
  above the box with the whistle as the control (step 4 has the
  whistle).

Done when: every prompt fixture renders in the box, the four goldens
are untouched (they record the bot), and tests/test_web_app.py asserts
the banner text is the narration's own line for a resolved maneuver, a
saved shot and a steal.
```

---

### 4. Answering on the board: the objects, no coloured buttons

**Prompt.**

```text
Remove the coloured button rows from webapp/present.py and the page and
answer prompts on the objects instead, exactly as the canvas shows on
rows 2, 3 and 5. present.py still builds one control set per
PromptKind from PendingPrompt.options and nothing else; what changes is
that a control now names the object it lights (a player id, a space
index, the ball, a goal, the die, the whistle, the time-out tile, a
card key) and its chip text, and the page lights that object and
attaches the click. Keep a hidden list of the same controls for
keyboard use (number keys in the order the options give, Enter, Esc).

The mapping, kind by kind (all read off the option dataclass named):
- ball_handler_selection, run_back_player, ball_recovery,
  halftime_extra_token, shooter_choice, shootout_pick: light the
  meeples in PlayerOptions.player_ids; chip = the distance's cost as
  the token image and count where distances says so.
- maneuver_challenge, loose_ball_pick (SendOptions): light the
  candidates with their cost chips; "send nobody" is clicking the ball
  itself, lit with "let it through" / "send nobody", only when
  may_decline.
- player_action (TurnOptions): the ball on the handler lights for
  "maneuver"; the goal at the attacking end lights for "shoot" only if
  the option is present; the time-out tile lights only if present. The
  box lists which of the three are lit and, in muted text, why the
  others are not, using the option's own note where one exists.
- run_back_space, and the DistanceOptions kinds (high_pass_choice,
  setup_pass_choice, setup_pass_push_back, dribble_advance_choice,
  dribble_burst_choice), fly: light the landing spaces (SpaceOptions /
  DistanceOptions turned into spaces by board.py, which already knows
  where a distance lands; if it does not, add that reading to the
  options in d12ball/prompts.py as its own commit) with a chip saying
  what landing there means, as the option's text; "put it out of play"
  is dragging the ball off the far end, with a ✕ that appears there
  when may_pass_out.
- low_pass_choice: light each receiver; a space with several receivers
  lights the space and asks in the box which one.
- speed_delta_choice: a row of d12 faces for the targets in the box
  (no board object).
- skill_test, loose_ball_skill_test, injury_test, own_goal_roll,
  shootout_test, score_attempt (RollOptions): a large lit d12 in the
  box; clicking it rolls. Before-the-die choices (Overdrive, Boost)
  light a ⚡ on the meeples the options name. score_attempt's "back"
  is the neutral control.
- coaching_offer, mind_pull, smooth, join_the_ball, force_test,
  set_up_attempt (DecisionOptions): light the object the decision is
  about (the meeple, the ball) for "take"; the decline is the neutral
  control, worded from the option.
- maneuver_action (ManeuverOptions): the cards, step 5.
- coaching_hub: step 6. shootout_order: step 7.
- tutorial_continue: clicking anywhere on the note.
- game_over: the REMATCH mark in the box (a link to the rematch's
  room).
The whistle: one control for Done (coaching_hub), Start the game
(lobby), Lock the order (shootout_order) and Pick it up (the owed
step). A pea-whistle silhouette, gold on a dark disc when the position
allows it, grey when it does not, with the refusal note under it from
finish_refusal or the setup method's refusal.

The neutral control: one outlined style (1px #3f4147, text #dbdee1, no
fill) for everything left: Back, Pass/decline, Start again, Copy link,
Send, Rename.

Done when: tests/test_web_app.py presses every prompt fixture through
the new controls and reaches the same Action as before (the fixtures
in tests/prompt_fixtures.py cover every kind); a new test asserts that
every control present.py emits names an object or is the neutral
style, and none carries a colour; and the AI answer tests still pass.
Record the mapping table above in docs/design/web-app.md.
```

---

### 5. The hand, the reveal and the challenge

**Prompt.**

```text
The maneuver pick (maneuver_action) and what follows, as on the Hand
and Reveal boards of the canvas.

- The hand is the printed maneuver cards (pictures.maneuver_card_png)
  as clickable images, 150px wide, in the question box; hover enlarges
  a card. Gambit cards are shown dimmed with the note "held only by the
  side behind" when ManeuverHand for the viewer's side does not hold
  them; the cards shown are exactly maneuver_keys for that side. A
  picked card gets a gold ring; the other side's pick stays face down
  (a card back) until both are in.
- The challenge picture beside the hand: the two pieces with their
  numbers, from dice_brief.maneuver_challenge_brief as now.
- The reveal: both cards face up with TIE or the winner between them,
  then the die (step 4) for a skill test, with the outcome banner
  (step 3) once rolled.
- An observer sees two card backs and the note that hands are turned
  over together.

Done when: the hand renders for a side holding three cards and a side
holding six, the observer view shows no faces, and the click reaches
driver.answer with the card's key.
```

---

### 6. The Coaching Choice on the board

**Prompt.**

```text
Replace the coaching_hub menus with the board itself, as on the
"Coaching Choice (setup), on the board" artboard. Everything offered is
CoachingHubOptions; the page adds no move of its own.

- Formation: a row of shape tiles (2-2-2, 2-3-1, 1-3-2, 3-2-1, 1-2-3)
  drawn as dots per zone from formations; the current one marked "now"
  and disabled.
- Substitute: drag a bench meeple onto the field player it replaces,
  or click the two in turn; only pairs the swaps/outgoing_ids/
  incoming_ids allow light up; the budget note ("setup: unlimited ·
  halftime: 2 · a new play: 1") is the option's, not the page's.
- Change zones: click two of your players (only pairs in swaps light).
- Move within a zone: drag a player to a lit space (repositions).
- Undo: a ↶ in the field's corner and Esc, if the service exposes an
  undo; if it does not, leave it out and say so in the PR rather than
  faking it client-side.
- Done: the whistle, dark with finish_refusal's text under it until
  the kickoff space is covered.

Done when: the tutorial and the setup fixtures reach kickoff through
the new controls in tests/test_web_app.py, and every drag has a click
equivalent for keyboard users.
```

---

### 7. The shootout order

**Prompt.**

```text
The secret order (shootout_order), as on the Shootout artboard: six
numbered slots in the question box, the coach's players from
ShootoutOptions dragged into them (click-to-place as the keyboard
path), drag between slots to reorder, Start again as the neutral
control, and the whistle to lock, dark until the sixth slot is filled.
Only the viewer's seat sees the panel; an observer and the other coach
see "<team> has set its order" and nothing else, and the order is
never sent to a browser that may not see it (check what the wire
carries today and cut it server-side if it leaks). The sudden-death
pick (shootout_pick) lights the meeples.

Done when: tests/test_web_app.py locks an order and reaches the same
Action as before, and a test asserts the other seat's wire state does
not contain the order.
```

---

### 8. The bench

**Prompt.**

```text
Replace the bench popover with the sideline under the field, as on
every play screen: two rounded boxes per team, bordered in the team's
colour at low alpha, BENCH ("may come on") and BACK BENCH ("off for
the game"), holding the meeples as step 1 draws them, with the same
badges, and the hover card. Which players are on which bench is the
record's reading (the two rows the popover already had); the page
groups nothing itself. In a Coaching Choice the bench meeples that may
come on light up (step 6).

Done when: the sideline renders for a game with an injured player on
the back bench and the Teams tab's rows say "bench" / "back bench" to
match.
```

---

### 9. The front door and the table

**Prompt.**

```text
Rework index.html and the pre-kickoff table to rows 1 of the canvas.

The front door: a left column with the name field (edit in place), a
dashed gold "+ A new room" card that creates a room, and under it two
ticks: "Dinky in the other seat" and "the tutorial". The first is
create_game followed by seat_ai on Coach 2; the second sets the
tutorial setting through configure; both are existing service methods,
called in sequence by the page, no new record field. Then a Reading
Room box (step 10) and the leave link. The right column: YOUR ROOMS as
cards (room number, topic, a status chip, the seats with team dots,
mode and clock), a gold edge on a room where it is your move, and
ROOMS WITH A SEAT FREE below. Clicking a card enters the room.

The table (before kickoff):
- Two seat cards: label, the sitter's name large (or "Empty seat ·
  click to sit"), YOU / AI chips, the colour-team swatches and the
  species-team swatches with a pair greyed where teams_open_to says
  so, the picked team's line, and the seat moves as drags: drag a name
  from the sideline into an empty seat, drag Dinky in, drag a coach out
  (admin, with the confirm), drag yourself out to leave. Every drag has
  a click equivalent.
- Settings as gold pills (the current value gold, the others outlined)
  over GAME_SETTINGS / open_settings, with the notes the record gives.
- The question box: the whistle for Start the game, dark with the
  refusal until both teams are picked; then the coin, the bot's own
  gold coin art, clicked to flip; the result face large and the other
  face small and dimmed; then "Click the goal you want to defend" over
  a miniature field whose two ends are the two answers
  (choose_home_or_visiting).
- The sideline strip: who is watching, Dinky waiting to be dragged in,
  Copy the room's link / Become admin / Close this room as neutral
  controls.
- The top bar's identity as one pill, vertically centred: "You are
  Coach 1" (gold edge) before the toss, "You are the Home coach ·
  <team>" (team-colour edge) after it, "You are an observer" for the
  rest, with "Take the free seat" beside it when there is one. The
  room number and topic share a baseline.

Done when: tests/test_web_table.py drives a room from creation to
kickoff through the new controls, including the two ticks, and a
kicked coach's confirm.
```

---

### 10. The sidebar tabs and the reading room

**Prompt.**

```text
Four tabs in the 380px sidebar: Log, Chat, Teams, Rules, with a dot on
a tab that has news (red) or your move (gold).

- Log: entries with a coloured left edge by kind (a new play blurple,
  a goal gold, a roll grey, the clock faint, a line the panel line),
  the minute as a small heading when it changes, words only, as now.
- Chat: as now, in the new chrome.
- Teams: both rosters as tables (role badge and name, OFF, DEF, the
  exhaustion as one token image per point, condition emoji, the space
  or bench / back bench), hover a row for the card.
- Rules: the Charter in the page. Read docs/living-rules.md through
  d12ball/rules_doc.py (the same reader the two rules commands use),
  list the 21 Laws by their headings, expand one to its text with its
  subsections, a search box over the text, and chips to switch to
  Learn to Play (docs/learn-to-play.md with its figures from
  docs/rulebooks/figures/) and to References: the six basic cards as
  images, the roles table and the four species from the same data the
  cards are drawn from. No PDF anywhere.
- A full-width Reading Room page (route /rules) with the table of
  contents on the left, the Law text in the middle and the references
  on the right, linked from the front door and the Rules tab.
- Refusals cite their Law: this needs the model to say which Law a
  RuleRefusal comes from. Propose it as an optional field on
  RuleRefusal set at the raise sites, in its own commit, reviewed as a
  model change; the page links the citation into the Rules tab. Do not
  map refusal text to Laws in the frontend.

Done when: the Rules tab shows the current living rules (a test reads
one heading through rules_doc and finds it in the page), the reading
room renders, and the Teams tab's numbers are board.py's.
```

---

### 11. The phone

**Prompt.**

```text
The one-screen phone layout (≤960px), as the two phone artboards in
row 4 show.

Portrait: the top bar, a compact jumbotron (teams, score, minute,
half, the ball's d12), then the field kept horizontal and whole, fitted
to the width: the seven spaces with small meeples (30px, initials and
species only, badges scaled), the goals as narrow slabs, the zone names
above, the range bars below, pinch to zoom; hold a meeple for its card
and name. The move is a bottom sheet with the state tag, the ask, and
the lit options repeated large enough to tap (the same meeples, at the
desktop size, with names) so nothing needs zooming; tabs Move / Log /
Chat / Teams / Rules along the sheet's foot with the news and your-move
dots. Landscape: the desktop field whole with the score and clock in
the top bar and the move as one slim strip under the field, the tabs
as pills in that strip. Fans stack as on the desktop at the smaller
steps.

Done when: the page is usable at 390×844 and 844×390 in a browser (put
screenshots in the PR), every lit option on the field also appears in
the sheet, and no meeple leaves its space.
```

---

### 12. Full time

**Prompt.**

```text
The final board, as the "Full time" artboard: the outcome banner with
the result and who scored the winner (narration), a statistics block
beside it read from d12ball/stats.py over the match's events (goals,
shots, maneuvers won, skill tests, exhaustion taken, time outs, per
side, in each team's colour), the REMATCH mark that posts /rematch and
links to the new room, "Back to the rooms", and "the whole log as
text" (a plain-text export of the room's log lines, the model's
narration as it was shown). The jumbotron's note reads "Final · <score>,
shootout <score>" when there was one.

Done when: a finished game fixture renders the block with stats.py's
numbers and the rematch link points at the room the service created.
```

---

## What is not in these prompts, on purpose

- Nothing changes the save format or MATCH_SAVED_FIELDS.
- Nothing changes the Discord frontend; where a step grows a prompt's
  options, the cog reads the new field only if it needs it, and the
  goldens stay untouched.
- The two candidate model changes (a NarrationGroup headline in step
  3, a Law on RuleRefusal in step 10) are proposed inside those steps
  for the author to accept or refuse, never slipped in.

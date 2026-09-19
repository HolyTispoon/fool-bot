# Formations and occupancy

Design notes for fool-bot; the map is [CLAUDE.md](../../CLAUDE.md), the rules are [living-rules.md](../living-rules.md).

## Formations and occupancy

Basic mode has five shapes -- **2-2-2, 2-3-1 and 1-3-2** on every board, plus
**3-2-1 and 1-2-3** on the nine-space board -- read from a coach's own goal
forward, six cards either way. **Every team is dealt 2-2-2**, and a coach
changes shape only in a [Coaching Choice](coaching-choice.md#the-coaching-choice) -- of which
setup is now one, so a game need not kick off in the shape it was dealt.

**Which board plays which shape is data, not geometry.** `board_sizes` on a
shape in `basic_rules.json` lists the boards it may be picked on, and leaving
it out means every board. It is not "a shape that would stack is refused":
2-3-1 and 1-3-2 overfill board 6's midfield and are played there anyway. 3-2-1
and 1-2-3 need a goal zone three deep, and being board 9's alone is the
author's call (2026-08-12 in the rules log). `BasicRuleset.formations_for_board`
is the only reading of it -- `D12Ball.available_formations` for a match, which
is what the Formation menu builds from and what `current_formation` names a
side's shape out of -- and `BasicRuleset.formation_shape` is the matching
refusal, so a shape offered in one place cannot be refused in another.
**A formation is named by its counts**, which `load_basic_ruleset` checks; that
is what lets the printed team board list the names and nothing else.

**Stacking is board-dependent.** Three in midfield fits board 7 and board 9 one
card a space; only board 6, whose midfield has two spaces, makes 2-3-1 or 1-3-2
overfill a zone. Board 9's two shapes stack nowhere -- its zones are three
spaces deep and neither puts more than three cards in one. So the occupancy
machinery below is exercised on board 6 and by `/coach`, not by the default
board -- render a sample at `--board-size 6` to see a stack.

**The deal spreads a goal zone's pair and packs midfield**, which is
`setup_space_order` and only ever visible on board 9 -- the one board whose
zones are deeper than 2-2-2 fills them. A goal zone's two cards take its two
end spaces and midfield clumps toward that side's own goal, so home deals H1,
H3, M1, M2, V1, V3 (see "Setup" in the living rules, and the 2026-08-12 entry
in the rules log). The clumped half is not an oversight: the kickoff space is
in midfield and **every** arrangement has to cover its own side's (2026-08-16,
and before that only the side kicking off), so spreading two cards over a
three-space midfield would empty the middle and hold the coach in the window
(`coaching_finish_refusal`). That is why the function takes the zone. Packing
from a side's own end is what makes the deal and all five formations satisfy
that rule for free. **This is the standard deal only**; a formation change re-deals through
`formation_space_order`, which packs and then stacks.

- **The shapes live in two places on purpose.** `Formation` in `d12ball/game.py`
  names them; the counts and the boards they are played on are in
  `basic_rules.json`, with the rest of the ruleset data. `load_basic_ruleset`
  checks the two agree, so neither can drift alone.
- **Occupancy is a coverage rule, not a limit** -- see "Occupancy" in the living
  rules. `MatchState.placement_spaces_in_zone` is the whole of it: a team's
  uncovered spaces in a zone, or every space once its other meeples cover them
  all. It discounts the meeple being moved, since the space it is leaving is
  about to be uncovered. **The run back is now its only caller.** A Coaching
  Choice satisfies coverage by construction instead of by checking (see
  `position_meeple`), which is why it can offer every space of a zone.
  `open_spaces_in_zone` still means "spaces this team has not covered" and is
  what gates `crowded_candidates` -- see "Who runs back" in [possession-and-turnovers.md](possession-and-turnovers.md).
- **A formation change re-deals the whole side, and nothing else does.**
  `D12Ball.formation_placement` orders the six by defensive skill and
  `formation_space_order` gives each a space, working outward from the coach's
  own end; `MatchState.deploy_side` puts cards and meeples down together, so
  nothing partial ever reaches the match. A coach who wants a particular card
  somewhere particular moves it afterwards. This replaced an assignment keyed
  by *area* (`own_goal` / `midfield` / `opponent_goal`) that a coach filled one
  select at a time -- `zone_for_area` and `SETUP_AREAS` survive from it, and are
  still how a shape is read from a coach's own end.
- **Board 6's midfield is the only zone whose stack space is a judgement call.**
  A surplus goes on the middle space of a three-space zone, or the
  centre-nearer space of a two-space one -- except there, where the two spaces
  straddle the centre. `formation_stack_space` breaks that tie toward the
  coach's own goal, which is the author's call and the only stack the three
  basic shapes can produce.
- **A Low Pass into a stack asks who receives it.** Several teammates on one
  space is ordinary under a stacking shape, and the receiver is what a Winger's
  set-up hands the shot to, so `low_pass_receivers` lists them and
  `LowPassReceiverView` puts the choice to the passer. `low_pass_candidates`
  still names one player per destination -- that is a button label, not the
  receiver.
- **Both prompts are posted over the field strip**, which is one upload for
  the two of them -- see
  [Choosing a distance, and the field under it](maneuver-prompt.md#choosing-a-distance-and-the-field-under-it).

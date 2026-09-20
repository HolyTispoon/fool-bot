# Shooting: range, the wall, and the overshot High Pass

Design notes for fool-bot; the map is [CLAUDE.md](../../CLAUDE.md), the rules are [living-rules.md](../living-rules.md).

## Where a shot may be taken from

A team may only shoot from within **shooting range** -- see "Score attempt" and
"Field, direction, and shooting range" in the living rules.
`MatchState.can_attempt_score` is the
whole rule, over `BoardState.is_in_shooting_range`.

- **Shooting range is not a zone**, and is deliberately not called a half
  either. It is measured from the middle of the board and cuts across midfield,
  so it is the far part of midfield plus the goal zone a team attacks -- three
  spaces of seven on the standard board, which is why "half" was the wrong word
  for it. On an odd-sized board (7 and 9) the middle space is in *nobody's*
  range, which is why the geometry compares doubled indices against the last
  index rather than dividing. That space is also the kickoff space, so no
  restart ever begins in range.
- **A set-up's shot obeys it too.** A scoring opportunity sends a player into an
  ordinary score attempt, so what it buys is the shot out of turn, not a shot
  from anywhere. Only the 2-space High Pass's set-up still checks it --
  `can_attempt_score` over `high_pass_receiver_candidates`, in `high_pass_step`
  -- because it is the only set-up whose landing space can be short of range.
  There used to be a `set_up_shot_candidates` wrapping the two, which never had
  a second caller.
- **A 2-space High Pass that lands short of range is still received.** The range
  rule takes away the shot, not the catch. The set-up branch and the long-pass
  contest are the same landing space asked two different questions, so a pass of
  2 that is refused a set-up has to resolve as an ordinary pass rather than fall
  through to a contest it has never had to win.
- **An overshoot is the set-up the rule cannot bite**, whichever maneuver made
  it. A Deflect's puts the ball on the space closest to the offense's own
  goal and a High Pass's on the space closest to the goal they attack; both are
  as deep into the shooting team's range as the field goes. So neither puts a
  range check over its candidates -- a branch that can never be taken reads as
  if it could.
- **Nothing gates `begin_score_attempt` itself.** The rule is enforced where the
  shot is *chosen*: `PlayerActionView` omits the button (and `build_turn_prompt`
  says why), `choose_action` refuses a stale click, `DinkyAI` only ever shoots
  from the scoring space, and the 2-space High Pass's set-up asks
  `can_attempt_score`.
- **The board image draws where range begins**, in `draw_shooting_range_band`
  -- a labelled bracket under the field, one for each side's range and (on
  board 7 and 9) a third over the space in nobody's. It used to be a dashed
  line drawn straight through the spaces, which marked the same edge but said
  nothing about what it meant; the labelled bracket is the same marking
  `boards.py`'s printed field board already carried (`draw_shooting_ranges`),
  so the two now agree by construction rather than by two separate drawings
  of the same rule. `shooting_range_bands` reads `is_in_shooting_range` a
  space at a time, the same reading the print board's own version makes, so
  neither can drift from the rule the bot enforces. The rule is positional and
  the board is where both coaches read position.

## What a shot is up against

A defender sharing the ball's space adds their whole defensive skill; a
defender anywhere else between the ball and the goal adds half of it,
rounded up -- see "Score attempt" in the living rules.
`ShotDefender.value` in `d12ball/components.py` is the whole rule.

- **The halving is per player, not over the group's total.** Two 5s in
  the way add 3 + 3 = 6, where halving their sum would give 5. The two
  readings agree whenever at most one defender rounds up, which is most
  positions -- so a change here can pass a playtest and still be wrong.
  It is the author's, confirmed 2026-08-11.
- **`MatchState.defenders_between_ball_and_goal` pairs each defender
  with whether they are on the ball**, because it is the only thing that
  knows: it walks the spaces from the ball outward, and by the time a
  caller has the skill in hand the position is gone.
  `D12Ball.intervening_defenders` turns that into `ShotDefender`s, and
  the roll and the image both read `.value` -- **neither may go back to
  summing `defense`.**
- **The image says which half is which.** A defence of "6 + 3 + 1" names
  no term, so each defender's portrait carries the value they
  contribute: a solid badge on the ball, an outlined one and the skill
  it was halved from beyond it, under a label per band. It rides on two
  optional fields of `ChallengeSide` (`contribution` and `halved`), so
  the maneuver challenge -- which shares `render_matchup` -- is drawn
  exactly as it was.
- **`halved` cannot be inferred from the two numbers.** A defensive
  skill of 1 halves to 1, and drawing that as a full value would say the
  defender is on the ball when they are not.

## A High Pass that runs out of field

An overshot High Pass offers a shot **or** a contest for the ball, and pays the
ball speed modifier against both -- see "High Pass" and "Ball speed" in the
living rules. `MatchState.pending_high_pass_overshoot` is the flag and
`MatchState.ball_speed_modifier` is the only place the sign is decided.

- **A passer never receives their own pass**, which is the whole of
  `D12Ball.high_pass_receiver_candidates` -- `scoring_opportunity_candidates`
  less `active_player_id`. It is asked by all three High Pass branches (the
  overshoot's set-up, the ordinary 2-space one, and the long-pass contest behind
  both), because they have to agree on who the pass reached and the occupant
  list is in no particular order. It can **only bite on a pass clamped to 0
  spaces**: a High Pass moves the ball and not the handler, so nowhere else is
  the passer still standing on it when it lands. Stating it as a rule about
  every High Pass rather than about that one case is deliberate -- see the
  2026-08-12 entry in the rules log.
  - **That is the one overshoot that can set nothing up while the offense is
    still on the ball, and since 2026-08-24 it is not a free ride either.** It
    is neither loose (the passer is standing there) nor a contest (there is no
    receiver to fight for what they never let go of) -- but with nowhere left
    to throw it and nobody to throw it to, that branch sends it out
    exactly as `setup_pass_out_step` already did, rather than letting
    `finish_maneuver_resolution` hand it straight back to the passer. The
    branch is read off `actual_distance == 0`, not `receiver_candidates`
    alone -- an ordinary loose ball landing on a genuinely empty space
    elsewhere on the field still goes through `finish_maneuver_resolution` as
    before. It is also why that function words a 0-space result rather than
    reporting "the ball moves 0 spaces forward", which no coach saw until this
    rule.
  - **It still costs High Pass's own 2 minutes**, which is why `high_pass_step`
    carries a `distance_moved` apart from the `actual_distance` the result
    reports. Every maneuver's clock cost is flat and distance-independent
    (2026-08-16) -- 1 for everything but High Pass, 2 for it -- so this is no
    longer a minimum bailing out a clamped throw; it is the same cost every
    High Pass pays, whatever it moved. **Every clock argument out of that
    function is the first**; only the wording reads the second.
- **A coach is only offered a distance that fits on the field.**
  `MatchState.high_pass_distances` drops any that would clamp, because a longer
  pass landing where a shorter one already would is that pass at a
  disadvantage -- negative modifier, contest owed. `D12Ball.high_pass_distance_options`
  wraps it with the handler's own maximum (the Fullback's 4), and is the single
  home three things read: the menu `HighPassChoiceView` builds, what the AI
  picks from, and `choose`'s refusal of a click on a menu the ball has moved out
  from under. Those buttons carry no message id, so an older prompt in the
  channel does dispatch.
- **Dinky throws to the furthest teammate it can reach, not simply the
  furthest** (2026-08-18). `MatchState.high_pass_receivers_at` is the
  lookahead -- the before-the-throw twin of `high_pass_receiver_candidates`,
  excluding the passer for the same reason -- and
  `DinkyAI.choose_high_pass_distance` falls back to the longest available only
  when no distance reaches anybody. It is not a rules change; it is that the AI's
  own maximizing was working against it, and
  [where the ball comes to rest](loose-balls.md#where-the-ball-comes-to-rest) sharpened the
  cost: a pass landing where the offense has nobody gives the ball up, so
  throwing as far as possible was giving it away as often as possible.
- **An overshoot is therefore only ever the no-menu case.** When even the
  shortest pass runs out of field -- the ball 0 or 1 spaces from the end --
  `resolve_high_pass` skips the prompt and applies the minimum distance
  directly, because 2, 3 and 4 are the same pass. `high_pass_distance_is_moot`
  is that test; it agrees with "`high_pass_distances` is empty" and exists
  because the moot check should not have to know the handler's role.
  **This is what makes `contest_on_decline` unconditional for an overshoot**: a
  chosen 2 can only overshoot from a position where no distance was offered, so
  the "a pass of 2 is received, full stop" rule and this one never meet.
- **`ball_speed_modifier` is the whole of the sign, and three sites ask it**:
  the score attempt's roll, the image that composes it, and the long-pass
  contest in `LooseBallSkillTestView.roll`. Each used to halve `ball.speed`
  itself. The fourth site is deliberately left alone -- the modifier a *defense*
  adds to a maneuver skill test it won with Steal Intercept, which is settled
  before any pass is thrown and is not the offense's to lose.
- **Every detail string is `:+d`**, because a modifier that can be negative can
  no longer be printed under a hardcoded `+`.
- **The flag is set only when a set-up is actually offered**, in
  `offer_overshoot_set_up`. An overshoot with nobody from the offense on the
  landing space has no shooter, falls through to the ordinary loose-ball paths,
  and would carry an inert flag for the rest of the turn if it were set earlier.
- **It is persisted**, unlike the overshoot test itself, which is a local read of
  `relative_flat_index` against the requested distance the way Deflect
  reads its own. Both things the flag governs outlive the effect that sets it: a
  score attempt is a view a restart re-attaches, and the contest is rolled a
  click later. `reset_maneuver` clears it with the rest of the turn.
- **The shot and the contest are two halves of one choice.** Declining an
  overshoot lands in the long-pass contest, still with the modifier against it;
  nothing about an overshoot settles the ball quietly.
  `begin_high_pass_contest` is that contest, reached both from the ordinary
  3-or-4 path and from `decline_scoring_attempt(contest=True)`. Its model
  twin is `high_pass_contest_step` in `d12ball/flow/arrival.py` since Phase
  4, two lines over `loose_ball_step`; the offer that precedes it is
  `scoring_attempt_choice_step` in the same module, and the set-up prompt is
  a follow-on rather than a `PendingPrompt` for the reason below --
  `contest_on_decline` rides on the view, so `SetUpAttemptChoiceView` has no
  `PromptKind` for a restart to come back through.
- **`contest_on_decline` rides on the view, not on the match.** By the time the
  decline arrives, an overshot pass and an ordinary 2-space one have left the
  match in the same state, and `SetUpAttemptChoiceView` was already the one view
  a restart cannot reconstruct -- so this adds nothing new to that gap. It also
  relabels the decline button, because "resolve as a normal pass" would be a lie
  there.

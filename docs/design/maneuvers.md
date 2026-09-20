# Maneuvers: keys, gambits, who wins, and every roll

Design notes for fool-bot; the map is [CLAUDE.md](../../CLAUDE.md), the rules are [living-rules.md](../living-rules.md).

## A maneuver's identity is not its printed name

`match.offense_maneuver` and `defense_maneuver` hold a **key** --
`low_pass`, `double_team` -- and never a display name.
`maneuver_key` in `d12ball/components.py` is the slug, and every
dispatch table, button custom_id and comparison in the cog and the
views is keyed on it.

It used to be the name. That made a rename upstream a code change and
put a display string in every saved game, and the author renamed the
basic D2 card from "Steal Intercept" to "Steal" on 2026-08-18 -- which
under names would have silently broken a dozen comparisons, five
tutorial rails and every game saved mid-turn.

- **`legacy_maneuver_key` translates a game saved before the keys.**
  Almost every name slugs straight to its key, so only the one that
  does not is written down. Same tolerant shape as `player_board` and
  `tie_mode`: nothing writes a name any more, so it dies out on its
  own. Don't add a migration pass, and don't drop it until no
  half-finished game can predate the change.
- **`RulesEngine.maneuver_name` is the only way back to a name**, and
  it is only ever for wording. A caller that has a key and wants to
  print it asks; a caller that wants to *decide* something compares
  keys.
- **Relations are by rank.** `ManeuverDefinition.defeats_rank`
  replaced `defeats`, because since the gambits each rank carries
  two cards -- the basic one and its counterpart -- and **rank alone
  decides** who wins (the author, 2026-08-18). Naming one of the two
  would be naming half a relation. `ManeuverCatalog.counterpart` is
  the pairing, looked up by rank rather than tabulated.
- **The importer resolves the sheet's `Defeats` name into that rank**,
  so the cycle is still data rather than something written into the
  code. It carries one alias -- the sheet renamed the row without
  rewriting its own four references to it -- which can be dropped once
  upstream catches up.

## Gambits

Six more cards, one per basic card's rank, turned on by
`GameMode.ADVANCED`. See "Gambits" in the living rules;
what is left open is in
[docs/gambit-matrix.md](../gambit-matrix.md).

**`RulesEngine.maneuver_tiers` is the only answer to who holds what**,
and the buttons, the hand image and the click that answers all read
it. Two things narrow it, and both are rules: a basic game is the
basic three, and **an unchallenged maneuver is always basic** (the
author) -- which is answerable at the moment a hand is drawn because
all three routes into the unopposed branch settle it before the
offense is prompted. That also makes declining a challenge a defensive
weapon rather than only a saving.

- **The outright rule is two questions about two cards**, not one
  about the matchup: `gambit_benefit_applies` (this card **won on
  the cards**) and `gambit_cost_applies` (this card **lost on
  them**) -- the author, 2026-09-07. `resolving_maneuver` asks the
  first and substitutes the basic counterpart when it answers no;
  `gambit_cost` asks the second.
  - **It replaced a single `advanced_effects_apply`**, which asked
    only whether the cards were decisive. That is right in every case
    but one, and the one is real: a decisive matchup whose card-winner
    is injured is settled by a skill test, and the *other* side can
    win it. Then the card resolving is the one that lost on the cards
    (it must not carry a benefit) and the card that lost the test is
    the one that won on them (it must not pay a cost). Asking about
    the matchup gave that pair both.
  - **A tie is the commonest case where nothing fires and is no longer
    the test**, which is the whole of the correction: the author's
    2026-08-19 wording made "not a tie" the decisive factor, and it
    was imprecise rather than wrong.
  - **`maneuver_side` reads the side off the match**, not off the
    card: a `ManeuverDefinition` carries no side, the catalog splits
    them, and the question is about this matchup anyway.
  - **Nothing is persisted for this**; it is read off the two stored
    keys, so a restart mid-effect answers the same way.
- **Each benefit is its basic counterpart parameterised, not a second
  function.** `apply_deflection`, `apply_steal`, `apply_pressure` and
  `apply_low_pass` each take a key and serve both cards on their rank.
  A change to what a deflection *is* reaches Clear for free, which is
  the point -- the two differ by a distance and a speed drop and
  nothing else.
  - **Low Pass's own resolution is not in the cog any more.**
    `d12ball/flow/effects.py`'s `low_pass_step` moves the ball, words
    it, charges a beaten Double Team, and decides between the ordinary
    tail and a Winger's set-up; `D12Ball.apply_low_pass` is four lines
    around it -- run the step, save, dispatch. `send_low_pass`,
    `low_pass_movement_note` and `pay_double_team_cost` went with it
    and are free functions there rather than cog methods. That is
    Phase 2 of docs/model-discord-split.md and the pattern the other
    eleven follow; the rule it settled is that the **step does not
    save and the wrapper does**, immediately, before dispatching. See
    "The model and the Discord layer" in CLAUDE.md.
  - **Both dribbles followed it (rank O2).**
    `dribble_advance_step` and `dribble_burst_step` are beside it,
    with `pay_clear_cost` moved down as a free function -- its only
    two callers were those two cards. Each ends by naming
    `FollowOnStep.OFFER_SPEED_CHOICE`, the ball-speed manipulation
    every dribble finishes on, which stays in the cog because
    *whether anyone is asked* is still Discord's decision: Dinky
    answers for itself and a tutorial beat holds the prompt behind a
    note. Nothing either card says changed.
    - **A beaten Clear's exhaustion is now saved.** The old
      `apply_dribble_advance` persisted and *then* called
      `pay_clear_cost`, which charges two tokens and re-tests the
      Exhausted threshold -- so both writes happened after the save
      and the next click reloaded a defender who had never been
      charged. Moving the whole effect into the step, with the
      wrapper saving after it, is what fixes it; it is the bug
      principle 9 is written for, and the rule is unchanged.
  - **Both steals followed them (rank D2).** `steal_step` is the
    whole of a Steal and of an Intercept -- the two differ by the
    sign of the carry and nothing else, so they are one function and
    a `direction`, the way Low Pass and Skilled Pass are one function
    and a `key`. `take_ball_by_steal` and `steal_result_text` went
    with it as free functions, and `D12Ball.apply_steal` is four
    lines around it. Nothing either card says changed.
    - **It is the first effect to hand off to the spine**, so it
      named two new `FollowOnStep` members:
      `BEGIN_RUN_BACK`, carrying `speed_choice_after=True` (a steal
      owes the ball-speed choice but does not reach
      `offer_speed_choice` directly -- `finish_run_back` offers it,
      once everybody is back), and `BEGIN_SHOOTER_CHOICE`, for the
      Intercept that overshoots into a scoring opportunity.
      `begin_run_back` and `begin_shooter_choice` themselves did not
      move.
    - **Two persists became one, and nothing was being lost.**
      `take_ball_by_steal` saved inside itself and the Skilled Pass
      cost branch saved again on top of it, so one branch wrote the
      file twice and the other once; both writes already carried
      everything. Unlike the beaten Clear above, this is the rule
      rather than a fix -- worth saying so, because the two read
      alike in a diff.
    - **One ordering is open.** An Intercept that overshoots returns
      before `gambit_cost` is read, so it collects no beaten
      Skilled Pass. Whether that is the rule (nobody goes back in
      position, so the free pass has no moment) or an oversight is
      the author's; the behaviour is preserved exactly and the
      question is written out in PR #233.
- **Every cost bites inside the winning maneuver's own resolution**,
  which is why there is no cost dispatcher. `gambit_cost` names the
  card that was beaten and the winner's handler asks it: Clear's 2
  exhaustion and Double Team's shove are charged by the card that beat
  them, Intercept's uncontested reception is a branch of the High
  Pass, and Dribble Burst's is the first exception to "every turnover
  resets ball speed to 1". A generic "and then pay the cost" step
  would have to know where inside each effect it belonged, which is
  the thing the handler already knows.
- **`pending_effect_continuation` is what lets an effect reach past
  its own maneuver**, as `{"kind": ...}` -- the same shape
  `pending_injury_resume` uses and for the same reason. Two need it:
  Setup Pass sets the ball's speed and *then* picks the pass out, and a
  beaten Skilled Pass hands the defense an unopposed Low Pass once the
  steal has settled. A speed choice had always been the *last* human
  step of an effect, leading straight into
  `finish_maneuver_resolution`; `continue_effect` is the branch.
  - **The record is cleared by whatever applies the step, not by the
    dispatch.** A continuation is one more prompt and a coach may take
    hours over it, so between dispatching and the click that answers,
    this field is the only thing on the match saying what is owed --
    which is why `build_effect_choice_view` reads it *first*, ahead of
    the winner. Clearing it at dispatch (which is what
    `finish_time_out` does with `pending_time_out`, for a flow with no
    prompt left in it)
    would leave a restart in that window putting the speed choice back
    up and letting a coach answer it twice.
  - An unrecognised kind falls through to the ordinary end of a
    maneuver rather than stranding the turn -- and *that* branch does
    clear it, or the next speed choice in the game would find it still
    set.
- **`pending_double_team` is the two defenders, not a flag.** A won
  Double Team leaves both challenging the next maneuver, each adding
  their defensive skill, and what the following turn needs is *who* --
  a flag would leave it re-deriving "the nearest teammate" off a board
  that has moved since. `announce_new_play_reset` clears it, which is
  the one thing the card says ends it; `reset_maneuver` deliberately
  does not, since that runs at the end of the turn that set it.
- **"The teammate closest to where the play started" is read before
  anything moves**, by both the benefit and the cost. A moment later
  the handler has been shoved back two and the ball with them, and the
  nearest defender to *that* space can be somebody else. The cost's
  caller reads it before the pass moves the ball and passes it in,
  which is why `pay_double_team_cost` takes a partner rather than
  looking one up.
- **A Setup Pass is gated on the field, not on the roster** (the
  author, 2026-08-25). `RulesEngine.setup_pass_distances` offers 1 and
  3 -- and a Fullback's 4 -- whenever the space they land on is on the
  board, and **0 alone still needs a teammate**, since it means one
  sharing the passer's own space and a passer never receives their own
  pass. It used to offer only distances that reached somebody, which
  read the card as a set-up that either happens or does not and left a
  passer with nobody ahead of them unable to play it at all.
  - **A pass landing on nobody settles where it lands**, exactly as a
    Deflect's does: `apply_setup_pass` hands it to `begin_loose_ball`,
    which since 2026-08-26 settles every arrival by what is standing
    there -- see [Where the ball comes to rest](loose-balls.md#where-the-ball-comes-to-rest).
    It pays `SETUP_PASS_CLOCK_COST` there, the card's flat 2 minutes,
    however far the ball actually travelled.
  - **That leaves one position a Setup Pass goes out from, and it is
    still a fourth `new_play=True` call site.** The card cannot
    overshoot, so `apply_setup_pass_out` is reached only where nothing
    is on the menu at all: the passer on the very last space of the
    field -- the one place even 1 space runs off the end -- with no
    teammate beside them. The other three call sites are the score
    attempt, a conceded own goal and the out-of-bounds loose ball.
  - **Dinky answers the distance through `choose_high_pass_distance`**,
    which is the same question now that a bad pass costs the ball: the
    longest that reaches a teammate, otherwise the longest available.
    A second policy would only be the same one written twice.
- **A role ability is inherited by rank, and what carries is the rule
  rather than the number.** Each sentence in `players.json` was written
  against one card and states a number, so read literally three of them
  are nonsense on the gambit that inherits it: a Fullback's "ball
  goes back 2" is a *reduction* on a 3-space Clear, its "high pass up to 4"
  is a fourth number against a card offering 0/1/3, and a Playmaker's
  "may advance 2" was no bonus at all on a run to the end of the field.
  The author settled all three on 2026-08-19 -- **the Fullback's
  ability is +1 distance** (High Pass 3->4, Deflect 1->2, Clear
  3->4, Setup Pass gains a 4), and **the Playmaker's is one exhaustion
  token off a Dribble Burst**, which is the only ability that reads
  differently on the two cards of a rank. The Midfielder's +3 and the
  rank-D2 ball speed modifier were already uniform and needed no
  ruling.
  - **The Playmaker's stayed on the cost when the burst was bounded**
    (the author, 2026-08-26). The 2026-08-19 reading turned on there
    being no distance left to add to; a run of up to 4 has one, and the
    ability is still a token off rather than a fifth space. So the
    distances a Playmaker is offered are everybody's, and the discount
    comes out of the total in `apply_dribble_burst` -- named once
    beside the run rather than subtracted from each button's price.
  - **A Fullback's extra space is distance, not speed.** A Block
    Deflect of 2 has always cost 1 speed, so a Clear of 4 still costs
    3. `apply_deflection` keeps `speed_drop` as the card's own number
    rather than deriving it from the distance -- written the other way
    it read correctly until the Fullback was let near a Clear.
  - **The three cannot be matched out of the ability sentences and
    cannot live in `maneuvers.json`**, which the sheet import rewrites
    whole. They are `EXTRA_NOTES` entries in `d12ball/cards.py`, which
    say what the ability does *on the card it is on* -- the same escape
    hatch Steal's ball speed modifier uses, and for the same reason.
- **Dinky rolls its rank as it always has and picks the tier at
  random.** That is not a policy and is not meant to be one: an
  gambit carries a cost as well as a benefit, and weighing the
  two is judgement, which Dinky makes none of. The alternative was
  Dinky never playing a gambit, which leaves half of advanced
  mode unreachable in a solo game.
- **`EveryMatchupResolvesTests` is the guard worth keeping.** It walks
  all thirty-six pairings on all three boards through the real
  `resolve_maneuver`, for two coaches and against Dinky, and asserts
  almost nothing about what happens. Twelve cards reached from four
  directions apiece is a lot of branches nobody would think to build a
  fixture for; it caught two real bugs the day it was written.

## Who wins a maneuver

**`D12Ball.settled_maneuver_winner` is the only answer to that**, and it
returns the winning maneuver's **key** or `None` when a skill test still has to
decide. Three call sites ask it and none of them may go back to reading
`maneuver_catalog.resolve()` on its own -- see "Injured players" in the living
rules for why the ranking is no longer the whole story.

- **Injury moves wins in both directions.** A decisive maneuver owed to an
  injured player is downgraded to a skill test they have to win, and a tie
  against exactly one injured participant is their automatic loss with nothing
  rolled. So the ranking alone both over- and under-reports a winner, which is
  why one predicate rather than a check at each site.
- **Two of the three callers are restarts.** `on_ready` uses it to decide
  whether the pending prompt is a `SkillTestView`, and `build_effect_choice_view`
  to decide whether an effect is pending at all. Both used to ask whether the
  ranking was a tie, which after a restart would have offered a skill test
  nobody owed, or an effect choice for a test that had not been rolled.
- **`resolve_maneuver` branches on it, and on `outcome` only for wording.**
  There are four ways a maneuver lands and each reads differently, but which
  one is a *win* is not decided there.
- **An uncontested maneuver wins whatever the offense picked, injured or
  not** -- no opponent to be disadvantaged against, no challenge to lose. Same
  for a tie where *both* participants are injured: it is an ordinary tie,
  because the disadvantage is measured against a healthy opponent. Both cases
  postdate the disadvantage rule and both are the author's, confirmed
  2026-08-09.
- **Injury separately withholds the skill modifier in a *contest*** -- a
  different thing this predicate has nothing to do with. It changes totals, not
  winners, and lives in `LooseBallSkillTestView.roll`, which covers both the
  loose ball and the long High Pass. An injured contestant rolls the bare d12:
  their offensive or defensive skill is left off, and **only** that. Ball speed
  and role abilities still apply, and a maneuver's skill test and a score
  attempt are untouched -- so the Midfielder's +3 and the Striker's +3 are both
  paid to an injured player. This was got backwards once, as the loss of a
  role's bonus; the name for it is "skill modifier".

## Every roll is a coach's

**Nothing rolls dice on its own.** A skill test, a score attempt, a loose ball,
an own goal and an injury test all wait behind a button, and any coach in the
game may press it -- one roll by one player is still their roll to throw, and
letting either side press it is what keeps a solo game moving when the risk is
the AI's. The two that were not always like this were the one-sided ones: the
own goal and the injury test had no opposing roll to wait for, so the bot rolled
them itself and posted the answer.

Both are now places a turn can **stop**, and that is the whole cost of it:

- **What the roll was going to do next has to outlive the wait.** An own goal
  carries `pending_own_goal_distance`, the clock cost of the maneuver that
  risked it, which the roll spends whichever way it goes. Injury tests carry
  `pending_injury_resume`, which is the contest's continuation -- a maneuver's
  skill test resumes into its winner's effect, a loose ball (or the long High
  Pass borrowing its machinery) into its run back, with the two arguments that
  run back needs, and a shootout skill test into the next one. Neither is
  derivable after the fact: `settled_maneuver_winner`
  answers None while a test is owed, and the contest that knew the distance has
  already cleared itself. Both are persisted, and `reset_maneuver` clears them
  with everything else the turn set.
- **`pending_injury_tests` is a queue, and `continue_injury_tests` is its only
  exit.** A contest can owe two tests; they are asked one at a time and the
  continuation fires when the last one is answered. A test that turns out not to
  be owed -- the player is already injured -- leaves by the same door rather
  than returning, so this can never be where a turn stops for good. **Nothing is
  written when nothing is owed**: `begin_injury_tests` goes straight to the
  continuation, which is the common case and the one that has to stay free.
- **Both are checked ahead of everything else in `pending_turn_view`**, because
  both interrupt a turn whose own state is still set underneath them -- a skill
  test comes back with its challenger and both maneuvers in place, an own goal
  with the Pressure that risked it still live, and either would otherwise be
  answered by the maneuver branches.
- **The player is in the injury button's custom_id as well as in the queue**, so
  a coach who scrolls back to the first of two prompts cannot roll the second
  player's test with it.

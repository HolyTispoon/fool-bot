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

- **A renamed card may keep its key.** A key is the slug of the name,
  so a rename usually moves it, as Steal's did. The author renamed four
  cards at once on 2026-09-28 -- Dribble Advance, Skilled Pass, Dribble
  Burst and Setup Pass became Dribble, Pinpoint, Burst and Cross -- and
  moving their keys would have rewritten some six hundred references,
  every golden's saved position and every game saved mid-turn, for a
  string no player reads. `PINNED_MANEUVER_KEYS` holds the four old
  keys against the new slugs, and `maneuver_key` reads it, so the
  importer writes `dribble_advance` beside the name "Dribble". That is
  why the code's identifiers still say `dribble_burst_distances` and
  `setup_pass`: they name the key, and the key is the card's identity.
  The table does not die out the way the legacy one does. A future
  rename can go either way; the question is only what moving the key
  would cost.
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
- **The importer resolves the sheet's `Defeats` names into that rank**,
  so the cycle is still data rather than something written into the
  code. A basic row names one card and, since 2026-09-28, an advanced
  row names both on the rank it beats (`Pressure, Double Team`); the
  importer refuses a cell whose cards sit on two ranks.
  `LEGACY_MANEUVER_NAMES` is for a rename the sheet has not caught up
  with in its own references, and is empty while it has.

## Gambits

Six more maneuvers, one on each basic card's rank, turned on by
`GameMode.ADVANCED`. **Each is an advanced maneuver, and playing one
is making a gambit** (the author, 2026-09-27): the gambit succeeds
when the advanced maneuver wins on rank and fails when it loses, and
what the code calls a card's *benefit* and *cost* are the successful
and the failed gambit's outcomes. From 2026-09-20 until then the card
itself was called a gambit, which is why the identifiers say so --
`is_gambit`, `gambit_cost`, `withheld_gambits` --
and they stay: each reads as "the card a gambit is made with", and
renaming them is churn through the saves' neighbours for no reader.
An advanced maneuver is **the advanced version of the basic maneuver
on its rank**. Double Team *is* Pressure, advanced, which is why rank
alone decides and why a tie on the cards resolves as Pressure. "A kind
of" was the first wording and was too loose; the relation is one to
one, and `ManeuverCatalog.counterpart` is it. See "Advanced maneuvers
and gambits" in the living rules; what is left open is in
[docs/gambit-matrix.md](../gambit-matrix.md).

**`MANEUVER_TIER_GAMBIT` is `"advanced"`**, the `maneuvers` tab's
`Mode` column, and since 2026-09-27 the rules' word agrees with it
again. `MANEUVER_TIER_WORDS` is the one table between the value and
anything a person reads -- the card's corner label (ADVANCED
MANEUVER), the web page's hexagon, the References' tag on an advanced card
(`tier_word`, which said "Gambit" until 2026-09-28) and the reference
image's filename.
Unlike `legacy_maneuver_key` above, this pair is not a migration
waiting to die: don't "fix" the value.

**`RulesEngine.maneuver_tiers` is the only answer to who holds what**,
and the buttons, the hand image and the click that answers all read
it. Three things narrow it, and all three are rules:

- a training or standard game is the basic three;
- **an unchallenged maneuver is always basic** (the author) -- which
  is answerable at the moment a hand is drawn because all three routes
  into the unopposed branch settle it before the offense is prompted.
  That also makes declining a challenge a defensive weapon rather than
  only a saving;
- **the coin decides who may make a gambit** (the author, 2026-09-28),
  below.

### The coin

Until 2026-09-28 a gambit needed a reason -- a coach held their gambits
only while their team was behind. **Now the coin decides** (Law 19.3):
the toss winner keeps it, its holder may declare a gambit at any
challenged maneuver, and declaring hands it to the other coach. Being
behind survives as the condition for **answering** a gambit.

- **Four questions, all on the engine.** `coin_holder` (the match's
  `coin_holder` once a declaration has moved it, the toss winner's side
  before that, home for a game seated with no toss, `None` without the
  gambits); `may_declare_gambit` (the holder, a challenged maneuver,
  nobody declared yet); `behind` (the old gate's two readings, fewer
  goals or more Exhausted-or-Injured *on the field*, strictly more, so
  both teams can be behind at once); and `may_answer_gambit` (the other
  side declared, and this side is behind). `maneuver_tiers` reads them, with `gambit_answer_owed` (the other
  side was behind at the declaration and has not yet said how it
  answers): the declarer's hand is `(advanced,)`, the other side's
  `(advanced,)` if it answered with a gambit and the basic three
  otherwise -- **never six** (the author, 2026-09-28: "each side should
  be shown only 3 cards").
- **The answer is a question of its own, asked before the cards**
  (`PromptKind.GAMBIT_ANSWER`, choices `"gambit"` and `"basic"`, asked
  of `prompt.side`): the author, the same evening, "Player B should
  choose whether to counter gambit before either player can pick any
  cards". It sits in the chain ahead of `MANEUVER_ACTION`, so a card
  pressed meanwhile is refused (`GAMBIT_ANSWER_FIRST`). A counter sets
  aside a basic card the side had picked; keeping the basic cards leaves
  it to be confirmed. **A side not behind at the declaration is recorded
  as keeping its basic cards there and then** (`gambit_answer =
  "basic"`): behind is read as the maneuvers are chosen, and a score
  that moves later in the same maneuver -- an own-goal roll -- would
  otherwise put the question up in the middle of the resolution, ahead
  of the effect's own prompts. The re-swept golden found exactly that.
- **Five saved fields, one per thing that outlives a click**:
  `coin_holder` on the match (None until it first moves -- that is also
  the fallback for a save that predates it, so nothing migrates);
  `coin_face`, the face the coin landed on when it last passed (below);
  `gambit_declared_by`, `gambit_answer` and `pick_unconfirmed`, this
  maneuver's, all cleared by `reset_maneuver`. The coin carries through halftime and
  the shootout because nothing clears it.
- **A declaration withdraws the declarer's pick and puts the other's
  in question** (`MatchState.declare_gambit`). A pick in question is
  not in (`maneuver_selections_complete`); its coach confirms it (the
  choice `"confirm"`, `MatchState.confirm_maneuver`) or changes it for
  any card in the hand, whatever the other side has done. Picking the
  same card again confirms too.
- **The choices are on the maneuver prompt**, beside the card: `"gambit"`
  (`side` only) and `"confirm"` (`side` only), and the card is the empty
  choice with its `maneuver_key` (`REQUIRED_ARGUMENTS`). The hand says
  which applies -- `ManeuverHand.may_declare`, `declared`, `unconfirmed`
  -- so a frontend reads it rather than working it out. A refused
  declaration cites `who-may-make-a-gambit`.
- **A declaration puts the pick up again**
  (`declare_gambit_step` names `SEND_MANEUVER_ACTION_PROMPT`): both
  hands have changed, and a prompt whose buttons no longer match the
  hands is one a restart would not rebuild. On Discord that is a new
  message, and the old one is deleted -- see
  [maneuver-prompt.md](maneuver-prompt.md).
- **Everything a declaration or an answer does is said.** "X declares
  a gambit and hands the coin to Y", "Y answers with a gambit of their
  own" or "Y plays their basic cards" (at the answer, before the cards),
  "Y has confirmed their maneuver" -- the advanced cards have their own
  back, so none of it is a secret. "Y may confirm their maneuver or
  change it" is said only to a person: the AI answers first.
- **Nothing is persisted for being behind**, as before: it is read off
  the scoreboard and the field when the hand is drawn.
- **What the coin holds back is asked too, not worked out.** The web
  page shows a side's gambits dimmed beside a hand that does not hold
  them, so which cards those are is `RulesEngine.withheld_gambits` --
  the complement of `maneuver_hand` within the side's cards, asked of
  `maneuver_tiers`, and empty in a game without the gambits, for an
  unchallenged maneuver and for a side that holds them. It rides on the
  prompt as `ManeuverHand.withheld` and is never an answer; the Discord
  hand image does not draw it.
- **The coin is on the hand and nothing else.** Volatile still upgrades
  a maneuver to its rank's gambit off an ignite whatever the coin says,
  and Synapse's Overdrive and Dravox and Hexis likewise: those are about
  the dice. The reference hexagon is not gated either
  (`RulesEngine.maneuver_reference_tier`).
- **Dinky declares on a coin flip.** Holding the coin with its hand not
  yet down, it declares half the time; after a declaration it rolls a
  rank and picks among the cards on it in the hand the prompt offers.
  Asked to answer a gambit while behind, it answers either way on a
  coin flip. The
  same indifference as the tier choice, below -- and the only way a solo
  coach ever sees the coin cross.
- **The game's own coin.** Each game is played with one of the six
  Fortune and Doom coins (`GAME_COINS`), drawn from `engine.rng` when
  the game is created and kept for the game (the author, 2026-09-28):
  the toss is flipped with it, Discord shows its emoji, the web page
  its faces. `D12BallGame.game_coin` is the reading, the gold 3 for a
  game saved before.
- **The coin is flipped each time it passes** (Law 19.3.3, the author,
  2026-10-01, amending "never flipped again"): `declare_gambit_step`
  draws the face with `engine.flip_coin` -- the toss's own draw, off
  `engine.rng` -- and `MatchState.declare_gambit` writes it as
  `coin_face`. **`RulesEngine.coin_face` is the one reading**: that
  face once the coin has passed, the toss's until then (the same face
  whoever flipped it, since a doom face hands the toss over), Fortune
  for a game seated without a toss, and `None` wherever `coin_holder`
  is. **The face decides nothing**; it is what the coin looks like, so
  every frontend draws the same one: the declaration says it ("hands
  the coin to Y, who flips it: [coin] Doom."), the holder's sentence
  says it ("holds the coin, [coin] Doom up, and may declare a
  gambit."), each through a `{coin:doom}` token, and the web page's
  box coin and jumbotron draw it. A save from before the flip has no
  `coin_face` and shows the toss. The draw moved every seeded game
  after a declaration, so the advanced golden and the full-game driver
  test were re-swept for their seeds.

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
    Phase 2 of the model/Discord split and the pattern the other
    eleven followed; the rule it settled is that the **step does not
    save**. The wrapper did, immediately, before dispatching, until
    Phase 6 moved that write into `dispatch_step_result`, once per run
    of the driver's loop. See "The model and the Discord layer" in
    CLAUDE.md and [model-discord-split.md](model-discord-split.md).
  - **Both dribbles followed it (rank O2).**
    `dribble_advance_step` and `dribble_burst_step` are beside it,
    with `pay_clear_cost` moved down as a free function -- its only
    two callers were those two cards. Each ends by naming
    `FollowOnStep.OFFER_SPEED_CHOICE`, the ball-speed manipulation
    every dribble finishes on, named because a tutorial beat holds
    the prompt behind a note (and, until step 7, because Dinky
    answered for itself inside it; it answers the prompt through the
    service now). Nothing either card says changed.
    - **The burst no longer ends there.** Since 2026-09-20 a won
      Burst leaves the ball at exactly 12 -- the author:
      "precisely 12, not any number" -- so there is no speed to ask
      and `dribble_burst_step` sets it, says "Ball speed is now
      **12**." where it changed (a ball already at 12 gets no line),
      and ends on `FINISH_MANEUVER_RESOLUTION` like a Deflect. It is
      the one dribble with no speed choice, and the one gambit whose
      effect can be entirely choiceless: a handler on the last space
      has no distance to pick either, so `pending_prompt` restores
      that window to the turn prompt, the choiceless-effect fallback.
      The beaten burst is unchanged -- the ball keeps whatever speed
      it had, and the defender's step is a steal's.
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
    a `direction`, the way Low Pass and Pinpoint are one function
    and a `key`. `take_ball_by_steal` and `steal_result_text` went
    with it as free functions, and `D12Ball.apply_steal` is four
    lines around it. Nothing either card says changed.
    - **It is the first effect to hand off to the spine**, so it
      named two new `FollowOnStep` members:
      `BEGIN_RUN_BACK`, carrying `speed_choice_after=True` (a steal
      owes the ball-speed choice but does not reach
      `offer_speed_choice` directly -- `finish_run_back` offers it,
      once everybody is back), and `BEGIN_SHOOTER_CHOICE`, for the
      Intercept that reaches the goal zone and sets up a scoring
      opportunity.
      `begin_run_back` and `begin_shooter_choice` themselves did not
      move.
    - **Two persists became one, and nothing was being lost.**
      `take_ball_by_steal` saved inside itself and the Pinpoint
      cost branch saved again on top of it, so one branch wrote the
      file twice and the other once; both writes already carried
      everything. Unlike the beaten Clear above, this is the rule
      rather than a fix -- worth saying so, because the two read
      alike in a diff.
    - **One ordering is open.** An Intercept that reaches the goal zone
      returns before `gambit_cost` is read, so it collects no beaten
      Pinpoint. Whether that is the rule (nobody goes back in
      position, so the free pass has no moment) or an oversight is
      the author's; the behaviour is preserved exactly and the
      question is written out in PR #233.
  - **Both pressures followed them (rank D3).** `pressure_step` is
    the whole of a Pressure and of a Double Team -- the two differ by
    the push and by the partner the gambit brings in, so they
    are one function and a `key`. `shove_pressured_handler`,
    `pressure_result_text` and `apply_pressure_turnover` went with it
    as free functions, and `D12Ball.apply_pressure` is four lines
    around it. Nothing either card says changed.
    - **A shove that sends the ball into the goal zone names a new
      follow-on**, `BEGIN_OWN_GOAL_ROLL`, and it is the first whose method
      posts a prompt of its own. So `begin_own_goal_roll` (a flow step in
      [`d12ball/flow/arrivals.py`](../../d12ball/flow/arrivals.py)
      since Phase 4) grew a `lead_in`
      and carries the shove above its question: a Pressure that
      sends the ball into the offense's own goal zone is one message now
      where it used to be two. The roll,
      its dice image and the messages around it did not move.
    - **`apply_own_goal_outcome` moved with the rank** and stopped
      saving. It is the verdict rather than the card, but it is the
      Pressure's verdict; `own_goal_roll_step` in
      [`d12ball/flow/effects.py`](../../d12ball/flow/effects.py) is the
      roll and the two sentences it is worth, and the cog wrapper saves once,
      immediately after it, on both branches. Both branches already
      wrote the same state, so this is the rule and not a fix --
      unlike rank O2's beaten Clear.
    - **The pair a Double Team leaves was unchanged by the move.**
      `pending_double_team` survived a restart mid-effect -- which the
      rank asserts rather than assumes, since it is the one record here
      that reaches into the next turn. (What it holds, and what clears
      it, changed with the card on 2026-10-03; see below.)
  - **Both deflections followed them (rank D1).** `deflection_step` is
    the whole of a Deflect and of a Clear -- the two differ by the
    distance and by how much speed comes off, so they are one function
    and a `key`. `deflection_numbers` and `knock_ball_back` went with
    it as free functions, and `D12Ball.apply_deflection` is four lines
    around it. Nothing either card says changed.
    - **The Fullback's +1 is still two numbers rather than one.**
      `deflection_numbers` returns the distance and the speed drop
      separately, and the ability moves only the first: a Deflect they
      play goes back 2 and still drops the speed 1, a Clear goes back 4
      and still drops it 3. Derived from the distance instead, this
      read correctly right up until the Fullback was let near a Clear.
    - **The rank named two new follow-ons**, `BEGIN_LOOSE_BALL` and
      `OFFER_SETUP_PASS_PUSH_BACK`. The second went with the 2026-10-03
      Cross, below.
    - **The goal-zone branch's ordering is unchanged and now pinned.** A
      deflection that reaches the goal zone and finds a defender standing
      where the ball stopped turns into a scoring opportunity -- a
      failed Cross's included. One that comes to rest on an empty
      space is an ordinary loose ball. Neither was asserted anywhere before
      the rank's fixtures.
    - **Step-then-save was the rule rather than a fix**, the third time
      of four. `knock_ball_back` saved the moved ball and the shot
      branch saved again over the turnover it then applied; nothing
      between them mutates the match, so both wrote the same state.
- **A failed Cross gambit is the beating card, as itself, with the
  contest given away** (the author, 2026-10-03). It was a push back --
  "a further" 1-3 on top of the deflection until 2026-09-27, then the
  beating card's one move at a distance its coach chose, which needed a
  prompt (`SETUP_PASS_PUSH_BACK`), a follow-on that asked it, and the
  one prompt the board was held back in front of. All three went:
  `deflection_step` plays a Deflect or Clear exactly as it always does,
  and the cost is read where a contest is settled --
  `RulesEngine.contest_auto_winner` gives the defense's contestant the
  ball with no roll while `failed_cross_contest` holds, which is
  whenever the maneuver still under way is a Cross the deflection beat
  on the cards. The maneuver's cards stay set until
  `finish_maneuver_resolution`, and every contest the landing leads to
  is settled before that, so nothing new is saved. Slitheron's ability
  is the same mechanism, so the two meet in one function: a passing
  Slitheron cancels the cost and the contest is rolled (Law 19.7.9);
  `resolve_contest_without_a_roll` words the reason for whichever it
  was. A game saved at the old prompt reads as "effect owed"
  (`BEGIN_EFFECT_RESOLUTION`) and plays the deflection as it now reads.
- **A Cross asks no speed** (2026-10-03). It used to set the speed
  first and pick the pass out after, which made it the one effect whose
  speed choice came before its move. The pass is asked straight away
  (`EFFECT_OFFERS["setup_pass"]` is `offer_setup_pass_distance`); a game
  saved with the old `setup_pass_shot` continuation reads its winner and
  comes back to the same pass, and `setup_pass_step` still spends it.
- **Every cost bites inside the winning maneuver's own resolution**,
  which is why there is no cost dispatcher. `gambit_cost` names the
  card that was beaten and the winner's handler asks it: Clear's 2
  exhaustion and Double Team's shove are charged by the card that beat
  them, Intercept's uncontested reception is a branch of the High
  Pass, and Burst's is the first exception to "every turnover
  resets ball speed to 1". A generic "and then pay the cost" step
  would have to know where inside each effect it belonged, which is
  the thing the handler already knows.
- **`pending_effect_continuation` is what lets an effect reach past
  its own maneuver**, as `{"kind": ...}` -- the same shape
  `pending_injury_resume` uses and for the same reason. One needs it
  now: a beaten Pinpoint hands the defense an unopposed Low Pass once
  the steal has settled (Cross needed it too, while it set the speed
  before the pass). A speed choice had always been the *last* human
  step of an effect, leading straight into
  `finish_maneuver_resolution`; `continue_effect` is the branch. A
  Double Team's partner is recorded on the same field
  (`DOUBLE_TEAM_PARTNER_KIND`) for the rest of its maneuver, so no
  later reading measures again off a board that has moved -- a value,
  not a new saved field.
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
- **`pending_double_team` is the partner, not a flag, and Merge is
  the reading of it** (2026-10-03). A won Double Team pushes 1, as a
  Pressure does, and the partner joins; that partner Merges through the
  next maneuver as an Ooze would -- on the ball's space, not rolling, in
  a skill test or a contest. So the partner is one more answer in
  `RulesEngine.merge_contributions`, the one reading of who Merges, and
  reaches the skill test, the contests and the dice images through it;
  the "both defenders add" bonus the skill test used to carry went. It
  used to last until a new play; now `finish_maneuver_resolution`
  clears it at the end of the maneuver after the one that set it -- the
  record the Double Team leaves says `merges`, which is how the first
  finish knows to keep it -- and after any contest that maneuver led to,
  since the loose-ball detour re-enters that function. A Defender's
  steal or a beaten Burst hands the ball over in the same breath, and
  no Merge is granted. A game saved under the old rule holds both
  defenders; both Merge where they stand, once, and the list clears
  with the next maneuver.
- **The partner is read before anything moves, and a tie is the
  coach's** (Law 19.10.3). The nearest defender on the ball's space or
  behind it -- toward their own goal -- by
  `double_team_partner_candidates`, measured where the play started.
  The cost's caller reads it before the pass moves the ball and passes
  it in, which is why `pay_double_team_cost` takes a partner rather than
  looking one up. Where several tie, `DOUBLE_TEAM_PARTNER` asks the
  defending coach, won or beaten, ahead of everything else the maneuver
  does: `begin_effect_resolution` raises it before it logs the maneuver,
  so the answer comes back through the same entry and the maneuver is
  logged once; the chain asks it at the same point; Dinky picks the
  higher defensive skill.
- **A Cross is gated on the field, not on the roster** (the
  author, 2026-08-25). `RulesEngine.setup_pass_distances` offers 1 and
  3 -- and a Fullback's 4 -- whenever the space they land on is on the
  board, and **0 alone still needs a teammate**, since it means one
  sharing the passer's own space and a passer never receives their own
  pass. It used to offer only distances that reached somebody, which
  read the card as a set-up that either happens or does not and left a
  passer with nobody ahead of them unable to play it at all.
  - **A pass landing on nobody settles where it lands**, exactly as a
    Deflect's does: `setup_pass_step` names `BEGIN_LOOSE_BALL`,
    which since 2026-08-26 settles every arrival by what is standing
    there -- see [Where the ball comes to rest](loose-balls.md#where-the-ball-comes-to-rest).
    It pays `SETUP_PASS_CLOCK_COST` there, the card's flat 2 minutes,
    however far the ball actually travelled.
  - **That leaves one position a Cross goes out from, and it is
    still a fourth `new_play=True` call site.** The card cannot
    reach the goal zone, so `setup_pass_out_step` is reached only where
    nothing is on the menu at all: the passer on the last space before
    the goal zone -- the one place even 1 space reaches it -- with no
    teammate beside them. The other three call sites are the score
    attempt, a conceded own goal and the out-of-bounds loose ball.
  - **Dinky answers the distance as it answers a High Pass's**
    (`DinkyAI._longest_reaching_pass`, on both prompts), which is the
    same question now that a bad pass costs the ball: the longest that
    reaches a teammate, otherwise the longest available. A second
    policy would only be the same one written twice.
- **A role ability is inherited by rank, and what carries is the rule
  rather than the number.** Each sentence in `players.json` was written
  against one card and states a number, so read literally three of them
  are nonsense on the gambit that inherits it: a Fullback's "ball
  goes back 2" is a *reduction* on a 3-space Clear, its "high pass up to 4"
  is a fourth number against a card offering 0/1/3, and a Playmaker's
  "may advance 2" was no bonus at all on a run to the last space before the
  goal zone. The author settled all three on 2026-08-19 -- **the Fullback's
  ability is +1 distance** (High Pass 3->4, Deflect 1->2, Clear
  3->4, Cross gains a 4), and **the Playmaker's is one exhaustion
  token off a Burst**, kept on 2026-08-26 once the burst was
  bounded (below). The Midfielder's +3 and the rank-D2 ball speed
  modifier were already uniform and needed no ruling.
  - **The Playmaker's moved back onto the space on 2026-09-26**, and
    with it the "only ability that reads differently on the two cards
    of a rank" stopped being true of anything. The sheet's sentence no
    longer names either card ("may advance an additional space when
    resolving Dribble maneuvers"), so neither auto-matches
    `role_abilities`' needle any more; both `dribble_advance` and
    `dribble_burst` carry a hand-written `EXTRA_NOTES` row in
    `d12ball/cards.py` instead of the one `dribble_burst` used to. The
    2026-08-26 reading (below) is superseded: a Playmaker's
    Burst now runs up to 5, `dribble_burst_distances`' own +1, charged
    the plain token a space `dribble_burst_cost` charges everybody --
    no more discount named beside the run.
  - *(Superseded 2026-09-26, kept for the reasoning it recorded.)*
    **The Playmaker's stayed on the cost when the burst was bounded**
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
  one is a *win* is not decided there. Since **Phase 4** of the model/Discord
  split it is a flow step in
  [`d12ball/flow/turn.py`](../../d12ball/flow/turn.py), with
  `maneuver_winner_text` and `skill_test_headline` -- the four sentences
  themselves -- beside it. The skill test's reveal rides as that step's
  `headline` **argument** rather than as narration, because
  `begin_maneuver_skill_test` embeds it in its own message instead of
  posting one above it.
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

**Except while a Cyborg's Overdrive is open** (the author, 2026-10-02):
Overdrive and Boost are declared *before* the die is thrown (Law 20.3.5), and
a Roll anybody may press let the other coach throw it before the Cyborg's
coach had decided. So while a human coach's Cyborg on the roll may still
declare, the roll waits on that coach until they declare or pass -- the
attacker's first, then the defender's -- and only then may either coach
press Roll. See
[species-abilities.md](species-abilities.md), "Overdrive is the only thing in
the game declared before a roll". The same holds for an Ooze's Merge, and
for an AI side (the author, 2026-10-07): Dinky is asked its declarations
and answers them -- Merge always, Overdrive and Boost while they keep the
Cyborg out of Drained -- but never throws the die.

**A shot is walked back only by the coach who chose it, and never for an
AI side.** "Back" on the score attempt is an answer to that prompt
(`retract_shot_step`), and a human standing in for the AI's rolls does
not get to undo its choice -- not a rule of the game but a feature of
how the AI plays: it does not misclick (the author, 2026-09-21). Since
step 6 of docs/architecture-migration.md the step refuses it, and the
prompt's `RollOptions.back` is what the view builds the button from, so
an AI side's score attempt carries no Back and waits on nothing but the
roll.

Both are now places a turn can **stop**, and that is the whole cost of it:

- **What the roll was going to do next has to outlive the wait.** An own goal
  carries `pending_own_goal_distance`, the clock cost of the maneuver that
  risked it -- which since 2026-09-28 was already charged when the Pressure
  won, so the roll spends it only for a game saved under the old rule
  ([clock-and-records.md](clock-and-records.md), "When the clock
  advances"). Injury tests carry
  `pending_injury_resume`, which is the contest's continuation -- a maneuver's
  skill test resumes into its winner's effect, a loose ball (or the long High
  Pass borrowing its machinery) into its run back, with the two arguments that
  run back needs, and a shootout skill test into the next one. Neither is
  derivable after the fact: `settled_maneuver_winner`
  answers None while a test is owed, and the contest that knew the distance has
  already cleared itself. Both are persisted, and `reset_maneuver` clears them
  with everything else the turn set.
- **`pending_injury_tests` is a queue, and `continue_injury_tests` is its only
  exit.** Both are flow steps in
  [`d12ball/flow/injuries.py`](../../d12ball/flow/injuries.py) since Phase 4.
  `dispatch_injury_resume` stayed in the cog, and knowingly: two of the three
  arrivals it names -- a maneuver's effect and a shootout test -- are not the
  spine's, so it is a `FollowOnStep` rather than a lift until Phase 5 takes
  the shootout. A contest can owe two tests; they are asked one at a time and the
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

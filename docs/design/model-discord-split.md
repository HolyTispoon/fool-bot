# The model/Discord split

Design notes for fool-bot; the map is [CLAUDE.md](../../CLAUDE.md), the rules are
[living-rules.md](../living-rules.md). The rules the split is made by are
CLAUDE.md's, in "The model and the Discord layer"; the plan is
[model-discord-split.md](../model-discord-split.md) -- a worksheet, not settled
history, read it for the phases still open. This file is for what has landed
and is permanent regardless of how much of the rest of the plan does: the two
guards from Phase 0, the seam Phase 1 cut, and the write side Phase 2 opened.

## `d12ball/prompts.py`

**Is the seam, in the one place it was cheapest to cut.** `pending_prompt`
answers "what is this match waiting on?" with a `PendingPrompt` -- a
`PromptKind`, the line to ask it with, and the few parameters the question
carries -- and the cog turns that into a `discord.ui.View`. It is the
principle "one reading, and it is in the model" made concrete, and it was the
first phase because nothing in it mutates: the whole chain is a read, so the
move had no rules risk to weigh against it.

- **The chain moved whole, ordering comments and all.** Which branch is
  checked before which carries real decisions -- setup, halftime, the window
  before the shootout and a time out are all read ahead of "no ball handler
  yet" because all four leave `active_player_id` None -- and those decisions
  live in the comments beside the branches rather than anywhere else. Splitting
  the chain, or paraphrasing it into a new shape, is how a second reading gets
  made by accident. See "Recovering a stuck game" in [recovery.md](recovery.md).
- **One kind per view class.** 26 of them: the chain's own 17 view classes
  over its 25 `return`s, plus the 9 the three folded-in builders add (6 effect
  prompts, 2 run-back, 1 loose-ball). A view built with different arguments for
  different situations is **one** kind carrying the difference in its
  parameters -- `SPEED_DELTA_CHOICE` is Setup Pass's, the dribbles' and
  Steal/Intercept's with `maneuver_key` telling them apart, and
  `LOW_PASS_CHOICE` is the plain and the free one with `free`. The alternative,
  a kind per situation, makes the cog's table a second copy of the chain's
  branching, which is the thing the phase exists to prevent.
- **A prompt carries what its branch decided and nothing else.** The six
  parameters (`player_ids`, `player_id`, `side`, `maneuver_key`, `skill_type`,
  `free`) are the ones the branches actually held. Anything else a frontend
  needs it asks the engine for with the match it already has -- the loose
  ball's candidate list is read in `view_for_prompt`, not carried, because a
  prompt is what to ask rather than a rendering brief.
- **`view_for_prompt` is the only place a kind becomes a view.** A later phase
  rendering a step's next prompt comes through it rather than growing a second
  table; two tables is the same failure as two chains, one step further down.
  `PLAIN_PROMPT_VIEWS` and `PARAMETERISED_PROMPT_KINDS` are asserted to cover
  `PromptKind` exactly, because a kind with no view would raise inside a
  restart, one game at a time.
- **The game became a parameter, so the lookup is eager.** The chain read
  `self.games[game_id]` inside the run-back branch alone; `pending_prompt`
  takes the game. Neither production caller can reach it without one --
  startup iterates `self.games.values()` and resume is handed the game -- but
  two shootout fixtures had never registered theirs, and now do.
- **The fixtures are shared, and were recorded first.**
  `tests/prompt_fixtures.py` stands a match in every branch with no discord in
  scope; `tests/test_d12ball_prompt_mapping.py` asserts the view and the ask
  through the cog, `tests/test_d12ball_prompts.py` the kind and the parameters
  through the model. The mapping test was written against the old chain and run
  green there before anything moved -- that is what makes it evidence rather
  than the new code agreeing with itself, and it is the pattern the later
  phases should copy.

## `d12ball/flow/`

**Is the write side of the same seam.** `pending_prompt` answers what a
match is waiting on; a flow step is what *changes* it. Each takes the
engine and the match, mutates, and hands back a `StepResult` -- the
narration, whether the board moved, and what happens next. Phase 2 cut
this on Low Pass alone and nothing else; Phase 3 followed a rank at a
time, and rank O2 brought the two dribbles, rank D2 the two steals,
rank D3 the two pressures, rank D1 the two deflections and rank O3 the
two passes -- so **`effects.py` holds all twelve cards, as nine
functions** (five of the cards are their rank-mate parameterised) and
`cogs/d12ball/effects.py` holds none of them. Rank O1
landed in between and moved none of them: Skilled Pass had come across
with Low Pass already, as the same step under a different `key=`.

- **Low Pass was the slice because it is not a toy.** Mid-sized, with a
  role-ability branch (the Winger's set-up, the one path that ends
  somewhere other than `finish_maneuver_resolution`), a continuation
  (the free pass a beaten Skilled Pass hands the defense), a shared
  function with Skilled Pass, and an advanced cost charged in the middle
  of its own sentence. A slice with one branch would have settled
  nothing.
- **`FollowOn` is transitional and the enum is the record.** The spine a
  step ends by naming -- `finish_maneuver_resolution`,
  `offer_scoring_attempt_choice`, later `begin_run_back` and
  `begin_loose_ball` -- is still async and still in the cog through
  Phase 5. A step names one as a member of the closed `FollowOnStep`
  enum with its arguments, and `D12Ball.follow_on_methods` is the only
  thing that turns a member into a call. Closed rather than a callable
  or a method name the cog would `getattr`, for two reasons: nothing on
  the model's side can reach into `cogs/` by spelling a string, and the
  enum's membership *is* the list of what the cog still dispatches, so
  Phase 6 reads the file rather than six pull request descriptions.
- **The narration never rides in the follow-on's arguments.** A Low Pass
  posts no message of its own: what it says opens the message the next
  step sends. So `StepResult.narration` is a list of blocks, and
  `dispatch_step_result` joins them on a space and passes them as that
  step's `lead_in`. Putting the joined string in `FollowOn.kwargs`
  instead would have worked and would have been wrong -- batching is the
  frontend's (principle 8), and a web app with no five-in-five bucket
  should not inherit Discord's answer to it. It is also what keeps the
  move from costing a request; see [rate-limits.md](rate-limits.md).
- **A `PendingPrompt` in `next` renders through `view_for_prompt`**, the
  same table a restart restores through. No Low Pass branch ends on one
  today (the receiver pick is asked before the pass is applied), so the
  dispatcher's branch is asserted directly rather than through a
  fixture. It is there from this phase on so the branch Phase 3 needs
  cannot arrive as a second table.
- **The step does not save; the wrapper does, immediately, before the
  dispatch.** `send_low_pass` persisted inside itself and
  `apply_low_pass` relied on it -- so stripping the save and adding none
  would have left the match reaching the spine unwritten, and a spine
  step ending in a prompt hands the turn to a click that reloads the
  match from the file. That is the beat-1 event-log bug in
  [gotchas.md](gotchas.md) reintroduced by the refactor meant to fix it.
  The `self.persist` count in `cogs/` was unchanged at 95 across
  Phase 2, which is the shape of the transition in one number: one
  left the step, one arrived in the wrapper. It has moved since only
  where a step held more saves than its wrapper needed -- rank D2 took
  it to 94, below.
- **A step takes `game` only where it reads the record.**
  `low_pass_step` does not and so does not take one; both dribbles do,
  because charging an exhaustion token tests a threshold the *game*
  decides -- a Cyborg's is a flat 7. That is what brought
  `apply_exhaustion` and `describe_exhaustion_gain` onto `RulesEngine`,
  with `condition_emojis` (the third emoji dict to land there) and the
  five `get_*_emoji` fallback lookups into `formatting.py`: a step that
  charges a token has to be able to say so, narration is the model's,
  and a cog method cannot be called from down here. `D12Ball` keeps a
  forwarding method for each, so none of the nineteen call sites moved
  -- the shape `team_emojis` took in Phase 1a. See
  [naming-and-wording.md](naming-and-wording.md).
- **A rank can add a `FollowOnStep` member, and O2 did.**
  `OFFER_SPEED_CHOICE` is the ball-speed manipulation every dribble
  (and every steal) ends on. It is a follow-on rather than a
  `PendingPrompt` because the model has not decided anybody is being
  asked: `offer_speed_choice` answers for Dinky itself and holds a
  tutorial beat's prompt behind a note, and both of those are the
  frontend's. A step returning the prompt directly would have moved
  that decision without meaning to.
- **The persist rule paid for itself here.** `apply_dribble_advance`
  persisted and *then* called `pay_clear_cost`, which charges a beaten
  Clear's two tokens and re-tests the Exhausted threshold -- so both
  writes landed after the save, and the next click read the match back
  off a file that never had them. Lifting the whole effect into the
  step, with the wrapper saving after it, fixes it without anybody
  deciding anything: it is the beat-1 bug in [gotchas.md](gotchas.md)
  one more time, and principle 9 is the general answer to it.
- **The fixtures were recorded first, the same way Phase 1b's were.**
  `tests/low_pass_fixtures.py` stands a match in every branch with no
  discord in scope; `tests/test_d12ball_low_pass_recording.py` asserts
  the narration, the board flag and the follow-on **through the cog**
  and was run green before anything moved, and
  `tests/test_d12ball_low_pass_flow.py` asks the model the same
  questions. The table names the follow-on by `FollowOnStep` member
  name, a string, which is what let it be written before the package
  existed. `tests/dribble_fixtures.py` with
  `tests/test_d12ball_dribble_recording.py` and
  `tests/test_d12ball_dribble_flow.py` is rank O2's copy of the same
  three files, ten branches over the two cards.
- **A rank can also turn out to be empty, and O1 did.** Phase 2 cut
  the slice on Low Pass, and Skilled Pass is that same card
  parameterised -- `low_pass_step(key="skilled_pass")`, with the
  `key=` threaded from `resolve_skilled_pass` through
  `apply_low_pass`. So rank O1 moved no code at all; the `self.persist`
  count in `cogs/` did not change, and neither did the golden
  transcript. What it added is the evidence Phase 2 had no reason to
  write: ten more fixtures in the shared table, all on branches the
  golden cannot see (the tutorial plays a Low Pass and never a Skilled
  Pass), and the one assertion a fixture table cannot make -- that
  `key` survives a save. It is not a field on the match: a restart
  mid-effect reads the card back out of `offense_maneuver`, or out of
  `pending_effect_continuation` for the free pass, so the round trip
  through `to_dict`/`from_dict` is the whole of what stands between
  the prompt a coach was looking at and the one they are handed back.
  A rank that lifts nothing is still worth its pull request for that.
- **Rank O1 left one thing behind, deliberately.**
  `resolve_low_pass`'s no-teammate-to-receive branch moves the ball a
  space, raises its speed, words it and persists, then hands off to
  `begin_loose_ball` -- mutate-and-say-what-happened, in the `resolve_*`
  half this phase does not touch. Lifting it would have meant adding
  `BEGIN_LOOSE_BALL` and settling what `board_changed` means for a
  step whose follow-on redraws the board itself: the cog deliberately
  does **not** refresh there, because `begin_loose_ball` draws the
  same board under its own announcement, so the flag would have to
  mean "the frontend should redraw" rather than "the board moved".
  That is one decision for all eight of `begin_loose_ball`'s callers
  rather than for one card, and rank D1 is where it is due.
- **Rank D2 was the first hand-off into the spine, and it cost two
  members.** `steal_step` is a Steal and an Intercept both -- the
  cards differ by the sign of the carry and nothing else, so they are
  one function and a `direction`, the way Low Pass and Skilled Pass
  are one function and a `key`. What it ends on is not
  `OFFER_SPEED_CHOICE`, which rank O2 had expected it to inherit: a
  steal owes the ball-speed choice but reaches it through
  `finish_run_back`, so the step names `BEGIN_RUN_BACK` and lets
  `speed_choice_after=True` carry the question. The Intercept that
  runs out of field names `BEGIN_SHOOTER_CHOICE` instead, and drops
  the speed choice with the run back.
  - **A follow-on's arguments arrive by keyword.**
    `dispatch_step_result` calls
    `method(interaction, game, match, lead_in=..., **kwargs)`, so a
    parameter the cog used to pass positionally is named now --
    `begin_shooter_choice`'s candidate list was one, and the one
    existing assertion that read it off `await_args.args[3]` had to
    move to `kwargs`. The call changed shape, not answer; the fixture
    table binds a recorded call to the real method's
    `inspect.signature` so it can answer for both at once, which is
    the trick the later ranks should copy rather than recording two
    tables.
  - **Step-then-save is not always a fix.** Rank O2's beaten Clear
    was a write being lost; D2's two persists -- one inside
    `take_ball_by_steal`, one in the Skilled Pass cost branch on top
    of it -- both already carried everything, so collapsing them
    changed the number of writes and nothing else. Both read alike in
    a diff, which is why a rank should say which of the two it found.
    `self.persist` in `cogs/` went 95 -> 94 here rather than staying
    level, and that is the whole of the difference.
  - **A defense rank has no unchallenged branch.** A defense card only
    resolves where a defender was sent, so `match.challenger_id` is
    always set in `steal_step` and "contested and unchallenged" is
    one half only in a defense rank's bot stop.
  - **The overshoot's extra paragraph is one narration block, not
    two.** The blocks are joined on a single space and that paragraph
    is separated by a blank line, so a second block would have put a
    stray space in front of its newlines. It rides inside the
    turnover's own block, the way a beaten Clear's cost rides inside
    the dribble's.
  - **One ordering was left open rather than settled.** An Intercept
    that overshoots returns before the Skilled Pass cost is read, so
    it collects none; the behaviour is lifted exactly as it stood and
    the question is in PR #233, deliberately unpinned by any fixture
    -- the same way rank D1's two questions were left in PR #232.
- **Rank D3 was the first follow-on to post a prompt of its own,
  and that is where `lead_in` stopped being free.** `pressure_step`
  is a Pressure and a Double Team both -- the push and the partner
  are the whole of the difference, so they are one function and a
  `key` -- and the branch that overshoots toward a side's own goal
  ends on `BEGIN_OWN_GOAL_ROLL`. `begin_own_goal_roll` took no
  `lead_in`, because the old branch posted the shove as a message and
  *then* asked for the roll, so an overshooting Pressure cost two
  messages where every other resolved maneuver costs one.
  - **The method grew the parameter rather than the step posting
    around it.** The narration rides above the prompt with a blank
    line between, which is exactly `begin_loose_ball`'s shape, and
    the branch is one message and one board refresh like the rest.
    Nothing either card says changed -- this is batching, and
    batching is the frontend's (principle 8). It is the only thing a
    coach sees differently in the whole rank, and the later ranks
    should expect to meet it again: a spine step that has never been
    handed narration has no reason to take any yet.
  - **The refresh also swapped places with the message**, on that
    branch alone. The old code posted and then redrew;
    `dispatch_step_result` redraws first. Same requests, same bucket
    -- see [rate-limits.md](rate-limits.md).
  - **A rank can lift something that is not a card.**
    `apply_own_goal_outcome` settles the roll a Pressure risked and
    words it, so it belongs to this rank, but the roll itself is a
    coach's dice and a dice image and stays `run_own_goal_roll`'s
    until Phase 4. It moved as a free function returning its verdict
    rather than as a second `StepResult`, and the cog saves once,
    unconditionally, immediately after it.
  - **Step-then-save was the rule rather than a fix**, the same as
    rank D2. The conceded branch saved inside the outcome and the
    avoided one saved two messages and a board refresh later; nothing
    between them mutates the match, so both wrote the same state.
    What collapsing them buys is that the write no longer sits behind
    three things that can fail. `self.persist` in `cogs/` went
    94 -> 92.
  - **`format_goal_time` came down with it**, from
    `cogs/d12ball_helpers.py` into `d12ball/formatting.py`, which
    re-exports it the way it re-exports everything else there: the
    own-goal verdict names the minute a goal went in, and a function
    that only formats a `GoalRecord` has no Discord in it. No call
    site moved.
  - **`pending_double_team` needed nothing at all.** It is set inside
    the shove's own wording and it was already in
    `MATCH_SAVED_FIELDS`; what the rank added is the assertion that
    it survives a `to_dict`/`from_dict` round trip, because it
    reaches into the *following* maneuver and a restart that lost it
    would give the next turn one challenger instead of two.
- **Rank D1 settled what `board_changed` means, which is the one
  question a rank had left open for another rank to answer.**
  `deflection_step` is a Deflect and a Clear both, and it calls
  `begin_loose_ball` directly rather than going through
  `finish_maneuver_resolution` -- the ball is out of everybody's hands
  where it stopped, so the question that step asks has an answer that
  does not matter. The old cog did **not** refresh the board before
  handing over, even though the ball had plainly moved, because
  `begin_loose_ball` draws the board under its own announcement.
  - **The step reports `board_changed=True` anyway, and the frontend
    skips the write.** The alternative was a step returning False
    because a Discord bucket says so, which is principle 8 read
    backwards: the model would have been carrying this channel's
    five-in-five arithmetic on behalf of every frontend that ever
    reads a `StepResult`. `FOLLOW_ONS_THAT_DRAW_THE_BOARD` in
    `cogs/d12ball/core.py` is where it went instead, and
    `dispatch_step_result` reads it. See
    [rate-limits.md](rate-limits.md).
  - **It is keyed to the step, not to the card.** Eight sites in
    `cogs/d12ball/effects.py` reach `begin_loose_ball` and this rank
    lifted two of them; the other six inherit the answer as they move,
    rather than each deciding it again. That is the same failure this
    flow has already had once -- `restrict_to_occupants` was a flag,
    and the two call sites that did not pass it kept the old
    behaviour for two days.
  - **`OFFER_SETUP_PASS_PUSH_BACK` is in the set one step removed**,
    and the rank's own recording is what found that: it was written
    expecting a refresh on that branch and the old cog had not made
    one. All three of the push-back's branches end in
    `begin_loose_ball`, so the board arrives with the loose ball, on
    the far side of the coach's answer rather than in front of a
    question whose answer moves the ball again.
  - **Two pre-existing tests read `distance_moved` off
    `await_args.args[3]`** and broke on a move that changed nothing,
    which is rank D2's `inspect.signature` lesson turning up in tests
    that are not the rank's own. The fix is the assertion; the rank
    added a `loose_ball_distance` helper to each of the two modules
    rather than making the call positional again.
  - **Step-then-save was the rule rather than a fix**, the third time
    of four: `knock_ball_back`'s own persist and the shot branch's
    both wrote the same state, with nothing between them that could
    fail. One `self.persist` site fewer in `cogs/` -- 96 -> 95 as
    merged: two left the step and one arrived in the wrapper.
  - **What did not move**, deliberately: `resolve_low_pass`'s
    no-teammate-to-receive branch, which is the eighth caller of
    `begin_loose_ball` and rank O1's. Two rules questions on it are
    open (PR #232) and they decide where the lifted step would put it,
    so lifting it now would have baked in an answer. Its
    `distance_moved` reaches `begin_loose_ball` positionally still,
    which is fine -- only a `FollowOn` names arguments.
- **Rank O3 was the last of the twelve, and the hardest, and what it
  had to settle was the board again.** `high_pass_step` is the throw
  and its six endings; `setup_pass_speed_step`, `setup_pass_step` and
  `setup_pass_out_step` are the other card, which is three steps
  rather than one because its speed choice comes **first** -- the only
  card in the game where it does -- and because the dead end its menu
  falls to is reachable without a pass being thrown at all. The two
  cards share a landing space and nothing else, so unlike the four
  ranks before it neither is the other parameterised.
  - **`BEGIN_HIGH_PASS_CONTEST` is the member it added, rather than
    `BEGIN_LOOSE_BALL` with a `headline=` and `is_high_pass=True`.**
    The brief expected the latter, since the long pass borrows the
    loose ball's machinery and `begin_high_pass_contest` is a
    two-line wrapper over `begin_loose_ball`. What that missed is
    that the two do different things with the board: a High Pass is
    not a loose ball, so `begin_loose_ball` announces it plainly and
    draws nothing (see [loose-balls.md](loose-balls.md)), and the
    board the pass moved has to be written **before** it. Naming the
    loose ball's member would have put the branch in
    `FOLLOW_ONS_THAT_DRAW_THE_BOARD` and lost that write. That is the
    answer being keyed to the step working exactly as rank D1
    intended, rather than an exception to it: two members because
    there are two steps.
  - **`begin_run_back` is the first follow-on that draws a board only
    sometimes**, and that is what `follow_on_draws_the_board` in
    `cogs/d12ball/core.py` exists for. A new play posts and pins one
    (`announce_new_play_reset`); an ordinary run back after a steal
    draws nothing, and rank D2 refreshed before handing to it. Both
    passes that run out of play reach it with `new_play=True` and the
    old cog wrote no board in front of either, so the argument is
    read beside the set rather than the model being asked to report a
    board that did not move. The set is still the shape of the
    answer; this is one step whose own arguments decide it.
  - **Step-then-save was the rule rather than a fix**, the fourth
    time of five. Every branch of both cards already persisted after
    its own mutations, and the one branch that persisted nowhere of
    its own (a Setup Pass landing on nobody) reached
    `begin_loose_ball`, whose two arrival gates persist before
    returning. `self.persist` in `cogs/` went 95 -> 91: eight left
    the steps, four arrived in the wrappers.
  - **One pre-existing assertion broke on a move that changed
    nothing**, reading `begin_loose_ball`'s `distance_moved` off
    `await_args.args[3]` -- rank D2's `inspect.signature` lesson for
    the third rank running.
    `tests/test_d12ball_gambits.py` gained the same
    `loose_ball_distance` helper rank D1 put in two other modules.
  - **What it did not move**, deliberately, is the same thing rank D1
    left: `resolve_low_pass`'s no-teammate-to-receive branch, rank
    O1's, with two rules questions open on it (PR #232). It is the
    last caller of `begin_loose_ball` in the `resolve_*` half and it
    is due whenever the author answers, not with a rank.

- **Phase 4 moved the spine, and what it had to settle was the message
  boundary.** `d12ball/flow/` grew four modules -- `arrival.py` (the two
  gates, the loose-ball check, the loose ball, the High Pass contest, the
  set-up offer), `resolution.py` (the tail of a maneuver),
  `turnovers.py` (the run back and the pickup after it) and
  `maneuver.py` (challenger to settled maneuver, and the injury queue).
  `cogs/d12ball/` fell from 11,706 to 11,417 lines, but the number that
  says what happened is a different one: the methods there that **touch
  the match** went 139 -> 96 and the ones that **write to it directly**
  61 -> 29, counted the worksheet's own way. The async and
  `interaction`-taking counts went *up* (188 -> 198, 161 -> 171),
  because the phase added wrappers; the decisions left.
  - **A step says one thing, because a `StepResult`'s narration blocks
    are one message by contract.** Where the old flow said two things in
    two messages, the step ends on the first and *names* the second. The
    clock reaching the period's last minute is the case that forced it:
    a step returning both would have joined them, and a coach would read
    "this is now last possession" inside a board caption -- a batching
    change smuggled in under a refactor, which is exactly what the golden
    exists to refuse.
  - **So five cog methods grew a `lead_in` they post on their own**, and
    the shape is worth a name: a follow-on that is handed narration but
    has no prompt of its own for it to open posts it first.
    `announce_last_possession`, `begin_effect_resolution`,
    `begin_maneuver_action_selection`, `start_set_up_shot` and
    `decline_scoring_attempt`. Each is the same two messages in the same
    order as before; what moved is which function sends the first one.
  - **A wrapper may read which shape a result took; it may not decide
    which it is.** `D12Ball.begin_loose_ball` posts a genuine loose ball
    with the board under it and a High Pass contest plainly, because
    whether a coach can already see the position is a question about this
    channel. What the position *is* -- the pre-decline, the auto-picks,
    the headline -- is `loose_ball_step`'s.
  - **The cascade is a generator, and that is the one place the phase
    departs from the shape.** Every run-back pass either places somebody
    or ends the cascade, and whether it needs a coach is only known once
    it has run, so one `StepResult` could not say "these four placements
    happened and then somebody has to choose". `run_back_passes` yields
    one per pass; the cog batches them into one message and saves between
    yields, which is the named exception to principle 9 kept exactly
    where the worksheet said to keep it.
    - **Its give-up branch stopped being a count and became a question.**
      A generator bounded by `range(max_passes)` cannot tell "used every
      pass it was given" from "could not settle", so the cog asks
      `next_run_back_step` and `pending_kickoff_fill` after the generator
      ends -- which is what the log line claims, said the way it is
      checked.
  - **`dispatch_step_result` gained the three things the spine needed.**
    A `lead_in=` of its own, for narration the *caller* holds and has not
    posted; `turn_message_id` and `allowed_mentions` on the
    `PendingPrompt` branch, because Phase 4 is the first phase to reach
    that branch in production and a prompt the game cannot find again is
    one `drop_turn_prompt` leaves live; and `lead_in` passed to a
    follow-on **only when there is one**, so a step that is never handed
    narration does not declare a parameter it would ignore, and one that
    is handed lines and cannot take them raises at the dispatch that
    would have dropped them.
  - **The enum grew rather than shrank, and the members are a different
    kind.** Phases 2 and 3 added members naming spine steps; Phase 4's
    twenty-five name the *Discord tails* the spine now hands back to --
    the two queues an arrival gate opens, the settling of a loose ball,
    the announcements, the prompts without a `PromptKind`. It is 34
    members, and it is still exactly what the cog dispatches. Phase 6
    reads it rather than six pull request descriptions.
  - **Three prompts are follow-ons rather than `PendingPrompt`s, each for
    a reason.** `ShooterChoiceView` and `SetUpAttemptChoiceView` have no
    `PromptKind` -- the second because `contest_on_decline` rides on the
    view rather than on the match (see [shooting.md](shooting.md)), so a
    restart cannot rebuild it; `ASK_RUN_BACK`'s prompt carries a rendered
    field strip beside the cascade's own board, which is two renders the
    frontend orders. `ASK_MANEUVER_ACTION` is a fourth, and the clearest:
    the hand image, the gambit-access paragraph and a tutorial note held
    behind Continue are all *how* the question reaches somebody.
  - **The headline of a skill test is narration, not an argument.** It
    was the obvious thing to put in `FollowOn.kwargs` and would have been
    narration riding in a follow-on's arguments -- the one shape
    `StepResult` is built to prevent.
  - **Three wordings came down from `cogs/d12ball_helpers.py` into
    `d12ball/formatting.py`**, which re-exports them:
    `HIGH_PASS_CONTEST_HEADLINE`, `ball_location_line` and
    `ball_space_phrase`. `RulesEngine` gained `injured_word_and_emoji`
    the same way, with a forwarding method on the cog. All four are
    `format_goal_time`'s shape from rank D3: narration is the model's,
    and a flow step cannot call a cog method.
  - **The advanced golden earned its commit on the first try.** The first
    version of `finish_maneuver_resolution_step` returned early on the
    last-possession branch and never reached `reset_maneuver`, so the
    game stopped dead at minute 16 with the turn never handed back.
    Nothing else in the 1,784-test suite noticed; the golden failed on
    the next 580 lines of transcript being gone. That is the whole
    argument for Phase 0, met once.
  - **Six test modules had assertions reading a follow-on's arguments
    positionally**, which is rank D2's `inspect.signature` lesson met
    once per module rather than once per rank. Two more needed
    `suppressed_cog_saves` beside `suppressed_view_saves`, because a
    skill test owing no injury tests now saves once through the wrapper
    rather than not at all -- principle 9 rather than an accident.

- **What is in `FollowOnStep` is asserted in
  `tests/test_d12ball_package_shape.py`**, not in any one rank's own
  tests, along with `D12Ball.follow_on_methods` covering it exactly --
  a member with no row raises inside a resolved maneuver, one card at
  a time. It started out in Low Pass's module, where every later rank
  would have had to edit an assertion about a card it was not
  touching.

## `tests/test_model_purity.py`

**Is the line itself.** Every module under `d12ball/` **and
`gamesaves/d12ball/`** imports **in a fresh subprocess** with `discord`
refused, none of them defines an `async def`, and none of them imports from
`cogs/`. All three hold today, so this is a **ratchet on something already
true** -- the purity was kept by habit, and habit is what erodes once flow
code starts moving across the line.

- **`gamesaves/d12ball/` is checked too, not just `d12ball/`.** The plan
  leans on `gamesaves/d12ball/storage.py` being pure -- it is what makes
  `MatchState.to_dict` "already a wire format" rather than a claim to prove
  later -- so the ratchet covers the module the plan actually depends on,
  not only the one it is named after. `gamesaves/tethysdeck/`, a different
  prototype's save, is left out.
- The subprocess is load-bearing, not fastidious. `unittest discover` imports
  every test module before running anything, so an in-process version of this
  check would find half of `d12ball/` already in `sys.modules`, and
  `import_module` hands back the cached module without re-executing it --
  passing against modules it never actually imported.
- The `discord`-refused assertion is checked with a `meta_path` finder rather
  than a bare `import discord` probe, so a transitive import is caught too:
  injecting `import discord` into `formatting.py` fails the check naming both
  that module and `engine`, which imports it.
- The no-`async def` assertion walks the AST rather than grepping, so a
  definition nested in a class or a function reads the way the interpreter
  reads it.
- The no-`cogs/`-import assertion is asserted and reported on its own,
  separate from the `discord` check, even though a stray cog import would
  trip that one too (naming `discord` itself, which is not the useful
  message).

## `tests/test_golden_transcript.py`

Plays the tutorial through the real cog and compares the narration byte for
byte, the sequence of prompts, and the final `to_dict()` key for key, against
`tests/golden/`. `FOOLBOT_UPDATE_GOLDEN=1` rewrites those files, so **a
wording change is a diff in a pull request rather than a test somebody
silences** -- the "What a message says" rules in
[naming-and-wording.md](naming-and-wording.md) are rules, and a refactor that
rewords a result has changed the game.

- **The module RNG is seeded, not `randint` patched.** The flow also reaches
  `random.shuffle` and `random.choice`, so patching one call misses the
  others; the seed is restored afterwards, since it is global and would
  otherwise leak into whatever test runs next.
- **`GOLDEN_SEED` is one that scores.** The tutorial's closing shot is
  deliberately unscripted (see "Determinism: rails and dice" in
  [tutorial.md](tutorial.md)), so two seeds give two different transcripts; a
  seed that missed would pin the unusual branch as the reference. A test
  asserts the recorded run is the one with the goal in it, so the golden
  cannot quietly become the missed-shot run.
- **It is stable**: two runs on one seed agree (asserted), and the transcript
  is identical under `PYTHONHASHSEED` 0, 1 and 42 (checked by hand) -- a set
  of player ids iterated into a message would otherwise vary by machine
  rather than by the change that broke it.
- **It covers one basic-mode solo game on board 7** -- no gambit, no species
  ability, no halftime, no shootout, no time out. Rewording two of the three
  `Ball speed is now` sites in `effects.py` did not fail it, because the
  tutorial only reaches the third. Don't read a green golden as "the wording
  is covered"; a phase that moves narration the golden doesn't reach should
  add its own.
- **Phase 4 did add its own, and it is in the same module.**
  `AdvancedGoldenTranscriptTests` over `tests/golden/advanced_*` is a whole
  advanced solo game on board 9, kickoff to full time: both modules on, the
  human coaching the Telekinetics against Dinky's Cyborgs, so the arrival
  gate (both halves), the loose ball, the run back's two questions, the
  injury queue, the own-goal roll and the coaching window a new play opens
  are all in the transcript. It was recorded on the code as it stood before
  the phase moved anything, which is what makes it evidence rather than the
  new code agreeing with itself.
  - **Its press rule has two exceptions to the tutorial's, and each replaces
    something the rails did.** The card is rotated on
    `ManeuverActionPromptView` -- "press the first enabled button" plays Low
    Pass every turn and never reaches eight of the twelve cards -- and
    `CoachingHubView` presses Done coaching, because the window is a menu
    whose first button re-opens a picker that re-opens the window, and the
    run never comes out of it. Both are one rule each and still
    reproducible.
  - **The seed is chosen for what it reaches, not for a score line.**
    `ADVANCED_VIEWS_THE_RUN_MUST_REACH` is asserted, naming what went
    missing, because a seed that drifted into a short quiet game would be a
    green golden that had stopped watching Phase 4's own branches -- the
    own-goal roll and the stacked run back are the two most seeds miss.
  - **What it still does not reach**: the shootout (the seed does not finish
    level), a time out, and `BallRecoveryView` -- the pickup after a ball
    goes out, a shot misses or an own goal is avoided. Phase 5 is where the
    first two are due.

## Two things about running the suite that cost time to rediscover

- **`requirements.txt` will not install below Python 3.13.** It pins
  `audioop-lts`, a backport that exists only because `audioop` left the
  standard library in 3.13 and has no distribution for earlier versions. On
  3.11 or 3.12, where `audioop` is still stdlib, the pin is both unnecessary
  and unsatisfiable -- `pip install discord.py Pillow python-dotenv` is
  enough to run the suite there. CI pins 3.13 and is unaffected.
- **Five tests fail when the suite runs as root, and none of them is a
  regression.** `test_an_unwritable_folder_reads_as_no_record` and the four
  `GameStorageTests` about unreachable folders all simulate a directory that
  cannot be written to, and uid 0 bypasses permission bits -- a write into a
  `chmod 000` directory simply succeeds. They pass in CI, which runs as an
  ordinary user. Before treating any suite failure as a regression, re-run
  the same commit on the branch's real base (`origin/main`, not a local
  `main` that may be far behind it).

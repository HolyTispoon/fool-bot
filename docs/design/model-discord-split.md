# The model/Discord split

Design notes for fool-bot; the map is [CLAUDE.md](../../CLAUDE.md), the rules are
[living-rules.md](../living-rules.md). The rules the split is made by are
CLAUDE.md's, in "The model and the Discord layer". **The split is done**:
the worksheet it was built from (`docs/model-discord-split.md`) went with
its last phase, as it said it would, and what it kept open is closed --
every step of a turn is the driver's, every click goes through
`driver.answer`, and a whole game plays through `driver.apply` with no
frontend loaded (`tests/test_driver_full_game.py`). This file is the record
of how it landed and why it is shaped the way it is: the two guards from
Phase 0, the seam Phase 1 cut, the write side Phase 2 opened, the loop Phase
6 moved, and the entry points Phase 6 closed on. The phase-by-phase history
is kept because the *ordering* decisions it records are rules a second
frontend has to keep, not because the phases are still open.

## Read this first: what the game service changed

The model's half of this note is current. The Discord half is not:
`dispatch_step_result` no longer runs the loop, `post_then_dispatch`,
`post_blocks_then_dispatch`, `post_stop`, `run_step`, `SafeView.answer`
and `dispatch_answer` are gone, and no view saves. Every click goes
through `GameService.apply_action` (`gamesaves/d12ball/service.py`),
which runs the driver and saves once, and `D12Ball.present` renders the
`GameResult` it hands back. Where this note describes the cog running
the chain, saving per stop, or a view writing before it edits, read
[game-service.md](game-service.md) for what stands now; the reasoning
recorded here for *why* the seam is where it is has not changed.

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
- **Phase 6 closed the last two prompts the chain could not answer, and
  one of them cost a persisted field.** `SET_UP_ATTEMPT` and
  `SHOOTER_CHOICE` were `FollowOnStep`s rather than kinds because the
  view carried what match state did not hold: by the time the offer is
  put, an overshot High Pass and an ordinary 2-space one have left the
  match in the same position, so `distance_moved` and
  `contest_on_decline` existed only on the view. A game that went down
  inside either came back to the maneuver's *first-stage distance
  choice* -- `effect_choice_prompt` said so, and it was the last known
  gap in the chain.
  - **`MatchState.pending_scoring_opportunity` is what closed it**, and
    it saves the question rather than the answer: the attempt's two
    numbers, which nothing in the position remembers, and for the
    shooter's pick nothing at all beyond the fact that it is being
    asked -- the candidates are `scoring_opportunity_candidates` over
    the ball's own space, read back where a restart reads everything
    else. An older save has no such key, which reads as None, which is
    "nothing outstanding": true of every save written before it.
  - **Two paths arm it and three spend it**, which is the thing to hold
    in mind when reading them: `offer_scoring_attempt_choice` and
    `begin_shooter_choice` arm it, and `take_scoring_opportunity`,
    `decline_scoring_attempt` and `ScoreAttemptView.back_from_set_up_shot`
    spend or re-arm it. The last is the one that is easy to miss -- it
    is the only path that puts the attempt-or-decline choice back up
    without going through the offer.
  - **`SEND_RUN_BACK_PROMPT` and `BEGIN_SUBSTITUTION_WINDOW` were never
    that**, although the same list named all four together. Both
    questions have been `pending_prompt`'s since Phase 1; what kept
    them follow-ons is that their *message* carries a picture. The run
    back's is closed -- `run_back_choice_prompt` asks `run_back_prompt`
    which of the two questions it is and replaces only the `ask`, and
    `D12Ball.post_run_back_prompt` attaches the field strip -- and the
    coaching window's closed with the last increment, when the
    tutorial's Continue gate became a prompt of its own
    (`TUTORIAL_CONTINUE`, below) rather than a thing the cog ran
    before the window opened.
- **The last increment added three kinds, and two of them are not
  questions about the position at all.** `TUTORIAL_CONTINUE` is the
  tutorial's Continue gate: a note held up with the step it gates
  behind it, on `D12BallGame.tutorial_gate` (`{"note": key, "then":
  FollowOn.to_dict() | None}`), read first of all by `pending_prompt`
  because whatever the match is waiting on, the gate is in front of
  it. It used to be a cog routine with a callback in a closure, so a
  restart inside one lost the continuation; now it is a prompt like
  any other, a restart re-posts the note, and `skip_tutorial` runs
  `gates.continue_step` to spend it. `GAME_OVER` is a finished game
  -- read second, so the rematch buttons are what a restart hands
  back rather than a stale prompt off the last turn. Both read the
  *game* record rather than the match, which is why `pending_prompt`
  has always taken the game. The third, `SETUP_PASS_PUSH_BACK`, is
  the push back Setup Pass's cost offers, which was a follow-on
  until the offer became a step the driver runs and its answer a
  prompt like the other six effect choices.
- **A prompt is asserted to survive a save and a load**, every kind of
  it, in `test_a_prompt_survives_a_save_and_a_load`. That is the
  restart in a test, and it is what a new prompt carrying a new
  argument is checked by: `pending_prompt` over the fixture and
  `pending_prompt` over `MatchState.from_dict(match.to_dict())` have to
  be the same prompt, arguments and all. A branch answering from a
  field `MATCH_SAVED_FIELDS` forgets fails it.
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

- **Phase 4 made it five modules, and widened what `FollowOn` means.**
  `arrivals.py` holds the two gates and the five arrival points they
  guard, `turnovers.py` the run back and the out-of-bounds pickup,
  `turn.py` the front half of a turn, and `injuries.py` the injury-test
  queue. The one to read first is `arrivals.py`: the gates and the
  arrivals moved **together**, because which runs first and which of the
  two spends `last_ball_path` is a rule, and half an ordering on each
  side of the seam is worse than none.
  - **A gate returns `Optional[StepResult]`** rather than a
    `StepResult`, so a caller stays the one `if ...: return` it has
    always been.
  - **The enum grew from 9 members to 27, and that is the honest
    reading.** Its meaning widened: a member used to name a step still
    wholly in `cogs/`, and now mostly names one whose decisions have
    moved and whose cog method is the wrapper that persists and posts.
    It still reads exactly as "what the cog still dispatches", which is
    the claim Phase 6 needs -- but not as "what has not been lifted".
    The `FollowOnStep` docstring names the three kinds now in it.
  - **`post_then_dispatch` is the other half of principle 8.**
    `dispatch_step_result` hands a step's lines to the next step as its
    lead-in, which is right for a maneuver resolving into its effect and
    wrong where the line is an event in its own right -- where the ball
    came down, that a new play has started, that everybody is running
    back. The advanced golden caught all three the moment they were
    merged. Which of the two a step gets is the frontend's decision, so
    it is a second method on the cog rather than a flag on `StepResult`.
  - **The run-back cascade is a generator**, yielding one `StepResult`
    per pass, which is what lets the loop be the model's while the
    per-pass persist stays the caller's -- the one named exception to
    principle 9.
- **Phase 5 made it seven modules.** `periods.py` holds the whistle and
  the three stage machines hanging off it -- halftime, the window before
  the shootout, and the shootout itself -- and `windows.py` the Coaching
  Choice on all five of its occasions, with the time out that buys one.
  The two are one phase because they are one loop: a stage machine hands
  out a window and `finish_substitution_window` routes back into
  whichever machine is running, which is the junction all five occasions
  come back through. Splitting that across the seam would have left half
  an ordering on each side, which is the mistake `arrivals.py` was moved
  whole to avoid.
  - **`advance_shootout` is still the one reading of what a shootout is
    waiting on.** It moved; it did not fork. The claim was already
    load-bearing -- two of the shootout's four steps are the bot's own,
    so a restart between them has no button and `/d12ball resume` has to
    ask -- and a lift that produced a second reading would have been the
    exact failure principle 3 names.
  - **`post_blocks_then_dispatch` is the third dispatcher**, and it
    posts one message per narration block. A period transition is a run
    of separate events -- the whistle, the halftime recovery, an AI
    side's extra token, the shootout's explainer -- which both existing
    dispatchers would have joined into one paragraph. Three methods
    rather than a flag on `StepResult`, for `post_then_dispatch`'s
    reason: which of them a step gets is the frontend's decision
    (principle 8). Its one exception is
    `FOLLOW_ONS_THAT_SPEAK_THE_LINES`: `announce_game_over` puts the
    final board and the rematch buttons on a message whose *content* is
    those lines.
  - **The enum went 27 -> 29, and two members Phase 4 expected to lose
    are still there.** `DISPATCH_INJURY_RESUME` did go: taking the
    shootout is what let the dispatcher move, since two of its three
    arrivals now answer in the model and the third names a follow-on
    like any other step would.
    `FINISH_SETUP_COACHING`, `FINISH_HALFTIME` and `ANNOUNCE_GAME_OVER`
    arrived, and all three are the third kind -- a board this phase may
    not post and pin, and the message the rematch buttons hang off.
    `END_PERIOD` stayed because the whistle's cascade is a run of
    separate messages and the two steps that name it hand their results
    to dispatchers that would merge them.
    `BEGIN_SUBSTITUTION_WINDOW` stayed because the window's prompt is
    the one in the game that carries the coach's own half-field, with
    the tutorial's Continue gate over the top of it -- a picture and a
    gate, which is the enum's second kind.
  - **`heading` in `FollowOn.kwargs` is not the narration coming back.**
    A window's own opening line goes *inside* the prompt, above the
    allowance; a preceding step's narration is its own message. Two
    different things that both used to be called `lead_in`, and the
    follow-on carries only the first.
  - **Three pure builders came down with them**, into
    `d12ball/formatting.py`: `build_goal_log`, `build_full_time_summary`
    and `format_goal_scorer`. Neither fetches an emoji nor touches
    discord.py -- which is that file's own stated rule for what belongs
    in it -- and the whistle needs both to word itself.
    `cogs/d12ball_helpers.py` re-exports all three, so no call site
    moved.
- **Low Pass was the slice because it is not a toy.** Mid-sized, with a
  role-ability branch (the Winger's set-up, the one path that ends
  somewhere other than `finish_maneuver_resolution`), a continuation
  (the free pass a beaten Skilled Pass hands the defense), a shared
  function with Skilled Pass, and an advanced cost charged in the middle
  of its own sentence. A slice with one branch would have settled
  nothing.
- **`FollowOn` was transitional and the enum was the record; now the
  enum is the joints of a turn.** Through Phase 5 the spine a step
  ends by naming -- `finish_maneuver_resolution`,
  `offer_scoring_attempt_choice`, later `begin_run_back` and
  `begin_loose_ball` -- was still async and still in the cog. A step
  named one as a member of the closed `FollowOnStep` enum with its
  arguments, and `D12Ball.follow_on_methods` was the only thing that
  turned a member into a call. Closed rather than a callable or a
  method name the cog would `getattr`, for two reasons: nothing on
  the model's side can reach into `cogs/` by spelling a string, and
  the enum's membership *was* the list of what the cog still
  dispatched, so Phase 6 read the file rather than six pull request
  descriptions. That table is gone (see `driver.py` below); the enum
  stayed, because what it records now is where one step ends and the
  next begins, which is what a frontend reads to place a message or
  a picture.
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
- **The step does not save; the wrapper did, immediately, before the
  dispatch, until the dispatcher took the save in Phase 6.**
  `send_low_pass` persisted inside itself and
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
    `cogs/d12ball/core.py` is where it went, and
    `dispatch_step_result` read it; since the last increment the same
    answer is `stop_draws_the_board` beside `DRIVER_STOPS`, read off
    the step the loop stopped on, and `PROMPTS_DRAWN_LATER` for the
    push back. See [rate-limits.md](rate-limits.md).
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
    loose ball's member would have put the branch under the loose
    ball's suppression and lost that write. That is the
    answer being keyed to the step working exactly as rank D1
    intended, rather than an exception to it: two members because
    there are two steps.
  - **`begin_run_back` is the first follow-on that draws a board only
    sometimes**, and that is what `follow_on_draws_the_board` in
    `cogs/d12ball/core.py` existed for. A new play posts and pins one
    (`announce_new_play_reset`); an ordinary run back after a steal
    draws nothing, and rank D2 refreshed before handing to it. Both
    passes that run out of play reach it with `new_play=True` and the
    old cog wrote no board in front of either, so the argument was
    read beside the set rather than the model being asked to report a
    board that did not move. The last increment made it the step's
    own flag, `StepResult.new_play`: the reset's lines are the caption
    of the board the play starts from, so the loop stops on it
    whoever asked, and the frontend pins that board and skips its
    ordinary write.
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

- **What is in `FollowOnStep` is asserted in
  `tests/test_d12ball_package_shape.py`**, not in any one rank's own
  tests, along with the driver's table covering it exactly -- a
  member with no row raises in the middle of a turn, one card at a
  time. It started out in Low Pass's module, where every later rank
  would have had to edit an assertion about a card it was not
  touching. Through Phase 6 there were **two** tables, the driver's
  and the cog's, disjoint and covering the enum together, and which
  side a member was on was recorded there (`IN_THE_DRIVER`); the
  last increment emptied the cog's and the assertion is now that
  `driver.MODEL_STEPS` and the enum are the same set, and that
  `D12Ball` has no `follow_on_methods` at all.
  - **The enum is 31 members, all in the driver.** It grew by three
    in Phase 6's third increment for Phase 4's reason yet again:
    `CONTINUE_SHOOTOUT`, `AUTO_RESOLVE_CHALLENGER` and
    `FINISH_SUBSTITUTION_WINDOW` are all steps the model already
    owned that *needed a name* once the thing reaching them became a
    step too -- and by one in the last, `START_TURN`, when the
    offensive choice split into the tutorial's staging
    (`SEND_TURN_PROMPT`, `turn.begin_turn`) and the turn itself
    (`turn.start_turn`), so the gate could sit between them as a
    prompt. **A growing enum was never the phase failing**: it counted
    what a frontend still dispatched, and a member arrived every time
    a *caller* crossed the seam ahead of the thing it called. When
    the last caller crossed, the count stopped meaning that.

## `d12ball/flow/driver.py`

**Is the loop**, and it is the last thing about a turn that was only
ever written in Discord's half of the bot. A step says what happens
next; something has to keep going. Until Phase 6 that something was
`D12Ball.dispatch_step_result`: read `StepResult.next`, look the
`FollowOnStep` up in `D12Ball.follow_on_methods`, await the cog
wrapper, which called the flow function, saved, and came back in. So a
second frontend had `pending_prompt` for what a match is waiting on
and every step for how to change it, and still had to write its own
answer to *what happens after a Deflect* -- which is principle 10's
failure with a different noun in it.

`driver.advance(engine, game, match, result)` is that walk with the
Discord taken out. It returns a `DriverRun`: the `StepResult` it
stopped on, the steps it ran to get there, the narration groups it
closed on the way, and -- since the last increment -- `stopped_on`,
the step it halted after where the frontend asked it to halt.
**`MODEL_STEPS` covers `FollowOnStep` exactly.** The bullets below are
how it got there, increment by increment, and the ones written while
the cog still had a table of its own say so.

- **The narration is carried, not collected.** A step takes the lines
  said before it as its `lead_in` and folds them into its own, which
  is how "a resolved maneuver is one message" was already written --
  the loop simply keeps doing it, and `lead_in` is the only thing it
  passes between steps. A step whose lines have to be **a message of
  their own** was therefore not something the first increment's loop
  could run: the frontend was handed the `FollowOn`, posted what it
  posted, and the chain continued on the far side of that. That is
  why `RESOLVE_MANEUVER` and the period's whistle stayed the cog's
  for one more increment although their steps had moved long before
  -- see `post_then_dispatch` and `post_blocks_then_dispatch`, which
  are the two batchings that distinction is made of, and
  `own_message` below, which is how it came into the loop.
- **`board_changed` is or-ed across the run**, and that is the whole
  of the arithmetic the loop does about the board. The old chain wrote
  the persistent board *between* steps; `BoardRefresher` was already
  collapsing those, and says why in its own docstring -- "the
  intermediate boards are worth nothing: a coach reads the board once
  everything has finished moving". So the run's answer is "something
  moved", the frontend writes at most one board for it, and a click
  makes **fewer** requests than it did rather than more.
- **`stop_after` is the frontend saying it has a picture to take.**
  A step whose line is posted with a *snapshot* of the board under it
  cannot have the position move on behind it, so the frontend names it
  and the loop stops once it has run -- `DriverRun.stopped_on` is
  that step with its arguments, and `result` is then the step's own
  result verbatim, because what the frontend has stopped to draw is
  the position *this* step left. `DRIVER_STOPS` in
  `cogs/d12ball/core.py` names two: the loose ball, announced by
  showing where it is, and the tail of a maneuver where it hands the
  offensive choice back, which shows the board that choice is made
  over. The third picture is the model's own stop: a step that opens
  a **new play** says so on `StepResult.new_play`, and the loop halts
  there whoever asked, because the reset's lines are the caption of
  the board the play starts from and the next step -- an AI side's
  coaching window -- rearranges the meeples on it. After any stop
  `dispatch_step_result` takes the picture (`post_stop`) and re-enters
  the loop with whatever the stopped step named, so a click still
  runs to its prompt in one call. It is the mirror of the old
  `FOLLOW_ONS_THAT_DRAW_THE_BOARD`, which said "do not write a board
  in front of this step"; that suppression is `stop_draws_the_board`
  now, read off the stop, plus `PROMPTS_DRAWN_LATER` for the one
  prompt (Setup Pass's push back) whose answer draws the board a beat
  later.
- **`own_message` is where the carrying stops, and it is what let the
  second batch of steps into the loop.** Until Phase 6's second
  increment the loop could only *carry* a step's lines forward as the
  next step's `lead_in`, so a step whose lines are an event in their
  own right could not be run by it at all -- the reveal, a settled
  loose ball, "Players run back!", the whistle. The distinction was
  the cog calling `post_then_dispatch` or `post_blocks_then_dispatch`
  instead of `dispatch_step_result`, and a *different method* is not
  something the model can name. Naming a step in `own_message` closes
  a `NarrationGroup` once it has run: the run comes back as the
  groups the frontend must put up before whatever is next, each
  tagged with the step that said it, plus the lines still being
  carried. Which of the three dispatchers a group gets is still read
  off its step, in `cogs/d12ball/core.py`, which is where principle 8
  puts it -- a web app with no five-in-five bucket may want every
  step's lines separately and is free to pass nothing.
  - `speaks_lines` is the exception to it: `ANNOUNCE_GAME_OVER` takes
    the whistle's lines as the *content* of its own message -- the
    final board and the rematch buttons ride on them -- so a group
    that would close in front of one of those is carried instead.
    That is `FOLLOW_ONS_THAT_SPEAK_THE_LINES`, passed in.
- **`BEGIN_HIGH_PASS_CONTEST` was the one near miss, and it needed no
  `stop_before` after all.** Its wrapper is the same three lines as
  the four arrivals the loop took first, but rank O3 made it a member
  of its own precisely so the board the pass moved is written
  *before* the contest is announced. What makes that survive is that
  the frontend writes the board **before it posts any of the run's
  groups**: the pass's board goes up, then the contest is announced
  over it, exactly as when the cog dispatched the step itself. What
  did have to move is the *suppression*. The run now ends on
  `BEGIN_LOOSE_BALL`, which drew the board under its own line, and
  suppressing there would have lost the pass's board altogether -- so
  the suppression read `is_high_pass` off the step's own arguments,
  beside `new_play`. Rank D1's rule applied one argument further in.
  Since the last increment it reads the step's own `board_changed`
  instead: `begin_loose_ball` reports the board moved for a genuine
  loose ball and not for a High Pass, and `stop_draws_the_board`
  asks that rather than the argument.
  - **What the loop could not run, through the third increment, was
    a step that puts up a picture of its own.** `BEGIN_LOOSE_BALL`
    and `OFFER_SETUP_PASS_PUSH_BACK` announce the position with a
    snapshot attached, and a snapshot taken after the run would show
    a position that has moved on. Those two stopped the loop by being
    absent from the table. The last increment put both in: the loose
    ball is a `stop_after`, and the push back ends on a prompt
    (`SETUP_PASS_PUSH_BACK`), which is a stop by definition.
- **It saves nothing, and its caller saves once.** This is principle 9
  and it is the one place the refactor makes the bot better rather
  than only more portable. Forty-one cog wrappers used to call their
  step, write the match, and dispatch -- so a cascade of four steps
  wrote the same file four times, and the write sat behind whatever
  the previous step had already posted. `dispatch_step_result` now
  writes once per run of the loop, after everything that moves has
  moved and before anything is posted, and `self.persist(` in
  `cogs/` went **83 to 43** in the first increment and to **16** by
  the last (with 28 spelled `cog.persist(` in a view; count both).
  The bare `save_games` calls write the game record alone -- a
  message id, a status, a tutorial flag -- and have no match to save;
  across `cogs/d12ball/` and `cogs/d12ball_views/` they went 42 to
  **31** (20 and 11) over the phase, mostly by a prompt's own
  "remember this message id" folding into `dispatch_step_result`.
  - **Three paths write twice**, on purpose, and the own-goal roll
    was the first. Its wrapper saves before building the dice image,
    and being *earlier than the posting* is the point of that save;
    the dispatcher's write then closes the click. Both write the same
    state. `tests/test_d12ball_pressure_flow.py` says so rather than
    leaving it to be rediscovered as a bug. Phase 6's third increment
    added the score attempt and the shootout test for the same
    reason: a goal credited and a shooter retired go down before a
    portrait render and a dice upload can fail.
- **`waiting_on` is `pending_prompt` re-exported**, so a frontend
  imports the driver and has the whole of what it needs. It is a
  re-export and never a second reading -- principle 3.

### `apply`, and the answers

**`advance` runs what a step starts; `answer` is what happens when
somebody answers.** Phase 6's third increment built the other half of
the seam: `driver.answer(engine, game, match, action)` takes an
`Action` naming the `PromptKind` it answers, checks it against
`pending_prompt`, and runs the model function for that kind.
`driver.apply` is `answer` plus `advance` -- a whole turn of the game
in one call, which is what a web app wants.

- **An action names a prompt, not a step**, and that is the whole
  difference between it and a `FollowOn`. A step is what the bot does
  next and the model names it; an action is what a *person* did, and
  the only thing that makes it legal is that the match was waiting on
  exactly that question. Checking that is a rule -- it is "whose turn
  is it", one click later -- so it is in the model.
- **An action carries what a person chose and nothing else.** Anything
  the position already says is read off the `PendingPrompt`, which is
  why every answer is handed one: the loose ball's `skill_type`, the
  set-up's two numbers, which player the run back is asking about. A
  frontend that had to send those back could send back different ones.
  - **Three actions carry a `side` anyway, and all three are right.**
    The maneuver pick, the shootout order and the shootout shooter are
    asked of *both* sides at once -- one message with two rows, or two
    ephemeral menus -- so which side a click is for is part of what
    was clicked rather than something the position decides. Who may
    click it is still `SafeView`'s.
  - **Two carry a label rather than a rule**, and they are the two
    strings the model could not write for itself: a shot's
    `action_label`, which the tutorial rewrites, and the coaching
    decline's `coach_name`, which names the human rather than the
    side. Nothing in the match knows what to call a Discord account.
- **`Refusal` is the model's, and `SafeView` is not.** Every reason
  `answer` can give is a rule: the match is waiting on a different
  question (the stale click a restart re-attaching an old prompt
  produces), the kind offers no such answer, or the position refuses
  what was chosen. That last one arrives as the `ValueError` the steps
  have always raised -- `MatchState.run_back_player` and its
  neighbours raise with the sentence already written -- and leaves as
  a `Refusal`, so a frontend has one door rather than two. Whose
  Discord account may press a button is not one of those reasons and
  stays where docs/design/permissions.md puts it.
- **`ANSWERS` covers `PromptKind` exactly**, so every question this
  game asks has a model function behind it.
  `test_every_prompt_kind_has_a_model_answer` asserts the equality, so
  a new kind arriving without an answer fails there once rather than
  in whatever corner of a game reaches it. **That is a claim about
  coverage and not about safety** -- see below.

#### What `answer` refuses, and what it does not

**Worth being exact about, because the obvious reading was wrong for
one increment.** `answer` makes three checks of its own before it
calls the adapter -- the kind, whether the choice is one the prompt
offers, and whether the action's arguments fit the adapter's
signature (`_argument_mismatch`, read off `inspect.signature`, so a
missing or unknown keyword is a `Refusal` rather than a `TypeError`
out of the middle of a step). After that, every refusal is one the
adapter or the model makes: a `ValueError` out of `MatchState`, the
engine or the step, or an adapter's own `_refuse`.

Measured on the shared fixtures through `apply` with no cog imported,
the third increment found that *some* adapters refused before they
mutated and some did not: a Dribble Burst offering 1, 2 or 3 accepted
6 and moved the meeple, `PLAYER_ACTION` was answerable in the middle
of a cascade, `take_scoring_opportunity` cleared the opportunity
before raising on an unknown id, and a run back could not be completed
through `apply` at all because `run_back_player_step` recorded
nothing. None of it was reachable -- no view called `answer` -- and
the worksheet made closing it the first job of the increment that
pointed the entry points at the driver, because that is the click
where it becomes live. That increment is the last one, and it closed
them the way the worksheet said: **an adapter refuses an argument
that is not on the list the frontend built its buttons from, which is
the engine's candidate list either way.** The distance choices refuse
a distance the card does not offer; the picks refuse a player not in
the candidate list; `PLAYER_ACTION` in the middle of a cascade is a
stale click now, because `pending_prompt` reads the run back, the
loose ball, the time out and the effect continuation ahead of it; the
tutorial's rails are asked again in the model (`_rail`, over
`tutorial.resolve_choice`) because the prompt may be an old one still
sitting in the channel; the coaching answers check the window is the
side's (`_window_is`). Every adapter refuses before it mutates.
`tests/test_d12ball_driver_actions.py` asserts a legal answer per
kind applies, that the two refusals `answer` makes itself leave the
match byte-for-byte as it was, and that a refused space carries the
step's own sentence; `tests/test_driver_full_game.py` is the claim
made whole.

- **The run back was the one that was a decision rather than a
  guard**, and it cost a persisted field. `RUN_BACK_PLAYER` and
  `RUN_BACK_SPACE` are two prompts for one answer -- who, and then
  where -- and the view carried the first in a closure while the
  match held nothing, so a restart between them, and every answer
  through `apply`, lost it. `MatchState.run_back_pick` is where the
  first answer lives now; `run_back_player_step` writes it,
  `pending_prompt` reads it to ask the second question, and the
  space step clears it. Its own commit, with the table entry and the
  fallback, reviewed as a change to the game (principle 6).
- **The skill test's winner was the second**, found by the advanced
  golden rather than the fixtures: a tie re-rolled at a token each
  leaves the match reading as `SKILL_TEST` still, and the *settled*
  test that follows a tie used to be told apart from an unsettled one
  by the view that rolled it. `MatchState.skill_test_winner` holds it,
  `settled_maneuver_winner` reads it first, and `reset_maneuver`
  clears it with the rest.
- **The stale-click sentences are the model's now**, in
  `driver.STALE_CLICK`: one per kind, with `MOVED_ON` for a kind it
  does not name. Every view used to word its own, so a stale click on
  a skill test and one on a shootout test read differently for the
  same reason; now the reason has one sentence and the frontend
  repeats it (`SafeView.refuse`, ephemeral, whether or not the click
  was already acknowledged).

- **`answer` and `apply` are two functions because the Discord
  frontend renders an answer before it runs the chain.** A prompt here
  is a message with buttons on it, and answering it *replaces* that
  message with what the answer said -- an edit rather than a new
  message, which is one request instead of two and therefore the
  frontend's (principle 8). A frontend doing that has to see the
  answer's own lines before the chain behind it runs, because the
  chain's first step takes those lines as its lead-in. Both go through
  `answer`, so there is still one reading of whether an action is
  legal.
- **`DriverRun.detail` is what an answer hands back beside its
  lines**, where it had numbers a picture is made of. It is
  `own_goal_roll_step`'s `(detail, StepResult)` shape generalised: an
  answer returning a pair has its first half put here, and one with no
  picture returns the `StepResult` alone.

### The last increment: every step, and every click

**What closed the phase** was one pull request over the worksheet's
remaining list, and the shape of each item is worth a line because
none of them was a lift in the old sense -- the steps had moved;
what moved here was *who calls them*.

- **The eighteen cog-side steps went into `MODEL_STEPS`**, which now
  covers the enum. Most were three-line wrappers already. The ones
  that were not were the pictures and the gate, and each became one
  of three things: a **stop** (`DRIVER_STOPS`, `StepResult.new_play`
  -- the loop runs the step and halts, `post_stop` takes the picture,
  the loop is re-entered), a **prompt** (`SETUP_PASS_PUSH_BACK`,
  `TUTORIAL_CONTINUE`, `GAME_OVER`) or a **group** the frontend reads
  the tag of (`AUTO_RESOLVE_CHALLENGER`'s group carries the challenge
  image, and closes even when it said nothing so the frontend learns
  the step ran). `render_prompt` is what a `PendingPrompt` reaches
  at the end of a run: the one place a kind picks up its picture --
  the field strip for `FIELD_PROMPT_KINDS`, the coach's half-field
  for `COACHING_PROMPT_KINDS`, the hand for `MANEUVER_ACTION`, the
  final board for `GAME_OVER` -- before `view_for_prompt` gives it
  its buttons. Two tables still: one for the picture, one for the
  view, both keyed on the kind and neither on the step.
- **Every click goes through `driver.answer`**, by way of
  `SafeView.answer`, which reports a `Refusal` ephemerally and hands
  back an `Answered` otherwise, and `SafeView.dispatch_answer`, which
  runs what the answer started once the view has edited the prompt
  with the answer's own lines (`lines_posted`). The views' stale-click
  guards went with it -- the kind check is that guard, once, in the
  model. A handful of views that post a message *before* running
  the chain still reach `post_then_dispatch` and
  `post_blocks_then_dispatch` directly; those are dispatchers, not a
  second door, and the answer they post came through `driver.answer`
  like every other.
- **`run_step(interaction, game, match, member, **kwargs)`** is the
  entry point every cog wrapper that names a step is one line over,
  and `play_ai_turn` is one of them: the AI's turn is
  `turn.ai_turn_step`, reached through `START_TURN`, its four exits
  the same four a human's turn takes. `DRIVER_BLOCKS_PER_MESSAGE`
  posts it a message per thing said, which is how it always read.
- **The tutorial's gates became a prompt** (`d12ball/flow/gates.py`,
  `hold_behind_note` and `continue_step`) -- see the prompts section
  above for the shape and the restart it fixes. The note text moved
  with it (`tutorial.note_text`, `gate_text`, `player_side`) since a
  note is narration and narration is the model's (principle 5). A
  gate's continuation must not raise the gate again, which is why the
  turn prompt is two steps.
- **Three persisted fields, each its own commit**, per principle 6:
  `MatchState.run_back_pick`, `MatchState.skill_test_winner` (both
  above) and `D12BallGame.tutorial_gate`. Every one reads as absent
  on an older save, which is the right answer for every save written
  before it.
- **The effect continuation is written at the speed choice.**
  `pending_effect_continuation` used to be set by `steal_step` and
  `setup_pass_speed_step` in front of the choice; now
  `speed_choice_step` writes it when the choice is made, because
  until then the match reads as `SPEED_DELTA_CHOICE` and the driver's
  kind check has to agree with what the coach is looking at. Press 37
  of the advanced golden is what found it.
- **What a coach sees differently**, all of it: the tutorial's speed
  note now follows the dribble's own line rather than preceding it
  (the golden transcript records the reorder); the AI's time out no
  longer drops the turn prompt it never posted; stale clicks say the
  same thing for the same reason across every prompt; a tutorial
  gate survives a restart and `skip_tutorial` runs whatever a held
  note was holding; and `/d12ball resume` re-posts a held note
  before the question behind it. Everything else is byte-identical
  on all three goldens.

### `d12ball/flow/rolls.py`

**The four contested rolls**, which were the largest block of rules
still written inside a `discord.ui.View`: a maneuver's skill test, the
contest for a loose ball (which the long High Pass comes through), a
score attempt against the wall of defenders, and a shootout test. Each
returns `(ContestDice, StepResult)` -- the sentences, and the same
numbers for the picture -- because the frontend puts the image
*between* two of the lines. `render_contest_dice` is untouched and
still takes the tuple these functions already built, so the Pillow
stayed in `cogs/` and only the arithmetic crossed.

- **What differs between the four is a rule every time**, which is why
  they are four functions and not one with flags. Injury withholds a
  contestant's own skill in the loose ball and the shootout and not in
  the other two; a tie is re-rolled at a token each in the skill test
  and the loose ball, goes to the attacker in a score attempt, and
  scores for nobody in a shootout; the tutorial scripts the first
  two's dice and deliberately scripts neither of the others; only the
  skill test and the shot write an event.
- **A tie comes back as the prompt the position reads as**, worded by
  what happened. Both contestants are charged and the test is rolled
  again, which is exactly `SKILL_TEST` (or `LOOSE_BALL_SKILL_TEST`) to
  `pending_prompt` -- so the result's `next` is that prompt with the
  tie as its `ask`, and a frontend puts the question up again without
  having to know that a tie is a thing. **The views read it by kind
  and not by "is it a prompt"**, because the settled path ends on a
  prompt too: the injury test the contest owes.
- **Overdrive rides on all six roll prompts, as a `choice` on each.**
  It is declared *before* a roll and spent by it, so it answers the
  prompt without settling it and comes back on the same question --
  which is the coaching hub's shape rather than a new one: four of the
  hub's five choices change the position and return to it, and only
  "done" ends the window. `OVERDRIVE_ROLLERS` is who is rolling, keyed
  on the prompt because "which roll are we in" is the whole of what
  decides who may take one, and it is the same six lists the views
  build their buttons from. That puts "once per roll, not while
  injured, not on a stale prompt" inside `ANSWERS`; who *may* press it
  is a fact about a Discord account and stays in `SafeView`. The
  author settled this on PR #259, against two alternatives: an action
  of its own kind breaks "an action names the prompt it answers" and
  needs a second door, and leaving it to the frontend makes every web
  app re-derive which roll a Cyborg is in, which is the rule.
- **The other two rolls went with them**, into their own modules
  rather than this one: `injuries.injury_test_step` and
  `arrivals.attempt_mind_pull_step`, each beside the queue it drains.
  Both are single-die and neither is contested, and both hand back
  `None` in place of a roll where there is nothing to roll -- an
  already-injured player, a Telekinetic injured between being queued
  and answering. That is how a step says "no picture here".
- **`scripted_or_random` is in `d12ball/flow/turn.py`**, beside
  `tutorial_beat`. `D12Ball.tutorial_dice` was two lines over
  `tutorial.scripted_dice`; every lifted roll site needs the same
  answer to "did the script want a number here", and a copy per module
  is how one of them stops asking.
- **Four paths save deliberately early, where the second increment
  had one**, and the count that matters is that one rather than the
  number of writes. The own-goal roll, the score attempt, the shootout
  test and the loose-ball contest each save *before* anything is
  posted -- a goal credited, a shooter retired, possession flipped and
  Overdrive spent -- because a render and an upload sit between that
  save and the dispatcher's, and a failure there would leave the
  channel showing a result the file does not have. **Plenty of other
  clicks also write twice** and none of them is a bug: a wrapper that
  persists and then dispatches writes the same state twice, and the
  auto-challenger route writes it four times. The loose-ball one was
  *lost* in this increment's first draft and put back in review (PR
  #259), which is the argument for the comment: an early save with no
  sentence beside it reads like a redundancy somebody should remove.

### How the split is measured

The two readings the worksheet tracks, with the rule each is counted
by, so the next re-measure is mechanical rather than a fresh
judgement call. **The rule outlives the plan**, because it is how a
regression would be noticed.

- A method in `cogs/d12ball/` is counted **async** by its `def`; it
  **takes an `interaction`** when that name is in its parameter list;
  it **touches the match** when its body holds an attribute access on
  a name `match`; and a **direct write** is an assignment (including
  `+=`) whose target is `match.<attr>`. All four are read off the AST,
  so a mention in a comment or a string counts for nothing.
- The second reading is `grep -c interaction cogs/d12ball/*.py`
  summed, which counts *lines* rather than signatures and is the
  slower and more honest of the two.
- The third is how many files in `tests/` need `discord.py` installed
  to import, which is what a web app inherits as a test suite.
- **A fourth was added by Phase 6's third increment**, and it is the
  same four AST readings over **`cogs/d12ball_views/`**. The original
  four are scoped to `cogs/d12ball/` and cannot see the views at all,
  which was fine while the flow was the thing moving and stopped being
  fine the moment a dozen *view bodies* lost their rules. Same rules,
  second directory; quote both or neither.

Measured after Phase 6's first increment, against the same commit's
base: **190 async methods, 159 of them taking an `interaction`** (163
with the four sync ones), **611 grep lines**, **54 methods touching
`match.`**, **10 direct writes**, **62 of 86 test files needing
discord.py**. Only the save counts moved: the loop moved without the
cog's surface moving, because every wrapper it emptied is still the
entry point a click arrives at.

Measured again after Phase 6's second increment, against the same
commit's base (`origin/main` at 88268aa): **188 async methods, 157 of
them taking an `interaction`**, **604 grep lines**, **49 methods
touching `match.`**, **5 direct writes**, **41 `self.persist(`** (from
43) and **44 bare `save_games(`** (from 46). The surface moved this
time, and the two that moved most are the ones worth reading: methods
touching `match.` fell 54 to 49 and direct writes fell **10 to 5**,
because twelve view bodies and cog methods that mutated the match in
between rendering it now call a flow step that does the mutating. That
is the figure the split is actually about; the `interaction` counts
barely move until the *entry points* go, and they have not.

**The test-file figure is 67 of 86 and reads 67 on the base too**, so
this increment did not move it -- but it is not the 62 recorded above,
and the rule is the difference rather than the tree. Counted here by
importing each `tests/*.py` in a subprocess with a `meta_path` finder
that refuses `discord`, and counting the ones that fail on it: the
same rule `tests/test_model_purity.py` applies to `d12ball/`. Whatever
produced 62 used another; use this one from now on, because it is the
one that can be re-run.

Measured again after Phase 6's third increment, against the same
commit's base (`origin/main` at f899d06). In `cogs/d12ball/`: **189
async methods, 158 of them taking an `interaction`** (162 with the
sync ones), **607 grep lines**, **46 methods touching `match.`**, **4
direct writes**, **37 `self.persist(`** (from 41) and **44 bare
`save_games(`**, unmoved. In `cogs/d12ball_views/`: **61 methods
touching `match.` (from 84)** and **0 direct writes (from 16)**.
Test files needing `discord.py`: **67 of 88**, where the base is 67 of
87 -- the increment's own test module is discord-free, which is the
only way that figure moves while the cog still owns every entry point.

**Read the two directories together or the increment looks like a
regression.** `cogs/d12ball/` went *up* by one async method and one
`interaction` parameter, because the turn's own action needed a
follow-on wrapper (`auto_resolve_challenger_step`). What actually
happened is in the other directory: **no view mutates a match
attribute any more**, down from sixteen that did, and twenty-three
fewer of them read one. That is the figure the split is about, and it
is the second increment's own warning coming true -- "the
`interaction` counts barely move until the *entry points* go, and they
have not". A click still lands on a `discord.ui.View`; what it finds
there is now a call into `d12ball/flow/` and a decision about what to
show.

**Measured after the last increment, against its base (`origin/main`
at 5226ec2), and this is the figure that finally moved.** In
`cogs/d12ball/`: **9270 lines to 7756**; **177 async methods (from
189), 156 of them taking an `interaction`** (from 162); **528 grep
lines** (from 607); **38 methods touching `match.`** (from 46) and
**0 direct writes** (from 2); **16 `self.persist(`** (from 37) and
**20 bare `save_games(`** (from 31). In `cogs/d12ball_views/`: **43
methods touching `match.`** (from 60), **0 direct writes**, **28
`cog.persist(`** (from 26; it moved between modules as the answers
did, and nearly every one left is the same shape -- `answer`, persist,
edit the prompt, `dispatch_answer` -- so the answer is on disk before
the edit that shows it, and the dispatcher's write after the run is
the second of the same state) and 11 bare `save_games(`, unmoved. Test files needing `discord.py`: **65
of 79**, where the base is 65 of 78 -- the full-game test is the one
that arrived, and it is discord-free.

**Read the `interaction` figures for what they are.** A click still
lands on a `discord.ui.View` and every entry point still takes an
`interaction`, because that is what a Discord frontend *is*; the 156
are the surface, and the surface is exactly what a second frontend
replaces. What the split is about is the other column: no method in
either directory assigns to the match, and the ones that read it do
so to render. `tests/test_driver_full_game.py` is the proof the
figure stands for -- a whole game, and the tutorial, through
`driver.apply` with nothing from `cogs/` imported.

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

## The three goldens

There are **three** since Phase 5, and they are separate files rather than
three seeds of one: they share the fixtures, the diff and the final-save
rendering, and what they do not share is the press rule -- the tutorial is
driven by its own rails, the advanced game has none, and the windows game
has a script written to reach the windows.

### The tutorial golden

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
  add its own. Phase 4 did.
- **Its transcript has changed exactly once since Phase 5**, in the
  last increment of Phase 6, and the diff is one reorder: the dribble's own line now
  precedes the tutorial's speed note, because the note is held behind
  a gate that is a prompt and a prompt comes after what was said. The
  save gained the `tutorial_gate` key. Everything else is byte for
  byte.

### The advanced golden

An advanced solo game, Telekinetics against Fire Demons on board 6 in 2-3-1,
recorded on the old code as the Phase 4 branch's first commit so that the
move is what it is compared against. It reaches all twelve maneuvers, the
Mind Pull and Smooth offers, a loose ball (contest pick and skill test), an
injury test, an own-goal roll, a run back that stops to ask, a score
attempt, a time-out, the halftime extra token and a coaching window. It
earned its keep inside the hour: it caught three places where a lifted step
merged two messages into one, which the tutorial golden does not reach.

- **`mode` is load-bearing and easy to miss.** `gambits_apply` and
  `species_abilities_apply` both read `game.mode` *as well as* their own
  flag, so a fixture with the two flags set and `mode` left at its `BASIC`
  default plays a basic game -- and the golden would have recorded nothing
  this file is for. Every seed swept looked healthy until that was fixed.
- **A whole-species team, and the human coaches it.** Dinky never pulls and
  never takes a Smooth, so an AI Telekinetic would be skipped rather than
  asked and the gate would go unrecorded.
- **The press rule is the script**, since there are no rails: "Done
  coaching" wherever a coaching hub offers it -- the hub is the one view in
  the game that can be walked in a circle -- and otherwise a rotation
  (`live[step % len(live)]`) rather than the first enabled button.
  First-always is deterministic too, and it plays Low Pass and Deflect for
  the whole game: ten of the twelve cards never run.
- **The coverage is asserted, not trusted.** Two tests name the branches and
  the cards the run has to keep reaching, the way the tutorial golden
  asserts that its run scores, so a change that quietly stops reaching the
  own-goal roll fails here rather than going unnoticed.
- **What it still does not reach**: the free pickup after a time-out, the
  stacked run back's *player* prompt, and full time and the shootout, which
  are past where the step budget stops. Those are Phase 5's ground.

### The windows golden

`tests/test_golden_windows.py`, Phase 5's, and the one that reaches what the
advanced golden's own docstring said it could not: full time, the shootout,
and the windows either side of them. It plays a **solo basic** game on board
7 from the standard deal, both halves out, to 1-1 at the whistle and 3-4 in
a shootout that goes to sudden death.

- **Basic and plain on purpose.** The advanced modules are the advanced
  golden's ground, and every press spent on a gambit here is a press not
  spent getting to minute 30. A whole game is about 100 presses.
- **Seed 31 was picked for the two things a script cannot arrange**, both of
  them dice: a level score at full time (eight seeds in forty) and a first
  shootout round level enough to go to sudden death (one of those eight). A
  game that finishes 2-1 ends at the whistle and guards none of
  `begin_full_time_coaching`, `begin_shootout` or `advance_shootout`, so the
  level score is asserted rather than hoped for.
- **Four press rules on top of the advanced golden's two.** Take a time out
  the moment one is offered (`may_call_time_out` is once a half, so "always"
  is exactly once each); make one substitution in a halftime window, read off
  `pending_coaching_swaps` rather than counted in the script; take the first
  player on either ephemeral shootout menu; and roll on the roll prompt
  rather than reading the order six times.
- **The one window it does not pin is a halftime substitution by the AI
  side.** Dinky only ever swaps to get an injured player off, so no script
  can make it, and no seed in the sweep had an injured Purple player on the
  field at the break. Both halftime windows do run, and Dinky's substitution
  routine is covered where it does fire -- in the time out it calls itself,
  at press 32. A halftime where both benches move is the author's bot stop.

### The full game through the driver

`tests/test_driver_full_game.py` is the fourth, and it is not a golden:
it pins no transcript. It plays a whole solo game and the whole
tutorial through `driver.apply` alone -- `pending_prompt` for the
question, a `Policy` that takes the first legal answer to it off the
position the way a frontend builds its buttons (with three
exceptions that exist to reach an ending: shoot when in range, take
every time out offered, and pick the maneuver card at random under
the seed, because the first card in the hand never gives the ball
away and a period under last possession never ends), `apply` for the
answer and everything it starts -- with nothing from `cogs/`
imported, and asserts the game finishes on the rematch prompt.
`TutorialPolicy` follows the rails and asserts every note is held
behind a Continue. **Both coaches are the policy**, which no Discord
script can do (`may_act_for` refuses half the presses of a two-human
game on one user id) and this one can, because authorisation is the
frontend's and there is no frontend here. **Every action is checked
against the save**: after each apply the match is written out and
read back, and the reloaded position has to be waiting on the same
question the live one is (principle 3) -- the restart, as a loop.
It is the sentence "the web app is a frontend rather than a port"
as a test. Seed 3 is the first of twenty swept on which the dumb
policy reaches the shootout, and `test_the_run_reaches_the_shootout`
says so.

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

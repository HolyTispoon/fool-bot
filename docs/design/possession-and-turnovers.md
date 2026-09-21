# The ball carrier, and turnovers

Design notes for fool-bot; the map is [CLAUDE.md](../../CLAUDE.md), the rules are [living-rules.md](../living-rules.md).

## Where the code is

Since **Phase 4** of the model/Discord split the run back is a flow step:
`begin_run_back`, `announce_new_play_reset`, `announce_run_back`,
`run_back_passes`, `finish_run_back`, `apply_charge_up` and
`begin_ball_recovery` all live in
[`d12ball/flow/turnovers.py`](../../d12ball/flow/turnovers.py). Names below
without a path are the flow functions; `d12ball.flow.turnovers.begin_run_back` and the
rest are the cog wrappers that persist and post.

**Two things deliberately did not move**, and both are principle 8 -- the
frontend owns batching and therefore the rate limits: the cascade's
batching, which is `D12Ball.continue_run_back`, and the run-back prompt's
field strip, which is `D12Ball.send_run_back_prompt`. **And one exception
to principle 9 stayed with them**: the per-pass persist, which the loop's
own docstring explains.

## The ball carrier

Possession is a team's, but the ball is a *player's*: a resolution that
leaves it with somebody in particular makes them the **ball carrier**, and
they take their side's next turn instead of the coach picking again off the
ball's space -- see "Choosing the handler" in the living rules.
`MatchState.ball_carrier_id` is the field and
`MatchState.turn_handler_candidates` is the whole of the rule.

- **Every place that offers a handler asks `turn_handler_candidates`**, never
  `eligible_ball_handlers` -- `send_turn_prompt`, `BallHandlerSelectionView`,
  `DinkyAI.choose_ball_handler`, and `select_ball_handler`'s own validation.
  `eligible_ball_handlers` still means "everyone of this team on the ball" and
  is what the loose-ball check and the kickoff fill ask, which is a different
  question and must not be narrowed.
- **`reset_maneuver` deliberately does not clear it.** It runs *between* the
  effect that sets the carrier and the prompt that spends it, so clearing it
  there drops every carry -- and `/d12ball offensive_choice` calls it to start
  a turn fresh, which would make that command a way to hand the ball to
  somebody else. It is consumed by `select_ball_handler` and cleared by
  `clear_ball_carrier`.
- **A stale carrier is harmless by construction.** `turn_handler_candidates`
  falls back to the full list whenever the named player is not among them, so
  a value surviving a period restart, or missing from a game saved before the
  field existed, narrows nothing. Correctness does not rest on having found
  every place to clear it.
- **The setting sites are the effects, not one dispatcher.** Nine of them:
  `dribble_advance_step`, `take_ball_by_steal`, `shove_pressured_handler`
  and `apply_pressure_turnover` (the handler, then the Defender's steal
  over the top of it),
  `send_low_pass`, the two High Pass branches where a pass of 2 is received,
  the two unopposed branches of `resolve_loose_ball`, and
  `LooseBallSkillTestView.roll`. There is no single "who has the ball now" to
  derive it from after the fact, which is why each says so itself. A new
  maneuver has to decide, the same way it decides steal-or-new-play.
  - **Five of the nine are no longer in `cogs/`**, and the list was
    renamed as each one moved rather than annotated: Phase 3 of the
    model/Discord split ([model-discord-split.md](model-discord-split.md))
    lifted the effects a rank at a time, and `dribble_advance_step`,
    `take_ball_by_steal`, `send_low_pass` and the two pressure sites
    are free functions in `d12ball/flow/effects.py` now. Which side of
    the seam a site sits on changes nothing about the rule -- the point
    of the bullet is that there are nine of them and each decides for
    itself.
- **Pressure sets it before the overshoot branch returns.** An own goal
  survived is still a handler who was pressured and kept the ball; a conceded
  one is a new play and gets cleared with everything else. The shove is
  what sets it, which is why `pressure_step` can return straight into
  `BEGIN_OWN_GOAL_ROLL` without deciding anything about the carry.
- **A contest names its winner**, so `begin_loose_ball` clears the carry when
  the ball comes free and the resolution sets it again to whoever won -- on
  the roll, or unopposed. That covers the long High Pass, which routes through
  the same machinery. The out-of-bounds branch is the exception: nobody
  contested it, so it stays clear and the pickup is an ordinary placement.
  Deflect sets nothing either -- it makes a loose ball, and the contest
  names the carrier.
- **The run-back exemption is the carry, read from the other end.**
  `begin_run_back` sets `pending_run_back_stays_player_id` from
  `ball_carrier_id` rather than taking it as an argument -- the player holding
  the ball does not run back, whoever they are, because running them back
  would move them off the ball and charge them for it. It used to be a
  `stays_player_id` argument that only the two steals passed, which left a
  loose-ball or High Pass winner being run back off the ball they had just
  won. Deriving it is what stops a new resolution naming a carrier and
  forgetting the exemption; **don't reintroduce the parameter.**
- **A new play exempts nobody**, so `begin_run_back` clears the carry before
  reading it. A goal scored off a High Pass set-up still has the receiver
  recorded as carrying, and they are not -- the ball is on its way back to the
  kickoff space. `announce_new_play_reset` clears it too; that one is for the
  reset, this one is for the exemption two lines below it.
- **The carry travels with the exemption**, in `inherit_run_back_exemption`
  (a substitution) and `swap_meeple_positions` (a meeple trade). Both belong
  to the space rather than the player, since both exist because that meeple is
  standing on the ball. `swap_field_positions` deliberately moves neither: it
  exchanges zone assignments and leaves both meeples where they are.
- **`build_turn_prompt` is told, not asked.** `select_ball_handler` has
  already consumed the field by the time the prompt is built, so `carrying=`
  is passed by the one caller that still knows -- worth the parameter, because
  a coach who is not offered a choice should be told why.

## Turnovers: steals and new plays

Every turnover resets the ball's speed and puts players back in position, but
*how* differs, and only one of the two opens a
[Coaching Choice](coaching-choice.md#the-coaching-choice).
`begin_run_back`'s `new_play` flag is the whole distinction -- see "Steals and
new plays" in the living rules for which is which. (A third kind,
[a time out](time-out.md#the-time-out), goes nowhere near `begin_run_back`: nothing was
contested and nothing went dead, so nobody runs back and nothing restarts.)

- **A steal runs back; a new play resets.** A steal keeps the old behaviour --
  the stealer stays, everyone else displaced picks a space in their zone at a
  token a space. A new play calls `announce_new_play_reset`, which puts *both*
  sides back on the arrangement their coaches set, free of exhaustion, and
  then offers the window. That leaves nobody displaced, so the run back that
  follows finds nothing to do and falls through to whatever the restart still
  owes.
- **`new_play` is the exception, not the rule.** It defaults False, so a new
  path that turns the ball over is a steal unless it says otherwise. Exactly
  three call sites pass it: the score attempt (goal or miss), the conceded own
  goal, and the out-of-bounds loose ball. Anything that adds a way for
  possession to change has to decide which it is -- did the ball go dead, or
  did the other team take it off them?
- **It is deliberately not persisted**, unlike the `pending_run_back_*`
  fields. It is consumed inside `begin_run_back`, and by the time anything is
  saved the state already records which branch was taken: a window open, or a
  run back pending. A restart resumes from that, never from the flag.
- **A Deflect that overshoots is neither.** It flips possession and goes
  straight to the shot without calling `begin_run_back` at all; the goal or
  miss that follows is the new play.
- **A new play posts its board and pins it**, via `post_new_play_board` inside
  `announce_new_play_reset`. The reset is the arrangement the play starts from
  and the one point in a restart where nothing is still moving, so it is the
  board worth keeping -- what the restart still owes (a kickoff fill, an
  out-of-bounds pickup) lands on the persistent message afterwards. The other
  two pinned boards are the kickoff (the persistent message itself, pinned in
  `TeamSelectionView`) and the second-half restart in `finish_halftime`.
  Nothing else pins; see "Discord's rate limits" in [rate-limits.md](rate-limits.md).
- **Who runs back is two questions, and `next_run_back_step` is the only
  reading of both.** It answers with a side and a list: one name means the
  player is settled and only the space is open, several means a stack has to
  send somebody and *the coach picks which* (2026-08-17). Those who must return
  -- `run_back_displaced`, everyone outside their own zone -- are answered
  before any stack, because a player coming home covers a space and a zone with
  nothing uncovered has no stack to break up. `run_back_movers` is the two
  together, asked only to find out whether a run back has anything to do at all.
  - **`crowded_candidates` offers the whole stack rather than picking out of
    it.** It used to keep whichever player the space's occupant list started
    with -- placement order, so arbitrary -- and hand the rest to the run back
    with nobody asked. One of them moves per pass and the cascade asks again,
    so a zone with two uncovered spaces is two questions rather than one
    silent pair of placements. The ball's holder is never a candidate, which
    is the run-back exemption read from the other end: a pair holding the ball
    between them is one candidate and no question.
  - **`apply_forced_run_backs` leaves an undecided stack out of its
    arithmetic** instead of zipping it into a space. A zone's displaced players
    may still be forced around it, and settling them can take the zone's last
    open space -- which dissolves the stack and saves the coach the question.
  - **The two questions share one message.** `RunBackPlayerChoiceView` asks
    which player and *edits itself into* `RunBackChoiceView` to ask which
    space, so the board uploaded for the first is the board the second is read
    off. That edit is the interaction-callback route, so it costs nothing out
    of the channel's bucket -- but it replaces the view wholesale, which is why
    the full-image link has to be rebuilt onto the new one by hand.
  - Neither pick is persisted. A restart reads the question back off the
    position through `build_run_back_view`, so a coach who had already answered
    the first is asked it again -- the same as a part-made Coaching Choice.
- **The cascade is one loop, not a recursion, and it batches.** Since Phase
  4 the loop is `run_back_passes`, a generator yielding one `StepResult` per
  pass, and the batching is `D12Ball.continue_run_back`: every placement made
  without asking anyone -- the forced ones, the AI's choices, the drop back
  that fills an empty kickoff -- goes into a list, and that list is posted as
  a single message with a single board refresh when the cascade reaches a
  coach's choice or runs out. It used to send a message and re-upload the
  board per player, which after a steal that scatters a six-card side is a
  dozen-odd requests into one channel with nothing between them -- see
  "Discord's rate limits" in [rate-limits.md](rate-limits.md). Anything added
  to the cascade should `yield` a result with its line on it, not send.
  `MAX_RUN_BACK_PASSES` bounds it: as a recursion the interpreter did that,
  and a loop that will not settle would hang the event loop for every game at
  once.
  - **The generator shape is what keeps the per-pass save possible.** The
    cascade persists after *every* pass, which is the one named exception to
    "the driver persists; steps do not": when the loop comes back with a
    question it stops there and the turn waits on a click that reloads the
    match off disk, so that pass's placements have to already be written.
    Collapsing it to one save after the loop loses placements on every
    cascade that stops to ask. Yielding a result per pass is what lets the
    loop be the model's and the saving stay the caller's.
  - **The give-up-after-`MAX_RUN_BACK_PASSES` branch is not that path**,
    though it reads like it: it leaves the loop rather than returning from
    inside it, and `finish_run_back` persists after it. Its ERROR ("the match
    is saved as it stands") is kept by that save whatever happens to the
    per-pass one. Worth writing down because the branch *looks* like the
    fragile one and is the safe one, and the genuinely fragile path has no
    log line drawing attention to itself. The ERROR now comes from
    `d12ball.flow.turnovers` rather than `cogs.d12ball.turnovers`; the sink
    is on the root logger, so it still reaches #logs.
- **A coach's run-back prompt carries the field strip, and prices every space
  it offers.** Both questions a run back asks -- which of these players goes,
  and which space they go to -- are questions about where everybody is standing
  and how far each space is, the same reasoning as
  [a loose ball](loose-balls.md#loose-balls-and-the-board), and the persistent message has
  scrolled away up the channel by the time a turn has resolved. And
  `RunBackChoiceView`'s buttons read `M2 (4 spaces)` -- a run back costs a
  token a space, so the distance *is* the price and the two spaces of a zone
  are rarely the same offer. `MatchState.run_back_distance` is the one reading
  of it, asked by the labels and spent by `run_back_player`, so what a button
  promises and what the coach is charged cannot drift; `travel_space_label` is
  the wording, shared by the buttons and by `describe_run_back_options` beside
  them.
  - **The strip rather than the whole match image**, which is what it carried
    before: the jumbotron, the assignment cards, the team boards and the
    benches are not what either question turns on, and dropping them is what
    makes the field itself legible inline. It is the same picture the five
    [distance prompts](maneuver-prompt.md#choosing-a-distance-and-the-field-under-it) carry and
    for the same reason.
  - **It costs a second render, not a second upload.** The cascade's own board
    still settles the persistent message and the prompt draws the strip beside
    it, so this is two `asyncio.to_thread` renders where there was one, and
    the same number of requests -- which is what the gate counts. See
    "Discord's rate limits" in [rate-limits.md](rate-limits.md).
  - **The picture goes when the question does.** The click edits the prompt
    into its answer, and `attachments=[]` takes the snapshot with it -- it
    shows the player still displaced, so leaving it under the result would put
    a stale position in the channel for the rest of the game. The board they
    moved to is the persistent message's, refreshed a line later.
  - The full-image link is added with the view handed over, or the edit that
    adds it drops the buttons the prompt exists for -- see
    `add_full_image_button`. That edit is the webhook route, not the channel's;
    see "Discord's rate limits" in [rate-limits.md](rate-limits.md).

### The arrangement

`MatchState.assigned_positions` is `player_id -> [zone, space]`, persisted
with the rest of the match, and it is what a new play restores -- and what any
[Coaching Choice](coaching-choice.md#the-coaching-choice) opens on, which is the same restore
read from the other end.

- **Only a deliberate placement sets it**, via `set_assigned_positions`: the
  standard deal, and the close of any [Coaching Choice](coaching-choice.md#the-coaching-choice) a
  side actually took up. A run back must never write to it -- the scramble a
  steal forces is not a shape a coach chose, and the whole point is that the
  next new play undoes it.
- **A player with no entry is left where they stand.** That is how a game
  saved before this field existed keeps working: `restore_assigned_positions`
  moves nobody, the ordinary run back still finds them displaced, and the
  side's next window sets a real arrangement.
- **Restoring never charges exhaustion**, so it goes through
  `board.place_meeple` rather than `run_back_player`, and it skips the
  occupancy check on purpose -- the end state is a whole arrangement that was
  valid when it was saved, even though restoring it one meeple at a time
  passes through states that are not.
- **The two placements a restart owes still cost**: the post-goal kickoff fill
  and the out-of-bounds pickup run after the reset, at the usual rate, because
  nothing guarantees a coach's arrangement covers the space in question.

# The time out

Design notes for fool-bot; the map is [CLAUDE.md](../../CLAUDE.md), the rules are [living-rules.md](../living-rules.md).

## Where the code is

Since **Phase 5** of the model/Discord split both halves of a time out are
flow steps in [`d12ball/flow/windows.py`](../../d12ball/flow/windows.py):
`begin_time_out` and `finish_time_out`, beside the Coaching Choice they
buy. Names below without a path are the flow functions;
`d12ball.flow.windows.begin_time_out` and `D12Ball.finish_time_out` are the cog
wrappers that persist and post.

**What stayed is the confirm and the prompt it replaces.**
`TimeOutConfirmView` puts the cost in front of the coach and restores the
turn prompt verbatim on Back, and `d12ball.flow.windows.begin_time_out` drops the
prompt the click came from. Both are edits to a message, which is the
frontend's by principle 2. `MatchState.may_call_time_out` was always the
model's and is unchanged.

## The time out

A side out of [shooting range](shooting.md#where-a-shot-may-be-taken-from) may stop play
to buy **both** coaches a [Coaching Choice](coaching-choice.md#the-coaching-choice) -- see "Time
out" in the living rules. It was **ceding the ball** until 2026-09-16, and what
changed is the price: it used to be bought with possession and is now bought
with a minute and the side's one time out for the half.

**It is not a turnover.** The ball does not move, possession does not change,
ball speed is left alone and nobody runs back. That is why it is no longer
filed under [Turnovers](possession-and-turnovers.md#turnovers-steals-and-new-plays) at all -- there are
two kinds now, not three.

- **`MatchState.may_call_time_out` is the whole of when it is offered**, and it
  is three reads: `can_attempt_score` from the other end, the half's own count
  (`may_take_time_out`), and **not** under last possession. So one sentence in
  `build_turn_prompt` explains both missing buttons, and `PlayerActionView`
  never builds the shot and the time out together. It is deliberately **not**
  conditional on having anyone to bring on: the window is the whole Coaching
  Choice, and the state with nobody to bring on needs all three substitutes to
  have come off injured.
  - **Last possession refuses it rather than ending the period** (the author,
    2026-09-16): *"you can do it on minute 29 but not on 30. You can do it on
    minute 14 but not 15."* Ceding was a turnover, so under last possession it
    ended the half like any other; a time out turns nothing over, so there was
    nothing for that rule to bite on. `begin_time_out` has no last-possession
    branch at all any more -- the button is never built there.
- **The once-a-half moved here from the new play.** `time_outs_used` is the
  set, `spends_time_out` is the only occasion that adds to it, and
  **`asks_declaration` and `spends_time_out` now share no occasion at all**: a
  new play asks without charging, a time out charges without asking. A new
  play's window is free and unlimited since 2026-09-16, so a coach who stops
  play early is still offered every later restart. What bounds coaching in open
  play is the two substitutions a half (`counts_against_the_half`), and that is
  now the only thing that does.
- **The confirm replaces the turn prompt rather than posting under it.** A time
  out spends a minute and the half's one pause, and it sits one button along
  from Maneuver, so `TimeOutConfirmView` puts the cost in front of the coach
  first. Both ends are `interaction.response.edit_message`, so it costs nothing
  out of the channel's edit bucket (see "Discord's rate limits" in [rate-limits.md](rate-limits.md)), and Back
  restores the prompt **verbatim** from a string the view carries --
  `build_turn_prompt` can no longer tell whether the handler was carrying the
  ball, so rebuilding it would quietly lose that line.
- **`pending_time_out` is persisted, and it means "a time out's windows are
  still running".** The whole of one happens either side of two Coaching
  Choices, and `call_time_out` resets the turn before the first one opens -- so
  by the time the second closes, nothing else in the match says how it got
  there and `finish_substitution_window` would fall through to a run back
  nobody owes. It is checked in `pending_prompt` ahead of the "no ball
  handler yet" branch for exactly the reason setup and halftime are, and
  `finish_time_out` clears it before dispatching so the state that follows
  speaks for itself.
- **It is answered as a reply.** The other coach's window is the same occasion
  (`finish_substitution_window` passes the occasion through rather than
  defaulting to `NEW_PLAY`), and neither coach is asked -- see
  `asks_declaration` under "The Coaching Choice" in [coaching-choice.md](coaching-choice.md). The reply costs the answering
  side nothing, so they keep their own time out.
- **The tail is a pickup the coach can cause themselves.** A Coaching Choice
  can re-deal a whole side, so a coach can rearrange their own handler off
  their own ball. **Possession stays theirs** (the author, 2026-09-16) and
  `finish_time_out` sends the nearest player either side of it to fetch it.
  - **That pickup is free**, and it is the one walk to the ball in the game
    that charges nothing. A time out costs a minute and no exhaustion, and a
    coach should not be billed for putting somebody back on a ball their side
    never lost.
  - **`pending_recovery_from_time_out` is one fact read at both ends**, which
    is why it is not called `..._is_free`: the same flag says the pickup costs
    nothing *and* that it is not a turnover, and both follow from the side
    fetching the ball being the side that had it all along.
    `apply_ball_recovery` reads it before the pickup clears it.
- **The clock cost rides on `pending_run_back_distance`, left at 1.** That
  field is what every tail step reads back for the clock, and the pickup spans
  a restart, so a time out has to say so there rather than pass it down a call
  chain. `call_time_out` sets it explicitly rather than leaning on the 1
  `reset_maneuver` already leaves, so the value reads as a deliberate fact and
  not a coincidence.
- **It is logged, and deliberately not as a turn action** (the author,
  2026-09-16). `EVENT_TIME_OUT` is its own kind: a possession is a run of
  consecutive `turn_action`s by one side and every event in a turn belongs to
  the last one before it, so logging a pause as a turn would invent a turn
  nobody played and hang the real turn's events off it. `stats.py` counts it on
  a row of its own, under the rule and with no share of the turns' denominator.
  `format_turn_actions` lists the two live actions and then whatever else the
  log holds, so `cede` goes on being reported for as long as a game remembers
  one and drops off the table on its own.
- **Dinky calls one to get an injured player off** (the author, 2026-09-16),
  and that is the only thing it uses one for. **This is the one call Dinky
  makes that looks like judgement and is not**: everything else it declines to
  do -- declining a challenge, slipping in, pulling the ball, and ceding, as
  this used to be -- is a weighing-up with no right answer, where an injured
  player rolls without their skill modifier for the rest of the game and can
  never recover. `DinkyAI.choose_action` checks it **after** the shot (a shot
  on is worth more, and the time out keeps) and **before** the maneuver (which
  is what Dinky does with nothing better to do). `play_ai_turn` dispatches it
  **ahead of `record_turn_action`**, since a time out is not one.
- **A game saved mid-cede comes back mid-time-out.** `CoachingOccasion._missing_`
  maps the old `"ceded"` value, and `from_dict` reads `declared_substitution`
  and `pending_cede` as the fallbacks for the two renamed fields. Reading a
  spent declaration as a spent time out is the conservative half of the change
  -- a new play's window is free now, so the worst it does is hold back a time
  out from a coach who only ever declared, and the half's end clears it either
  way. Nothing writes the old names, so they die out on their own; don't drop
  the fallbacks until no half-finished game can predate the change.
  - **The fallbacks name the *old* key, and that is exactly what a blanket
    rename across the file breaks.** One did, leaving
    `data.get("time_outs_used", data.get("time_outs_used", []))` -- which reads
    as a fallback and is not one. `LegacyCedeSaveTests` is the guard.

# The extreme shootout

Design notes for fool-bot; the map is [CLAUDE.md](../../CLAUDE.md), the rules are [living-rules.md](../living-rules.md).

## The extreme shootout

**Every game is settled.** A level score at full time opens the shootout -- see
"Extreme shootout" in the living rules -- and there is no setting for it: league
mode and the `tie_mode` field went with it, so `end_period` branches on the
score alone. A saved game still carrying `tie_mode` loads without it rather than
being skipped, which is what the retired-field filter in
`gamesaves/d12ball/storage.py` is for; nothing writes the key any more, so it
dies out on its own.

- **A level score opens a Coaching Choice first, not the shootout.**
  `end_period` hands off to `begin_full_time_coaching`, one substitution to
  each coach, and `finish_full_time_coaching` is the only caller of
  `begin_shootout` -- so **the six who shoot are the six on the field when the
  shooting starts**, which is after that window and not at the whistle.
  `pending_full_time_stage` and `pending_shootout` are therefore never both
  set, and `pending_turn_view` reads the first ahead of everything a turn
  leaves behind, exactly as it does for setup and halftime.

- **`D12Ball.advance_shootout` is the only reading of "what is this shootout
  waiting on?"**, and `pending_turn_view` answers the same three questions in
  the same order. Two of the four steps are the bot's own -- the reveal, and
  setting the next test up -- so a restart between them has no button anywhere,
  which is why `resume_pending_prompt` hands a shootout back to
  `advance_shootout` rather than posting a view. Same shape as the run back and
  the halftime sequence, and the same reason.
- **The first round records no shooter.** `shootout_shooter` reads it off the
  coach's order and the count of who has been out, so the reveal has no state of
  its own to lose. Sudden death has no order to read, so there it is exactly
  what the coach picked -- and that is the only case
  `shootout_shooters_complete` can be false in.
- **The roll retires its own shooters**, in the same save as the goal
  (`finish_shootout_test`). That is what stops a restart between the roll and the
  injury tests re-rolling a test already paid for, and it is why
  `continue_shootout` may not call it again: round 1 derives its shooter, so a
  second call would quietly retire the next pair as well.
- **A part-built order lives on the match, not on the view.** Both menus are
  ephemeral -- neither coach may see the other's -- so a restart cannot
  re-attach to them and `restore_shootout_menus` re-registers them
  message-agnostically. A view rebuilt that way starts empty, so a coach who had
  ordered five would come back to none if the order lived there. **These are the
  last two views that need that**: the maneuver pick used to be a third and went
  public on 2026-08-25 (see [The maneuver prompt](maneuver-prompt.md#the-maneuver-prompt)), so an
  order that could be shown publicly would take the trick out of the codebase
  altogether. It cannot -- an order is a real secret, where a hand of cards
  never was.
- **`shootout_winner` is the whole of "is it over?"**, both rounds in one
  predicate: in round 1 a lead bigger than the tests still to come (which it
  counts by asking who is left, hence the retirement above), and in sudden death
  any lead at all, since that round started level by construction.
- **A shootout goal is a goal**, so `award_shootout_goal` writes the scoreboard
  *and* a separate tally. The tally is not the score: it is what the "cannot be
  caught" stop counts and what `shootout_score_line` reads for the summary,
  because 6:5 says nothing about how the game was won.
- **`shootout_heading` is only ever a question.** It names the test about to be
  rolled, and by the time a result is posted the shooters have been retired and
  that number has moved on -- so a result carries `shootout_running_score`
  instead.
- **"Your Order" is on the roll prompt**, not on the order prompt, because the
  order prompt is deleted the moment both sides have set theirs and the roll
  prompt is what a coach is looking at for the rest of the shootout. A coach may
  look at their own order whenever they like -- they just may not reorder it --
  so it answers ephemerally, and in sudden death, which has no order, it lists
  who they have left this round.
- **A shootout test costs no exhaustion and owes no injury checks either**
  (2026-08-15), which is the author's ruling and not a shortcut -- the rule for
  every other skill test read straight would give checks, so the living rules
  state the exception in both places. It is not one of the ways to gain a token,
  and an Exhausted shooter carries that into the shootout and out again
  unchanged. `finish_shootout_test` goes straight to `continue_shootout` rather
  than through `begin_injury_tests`.
  - **The `shootout_test` resume kind is still read and never written.**
    `dispatch_injury_resume` keeps the branch so a game saved between that roll
    and its tests finishes the way it started; nothing writes it any more, so it
    dies out on its own -- the same retirement `tie_mode` and `player_board`
    got. Don't drop it until no half-finished game can predate the change.

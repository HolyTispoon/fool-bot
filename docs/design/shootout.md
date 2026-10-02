# The extreme shootout

Design notes for fool-bot; the map is [CLAUDE.md](../../CLAUDE.md), the rules are [living-rules.md](../living-rules.md).

## Where the code is

Since **Phase 5** of the model/Discord split the shootout is flow steps in
[`d12ball/flow/periods.py`](../../d12ball/flow/periods.py):
`begin_shootout`, `advance_shootout`, `ask_shootout_orders`,
`ask_shootout_shooters`, `reveal_shootout_test`, `continue_shootout` and
`shootout_order_text`, alongside `begin_full_time_coaching` and the
window that comes before them. Names below without a path are the flow
functions; `D12Ball.advance_shootout` and the rest are the cog wrappers
that persist and post. `advance_shootout` is still **the one reading** of
what a shootout is waiting on -- it moved, it did not fork.

**The two ephemeral menus stayed**, with `D12Ball.restore_shootout_menus`:
a secret order has no public message to live on, which is Discord's own
trick and not a rule. The flow says what to ask and what a coach's own
order reads as; `ShootoutOrderSelectView` and `ShootoutPickSelectView` are
how it reaches one person and not the other.

**`D12Ball.post_shootout_prompt` is gone.** All three shootout questions
are `PendingPrompt`s now -- `SHOOTOUT_ORDER`, `SHOOTOUT_PICK`,
`SHOOTOUT_TEST` -- so `D12Ball.present` posts them through
`view_for_prompt`, the same table a restart restores through.

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
  set, and `pending_prompt` reads the first ahead of everything a turn
  leaves behind, exactly as it does for setup and halftime.

- **`advance_shootout` is the only reading of "what is this shootout
  waiting on?"**, and `pending_prompt` answers the same three questions in
  the same order. Two of the four steps are the bot's own -- the reveal, and
  setting the next test up -- so a restart between them has no button anywhere,
  which is why `GameService.resume` hands a shootout back to
  `advance_shootout` rather than handing back a prompt. Same shape as the run back and
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
- **A shootout test costs no exhaustion** (2026-08-15): it is not one of the
  ways to gain a token, so a shooter carries their tokens into the shootout and
  out again unchanged, less what an Overdrive or Boost adds.
- **Every shootout test opens with an injury check, and owes none after it**
  (the author, 2026-10-02, Law 17.4). Each shooter not already injured rolls
  one, Exhausted or not -- a flat check against the tokens they carry -- and a
  shooter it injures shoots the bare die. It is what gives Overdrive a price in
  the shootout: declared before the check, its drain counts toward it
  (docs/design/species-abilities.md). It replaced the 2026-08-15 ruling that a
  shootout test owed no checks, which was written because the rule for a skill
  test read straight would have given checks *after* the roll.
  - **The check is rolled inside the shootout test's own step**
    (`rolls.shootout_checks`, called by `shootout_test_step` before the dice),
    behind the same Roll button, not as a queue of `INJURY_TEST` prompts the
    way a skill test's checks are. Two reasons: the check has to come *before*
    the shot, and a shot waiting on a separate button per check would be two
    more clicks on every test of a shootout that already has twelve. It goes
    through `injuries.roll_injury_check`, the one reading of the check that
    `injury_test_step` rolls too, so it is the same bare d12 with only
    Kindlefinger's ignite on it (Law 15.3.4). The checks' dice are said, not drawn: the dice
    picture stays the two shooters' shot.
  - `finish_shootout_test` still goes straight to `continue_shootout` rather
    than through `begin_injury_tests`: nothing is owed after the shot.
  - **On Discord the prompt asks for Overdrive and Boost before it offers
    the die**: no Roll button while a coach is still to decide, and the
    press that settles the last decision puts it up on the same message
    (docs/design/species-abilities.md). A restart rebuilds the view off the
    position, so it comes back with Roll or without it as the position says.
  - **The `shootout_test` resume kind is still read and never written.**
    `dispatch_injury_resume` keeps the branch so a game saved between that roll
    and its tests finishes the way it started; nothing writes it any more, so it
    dies out on its own -- the same retirement `tie_mode` and `player_board`
    got. Don't drop it until no half-finished game can predate the change.

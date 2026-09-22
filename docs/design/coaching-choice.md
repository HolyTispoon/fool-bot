# The Coaching Choice

Design notes for fool-bot; the map is [CLAUDE.md](../../CLAUDE.md), the rules are [living-rules.md](../living-rules.md).

## Where the code is

Since **Phase 5** of the model/Discord split the window is a flow step:
`open_substitution_window`, `finish_substitution_window`,
`coaching_window_note`, `coaching_summary` and `apply_substitution` all
live in [`d12ball/flow/windows.py`](../../d12ball/flow/windows.py), and
the three
stage sequences that hand windows out (`advance_setup_stage`,
`advance_halftime_stage`, `advance_full_time_stage`) in
[`periods.py`](../../d12ball/flow/periods.py) beside it. Names below
without a path are the flow functions; `d12ball.flow.windows.begin_substitution_window`
and the rest are the cog wrappers.

**The window is the one prompt in the game whose message carries the
coach's own half-field**, so `d12ball.flow.windows.begin_substitution_window` posts it
itself rather than letting the presenter do it -- and that, with
the tutorial's Continue gate over the top of it, is why
`FollowOnStep.BEGIN_SUBSTITUTION_WINDOW` outlived the phase that was
expected to remove it. A step that wants to open a window **names** it.

**The menu's own clicks did not move and are not meant to.** Every step
inside the flow is an `interaction.response.edit_message` on one message
(see "The whole flow lives on one message" below), which is a Discord
economy rather than a rule. The views call the forwarding methods above
for the two things that *are* rules -- what a swap does, and what the
window changed.

**A swap that moves nobody is not a swap** (the author, 2026-09-21):
`swap_field_positions` refuses two players assigned to the same zone,
which the zone menu used to filter out of the second pick and nothing
in the model refused. The menu's second pick is the prompt's
`SwapOptions.partner_ids` -- everyone in a *different* zone -- and
moving a meeple within its zone is what space positioning is for.

**`heading` is not a lead-in.** The window's own opening line ("## Before
kickoff", "## Halftime") goes *inside* the prompt, above the allowance,
so it rides in `FollowOn.kwargs` as `heading` rather than as narration the
frontend would post above the menu. Narration named `lead_in` is whatever
step opened the window talking -- a new play's reset, the full-time
whistle -- and is its own message. A heading is an instruction to a coach,
which is why an AI side's window (below) never posts one; the time out's
announcement used to be a heading and is narration since step 7 of
docs/architecture-migration.md, because it has to be said whoever called
([time-out.md](time-out.md)).

**An AI side's window is the same prompt a coach's is**, answered through
the service one hub action at a time (`DinkyAI.choose`, step 7): the offer
is declared where Dinky has an injured player to get off and passed
otherwise ("**🟣 Dinky AI passed.**"), the hub gets a `substitute` per
injured player its allowance covers, a `reposition` onto the kickoff space
where `CoachingHubOptions.finish_refusal` says it must, and then `done`,
which says what a coach's Done says ("**Purple (Visiting) are done.** ...").
Until step 7 it was a routine, `run_ai_substitution_window`, that ran the
whole window inside `open_substitution_window` and worded it its own way.

## The Coaching Choice

Setup, a new play's substitution window and halftime are **one flow offering
the same four actions** -- formation, substitution, zone assignment, space
positioning. See "Coaching Choice" in the living rules. They were three flows
offering overlapping subsets of those four; a coach should not have to learn
three menus to do one job.

A fourth occasion joined them: the window between full time and the
[extreme shootout](shootout.md#the-extreme-shootout). It is the same flow, with **one
substitution and none of the other three actions** -- a shootout is played by
who is on the field and by nothing about where they stand, so formation, zone
assignment and space positioning would move meeples that never play again.

A fifth is [a time out](time-out.md#the-time-out), which is a new play's window bought
with a minute rather than handed out by the play.

- **`CoachingOccasion` carries every difference between the five**, as
  properties rather than as flags at the call sites: the substitution
  allowance, whether the declare-or-pass offer is put at all, whether the
  declaration is charged, whether a player taken off is retired to the back
  bench, and whether the three positional actions are offered at all. Anything
  that differs by occasion belongs on that enum, not in an `if` in the cog.
- **`spends_time_out` and `asks_declaration` are two facts, not one, and
  since 2026-09-16 they share no occasion at all.** A new play asks without
  charging (its window is free and unlimited); a time out charges without
  asking, the button that called it being the taking-up.
  `open_coaching_window` reads the second (open declared, however that came
  about) and `declare_coaching` the first (charge, unless this is a reply),
  which is why an occasion given for free and one paid for in advance can
  share the same code path. They used to agree on the first four occasions
  and part company only at the ceded ball; now they cross.
- **`offers_positioning` governs the arrangement as well as the menu**, which
  is one fact read at both ends: a window with no positioning in it neither
  opens on the coach's arrangement (`begin_substitution_window` skips the
  restore) nor records one (`finish_substitution_window` skips
  `set_assigned_positions`). Restoring at full time would rearrange the last
  board of the game, and recording would overwrite an arrangement nothing will
  ever read. `CoachingHubView` simply does not build the three buttons, rather
  than building them disabled -- there is nothing a coach could do to enable
  them.
- **Four substitution budgets, not one.** Setup is unlimited, so
  `substitutions_remaining()` returns **None** there -- callers have to tell
  that apart from a limit of zero, which is what `may_substitute()` and
  `substitution_allowance_label` are for. **`apply_substitution` asks
  `may_substitute` itself, before anybody moves** (step 6 of
  docs/architecture-migration.md); until then only the hub's button
  did, and a third new-play substitution sent through the driver went
  through with "No substitutions left." in its own narration. The
  button is built from the prompt's `CoachingHubOptions.may_substitute`,
  which is the same reading plus whether there is anybody to bring on. Open play's -- a new play's or a
  time out's, which draw on the same pot -- come out of
  `half_substitutions_used`, per side, cleared at halftime; halftime's two and
  full time's one are counted inside the window and charged to neither half.
  So a side can substitute seven times in a game.
- **Who may come on is one question, not six.** `MatchState.substitution_pool`
  takes a side and nothing else: the bench while anyone is sitting on it, the
  back bench once it has drained, minus anyone injured. It used to take the
  outgoing player, because the back bench was thought to open only for an
  injured swap -- **it does not**, and that reading left a side with three
  swaps behind them and a healthy six unable to substitute at all. See
  "Who may come on" in the living rules, and the 2026-08-10 correction in the
  rules log. Don't reintroduce the parameter: the answer is the same for all
  six, and a caller passing one is asking a question the rules do not ask.
  - The one state with nobody to bring on is **both benches spent**: three
    substitutions to drain the bench, and every one of the three who came off
    injured, since injury is the only thing that takes a card out of a pool.
    That is what the full-time window skips on and what disables the hub's
    Substitution button.
- **The counter is the only gate on a new play's window, and it gates the
  swaps rather than the window.** Nothing decides whether a side is *offered*
  one: "every new play offers the side restarting play a Coaching Choice,
  however many they have already had this half" (see "A new play always offers
  one" in the living rules), so `begin_run_back` names
  `BEGIN_SUBSTITUTION_WINDOW` unconditionally. A side with both substitutions
  spent still gets the rearrangement -- it is the swaps they have run out of,
  not the pause.
  - There **was** a second gate here, and it read the once-a-half that a new
    play's declaration shared with the ceded ball. That count moved onto the
    time out alone on 2026-09-16 and the window stopped being bounded by
    anything; the call site kept reading it under its new name
    (`may_take_time_out`) until 2026-09-21, which skipped a coach who had
    called a time out past every later restart in the half. See that date in
    docs/rules-log.md, and the regression test
    `test_a_spent_time_out_still_gets_the_window`.
- **The whole flow lives on one message.** Every step is an
  `interaction.response.edit_message`, and nothing in it ever sends another.
  That is the interaction-callback route, so unlike the board refresh it does
  not compete for the five-in-five bucket -- see "Discord's rate limits" in [rate-limits.md](rate-limits.md). It
  used to be a message per step, and a coach making two substitutions and a
  rearrangement put eight into the channel plus a board refresh apiece. One
  message also cannot go stale: every older prompt used to keep a live view, so
  a coach could scroll up and click a menu from three steps ago.
- **`CoachingView.show(..., moved=)` decides whether the image is re-sent.**
  Passing no `attachments` leaves the one already on the message alone, so only
  a step that actually moved something re-uploads. Opening a submenu does not.
- **A part-made pick lives on the view**, so a restart comes back to the hub.
  That costs almost nothing now: every action is one or two clicks, and a
  formation change is atomic.
- **What the coach *did*, though, lives on the match**, because the one message
  is also the thing that destroys it: each step's note is written over by the
  next, so "so-and-so comes on for so-and-so" is gone by the time the coach
  clicks Done. `pending_coaching_formation` (the shape at the open) and
  `pending_coaching_swaps` are what survive it, and `coaching_summary` reads
  them into the message the window closes with. Both are persisted, so a window
  resumed after a restart still closes with what was done before it, and both
  are cleared by `close_coaching_window` -- so the summary has to be built
  *before* the window is closed.
  - **Only the shape and the swaps.** Zone assignment and space positioning are
    on the board, and the board goes up the moment coaching ends. Reporting the
    shape as a change (`2-2-2 → 2-3-1`) rather than as a state is why the
    opening shape is recorded at all: a coach who changes shape and changes back
    did nothing.
- **A window opens on the arrangement its coach last settled**, restored by
  `begin_substitution_window` before anything else -- never on the scramble a
  run back left. A new play resets both sides before offering the window and
  setup runs on a fresh deal, so this only ever moves anybody at halftime, and
  the board refresh it asks for is conditional on having moved somebody. It is
  the guarantee for every occasion rather than a halftime step because the
  half-field a coach works from should show their own shape whatever brought
  them there. `repost_coaching_prompt` deliberately does *not* restore: that is
  a resume, and the window's own moves have already happened.
- **Setup, halftime and full time each have their own stage sequence**
  (`SETUP_STAGES`, `HALFTIME_STAGES`, `FULL_TIME_STAGES`), and
  `finish_substitution_window` routes back into whichever is running instead of
  offering the other side a response. The first two run **the side kicking off
  first** -- home at setup, the visitors at halftime. Nobody kicks anything off
  at full time, so home going first there is the author's call and not the
  position's.
- **A full-time window with nothing in it is skipped, silently.** Its only
  action is the substitution, so a side with an empty `substitution_pool` would
  get a Done button with extra steps. Halftime's extra-token stage skips the
  same way for the same reason. Every other occasion has three more actions to
  fall back on, so none of them skips. It is a genuinely rare state -- see
  "Who may come on is one question, not six" above.
- **The kickoff space is the only thing that can hold a coach in the flow, and
  since 2026-08-16 it holds every coach in every window.**
  `coaching_finish_refusal` refuses Done until *this* side has somebody on
  *their own* kickoff space -- `MatchState.kickoff_space_for`, read off the
  rule rather than off the ball, since an arrangement is set in windows where
  the ball is elsewhere. It used to ask only the side kicking off the coming
  period, and only at setup and halftime; it is now a property of an
  arrangement, which is what lets a goal restart without the conceding side
  dropping somebody back and paying for it. Full time is exempt because it
  positions nobody (`offers_positioning`). The AI is held to it at the same
  menu: `CoachingHubOptions.finish_refusal` carries the refusal, and Dinky
  repositions the nearest midfielder onto the space before it says it is
  done (`cover_kickoff_space` did the same at the end of its routine until
  step 7).
  - **The standard deal and all five formations already satisfy it** -- a
    midfield packed from a side's own end always reaches that side's kickoff
    space, on every board -- so this costs a coach nothing until they use
    space positioning to empty it deliberately. Board 6 is the only board
    where the two sides cover *different* spaces.
  - **`pending_kickoff_fill` survives as a fallback, not as a rule.** A game
    saved before this landed can hold an arrangement that leaves the space
    empty, and both developers run the bot against their own saves.
- **`LEGACY_HALFTIME_STAGES` is not dead weight.** Halftime used to run
  substitutions and any-zone repositioning as two stages a side; a game saved
  in either resumes at that side's hub. `from_dict` reads the old
  `pending_substitution_*` keys for the same reason. Both developers run the
  bot from their own tree against their own saves, so a half-finished game
  outlives the change that renamed things.

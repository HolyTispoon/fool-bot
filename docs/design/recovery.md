# Recovering a stuck game

Design notes for fool-bot; the map is [CLAUDE.md](../../CLAUDE.md), the rules are [living-rules.md](../living-rules.md).

## Recovering a stuck game

A restart re-arms exactly **one** message per game — the one recorded in
`turn_message_id` — so a game can come back with no working button anywhere in
its channel. `/d12ball resume` puts the question back up and
`/d12ball abandon_game` ends the ones nobody is going to finish. Both are open
to either player in the game, or to any game helper (`may_administer_game`,
which is `may_act_in_game` under the name these two read as) -- see
[Who may act on a game](permissions.md#who-may-act-on-a-game).

**So that is what a crash tells the coach to do.** The two catch-alls for an
unexpected exception -- `SafeView.on_error` for a click and
`cog_app_command_error` for a command -- share `ERROR_RECOVERY_ADVICE` in
`cogs/d12ball_helpers.py`: try again, then `/d12ball resume`, then the person
running the bot. They used to stop at the first of those, which is advice for
a dropped connection and for nothing else -- a bug in the flow is reached
identically on every click, and the turn it stranded is the thing resume
exists to put back. **The retry stays first, and is not hedged.** A coach
whose click failed cannot be told which kind of failure they have hit, the
transient one does clear on a second press, and a message opening by ruling
that out is both discouraging and, often enough, wrong. The traceback is in
`#logs` and on the host's console and nowhere a coach can see, so the last
step is the only way a bug resume cannot fix ever gets reported.

**The ephemeral views in the game are the shootout's two secret picks**, and
they are ephemeral for one reason: a coach must not see the other side's choice
before the reveal, and it is the only thing Discord offers that hides it.
`ShootoutOrderSelectView` is the shooting order and `ShootoutPickSelectView` the
sudden-death shooter. Everywhere else `ephemeral=True` carries a reply with no
buttons on it — an error, or a coach's own maneuver pick coming back to them.
Those two are also the only views a restart cannot re-attach to their message:
the bot never holds a durable handle to an ephemeral message, so there is no id
to give `add_view`.

**The maneuver pick used to be a third, and is not any more** — see
[The maneuver prompt](maneuver-prompt.md#the-maneuver-prompt). Its cards were never the secret;
the *pick* was, and an ephemeral reply to a public button hides that just as
well.

`restore_shootout_menus` is the way round it for the two that are left.
`add_view` **without** a message_id lands the view under a `None` key, and
discord.py's `ViewStore.dispatch_view` looks a click up by
`(message_id, custom_id)` and then falls back to `(None, custom_id)` — so the
menu a coach already has open starts answering again after a restart. It is safe
because the custom_ids already carry the game and the side, and because a
message_id match wins over the fallback, so the next menu the game opens is
dispatched to its own view as usual. The registration outlives the shootout,
which costs nothing: a stale click is answered rather than acted on. The
fallback is asserted against discord.py's own store in
`ShootoutMenuRestoreTests` (`tests/test_d12ball_shootout.py`), because the whole
thing rests on it surviving a library upgrade.

Three more ways a restart strands a game, none of them about ephemerality:

- The prompt was **deleted** before the restart. `close_maneuver_prompt` drops
  the maneuver prompt once both sides have picked and clears `turn_message_id`
  with it, and `close_turn_prompt` does the same for the shootout's order
  and shooter prompts. There is then nothing to re-arm.
- The process died **before the prompt it was about to send was recorded**.
- The process died **in the middle of a cascade whose next step was the bot's
  own**. This is the one that strands a game hardest: `continue_run_back`, the
  setup sequence, the halftime sequence, the full-time one and the shootout are
  driven from a live interaction, so there is no button anywhere and nothing
  will ever pick the state back up.

Two things follow from that:

- **`pending` in `d12ball/prompts.py` is the only reading of "what is this
  match waiting on?"**, and `pending_prompt` and `owed_step` are its two
  readers. It lives with no Discord in it -- that is the model/Discord
  split's first move, and the reasoning is in
  [model-discord-split.md](model-discord-split.md) -- and answers one of two
  ways: a `PendingPrompt` -- a `PromptKind`, the line to ask it with, and the
  few parameters the question carries -- where somebody is asked, or a
  `FollowOn` naming the step the bot itself owes where nobody is.
  `D12Ball.pending_turn_view` is the Discord mapping over the first --
  `view_for_prompt` is the one place a kind becomes a `discord.ui.View`, and
  the `ask` passes through untouched -- and returns `None` for the second,
  because there is no button to restore for a step the bot owes. Startup
  re-attaches the view it returns to the message the prompt is already on,
  and skips (and logs) a game it gets `None` for; `GameService.resume` hands
  the same prompt back and `D12Ball.resume_game` posts it on a fresh message,
  through `render_prompt`, so it comes back with its picture. A second copy
  of that branch chain is how a resume comes to offer a different prompt from
  the one a restart restores -- and, once a web app asks the same question, how
  the two frontends come to disagree about whose turn it is. Its ordering
  carries real decisions —
  setup, halftime, the window before the shootout and a
  [time out](time-out.md#the-time-out) are checked ahead of "no ball handler yet"
  because all four leave `active_player_id` None, and a maneuver is recognised
  by `challenger_id` rather than `pending_action`, which `choose_challenger`
  clears.
- **A state whose next step is the bot's is run, not re-asked**, and
  `owed_step` is what says which those are: a stage of setup, halftime or
  full time with no window open, a pickup nobody need make, the tail of
  a time out, a run back with only forced placements left, a loose ball both
  sides have answered, a won card with nothing to ask. Each names a
  `FollowOnStep` (`ADVANCE_SETUP_STAGE`, `ADVANCE_HALFTIME_STAGE`,
  `ADVANCE_FULL_TIME_STAGE`, `ADVANCE_SHOOTOUT`,
  `FINISH_TIME_OUT`, `BEGIN_BALL_RECOVERY`, `CONTINUE_RUN_BACK`,
  `RESOLVE_LOOSE_BALL`, `BEGIN_EFFECT_RESOLUTION`) and `GameService.resume`
  runs it through the same loop a click runs through. That is the whole
  difference between resume's two callers, and the reason `pending_prompt`
  returns a prompt, and `pending_turn_view` a view, rather than either
  posting it.
  - **A state waiting on the AI is run the same way**, and there is no
    view for it either. Since step 7 of
    [../architecture-migration.md](../architecture-migration.md) an AI
    side's extra token, shootout order or shooter, Coaching Choice and
    pickup are the prompts a coach gets, answered by the service inside
    the run that reaches them (`driver.ai_action`,
    [game-service.md](game-service.md)); a save waiting on one is a run
    that never finished. `resume` answers it and runs on ("the AI's
    choice"); startup re-arms nothing for it and logs the game, as for
    an owed step; `pending_turn_view` is `None` for it. Step 5 had made
    those states owed steps of the bot's (`RUN_AI_COACHING_WINDOW` was the
    seventh member), which step 7 took back out.
  - **The chain used to answer `PLAYER_ACTION` for four of those states** (a
    run back with nothing left to ask, a loose ball both sides had answered,
    a choiceless effect, the tail of a time out), so startup re-armed a
    `PlayerActionView` over them and a turn action was *applied* mid-cascade
    -- finding 1 of [../web-app.md](../web-app.md). Step 5 of
    [../architecture-migration.md](../architecture-migration.md) closed it:
    the fallbacks are `FollowOn`s, `driver.answer` refuses every action while
    one is owed (`STEP_OWED`), and the resume ladder that had moved from the
    cog into `GameService.resume` with its own order is gone -- see
    [game-service.md](game-service.md). **The shootout's own reading did not
    fork**: `advance_shootout` moved whole, and the chain answers its three
    sub-states in the same order, with the same asks the step puts up
    (`shootout_order_prompt`, `shootout_pick_prompt`).
  - **That every one of those states reads back the same after a save and a
    load is asserted**, window by window and shootout sub-state by sub-state,
    in `WindowStateSurvivesASaveTests` (`tests/test_d12ball_periods_flow.py`).
    A window is the longest wait in the game, so it is where a lift would show
    up as a game that comes back asking something else.
  - **Phase 6 closed the last two states a restart could not restore.**
    A game that went down inside a set-up's attempt-or-decline offer,
    or inside the pick of who takes a scoring opportunity, came back
    to the maneuver's *first-stage distance choice* -- the offer's own
    arguments lived on the view and nowhere a save could reach.
    `MatchState.pending_scoring_opportunity` records the question now
    and `PromptKind.SET_UP_ATTEMPT` / `PromptKind.SHOOTER_CHOICE`
    answer from it, so a restart in either comes back to the offer,
    shooter and numbers and all. Nothing a coach sees in a running
    game changed; what changed is what is on disk when they close the
    tab. Every kind is asserted to read back the same after a save and
    a load in `test_a_prompt_survives_a_save_and_a_load`
    (`tests/test_d12ball_prompts.py`), which is the restart written as
    a test.
  - **Phase 6 moved the write that all of this rests on, and moved it the
    right way.** A resume reads the match out of the save file, so what is on
    disk when a prompt goes up is the whole of what a restart has. Until
    Phase 6 each cog wrapper saved between its own step and the next, so a
    cascade wrote the file several times and the *last* of those writes sat
    behind whatever had already been posted; `GameService.run` now
    writes once, after `driver.advance` has run everything that moves and
    **before** anything is sent. Fewer writes, and the one that matters is no
    longer behind a request that can fail. `driver.waiting_on` is
    `pending_prompt` re-exported and never a second reading, so a frontend
    that puts up what a run handed back and a restart that reads the file
    reach the same question -- which is the property this whole section is
    about.
  - **The third increment closed the last place a live prompt was built
    by hand rather than through the table.** `ScoreAttemptView.back`
    re-armed the set-up offer and then constructed
    `SetUpAttemptChoiceView` itself with arguments it had read off the
    match a line earlier; it now takes the `PendingPrompt`
    `retract_shot_step` ends on and renders it through
    `view_for_prompt`, which is the table a restart restores through.
    `send_challenger_prompt` is the same change on the other side of a
    turn. Neither was wrong -- both built the view a restart would have
    built -- but "both happen to agree" is what principle 3 is against,
    and there is one fewer place for them to stop agreeing.
  - **The last increment made two more states restart-safe, and one
    of them outranks everything above.** A tutorial note held behind
    Continue used to be a `TutorialContinueView` with the continuation
    in a closure -- never registered, so a restart left a dead button
    and a resume put up the thing the note explains *without* the note.
    It is `PromptKind.TUTORIAL_CONTINUE` now, over
    `D12BallGame.tutorial_gate`, read first of all by `pending_prompt`
    and by `GameService.resume`, because the position underneath is
    exactly what it was before the note went up and re-driving it would
    run what the note is explaining. `skip_tutorial` spends the gate
    the way the click would (`gates.continue_step`). The other is the
    run back's first answer: `RUN_BACK_PLAYER` then `RUN_BACK_SPACE`
    are two prompts for one answer and the view carried the first, so
    a restart between them re-asked it; `MatchState.run_back_pick`
    holds it now. A finished game reads as `PromptKind.GAME_OVER`, so
    a restart hands back the rematch buttons rather than a stale prompt
    off the last turn.
  - **What a restart still cannot restore**: a part-made coaching pick
    lives on the hub's sub-menus and nowhere else, and a Low Pass
    waiting on *which* of several teammates receives it reads back as
    the first-stage distance choice. Both are narrow crash windows in
    which nothing has been applied, so the coach re-picks.
    `driver.answer` refusing an action that does not match
    `pending_prompt` is what makes that safe rather than merely
    harmless -- the answer to the question they were looking at cannot
    be applied to the one they are handed back -- and since the last
    increment every click goes through it.

- **An open Coaching Choice is re-posted, never re-opened.**
  `repost_coaching_prompt` exists because opening a window calls
  `open_coaching_window`, which resets the substitution counter — resuming
  through it would hand a coach back the swaps they had already spent. It is
  checked ahead of the setup, halftime and full-time stages for the same
  reason: all three run their coaching through that one window.
- **`resume force:true` clears the turn**, via `reset_maneuver` and
  `close_coaching_window`, and asks the offense to choose again. It refuses
  during setup, halftime, a [time out](time-out.md#the-time-out) and the shootout --
  the window before it included: those are real positions in the game rather
  than a turn gone wrong, and clearing them would drop a coach's window -- or
  both coaches' shooting orders -- on the floor. A time out has a second
  reason: its own turn has already been reset, so the prompt a cleared turn
  puts up would be asking a side to act with no handler chosen.
  `offensive_choice` refuses in all the same states for the same reasons.
- **`/d12ball offensive_choice`'s refusals all point at resume.** "A score
  attempt is already in progress" was the symptom that started this:
  `pending_action` stays `"shoot"` for the whole post-goal sequence, since only
  `reset_maneuver` at the end of the turn clears it, so a restart during the new
  play's coaching window leaves it set with the window still open. The third
  refusal is a roll a coach still owes (see "Every roll is a coach's" in [maneuvers.md](maneuvers.md)), which
  `pending_action` says nothing about -- `choose_challenger` cleared it when the
  maneuver that led there began. The fourth is a time out, which leaves
  `pending_action` clear for the same kind of reason: the turn was reset before
  either window opened.
- **Abandoning archives, it does not delete.** The channel is the record of what
  happened, deleting one is the tightest rate limit Discord has, and keeping the
  saved game is what stops the PBD number being handed out twice (see the
  pruning note in [gotchas.md](gotchas.md)). `abandon_and_archive_game` moves the channel
  first because that is the only step that can fail — a half-ended game is worse
  than one still stuck — then clears `message_id` and `turn_message_id`, since
  startup restores views off those two and reads nothing about status.
  `D12BallGame.abandon()` accepts a game still in setup, which `finish_game`
  refuses; a game gets stuck before kickoff as easily as after it.
- **The model's half of abandoning is `GameService.abandon`**: the record's
  `abandon()`, saved. The cog clears its two message ids and calls it; the web
  app's `POST /api/room/{id}/abandon` calls it with nothing to clear. Everything
  else the command does -- the channel told, moved and stripped -- is Discord's
  (see [web-app.md](web-app.md), "Beyond the game").

**A bot run out of a git worktree keeps its own saved games.** `PROJECT_ROOT` in
`gamesaves/d12ball/storage.py` is resolved from that file's own path, so
`<checkout>/data/d12ball_games.json` is per checkout. Restarting "with updates"
from a different tree loads a different set of games, which looks exactly like a
game breaking on restart and is not something `/d12ball resume` can help with.
Check which tree the bot is actually running from before treating a missing game
as a bug.

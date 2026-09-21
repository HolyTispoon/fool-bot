# Migrating to ARCHITECTURE.md

**This is a worksheet, not a specification.** [ARCHITECTURE.md](../ARCHITECTURE.md)
is the target; this is the code read against it on 2026-09-21, what
falls short, and the order the gaps close in. Items are struck as
they land. When the migration is done, what outlives it moves to
`docs/design/` and this file goes. **Nothing in it is a rule.**

## The target, in one paragraph

Four parts. `d12ball/` is the game and knows nothing about Discord,
the web or files. `GameService` is the one door for a state change:
load the game, apply an `Action` through `driver`, save once, return
a `GameResult`. The Discord cog authorises the person, turns a click
into an `Action`, calls the service and presents the result. The web
app does the same over HTTP. The AI picks an `Action` like anyone
else. Read-only requests (a board, the stats, the rules) do not go
through the driver.

## What does not conform, 2026-09-21

Read against `main` at 19350b6 by three sweeps: the views, the cog
mixins, and the AI, tests and wire shapes. Line references are to
that commit.

### There is no service, and the cog is both service and presenter

- `D12Ball.dispatch_step_result` (`cogs/d12ball/core.py:1599`) runs
  the driver's loop, **saves**, redraws, posts, and re-enters the loop
  after each picture. Saving and presenting are interleaved in one
  method, which is the shape the architecture separates.
- `games` is loaded from disk and `RulesEngine` built inside
  `CoreMixin.__init__` (`core.py:342`, `:387`). A second frontend
  cannot get at either without constructing the cog.
- `driver.answer` and `driver.advance` are split (`Answered`,
  `SafeView.dispatch_answer`, `lines_posted`) so a view can edit its
  prompt with the answer's lines before the chain runs. That is a
  presentation concern spelled as two model calls.

### Persistence is everywhere

- `cog.persist(` is called at **28** sites in `cogs/d12ball_views/`
  and `self.persist(` at **16** in `cogs/d12ball/`. Four of the view
  sites exist because their branch "never reaches a dispatcher"
  (`rolls.py:113`, `loose_ball.py:415`, `coaching.py:178`,
  `base.py:526`); several are deliberate double writes
  (`rolls.py:414`, `shootout.py:635`). There is no one rule for when
  a view saves.
- Four cog sites save per step outside the driver's one save
  (`core.py:1301`, `effects.py:423`, `effects.py:813`,
  `turnovers.py:432`).

### Dead and forwarding cog methods

- **About 95 cog methods have no production caller.** 42 of the 45
  on `ManeuverEffectsMixin`, 14 on `TurnoverMixin`, 12 on
  `PeriodMixin`, 13 on `PresentationMixin`, 14 on `CoreMixin` -- the
  twelve `docs/web-app.md` lists and the rest. Every one is a Phase 6
  leftover: the driver runs the step, the wrapper stayed.
- Forwarders over the engine or a flow function with no caller:
  `record_turn_action`, `apply_substitution`, `apply_position_swap`,
  `apply_reposition`, `coaching_window_note`, `coaching_summary`,
  `cover_kickoff_space`, `run_back_space_prompt`, `build_goal_log`,
  `apply_exhaustion`, `describe_exhaustion_gain`, `tutorial_dice`,
  `tutorial_player_side`, the six `self.boards.*` forwarders.
- `post_then_dispatch`, `post_blocks_then_dispatch`, `run_step` are
  three dispatchers where one presenter over a result should do.

### Domain work still in the cog

- `resume_pending_prompt` (`cogs/d12ball/turnovers.py:253`) is a
  second "what is this match waiting on" ladder, with nine flags in
  its own order, each handed to a cog routine (`advance_shootout`,
  `advance_setup_stage`, `advance_halftime_stage`,
  `advance_full_time_stage`, `finish_time_out`, `continue_run_back`,
  `begin_ball_recovery`). None is a `FollowOnStep`. Finding 2 of
  `docs/web-app.md`.
- `begin_setup_coaching` loads the match and calls the flow itself.
- `/d12ball resume --force` decides which states force may not skip
  (`slash_commands.py:2161`), a rules list duplicated from the model.
- `pending_prompt` answers `PLAYER_ACTION` for three states where the
  bot owes a step (finding 1 of `docs/web-app.md`), so an action is
  accepted mid-cascade.

### Rules enforced only by a button

- `may_substitute` (`coaching.py:363`), `may_decline_challenge`
  (`turn.py:533`) and the same-zone swap filter (`coaching.py:756`)
  are checked when the buttons are built and nowhere in the driver.
  The model accepts the illegal answer.
- Option lists the view computes and the driver re-derives: the
  push-back distances (`effects.py:453`, duplicating
  `setup_pass_push_back_distances`), the speed targets
  (`effects.py:968`), the halftime extra-token candidates, the hub's
  four sub-menus.

### Setup and the lobby are outside the model

- Team pick, the AI's team draw (`random.choice`, `setup.py:575`),
  the coin toss (`random.choice`, `setup.py:661`), home-or-visiting,
  Dinky's tutorial answer and `initialize_standard_match` all run in
  `cogs/d12ball_views/setup.py`. The lobby's toggles mutate the game
  record in `lobby.py`. No service method, no prompt kind.
- Three shootout views call `driver_answer` directly and hand-roll
  the refusal so it lands on an ephemeral menu.

### The AI mutates through its own paths

- Nineteen `AIStrategy` methods are called from inside flow steps
  behind `side_is_ai` forks: `ai_turn_step` (`flow/turn.py:1066`),
  `write_ai_maneuver_picks`, `run_ai_substitution_window`,
  `ask_shootout_orders`, `ask_shootout_shooters`, every `offer_*` in
  `flow/effects.py`, `run_back_ai_placement`, and the loose-ball pick
  in `engine.py:2040`. Each calls the `*_step` the human adapter calls
  but skips the adapter, so the validation differs (the speed choice
  passes `distance_moved`, the human path does not).

### Discord in the model

- `RulesEngine` holds four emoji dicts the cog fills after load
  (`engine.py:276-307`), read at ~30 sites across the engine, the
  prompts and the flow.
- Twelve `<@id>` mention sites in `d12ball/`; nine sentences naming a
  channel, a row colour, a click or "only you can see".
- `engine.py` imports `render.py`, which imports Pillow.

### Transitional structures and tests

- `driver.runs()` and `can_answer()` are always true;
  `driver_answer` is an alias; the `FollowOnStep` member notes
  describe a table that no longer exists.
- `tests/flow_stubs.py` keeps a two-sided shape (`COG_METHOD_NAMES`,
  `runs_in_the_model`) whose cog side is empty, and patches
  `D12Ball.dispatch_step_result` at import so tests may stub cog
  attributes the driver never reads.
- Roughly 60 test call sites drive a dead cog wrapper by name.

## The plan

The architecture's migration order, mapped onto this code. Each step
leaves the bot playable and the three goldens byte-identical unless
the step says otherwise. Steps 1 to 4 landed together on the
`architecture-simplification` branch; what they settled is in
[docs/design/game-service.md](design/game-service.md).

### 1. `GameService` and `GameResult` -- done (this branch)

`gamesaves/d12ball/service.py`. The service owns `games`, the engine
and the single save. `apply_action(game_id, action)` is `driver.answer`
plus `driver.advance`, looped through the frontend's stops, saved
once, returned as a `GameResult`. Two more entry points for the steps
nobody is asked for: `begin(game_id)` opens the pre-kickoff window
after setup, and `resume(game_id)` is `resume_pending_prompt`'s
ladder with the Discord taken out -- it runs the step the bot owes or
hands back the prompt. `run_step(game_id, FollowOn)` is what a
command that names a step calls (`send_turn_prompt` for `--force`).

**The result is richer than the architecture's sketch, on purpose.**
Discord posts pictures of the position mid-run -- the loose ball's
snapshot, the tail of a maneuver, the pinned board of a new play --
and the goldens pin where. So the result carries the closed narration
groups in order, each tagged with the step that said it and, where the
frontend stopped to draw, the position as a dict. A web page renders
the same groups and the same boards. `public_messages` would lose the
order a coach reads.

**Batching stays the frontend's.** `Batching` is one object the
service is built with: the stops, the own-message steps, and what to
do at a stop (draw it, post the lines plainly, or carry them on).
`DiscordBatching` in `cogs/d12ball/core.py` is today's
`DRIVER_STOPS`, `DRIVER_OWN_MESSAGE`, `stop_draws_the_board` and
`post_stop`'s branches in one place.

### 2. One presenter -- done (this branch)

`D12Ball.present(interaction, game, result)` replaces
`dispatch_step_result`, `post_stop`, `post_then_dispatch`,
`post_blocks_then_dispatch` and `run_step`: write the board once if it
moved, post each group as the messages its step earns, draw each
picture from its snapshot, put up the prompt through `render_prompt`.
It saves nothing. `render_match_png` takes the position to draw so a
snapshot renders from the dict the service handed back rather than
from the save.

### 3. Every view through the service -- done (this branch)

`SafeView.apply(interaction, game, action)` calls the service, reports
a `Refusal` ephemerally, hands back the `GameResult`. A view renders
the answer's own lines as it likes (an edit of its prompt, the dice
between two of them) and calls `present` for the rest. Every
`cog.persist(` in the views goes, because the service has already
saved before the view renders anything -- which is the early save the
four load-bearing sites were doing by hand, made the rule. The
shootout's three direct `driver_answer` calls go the same way.
`Answered`, `dispatch_answer` and `lines_posted` go with them.

### 4. Delete the dead cog methods -- done (this branch)

The ~95 above, the forwarders, `runs`, `can_answer`, `driver_answer`,
`COG_METHOD_NAMES` and the cog side of `flow_stubs`. Tests that drove
a wrapper by name drive the same step through
`tests/flow_stubs.run_step(cog, interaction, game, match, member, ...)`,
which is the wrapper's signature with the member spelled.

### 5. The bot's own steps become the model's -- next

`begin_setup_coaching`, the three stage advancers, `finish_time_out`,
`begin_ball_recovery`, `advance_shootout` and `begin_halftime` become
`FollowOnStep` members or one `owed_step(engine, game, match)` in
`d12ball/prompts.py` (proposal 1 of `docs/web-app.md`). Then
`GameService.resume` is a call to `owed_step` and the three
`PLAYER_ACTION` fallbacks in `pending_prompt` go; `answer` refuses
while a step is owed. The `--force` rules list moves with it.

### 6. Rules a button holds move into the adapters -- next

`may_substitute` into `apply_substitution`, `may_decline_challenge`
into `_answer_maneuver_challenge`, the same-zone swap into
`swap_field_positions`; the view builds its buttons from what the
prompt offers. **Settled by the author, 2026-09-21:** a swap that
moves nobody is not a swap, so the same-zone case is a refusal. An AI
side's shot is never retracted -- not a rule of the game, a feature
of how the AI plays (it does not misclick) -- so `retract_shot_step`
refuses it and the AI's score attempt carries no Back button and
waits on nothing but the roll. `PendingPrompt` grows `options` per kind (proposal 4
of `docs/web-app.md`) so a view, the web app and the full-game
policy read the same list. One refuse-leaves-unchanged test per kind
per choice.

### 7. The AI chooses an `Action` -- next, its own PR

`AIStrategy.choose(prompt, match) -> Action` replaces the nineteen
methods, and `GameService.apply_action` loops while the prompt's side
is the AI's -- and stops at a roll, because every roll waits behind a
button either coach may press (CLAUDE.md, "Nothing rolls dice on its
own"); the AI answers choices, never dice. The `side_is_ai` forks in
`flow/turn.py`, `windows.py`, `periods.py`, `effects.py`,
`arrivals.py`, `turnovers.py` and `engine.py` go. **The goldens
change**, and the author has said how (2026-09-21): **the human's
exact voice, with the AI's name where the coach's mention would be.**
"Dinky has chosen to maneuver with X" and its neighbours go; an AI
answer reads as the adapter words a coach's, "Dinky" in place of
`<@id>`. That is the same substitution step 9's tokens make, so the
two are one pass: narration says `{coach:visiting}`, the presenter
renders a mention for a person and the name for the AI.

### 8. Setup and the lobby as service methods -- next

`create_game`, `pick_team`, `flip_coin`, `choose_home_or_visiting`,
`start_game` on the service; the randomness and
`initialize_standard_match` move with them; the views call them.
**Settled (decision 3, 2026-09-21): the Discord ids on `D12BallGame`
become optional** -- `guild_id`, `channel_id` and `message_id` as
`Optional[int] = None`, in their own commit under principle 6, since
that is a change to the saved record. Every existing save reads back
unchanged; a game the web app creates has no channel, and the startup
sweep skips one.

### 9. Discord out of the model -- next

Narration emits tokens (`{coach:home}`, `{team:purple}`) and the
frontend renders them; the emoji dicts leave the engine; the nine
sentences naming a channel become the frontend's captions;
`TEAM_COLORS` moves below `render.py`. The goldens regenerate once.

### 10. The web app -- last

On the same service, with `to_dict` on `GameResult`, `PendingPrompt`
and the roll details.

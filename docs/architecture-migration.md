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

- ~~`resume_pending_prompt` (`cogs/d12ball/turnovers.py:253`) is a
  second "what is this match waiting on" ladder, with nine flags in
  its own order, each handed to a cog routine (`advance_shootout`,
  `advance_setup_stage`, `advance_halftime_stage`,
  `advance_full_time_stage`, `finish_time_out`, `continue_run_back`,
  `begin_ball_recovery`). None is a `FollowOnStep`. Finding 2 of
  `docs/web-app.md`.~~ Step 5.
- ~~`begin_setup_coaching` loads the match and calls the flow itself.~~
  Step 1 (`GameService.begin`).
- ~~`/d12ball resume --force` decides which states force may not skip
  (`slash_commands.py:2161`), a rules list duplicated from the model.~~
  Step 5.
- ~~`pending_prompt` answers `PLAYER_ACTION` for three states where the
  bot owes a step (finding 1 of `docs/web-app.md`), so an action is
  accepted mid-cascade.~~ Step 5.

### Rules enforced only by a button

- ~~`may_substitute` (`coaching.py:363`), `may_decline_challenge`
  (`turn.py:533`) and the same-zone swap filter (`coaching.py:756`)
  are checked when the buttons are built and nowhere in the driver.
  The model accepts the illegal answer.~~ Step 6.
- ~~Option lists the view computes and the driver re-derives: the
  push-back distances (`effects.py:453`, duplicating
  `setup_pass_push_back_distances`), the speed targets
  (`effects.py:968`), the halftime extra-token candidates, the hub's
  four sub-menus.~~ Step 6: `PendingPrompt.options`.

### Setup and the lobby are outside the model

- ~~Team pick, the AI's team draw (`random.choice`, `setup.py:575`),
  the coin toss (`random.choice`, `setup.py:661`), home-or-visiting,
  Dinky's tutorial answer and `initialize_standard_match` all run in
  `cogs/d12ball_views/setup.py`. The lobby's toggles mutate the game
  record in `lobby.py`. No service method, no prompt kind.~~ Step 8.
- ~~Three shootout views call `driver_answer` directly and hand-roll
  the refusal so it lands on an ephemeral menu.~~ Step 3.

### The AI mutates through its own paths

- ~~Nineteen `AIStrategy` methods are called from inside flow steps
  behind `side_is_ai` forks: `ai_turn_step` (`flow/turn.py:1066`),
  `write_ai_maneuver_picks`, `run_ai_substitution_window`,
  `ask_shootout_orders`, `ask_shootout_shooters`, every `offer_*` in
  `flow/effects.py`, `run_back_ai_placement`, and the loose-ball pick
  in `engine.py:2040`. Each calls the `*_step` the human adapter calls
  but skips the adapter, so the validation differs (the speed choice
  passes `distance_moved`, the human path does not).~~ Step 7.

### Discord in the model

- ~~`RulesEngine` holds four emoji dicts the cog fills after load
  (`engine.py:276-307`), read at ~30 sites across the engine, the
  prompts and the flow.~~ Step 9: tokens.
- ~~Twelve `<@id>` mention sites in `d12ball/`; nine sentences naming a
  channel, a row colour, a click or "only you can see".~~ Step 9: the
  mentions are `{coach:n}`, the row colour is the cog's caption, the
  channel sentences are reworded. "Only you can see what you picked"
  and the shootout's "Nobody else sees it" stay: a secret pick is a
  rule, not a medium.
- ~~`engine.py` imports `render.py`, which imports Pillow.~~ Step 9.

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
`architecture-simplification` branch, step 5 on `owed-step`, step 6
on `step-6`, step 7 on `step-7`, step 8 on `step-8`, step 9 on
`step-9` and step 10 on `claude/charming-edison-wj3bjx`; what they
settled is in
[docs/design/game-service.md](design/game-service.md), for steps
6, 7 and 9
[docs/design/model-discord-split.md](design/model-discord-split.md),
and for step 10 [docs/design/web-app.md](design/web-app.md).

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

### 5. The bot's own steps become the model's -- done (`owed-step`)

`d12ball.prompts.pending(engine, game, match)` is the one chain, and
it answers a `PendingPrompt` or a `FollowOn`; `pending_prompt` and
`owed_step` are the two readers over it, exactly one of which answers
for any position (decision 1 of `docs/web-app.md`). The four
`PLAYER_ACTION` fallbacks are `FollowOn`s now -- `CONTINUE_RUN_BACK`,
`RESOLVE_LOOSE_BALL`, `BEGIN_EFFECT_RESOLUTION`, `FINISH_TIME_OUT` --
and the steps only the ladder had named are seven new `FollowOnStep`
members with rows in `MODEL_STEPS` (`ADVANCE_SETUP_STAGE`,
`ADVANCE_HALFTIME_STAGE`, `ADVANCE_FULL_TIME_STAGE`,
`ADVANCE_SHOOTOUT`, `RUN_AI_COACHING_WINDOW`, `FINISH_TIME_OUT`,
`BEGIN_BALL_RECOVERY`), each still called inline where the flow
reaches it. `GameService.resume` runs what `owed_step` hands it and
its ladder is gone; `driver.answer` refuses every action while a step
is owed (`STEP_OWED`, with `Refusal.waiting_on` `None`), which closes
finding 1; the startup sweep skips and logs a game with no prompt to
re-arm. The `--force` rules list is `RulesEngine.turn_reset_refusal`
and the command is `GameService.reset_turn`. `NarrationGroup` and
`Narration` carry the step's `arguments`, so the challenge image is
drawn of the challenger the walk-in named. `begin_setup_coaching` and
`begin_halftime` did not need a member: neither is ever owed on a
save (the first is `begin`'s, the second runs inside the whistle).
`tests/test_d12ball_game_service_resume.py` resumes every fixture
with no cog imported. The goldens did not change.

### 6. Rules a button holds move into the adapters -- done (`step-6`)

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

What landed, in three commits. `RuleRefusal` (a `ValueError`
subclass, in `components.py`) is the one refusal channel: the
`MatchState` mutators, the flow and the adapters raise it,
`driver.answer` and the two cog catch sites catch it and nothing
else, so a `TypeError` or a `TeamSide` built from a bad wire value
is a bug again (finding 4); `driver.REQUIRED_ARGUMENTS` names what
each *choice* needs of the arguments its adapter had to leave
optional, so a hub `reposition` with no `space_index` is refused as
missing. The four rules moved as above. `PendingPrompt.options` is a
dataclass per shape (`PlayerOptions`, `SendOptions`,
`DistanceOptions`, `ManeuverOptions`, `RollOptions`,
`CoachingHubOptions`, `ShootoutOptions` and their neighbours in
`d12ball/prompts.py`), built once by `pending` through the `OPTIONS`
table and attached by `driver.advance` to a step's own `next` prompt
through `with_options`, so a frontend that renders `next` and one
that re-reads the chain hold one list; every adapter checks the
action against it, every view builds its buttons from it
(`SafeView.prompt_options`), and the full-game `Policy` and
`LEGAL_ACTIONS` read it and nothing off the match. The speed targets
are `RulesEngine.speed_targets` and the push back
`RulesEngine.setup_pass_push_back_distances`; `OVERDRIVE_ROLLERS`
is `prompts.py`'s; `D12Ball.tutorial_railed_option` and
`D12Ball.tutorial_beat` are gone, since a rail reaches a view on the
prompt. `tests/test_d12ball_driver_actions.REFUSED_ACTIONS` is a
refused answer per kind per choice, forty-three of them, each leaving
the match byte for byte. The goldens did not change.

**Two positions the one chain misread were found by the policy
walking them for the first time**, and read right in the same
commit: the speed step a Pressure that beats a Dribble Burst owes
the defense (the chain named `BEGIN_EFFECT_RESOLUTION` again, so a
resume there would have replayed the pressure), and whose the
steal's speed step is when a Smooth took the ball over during the
run back (`pending_run_back_stays_player_id`, as `finish_run_back`
hands it on, not the challenger). Neither is a rules change.

### 7. The AI chooses an `Action` -- done (`step-7`)

`AIStrategy.choose(prompt, game, match, side) -> Action` replaces the
nineteen methods, and `GameService.run` loops while the prompt is
the AI's -- and stops at a roll, because every roll waits behind a
button either coach may press (CLAUDE.md, "Nothing rolls dice on its
own"); the AI answers choices, never dice. The `side_is_ai` forks in
`flow/turn.py`, `windows.py`, `periods.py`, `effects.py`,
`arrivals.py`, `turnovers.py` and `engine.py` are gone. **The goldens
changed**, as the author said they would (2026-09-21): **the human's
exact voice, with the AI's name where the coach's mention would be.**
"Dinky has chosen to maneuver with X" and its neighbours went; an AI
answer reads as the adapter words a coach's -- "🟣 Glompex [MF] will
maneuver for Purple", "🟣 Dinky AI has picked their maneuver", "**🟣
Dinky AI passed.**", "**Purple (Visiting) are done.**" -- with the
name where `format_player(mention=True)` already put it for player 2
of a solo game. Step 9's tokens make the same substitution once for
every line, so the two are one pass.

What landed. **Whose question a prompt is** is the third reader over
the one chain, `d12ball.prompts.asked_sides(match, prompt)`: a table
by kind -- the side or the player the prompt names, the window's
side, the defending side for the two questions put to the defense,
possession for the rest, both sides' still-owed halves for the
maneuver pick and the shootout's menus, and nobody for the six rolls,
the tutorial's Continue and the finished game (`NOBODYS_QUESTIONS`).
`driver.ai_action(engine, game, match, prompt)` is the one place that
asks it for the AI: the first asked side that is the AI's gets
`engine.get_ai_strategy(game).choose(...)`, and a roll never reaches
a strategy. `GameService.run` calls it whenever the loop ends on a
prompt, puts the answer through `driver.answer` like a click (a
refusal is a bug in the strategy and raises), and carries on; a
resume runs a saved AI prompt on the same way ("the AI's choice"),
and the startup sweep re-arms nothing for one. **The AI's answer is
batched by the frontend**, as a coach's is: `Batching.carry_answer`
is `carry_from` for the answers nobody clicked, `DiscordBatching`'s
`AI_ANSWER_CARRY` mirrors what each kind's view passes, and the
result carries two new group tags -- `Narration.prompt`, the lines
that opened a question the AI answered before anybody saw it, and
`Narration.action`, its answer's own lines -- which `D12Ball.post_group`
posts as the kind's view would have (`post_ai_answer`: a hub note is
never a message, the shootout's first block is the coach's own
secret). A carried answer takes back the group the loop had just
closed after the step that asked, so an AI side's run back is still
one message and one board refresh (`CONTINUE_RUN_BACK` composes the
placement), which docs/design/rate-limits.md requires.

What it made the model say plainly. The AI is asked everything a
coach is: `pending` no longer answers a `FollowOn` for an AI side's
extra token, order, shooter, window or pickup, and
`RUN_AI_COACHING_WINDOW` is gone from the enum; `maneuver_pick_sides`
keeps an AI hand on the prompt until it has picked; the tutorial's
`maneuver_for(side)` rails both halves of the menu, Dinky's card as a
rail on Dinky's hand (`ManeuverHand.railed`); `CoachingHubOptions`
carries `finish_refusal`, the kickoff space a side must cover before
it may finish, and Dinky repositions onto it through the hub instead
of `cover_kickoff_space`. Two adapters name their step rather than
calling it -- the challenge's send is `AUTO_RESOLVE_CHALLENGER` and
the pickup is `APPLY_BALL_RECOVERY` -- so the walk-in's image and the
pickup's message are the same group whoever answered, and the two
views dropped their own rendering of them. The time out's
announcement is `begin_time_out`'s narration rather than the window's
heading (an AI caller has no menu to carry a heading on), so a
coach's turn prompt is edited into it and the menu follows. The
lead-in a step composed into an ask with `\n\n` -- the set-up offer,
the shooter choice, the pickup, the push back, the speed choice -- is
the prompt's `narration` now and `render_prompt` joins the two as
paragraphs, which changed no human message; `OFFER_SPEED_CHOICE` left
`DRIVER_OWN_MESSAGE`, where only the AI's inline path had needed it.
The shootout's two asks are built once (`shootout_order_prompt`,
`shootout_pick_prompt`) and read by the step and the chain alike, so
the coach's menu after the AI has set its order is addressed to them
alone, as it was. `Action` moved beside `PendingPrompt` in
`d12ball/prompts.py` (the AI builds one and the engine holds the AI;
the driver re-exports it). Finding 16 of `docs/web-app.md` is closed,
and the speed choice's `distance_moved` asymmetry went with it: the
argument was inert on the AI's path (Setup Pass charges its own
clock), and the one reading is the adapter's.

Tests. `tests/test_d12ball_driver_actions.AIAnswerTests` stands
every fixture in `tests/prompt_fixtures.py` in front of Dinky on
either side of the board and asserts its answer is accepted by
`driver.answer`, that every kind Dinky answers is reached, and that
no roll is ever put to it; the four AI owed cases became `ai_case`s
(a kind and an ask, no view), which `test_d12ball_game_service_resume`
runs on and `test_d12ball_prompt_mapping` re-arms nothing for.
`tests/ai_answers.py` is how a test asks Dinky a question -- the
prompt off the one chain, the answer off `driver.ai_action` -- and
the Dinky unit tests (substitutions, the time out, the gambit die,
the High Pass, the run back, the kickoff cover) ask it that way now.
`tests/test_driver_full_game.play` answers for the AI through the
same function, so the driver-level tutorial run plays Dinky's turns
as the service would.

### 8. Setup and the lobby as service methods -- done (`step-8`)

`create_game`, `pick_team`, `flip_coin`, `choose_home_or_visiting`,
`start_game` on the service; the randomness and
`initialize_standard_match` move with them; the views call them.
**Settled (decision 3, 2026-09-21): the Discord ids on `D12BallGame`
become optional** -- `guild_id`, `channel_id` and `message_id` as
`Optional[int] = None`, in their own commit under principle 6, since
that is a change to the saved record. Every existing save reads back
unchanged; a game the web app creates has no channel, and the startup
sweep skips one.

What landed, in two commits. **The ids first, on their own**: the
three are `Optional[int] = None` and keyword-only, so the required
`player_1_id` may still follow them and the saved dict keeps its key
order; the startup sweep, `fetch_game_channel`,
`game_channel_is_archived` and `game_for_channel` each skip or refuse
a game with none; `tests/test_driver_full_game.py` stopped fabricating
them. **Then the methods.** The rules are the record's:
`D12BallGame` gained `lobby_join`, `lobby_observe`, `lobby_leave`,
`configure` (every setting by the key a button carries --
`GAME_SETTINGS` -- from the enum or its wire string), `start_lobby`
and `reopen_lobby`, `pick_team`, `excluded_teams`,
`picking_player_number`, `team_pick_lands_on` and `ai_team_pool`,
each refusing with `RuleRefusal`, which moved to `d12ball/game.py`
(the leaf) and is re-exported from `components.py`; the record's
older mutators (`resolve_coin_toss`, `choose_home_or_visiting`,
`start_game`, `finish_game`, `abandon`) raise it too. `GameService`
gained the door over each -- `next_game_number`, `create_game`,
`discard_game`, the three lobby moves, `configure`, `start_lobby`,
`reopen_lobby`, `pick_team`, `flip_coin`,
`choose_home_or_visiting` -- each load, apply, save once, return the
record; a refusal is the exception itself and nothing is written.
The randomness went to the model, not the service (decision 7): the
coin is `RulesEngine.flip_coin` and the AI's team is
`AIStrategy.choose_team(pool)` over `D12BallGame.ai_team_pool`, the
same pool the picker greys out by. `flip_coin` seats Dinky visiting
in a tutorial, as the view did. `ADVANCED_MODULES` and the
last-module-on rule moved onto the record from `cogs/d12ball_helpers.py`.
The setup and lobby views, `open_new_game`, `open_lobby` and the
four lobby methods on the cog call the service and show what it
refuses; `cogs/d12ball_views` binds no `save_games` anywhere now
(`SAVING_VIEW_MODULES` is empty and `suppressed_view_saves` patches
nothing), and the two record-only writes left in the setup flow --
the message id after a post -- go through `GameService.save`.

Three things the bot does differently, none a rule of the game. A
lobby click saves before the message is edited rather than after,
as every click past the lobby has since step 3 (the ack-then-save
order was a guard against a slow disk on the live host, and it now
holds for none of the clicks). A tutorial's setup screen can no
longer put it on a nine-space board or in Advanced mode: the pin
was the lobby's only, and `configure` holds it for the whole of
setup. The two wordings of the Decent AI refusal are one. Finding 7
of `docs/web-app.md` is closed:
`tests/test_game_service_setup.py` opens a lobby, joins, configures,
starts, picks, flips, chooses and reaches the pre-kickoff window
through the service alone, on a record with no server, channel or
message. The goldens did not change.

### 9. Discord out of the model -- done (`step-9`)

Narration emits tokens and the frontend renders them; the emoji dicts
leave the engine; the sentences naming a row or a channel become the
frontend's or are reworded; `TEAM_COLORS` and `ChallengeSide` stay
below `render.py`; and, from decision 7 of `docs/web-app.md`, every
draw the game makes is the engine's. Four commits.

**The tokens** (`d12ball/tokens.py`). A sentence that names a team,
a role badge, a condition mark, a species ability or the coach it is
put to writes `{team:purple}`, `{role:fullback:orange}`,
`{condition:exhaust}`, `{species:cyborg}` or `{coach:1}` through the
five builders, and the cog renders every one once, at its door:
`D12Ball.rendered` over each `GameResult` the service hands back
(`apply_action`, `dispatch_step_result`, resume, begin, `run_step`,
`reset_turn`) and `render_text` for the sentences the cog composes
itself (the setup screen, the coin, the coaching prompt, a restored
ask, `player_label`). `DiscordTokens` in `cogs/d12ball_helpers.py` is
the resolver, with the fallbacks that were `formatting.py`'s beside
it, and the four dicts are the cog's -- read-only class defaults
until `cog_load` replaces them. **A coach is a player number, not a
side** (decision 4 said `{coach:home}`): the setup messages name a
coach before the coin has seated anybody, so the number is the one
key that names one at every point, and the record maps it to an
account, a name or the AI (`formatting.coach_name`); Discord
mentions the account and names the AI. The five bare `<@id>` sites
read "Someone" for an AI side, which had no account; addressed by
number the AI is named like anyone, which was the whole of the
change to the advanced and windows goldens (three lines, the
substitution step 7 asked for). Every other posted line was byte for
byte what it had been -- the goldens record what the cog *sends*, so
a rendering that is faithful leaves them alone. `MatchState` keeps a
`lead_in` on a pending Smooth or Mind Pull, so a save made mid-arrival
now holds tokens where it held emoji markup; both render, since a
token the resolver does not find is left as it stands.

**The sentences.** The maneuver ask says who picks and that the pick
is secret; which row is theirs is `build_maneuver_action_caption`'s,
composed in the cog over the model's own list of who is asked and its
gambit paragraph, so the posted text did not change. "Use the prompt
at the bottom of the channel" is "Use the current prompt", and the
lobby's leave refusal invites rather than shares a channel. The two
labels the frontend handed into narration went (finding 12): a shot
is worded by `begin_shot_step`, which the tutorial never did rewrite,
and a passed Coaching Choice names the side's coach off the record.
Those two are the only other golden change: the coach's shot reads
in lower case like the AI's, and the fixtures' "Coach" reads as
"Player 1".

**The engine and Pillow** (finding 14). `challenge_side` was a
rendering brief and the one thing that made `engine.py` import
`render.py`; it is `PresentationMixin.challenge_side` now, and
`tests/test_model_purity.py` gained a ratchet: the service and
everything a turn runs import with `PIL` and `reportlab` refused.

**The dice** (decision 7, finding 11). `RulesEngine.rng` is one
`random.Random`, every random call in the model goes through it, and
the engine hands each AI strategy the same stream when it takes it
on, so one seed fixes the dice and the AI together and nothing in
`d12ball/` reads the module `random`. Every d12 is rolled by
`scripted_or_random(engine, ...)`: the score attempt, the shootout
test, the own-goal roll and Mind Pull rolled their own before, which
is why the tutorial's script could not have fixed them. The goldens
seed the engine inside their recorders and are byte for byte what
they were. Per engine rather than per match: a seed on the save is a
new persisted field, which principle 6 keeps out of a refactor.

**Tests.** `tests/test_golden_service.py` is the fourth golden and
the first with no frontend (decision 9): the tutorial through
`GameService.apply_action` with the default `Batching`, every
`GameResult` written down with its tokens, and the final save.
`tests/test_d12ball_tokens.py` pins the spelling, the resolver's
three-step fallback, that every prompt's ask renders clean, and that
no cog transcript carries a token. Findings 6, 11, 12 and 14 of
`docs/web-app.md` are closed.

### 10. The web app -- last -- done (`claude/charming-edison-wj3bjx`)

On the same service, with `to_dict` on `GameResult`, `PendingPrompt`
and the roll details. What landed, in four commits; what it settled is
in [docs/design/web-app.md](design/web-app.md).

**The wire shapes** (finding 10). `d12ball/wire.py` holds the one
conversion, `jsonable`, which raises rather than falling back to
`str(value)`; every dataclass a frontend is handed has a `to_dict` --
the twelve option shapes and their four nested pieces, `PendingPrompt`
(each options class tagged with its `shape`), `Narration`,
`GameResult`, and the five roll details beside `IgnitedRoll`. It is
one-way: only `Action.from_dict` reads, and it builds the `PromptKind`
rather than leaving it the string a request carried, since `answer`
compares the kind by identity and every such action would otherwise be
refused as a stale click. `GameResult.to_dict` **leaves the position
out** unless `match=True` is written at the call site: a result is what
one person is shown, and the match holds the other side's maneuver pick
and an unrevealed shootout order. The two coercions the finding names
are in the adapters, where a value off a wire becomes a model type:
`TeamSide` on the coaching and shootout answers, and `Formation` in the
hub, which `apply_formation` words with `formation.value`.

**The lock** (decision 5, finding 13). `gamelocks.GameLocks`, one
`asyncio.Lock` per game, held from taking an action to having finished
showing what came back -- not around the apply, which is synchronous
and cannot be interleaved on one event loop, but around the renders,
uploads and edits after it, which can and which is a turn arriving in a
channel out of order. The Discord half takes it in
`SafeView._scheduled_task`, overriding discord.py's own click dispatch
because `interaction_check` runs before the callback and cannot hold
anything across it; `tests/test_game_locks.py` ratchets that the
method being overridden still exists.

**The app.** `webapp/`, an aiohttp server the cog starts in `cog_load`
when `FOOLBOT_WEB_PORT` is set, over its own service, games and locks.
`webapp/present.py` builds the controls, one builder per `PromptKind`
off `PendingPrompt.options` and nothing else; `webapp/keys.py` names
the viewer with an HMAC of the game id and the player number, derived
rather than stored (principle 6), and `/d12ball web_link` hands a coach
their own link. A page may only send back a control it was offered,
checked before the model sees it -- the web equivalent of a button
Discord never drew, which is also what keeps a hand-made request from
reaching an adapter with an argument no prompt offered (finding 4's
open edge). What a coach may not see is not sent: the rows for a side
this viewer does not coach are left out of the payload rather than
greyed in the page. The board is `render_match_image` with
`RulesEngine.cyborg_condition_ids`, which moved onto the engine from
`PresentationMixin` in its own commit, and a stop's picture is drawn
from the snapshot `Narration.board` carries.

**One thing the service gained**, and it is worth reviewing on its own
merits: `GameService.listeners`, which hands every result to whoever is
watching, after the save. A game is played from two sides and they need
not be on the same frontend -- a coach reading a web page has no
interaction to be replied to when the other coach clicks a button in
Discord, so the result the service produced for that click is the
page's only way to see the turn. It formats nothing and is not a second
presenter; each listener is called inside its own guard, since one that
raised would take somebody's click down with it.

**Tests.** `tests/test_web_purity.py` ratchets that nothing under
`webapp/` imports `cogs` or `discord`, by AST, so a lazy import inside
a function fails too. `tests/test_wire_shapes.py` walks every fixture
with no frontend imported: every prompt and every result is
`json.dumps`-able and every field of the three carried dataclasses is
on the wire. `tests/test_web_app.py` plays over a real HTTP client and
presses **every control of every fixture** through `apply_action`,
asserting none is refused -- principle 10 as a thing that can be run.
The goldens did not change.

## Where this leaves the two worksheets

The migration is done, and by the convention at the top of this file
both it and [docs/web-app.md](web-app.md) should now go, with what
outlives them in `docs/design/`. They have not, for one mechanical
reason: about ninety comments in the code cite this file by name and
about forty-five cite the review, mostly as "step 5 of
docs/architecture-migration.md" or "finding 4 of docs/web-app.md",
and retargeting those citations is its own change rather than a line
in this one. The settled design is in
[docs/design/web-app.md](design/web-app.md),
[game-service.md](design/game-service.md) and
[model-discord-split.md](design/model-discord-split.md); read these two
files as the record those comments point at.

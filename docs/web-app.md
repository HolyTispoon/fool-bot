# A web app over the D12 Ball model

**This is a worksheet, not a specification.** It is the review of the
model/Discord split read against the thing the split was for -- a
second frontend, a web app, over the same model as the bot -- and what
that review adds to the plan. **The order the work runs in is
[docs/architecture-migration.md](architecture-migration.md)'s**, and
nothing here re-sequences it; [ARCHITECTURE.md](../ARCHITECTURE.md) is
the target both are held to. The decisions already taken are at the
top so nobody re-opens them; the findings are below with where each
now stands, and each names the migration step that closes it; the
proposals are what those steps owe the web app that the migration
worksheet does not spell out. When the web app ships, what survives
of this moves to `docs/design/web-app.md` and this file goes.
**Nothing in it is a rule.**

The standard everything below is held to is CLAUDE.md's "The model and
the Discord layer", and the last of its principles in particular:
*the web app may not reach past the flow*. Where the review found a
rule a web app would have to copy, that is a finding against the
split, whether or not the bot plays correctly today.

## Decided, 2026-09-21

Settled in review of PR #263, read against the
`architecture-simplification` branch (PR #264), where steps 1 to 4 of
the migration had landed: `GameService` as the one door, one save per
click, `D12Ball.present` as the one presenter, every view through
`SafeView.apply`, and the dead wrappers gone, with the three goldens
byte-identical.

1. **"Asked" and "owed" are two functions.** `pending_prompt` is what
   a frontend asks; `owed_step(engine, game, match)` is what the
   service runs. `GameService.resume` already has the second one's
   shape, written as a ladder; the work is replacing the ladder's
   body with `owed_step` and reading it from `apply_action` too, so an
   action is refused while a step is owed. Putting a step inside a
   `PendingPrompt` would make a view know not to render it.
2. **`PendingPrompt.options` is a per-kind dataclass**, not a flat
   list. The hub has four lists and a formation menu; a flat list of
   strings would hand the model's structure back to the frontend to
   parse. `GameResult.prompt` carries the prompt, so a web page gets
   the options in the same response as the narration.
3. **The Discord ids on `D12BallGame` become optional**, in their own
   commit under principle 6. `Optional[int] = None` on `guild_id`,
   `channel_id` and `message_id` reads as absent on every existing
   save. A web game needs a record with no channel, and the startup
   sweep cannot be handed a fake one forever.
4. **Narration emits tokens, and the goldens record tokens.**
   `{coach:home}`, `{team:purple}`, `{role:fullback:purple}` and the
   like; rendered once, in `D12Ball.present` / `render_prompt`, the
   way a `PromptKind` is rendered into a view -- not in each view. The
   goldens pin the model's voice, so they pin the tokens.
5. **One process, one service, a per-game lock.** Both frontends call
   one `GameService` over one `games` dict in one process. The service
   is synchronous and the bot is one event loop, so a
   `dict[game_id, asyncio.Lock]` held by whoever owns the loop, taken
   around `apply_action` plus `present`, is enough; the web app in the
   same process shares it. A shared store with per-game rows is the
   day the web app has to outlive a bot restart, and not before.
6. **Setup and the lobby are service methods, not prompt kinds.**
   `create_game`, `pick_team` (with the AI's draw), `flip_coin` (with
   the coin), `choose_home_or_visiting` (with Dinky's answer) and
   `start_game` on `GameService`; the `random.choice` calls and
   `initialize_standard_match` move with them; the setup views call
   them. ARCHITECTURE.md says so in as many words: lobby operations
   do not pass through the turn driver.
7. **The `Random` is the engine's, or the match's, never the
   service's.** `GameService` constructs nothing and rolls nothing;
   one seedable `rng` per match through `RulesEngine` is what lets a
   web process replay either of two games.
8. **The AI chooses an `Action` through the same service**, and it is
   a step of its own with its own PR, because the goldens change: an
   AI answer becomes a group of its own, worded by the adapter. The
   author has said how it reads (migration step 7): the human's exact
   voice, with the AI's name where the coach's mention would be --
   the same substitution step 9's tokens make, so the two are one
   pass. The AI answers choices, never dice.
9. **The driver-side golden drives `GameService.apply_action`** with
   the default `Batching()` and pins the `GameResult`s -- that is what
   a web app inherits, where a golden through `driver.apply` alone
   would miss the save and the stops.

## What the review found, 2026-09-21

Read against `main` at 19350b6, the merge of the split's last phase.
Four readings were made -- the driver and the prompts, the cog and the
views, the model-side tests, and the infrastructure a second process
would need -- and the three findings marked **confirmed** were
reproduced by hand through `driver.answer` on the shared fixtures in
`tests/prompt_fixtures.py`, with no cog imported. The rest are read
off the code with file references; none is inferred from the docs.
**Where each stands** is against the `architecture-simplification`
branch, and is the part to keep current: strike a finding when the
step that closes it lands.

**Where the split holds.** Every in-turn click in the eight view
modules that play a turn mutates only through `driver.answer`; the four
contested rolls, both single-die rolls and every tie are the model's;
`MODEL_STEPS` covers `FollowOnStep` and `ANSWERS` covers `PromptKind`
exactly (31 and 32, checked programmatically); the AI's turn is the
driver's own (`START_TURN` called `ai_turn_step` inline until step 7,
which made it the service's: the AI answers the same prompts a coach
does, inside `GameService.run`, so a frontend cannot forget it); the
model reads no clock; `render.py` returns PNG
bytes with no Discord in it; the board is already JSON
(`BoardState.spaces`, `to_dict`). A whole game plays through
`driver.apply` with nothing from `cogs/` imported. What follows is the
remainder.

### Errors

1. ~~**The model accepts a turn action while it still owes a step.**~~
   *Confirmed; closed by migration step 5.* `pending_prompt` answered
   `PLAYER_ACTION` for the three "the bot's own next step" states its
   docstring names (`d12ball/prompts.py`, the fallbacks for a run back
   with only forced placements left, a ball recovery, an effect with
   no choice in it). On the `run_back_finished` fixture,
   `Action(PLAYER_ACTION, "maneuver")` is **Answered**: the maneuver
   starts, `AUTO_RESOLVE_CHALLENGER` is named, and `pending_run_back`
   is still set underneath. The design doc says a turn action
   mid-cascade became a stale click in Phase 6; it did, for every
   state where a *real* prompt reads ahead of it, and not for the
   states where the fallback *is* the prompt. On Discord the startup
   sweep posts that fallback view, so it is reachable after a restart;
   `GameService.resume` re-drives instead and never posts it, which is
   why nobody has seen it. This is what makes `apply_action` honest
   for a web request arriving mid-cascade, and it is the first thing
   left. **Closed**: `owed_step` names the step, `driver.answer`
   refuses with `STEP_OWED` while one is owed, and the sweep re-arms
   nothing over it.
2. ~~**Recovery is a second chain, and it mutates.**~~ *Closed by
   step 5.* On `main` it was
   `D12Ball.resume_pending_prompt`, nine flags in an order of its own,
   each handed to a cog routine that was not a `FollowOnStep`. On the
   branch that is `GameService.resume`: the ladder runs each owed
   branch itself through `run`, in the model's half, and the cog only
   presents. What is *not* closed is the second copy of the ordering
   -- the ladder still exists, it just moved. Decision 1 is what
   removes it: the ladder's body becomes `owed_step`, read by
   `pending_prompt`'s neighbour, and `apply_action` reads it too.
   **Done**: `GameService.resume` is `owed_step` run through `run`, or
   the prompt handed back; the ladder is gone.
3. ~~**Four rules are enforced only by a disabled button, and the model
   accepts the illegal answer.**~~ *The first confirmed. Closed by
   migration step 6 for the first three and `may_decline_challenge`;
   the fourth, the shootout's `side`, is finding 9's and stays open.*
   - The substitution allowance. `windows.apply_substitution` never
     asks `may_substitute`; the hub button does
     (`cogs/d12ball_views/coaching.py`). On the `coaching_hub` fixture
     a third new-play substitution goes through and the narration
     says "No substitutions left." while making it.
   - Shot retraction for an AI side: the view offers Back only when
     the possessing side has a human; `retract_shot_step` checks only
     `may_cancel_pending_shot`.
   - The same-zone swap: the view filters it out; `swap_field_positions`
     accepts it as a narrated no-op.
   - The shootout's `side`: the view resolves which side a click owes
     (`claim`); `_answer_shootout_order` takes the side as given.
   The migration worksheet adds a fifth of the same shape,
   `may_decline_challenge`. The second and third were the review's
   one question for the author -- rules, or button conveniences --
   and the author settled both under migration step 6: a swap that
   moves nobody is not a swap, so the same-zone case is a refusal;
   an AI side's shot is never retracted, not as a rule of the game
   but as a feature of how the AI plays, so `retract_shot_step`
   refuses it and the AI's score attempt carries no Back button.
4. ~~**`answer` can escape as a bare exception.**~~ *Confirmed. Closed
   by step 6: `RuleRefusal` is the one channel `answer` catches, and
   `REQUIRED_ARGUMENTS` refuses a `None` an adapter would dereference.* `_argument_mismatch` flags a missing argument only
   where the adapter gives it no default, and several adapters default
   a required argument to `None` and pass it into arithmetic: a hub
   `reposition` with no `space_index` raises `TypeError` out of
   `MatchState.position_meeple`, and the `except ValueError` in
   `driver.answer` does not see it. The same net is also too wide:
   `TeamSide(side)` on a bad wire value comes back as a `Refusal`
   whose sentence is the interpreter's, shown to a person and
   indistinguishable from a rule. On the branch an exception out of
   the middle of a step propagates through the service and the cog
   catches `ValueError` and reports it, having saved what ran -- so
   the escape is now a saved half-step rather than a lost one, which
   is better and not right.
5. ~~**The skill test's settled path saves late.**~~ *Closed by the
   service, and it closed the whole class.* `apply_action` writes the
   match before it returns, which is before any view has rendered
   anything, so the settled path, the four load-bearing early saves
   and the tie branches are all covered by the same line, and every
   `cog.persist(` in the views is gone.
6. ~~**Discord's mention syntax is generated inside the model.**~~
   *Closed by step 9.* Nine sites built `<@{id}>` -- `prompts.py`,
   `formatting.py`, `engine.py` and four flow modules -- the maneuver
   ask named the row colours, two refusal sentences said "the prompt
   at the bottom of the channel", and the engine held four emoji
   dicts. A coach is `{coach:n}` now and a mark is a token
   (`d12ball/tokens.py`), rendered once at the cog's door
   (`D12Ball.rendered`, `DiscordTokens`); the row is the cog's caption
   (`build_maneuver_action_caption`); the channel sentences are
   reworded. `coin_winner_player_number`'s mention-string fallback
   stays, per gotchas.md, for saves that predate the number. What
   stays in the model on purpose: "only you can see what you picked"
   and the shootout's "Nobody else sees it" -- a secret pick is a
   rule of the game, and a web page keeps the secret too.

### Gaps a web app would have to fill by copying

7. ~~**There is no model path from a lobby to kickoff.**~~ *Closed by
   step 8 (decisions 3 and 6): `GameService.create_game`, the lobby
   moves, `configure`, `pick_team`, `flip_coin` and
   `choose_home_or_visiting`, each over a rule on `D12BallGame`, and
   the three Discord ids optional;
   `tests/test_game_service_setup.py` walks the path with no frontend
   and no channel.* The team pick,
   the AI's team draw (`random.choice` in the view), the coin toss
   (`random.choice` in the view), home or visiting, the tutorial's
   "Dinky takes visiting", the pairing exclusions, which side a
   helper's pick lands on, the test game's shared coach,
   `initialize_standard_match` and the first `begin_setup_coaching`
   all live in `cogs/d12ball_views/setup.py`, `lobby.py` and
   `slash_commands.py`, with no service method. The startup sweep has
   its own reading of these states. `D12BallGame` requires a guild id,
   a channel id and a message id to exist; `tests/test_driver_full_game.py`
   fabricates all three (decision 3 is the answer).
8. ~~**Option lists the prompt does not carry, and the model does not
   expose.**~~ *Closed by step 6 (decision 2): `PendingPrompt.options`,
   a dataclass per shape, carries every list below and the rails;
   the `Policy` reads it and nothing else.* The proof
   is `tests/test_driver_full_game.py`'s `Policy`, which re-derives
   every one of these itself. Per kind:
   - `SPEED_DELTA_CHOICE`: the target list is computed inline in the
     driver *and* in the view, the view with a hard-coded 12 where
     the driver reads `BALL_SPEED_MAX`; the test policy holds a third
     copy.
   - `SETUP_PASS_PUSH_BACK`: `effects.setup_pass_push_back_distances`
     exists; the view computes its own and never calls it.
   - `HALFTIME_EXTRA_TOKEN`: field players minus injured, inline in
     both driver and view.
   - `DRIBBLE_ADVANCE_CHOICE`: `(1, 2)` hard-coded in both.
   - `PLAYER_ACTION`: no list of which of the three actions is live;
     the view assembles it from `can_attempt_score`,
     `may_call_time_out` and the tutorial's rails, and the driver
     refuses per choice through `turn_action_refusal`.
   - `COACHING_HUB`: the substitute-out list, the swap partner list,
     the reposition meeple and space lists are filtered in the views;
     only formations, the substitution pool and the swap candidates
     are model calls.
   - `RUN_BACK_SPACE`: a three-call recipe rather than one function.
   - `MANEUVER_ACTION`: which side is still owed a pick is re-derived
     from `offense_maneuver is None`.
   - The tutorial's rails: the driver refuses off them (`_rail`), but
     no prompt says which options are railed, so a second frontend
     asks `tutorial.resolve_choice` itself to grey the rest.
9. **Three prompt kinds carry no `side`.** *Open; with 8.*
   `COACHING_HUB`, `COACHING_OFFER` and the shootout kinds are
   answered with a `side` the frontend sends back, read off
   `pending_coaching_side` (the cog) or resolved by `claim` (the
   shootout view). The design doc's own warning applies: a frontend
   that has to send it back can send back a different one. Finding
   3's fourth item is what that costs.
10. **No wire shape.** *Open; last, with the web app.* With
    `GameResult` as the shared result, what wants a `to_dict` is
    `GameResult`, `Narration`, `PendingPrompt` (with its options,
    once 8 lands) and the roll details, and `Action.from_dict` for
    the request side; `StepResult`, `DriverRun`, `NarrationGroup` and
    `Answered` no longer cross the service and need none.
    `Action.kind` is compared by identity, so a kind arriving as a
    string is silently `MOVED_ON`; `formation` is checked against a
    dict keyed by the `Formation` enum, so a JSON string is refused.
    Both coercions belong in the adapters. `Action.arguments` are the
    adapters' keyword names, read off `inspect.signature`, which is a
    contract nobody has written down.
11. ~~**Randomness is process-global.**~~ *Closed by step 9 (decision
    7).* Fifteen `random.*` sites across `flow/`, `engine.py` and
    `ai.py` read one `random.Random` now, `RulesEngine.rng`, which the
    engine hands its AI strategies too; nothing in `d12ball/` reads
    the module `random`. Every d12 is rolled by
    `scripted_or_random(engine, ...)`, including the four that rolled
    their own (the score attempt, the shootout test, the own-goal
    roll and Mind Pull -- the loose-ball contest already went through
    it), so the tutorial's script can fix any of them. The stream is
    the engine's rather than the match's: a seed on the save is a new
    persisted field, and principle 6 keeps that out of a refactor.
12. ~~**Two labels cross into narration from the frontend.**~~
    *Closed by step 9.* A shot's `action_label` and the coaching
    decline's `coach_name` are gone: `begin_shot_step` words the shot
    (the tutorial never did rewrite the label) and
    `decline_coaching_step` names the side's coach off the record
    (`formatting.coach_name`, which `refresh_player_names` keeps
    current).
13. ~~**Two frontends cannot share the save file.**~~ *Settled by
    decision 5.* `save_games` is a whole-file rewrite on every call
    and `load_games` runs once, so a second process would overwrite
    the first's file with a stale copy of every game -- which is why
    there is one process. What remains of it is the lock: nothing
    today serialises load, apply, persist per game, so a double click
    that reaches `answer` twice before the first save is not refused
    by the kind check. The lock lands with the web app, and the bot's
    views take it too.
14. ~~**The engine imports Pillow.**~~ *Closed by step 9.*
    `challenge_side`, the one reason `engine.py` took `TEAM_COLORS`
    and `ChallengeSide` from `render.py`, is the cog's
    (`PresentationMixin.challenge_side`), and `test_model_purity`
    ratchets it: the service and everything a turn runs import with
    `PIL` and `reportlab` refused. `d12ball/rulebooks.py` still
    imports reportlab, as a drawing module may; the no-discord probe
    still needs it installed.
15. **What the driver path is not tested on.** *Open; each step
    takes its share.* The full-game run sends no hub edit (every hub
    answers `done`), no Overdrive, no decline, no `back`, never
    reaches the time-out pickup, the loose ball, the shooter's pick or
    the run back's player prompt -- ten kinds and four steps in all --
    and asserts refuse-leaves-unchanged only for the wrong-kind
    refusal. Seven pure flow suites need discord.py only because
    `tests/flow_stubs.py` imports the cog at module import. Nothing
    saves through the cog and answers through the driver, or the
    reverse. `tests/test_game_service.py` on the branch covers the
    service itself: one save before return, a refusal writes nothing,
    the batching at a stop, `resume`.

### What the review missed

16. **The AI chooses through its own paths.** Nineteen `AIStrategy`
    methods are called from inside flow steps behind `side_is_ai`
    forks -- `ai_turn_step`, `write_ai_maneuver_picks`,
    `run_ai_substitution_window`, the shootout's two, every `offer_*`
    in `flow/effects.py`, `run_back_ai_placement`, the loose-ball pick
    in `engine.py` -- each calling the `*_step` the human adapter
    calls but skipping the adapter. That is how the speed choice came
    to pass `distance_moved` on one path and not the other. The review
    read the AI's turn as the driver's own and stopped there; the
    architecture's "AI" section is the finding. *Closed by step 7:
    `AIStrategy.choose` hands back an `Action`, `driver.ai_action`
    asks it for the prompt's AI side (`asked_sides`), and
    `GameService.run` puts the answer through `driver.answer` like a
    click. The forks are gone; the speed choice has one reading.*

### Small things

Done on the branch: the eleven dead wrappers and eighty-two more,
`runs()`, `can_answer()`, `driver_answer`, the stale member notes in
`result.py`, the `ANSWERS` and `effect_choice_prompt` docstrings,
`flow/__init__.py`. ~~One stands: `post_group` (was
`post_narration_group`) keys the challenge image on
`match.challenger_id is not None` rather than on the group. The clean
fix is for the `AUTO_RESOLVE_CHALLENGER` group to carry its
`challenger_id` (the step's own kwarg) as a small `Narration` field;
it goes with step 5.~~ Done with step 5: `Narration.arguments`. The goldens pin `--- message` boundaries and view
class names, which is the frontend's batching; that is fine while they
drive the cog, and decision 9 is the golden a web app regresses
against.

## What this adds to the migration

The migration worksheet has the steps; these are the pieces of each
that the review settled and the migration does not spell out. The
numbers are the migration's.

- ~~**Step 5, the owed step.** `owed_step(engine, game, match) ->
  Optional[FollowOn]` in `d12ball/prompts.py`, read first by
  `GameService.resume` (whose ladder it replaces) and by
  `apply_action` (which refuses while it answers). The three
  `PLAYER_ACTION` fallbacks go; the `--force` rules list moves with
  it. The `AUTO_RESOLVE_CHALLENGER` group carries `challenger_id`.
  The two-frontend resume test lands here: save through the cog
  mid-cascade, restore through the service with no cog, and the
  reverse, for every prompt kind and every owed step.~~ Done: the
  two readers share one chain (`pending`), the four fallbacks are
  `FollowOn`s, and `tests/test_d12ball_game_service_resume.py`
  resumes every fixture in `tests/prompt_fixtures.py` with no cog
  imported, beside `tests/test_d12ball_recovery.py`'s Discord half.
- ~~**Step 6, the adapters refuse, and the prompt carries its
  options.** A `RuleRefusal` exception replaces `ValueError` as the
  refusal channel: the steps that raise with the sentence already
  written raise it, `answer` and the service catch only it, and
  `_argument_mismatch` treats a `None` default the adapter
  dereferences as missing, so a `TypeError` is a bug again. Every
  rule a button holds moves into its adapter (finding 3, plus
  `may_decline_challenge`). Then `PendingPrompt.options`, a dataclass
  per kind (decision 2), one kind at a time, each with the view and
  the full-game `Policy` moved onto it in the same commit. One
  refuse-leaves-unchanged test per kind per offered choice, made the
  way `test_a_refused_action_changes_nothing` makes it for the wrong
  kind.~~ Done, in three commits on `step-6`; the options landed as
  one commit for every kind rather than one per kind, because the
  attachment point (`with_options`, in `pending` and at the end of
  `driver.advance`) is one line and the views could not read half a
  table. `REQUIRED_ARGUMENTS` is how `_argument_mismatch` knows which
  `None` a choice will dereference. What the step records is in
  `docs/architecture-migration.md` under step 6.
- **Step 7, the AI** -- done. `AIStrategy.choose(prompt, game,
  match, side) -> Action` and a loop in `GameService.run` while the
  prompt is the AI's, stopping at a roll; the forks went, worded per
  decision 8. `game` is there for the one answer that names the AI (a
  passed window's `coach_name`, which step 9's tokens will take back)
  and `side` for the two prompts put to both sides at once. What the
  step records is in `docs/architecture-migration.md` under step 7:
  the third reader over the chain (`asked_sides`), the frontend's
  batching of an AI answer (`Batching.carry_answer`, the `prompt` and
  `action` tags on a `Narration`), and the run back kept to one
  message.
- ~~**Step 9, the voice, and the dice.** Tokens per decision 4; the
  coin winner stored as a player number (the mention-string fallback
  stays, per gotchas.md; the new write is the number); the two
  channel sentences and the maneuver ask's privacy sentences become
  the presenter's captions; `coach_name` and `action_label` go the
  same way. `TEAM_COLORS` and `ChallengeSide` move below `render.py`.
  The `Random` per match through `RulesEngine`, the four bypassing
  rolls first. The goldens regenerate once, for the tokens.~~ Done,
  in four commits on `step-9`; what the step records is in
  `docs/architecture-migration.md` under step 9. Three things the
  review did not spell out: a coach's token is a player number rather
  than a side, since a coach is named before the coin has seated
  anybody; the three cog goldens did *not* regenerate for the tokens
  -- they record what the cog sends, and a faithful rendering leaves
  them alone, so the only diffs were the AI named where "Someone" had
  stood in for its missing account and the two labels' wording; and
  the `Random` is per engine, not per match, because a seed on the
  save is a persisted field.
- ~~**Step 8, setup as service methods.** Decision 6's five methods,
  and decision 3's optional ids in their own commit.~~ Done, in two
  commits on `step-8`; what the step records is in
  `docs/architecture-migration.md` under step 8. Two things the review
  did not spell out: the rules went onto the record (`D12BallGame`
  refuses with `RuleRefusal`, which moved to `d12ball/game.py`) and
  the service is the thin door over them, so a web app validates a
  lobby click the way the bot does; and the randomness went to the
  engine and the strategy, not the service, per decision 7.
- **Step 10, the web app.** The wire shapes of finding 10; the
  per-game lock of decision 5, taken by the bot's views too; an
  asyncio server in the bot's process over the same `GameService`. A
  page that shows the board from `Narration.board` and `to_dict`, the
  groups as they close, the prompt's options as controls; every
  request one `Action` through `apply_action`.

## Tests

- **The `Policy` is the measure.** It reads `GameResult.prompt` and
  nothing else, and the loop is
  `service.apply_action(game_id, policy.action(result.prompt))`. A
  `Policy` that reads `result.match` to choose is a web app that
  would have to. It is principle 10 as a thing that can be run.
- ~~**A service-side golden**, once step 9 has settled the tokens: the
  windows golden's press script through `GameService.apply_action`
  with the default `Batching()`, pinning the `GameResult`s and the
  final save (decision 9). The three cog goldens stay, since they pin
  the batching a coach reads.~~ `tests/test_golden_service.py`, with
  step 9 -- the tutorial rather than the windows script, since the
  rails make it reproducible off the seed alone and the tutorial's
  press rule is the model's; the windows game's press script is the
  cog's, and would be a second copy of it.
- ~~**Refuse-leaves-unchanged per kind per choice**, from step 6 on.~~
  `tests/test_d12ball_driver_actions.REFUSED_ACTIONS`.
- **Two-frontend resume**, from step 5 on -- landed with it.
- **The purity probe grows one check**: `d12ball/flow/` and
  `d12ball/prompts.py` import with `PIL` refused as well as `discord`;
  and it skips, and reports, a module whose only failure is a missing
  third-party dependency, so it stops failing wherever reportlab is
  absent.

# A web app over the D12 Ball model

**This is a worksheet, not a specification.** It is the review of the
model/Discord split read against the thing the split was for -- a
second frontend, a web app, over the same model as the bot -- and the
plan that falls out of it, in the shape the split's own worksheet had:
what was found at the top, what is proposed under it with the open
questions marked, phases that each end on a stop a person can check,
and the answered parts cut as they land. When the web app ships, what
survives of this moves to `docs/design/web-app.md` and this file goes.
**Nothing in it is a rule.**

The standard everything below is held to is CLAUDE.md's "The model and
the Discord layer", principles 1 through 10, and the last of them in
particular: *the web app may not reach past the flow*. Where the
review found a rule a web app would have to copy, that is a finding
against the split, whether or not the bot plays correctly today.

## What the review found, 2026-09-21

Read against `main` at 19350b6, the merge of the last phase. Four
readings were made -- the driver and the prompts, the cog and the
views, the model-side tests, and the infrastructure a second process
would need -- and the three findings marked **confirmed** were
reproduced by hand through `driver.answer` on the shared fixtures in
`tests/prompt_fixtures.py`, with no cog imported. The rest are read
off the code with file references; none is inferred from the docs.

**Where the split holds.** Every in-turn click in the eight view
modules that play a turn mutates only through `driver.answer`; the four
contested rolls, both single-die rolls and every tie are the model's;
`MODEL_STEPS` covers `FollowOnStep` and `ANSWERS` covers `PromptKind`
exactly (31 and 32, checked programmatically); the AI's turn is the
driver's own (`START_TURN` calls `ai_turn_step` inline, so a frontend
cannot forget it); the model reads no clock; `render.py` returns PNG
bytes with no Discord in it; the board is already JSON
(`BoardState.spaces`, `to_dict`). A whole game plays through
`driver.apply` with nothing from `cogs/` imported. What follows is the
remainder.

### Errors

1. **The model accepts a turn action while it still owes a step.**
   *Confirmed.* `pending_prompt` answers `PLAYER_ACTION` for the three
   "the bot's own next step" states its docstring names
   (`d12ball/prompts.py`, the fallbacks for a run back with only
   forced placements left, a ball recovery, an effect with no choice
   in it). On the `run_back_finished` fixture,
   `Action(PLAYER_ACTION, "maneuver")` is **Answered**: the maneuver
   starts, `AUTO_RESOLVE_CHALLENGER` is named, and
   `pending_run_back` is still set underneath. The design doc says a
   turn action mid-cascade became a stale click in Phase 6; it did,
   for every state where a *real* prompt reads ahead of it, and not
   for the states where the fallback *is* the prompt. On Discord the
   startup sweep posts that fallback view, so it is reachable after a
   restart; `resume_pending_prompt` re-drives instead and never posts
   it, which is why nobody has seen it.
2. **Recovery is a second chain, and it mutates.**
   `D12Ball.resume_pending_prompt` (`cogs/d12ball/turnovers.py`) reads
   nine flags in an order of its own and hands each to a cog routine
   -- `advance_shootout`, `advance_setup_stage`,
   `advance_halftime_stage`, `advance_full_time_stage`,
   `finish_time_out`, `continue_run_back`, `begin_ball_recovery` --
   none of which is a `FollowOnStep`, so none is reachable from the
   driver by name. Its docstring says nothing there changes the match;
   every branch above the fall-through runs a step. This is finding 1
   seen from the other side: the model has no answer for "nobody is
   asked; run this", so the frontend keeps one. A web app copies it or
   strands the same games a restart strands.
3. **Four rules are enforced only by a disabled button, and the model
   accepts the illegal answer.** *The first confirmed.*
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
4. **`answer` can escape as a bare exception.** *Confirmed.*
   `_argument_mismatch` flags a missing argument only where the
   adapter gives it no default, and several adapters default a
   required argument to `None` and pass it into arithmetic: a hub
   `reposition` with no `space_index` raises `TypeError` out of
   `MatchState.position_meeple`, and the `except ValueError` in
   `driver.answer` does not see it. The same net is also too wide:
   `TeamSide(side)` on a bad wire value comes back as a `Refusal`
   whose sentence is the interpreter's, shown to a person and
   indistinguishable from a rule.
5. **The skill test's settled path saves late.** `SkillTestView.roll`
   answers, renders the dice, edits, posts the ignition, posts the
   verdict, refreshes the board, and only then reaches the
   dispatcher's save. A failed upload lets the next click roll again.
   The tie branch saves early and says why; the design doc's own
   "a fifth needs the same sentence" is this path.
6. **Discord's mention syntax is generated inside the model.** Nine
   sites build `<@{id}>` -- `prompts.py`, `formatting.py`, `engine.py`
   and four flow modules -- and `D12BallGame.coin_winner_player_number`
   reads a mention string back *as data* to find the coin winner. The
   maneuver ask also describes Discord affordances as play ("only you
   can see what you picked", the row colours), and two refusal
   sentences say "the prompt at the bottom of the channel". A web app
   renders every one of those verbatim, which is principle 5's "one
   voice" failing in the other direction: the voice is right, and it
   is speaking Discord.

### Gaps a web app would have to fill by copying

7. **There is no model path from a lobby to kickoff.** The team pick,
   the AI's team draw (`random.choice` in the view), the coin toss
   (`random.choice` in the view), home or visiting, the tutorial's
   "Dinky takes visiting", the pairing exclusions, which side a
   helper's pick lands on, the test game's shared coach,
   `initialize_standard_match` and the first `begin_setup_coaching`
   all live in `cogs/d12ball_views/setup.py`, `lobby.py` and
   `slash_commands.py`, with no `PromptKind` and no `create_game`. The
   startup sweep has its own reading of these states. `D12BallGame`
   requires a guild id, a channel id and a message id to exist;
   `tests/test_driver_full_game.py` fabricates all three.
8. **Option lists the prompt does not carry, and the model does not
   expose.** The proof is `tests/test_driver_full_game.py`'s `Policy`,
   which re-derives every one of these itself. Per kind:
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
9. **Three prompt kinds carry no `side`.** `COACHING_HUB`,
   `COACHING_OFFER` and the shootout kinds are answered with a `side`
   the frontend sends back, read off `pending_coaching_side` (the cog)
   or resolved by `claim` (the shootout view). The design doc's own
   warning applies: a frontend that has to send it back can send back
   a different one. Finding 3's fourth item is what that costs.
10. **No wire shape.** Only `FollowOn` has `to_dict`. `PendingPrompt`,
    `Action`, `Refusal`, `StepResult`, `DriverRun`, `NarrationGroup`
    and `Answered` have none; `DriverRun.detail` is `object`.
    `Action.kind` is compared by identity, so a kind arriving as a
    string is silently `MOVED_ON`; `formation` is checked against a
    dict keyed by the `Formation` enum, so a JSON string is refused.
    `Action.arguments` are the adapters' keyword names, read off
    `inspect.signature`, which is a contract nobody has written down.
11. **Randomness is process-global.** Fifteen `random.*` sites across
    `flow/`, `engine.py` and `ai.py`, no `Random` instance, no seed on
    the match. Two games in one web process cannot each be
    reproducible, and four rolls (the score attempt, the shootout
    test, the loose-ball contest, the effects roll) bypass
    `scripted_or_random`, so the tutorial's script cannot fix them and
    the goldens rely on the global seed.
12. **Two labels cross into narration from the frontend.** A shot's
    `action_label` (a button's word for it, rewritten by the tutorial)
    and the coaching decline's `coach_name` (a Discord display name).
    Both are documented; both mean principle 5's one voice depends on
    what each frontend passes.
13. **Two frontends cannot share the save file.** `save_games` is a
    whole-file rewrite of every game on every call -- atomic per write,
    no locking, no per-game granularity -- and `load_games` runs once,
    in the cog's constructor; the file is only what a restart reads.
    A second process would overwrite the first's file with its own
    stale copy of every game. There is also no lock around load,
    apply, persist in either frontend, so a double click that reaches
    `answer` twice before the first persists is not refused by the
    kind check.
14. **The engine imports Pillow.** `engine.py` takes `TEAM_COLORS` and
    `ChallengeSide` from `render.py`, which imports PIL and resolves
    twenty-odd fonts at import. Every web process that loads the model
    pays that, and `d12ball/rulebooks.py` imports reportlab the same
    way, which is why `test_model_purity` fails on any machine without
    it.
15. **What the driver path is not tested on.** The full-game run sends
    no hub edit (every hub answers `done`), no Overdrive, no decline,
    no `back`, never reaches the time-out pickup, the loose ball, the
    shooter's pick or the run back's player prompt -- ten kinds and
    four steps in all -- and asserts refuse-leaves-unchanged only for
    the wrong-kind refusal. Seven pure flow suites need discord.py only
    because `tests/flow_stubs.py` imports the cog at module import.
    Nothing saves through the cog and answers through the driver, or
    the reverse.

### Small things

- The transitional table is still described where it no longer is:
  `d12ball/flow/result.py`'s member notes (`OFFER_SPEED_CHOICE`,
  `OFFER_SETUP_PASS_PUSH_BACK`, `BEGIN_LOOSE_BALL`, `END_PERIOD`,
  `CONTINUE_RUN_BACK`'s "per-pass persist", `APPLY_BALL_RECOVERY`,
  `AUTO_RESOLVE_CHALLENGER`), the `ANSWERS` docstring in `driver.py`,
  `effect_choice_prompt`'s docstring in `prompts.py` (it says the gap
  is open; the code under it closed it), and `d12ball/flow/__init__.py`
  ("what has not yet" moved). `runs()` and `can_answer()` are always
  true. `_begin_maneuver_action_selection` duplicates `_lead_in_first`.
  `waiting_on` re-imports what the module already imports.
- Eleven cog wrappers have no callers (`auto_resolve_challenger`,
  `announce_uncontested_maneuver`, `begin_maneuver_action_selection`,
  `resolve_maneuver`, `begin_maneuver_skill_test`,
  `begin_effect_resolution`, `begin_injury_tests`,
  `continue_injury_tests`, `run_injury_test`, `build_effect_choice_view`,
  `build_run_back_view`), and `play_ai_turn` has none either.
- `post_narration_group` keys the challenge image on
  `match.challenger_id is not None` rather than on the group's tag,
  which is the one place the frontend reads the position to decide a
  picture instead of reading the step.
- A helper on Discord is handed both sides' secret shootout menus.
- The goldens pin `--- message` boundaries and view class names, which
  is the frontend's batching. That is fine while they drive the cog; a
  driver-side golden is the one a web app could regress against.

## Proposed

Nothing here is decided. Each item is a proposal with the reason
beside it; the ones the author has to settle are marked **open** and
collected again at the bottom.

1. **A third answer to "what is this match waiting on": nobody.**
   `pending_prompt` keeps returning a `PendingPrompt`, and a sibling
   `owed_step(engine, game, match) -> Optional[FollowOn]` returns the
   step the bot owes where there is one -- a run back with only forced
   placements, a ball recovery, an effect with no choice, a shootout
   between its two automatic steps, a setup or halftime stage. The
   frontend runs it through `driver.advance` and reads the prompt off
   the far side. `resume_pending_prompt` becomes that call and the
   startup sweep the same; the three `PLAYER_ACTION` fallbacks go, and
   `answer` refuses any action while a step is owed. This closes
   findings 1 and 2 with one function and is the first phase because
   every other phase reloads a save.
   - **Open:** whether `pending_prompt` should return the owed step
     itself, as a fourth thing a `PendingPrompt` can be, or whether
     "asked" and "owed" stay two functions. Two functions keeps
     principle 3's one reading of *asked*; one function keeps one
     reading of *waiting*. The proposal is two, with `owed_step` read
     first by everything that restores.
2. **Every rule a button enforces moves into its adapter.** The
   substitution allowance into `apply_substitution`, the AI-side
   retraction into `retract_shot_step`, the same-zone swap into
   `swap_field_positions`, and the shootout's owing side read by the
   model rather than sent by the frontend (proposal 4 carries it).
   Each with a test that walks every offered choice with an illegal
   argument and asserts `to_dict` unchanged -- the assertion
   `test_a_refused_action_changes_nothing` makes for the wrong kind,
   made for every refusal.
3. **A `RuleRefusal` exception replaces `ValueError` as the refusal
   channel.** The steps that raise with the sentence already written
   raise it; `answer` catches only it; `_argument_mismatch` treats a
   `None` default on an argument the adapter dereferences as missing.
   A `TypeError` out of the middle of a step is then a bug again
   rather than a Refusal or an escape.
4. **`PendingPrompt` grows `options`, read from the engine per kind,
   and `side` on the three kinds that lack it.** One function per kind
   in the model answers "what may be chosen here" -- the speed
   targets, the push-back distances, the extra-token candidates, the
   live turn actions, the hub's four sub-menu lists, the run-back
   spaces, which side is owed a pick, and which of the options the
   tutorial's rail leaves enabled. The views build their buttons from
   it, the driver refuses against it, and the full-game `Policy` is
   rewritten to need nothing but the prompt. **That rewrite is the
   test of principle 10**: a policy that reads a `match.` field to
   choose is a web app that would have to.
   - **Open:** whether `options` is a list of choices with their
     arguments, or a per-kind dataclass. The proposal is the latter,
     one per kind that has more than a choice string, because the hub
     has four lists and a formation menu and a flat list would carry
     them as strings.
5. **The lobby-to-kickoff sequence becomes prompts.** `PromptKind`
   gains the team pick, the coin toss and the home-or-visiting choice;
   the AI's draw, the coin and Dinky's answer are steps that roll in
   the model; `initialize_standard_match` and `begin_setup_coaching`
   are follow-ons. `D12BallGame` gains a `create_game` that takes the
   Discord ids as optional -- **open:** whether those become
   `Optional[int]` (a save-format change, its own commit under
   principle 6) or a web game fabricates them the way the full-game
   test does. The proposal is the former, since the startup sweep and
   `game_for_channel` cannot be handed a fake channel forever.
6. **Mentions and emoji leave the model.** Narration emits a token the
   frontend renders -- `{coach:home}` for the person, `{team:purple}`
   and `{role:fullback:purple}` for the marks -- and the coin winner is
   stored as a player number rather than a mention string (a legacy
   fallback that stays, per gotchas.md; the new write is the number).
   The maneuver ask's two sentences about privacy and rows become the
   frontend's caption. `coach_name` and `action_label` stay as they
   are, documented, until a second frontend shows they are a problem.
   - **Open:** the token syntax, and whether the tutorial golden's
     transcript should record tokens or rendered text. The proposal is
     tokens, since the golden pins the model's voice.
7. **A `Random` per match, threaded through the engine.** `RulesEngine`
   takes an `rng` at construction, the fifteen sites read it, the four
   rolls that bypass `scripted_or_random` go through it, and the
   goldens seed the instance rather than the module. A web process
   then runs two games in the same second and can replay either.
8. **One process hosts both frontends.** The web app is an asyncio
   server in the bot's process, sharing `D12Ball.games`, the one
   `RulesEngine` and the single writer, with a per-game
   `asyncio.Lock` around load, apply, persist that the bot's views take
   too. That is the cheapest thing that is correct, and it inherits
   the deploy story in collaboration.md unchanged -- one bot per token
   becomes one process per token. A shared store with per-game rows
   and versioning is the alternative if the web app has to outlive a
   bot restart, and it is a larger change to the cog than to the
   model.
   - **Open:** which. The proposal is one process, revisited only if
     the web app needs to be deployed apart from the bot.
9. **Wire shapes.** `to_dict`/`from_dict` on `PendingPrompt`, `Action`,
   `Refusal`, `StepResult`, `DriverRun` and `NarrationGroup`;
   `Action.kind` accepted as the kind's value; every enum-keyed check
   in an adapter coerces the way `TeamSide(side)` does. `detail` gets a
   `to_dict` per roll type, since the dice are what a web page draws.
10. **The import edge and the purity probe.** `TEAM_COLORS` and
    `ChallengeSide` move below `render.py` so the engine imports no
    PIL; `test_model_purity` skips a module whose only failure is a
    missing third-party dependency, and reports it, rather than
    failing the ratchet wherever reportlab is absent. `flow_stubs`
    imports the cog lazily, which frees seven flow suites for a CI
    without discord.py.
11. **The early save on the skill test's settled path**, with the
    sentence the other four carry.
12. **The stale docstrings and the dead wrappers go**, in the commit
    that touches each file for something else.

## Phases

Each ends on a stop somebody can check without the web app existing,
because the web app is the last phase and everything before it is the
model becoming honest enough to carry one. The order is by what each
phase reloads: a phase that restores a save needs finding 1 closed
first, and a phase that builds buttons needs the options to build them
from.

- **Phase W0 -- the owed step.** Proposal 1, and the two-frontend
  resume test that finding 15 says is missing: save through the cog
  mid-cascade, restore through `owed_step` and `advance` with no cog,
  and the reverse. *Stop:* `resume_pending_prompt` is a call to
  `owed_step`; the three fallbacks are gone; a maneuver mid-run-back
  is a `Refusal`.
- **Phase W1 -- the adapters refuse.** Proposals 2 and 3, and 11.
  *Stop:* every kind's every offered choice, given an illegal
  argument, leaves `to_dict` unchanged and raises nothing.
- **Phase W2 -- the prompt carries its options.** Proposal 4, one kind
  at a time, each with the view and the `Policy` moved onto it in the
  same commit. *Stop:* `tests/test_driver_full_game.py` reads no
  `match.` attribute to choose; the full game reaches every kind.
- **Phase W3 -- the voice.** Proposals 6 and 7; the three goldens
  regenerate once, for the tokens. *Stop:* `grep "<@" d12ball/` is
  empty; a game replays from its own seed.
- **Phase W4 -- a game with no channel.** Proposal 5, with 9 and 10.
  *Stop:* `tests/test_driver_full_game.py` starts from the lobby and
  fabricates no id.
- **Phase W5 -- the web app.** Proposal 8. A page that shows the
  board from `to_dict`, the narration groups as they close, and the
  prompt's options as controls; every request is one `Action` through
  `apply`. *Stop:* a game played half on Discord and half on the page,
  the same save, the same voice.

## Tests

- **The `Policy` is the measure.** It reads the prompt and nothing
  else, or the phase that left it reading `match.` is not done. It is
  the same rule as principle 10 and it is the one that can be run.
- **A driver-side golden**, once W3 has settled the tokens: the same
  press script as the windows golden, through `apply`, pinning the
  narration groups and the final save. The three cog goldens stay,
  since they pin the batching a coach reads.
- **Refuse-leaves-unchanged per kind per choice**, from W1 on.
- **Two-frontend resume**, from W0 on: every prompt kind and every
  owed step, saved on one side and restored on the other.
- **The purity probe grows one check**: `d12ball/flow/` and
  `d12ball/prompts.py` import with `PIL` refused as well as `discord`.

## Still open

Collected from above, for the author:

1. Whether "owed" is a second function beside `pending_prompt` or a
   fourth thing a `PendingPrompt` can be. (Proposal 1.)
2. The shape of `options`: a flat list or a per-kind dataclass.
   (Proposal 4.)
3. Whether the Discord ids on `D12BallGame` become optional, which is
   a save-format change, or a web game fabricates them. (Proposal 5.)
4. The token syntax for mentions and marks, and whether the goldens
   record tokens or rendered text. (Proposal 6.)
5. One process or a shared store. (Proposal 8.)
6. Two rules the review found only a button holds, worth confirming
   as rules before they move: may an AI side's shot be retracted at
   all, and is a same-zone swap a no-op or a refusal? Both are in
   finding 3; neither is in the living rules by name.

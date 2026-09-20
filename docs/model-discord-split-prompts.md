# Model/Discord split -- one prompt per phase

The prompts the phases of [model-discord-split.md](model-discord-split.md)
are run from, one per conversation. Each is self-contained: paste it whole
into a fresh conversation in the fool-bot checkout. They all begin with the
same preamble block, so it is written once here and each prompt says
`[PREAMBLE]` where it goes.

This file lives and dies with the worksheet: a phase's prompt is deleted
when that phase lands, and the file goes when the worksheet does. Nothing
in it is a rule -- the principles are the worksheet's, and CLAUDE.md's from
Phase 1 on.

Phase 0 has landed (PR #201), so there is no prompt for it. Phase 1 was
split in two because the worksheet itself said its emoji prerequisite
"lands first, on its own"; that half (1a) has now landed too, so only
1b's prompt remains. Phase 3 is one template run six times.

---

## [PREAMBLE] -- paste at the top of every prompt

```
You are working in the fool-bot repository, on the model/Discord split. Read
CLAUDE.md first, then docs/model-discord-split.md whole -- it is the
worksheet this work is being done from -- and then only the docs/design/
files this phase's section names. Everything below assumes you have.

Ground rules for every phase:

- Branch off a fresh `origin/main` before the first edit; never work on
  main; never force-push. One phase is one pull request, landed on main by
  PR, and the bot must be fully working at the end of it.
- The principles in the worksheet (or, from Phase 2 on, the "The model and
  the Discord layer" section of CLAUDE.md) are the review standard. In
  particular: nothing under d12ball/ imports discord or is async;
  `interaction` never crosses the seam; the save format does not change
  (no new key, default or fallback); narration text stays the model's and
  is not replaced by structured events; steps do not persist, the caller
  does; BoardRefresher and the mixin layout are not touched.
- Line numbers quoted in the worksheet are stale -- it says so itself.
  Find every function by symbol name (grep or an Explore agent), never by
  line, and re-measure any count you quote in a commit or PR from the tree.
- The safety net is tests/test_model_purity.py and
  tests/test_golden_transcript.py. Run the full suite
  (`python3 -m unittest discover -s tests`) before your first edit on the
  branch, to baseline it, and again before opening the PR. A phase that
  moves code must leave the golden transcript byte-identical; if it does
  not, that is a finding to report, not a file to regenerate. Only
  regenerate a golden (FOOLBOT_UPDATE_GOLDEN=1) when the diff is a wording
  change the author asked for, and then the regenerated files are in the
  PR as their own commit. A full run must not create data/.
- Save-suppression in tests goes through tests/save_patches.py; a test
  names a player by role via tests/roster.py.
- A rules question is the author's to answer (the user is the author). If
  you cannot tell whether something in the code is a bug or a deliberate
  rule, stop and ask rather than infer; docs/living-rules.md is the
  reference. Do not change a rule in this work. If the move surfaces one
  that looks wrong, note it in the PR and leave the behaviour as it was.
- Wide searches go through an Explore subagent; single lookups where the
  symbol is known go direct.
- Every phase ends on a bot stop -- manual play on a running bot -- that
  only the author can do. Your job is to hand it over: the PR description
  carries the checklist for that stop, taken from the worksheet's section
  for this phase, with anything your change added to it. Do not claim any
  of it was done. The live bot is the Windows checkout; nothing you do here
  reaches it until that tree pulls and restarts.
- When the phase lands, the worksheet is edited the way
  advanced-maneuver-matrix.md is: the phase's section is cut down to what
  is still open (or deleted if nothing is), and the phase table at the
  top marks it done. The design doc for each area the move touched is
  corrected in the same PR, with the reasoning, not only the new path.
  Your own prompt in docs/model-discord-split-prompts.md is deleted in the
  same PR. CLAUDE.md's map table changes only for a new module or a moved
  responsibility.
- PR description in the house shape: what this changes, why it is built
  this way, what was settled so nobody reopens it in review, testing (what
  ran, what did not and why), the bot-stop checklist, and the PR template's
  checkboxes (suite passes / rules change? / architecture change? / board
  image change? / new persisted field? / more Discord requests per click? /
  no data/ or one-off scripts in the diff).
```

---

## Phase 1b -- `PendingPrompt`, the keystone

```
[PREAMBLE]

This is Phase 1 of docs/model-discord-split.md, "PendingPrompt, and the
keystone". Phase 1a (team_emojis on the engine, RulesEngine.format_player_label)
has landed on main; confirm that before starting, because the two `ask`
lines that name a player depend on it. Read docs/design/recovery.md and
docs/design/cog-structure.md as well. This phase is a pure read: nothing in
it mutates a match, so if you find yourself writing to one, stop.

What moves -- new module `d12ball/prompts.py`:

- `PromptKind`, one value per distinct prompt the chain can return. The
  worksheet measured 26: the chain's own View classes plus the 9 the three
  builders add (6 effect prompts, 2 run-back, 1 loose-ball). Count them
  yourself from `pending_turn_view`, `build_effect_choice_view`,
  `build_run_back_view` and `build_loose_ball_view`; if you get a different
  number, say which the worksheet missed or double-counted.
- `PendingPrompt`: `kind`, `ask` (the line put above the view), and only the
  parameters the branches actually carry (`player_ids`, `player_id`,
  `side`, `maneuver_key`, `skill_type`, `free` -- verify against the
  branches; add nothing speculative).
- `pending_prompt(engine, game, match) -> PendingPrompt`: the whole chain
  from `D12Ball.pending_turn_view` (cogs/d12ball/core.py), moved, with the
  three builders folded in as kind-and-parameters:
  `build_run_back_view` -> RUN_BACK_SPACE(player_id) / RUN_BACK_PLAYER(player_ids)
  off `next_run_back_step`; `build_loose_ball_view` -> LOOSE_BALL_PICK(side,
  skill_type) off the loose-ball side helpers; `build_effect_choice_view`
  -> the effect prompts off `pending_effect_continuation` and
  `resolving_maneuver`. `self.games[game_id]` becomes the `game` parameter.
  The `None -> PlayerActionView` fallback becomes `PromptKind.PLAYER_ACTION`
  and stays exactly as deliberate as it is now; carry its comment over.
- Preserve the chain's ordering and every comment that explains the
  ordering. The order is the rule ("what is this match waiting on" has one
  answer), and this move must not change a single branch's outcome.

What stays in the cog:

- `pending_turn_view` becomes a mapping table: `PromptKind` -> the View
  constructor, and nothing else. Its two callers -- `on_ready`'s restore in
  core.py and `resume_pending_prompt` in turnovers.py -- keep their
  signatures and are otherwise untouched. Make the mapping a single function
  (`view_for_prompt(prompt)` or similar) that later phases can also use to
  render a `StepResult.next`, and say in its docstring that it is the only
  place a PromptKind becomes a View.
- The View constructors themselves.

Tests:

- Add tests/test_d12ball_prompts.py: for each PromptKind, a match fixture in
  that state and an assertion on `pending_prompt(...)`'s kind and
  parameters. These need no discord and must import under
  test_model_purity's finder -- that is the point of them. Also a test that
  the cog mapping covers every PromptKind (no kind without a View).
- The equivalence test that matters most: for every existing test fixture
  that reaches `pending_turn_view` today, the View class the new table
  returns is the class the old chain returned. Build it before you move the
  chain, run it against the old code to see it pass, then move.
- Golden transcript unchanged; test_model_purity green.

Docs, in this PR:

- The principles section of docs/model-discord-split.md moves into
  CLAUDE.md as a section of its own, "The model and the Discord layer", and
  the worksheet's copy is deleted -- a settled rule has one home. Keep the
  wording; do not soften principle 9's "until Phase 6 the cog wrapper holds
  that save" transition note, which every following phase relies on.
- CLAUDE.md's hard rule that `pending_turn_view` is the only reading of
  "what is this match waiting on" is rewritten: `pending_prompt` is the one
  reading, `pending_turn_view` is the Discord mapping over it. Same edit in
  docs/design/recovery.md.
- CLAUDE.md's map table: a row for `d12ball/prompts.py`.
- The worksheet's Phase 1 section is cut down to the milestone note
  (spectator page) and anything still open.

Bot stop for the author (put this table in the PR): the restart matrix from
the worksheet's Phase 1 section, every row, once by killing and restarting
the bot and once through `/d12ball resume`; plus resuming three or four
pre-branch saves in different states, on both machines. Hand it over; do
not claim it was run.
```

---

## Phase 1 milestone (optional, separate repo or scratch) -- the spectator page

```
The fool-bot repository has landed Phase 1 of docs/model-discord-split.md
(`d12ball/prompts.py`, `pending_prompt(engine, game, match)`). The worksheet
says a read-only spectator page is possible after it "with nothing further
moved", and that it is worth building before Phase 3 to prove the seam
against a real frontend rather than a plan.

Build the smallest thing that proves that: a local web page that, for one
saved game, shows the board as a PNG and the line "waiting on: <kind>
<parameters> -- <ask>". Use only: `gamesaves/d12ball/storage.load_games`
for the record, `pending_prompt` for the wait, and
`d12ball.render.render_match_image(match, catalog)` -- NOT the cog's
`render_match_png`, which is async, Discord-shaped and builds a caption out
of fetched emoji. Its `title` is optional and it captions itself from the
team names and period; put the PBD number and coaches on the page around
the image instead.

Rules: the page imports nothing from cogs/, derives no candidate list and no
"what is it waiting on" of its own (principle 10 -- if something is missing
from `pending_prompt`, that is a finding to bring back to the bot, not a gap
to fill here). It plays nothing. Report what the seam was missing, if
anything, as a list; that list is the input to Phase 2.
```

---

## Phase 2 -- `StepResult`, proved on Low Pass alone

```
[PREAMBLE]

This is Phase 2 of docs/model-discord-split.md, "StepResult, on one
vertical slice". Phase 1 has landed (d12ball/prompts.py exists and
pending_turn_view is a mapping table); confirm before starting. Read
docs/design/maneuvers.md, docs/design/gotchas.md (the swallowed save) and
the "The model and the Discord layer" section of CLAUDE.md, which is now
the principles' home.

Two things to settle first, and write down in the PR as settled:

1. The shape of `StepResult.next`. The worksheet writes it as
   `PendingPrompt | None  # or a follow-on step to run`, and Phase 3 relies
   on the second half: a lifted effect ends by naming a spine step that is
   still async and still in the cog (`finish_maneuver_resolution`,
   `offer_scoring_attempt_choice`, later `begin_run_back`,
   `begin_loose_ball`). So `next` needs a second variant, a small
   `FollowOn` naming that step by key with its arguments -- and it is
   transitional: Phase 6's driver runs follow-ons itself and the cog's
   dispatch of them goes. Design it as a closed set of keys, not a
   callable or a method name string the cog `getattr`s, and mark it
   transitional in its docstring.
2. A `PendingPrompt` in `next` is rendered by the same
   `view_for_prompt` the restore path uses. From this phase on, the live
   flow and the restart flow build the prompt through one table, which is
   the drift principle 3 exists to prevent.

What moves:

- `d12ball/flow/__init__.py`, `d12ball/flow/result.py` with
  `StepResult(narration: list[str], board_changed: bool, next: PendingPrompt
  | FollowOn | None)`.
- Low Pass and nothing else: `D12Ball.send_low_pass` (already sync, in
  cogs/d12ball/effects.py) plus `low_pass_movement_note` and the wording
  that `apply_low_pass` builds inline, into `d12ball/flow/effects.py` as a
  sync function returning StepResult. The `self.persist(game, match)` inside
  send_low_pass is stripped out -- and here is the one rule of this phase:
  `apply_low_pass` in the cog becomes call the step -> `self.persist(game,
  match)` -> post the narration -> refresh the board if `board_changed` ->
  dispatch `next`. The persist is not optional and it is before the
  dispatch. The worksheet explains why (a spine step ending in a prompt
  hands the turn to a click that reloads the match from disk); read that
  paragraph twice. This is the transition rule for Phases 2-5.
- The Winger set-up branch and the Skilled Pass continuation
  (`pending_effect_continuation`) come with it; they are why Low Pass is the
  slice. `send_low_pass` is shared by Skilled Pass's free pass, so that path
  is touched too -- test it.

Tests:

- Model-side tests for the new step, no discord: narration lines exactly
  equal to what the cog produced before (record them from the old code
  first, on the same fixtures, then move), board_changed true/false where
  the old `refresh_match_image` decision was, `next` correct for a plain
  pass, a pass into a stack (receiver pick), a Winger set-up, a free
  Skilled Pass.
- A test that the step does not save: run it under
  tests/save_patches.py's suppression and assert nothing tried to.
- A test on the cog wrapper that a save happens between the step and the
  dispatch (patch persist, patch the dispatched spine method, assert order).
- Golden transcript byte-identical (it reaches Low Pass); test_model_purity
  green; EveryMatchupResolvesTests green.

Docs: CLAUDE.md's new section gains `StepResult`, `FollowOn` (marked
transitional), the flow package and the transition rule for the persist;
map row for `d12ball/flow/`; docs/design/maneuvers.md notes where Low Pass
now lives; the worksheet's Phase 2 section is cut down.

Bot stop for the author (in the PR): three or four Low Passes -- one plain,
one into a stack on board 6 so the receiver pick fires, one as a Winger for
the set-up, one free off a beaten Skilled Pass -- and a restart in the
middle of the receiver pick, which is the effect-choice branch of Phase 1
catching it.
```

---

## Phase 3 -- one rank per PR (template; run six times)

Fill in the `RANK` block from the table below and paste the rest unchanged.
Do them in the order given; each assumes the previous has landed.

| Run | RANK block |
| --- | --- |
| 3a | `Rank O2 -- Dribble Advance and Dribble Burst. Self-contained: moves the handler and ends; the speed choice is the only prompt. No hand-off to the spine beyond finish_maneuver_resolution.` |
| 3b | `Rank O1 -- Skilled Pass, and the shared apply_low_pass(key=) wrapper. Low Pass moved in Phase 2; this is the rest of the rank. Expect it to be small; if it is not, something in Phase 2 was left half-moved and this PR says what.` |
| 3c | `Rank D2 -- Steal and Intercept. A turnover, so this is the first hand-off to begin_run_back: the step's next is a FollowOn naming it; begin_run_back stays async in the cog. take_ball_by_steal saves itself today -- strip it and the wrapper persists.` |
| 3d | `Rank D3 -- Pressure and Double Team. The own-goal branch (run_own_goal_roll stays in the cog; apply_own_goal_outcome saves itself today -- strip it and the wrapper persists) and pending_double_team reaching into the next turn. Read docs/design/possession-and-turnovers.md.` |
| 3e | `Rank D1 -- Deflect and Clear. Calls begin_loose_ball directly rather than through finish_maneuver_resolution; knock_ball_back saves itself today -- strip it and the wrapper persists. Read docs/design/loose-balls.md.` |
| 3f | `Rank O3 -- High Pass and Setup Pass. The hardest by a distance: the overshoot, the contest, out-of-bounds into begin_ball_recovery. throw_high_pass saves itself today -- strip it and the wrapper persists. Read docs/design/shooting.md and docs/design/loose-balls.md (the High Pass exemption).` |

```
[PREAMBLE]

This is one rank of Phase 3 of docs/model-discord-split.md, "the effects, a
rank per pull request". Phases 1 and 2 have landed, and so has every rank
listed before this one in the worksheet's Phase 3 table; confirm on
origin/main before starting. Read docs/design/maneuvers.md and the "The
model and the Discord layer" section of CLAUDE.md, plus the design doc the
rank block names.

RANK: <paste the rank block here>

The pattern is Phase 2's, applied to both cards of this rank, and this PR
does not invent a new one. For each card's `apply_*` in
cogs/d12ball/effects.py: the mutation and the wording move into
d12ball/flow/effects.py as a sync function returning StepResult; any
`self.persist` inside the moved code is stripped; the cog wrapper becomes
step -> persist -> post narration -> refresh if board_changed -> dispatch
`next`. Where the effect hands off to spine machinery that is still the
cog's (finish_maneuver_resolution, begin_run_back, begin_loose_ball,
offer_scoring_attempt_choice, run_own_goal_roll, begin_ball_recovery), `next`
is a `FollowOn` naming it -- the spine does not move in this phase, under
any provocation. Advanced-mode cost and benefit (`advanced_cost`,
`settled_maneuver_winner`) are engine questions already; the step asks them,
it does not re-derive them.

Before you move anything, pin the rank's wording. The golden transcript
reaches only one card of this rank (the tutorial plays Dribble Advance, Low
Pass, Pressure, Steal, High Pass and Deflect -- one per rank -- and none of
Dribble Burst, Skilled Pass, Intercept, Double Team, Clear or Setup Pass,
and no advanced cost). So: on the old code, on fixtures that reach both
cards contested and unchallenged, basic and advanced, record the exact
narration lines and the refresh decision, and write those into the
model-side tests for the new step. A rank whose lifted narration differs by
a character from the recording is a rank that moved a rule, and that is a
finding, not a regeneration.

Tests, beyond that: the step does not save (under save_patches suppression);
the wrapper saves between step and dispatch; `next` is right on every
branch, including the ones that end in a prompt (restart mid-effect is the
Phase 1 effect-choice branch catching it -- assert pending_prompt returns
the same kind before and after a to_dict/from_dict round trip in that
state); golden transcript byte-identical; test_model_purity green;
EveryMatchupResolvesTests green.

Docs: docs/design/maneuvers.md (and the rank block's doc) gain a line only
where the move changed something worth recording. Most ranks change nothing
there; a rank that wants a paragraph is a rank that moved a rule -- say so
in the PR if that happened. The worksheet's Phase 3 table marks this rank
done.

Bot stop for the author (in the PR): both cards of this rank, contested and
unchallenged, on two board sizes, in a basic and an advanced game; watch the
advanced cost fire; one restart mid-effect. Plus whatever this rank's
hand-off adds (a run back, a loose ball, an own goal, a ball recovery).
```

---

## Phase 4 -- the spine

```
[PREAMBLE]

This is Phase 4 of docs/model-discord-split.md, "the spine" -- the biggest
single phase and the one the worksheet says to resist splitting badly. All
six Phase 3 ranks have landed; confirm on origin/main. Read
docs/design/sending-a-player.md, docs/design/possession-and-turnovers.md,
docs/design/loose-balls.md, docs/design/species-abilities.md (the arrival
gate) and docs/design/maneuvers.md (injury tests, own goals), and the "The
model and the Discord layer" section of CLAUDE.md. Do not begin editing
until you have read the arrival-gate ordering in species-abilities.md and
can say back why "the path is spent whether or not anybody may pull".

What moves into d12ball/flow/ as sync functions returning StepResult, with
`interaction` leaving each of them:

- the front half of a turn: `auto_resolve_challenger`,
  `announce_uncontested_maneuver`, `begin_maneuver_action_selection`,
  `resolve_maneuver` (cogs/d12ball/core.py). Nothing in Phases 1-3 touched
  these; both a human's pick and play_ai_turn's pass through them.
- the three arrival points: `finish_maneuver_resolution` (periods.py),
  `begin_loose_ball` and `offer_scoring_attempt_choice` (effects.py), and
  the two gates each opens with, `check_for_mind_pull` and
  `check_for_loose_ball`. These move together or not at all: the gates and
  the loose-ball check are ordered against each other on purpose and moving
  half the ordering is worse than moving none.
- `begin_loose_ball`'s contest and `begin_loose_ball_skill_test`.
- `begin_run_back` / `continue_run_back` / `finish_run_back` (turnovers.py).
  The loop moves; the batching of its cascade into one message and one
  board refresh stays in the cog (principle 8). And -- named exception to
  principle 9, keep it and keep its comment -- the loop's per-pass persist
  stays: when `next_run_back_step` comes back with a question the loop
  returns from inside itself, so that pass's placements must already be on
  disk before the prompt goes out. In the lifted shape that means the loop
  yields a StepResult per pass and the cog persists after each, or the
  driver-to-be does; either way, collapsing it to one save after the loop
  loses placements on every cascade that stops to ask. The
  MAX_RUN_BACK_PASSES give-up branch is not that path (it breaks, and
  finish_run_back saves) -- the worksheet explains, and the PR should
  restate it so a reviewer does not "fix" the wrong one.
- `begin_injury_tests` / `continue_injury_tests` (core.py),
  `run_own_goal_roll` (effects.py), `begin_ball_recovery` (turnovers.py).

`FollowOn` shrinks as each spine step moves; whatever the cog still
dispatches at the end of this phase is the list Phase 5/6 inherits -- write
that list in the PR.

Golden coverage is the risk here. The tutorial golden covers one basic solo
game on board 7 -- no advanced maneuver, no species ability, no Mind Pull,
no injury test, no own goal, no stacked run back. The worksheet says this
phase adds a golden for what it moves. Add at least one: a seeded, scripted
advanced game (both modules on, a board with stacks, a species that can
Mind Pull) driven through the real cog by the same harness
tests/test_golden_transcript.py uses, recorded on the old code before the
move so the move is what it is compared against. Say in the PR which
branches it reaches and which it still does not.

Tests otherwise: every moved step has a model-side test with no discord;
nothing moved saves; the cog wrapper (or per-pass loop) saves where the
transition rule says; pending_prompt agrees before and after a save/load
round trip in every state this phase can leave a match in;
EveryMatchupResolvesTests and TutorialPlaythroughTests green (they drive the
real cog and are where a flow change is tested); both goldens
byte-identical; test_model_purity green.

Docs: docs/design/possession-and-turnovers.md, loose-balls.md,
species-abilities.md (arrival gate), sending-a-player.md, maneuvers.md each
get their paths corrected and, where the reasoning now lives in a flow
function's docstring, a pointer to it. CLAUDE.md's map row for
d12ball/flow/ grows; the cog-structure.md description of what the six
mixins hold is corrected. The worksheet's Phase 4 section is cut down.

Bot stop for the author (in the PR): a full game, two humans, advanced mode
with both modules on, on board 6 and again on board 9; a solo game against
Dinky; the tutorial end to end (it asserts possession changes hands the
three scripted times). A restart inside a run back that stopped to ask, and
inside a Mind Pull offer.
```

---

## Phase 5 -- periods and windows

```
[PREAMBLE]

This is Phase 5 of docs/model-discord-split.md, "periods and windows".
Phase 4 has landed; confirm on origin/main and read the FollowOn list its
PR left behind. Read docs/design/coaching-choice.md, docs/design/shootout.md,
docs/design/time-out.md, docs/design/clock-and-records.md, and the "The
model and the Discord layer" section of CLAUDE.md.

What moves, as sync flow functions returning StepResult:

- the Coaching Choice and its five occasions (`CoachingOccasion`, the
  substitution budgets, what survives on the match) -- one flow, one
  message, per coaching-choice.md; the *message* part stays the cog's.
- halftime, full time and the shootout: the stage machines
  (`SETUP_STAGES`, `HALFTIME_STAGES`, `FULL_TIME_STAGES`,
  `advance_shootout`) are already most of the way there. `advance_shootout`
  is the one reading of the shootout's state (shootout.md) and stays that.
- the time out (`may_call_time_out`, `pending_time_out`, `finish_time_out`)
  -- charged, not asked; the free pickup.
- the clock and `end_period`. The clock never stops; `record_goal` and
  `record_event` remain the only writers of their logs and nothing reads
  the event log to decide a rule.

What stays: the two ephemeral shootout menus (the secret orders). They are
Discord-specific. The flow exposes what they need to submit and what to
show; the menus themselves, and `restore_shootout_menus`, stay in the cog.

Golden: the tutorial golden reaches none of this (no halftime, no shootout,
no time out). Add a seeded, scripted golden that runs a game through
halftime with substitutions on both sides, a time out in each half, a level
score at full time and a shootout into sudden death, recorded on the old
code before the move. If the harness cannot drive one of those (the
worksheet notes the tutorial is the only multi-turn game the suite can
drive today), extending the harness is in scope for this PR and the
extension is described in docs/design/model-discord-split.md; say which
window remains unpinned if any does.

Tests otherwise as in Phase 4: model-side tests with no discord for each
moved step; nothing moved saves; the wrapper saves where the transition rule
says; pending_prompt agrees before and after a save/load round trip in every
window state, including each shootout sub-state (recovery.md: these are
handed back to the routine that drives them -- check that still holds);
MatchStateSerializationTests green with no new saved field; goldens
byte-identical; test_model_purity green.

Docs: coaching-choice.md, shootout.md, time-out.md, clock-and-records.md
paths corrected; recovery.md's account of what a restart strands and how
the shootout menus are re-armed re-checked against the code. The
worksheet's Phase 5 section is cut down.

Bot stop for the author (in the PR): a game taken to a level score at full
time and through a shootout to sudden death; a halftime with substitutions
on both sides; a time out in each half; a restart inside each window and
inside each shootout sub-state.
```

---

## Phase 6 -- the driver

```
[PREAMBLE]

This is Phase 6 of docs/model-discord-split.md, "the driver" -- the last
phase, after which the cog is a frontend. Phases 1-5 have landed; confirm
on origin/main and read Phase 5's PR for whatever FollowOn keys the cog
still dispatches. Read docs/design/cog-structure.md, docs/design/recovery.md,
docs/design/rate-limits.md and docs/design/permissions.md, and the "The
model and the Discord layer" section of CLAUDE.md.

What this phase builds:

- `d12ball/flow/driver.py`: receive an action, validate it against
  `pending_prompt` (an action that does not answer the current prompt is
  refused with a reason -- that is the model's, since it is a rule about
  whose turn it is), apply the step, run any follow-ons, and return
  `(narration, board_changed, PendingPrompt)`. `FollowOn` dies here: the
  driver runs follow-ons itself, so the cog dispatches nothing. Authorization
  (`may_act_for`, `may_act_in_game`, the helper exception) is NOT the
  driver's; it is a fact about a Discord user and stays in `SafeView`. The
  driver takes an already-authorized action naming a side.
- `play_ai_turn` moves in, so a web app gets Dinky. Dinky's choices are
  already `d12ball/ai.py`'s; what moves is the sequencing. Nothing rolls
  dice on its own -- the AI's rolls still wait behind a button either coach
  may press, so the AI turn ends where a human's would, on a PendingPrompt.
- `persist` collapses to one call in the driver's caller (principle 9). Be
  exact about what that means: every `self.persist(game, match)` in cogs/
  that follows a step the driver now runs goes; the run-back per-pass
  persist is either the driver's, one save per yielded pass, or is
  documented as the one exception with its reason. The `save_games` calls
  that save the game record alone (a message id, a status, a tutorial
  flag) are not touched -- count them before and after and put both
  numbers in the PR.
- The cog becomes: click -> authorize -> `driver.apply(...)` -> persist ->
  render (`view_for_prompt`, one message for the narration, one board
  refresh through BoardRefresher if board_changed). BoardRefresher and its
  timing are not touched. Rate-limit rule: no click may make more Discord
  requests than it did before this phase; say how you checked.

Tests:

- Driver tests with no discord: for each PromptKind, an action that answers
  it and one that does not; the returned PendingPrompt matches
  pending_prompt on the resulting match; a full scripted game plays to a
  result through the driver alone, with no cog imported -- this is the test
  the web app inherits.
- A stray-save guard on the driver (it saves nothing); an ordering test on
  the cog that persist happens after driver.apply and before any send.
- All goldens byte-identical, EveryMatchupResolvesTests,
  TutorialPlaythroughTests, MatchStateSerializationTests, StraySaveGuardTests,
  test_model_purity green.
- Report the two figures the worksheet says the split is measured by: the
  count of async cog methods taking `interaction` (from the AST, by the
  worksheet's counting rule) and `grep -c interaction cogs/d12ball/*.py`,
  before and after; and how many of the test files still need discord.py
  installed to import.

Docs: CLAUDE.md's cog-structure.md ("Why the cog is mixins") is rewritten to
say what the cog is now rather than what it used to defend -- the reasoning
"these methods co-operate through the cog's own state and call each other
by the hundred" stops being true and the section must not keep saying it.
recovery.md is re-read against the code end to end. The worksheet
docs/model-discord-split.md is deleted, and docs/model-discord-split-prompts.md
with it, and the CLAUDE.md map rows for both go; docs/design/model-discord-split.md (the safety net) stays and its
first paragraph stops pointing at a worksheet that no longer exists.

Bot stop for the author (in the PR, and this is the one the worksheet says
earns a week of play before it lands): a full game each way (two humans,
solo), the tutorial, a restart in ten distinct states, an old pre-split save
resumed and played to a result, on both machines. Open the PR as a draft
and say so.
```

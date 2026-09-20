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

Phase 0 has landed (PR #201) and so has Phase 1, in the two halves the
worksheet's own "lands first, on its own" asked for (1a in PR #223, 1b in
PR #225), so there are no prompts for either. Phase 3 is one template run
six times.

---

## [PREAMBLE] -- paste at the top of every prompt

```
You are working in the fool-bot repository, on the model/Discord split. Read
CLAUDE.md first, then docs/model-discord-split.md whole -- it is the
worksheet this work is being done from -- then
docs/design/model-discord-split.md (the safety net, and the two things
about running the suite that cost time to rediscover: the Python 3.13 pin
and the five tests that fail only as root), and then only the other
docs/design/ files this phase's section names. Everything below assumes
you have.

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
- Line numbers quoted in the worksheet are stale (they were measured when
  it was written). Find every function by symbol name (grep or an Explore
  agent), never by line, and re-measure any count you quote in a commit or
  PR from the tree.
- Each prompt opens with a probe -- a shell check that the phase it
  depends on has landed on origin/main. Run it against a fresh
  `git fetch`; if it fails, stop and say so rather than working on top of
  a branch that has not merged.
- Whenever a phase records something on the old code first (a View class
  per fixture, a narration line per branch), the recording is the branch's
  first commit and the move comes after it, so the PR's own history shows
  the recording predates the code it is compared against.
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
  is still open (or deleted if nothing is), and the phase table's Status
  column marks it done with the PR number. The design doc for each area
  the move touched is corrected in the same PR, with the reasoning, not
  only the new path. Your own prompt in docs/model-discord-split-prompts.md
  is deleted in the same PR. CLAUDE.md's map table changes only for a new
  module or a moved responsibility.
- Prompt errata: every later prompt in docs/model-discord-split-prompts.md
  was written from the same worksheet you just found stale in places. In
  the same PR, correct the next phase's prompt for anything this run
  learned that it gets wrong -- a symbol name, a location, a count, a
  branch it did not know about -- and say in the PR description what you
  changed there. Do not rewrite its intent; fix its facts.
- PR description in the house shape: what this changes, why it is built
  this way, what was settled so nobody reopens it in review, testing (what
  ran, what did not and why), the bot-stop checklist, and the PR template's
  checkboxes (suite passes / rules change? / architecture change? / board
  image change? / new persisted field? / more Discord requests per click? /
  no data/ or one-off scripts in the diff).
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
`d12ball.render.render_match_image(match, catalog, ...)` -- NOT the cog's
`render_match_png`, which is async, Discord-shaped and builds a caption out
of fetched emoji. Its `title` is optional and it captions itself from the
team names and period; put the PBD number and coaches on the page around
the image instead. The catalog is `load_player_catalog()` from
d12ball/components.py.

Two more arguments matter, and the cog passes both: `species_icons`, which
it takes from `engine.species_abilities_apply(game)`, and `cyborg_ids`,
which it takes from `D12Ball.cyborg_condition_ids(game, match)` in
cogs/d12ball/presentation.py. The first the page can ask the engine for.
The second is a cog method that reads only the match and
`engine.has_species_ability`, so the page cannot call it without importing
a cog -- which is exactly the kind of gap this milestone exists to find.
Either report it as the first item on the list below and render advanced
games knowingly without their Cyborg markers, or, better, move
`cyborg_condition_ids` onto `RulesEngine` first as its own small PR (the
shape `team_emojis` took in Phase 1a: the cog keeps a forwarding method,
no call site moves) and have the page call the engine's.

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
pending_turn_view is a mapping table).

Probe:
`grep -q "class PromptKind" d12ball/prompts.py && grep -q "def pending_prompt" d12ball/prompts.py`

Read
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
   transitional in its docstring. Because it is a closed set, the enum
   itself is the record of what the cog still dispatches: Phases 3-5 add
   and remove members, and Phase 6 reads the enum rather than a PR
   description to learn what is left.
2. A `PendingPrompt` in `next` is rendered by the same
   `view_for_prompt` the restore path uses. From this phase on, the live
   flow and the restart flow build the prompt through one table, which is
   the drift principle 3 exists to prevent. Its signature is
   `view_for_prompt(game_id, match, prompt)` -- the match is there for the
   one kind whose view is built from a candidate list rather than from the
   prompt alone -- and `pending_prompt(engine, game, match)` takes the game
   record, not a game id.

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
  first, on the same fixtures, commit the recording as the branch's first
  commit, then move -- Phase 1b did exactly this, and
  tests/prompt_fixtures.py plus tests/test_d12ball_prompt_mapping.py are
  the worked example: a discord-free fixture table two test modules read,
  one through the model and one through the cog), board_changed true/false
  where
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
listed before this one in the worksheet's Phase 3 table.

Probe: d12ball/flow/effects.py exists, and for each card of every rank
listed before this one the worksheet's Status column names its PR and
`grep -c "def .*<card key>" d12ball/flow/effects.py` is not 0. If either
fails, stop.

Read docs/design/maneuvers.md and the "The
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
model-side tests for the new step, committed before the move as the
branch's first commit. A rank whose lifted narration differs by
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
six Phase 3 ranks have landed.

Probe: the worksheet's Status column names a PR for every rank 3a-3f, and
`grep -c "self.persist" cogs/d12ball/effects.py` has fallen to the
wrappers alone -- say what the number is.

Read
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
  `D12Ball.begin_loose_ball` and `offer_scoring_attempt_choice`
  (effects.py), and the two gates each opens with, `check_for_mind_pull`
  and `check_for_loose_ball`. Two things are called `begin_loose_ball`:
  the cog's, which is what moves, and `MatchState.begin_loose_ball` in
  d12ball/components.py, which is already the model's and is what the
  cog's calls into. Keep the names apart in the PR and in the flow
  function's docstring. These move together or not at all: the gates and
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
dispatches at the end of this phase is the list Phase 5/6 inherits. The
enum is that list -- prune it to exactly what is still dispatched, and
repeat the members in the PR description.

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
Phase 4 has landed.

Probe: `grep -q "def finish_maneuver_resolution" d12ball/flow/*.py`, and
`FollowOn` in d12ball/flow/result.py has only the members Phase 4 left
(read the enum; it is the list).

Read docs/design/coaching-choice.md, docs/design/shootout.md,
docs/design/time-out.md, docs/design/clock-and-records.md, and the "The
model and the Discord layer" section of CLAUDE.md.

What moves, as sync flow functions returning StepResult. Much of the
vocabulary here is already the model's -- `CoachingOccasion`,
`may_call_time_out` and `pending_time_out` live on `MatchState` in
d12ball/components.py, and the stage lists live in d12ball/engine.py --
so what crosses the seam is the cog's driving of them, not those names:

- the Coaching Choice and its five occasions -- the cog flow that walks a
  window (the substitution budgets, what survives on the match), one flow,
  one message, per coaching-choice.md; the *message* part stays the cog's.
- halftime, full time and the shootout: the cog methods that step the
  stage machines (`SETUP_STAGES`, `HALFTIME_STAGES`, `FULL_TIME_STAGES`)
  and `advance_shootout` (periods.py), which is the one reading of the
  shootout's state (shootout.md) and stays that.
- the time out: `finish_time_out` (turnovers.py) and whatever charges it --
  charged, not asked; the free pickup. `may_call_time_out` is already the
  model's answer; the flow asks it.
- the clock and `end_period` (periods.py). The clock never stops;
  `record_goal` and `record_event` remain the only writers of their logs
  and nothing reads the event log to decide a rule.

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
phase, after which the cog is a frontend. Phases 1-5 have landed.

Probe: the worksheet's Status column names a PR for Phases 0-5, and the
`FollowOn` enum in d12ball/flow/result.py is what the cog still dispatches
(read the enum; it is the list, and it dies in this phase).

Read docs/design/cog-structure.md, docs/design/recovery.md,
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
  worksheet's counting rule under "Where the line already is") and
  `grep -c interaction cogs/d12ball/*.py`, before and after; and how many
  of the test files still need discord.py installed to import. "Before" is
  measured on this branch's base, not taken from the worksheet, whose
  figures date from before Phase 1. This PR deletes the worksheet, so
  first move the counting rule and the final figures into
  docs/design/model-discord-split.md under a heading of their own; the
  rule outlives the plan because it is how a regression would be noticed.

Docs: docs/design/cog-structure.md ("Why the cog is mixins") is rewritten to
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

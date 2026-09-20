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

Phase 0 has landed (PR #201), and so has Phase 1, in the two halves the
worksheet's own "lands first, on its own" asked for (1a in PR #223, 1b in
PR #225), and so has Phase 2 (PR #227), and so has the whole of Phase 3 --
one template run six times, **3a to 3f (PR #229, PR #232, PR #233,
PR #235, PR #236, PR #241)** -- and so has Phase 4 (PR #249), and so has
Phase 5. So there are no prompts for any of them, and what is left here is
Phase 6, the last one.

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

- **Claim the phase before you do anything else, and stop if you cannot.**
  Branch off a fresh `origin/main`, then push the branch empty, before the
  first edit:

      git fetch origin main
      git checkout -B split-phase-<phase> origin/main
      git push origin split-phase-<phase>:refs/heads/split-phase-<phase> \
          --force-with-lease=refs/heads/split-phase-<phase>:

  The empty value after the colon means **"only if this ref does not
  exist"**, and it is the git server that decides, atomically. If the push
  is rejected, another run is already on this phase: **stop, and say so.**
  Do not pick a different branch name and carry on -- that is the failure
  this exists to prevent.

  Why this and not the obvious check: on 2026-09-20 four runs of the
  scheduled routine built Phase 4 at once. Every one of them looked for a
  competing branch or pull request and correctly found none, because none
  of the others had pushed yet -- the gate samples shared state once and
  then works for an hour before publishing anything. Three complete
  implementations of the largest phase in the plan were thrown away. A
  check that reads cannot fix that; only a write that exactly one racer
  can win. Verified against git rather than assumed: with the ref already
  present, this push is rejected even when it would be a fast-forward,
  which a plain push accepts.

  **Ask only about your own phase's branch, never `split-phase-*`.** Every
  branch survives its pull request being merged or closed, so a pattern
  match over all of them reports a phase that finished weeks ago and stops
  every future run forever.

  A dead run leaves its claim behind, and that is deliberate -- an
  abandoned branch with no pull request is visible, and taking it over
  automatically is how two runs end up on one phase again. Delete the
  branch by hand to release it.

  **This is not the force-push CLAUDE.md forbids**, and the difference is
  worth being exact about because the flag's name says otherwise. That
  rule protects a branch somebody may have checked out, by refusing to
  rewrite history under them. This invocation cannot rewrite anything: the
  lease it takes is "the ref is absent", so the push either creates a
  branch that did not exist or fails. Used once, before the first edit,
  with `<phase>` in the ref name. Everything after it is an ordinary
  push.
- Never work on main; never force-push. One phase is one pull request,
  landed on main by PR, and the bot must be fully working at the end of
  it.
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
- The safety net is tests/test_model_purity.py and the three goldens --
  tests/test_golden_transcript.py (the tutorial),
  tests/test_golden_advanced.py (a free advanced game) and
  tests/test_golden_windows.py (a whole game to full time and through a
  shootout). Run the full suite
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
  gambit-matrix.md is: the phase's section is cut down to what
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
anything, as a list. Phase 2 has landed since this was written, so that
list is a finding to take to the author rather than the input to a phase
still being planned.
```

---

## Phase 6 -- the driver

```
[PREAMBLE]

This is Phase 6 of docs/model-discord-split.md, "the driver" -- the last
phase, after which the cog is a frontend. Phases 1-5 have landed.

Probe: the worksheet's Status column names a PR for Phases 0-5, and the
`FollowOn` enum in d12ball/flow/result.py is what the cog still dispatches
(read the enum; it is the list, and it dies in this phase). It has **29**
members: Phase 5 removed `DISPATCH_INJURY_RESUME` and added
`FINISH_SETUP_COACHING`, `FINISH_HALFTIME` and `ANNOUNCE_GAME_OVER`.
`END_PERIOD` and `BEGIN_SUBSTITUTION_WINDOW` are still there despite Phase
5 being expected to take them; each says on its own entry why.

Read docs/design/cog-structure.md, docs/design/recovery.md,
docs/design/rate-limits.md and docs/design/permissions.md, and the "The
model and the Discord layer" section of CLAUDE.md.

What this phase builds:

- `d12ball/flow/driver.py`: receive an action, validate it against
  `pending_prompt` (an action that does not answer the current prompt is
  refused with a reason -- that is the model's, since it is a rule about
  whose turn it is), apply the step, run any follow-ons, and return
  `(narration, board_changed, PendingPrompt)`. `FollowOn` dies here: the
  driver runs follow-ons itself, so the cog dispatches nothing -- note that
  Phase 5 left **29** members, not a handful, and that most of them name a
  cog *wrapper* whose model half has already moved, so collapsing one is
  usually deleting three lines rather than lifting a step. The handful that
  are genuinely still the cog's are pictures, pins and gates: the coaching
  window's half-field image, the three board postings, the tutorial's
  Continue gates, the run-back field strip, the maneuver hand. Authorization
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
  numbers in the PR. **Measure both counts from this branch's base rather
  than quoting CLAUDE.md**, which deliberately stopped naming a number for
  the second one: `dispatch_step_result` absorbed a batch of "remember this
  prompt's message id" saves in Phases 4 and 5, so the figure has moved
  twice since it was written.
- The cog becomes: click -> authorize -> `driver.apply(...)` -> persist ->
  render (`view_for_prompt`, one message for the narration, one board
  refresh through BoardRefresher if board_changed). **The driver needs all
  three of the existing dispatchers**, under whatever names: some steps'
  lines are carried into the next step as its lead-in
  (`dispatch_step_result`), some are one message of their own
  (`post_then_dispatch`), and a period transition's are **a message per
  block** (`post_blocks_then_dispatch`, Phase 5's). Which of the three a
  step gets is the frontend's decision, so the distinction has to survive
  the driver rather than be collapsed into it. BoardRefresher and its
  timing are not touched. Rate-limit rule: no click may make more Discord
  requests than it did before this phase; say how you checked.

Tests:

- Driver tests with no discord: for each PromptKind, an action that answers
  it and one that does not (`tests/prompt_fixtures.py` already stands a
  match in every one of them); the returned PendingPrompt matches
  pending_prompt on the resulting match; a full scripted game plays to a
  result through the driver alone, with no cog imported -- this is the test
  the web app inherits.
- A stray-save guard on the driver (it saves nothing); an ordering test on
  the cog that persist happens after driver.apply and before any send.
- All **three** goldens byte-identical (tutorial, advanced, and Phase 5's
  windows game, which plays a whole game to full time and through a
  shootout), EveryMatchupResolvesTests, TutorialPlaythroughTests,
  MatchStateSerializationTests, StraySaveGuardTests, test_model_purity
  green.
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

# Separating the model from the Discord layer

**This is a worksheet, not a specification.** It is the plan the split is
being built from, and like `advanced-maneuver-matrix.md` the answered parts
should be deleted as they land rather than kept in parallel with the code.
The principles it was written around now have their one permanent home:
"The model and the Discord layer" in CLAUDE.md, moved there when Phase 1
landed. When the last phase is done this file goes.

**Line numbers quoted below are stale.** They were measured when the
worksheet was written and the files have moved under them since. Find a
function by its symbol name, never by the line quoted here, and re-measure
any count before quoting it in a commit or a PR.

The goal is a web app and the Discord bot playing the same game off the same
model, so that a rules change is made once and governs both.

## The seven phases

**Phase 0 is the safety net and Phases 1 to 6 are the work**, so there are
seven of them. Each leaves the bot fully working and lands on `main` on its
own -- that is the constraint the ordering was chosen under, not a property
it happened to have.

| Phase | What it does | Moves rules code? | Status |
| --- | --- | --- | --- |
| **0** | The safety net: the purity guard and the golden transcript | No | Done (PR #201) |
| **1** | `PendingPrompt` -- "what is this match waiting on", into the model | No (a pure read) | Done (PR #223, PR #225) |
| **2** | `StepResult`, proved on Low Pass alone | One maneuver | Done (PR #227) |
| **3** | The twelve effects, a rank per pull request (3a-3f) | Six ranks | 3a-3c done (PR #229, PR #232, PR #233); 3d-3f open |
| **4** | The spine: resolution, arrivals, run back, injuries, own goal | Yes | Open |
| **5** | Periods and windows: coaching, halftime, full time, shootout, time out | Yes | Open |
| **6** | The driver, and the cog becomes a frontend | The last of it | Open |

The Status column is the record of what has landed; a phase's PR updates
its row (and, for Phase 3, names the ranks done) in the same commit that
cuts the section down.

A **read-only web app is possible after Phase 1** and a **playable one after
Phase 6**; everything between the two is how much of a turn the web app can
drive rather than watch.

---

## Where the line already is

*Re-measured 2026-09-19 against current `main`: the render-group split and the
reply-strip sweep landed since this was last counted, and moved a few of the
figures below by a percent or two. Re-run the counts again before trusting
them past another batch of unrelated pull requests -- that is the nature of a
number taken from the tree rather than asserted. The four figures about
`cogs/d12ball/` below now carry their counting rule with them, which is what
makes them re-measurable rather than re-guessable -- the `interaction` count
had been quoted under two different rules at once.*

`d12ball/` is 22,142 lines and does not import `discord` anywhere. Neither
does `gamesaves/`. That is not luck -- it is a rule the author has been
holding, and it is most of the work already done.

What is **already portable, unchanged**:

| Module | Lines | What it is |
| --- | --- | --- |
| `d12ball/components.py` | 5,362 | `MatchState` (127 methods), `BoardState`, the catalogs |
| `d12ball/engine.py` | 2,837 | `RulesEngine`, 101 methods, **stateless** -- built from four catalogs, takes the match per call |
| `d12ball/render.py` + `cards.py` + `boards.py` + `player_cards.py` + `species_cards.py` | 10,487 | Pillow. Serves a web app as a PNG endpoint on day one |
| `d12ball/ai.py`, `stats.py`, `tutorial.py`, `formatting.py`, `game.py`, `rules_doc.py` | 3,456 | All pure |
| `gamesaves/d12ball/storage.py` | 415 | Persistence. `MatchState.to_dict` is **already a wire format** |

What is **not portable**, and is the whole of this plan:

`cogs/d12ball/` is 12,537 lines and holds the **turn flow**: 188 async
methods, of which **157 take an `interaction`** (4 more sync ones do, so 161
in all), **139 read or write `match.`**, and **61 assign to a `match`
attribute directly from the cog** -- nearly all of them `pending_*` flags.

*Each of those four is a rule, not a grep, and the rule is written down so
the next re-measure is mechanical rather than a fresh judgement call:* a
method is counted **async** by its `def`; it **takes an `interaction`** when
that name is in its parameter list; it **touches the match** when its body
holds an attribute access on a name `match`; and a **direct write** is an
assignment (including `+=`) whose target is `match.<attr>`. All four are
read off the AST, so a mention in a comment or a string counts for nothing.

So `MatchState` holds the data and `RulesEngine` answers questions, but the
*sequencing* -- what happens next, and what the match is waiting on -- is
Discord's. A web app built on `d12ball/` alone would have to reimplement the
spine of a turn, which is exactly where the two would drift apart.

**The author has already started this.** Of the 63 functions in
`effects.py`, 13 are already sync, with no `await` and no `interaction` in
them -- so they are already on the model's side of the line in everything
but their address:

- **They change the match**: `send_low_pass`, `throw_high_pass`,
  `knock_ball_back`, `take_ball_by_steal`, `shove_pressured_handler`,
  `apply_pressure_turnover`.
- **They word what happened**: `low_pass_movement_note`,
  `deflection_numbers`.
- **They do both**, which is the shape a flow step has:
  `pay_double_team_cost`, `pay_clear_cost`, `steal_result_text`,
  `pressure_result_text`, `apply_own_goal_outcome`.

That third group is the useful one, because mutate-and-say-what-happened is
exactly `StepResult`. The `async apply_*` wrappers around all thirteen are
already *mutate -> word it -> refresh the image -> dispatch the next step*,
and only the last two of those four are Discord's. This plan finishes a
split the code has already begun rather than starting a new one.

**Five of the thirteen saved themselves, and that is the one thing a step
may not do** (principle 9). `send_low_pass`, `throw_high_pass`,
`knock_ball_back`, `take_ball_by_steal` and `apply_own_goal_outcome` each
called `self.persist(game, match)` in their own body. So they are on the
model's side in everything but their address *and* their save, and lifting
one means stripping the persist out of it first. **Three are left**: Phase 2
took `send_low_pass` and rank D2 took `take_ball_by_steal`.

**That is not a free deletion, because the wrapper was not saving either.**
`apply_low_pass` never persisted: it relied on `send_low_pass` having done
so before `finish_maneuver_resolution` or `offer_scoring_attempt_choice`
ran. Strip the step's save and add none to the wrapper, and the match
reaches the spine unsaved -- and a spine step that ends in a prompt hands
the turn to a click that reloads the match out of the save file. That is
the beat-1 event-log bug CLAUDE.md already records, reintroduced by the
refactor meant to fix it. So the persist moves rather than being removed,
and the wrapper it moved into is `D12Ball.apply_low_pass` -- the shape the
other four follow. See "The model and the Discord layer" in CLAUDE.md, and
`d12ball/flow/` in [design/model-discord-split.md](design/model-discord-split.md).

A fourteenth sync function in that file, `build_loose_ball_view`, is **not**
one of them: it constructs a `discord.ui.View` and stays where it is. It is
named here because it looks like the others in a listing and is not, and
because Phase 1 is what turns it into a prompt kind.

---

## Phase 0 -- the safety net

Nothing moves. This phase exists because the phases after it are large
mechanical moves, and a mechanical move needs something that fails loudly
when it stops being mechanical.

**Done.** What follows is what it turned out to be, rather than what it
was planned as -- the two guards are `tests/test_model_purity.py` and
`tests/test_golden_transcript.py`.

1. **Baseline the suite.** `python3 -m unittest discover -s tests`, on the
   branch's real base rather than on local `main`, which can be far behind
   it. **1,573 tests, 5 failures, all environmental.**
   - **`requirements.txt` will not install below Python 3.13**, because it
     pins `audioop-lts` -- a backport that exists only because `audioop`
     left the standard library in 3.13, and that has no distribution for
     earlier versions. On 3.11 `audioop` is stdlib and the pin is both
     unsatisfiable and unnecessary: `pip install discord.py Pillow
     python-dotenv` is enough to run the suite. CI pins 3.13 and is
     unaffected.
   - **The five failures are all the same cause, and it is running as
     root.** `test_an_unwritable_folder_reads_as_no_record` and the four
     `GameStorageTests` about unreachable folders all simulate a directory
     that cannot be written to, and **uid 0 bypasses permission bits** --
     a write into a `chmod 000` directory succeeds, verified directly.
     They pass in CI, which runs as an ordinary user. Nobody should read
     them as a regression, and the way to be sure is to re-run the same
     commit on the base.

2. **The purity guard**, `tests/test_model_purity.py`. Three assertions,
   and each was checked by injecting the violation it exists to catch:
   - every module under `d12ball/` imports **in a fresh subprocess** with
     `discord` refused by a `meta_path` finder. The subprocess is
     load-bearing: `unittest discover` imports every test module before
     running anything, so by the time an in-process version ran, half of
     `d12ball/` would already be in `sys.modules` and `import_module`
     would return it without re-executing. Injecting `import discord`
     into `formatting.py` fails it naming both that module **and**
     `engine`, which imports it -- the transitive half is the part worth
     reporting.
   - no `async def` anywhere in `d12ball/`, over the AST rather than by
     grep, so a definition nested in a class or a function reads the way
     the interpreter reads it.
   - `d12ball/` imports nothing from `cogs/`. A cog import fails the
     first assertion too, but naming a module nobody would expect, so
     the direction is asserted on its own and reported as itself.

3. **The golden transcript**, `tests/test_golden_transcript.py`, over
   `tests/golden/`. It plays the tutorial through the real cog and
   compares the narration byte for byte, the sequence of prompts, and the
   final `to_dict()` key for key. `FOOLBOT_UPDATE_GOLDEN=1` rewrites the
   files, so **a changed golden is a diff in a pull request rather than a
   test somebody silences**. On failure it prints a cut-down unified diff
   naming the press and the message, because "Diff is 18081 characters
   long" is the opposite of a review conversation.
   - **The seed is load-bearing and the dice are pinned deliberately.**
     Patching `randint` is not enough -- the flow also reaches
     `random.shuffle` and `random.choice` -- so the module RNG is seeded
     and restored. Two seeds produce two different transcripts, because
     the tutorial's closing shot is deliberately not scripted;
     `GOLDEN_SEED` is one that **scores**, since a seed that missed would
     pin the unusual branch as the reference. A test asserts that, so the
     golden cannot quietly become the missed-shot run.
   - **It is stable**, which is the claim the whole file rests on: two
     runs on one seed agree (asserted), and the transcript is identical
     under `PYTHONHASHSEED` 0, 1 and 42 -- checked, because a set of
     player ids iterated into a message would have made it vary between
     machines rather than on the change that broke it.
   - **It covers one basic-mode solo game on board 7**, which is the only
     multi-turn game the suite can drive today. No advanced maneuver, no
     species ability, no halftime, no shootout, no time out. Proof that
     the gap is real rather than theoretical: rewording *two* of the
     three `Ball speed is now` sites in `effects.py` did not fail it,
     because the tutorial only reaches the third. **Phases 4 and 5 should
     each add a golden for what they move.**

4. **The existing guards**, so nobody weakens them by accident:
   `EveryMatchupResolvesTests` (36 pairings x 3 boards x 2 control paths),
   `TutorialPlaythroughTests`, `MatchStateSerializationTests`,
   `StraySaveGuardTests`.

**Bot stop:** none. Nothing about the running bot changed.

---

## Phase 1 -- `PendingPrompt`, and the keystone

**Done** -- `team_emojis` and `RulesEngine.format_player_label` in PR #223,
the chain itself in PR #225. `pending_prompt(engine, game, match)` lives in
`d12ball/prompts.py` and answers with a `PendingPrompt`; `pending_turn_view`
is the mapping over it and `D12Ball.view_for_prompt` the one place a
`PromptKind` becomes a view. There are **26 kinds**, which is the count this
section estimated, confirmed against the tree. The reasoning is in
["Recovering a stuck game"](design/recovery.md) and the principles are now
CLAUDE.md's.

What is still open is the milestone below, which is a separate piece of work
and not in this repository.

### Milestone: the web app can start here

After this phase a **read-only spectator page** is possible with nothing
further moved: `load_games` for the record, `pending_prompt` for "what is
this game waiting on", and the board as a PNG.

**The board is `render.render_match_image(match, catalog)`, not the cog's
`render_match_png`.** That distinction is the whole reason this milestone
lands here rather than later. `render_match_png` is an async *cog* method
that loads the match, builds a `PBD12 - @coach vs. @coach, First Half`
caption out of the team emoji it fetched at startup, and hands the rest to
`render_match_image` in a worker thread. A web app cannot call it and does
not need to: `render_match_image`'s `title` is optional and it writes its
own caption from the two team names and the period when none is passed, so
the pure entry point needs no glue at all. What the web app gives up by
calling it directly is the PBD number and the coaches' names in the
caption -- which it can put on the page around the image instead.

The page plays nothing, but it proves the seam against a real frontend
rather than against a plan, and it is worth building before Phase 3 for
exactly that reason.

---

## Phase 2 -- `StepResult`, on one vertical slice

**Done** (PR #227). `d12ball/flow/` holds `StepResult`, the transitional
`FollowOn`, and `low_pass_step`; `D12Ball.apply_low_pass` is the wrapper
and `D12Ball.dispatch_step_result` the whole of the Discord side. What it
settled -- the shape of `next`, the narration staying out of the
follow-on's arguments, the persist between the step and the dispatch --
is in CLAUDE.md's "The model and the Discord layer" and in
[design/model-discord-split.md](design/model-discord-split.md). Nothing
about it is still open.

---

## Phase 3 -- the effects, a rank per pull request

Six ranks, six short-lived branches, each landing on `main`. Ordered by how
much other machinery the rank hands off to -- the self-contained ones first,
so the pattern is settled before it meets the hard cases.

| # | Rank | Cards | Why here |
| --- | --- | --- | --- |
| 3a | O2 | Dribble Advance, Dribble Burst | **Done (PR #229).** Moved the handler and ended; the speed choice was the only prompt |
| 3b | O1 | Low Pass, Skilled Pass | **Done (PR #232).** Nothing was left to move -- Phase 2's step already carried both cards -- so the rank is its evidence: ten fixtures and the `key=` round trip |
| 3c | D2 | Steal, Intercept | **Done (PR #233).** One step and a sign for both cards, and the first hand-off into the spine: `BEGIN_RUN_BACK` and `BEGIN_SHOOTER_CHOICE` |
| 3d | D3 | Pressure, Double Team | The own-goal branch, and `pending_double_team` reaching into the next turn |
| 3e | D1 | Deflect, Clear | Calls `begin_loose_ball` directly rather than going through `finish_maneuver_resolution` |
| 3f | O3 | High Pass, Setup Pass | Hardest by a distance: 169 lines, 10 awaits, the overshoot, the contest, the out-of-bounds |

Through this phase the spine (`finish_maneuver_resolution`, `begin_run_back`,
`begin_loose_ball`) is **still async and still in the cog**. Each lifted
effect returns a `StepResult` whose `next` names the spine step, and the cog
dispatches it. That is what keeps every one of these six shippable on its
own.

**What 3a settled, so the ranks after it do not reopen it** (the detail is
in [design/model-discord-split.md](design/model-discord-split.md)):

- **A rank may add a `FollowOnStep` member**, and `OFFER_SPEED_CHOICE` is
  3a's. `offer_speed_choice` is not a `PendingPrompt` the step returns,
  because whether anybody is asked at all is still the cog's decision --
  Dinky answers for itself and a tutorial beat holds the prompt behind a
  note. 3c did **not** inherit it: a steal owes the same choice but
  reaches it through `finish_run_back`, so it named `BEGIN_RUN_BACK`
  and let the flag carry the question.
- **A step takes `game` where it reads the record**, which for anything
  charging exhaustion is always: `RulesEngine.apply_exhaustion` and
  `describe_exhaustion_gain` moved onto the engine with
  `condition_emojis` in 3a, so 3c to 3f charge tokens through the engine
  and neither method has to move again.
- **The persist rule is load-bearing rather than tidy.**
  `apply_dribble_advance` saved and *then* charged a beaten Clear, so
  those two tokens and the Exhausted flag they set were never written
  out. Step-then-save fixed it with nothing decided. Expect one of these
  per rank where a cost is paid after the old save, and say so in the PR
  rather than treating it as noise.

**What 3b found, for the ranks that have not run yet.** The rank
itself was empty -- `low_pass_step(key="skilled_pass")` is the whole of
a Skilled Pass and Phase 2 landed it -- so what it produced is two
corrections to what the later ranks expect:

- **`offer_speed_choice` has one direct caller left in `cogs/` that
  has not moved**: `resolve_setup_pass`, which is rank O3's.
  `finish_run_back` is the other, and it is the spine's. (The rest of
  this bullet was 3c's brief and 3c has run -- see below.)
- **`begin_loose_ball` is not rank D1's alone.** Eight call sites in
  `cogs/d12ball/effects.py` reach it, and one of them is rank O1's own
  -- `resolve_low_pass`'s no-teammate-to-receive branch, which moves
  the ball, words it and persists before handing over. It was left
  where it is: it is in the `resolve_*` half this phase does not
  touch, and lifting it would settle `board_changed` for every loose
  ball rather than for one card. See 3e, which is where that is due.
  A second scheduled run reached that branch before standing down, and
  turned up **two rules questions on it** that have to be answered
  before it moves rather than while it moves: a *failed* free pass
  charges a space minute where a completed one charges none (the
  branch hardcodes `distance_moved=1` and never reads `free`), and it
  leaves its `free_low_pass` continuation standing, which
  `apply_speed_choice` then re-offers. Both are pre-existing on `main`
  and both are written out in PR #232.

**What 3c settled, for 3d to 3f and for Phase 4.** It was the first
rank to hand off to the spine rather than to another effect, so most
of what it produced is about the seam rather than about the cards:

- **A rank may add more than one member, and D2 added two.**
  `BEGIN_RUN_BACK` (with `speed_choice_after` in its kwargs) and
  `BEGIN_SHOOTER_CHOICE`. Phase 4's "three arrival points" list does
  not name `begin_shooter_choice`; it is a dispatched follow-on from
  this rank on, so Phase 4 either moves it or leaves the member in the
  enum knowingly.
- **`dispatch_step_result` passes a follow-on's arguments by
  keyword.** Every spine method a rank hands off to is called
  `method(interaction, game, match, lead_in=..., **kwargs)`, so a
  parameter the cog used to pass positionally arrives named -- and an
  existing test reading `await_args.args[n]` breaks on a move that
  changed nothing. `begin_shooter_choice(…, [challenger], …)` was one.
  The fix is the assertion, not the call; binding a recorded call to
  the real method's `inspect.signature` is how the rank's own fixture
  table answered for both shapes at once.
- **Step-then-save is not always a fix.** Rank O2 found a write that
  was being lost; D2 found two persists that both already carried
  everything -- `take_ball_by_steal`'s own, and a second in the
  Skilled Pass cost branch on top of it. Collapsing them changed the
  number of writes and nothing else. Say which of the two a rank found
  rather than assuming O2's.
- **A defense rank has no unchallenged branch.** A defense card only
  resolves where a defender was sent, so "contested and unchallenged"
  in the bot stop is one half only for D1, D2 and D3 -- and
  `match.challenger_id` can be read without a None check in their
  steps.
- **A paragraph inside a branch's narration stays one block.**
  `dispatch_step_result` joins blocks on a single space, so a second
  block separated by a blank line would carry a stray space in front
  of its newlines. The Intercept overshoot's "no field left ahead of
  them" rides inside the turnover's block, the way a beaten Clear's
  cost rides inside the dribble's.
- **One ordering is open, and the behaviour was left as it was.** An
  Intercept that overshoots returns before the Skilled Pass cost is
  read, so it collects none. Whether that is the rule (nobody goes
  back in position, so the free pass has no moment) or an oversight is
  the author's to say; it is written out in PR #233 under "Questions
  for the author", and deliberately **not** pinned in a fixture, the
  same way 3e's two questions were left unpinned in PR #232.

**Bot stop, per rank:** play both cards of the rank, contested and
unchallenged, on two board sizes, in a basic and an advanced game. Watch the
advanced cost fire. Restart mid-effect once per rank -- the effect-choice
branch of Phase 1 is what catches it.

**CLAUDE.md:** the maneuver's own section gains a line only where the move
changed something worth recording. Most of these should change nothing in
it, and a rank that wants a paragraph is a rank that moved a rule.

---

## Phase 4 -- the spine

The turn's own machinery, and where `interaction` dies from everything
Phases 1-3 didn't already reach:

- **the front half of a turn**: choosing and announcing a challenger
  (`auto_resolve_challenger`, `announce_uncontested_maneuver` -- see
  [sending-a-player.md](design/sending-a-player.md)),
  `begin_maneuver_action_selection` and `resolve_maneuver`. Easy to read as
  already covered by "the spine" below, and it isn't -- nothing in Phases
  1-3 touches it. Both a human's pick and `play_ai_turn`'s pass through it,
  which is also why "`interaction` dies" above is qualified: it doesn't,
  until this moves too.
- the **three arrival points**, which are where a ball that has moved is
  settled: `finish_maneuver_resolution` (the tail of every ordinary path),
  `begin_loose_ball` (a Deflect, and the High Pass contest behind it) and
  `offer_scoring_attempt_choice` (a set-up). Between them they are every
  one of the four things a Mind Pull pre-empts.
- the **two gates** each of those opens with, `check_for_mind_pull` and
  `check_for_loose_ball` -- which are not the arrival points but the `if
  ...: return` at the top of them
- `begin_loose_ball`'s contest
- `begin_run_back` / `continue_run_back` (the cascade; note principle 8 --
  the batching stays in the cog, the loop moves). **The loop's own
  per-pass `self.persist(game, match)` (`turnovers.py:1622`) stays too**, as
  a named exception to principle 9, and the path that needs it is the
  **coach's-choice `return`** (`:1657`): when `next_run_back_step` comes
  back with a question, the loop posts the prompt and returns from inside
  itself, so nothing after the loop runs. The turn is then waiting on a
  click that reloads the match out of the save file -- which means this
  pass's placements have to already be on disk, and the intra-loop persist
  is what puts them there. Collapse it to one save after the loop and every
  cascade that stops to ask somebody loses the placements it just made.
  - **The give-up-after-`MAX_RUN_BACK_PASSES` branch is not that path**,
    though it reads like it: it `break`s rather than returning, and the two
    statements after the loop are `flush()` and `finish_run_back`, which
    persists at `:1505`. So its log line ("the match is saved as it
    stands") is kept by that save whatever happens to the one in the loop.
    Worth writing down because the branch *looks* like the fragile one and
    is the safe one, and the genuinely fragile path has no log line drawing
    attention to itself.
- `begin_injury_tests` / `continue_injury_tests`
- `run_own_goal_roll`
- `begin_ball_recovery`

This is the biggest single phase and the one to resist splitting badly: the
arrival gates and the loose-ball check are ordered against each other on
purpose ("the path is spent whether or not anybody may pull"), and moving
half of that ordering is worse than moving none of it.

**Bot stop:** a full game, two humans, advanced mode with both modules on,
on board 6 and again on board 9. Then a solo game against Dinky. Then the
tutorial end to end -- it is five real turns through the real flow and it
asserts possession changes hands the three scripted times.

**CLAUDE.md:** "The ball carrier", "Turnovers", "Loose balls and the board"
and "Mind Pull, and the arrival gate" all describe functions that have moved
module. Each gets its path corrected in the same commit.

---

## Phase 5 -- periods and windows

- the Coaching Choice and its five occasions
- halftime, full time, the shootout
- the time out
- the clock and `end_period`

These are more self-contained than the spine and mostly already read as
stage machines (`SETUP_STAGES`, `HALFTIME_STAGES`, `FULL_TIME_STAGES`,
`advance_shootout`). The work is mechanical; the risk is the two ephemeral
shootout menus, which are Discord-specific and stay where they are.

**Bot stop:** a game taken to a level score at full time and through a
shootout to sudden death. A halftime with substitutions on both sides. A
time out in each half. Restart inside each window.

---

## Phase 6 -- the driver

The last piece, and the one that makes the web app a frontend rather than a
port:

- `d12ball/flow/driver.py` -- receive an action, validate it, apply the
  step, return `(narration, board_changed, PendingPrompt)`.
- `play_ai_turn` moves in, so a web app gets Dinky for free.
- `persist` collapses from 95 call sites to one, in the driver
  (principle 9). The 52 bare `save_games` calls that save the *game
  record* alone -- a message id, a status, a tutorial flag -- stay the
  cog's, since they have no match to write.
- The cog becomes: click -> authorize -> `driver.apply(...)` -> render.

**Bot stop:** everything. A full game each way, the tutorial, a restart in
ten states, and an old save. This is the phase that earns a week of the two
of you actually playing on it before it lands.

**CLAUDE.md:** "Why the cog is mixins" is rewritten -- much of its reasoning
("these methods co-operate through the cog's own state and call each other
by the hundred") stops being true once the flow is out, and the section
should say what it is now rather than what it used to defend.

---

## What deliberately does not move

Naming these now so nobody widens the job mid-phase:

- **`BoardRefresher`** and the whole five-in-five gate. It is Discord's
  arithmetic and the one part of the bot with measured timing invariants.
- **Views, channels, the lobby and hub, emoji, `botlog`, archive export.**
- **`render.py` and the card/board modules.** Already shared; the web app
  consumes them as a PNG endpoint.
- **The mixin split itself.** CLAUDE.md warns that turning those calls into
  collaborator objects is "a far larger change and a different one -- don't
  start it by halves". This plan does not start it. The cog stays six
  mixins; it just has less in it.
- **The save format.** Principle 6.

---

## What to resist

- Wording the same position twice, once per frontend (principle 5).
- A new persisted field "while we're in here" (principle 6).
- A `pending_prompt` in the web app because the real one "didn't quite fit"
  (principle 10). Grow the real one.
- Collapsing the mixins.
- Long-lived branches. CLAUDE.md: short-lived, land on `main` via a pull
  request. Every phase above is shippable on its own, and that is not an
  accident of the ordering -- it is the constraint the ordering was chosen
  under.

---

## How it is known to be working

Two readings, both cheap:

- **`interaction` leaves the package.** Two readings, and they are not the
  same number: 157 async methods **take** one as a parameter today, and
  `grep -c interaction cogs/d12ball/*.py` totals **699 matching lines**. The
  first falls as methods cross the seam and the second as the call sites
  inside them go, so the second is the slower and more honest of the two.
  161 was quoted here for the grep and was never a grep count -- it is the
  signature count with the 4 sync methods added in.
- **The test suite's discord dependency falls.** 45 of 55 test files
  currently need `discord.py` installed just to import, because they drive
  the cog. As the flow moves into the model, those become model tests that
  run without it. When most of the suite is discord-free, the split is real
  -- and the web app has a test suite waiting for it.

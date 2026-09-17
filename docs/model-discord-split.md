# Separating the model from the Discord layer

**This is a worksheet, not a specification.** It is the plan the split is
being built from, and like `advanced-maneuver-matrix.md` the answered parts
should be deleted as they land rather than kept in parallel with the code.
The principles in it have one permanent home, and it is CLAUDE.md -- see
Phase 1. When the last phase is done this file goes.

The goal is a web app and the Discord bot playing the same game off the same
model, so that a rules change is made once and governs both.

---

## Where the line already is

`d12ball/` is 21,583 lines and does not import `discord` anywhere. Neither
does `gamesaves/`. That is not luck -- it is a rule the author has been
holding, and it is most of the work already done.

What is **already portable, unchanged**:

| Module | Lines | What it is |
| --- | --- | --- |
| `d12ball/components.py` | 5,362 | `MatchState` (127 methods), `BoardState`, the catalogs |
| `d12ball/engine.py` | 2,826 | `RulesEngine`, 101 methods, **stateless** -- built from four catalogs, takes the match per call |
| `d12ball/render.py` + `cards.py` + `boards.py` + `player_cards.py` + `species_cards.py` | ~9,700 | Pillow. Serves a web app as a PNG endpoint on day one |
| `d12ball/ai.py`, `stats.py`, `tutorial.py`, `formatting.py`, `game.py`, `rules_doc.py` | ~3,100 | All pure |
| `gamesaves/d12ball/storage.py` | 415 | Persistence. `MatchState.to_dict` is **already a wire format** |

What is **not portable**, and is the whole of this plan:

`cogs/d12ball/` is 12,510 lines and holds the **turn flow**. 188 async
methods, 161 taking `interaction`, 125 touching match state, and **76 direct
writes of rules state from the cog** -- nearly all of them `pending_*` flags.

So `MatchState` holds the data and `RulesEngine` answers questions, but the
*sequencing* -- what happens next, and what the match is waiting on -- is
Discord's. A web app built on `d12ball/` alone would have to reimplement the
spine of a turn, which is exactly where the two would drift apart.

**The author has already started this.** In `effects.py`, 14 of 63 functions
are pure sync mutators with no `await` and no `interaction`: `send_low_pass`,
`throw_high_pass`, `knock_ball_back`, `take_ball_by_steal`,
`shove_pressured_handler`, `pay_double_team_cost`, `pay_clear_cost`,
`apply_pressure_turnover`, `apply_own_goal_outcome`. The `async apply_*`
wrappers around them are already *mutate -> word it -> refresh the image ->
dispatch the next step*. This plan finishes that split rather than starting a
new one.

---

## The principles

These are the rules the split is made by. **At the end of Phase 1 they move
into CLAUDE.md as a section of their own** ("The model and the Discord
layer"), and this copy is deleted -- a settled rule has exactly one home.
Until then they live here so the early phases have something to be reviewed
against.

1. **The model may not import `discord`, and may not be `async`.** Both
   halves matter. No-discord is the obvious one; not-async is the one that
   gets given away quietly, because the first `await` in a model function
   is what drags an event loop, an interaction and a rate-limit bucket in
   behind it. A step that wants to be async wants to send something, and
   sending is the frontend's. The line is mechanical, so it is tested
   mechanically -- see Phase 0.

2. **A rule is a question the model answers. The frontend asks it and
   renders the answer.** This is `RulesEngine`'s existing shape, extended
   to the flow: nothing in `cogs/` may decide a rule, and nothing in
   `d12ball/` may decide a presentation.

3. **One reading of "what is this match waiting on", and it is in the
   model.** `pending_turn_view` already claims this and already carries the
   ordering decisions in its comments; what it does not do is answer
   anywhere a web app can hear it. `pending_prompt(engine, game, match)`
   is that same chain returning a `PendingPrompt`, and the cog's mapping
   from kind to `discord.ui.View` is the only thing left in `cogs/`.
   **A second copy of that chain is the failure mode** -- it is how a
   resume comes to offer a different prompt from the one a restart
   restores, and with two frontends it is how the web app and the bot come
   to disagree about whose turn it is.

4. **A flow step returns what happened. It does not send it.** `StepResult`
   carries the narration lines, whether the board moved, and the next
   prompt. The frontend decides what becomes a message, what becomes an
   edit, and what becomes a websocket frame.

5. **Narration text is the model's, because the wording rules are rules.**
   "Say what the position is, never what it is not." "Don't answer a
   question nobody asked." "A move that costs nothing says nothing." Those
   are in CLAUDE.md as rules about *every message the bot posts*, and they
   were settled by the author reading a turn back out of a channel. Two
   frontends wording the same position separately is two voices, and only
   one of them would be held to those rules. `formatting.py` and the
   engine's `build_turn_prompt` / `build_loose_ball_prompt` already word
   things with no discord.py in them -- this extends that, it does not
   invent it.
   - The corollary: **do not replace narration with structured events "so
     the web app can word it itself".** That is the same mistake with an
     architecture diagram in front of it.

6. **The save format is the contract, and this refactor may not change
   it.** Not a key, not a default, not a fallback. Both developers run the
   bot from their own tree against their own saves, and a half-finished
   game outlives the commit -- which is why `MATCH_SAVED_FIELDS` carries
   the fallbacks it does. A phase that wants a new persisted field is a
   phase that has stopped being a refactor. If one is genuinely needed it
   goes in its own commit, with the table entry and the fallback, reviewed
   as a change to the game rather than as plumbing.

7. **`interaction` never crosses the seam** -- not as a parameter, not
   stashed on a match, not smuggled through a callback. It is the single
   clearest test of whether a function has ended up on the right side, and
   it is greppable.

8. **The frontend owns batching, and therefore owns the rate limits.** A
   step returns a list of lines; the cog decides they are one message.
   `continue_run_back` batching a cascade into one message and one board
   refresh is a Discord economy, not a rule -- the web app has no such
   limit and should not inherit the shape. `BoardRefresher` and its
   five-in-five arithmetic stay exactly where they are; what reaches them
   is `StepResult.board_changed`.

9. **The driver persists; steps do not.** Today `self.persist(...)` is called at 95
   sites in `cogs/`, and CLAUDE.md already records the class of bug that
   produces --
   an event recorded without a save is one the next interaction never
   sees. A step mutates and returns; the driver saves once, after. This is
   the one place the refactor makes the bot *better* rather than only
   more portable, and it should be called out as such in review.

10. **The web app may not reach past the flow.** No importing a cog, no
    re-deriving a candidate list "just for the UI", no second
    `pending_prompt`. If the web app needs something the flow does not
    expose, the flow grows a method and the bot gets it too. The moment
    the web app has a rule of its own, this whole exercise has failed.

---

## Phase 0 -- the safety net

Nothing moves. This phase exists because the phases after it are large
mechanical moves, and a mechanical move needs something that fails loudly
when it stops being mechanical.

1. **Baseline the suite.** `python3 -m unittest discover -s tests` on a
   clean tree, recorded in the PR body. (A container without `discord.py`
   and `Pillow` reports ~49 import errors that are not failures -- install
   `requirements.txt` first.)

2. **Add the no-discord guard.** A test that imports every module under
   `d12ball/` with `discord` blocked in `sys.modules`, and fails naming the
   module that reached for it. Principle 1 is worth nothing unenforced, and
   the existing purity is currently held by habit.
   - Same test asserts no `async def` in `d12ball/`, for the second half of
     principle 1.

3. **Add the golden-transcript test.** This is the important one. Replay a
   saved game with the dice pinned and assert, step by step:
   - the narration strings, byte-identical;
   - the sequence of prompts;
   - the final `match.to_dict()`, key for key.

   Every later phase runs it. A refactor that changes a word changes the
   golden file, and changing a golden file is a review conversation rather
   than something that slips through. `TutorialPlaythroughTests` is the
   model for how to drive this -- it already plays five real turns through
   the real cog with Discord mocked.

4. **Note the existing guards** so nobody weakens them by accident:
   `EveryMatchupResolvesTests` (36 pairings x 3 boards x 2 control paths),
   `TutorialPlaythroughTests`, `MatchStateSerializationTests`,
   `StraySaveGuardTests`.

**Bot stop:** none. Nothing changed.

**CLAUDE.md:** the "Where the statistics are tested" section gains the
golden transcript beside the other two, under "The test suite".

---

## Phase 1 -- `PendingPrompt`, and the keystone

**The single highest-leverage change in the project, and the one with no
rules risk**, because nothing mutates: the whole chain is a read.

### What moves

New `d12ball/prompts.py`:

- `PromptKind` -- one value per distinct prompt (~20, matching the branches).
- `PendingPrompt` -- `kind`, `ask` (the line put above it), and the handful
  of parameters the branches actually carry: `player_ids`, `player_id`,
  `side`, `maneuver_key`, `skill_type`, `free`.
- `pending_prompt(engine, game, match) -> PendingPrompt` -- the 280-line
  chain from `core.py:1581`, moved whole.

The chain's dependencies are already almost all model:

```
match.*                                        the bulk
engine.{settled_maneuver_winner,
        next_run_back_step, halftime_stage,
        get_player_definition}                 pure already
player_label                                   Discord-free underneath
self.games[game_id]                            becomes a `game` parameter
build_{run_back,loose_ball,effect_choice}_view the only Discord-shaped bits
```

Those three builders are the interesting part, and they are the same shape:
each is *already* a pure decision over match state that happens to end in a
`View` constructor. They become kind-and-parameters:

- `build_run_back_view` -> `RUN_BACK_SPACE(player_id)` or
  `RUN_BACK_PLAYER(player_ids)`, off `next_run_back_step`.
- `build_loose_ball_view` -> `LOOSE_BALL_PICK(side, skill_type)`, off
  `loose_ball_side_on_the_clock` / `loose_ball_prompt_side`.
- `build_effect_choice_view` -> the effect prompts, off
  `pending_effect_continuation` and `resolving_maneuver`.

Each returns `None` today and falls back to `PlayerActionView`; that becomes
`PromptKind.PLAYER_ACTION`, and the fallback stays exactly as deliberate as
it is now.

### What stays

`pending_turn_view` survives in the cog as a **mapping table** -- kind to
`View`, nothing else. Both its callers (`on_ready`'s restore and
`resume_pending_prompt`) are untouched, which is the point: they are the two
that must not drift.

### Sizing

~400 lines moved, ~150 lines of mapping table left behind.

### Test stop -- and this is a real one

The suite does not exercise restarts, and this chain exists *for* restarts.
So, from a working tree, with the bot running:

- **The restart matrix.** Get a game into each state below, kill the bot,
  restart it, and check the prompt that comes back is the one that was
  there. Then do it again with `/d12ball resume`, which is the other caller.

  | State | How to reach it |
  | --- | --- |
  | setup coaching | create a game, get to the window |
  | halftime | `/debug` the clock to 15, turn over |
  | full time (level score) | level the score, run the clock out |
  | mind pull owed | advanced game, Telekinetic on the ball's path |
  | injury test owed | any skill test that goes badly |
  | own goal owed | Pressure into a defender's own goal |
  | shootout (3 sub-states) | play the full-time window out |
  | time out | call one |
  | run back, one candidate | steal that displaces one |
  | run back, a stack | steal on board 6 under 2-3-1 |
  | ball recovery | out-of-bounds Setup Pass |
  | loose ball pick / skill test | Deflect onto an empty space |
  | score attempt | shoot |
  | maneuver challenge | start a maneuver |
  | maneuver pick | send a challenger |
  | skill test | tie the cards |
  | effect choice | win decisively with a pass |
  | no handler (kickoff) | finish setup |
  | plain turn prompt | anything else |

- **Old saves load.** Point the bot at a save written before this branch and
  resume a game in each of three or four of those states. Nothing in this
  phase touches persistence, so this is confirming principle 6 rather than
  testing it -- which is exactly when it is cheap.

- Both developers, on both machines. The live bot is the Windows `K:\`
  checkout; a fix on the Mac has not reached it until that tree has pulled
  and **the bot has been restarted there**.

### Milestone: the web app can start here

After this phase a **read-only spectator page** is possible with nothing
further moved: `load_games` for the record, `render_match_png` served as a
PNG, and `pending_prompt` for "what is this game waiting on". It plays
nothing, but it proves the seam against a real frontend rather than against
a plan, and it is worth building before Phase 3 for exactly that reason.

### CLAUDE.md

The principles above move in, as a section of their own, and this file's
copy is deleted. The "Recovering a stuck game" section is edited to point at
`pending_prompt` as the one reading, with `pending_turn_view` named as the
Discord mapping over it.

---

## Phase 2 -- `StepResult`, on one vertical slice

Prove the write-side seam on one maneuver before committing to twelve.

- `d12ball/flow/__init__.py`, `d12ball/flow/result.py`:

  ```
  @dataclass
  class StepResult:
      narration: list[str]              # what the cog builds inline today
      board_changed: bool               # what refresh_match_image decided
      next: PendingPrompt | None        # or a follow-on step to run
  ```

- Move **Low Pass** and nothing else: `send_low_pass` (already sync) plus
  the wording, into `d12ball/flow/effects.py` as a sync function returning
  `StepResult`. `apply_low_pass` in the cog becomes: call it, post the
  narration, refresh if `board_changed`, dispatch `next`.

Low Pass is the right slice because it is mid-sized (96 lines, 4 awaits), it
has a role-ability branch (the Winger's set-up) so it is not a toy, and it
has a continuation (Skilled Pass's free pass) so the `pending_effect_continuation`
machinery is exercised.

**Bot stop:** play three or four Low Passes -- one plain, one into a stack
(board 6) so the receiver pick fires, one as a Winger for the set-up, one
free off a beaten Skilled Pass. Golden transcript must be unchanged.

**CLAUDE.md:** `StepResult` and the flow package described, under the new
section.

---

## Phase 3 -- the effects, a rank per pull request

Six ranks, six short-lived branches, each landing on `main`. Ordered by how
much other machinery the rank hands off to -- the self-contained ones first,
so the pattern is settled before it meets the hard cases.

| # | Rank | Cards | Why here |
| --- | --- | --- | --- |
| 3a | O2 | Dribble Advance, Dribble Burst | Moves the handler and ends. Speed choice is the only prompt. |
| 3b | O1 | Low Pass, Skilled Pass | Already done in Phase 2 -- this is Skilled Pass and the shared `apply_low_pass(key=)` |
| 3c | D2 | Steal, Intercept | A turnover, so it meets `begin_run_back` -- the first hand-off |
| 3d | D3 | Pressure, Double Team | The own-goal branch, and `pending_double_team` reaching into the next turn |
| 3e | D1 | Deflect, Clear | Calls `begin_loose_ball` directly rather than going through `finish_maneuver_resolution` |
| 3f | O3 | High Pass, Setup Pass | Hardest by a distance: 169 lines, 10 awaits, the overshoot, the contest, the out-of-bounds |

Through this phase the spine (`finish_maneuver_resolution`, `begin_run_back`,
`begin_loose_ball`) is **still async and still in the cog**. Each lifted
effect returns a `StepResult` whose `next` names the spine step, and the cog
dispatches it. That is what keeps every one of these six shippable on its
own.

**Bot stop, per rank:** play both cards of the rank, contested and
unchallenged, on two board sizes, in a basic and an advanced game. Watch the
advanced cost fire. Restart mid-effect once per rank -- the effect-choice
branch of Phase 1 is what catches it.

**CLAUDE.md:** the maneuver's own section gains a line only where the move
changed something worth recording. Most of these should change nothing in
it, and a rank that wants a paragraph is a rank that moved a rule.

---

## Phase 4 -- the spine

The turn's own machinery, and where `interaction` finally dies from the
effect path:

- `finish_maneuver_resolution` -- the tail of every ordinary path
- the three arrival gates and `check_for_mind_pull` / `check_for_loose_ball`
- `begin_loose_ball` and the contest
- `begin_run_back` / `continue_run_back` (the cascade; note principle 8 --
  the batching stays in the cog, the loop moves)
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
  (principle 9). The ~53 bare `save_games` calls that save the *game
  record* alone -- a message id, a status -- stay the cog's, since they
  have no match to write.
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

- **`grep -c interaction` in `cogs/d12ball/`** falls from 161 toward zero.
- **The test suite's discord dependency falls.** 45 of 55 test files
  currently need `discord.py` installed just to import, because they drive
  the cog. As the flow moves into the model, those become model tests that
  run without it. When most of the suite is discord-free, the split is real
  -- and the web app has a test suite waiting for it.

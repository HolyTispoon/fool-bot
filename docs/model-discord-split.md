# Separating the model from the Discord layer

**This is a worksheet, not a specification.** It is the plan the split is
being built from, and like `advanced-maneuver-matrix.md` the answered parts
should be deleted as they land rather than kept in parallel with the code.
The principles in it have one permanent home, and it is CLAUDE.md -- see
Phase 1. When the last phase is done this file goes.

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
| **1** | `PendingPrompt` -- "what is this match waiting on", into the model | No (a pure read) | 1a done (PR #223); 1b open |
| **2** | `StepResult`, proved on Low Pass alone | One maneuver | Open |
| **3** | The twelve effects, a rank per pull request (3a-3f) | Six ranks | Open |
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

**Five of the thirteen save themselves, and that is the one thing a step may
not do** (principle 9). Every mutator on the list does it -- `send_low_pass`
(`effects.py:196`), `throw_high_pass` (`:928`), `knock_ball_back` (`:2297`),
`take_ball_by_steal` (`:2550`) and `apply_own_goal_outcome` (`:3253`) each
call `self.persist(game, match)` in their own body. So they are on the
model's side in everything but their address *and* their save, and lifting
one means stripping the persist out of it first.

**That is not a free deletion, because the wrapper is not currently saving
either.** `apply_low_pass` never persists: it relies on `send_low_pass`
having done so before `finish_maneuver_resolution` or
`offer_scoring_attempt_choice` run. Strip the step's save and add none to
the wrapper, and the match reaches the spine unsaved -- and a spine step that
ends in a prompt hands the turn to a click that reloads the match out of the
save file. That is the beat-1 event-log bug CLAUDE.md already records,
reintroduced by the refactor meant to fix it. So the persist moves rather
than being removed: see the wrapper in
[Phase 2](#phase-2----stepresult-on-one-vertical-slice).

A fourteenth sync function in that file, `build_loose_ball_view`, is **not**
one of them: it constructs a `discord.ui.View` and stays where it is. It is
named here because it looks like the others in a listing and is not, and
because Phase 1 is what turns it into a prompt kind.

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
   - **Both halves already hold**: `d12ball/` imports no `discord` and
     contains no `async def` at all today. So the Phase 0 guard is a
     **ratchet on something already true**, not a cleanup with work behind
     it -- which is why it is cheap, and why it is worth adding before the
     phases that would otherwise erode it one convenience at a time.

2. **A rule is a question the model answers. The frontend asks it and
   renders the answer.** This is `RulesEngine`'s existing shape, extended
   to the flow.
   - **The line is between *what* and *how*, not between rules and
     words.** The model decides what is true and what is said about it --
     who may act, what the position is, the sentence describing it. The
     frontend decides how that reaches a person: a message or a `<div>`,
     an edit or a re-render, which lines are batched together, what a
     button looks like and what its custom_id is.
   - Said the short way: **nothing in `cogs/` may decide a rule, and
     nothing in `d12ball/` may know what a message *is*.** Narration text
     is the model's (principle 5) and is not a counter-example to this --
     a sentence is a fact about the position, where a `discord.Embed` is
     a medium.

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

9. **The driver persists; steps do not.** `self.persist(...)` is called at
   **95 sites** in `cogs/` today, and CLAUDE.md already records the class
   of bug that produces: an event recorded without a save in the same
   breath is one the next interaction never sees, which is how beat 1 of
   the tutorial vanished from the log. A step mutates and returns; the
   driver saves once, after it. This is the one place the refactor makes
   the bot *better* rather than only more portable, so it should be
   reviewed on its own merits.
   - **Until Phase 6, the cog wrapper holds that save.** A step lifted in
     Phases 2-5 stops persisting and the spine below it is still the cog's,
     so the wrapper persists immediately after the step and before
     dispatching what comes next; Phase 6 is what collapses those calls into
     the driver. See
     [Phase 2](#phase-2----stepresult-on-one-vertical-slice) -- the
     transition is where the bug this principle fixes can be reintroduced.
   - **It does not touch the other 52.** `cogs/` calls `save_games(...)`
     at 53 sites; one of those is inside `persist` itself and the other 52
     save the *game record* alone -- a message id, a status, a tutorial
     flag -- and have no match to write. Those stay exactly where they
     are. Collapsing them too would be widening the job.

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

**The single highest-leverage change in the project, and the one with no
rules risk**, because nothing mutates: the whole chain is a read.

### What moves

New `d12ball/prompts.py`:

- `PromptKind` -- one value per distinct prompt. **There are 26**, which is
  measured rather than estimated: the chain itself names 17 `View` classes
  over 25 `return` statements, and the three builders it delegates to add
  9 more (6 effect prompts, 2 run-back, 1 loose-ball). Any count near 20 is
  a count that forgot the builders.
- `PendingPrompt` -- `kind`, `ask` (the line put above it), and the handful
  of parameters the branches actually carry: `player_ids`, `player_id`,
  `side`, `maneuver_key`, `skill_type`, `free`.
- `pending_prompt(engine, game, match) -> PendingPrompt` -- the 280-line
  chain at `core.py:1581`, moved whole.

The chain's dependencies are already almost all model:

```
match.*                                        the bulk
engine.{settled_maneuver_winner,
        next_run_back_step, halftime_stage,
        get_player_definition}                 pure already
player_label                                   see below -- one decision owed
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

### The prerequisite: where a fetched emoji dict lives

**Done, landed on its own ahead of the rest of Phase 1** -- see "Naming
a player" in docs/design/naming-and-wording.md for the settled
reasoning, which now covers both dicts the same way.

`team_emojis` joined `role_emojis` on `RulesEngine`, in the same shape:
the engine owns the dict, `D12Ball.team_emojis` is a property over it
whose setter assigns to `engine.team_emojis`, and `cog_load`'s
`self.team_emojis = await load_team_emojis(...)` rebinds the engine's
own attribute rather than a second copy existing beside it.
`build_turn_prompt` and `build_loose_ball_prompt` read it off `self`
now, rather than taking it as a parameter.

That was the prerequisite because `player_label` crossing the seam is
what `pending_prompt`'s two `ask` lines (Mind Pull, injury test) need,
and `player_label` wants both dicts. `RulesEngine.format_player_label`
is that, engine-side -- **not** `format_roster_player_for_message` with
a flag added, since that method is a distinct, narrower thing already:
role badge only, no team emoji, for `apply_formation` and
`build_turn_prompt`, where a team emoji next to a card already on that
team's board would say nothing new. `D12Ball.player_label` forwards to
the new method so no call site moved.

Each returns `None` today and falls back to `PlayerActionView`; that becomes
`PromptKind.PLAYER_ACTION`, and the fallback stays exactly as deliberate as
it is now.

### What stays

`pending_turn_view` survives in the cog as a **mapping table** -- kind to
`View`, nothing else. Both its callers (`restore_saved_views`, which the
cog's `__init__` runs, and `resume_pending_prompt`) are untouched, which is
the point: they are the two that must not drift.

### Sizing

**405 lines move**, measured rather than estimated: `pending_turn_view` 280,
`build_effect_choice_view` 78, `build_run_back_view` 26,
`build_loose_ball_view` 21. What is left behind in the cog is a mapping
table of 26 entries and the `View` constructors they name -- call it 150
lines, which is the one number here that is a guess.

**The emoji prerequisite above is not in that 405.** It was a small,
separable change -- one dict moved, one property added, two engine builders
losing a parameter -- and it landed first, on its own.

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
  `StepResult`, with the `self.persist(game, match)` currently inside it
  stripped out. `apply_low_pass` in the cog becomes: call it, **persist**,
  post the narration, refresh if `board_changed`, dispatch `next`.

**The persist is in that list on purpose, and it is the transition rule for
every phase up to the last.** Through Phases 2-5 the cog wrapper saves
immediately after the step and before dispatching `next`; Phase 6 collapses
those wrapper calls into the one in the driver. Principle 9 is right about
the destination and says nothing about the way there, and the way there is
where this can break: a lifted step no longer saves, the spine underneath it
is still the cog's, and a spine step ending in a prompt hands the turn to a
click that reloads the match from the file. Drop the persist at this stage
and Low Pass's own events are gone by the next interaction -- which is the
bug principle 9 exists to fix, reproduced by the move that was meant to fix
it. The same applies to the four other self-saving steps as Phase 3 lifts
them.

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

The turn's own machinery, and where `interaction` dies from everything
Phases 1-3 didn't already reach:

- **the front half of a turn**: choosing and announcing a challenger
  (`auto_resolve_challenger`, `announce_uncontested_maneuver` -- see
  [sending-a-player.md](docs/design/sending-a-player.md)),
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

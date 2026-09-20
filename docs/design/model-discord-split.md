# The model/Discord split

Design notes for fool-bot; the map is [CLAUDE.md](../../CLAUDE.md), the rules are
[living-rules.md](../living-rules.md). The rules the split is made by are
CLAUDE.md's, in "The model and the Discord layer"; the plan is
[model-discord-split.md](../model-discord-split.md) -- a worksheet, not settled
history, read it for the phases still open. This file is for what has landed
and is permanent regardless of how much of the rest of the plan does: the two
guards from Phase 0, the seam Phase 1 cut, and the write side Phase 2 opened.

## `d12ball/prompts.py`

**Is the seam, in the one place it was cheapest to cut.** `pending_prompt`
answers "what is this match waiting on?" with a `PendingPrompt` -- a
`PromptKind`, the line to ask it with, and the few parameters the question
carries -- and the cog turns that into a `discord.ui.View`. It is the
principle "one reading, and it is in the model" made concrete, and it was the
first phase because nothing in it mutates: the whole chain is a read, so the
move had no rules risk to weigh against it.

- **The chain moved whole, ordering comments and all.** Which branch is
  checked before which carries real decisions -- setup, halftime, the window
  before the shootout and a time out are all read ahead of "no ball handler
  yet" because all four leave `active_player_id` None -- and those decisions
  live in the comments beside the branches rather than anywhere else. Splitting
  the chain, or paraphrasing it into a new shape, is how a second reading gets
  made by accident. See "Recovering a stuck game" in [recovery.md](recovery.md).
- **One kind per view class.** 26 of them: the chain's own 17 view classes
  over its 25 `return`s, plus the 9 the three folded-in builders add (6 effect
  prompts, 2 run-back, 1 loose-ball). A view built with different arguments for
  different situations is **one** kind carrying the difference in its
  parameters -- `SPEED_DELTA_CHOICE` is Setup Pass's, the dribbles' and
  Steal/Intercept's with `maneuver_key` telling them apart, and
  `LOW_PASS_CHOICE` is the plain and the free one with `free`. The alternative,
  a kind per situation, makes the cog's table a second copy of the chain's
  branching, which is the thing the phase exists to prevent.
- **A prompt carries what its branch decided and nothing else.** The six
  parameters (`player_ids`, `player_id`, `side`, `maneuver_key`, `skill_type`,
  `free`) are the ones the branches actually held. Anything else a frontend
  needs it asks the engine for with the match it already has -- the loose
  ball's candidate list is read in `view_for_prompt`, not carried, because a
  prompt is what to ask rather than a rendering brief.
- **`view_for_prompt` is the only place a kind becomes a view.** A later phase
  rendering a step's next prompt comes through it rather than growing a second
  table; two tables is the same failure as two chains, one step further down.
  `PLAIN_PROMPT_VIEWS` and `PARAMETERISED_PROMPT_KINDS` are asserted to cover
  `PromptKind` exactly, because a kind with no view would raise inside a
  restart, one game at a time.
- **The game became a parameter, so the lookup is eager.** The chain read
  `self.games[game_id]` inside the run-back branch alone; `pending_prompt`
  takes the game. Neither production caller can reach it without one --
  startup iterates `self.games.values()` and resume is handed the game -- but
  two shootout fixtures had never registered theirs, and now do.
- **The fixtures are shared, and were recorded first.**
  `tests/prompt_fixtures.py` stands a match in every branch with no discord in
  scope; `tests/test_d12ball_prompt_mapping.py` asserts the view and the ask
  through the cog, `tests/test_d12ball_prompts.py` the kind and the parameters
  through the model. The mapping test was written against the old chain and run
  green there before anything moved -- that is what makes it evidence rather
  than the new code agreeing with itself, and it is the pattern the later
  phases should copy.

## `d12ball/flow/`

**Is the write side of the same seam.** `pending_prompt` answers what a
match is waiting on; a flow step is what *changes* it. Each takes the
engine and the match, mutates, and hands back a `StepResult` -- the
narration, whether the board moved, and what happens next. Phase 2 cut
this on Low Pass alone and nothing else; Phase 3 follows a rank at a
time, and rank O2 brought the two dribbles -- so `effects.py` holds
four cards (two of them one function parameterised) and
`cogs/d12ball/effects.py` still holds nine.

- **Low Pass was the slice because it is not a toy.** Mid-sized, with a
  role-ability branch (the Winger's set-up, the one path that ends
  somewhere other than `finish_maneuver_resolution`), a continuation
  (the free pass a beaten Skilled Pass hands the defense), a shared
  function with Skilled Pass, and an advanced cost charged in the middle
  of its own sentence. A slice with one branch would have settled
  nothing.
- **`FollowOn` is transitional and the enum is the record.** The spine a
  step ends by naming -- `finish_maneuver_resolution`,
  `offer_scoring_attempt_choice`, later `begin_run_back` and
  `begin_loose_ball` -- is still async and still in the cog through
  Phase 5. A step names one as a member of the closed `FollowOnStep`
  enum with its arguments, and `D12Ball.follow_on_methods` is the only
  thing that turns a member into a call. Closed rather than a callable
  or a method name the cog would `getattr`, for two reasons: nothing on
  the model's side can reach into `cogs/` by spelling a string, and the
  enum's membership *is* the list of what the cog still dispatches, so
  Phase 6 reads the file rather than six pull request descriptions.
- **The narration never rides in the follow-on's arguments.** A Low Pass
  posts no message of its own: what it says opens the message the next
  step sends. So `StepResult.narration` is a list of blocks, and
  `dispatch_step_result` joins them on a space and passes them as that
  step's `lead_in`. Putting the joined string in `FollowOn.kwargs`
  instead would have worked and would have been wrong -- batching is the
  frontend's (principle 8), and a web app with no five-in-five bucket
  should not inherit Discord's answer to it. It is also what keeps the
  move from costing a request; see [rate-limits.md](rate-limits.md).
- **A `PendingPrompt` in `next` renders through `view_for_prompt`**, the
  same table a restart restores through. No Low Pass branch ends on one
  today (the receiver pick is asked before the pass is applied), so the
  dispatcher's branch is asserted directly rather than through a
  fixture. It is there from this phase on so the branch Phase 3 needs
  cannot arrive as a second table.
- **The step does not save; the wrapper does, immediately, before the
  dispatch.** `send_low_pass` persisted inside itself and
  `apply_low_pass` relied on it -- so stripping the save and adding none
  would have left the match reaching the spine unwritten, and a spine
  step ending in a prompt hands the turn to a click that reloads the
  match from the file. That is the beat-1 event-log bug in
  [gotchas.md](gotchas.md) reintroduced by the refactor meant to fix it.
  The `self.persist` count in `cogs/` is unchanged at 95 across this
  phase, which is the shape of the transition in one number: one left
  the step, one arrived in the wrapper.
- **A step takes `game` only where it reads the record.**
  `low_pass_step` does not and so does not take one; both dribbles do,
  because charging an exhaustion token tests a threshold the *game*
  decides -- a Cyborg's is a flat 7. That is what brought
  `apply_exhaustion` and `describe_exhaustion_gain` onto `RulesEngine`,
  with `condition_emojis` (the third emoji dict to land there) and the
  five `get_*_emoji` fallback lookups into `formatting.py`: a step that
  charges a token has to be able to say so, narration is the model's,
  and a cog method cannot be called from down here. `D12Ball` keeps a
  forwarding method for each, so none of the nineteen call sites moved
  -- the shape `team_emojis` took in Phase 1a. See
  [naming-and-wording.md](naming-and-wording.md).
- **A rank can add a `FollowOnStep` member, and O2 did.**
  `OFFER_SPEED_CHOICE` is the ball-speed manipulation every dribble
  (and every steal) ends on. It is a follow-on rather than a
  `PendingPrompt` because the model has not decided anybody is being
  asked: `offer_speed_choice` answers for Dinky itself and holds a
  tutorial beat's prompt behind a note, and both of those are the
  frontend's. A step returning the prompt directly would have moved
  that decision without meaning to.
- **The persist rule paid for itself here.** `apply_dribble_advance`
  persisted and *then* called `pay_clear_cost`, which charges a beaten
  Clear's two tokens and re-tests the Exhausted threshold -- so both
  writes landed after the save, and the next click read the match back
  off a file that never had them. Lifting the whole effect into the
  step, with the wrapper saving after it, fixes it without anybody
  deciding anything: it is the beat-1 bug in [gotchas.md](gotchas.md)
  one more time, and principle 9 is the general answer to it.
- **The fixtures were recorded first, the same way Phase 1b's were.**
  `tests/low_pass_fixtures.py` stands a match in every branch with no
  discord in scope; `tests/test_d12ball_low_pass_recording.py` asserts
  the narration, the board flag and the follow-on **through the cog**
  and was run green before anything moved, and
  `tests/test_d12ball_low_pass_flow.py` asks the model the same
  questions. The table names the follow-on by `FollowOnStep` member
  name, a string, which is what let it be written before the package
  existed. `tests/dribble_fixtures.py` with
  `tests/test_d12ball_dribble_recording.py` and
  `tests/test_d12ball_dribble_flow.py` is rank O2's copy of the same
  three files, ten branches over the two cards.
- **What is in `FollowOnStep` is asserted in
  `tests/test_d12ball_package_shape.py`**, not in any one rank's own
  tests, along with `D12Ball.follow_on_methods` covering it exactly --
  a member with no row raises inside a resolved maneuver, one card at
  a time. It started out in Low Pass's module, where every later rank
  would have had to edit an assertion about a card it was not
  touching.

## `tests/test_model_purity.py`

**Is the line itself.** Every module under `d12ball/` **and
`gamesaves/d12ball/`** imports **in a fresh subprocess** with `discord`
refused, none of them defines an `async def`, and none of them imports from
`cogs/`. All three hold today, so this is a **ratchet on something already
true** -- the purity was kept by habit, and habit is what erodes once flow
code starts moving across the line.

- **`gamesaves/d12ball/` is checked too, not just `d12ball/`.** The plan
  leans on `gamesaves/d12ball/storage.py` being pure -- it is what makes
  `MatchState.to_dict` "already a wire format" rather than a claim to prove
  later -- so the ratchet covers the module the plan actually depends on,
  not only the one it is named after. `gamesaves/tethysdeck/`, a different
  prototype's save, is left out.
- The subprocess is load-bearing, not fastidious. `unittest discover` imports
  every test module before running anything, so an in-process version of this
  check would find half of `d12ball/` already in `sys.modules`, and
  `import_module` hands back the cached module without re-executing it --
  passing against modules it never actually imported.
- The `discord`-refused assertion is checked with a `meta_path` finder rather
  than a bare `import discord` probe, so a transitive import is caught too:
  injecting `import discord` into `formatting.py` fails the check naming both
  that module and `engine`, which imports it.
- The no-`async def` assertion walks the AST rather than grepping, so a
  definition nested in a class or a function reads the way the interpreter
  reads it.
- The no-`cogs/`-import assertion is asserted and reported on its own,
  separate from the `discord` check, even though a stray cog import would
  trip that one too (naming `discord` itself, which is not the useful
  message).

## `tests/test_golden_transcript.py`

Plays the tutorial through the real cog and compares the narration byte for
byte, the sequence of prompts, and the final `to_dict()` key for key, against
`tests/golden/`. `FOOLBOT_UPDATE_GOLDEN=1` rewrites those files, so **a
wording change is a diff in a pull request rather than a test somebody
silences** -- the "What a message says" rules in
[naming-and-wording.md](naming-and-wording.md) are rules, and a refactor that
rewords a result has changed the game.

- **The module RNG is seeded, not `randint` patched.** The flow also reaches
  `random.shuffle` and `random.choice`, so patching one call misses the
  others; the seed is restored afterwards, since it is global and would
  otherwise leak into whatever test runs next.
- **`GOLDEN_SEED` is one that scores.** The tutorial's closing shot is
  deliberately unscripted (see "Determinism: rails and dice" in
  [tutorial.md](tutorial.md)), so two seeds give two different transcripts; a
  seed that missed would pin the unusual branch as the reference. A test
  asserts the recorded run is the one with the goal in it, so the golden
  cannot quietly become the missed-shot run.
- **It is stable**: two runs on one seed agree (asserted), and the transcript
  is identical under `PYTHONHASHSEED` 0, 1 and 42 (checked by hand) -- a set
  of player ids iterated into a message would otherwise vary by machine
  rather than by the change that broke it.
- **It covers one basic-mode solo game on board 7**, the only multi-turn game
  the suite can drive today -- no advanced maneuver, no species ability, no
  halftime, no shootout, no time out. Rewording two of the three `Ball speed
  is now` sites in `effects.py` did not fail it, because the tutorial only
  reaches the third. Don't read a green golden as "the wording is covered";
  a phase that moves narration the golden doesn't reach should add its own.

## Two things about running the suite that cost time to rediscover

- **`requirements.txt` will not install below Python 3.13.** It pins
  `audioop-lts`, a backport that exists only because `audioop` left the
  standard library in 3.13 and has no distribution for earlier versions. On
  3.11 or 3.12, where `audioop` is still stdlib, the pin is both unnecessary
  and unsatisfiable -- `pip install discord.py Pillow python-dotenv` is
  enough to run the suite there. CI pins 3.13 and is unaffected.
- **Five tests fail when the suite runs as root, and none of them is a
  regression.** `test_an_unwritable_folder_reads_as_no_record` and the four
  `GameStorageTests` about unreachable folders all simulate a directory that
  cannot be written to, and uid 0 bypasses permission bits -- a write into a
  `chmod 000` directory simply succeeds. They pass in CI, which runs as an
  ordinary user. Before treating any suite failure as a regression, re-run
  the same commit on the branch's real base (`origin/main`, not a local
  `main` that may be far behind it).

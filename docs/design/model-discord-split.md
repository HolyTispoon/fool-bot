# The model/Discord split's safety net

Design notes for fool-bot; the map is [CLAUDE.md](../../CLAUDE.md), the rules are
[living-rules.md](../living-rules.md). The plan this guards is
[model-discord-split.md](../model-discord-split.md) -- a worksheet, not settled
history; read it for the phases and the principles. This file is for the two
guards Phase 0 landed, which are permanent regardless of how much of the rest
of the plan lands.

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

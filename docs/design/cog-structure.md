# Why the cog is mixins

Design notes for fool-bot; the map is [CLAUDE.md](../../CLAUDE.md), the rules are [living-rules.md](../living-rules.md).

## Why the cog is mixins

`cogs/d12ball/` is six mixin classes assembled into one `D12Ball` in
`__init__.py`, and the choice of mixins over collaborator objects is the whole
design.

- **These methods co-operate through the cog's own state and call each other by
  the hundred.** `self.foo(...)` has to keep working across every seam, and a
  mixin is the only split where it does, untouched. Turning those calls into
  explicit dependencies on collaborator objects is a far larger change and a
  different one -- don't start it by halves.
- **The seams are the author's, not invented.** The single file carried sixteen
  `# -- Low Pass ---` banners, and the split follows them. Each mixin is a
  contiguous run of the old file, so the moves are readable as moves.
- **The mixin order carries no resolution.** It is the order the file read in.
  No method is defined by two mixins, and `test_no_method_is_defined_by_two_mixins`
  in `tests/test_d12ball_package_shape.py` is what keeps that true -- a name in
  two of them means one is dead code, chosen by the MRO rather than by anybody.
- **`commands.GroupCog` comes last**, so the mixins sit ahead of it in the MRO.
  discord.py collects commands by walking the whole MRO (`CogMeta.__new__`), so
  a command or subgroup defined on a mixin registers exactly as one on the cog
  would -- verified against the assembled class, which has the same 221 methods
  and the same 17 app commands as the single file did.
- **The command module is `slash_commands.py`, not `commands.py`.** A submodule
  binds its own name into the package namespace, so `commands.py` would shadow
  `discord.ext.commands` in the very file that reads `commands.GroupCog`.
- **`pending_turn_view` moved whole, into `core`.** It was a flat, ordered
  dispatch chain whose ordering is load-bearing and mostly comments explaining
  why each branch sits where it does -- see "Recovering a stuck game" in [recovery.md](recovery.md). A second
  copy of that chain is the failure mode; splitting it is how you get one.
  That reasoning is why the chain later moved *whole again*, out of the cog
  and into `d12ball/prompts.py` (Phase 1 of
  [model-discord-split.md](../model-discord-split.md)); what `core` keeps is
  the mapping from a `PromptKind` to a view, which carries no ordering at all.
- **What a mixin holds is shrinking, and the six seams are not moving.**
  Phases 2-6 of [model-discord-split.md](../model-discord-split.md) lifted
  the decisions out of `core`, `effects`, `periods` and `turnovers` into
  `d12ball/flow/`, and what each of those mixins keeps is the same
  responsibility with the rules taken out of it: `core` the turn's Discord
  spine (the three dispatchers, `follow_on_methods`, `view_for_prompt`) and
  the cog wrappers for the front half of a turn;
  `effects` one wrapper per card plus the loose ball's and the own goal's
  posting; `periods` the clock's tail; `turnovers` the coaching windows, the
  run-back cascade's *batching* and the run-back prompt's field strip.
  **A wrapper is two lines now** -- run the step, dispatch -- because Phase
  6 moved the save into `dispatch_step_result`, the driver's caller
  (principle 9 in [CLAUDE.md](../../CLAUDE.md)). The reason a wrapper is
  still a method on a mixin rather than a function is the first bullet
  above: its callers spell it `self.foo(...)` and there are hundreds of
  them.
- **The first bullet is still true, and Phase 6 is what would make it
  false.** "These methods co-operate through the cog's own state and call
  each other by the hundred" was the argument for mixins, and the phase
  that empties the cog is the phase that retires it. It has not happened
  yet: `d12ball/flow/driver.py` took the **loop** -- what runs after a step
  -- but the cog kept every entry point a click arrives at, and the figures
  say so. 190 async methods in `cogs/d12ball/`, 159 of them taking an
  `interaction`, both unchanged by the move. What did change is that none
  of them decides what happens next any more; five of the steps they used
  to dispatch are run by the driver, and the rest are pictures, pins and
  gates waiting on a loop that can stop *before* a step as well as after
  one. Until then this section says what it always said, because the code
  it describes has not moved.
- **A method that is now only a forwarder stays where its callers are.**
  `player_label`, `apply_exhaustion`, `injured_word_and_emoji`,
  `maneuver_prompt_wording` and `run_back_space_prompt` all forward into the
  engine or the flow. Keeping them is what made each of those lifts a move
  of one function rather than a rename across ninety call sites.

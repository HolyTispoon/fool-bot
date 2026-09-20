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
- **What the six mixins hold has changed under the split, and the names have
  not.** After Phase 4 of [model-discord-split.md](../model-discord-split.md)
  the spine's *decisions* are `d12ball/flow/`'s and what is left in each mixin
  is the posting: `core` is the lifecycle, the lookups, `persist`,
  `dispatch_step_result` and the follow-on table; `effects` is one banner per
  maneuver plus how a loose ball reaches a channel; `turnovers` is the run
  back's batching and the prompts either side of it; `periods` is the clock's
  messages, halftime and the shootout. The mixin a method lives in is still
  the run of the old file it came from -- what changed is that most of them
  are now four lines around a flow step. See
  [model-discord-split.md](model-discord-split.md) for which.
  - **The wrappers are where the phase's one repeated shape lives.** A
    follow-on that is handed narration but has no prompt of its own for it to
    open posts it first -- `begin_effect_resolution`,
    `begin_maneuver_action_selection`, `start_set_up_shot`,
    `decline_scoring_attempt` and `announce_last_possession` all do. Each is
    the same two messages in the same order as before the phase; what moved is
    which function sends the first one. A wrapper may read *which shape* a
    result took, because how it goes out is the frontend's; what it may not do
    is decide which it is.

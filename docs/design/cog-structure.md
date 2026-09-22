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
  and into `d12ball/prompts.py` (Phase 1 of the model/Discord split); what
  `core` keeps is the mapping from a `PromptKind` to a view and to the
  picture that kind carries, which carries no ordering at all.
- **What a mixin holds shrank, and the six seams did not move.**
  Phases 2-6 of the model/Discord split (see
  [model-discord-split.md](model-discord-split.md)) lifted every decision
  out of `core`, `effects`, `periods` and `turnovers` into `d12ball/flow/`,
  and what each mixin keeps is the same responsibility with the rules
  taken out of it: `core` the presenter (`present`, `post_group`,
  `render_prompt`, `view_for_prompt`) over `GameService`, which the cog
  reaches through its `service` property; `effects` the two dice images
  that go between a roll's lines; `periods` the final board and the
  shootout's menus; `turnovers` the coaching image and `resume_game`;
  `presentation` the pictures. The sixty-odd two-line entry points that
  used to sit beside them -- call one step, or name one by its
  `FollowOnStep`, and dispatch -- are gone: nothing in the bot called
  them once every click went through the driver, and the tests that
  drove a step through one drive it through `tests/cog_steps.py` now.
  See [game-service.md](game-service.md).
- **The first bullet is now half true, and it is the half that keeps the
  mixins.** "These methods co-operate through the cog's own state and call
  each other by the hundred" was the argument for mixins. They still call
  each other -- an entry point calls the dispatcher, the dispatcher calls
  the renderers, the renderers call the image builders -- but nothing they
  say to each other is a rule any more: `d12ball/flow/driver.py` runs every
  step of a turn and answers every prompt, and a click lands on
  `SafeView.apply`, which is `GameService.apply_action` with the refusal
  rendered.
  Turning the remaining calls into collaborator objects would be the "far
  larger change and a different one" it always was, and it is still not
  started. What the phase changed is what the mixins are *for*: they are a
  frontend, and the figures say how much of one -- measured by the rule in
  "How the split is measured" in [model-discord-split.md](model-discord-split.md),
  which is what to re-run rather than quote.
- **A method that is now only a forwarder stays where its callers are.**
  `player_label`, `apply_exhaustion`, `injured_word_and_emoji`,
  `maneuver_prompt_wording`, `run_back_space_prompt`,
  `record_turn_action`, `apply_position_swap` and `apply_reposition`
  all forwarded into the engine or the flow (the first three render
  what they forward to, since step 9's tokens). Keeping them is what made each of those lifts a move
  of one function rather than a rename across ninety call sites.

# The test suite

Design notes for fool-bot; the map is [CLAUDE.md](../../CLAUDE.md), the rules are [living-rules.md](../living-rules.md).

## The test suite

**A patch target naming a module is a patch on that module's own binding.**
This bit both package splits, and bit the cog's hardest: 192 patches of
`cogs.d12ball.save_games` against six mixins that all save.
`cogs/d12ball_views` was one module, so
`mock.patch("cogs.d12ball_views.save_games")` covered every view in the game;
it is a package now, and `from ... import save_games` binds the name into
each submodule, so the same patch reaches none of them. It fails *silently*
-- the patch applies to the package, the test passes, and the real save
writes `data/d12ball_games.json`, because not one of those forty-odd patches
was ever bound with `as` or asserted on. `tests/save_patches.py` is the one
answer for all of them (`suppressed_view_saves`, `suppressed_cog_saves` and
`suppressed_full_image_links`, each patching every submodule that names
the thing), and `tests/test_d12ball_package_shape.py` fails if a submodule
starts saving and is not named there.

- **Naming the right module is not the whole of it, because most views do
  not save through their own binding.** `suppressed_view_saves` covers the
  three view submodules that call `save_games` themselves; every other view
  saves through `self.cog.persist`, which is `cogs.d12ball.core`'s binding
  and needs `suppressed_cog_saves`. A test that wraps only the first is the
  same silent failure one step along -- it reads as suppressed, and the cog
  writes underneath it. Nineteen call sites on `main` were doing exactly
  that, across six files, and the suite was green for all of them. **A view
  usually needs both helpers**, not the one that matches its package.
- **A forgotten suppression now fails the test that forgot it.**
  `save_patches.guard_stray_saves` replaces `save_games` in all ten modules
  that bind it with a stand-in that raises, and importing `save_patches`
  arms it -- which covers the whole run, because `unittest discover` imports
  every test module before it runs any test, so the nine that exercise the
  cog without importing `save_patches` are guarded too. It arms the
  *modules'* bindings and never `gamesaves.d12ball.storage` itself, which is
  what leaves `test_game_storage.py` -- the one place that means to reach a
  disk, through a `GAMES_FILE` pointed at a tempdir -- working untouched.
  `mock.patch` restores what it replaced, so a suppression helper puts the
  guard back on its way out.
  - **`SAVING_MODULES` is armed, and `cogs/debug.py` is why it is a third
    list.** `/debug reset_channels` saves too, and belongs to neither
    package, so the two lists the suppression helpers use would never have
    named it. `StraySaveGuardTests` walks `cogs/` and fails if any module
    binds `save_games` without being named -- the guard can only see a
    binding the list knows about.
- **The way to be sure is still to make the real function raise and run the
  suite.** Replacing `gamesaves.d12ball.storage.save_games` with a recorder
  before the tests import anything lists every call site that reaches it,
  which is the only thing that found the nineteen. The list should now be
  twelve, all of them `test_game_storage.py` testing storage on purpose.
  That is the check worth repeating after anything that moves a view -- and
  the cheaper version of it is that a full run must not create `data/` at
  all.
- **`cogs.d12ball_views.random` and `.discord` were never the views'.** Both
  named the global module through the views' namespace, so those patches
  were always global; they say `random.` and `discord.` now, which is what
  they always did.


**A recorder is tested where a real game is already being played.** The event
log behind the statistics is written at seven separate funnels, and a recorder
that fires on the wrong object -- or before a save that never happens -- passes
every unit test and loses the event. So `tests/test_d12ball_stats.py` covers
the fold and the two suites that already play real games cover the writing:
`TutorialPlaythroughTests` (five scripted turns through the real cog) and
`EveryMatchupResolvesTests` (all thirty-six pairings). See "Where the
statistics are tested".

**A test names a player by their role, not by their name.** The roster is data
the author revises, and a revision is not a code change: 36250a9 renamed five
orange players and broke the suite on `main`, independently of the branch it
landed on, because tests had picked their fixtures by id. Almost none of them
were about *who* the player was -- they wanted a fielded card, or a fullback,
or three of a side to drain the bench with. `tests/roster.py` is how they ask
for that: `fielded(match, PlayerRole.STRIKER)`, `benched(...)`,
`field_players(match)[:3]`, and `roles(ids)` for a test asserting what a deal
fielded rather than who.

- **Every team is dealt the same six roles and benches the same three**, so
  those answer for any team, and a side is named by its `TeamSide` rather than
  by which colour is playing it. The side defaults to home.
- **The standard deal's own tests assert roles against
  `BasicRuleset.standard_setup` itself**, since the deal *is* by role
  (`default_formation_deal`) -- a list of six names was a snapshot of the data
  rather than a reading of the rule, which is why it broke.
- **A test genuinely about a particular player keeps naming them**: the roster
  listing, `test_d12ball_player_import`, and the portrait-art check, which is
  the one that *should* fail when a rename lands without the matching image.
  Everything else should be answerable after a rename without being touched.
- **A team's colour comes from `TEAM_COLORS`** for the same reason -- a test
  carrying `"#f28c28"` under the label `"Orange"` had been wrong since the
  palette moved and nothing noticed, because it was only ever passed to a
  renderer as a string. See "Team colors" in [teams-and-players.md](teams-and-players.md).
- **A test asserting a label the bot builds out of a name puts the name in
  by lookup**, rather than baking the whole string. The High Pass distance
  buttons (`test_d12ball_high_pass.py`) read
  `f"3 spaces (V2-{striker} [SK])"` off `display_name(fielded(...))`: the
  wording, the space code and the role initials are what is under test, and
  the card standing there is not.
- **A tie broken on roster order is read off the roster, never written down.**
  `test_dinky_breaks_a_role_tie_on_bench_order` asks the bench which of the
  two tied roles it lists first, because the rule is "bench order decides" --
  naming the winner is asserting today's ordering of the data.
- **Synthetic fixtures carry names that are obviously off the roster** --
  `Defender A`, `Shooter`, in `test_d12ball_shot_defence.py` and the dice
  captions in `test_d12ball_components.py`. They are built in the test file
  and never looked up, so a real name there cannot break; it just reads as a
  roster reference and sends the next rename chasing it.
- **`grep` the roster against `tests/` to check, and mutate the data to be
  sure.** Both were done when this landed: no player id or display name
  appears anywhere in `tests/`, and the suite was re-run against a renamed
  id, a renamed player, a reordered roster and a cross-team reshuffle. What
  a reshuffle *cannot* survive is a team losing one of the six standard-setup
  roles or its ninth player -- `load_player_catalog` and
  `default_formation_deal` refuse the data outright, which is the rules
  talking and not the suite.

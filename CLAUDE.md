# fool-bot

A Discord bot for playing and testing Prophetic Fool prototypes. The active
prototype is **D12 Ball**, a board game whose state is rendered to a PNG and
posted into a Discord channel.

**This file is a map.** The reasoning behind every design decision is in
[docs/design/](docs/design/), one file per topic, and the table at the bottom
says which to read before touching what. Read the file for the area a task
touches before changing it; don't read them all.

## Running it

```bash
pip install -r requirements.txt     # needs a .env with DISCORD_TOKEN
python3 foolbot.py
```

```bash
python3 -m unittest discover -s tests
```

## Where things live

| Path | What it is |
| --- | --- |
| `foolbot.py` | Bot entry point; generic deck/dice commands. Loads the cogs. |
| `botstate.py` | The little the bot remembers between runs, in `data/bot_state.json` |
| `discord_emoji_cache.py` | The cache-with-cooldown shape shared by every cog's application-emoji lookup -- only the retry timing, not what each cog loads |
| `botlog/` | Console logging setup, and the #logs channel mirror -- [logging.md](docs/design/logging.md) |
| `cogs/d12ball/` | All D12 Ball slash commands and the Discord interaction flow, as six mixins assembled into `D12Ball` in `__init__.py`: `core` (lifecycle, lookups, `persist`, the spine of a turn, `pending_turn_view`), `effects` (one banner per maneuver), `turnovers` (run back, time out, out-of-bounds pickup), `periods` (clock, halftime, shootout), `presentation` (prompts, images, channels, the AI turn, tutorial narration), `slash_commands` (every command, the three subgroups, the startup sweep). `from cogs.d12ball import D12Ball` is unchanged -- [cog-structure.md](docs/design/cog-structure.md) |
| `cogs/d12ball_helpers.py` | Constants and free functions shared by the cog and its views -- emoji lookups, player/team formatting, channel naming, the authorization predicates. Re-exports everything `d12ball/formatting.py` holds; what stays here fetches emoji or touches discord.py itself |
| `cogs/d12ball_views/` | The `discord.ui.View` classes, one per prompt a player can be shown, in ten modules (`base`, `setup`, `turn`, `rolls`, `runback`, `effects`, `coaching`, `halftime`, `loose_ball`, `shootout`). `__init__.py` re-exports every name. `base` holds `SafeView` (`load_match`/`require_match`, the `may_act_for*` gates) and imports from no sibling, which keeps the package a DAG |
| `cogs/d12ball_boards.py` | The write gate on a game's persistent board message: `BoardRefresher` and one `BoardRefreshState` per game. `D12Ball` keeps a thin forwarding method for each of its six methods -- [rate-limits.md](docs/design/rate-limits.md) |
| `cogs/debug.py` | Maintenance commands: the PBD channel-and-count reset, the archive export |
| `d12ball/components.py` | Game state model -- `MatchState`, `BoardState`, `TeamSetup`, `PlayerCatalog`, `MATCH_SAVED_FIELDS` |
| `d12ball/engine.py` | `RulesEngine` -- every decision and candidate list that never touches Discord, over the fixed catalogs and AI strategies. `D12Ball.engine` is the one instance; call sites read `self.engine.foo(...)`. Includes the prompt-text and matchup-data builders that need only the match and the catalogs |
| `d12ball/prompts.py` | `PromptKind`, `PendingPrompt` and `pending_prompt` -- the one reading of what a match is waiting on, with no Discord in it. The cog maps a kind to a view and renders the `ask` -- [model-discord-split.md](docs/design/model-discord-split.md) |
| `d12ball/flow/` | The turn's flow with no Discord in it, five modules: `result.py` (`StepResult` and the transitional `FollowOn`), `effects.py` (**all twelve maneuvers** as nine steps -- five cards are their rank-mate parameterised, Setup Pass is three -- and the own-goal roll), `arrivals.py` (the two arrival gates and the five arrival points they guard, which moved together because the ordering between them is a rule), `turnovers.py` (the run back, as a generator yielding a `StepResult` per pass, and the out-of-bounds pickup) and `turn.py` (the front half: the challenger, the picks, and which card won). A step changes the match and says what happened; it sends nothing and saves nothing -- [model-discord-split.md](docs/design/model-discord-split.md) |
| `d12ball/formatting.py` | Plain-text formatting over match/game/zone data with no Discord dependency -- space codes, side labels, player names |
| `d12ball/game.py` | `D12BallGame` (per-channel game record), `Team`, `TEAM_PAIRS`, `GameMode`, `Formation` |
| `d12ball/render.py` | Board, matchup and dice image rendering (Pillow); `TEAM_COLORS` |
| `d12ball/cards.py` | The twelve maneuvers as cards -- the printed face, the shared back, the hand the bot shows |
| `d12ball/player_cards.py` | The roster as cards, print-only, over `cards.py` |
| `d12ball/species_cards.py` | The four species abilities as a three-card reference set, print-only |
| `d12ball/boards.py` | The field, jumbotron and team boards, print-ready for the tabletop game |
| `d12ball/rules_doc.py` | Reads `docs/living-rules.md` for the two rules commands |
| `d12ball/stats.py` | Every statistic `/d12ball stats` reports, as a fold over `MatchState.events`. No Discord and no game flow |
| `d12ball/tutorial.py` | The scripted opening a tutorial game plays -- the five beats as data, and the rails |
| `d12ball/data/` | `players.json`, `basic_rules.json`, `maneuvers.json`, `species.json` -- regenerated whole by the import scripts, never edited by hand |
| `d12ball/images/` | Card art, emoji, the four species icons (ink and coloured) |
| `d12ball/fonts/` | Bundled DejaVu and Racing Sans One, loaded by absolute path |
| `gamesaves/d12ball/storage.py` | Persistence to `data/d12ball_games.json`, and the legacy-save migrations |
| `gamesaves/d12ball/archive_export.py` | Writing one finished game's export to disk for `/debug export_archived_games` |
| `gamesaves/d12ball/hub.py` | The per-guild hub message pointers, in `data/d12ball_hubs.json` |
| `scripts/` | CLI tools used repeatedly (not one-off scratch work) |
| `tests/roster.py`, `tests/save_patches.py` | Naming a test's player by role; suppressing saves -- [testing.md](docs/design/testing.md) |
| `docs/living-rules.md` | **The whole ruleset as it currently stands.** The one thing to check a mechanic against |
| `docs/rules-log.md` | Every rules change, dated and sourced; what is still open; where upstream is behind |
| `docs/gambit-matrix.md` | The worksheet the gambits were built from, cut to what is still open. **Nothing in it is a rule** |
| `docs/model-discord-split.md` | The worksheet the model/Discord split is being built from -- the phases still open, what deliberately does not move, the bot-testing stop each phase ends on. **Nothing in it is a rule**; the principles it was written around now live in "The model and the Discord layer" below, moved there when Phase 1 landed |
| `docs/tts-module.md` | The worksheet the Tabletop Simulator module is being built from -- the four decisions already taken, the five phases and the in-TTS stop each ends on, what the convenience scripts may and may not do. **Nothing in it is a rule** |
| `docs/model-discord-split-prompts.md` | The prompt each phase of that worksheet is run from, one conversation per phase. Deleted phase by phase as they land, and with the worksheet at the end |
| `docs/design/` | The design notes this file points at -- one topic per file |

## Hard rules

These hold everywhere. Each has its reasoning in the design doc named beside it.

**Rules and data**
- **Read [docs/living-rules.md](docs/living-rules.md) before changing anything that models the game.** Several mechanics exist only in the code, so a bug and a deliberate decision look identical there; take rules questions to the author (inline comments on a docs PR have worked far better than chat) rather than inferring them. A rules change is the living rules plus a dated `docs/rules-log.md` entry, as its own commit. -- [rules-and-data.md](docs/design/rules-and-data.md)
- **Don't guess a sheet gid; run the import scripts.** `gid=0` is a stale tab that still answers. Every ability comes in twice (`ability`, `ability_short`) from the sheet's own columns -- **never shorten an ability in code**, and `strip_formula_escape` runs on every ability column.
- The rules commands read `docs/living-rules.md` itself; there is no second copy of the rules text anywhere in the bot.

**State and saves** -- [gotchas.md](docs/design/gotchas.md)
- **Save a match with `D12Ball.persist(game, match)`**, never `to_dict` + `save_games` by hand. `save_games` alone is only for a change to the game record. Anything that records state or an event saves in the same breath, or the next click reloads without it.
- **A new `MatchState` field goes in `MATCH_SAVED_FIELDS`** (or `MATCH_EXPLICIT_FIELDS` when it needs its own handling); the suite fails until it does. The wire format is not the table's to change.
- **Legacy fallbacks stay** (`player_board`, `tie_mode`, `ceded`, `legacy_maneuver_key`, the reshuffle migration, the `shootout_test` resume kind, ...) until no half-finished game can predate them. Both developers run the bot against their own saves. Don't add migration passes; don't rename saved keys.
- `data/` is untracked runtime state, per checkout. Never commit it. `save_games` never raises and a save failure never fails the turn.
- **`d12ball/prompts.py`'s `pending_prompt` is the only reading of "what is this match waiting on?"**; `pending_turn_view` is the Discord mapping over it, and `view_for_prompt` the only place a `PromptKind` becomes a view. A second copy of that chain is how a resume comes to offer a different prompt from the one a restart restores. -- [recovery.md](docs/design/recovery.md)
- `MatchState.record_goal` and `record_event` are the only writers of the goal log and the event log; nothing in the game may read the event log to decide a rule. -- [clock-and-records.md](docs/design/clock-and-records.md)
- **Maneuvers are keyed** (`low_pass`, `double_team`), never held or compared by display name; `RulesEngine.maneuver_name` is the only way back to a name, for wording alone. -- [maneuvers.md](docs/design/maneuvers.md)
- **`RulesEngine.maneuver_tiers` is the only answer to which cards a coach may play, and it is asked per side.** A gambit is held only by a coach whose team is behind (`may_play_gambits`), so the two hands on one prompt can be six cards and three -- the buttons, the hand image and the click that answers all ask it, once each per side. -- [maneuvers.md](docs/design/maneuvers.md)
- **Nothing reads `game.advanced_maneuvers`, `game.species_abilities` or `PlayerDefinition.species` to decide a rule.** `RulesEngine.gambits_apply`, `species_abilities_apply` and `has_species_ability` are the answers. -- [species-abilities.md](docs/design/species-abilities.md)

**Discord**
- **Rate limits: the fix is always fewer requests, never slower ones.** Every edit to any message in a channel shares one ~five-in-five-seconds bucket; only the board message may be edited through the channel; `BOARD_REFRESH_INTERVAL` stays above five seconds; a cascade of the bot's own steps is one message and one board refresh at the end; render once, upload twice (`png=`); only `post_new_play_board` pins. **Read [rate-limits.md](docs/design/rate-limits.md) before adding any send, edit or pin to a game flow.**
- A new prompt or announcement sent after a click's own answer goes through `send_new_prompt`, or it renders as a reply to the wrong message.
- Every render goes through `asyncio.to_thread`. Pillow is CPU-bound and blocks the heartbeat.
- **Use `logging`, not `print`.** ERROR reaches #logs and means somebody must act; INFO/WARNING are console-only. The sink never logs its own failures. -- [logging.md](docs/design/logging.md)
- **Nothing rolls dice on its own.** Every roll waits behind a button either coach may press. -- [maneuvers.md](docs/design/maneuvers.md)
- **Authorization is `SafeView.may_act_for` / `may_act_in_game`** (the coach a button belongs to, or a `manage_channels` helper). `is_game_participant` is a fact, not a gate. The permission is read with `is True`, never truthiness -- a Mock is truthy and turns every gate into a no-op silently. -- [permissions.md](docs/design/permissions.md)

**Rendering** -- [board-image.md](docs/design/board-image.md)
- **Look at the image.** The suite only checks a PNG of the expected size. `scripts/render_sample.py` renders boards; `--game <id>` reproduces a real one.
- **A refactor of drawing code is verified by SHA-256**, every image it feeds, both tiers and all three board sizes, byte-identical before and after.
- Fonts are bundled and loaded by absolute path; never look them up by bare name. `render.py` resolves fonts at **import**, so restart the bot after any render change.
- **`TEAM_COLORS` in `render.py` is the only hex for a team**; species teams inherit through `TEAM_PAIRS`. Name a team with `team_display_name`, never `.value.title()`. -- [teams-and-players.md](docs/design/teams-and-players.md)
- A bundled file's name is case-sensitive on Linux and not on macOS; the loaders swallow a miss silently, and the test compares against the directory listing.
- Anything drawing a species icon asks `render.species_icon`; never paste the loader's answer straight.

**Naming and wording** -- [naming-and-wording.md](docs/design/naming-and-wording.md)
- **A player is never named without their role.** `player_with_role` in a button or autocomplete (plain `Hellguard [FB]`), `D12Ball.player_label` / `player_id_label` in a message (team emoji in front, role badge where uploaded). The brackets are the only spelling; a button label is cut to 80 characters.
- Say what the position is, never what it is not; don't answer a question nobody asked; a move that costs nothing says nothing (`describe_exhaustion_gain` returns `""`, so callers join on `filter(None, ...)`).

**Tests** -- [testing.md](docs/design/testing.md)
- **A test names a player by role** (`tests/roster.py`: `fielded`, `benched`, `roles`), never by id or name -- the roster is data the author revises.
- **Suppress saves through `tests/save_patches.py`** (`suppressed_cog_saves` *and* `suppressed_view_saves`; a view usually needs both). A patch on a package name reaches none of its submodules. A full run must not create `data/`.
- `EveryMatchupResolvesTests` and `TutorialPlaythroughTests` drive the real cog; a recorder or a flow change is tested there, not only in a unit test.
- **`tests/test_model_purity.py` ratchets `d12ball/` and `gamesaves/d12ball/` importing no `discord` and defining no `async def`; `tests/test_golden_transcript.py` pins the tutorial's narration byte for byte.** Both are the safety net under the model/Discord split. -- [model-discord-split.md](docs/design/model-discord-split.md)

**Git and collaboration** -- [collaboration.md](docs/design/collaboration.md)
- **Never force-push a branch that has been pushed.** Feature branches are short-lived and land on `main` by PR. Either developer may be running the bot from the working tree at any time.
- **The live bot is the Windows checkout at `K:\...\fool-bot`**; a traceback from a `K:\` path is it, and a fix on the Mac has not reached it until that checkout has pulled and restarted. `.env`, `data/` and saved games are per checkout. One bot per token.
- Don't commit one-off diagnostic scripts; `scripts/` is for tools run more than once.
- Verify git and environment behaviour before asserting it; before concluding "it works here but not there", establish what actually differs between the hosts.

## The model and the Discord layer

These are the rules the model/Discord split is made by, and the standard a
change under `d12ball/` or `cogs/d12ball/` is reviewed against. They were
written in [docs/model-discord-split.md](docs/model-discord-split.md) --
the worksheet the split is being built from -- and moved here when Phase 1
landed, because a settled rule has exactly one home. The worksheet keeps
what is still open: the phases, what deliberately does not move, and the
bot stop each phase ends on.

1. **The model may not import `discord`, and may not be `async`.** Both
   halves matter. No-discord is the obvious one; not-async is the one that
   gets given away quietly, because the first `await` in a model function
   is what drags an event loop, an interaction and a rate-limit bucket in
   behind it. A step that wants to be async wants to send something, and
   sending is the frontend's. The line is mechanical, so it is tested
   mechanically -- see
   [model-discord-split.md](docs/design/model-discord-split.md).
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
   model.** `pending_turn_view` used to claim this and to carry the
   ordering decisions in its comments; what it did not do was answer
   anywhere a web app could hear it. `pending_prompt(engine, game, match)`
   in `d12ball/prompts.py` is that same chain returning a `PendingPrompt`,
   and `D12Ball.view_for_prompt`, the mapping from kind to
   `discord.ui.View`, is the only thing left in `cogs/`.
   **A second copy of that chain is the failure mode** -- it is how a
   resume comes to offer a different prompt from the one a restart
   restores, and with two frontends it is how the web app and the bot come
   to disagree about whose turn it is.

4. **A flow step returns what happened. It does not send it.** `StepResult`
   carries the narration lines, whether the board moved, and the next
   prompt. The frontend decides what becomes a message, what becomes an
   edit, and what becomes a websocket frame.
   - **It lives in `d12ball/flow/`**, one module per group of steps, and
     `d12ball/flow/result.py` holds the three types. A step takes
     `(engine, match, ...)` and adds `game` only where it actually reads
     the record -- never an `interaction`. `D12Ball.dispatch_step_result`
     is the whole of the Discord side: redraw if `board_changed`, then
     ask or continue.
   - **`StepResult.next` has a second shape, `FollowOn`, and it is
     transitional.** Through Phases 2-5 the spine of a turn is still
     async and still in `cogs/`, so a lifted step ends by naming the step
     that has not moved -- a member of the closed `FollowOnStep` enum,
     with its arguments, turned into a call by one table in
     `D12Ball.follow_on_methods`. Closed rather than a callable or a
     method name, so **the enum is the record of what the cog still
     dispatches**: later phases add and remove members, and Phase 6 reads
     it rather than a pull request. It dies with that table when the
     driver runs follow-ons itself.
   - **The narration is the result's, never the follow-on's.** The cog
     joins the lines on a space and hands them to whatever comes next as
     its `lead_in`, which is why a resolved maneuver is still one message
     and one board refresh. How the lines go together is the frontend's
     (principle 8), so nothing in the model says.

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

9. **The driver persists; steps do not.** `self.persist(...)` was called at
   **95 sites** in `cogs/` when this was written -- the phases have been
   collapsing them a rank at a time since, so measure rather than quote it --
   and CLAUDE.md already records the class
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
     the driver. `D12Ball.apply_low_pass` is the shape, and the first one:
     call the step, `self.persist(game, match)`, dispatch. The transition
     is where the bug this principle fixes can be reintroduced, because
     the wrapper was not saving before -- it relied on the step doing it,
     so the line is added rather than moved. The count above did not
     change when Low Pass moved for exactly that reason: one persist left
     the step and one arrived in the wrapper.
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

## Read this before touching...

| Before touching | Read | What it settles |
| --- | --- | --- |
| Anything that models the game; the import scripts; `players.json`, `maneuvers.json`, `species.json`; `rules_doc.py` | [rules-and-data.md](docs/design/rules-and-data.md) | Where the rules live upstream, the two-column abilities, the formula-escape quirk, how `/d12ball rules_*` serve the living rules |
| Formations, the deal, `placement_spaces_in_zone`, stacking, board 6 | [formations-and-occupancy.md](docs/design/formations-and-occupancy.md) | Shapes are data per board; occupancy is coverage, not a limit; who re-deals |
| Setup, halftime, full time, the coaching window, substitutions, `CoachingOccasion`, the kickoff-space hold | [coaching-choice.md](docs/design/coaching-choice.md) | Five occasions on one flow and one message; four substitution budgets; what survives on the match |
| Challengers, walk-ins, `contest_candidates`, declining a challenge, the uncontested maneuver | [sending-a-player.md](docs/design/sending-a-player.md) | Distance is the measure; two candidates and ties; a count not a flag |
| `ManeuverActionPromptView`, `send_field_prompt`, any prompt that asks a distance | [maneuver-prompt.md](docs/design/maneuver-prompt.md) | Why the prompt is public and never edited; the field strip under six prompts |
| Maneuver keys, gambits and who may play one, `maneuver_tiers`, `resolving_maneuver`, `gambit_cost`, `settled_maneuver_winner`, injury tests, own goals | [maneuvers.md](docs/design/maneuvers.md) | Rank decides; a gambit needs a reason; benefit and cost are two questions; every roll is a coach's and what outlives the wait |
| Volatile, Lithium Powered, Slimey, Mind Pull, Smooth, `check_for_ball_arrival`, `ignite`, `exhaustion_threshold`, Overdrive, `set_ball_space` / `restart_ball_at` | [species-abilities.md](docs/design/species-abilities.md) | One switch, two modules; the roll funnel and the ignition die; the arrival gate, and which of its two halves spends the path |
| The clock, `advance_time`, `GoalRecord`, `events`, `stats.py` | [clock-and-records.md](docs/design/clock-and-records.md) | The clock never stops; the goal log; what the statistics are and are not |
| `end_period`, the shootout, its two ephemeral menus | [shootout.md](docs/design/shootout.md) | Every game is settled; `advance_shootout` is the one reading; the secret orders |
| `can_attempt_score`, `ShotDefender`, the High Pass distances and overshoot | [shooting.md](docs/design/shooting.md) | Range is not a zone; halving is per defender; the passer never receives their own pass |
| `begin_loose_ball`, `contest_noun`, anything announcing where the ball landed | [loose-balls.md](docs/design/loose-balls.md) | What is standing on the space decides; only an empty space is loose; the High Pass exemption |
| `ball_carrier_id`, `begin_run_back`, `new_play`, `assigned_positions`, `continue_run_back` | [possession-and-turnovers.md](docs/design/possession-and-turnovers.md) | Steal vs new play; the run-back exemption is the carry; who runs back is two questions |
| `may_call_time_out`, `pending_time_out`, `finish_time_out` | [time-out.md](docs/design/time-out.md) | Not a turnover; charged not asked; the free pickup |
| `d12ball/tutorial.py`, any rail, `stage_tutorial_beat`, `post_tutorial_note` | [tutorial.md](docs/design/tutorial.md) | Five real turns from the standard deal; nothing moves a meeple between beats; the Continue gate |
| Adding a method to the cog, moving one between mixins | [cog-structure.md](docs/design/cog-structure.md) | Why mixins, why the order carries nothing, why `commands.GroupCog` is last |
| `botlog/`, log levels, the deploy notice, `FOOLBOT_LOG_*` | [logging.md](docs/design/logging.md) | Opt-in mirror per bot; what level means; reconnects are weather until they are not |
| `BoardRefresher`, `refresh_match_image`, any `channel.send`/edit/pin in a flow, `setup_hook`'s sync | [rate-limits.md](docs/design/rate-limits.md) | The measured invariants of the board gate, and every 429 batch that set them |
| `render.py`, meeples, the matchup image, `render_field_image`, fonts | [board-image.md](docs/design/board-image.md) | Three board images and which is whose; the 76px meeple; the hash-verified refactor |
| `cards.py`, `player_cards.py`, `species_cards.py`, the species icons, hand images | [cards.md](docs/design/cards.md) | One layout for print and Discord; what the sheet can't carry (`EXTRA_ROLES`, `EXTRA_NOTES`); the icon as one flat ink |
| `boards.py`, the print sheets, end zones, zone rows | [printed-boards.md](docs/design/printed-boards.md) | Tabloid, the token silos, no die values, why the field board is portrait |
| `Team`, `TEAM_COLORS`, `TEAM_PAIRS`, player ids, `team_for_player`, `duplicate_card_id`, `species` | [teams-and-players.md](docs/design/teams-and-players.md) | Eight teams on two axes; a player fielded on both sides as two cards; the emoji PNGs |
| Channel names, archiving, `/debug export_archived_games` | [channels-and-archive.md](docs/design/channels-and-archive.md) | The number after the prefix; export before delete; the permission gate rides on the group |
| `setup_hub`, `LobbyView`, `HUB_ROLES`, the d12 emoji | [hub-and-lobby.md](docs/design/hub-and-lobby.md) | Two hub messages; a lobby is a `SETUP` game with nothing decided; what Start Game finalises |
| Any gate on a button or command; `HelperConfirmationView` | [permissions.md](docs/design/permissions.md) | A coach first, then a helper; a helper holds no side; the confirmation is an exception |
| `/d12ball resume`, `abandon_game`, `restore_shootout_menus`, `on_ready` re-arming | [recovery.md](docs/design/recovery.md) | What a restart strands and why; states handed back to the routine that drives them |
| `to_dict`/`from_dict`, `storage.py`, the startup sweep, the full-image link, bundled file names | [gotchas.md](docs/design/gotchas.md) | Every fallback and why it stays; the swallowed save; the case-sensitive name |
| Writing or moving a test; patching `save_games` | [testing.md](docs/design/testing.md) | The package-split patch trap; the stray-save guard; naming by role |
| Deploying, the `K:\` host, `update_main_bot.ps1`, a 10062 | [collaboration.md](docs/design/collaboration.md) | Two machines, one live bot; one bot per token |
| `d12ball/prompts.py`, `pending_turn_view`, `view_for_prompt`, `tests/prompt_fixtures.py`; `d12ball/flow/`, `StepResult`, `FollowOn`, `dispatch_step_result`, `tests/low_pass_fixtures.py`, `tests/dribble_fixtures.py`; `tests/test_model_purity.py`, `tests/test_golden_transcript.py`, `tests/golden/`, anything that could add a `discord` import or `async def` under `d12ball/` or `gamesaves/d12ball/` | [model-discord-split.md](docs/design/model-discord-split.md) | Why the chain moved whole and what a prompt may carry; one kind per view class; the purity ratchet and why it runs in a subprocess; the golden transcript's seeded RNG and what it does not cover; the Python-version and root-test gotchas |

## Notes for Claude

- **Keep the map and the design docs current with the code.** When a change
  alters the architecture or a decision -- a new module, a responsibility
  moving, a new persisted field, a new environment variable, a rule the code
  now enforces differently -- update the topic's file in `docs/design/` in the
  same commit, with the reasoning and not just the fact; add a row here only
  for a new topic or a new hard rule. A code comment pointing at a section
  names the design file, not this one. Leave both alone for ordinary changes
  that fit the structure already described.
- **Read the design doc for the area before editing it**, and only that one.
  Each is five to fifteen minutes of context; all of them is the whole budget.
- **Use an Explore subagent for any wide search** -- sweeping many files, a
  naming convention, "where is X read", anything that would take more than
  two or three greps. Every Bash result lands in the main context permanently
  (one session made 4,074 Bash calls); a subagent's search stays in its own
  window and returns only the conclusion. Search directly only for a single
  lookup where the file or symbol is already known.

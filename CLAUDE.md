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
python3 -m webapp                   # the web app: its own process and games, no token
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
| `cogs/d12ball/` | **The Discord frontend** over `d12ball/flow/`: every slash command, and the rendering of what the driver hands back, as six mixins assembled into `D12Ball` in `__init__.py`: `core` (lifecycle, lookups, the `service` property, `DiscordBatching`, `present` -- the one presenter over a `GameResult`, and `post_group` under it -- `render_prompt` and `view_for_prompt`, the entry points into a turn's front half), `effects` (entry points into each maneuver's effect, and the two dice images that go between a roll's lines), `turnovers` (entry points into the run back, the time out and the pickup, the coaching image, resume), `periods` (entry points into the clock's tail, halftime and the shootout, the final board), `presentation` (the board, the field strip, the challenge and shot images, the ignition die, channels), `slash_commands` (every command, the three subgroups, the startup sweep). Nothing in it decides a rule; an entry point calls one step, or names one, and dispatches. `from cogs.d12ball import D12Ball` is unchanged -- [cog-structure.md](docs/design/cog-structure.md) |
| `cogs/d12ball_helpers.py` | Constants and free functions shared by the cog and its views -- emoji lookups, player/team formatting, channel naming, the authorization predicates, and **`DiscordTokens`**, the one resolver that draws the model's tokens for Discord (the emoji fallbacks live beside it). Re-exports everything `d12ball/formatting.py` holds; what stays here fetches emoji or touches discord.py itself |
| `cogs/d12ball_views/` | The `discord.ui.View` classes, one per prompt a player can be shown, in ten modules (`base`, `setup`, `turn`, `rolls`, `runback`, `effects`, `coaching`, `halftime`, `loose_ball`, `shootout`). `__init__.py` re-exports every name. `base` holds `SafeView` (`load_match`/`require_match`, the `may_act_for*` gates, and `apply` -- the one call a click makes, through `GameService`) and imports from no sibling, which keeps the package a DAG. `setup` and `lobby` change the record through the service's setup methods and show what it refuses; no view saves |
| `cogs/d12ball_boards.py` | The write gate on a game's persistent board message: `BoardRefresher` and one `BoardRefreshState` per game. `D12Ball.refresh_match_image` is the one forwarder over it -- [rate-limits.md](docs/design/rate-limits.md) |
| `cogs/debug.py` | Maintenance commands: the PBD channel-and-count reset, the archive export |
| `d12ball/components.py` | Game state model -- `MatchState`, `BoardState`, `TeamSetup`, `PlayerCatalog`, `MATCH_SAVED_FIELDS`; re-exports `RuleRefusal`, the one exception the position refuses a choice with (defined in `game.py`, the leaf, since the record refuses too) |
| `d12ball/engine.py` | `RulesEngine` -- every decision and candidate list that never touches Discord, over the fixed catalogs and AI strategies, and **`rng`, the one `random.Random` every draw the game makes comes from** (the AI strategies draw from it too). `D12Ball.engine` is the one instance; call sites read `self.engine.foo(...)`. Includes the prompt-text builders that need only the match and the catalogs; imports nothing from `render.py` |
| `d12ball/prompts.py` | `PromptKind`, `PendingPrompt`, `Action` and `pending` -- the one reading of what a match is waiting on, with no Discord in it, from a tutorial note held behind Continue to a finished game's rematch: a `PendingPrompt` where somebody is asked, a `FollowOn` where the bot owes the next step. `pending_prompt` and `owed_step` are the two readers over it, one each, and `asked_sides` the third: whose question a prompt is (nobody's for a roll). **A prompt carries its `options`** -- what may be chosen, a dataclass per kind built once by the `OPTIONS` table, the rails included -- and a view, the adapter, the AI and the full-game policy all read that one list. The cog maps a kind to a view and renders the `ask` with the picture that kind carries; the service runs the owed step and answers for the AI -- [model-discord-split.md](docs/design/model-discord-split.md), [game-service.md](docs/design/game-service.md) |
| `d12ball/ai.py` | `AIStrategy` and `DinkyAI`: the AI opponent answers the same `PendingPrompt` a coach is asked, `choose(prompt, game, match, side) -> Action`, reading the prompt's `options` and never a roll. `driver.ai_action` asks it; `GameService.run` puts the answer through `driver.answer` like a click -- [game-service.md](docs/design/game-service.md) |
| `d12ball/flow/` | **The whole of a turn, with no Discord in it**, ten modules: `result.py` (`StepResult` and `FollowOn`, the step the driver runs next), `effects.py` (**all twelve maneuvers** -- what each does when it wins, and `offer_*`, whether anybody is asked and what -- and the own-goal roll), `arrivals.py` (the two arrival gates and the five arrival points they guard, which moved together because the ordering between them is a rule), `turnovers.py` (the run back and its cascade, and the out-of-bounds pickup), `turn.py` (the front half: the turn's start, an AI side's whole turn, the challenger, the picks, which card won, the skill test's reveal), `injuries.py` (the injury-test queue and the three arrivals it drains into), `periods.py` (the whistle, halftime, the window before the shootout, the shootout and the game's end), `windows.py` (the Coaching Choice on all five occasions, and the time out that buys one), `rolls.py` (**the four contested rolls**, each handing back its numbers beside its sentences, because the picture goes between two of the lines), `gates.py` (the tutorial's Continue gates, as a prompt) and `driver.py` (**the loop and the answers**: `MODEL_STEPS` runs every `FollowOnStep`, `advance` runs a chain until a prompt or a stop the frontend asked for, and `answer`/`apply` take an action, refuse it while the bot owes a step, check it against `pending_prompt` and the position, and run it -- the one door every click and every web-app request goes through). A step changes the match and says what happened; it sends nothing and saves nothing -- [model-discord-split.md](docs/design/model-discord-split.md) |
| `d12ball/space_numbering.py` | **A temporary experiment**: the one switch that renames the board's spaces from `H1`/`M2`/`V1` to a flat `1`-`7` counted from the home end. `formatting.space_label` and `render.space_code` both ask it, which is why each takes the board -- a flat number has to count the zones to its left. **Nothing in it is a rule**, and the living rules still say `H1`. Set `FLAT_SPACE_NUMBERING = False` to turn it off -- [SPACE-NUMBERING-EXPERIMENT.md](docs/SPACE-NUMBERING-EXPERIMENT.md) is what to reverse to remove it |
| `d12ball/formatting.py` | Plain-text formatting over match/game/zone data with no Discord dependency -- space codes, side labels, player names, a coach's name off the record |
| `d12ball/tokens.py` | **The marks narration leaves for a frontend to draw**: `{team:purple}`, `{role:fullback:orange}`, `{condition:exhaust}`, `{species:cyborg}`, `{coach:1}` -- five builders, the only way a token is written, and `render(text, resolve)`, the only way one is read. The cog renders once at its door (`D12Ball.rendered` / `render_text`); a web app renders its own way -- [model-discord-split.md](docs/design/model-discord-split.md), "Tokens" |
| `d12ball/wire.py` | **How the model's own values are written down for a frontend that talks over a wire**: `jsonable`, the one conversion, and the `to_dict` on everything a `GameResult` carries. One-way -- `Action.from_dict` is the only reader -- and not a save; the save format is `MatchState.to_dict`'s -- [web-app.md](docs/design/web-app.md) |
| `d12ball/game.py` | `D12BallGame` (the game record -- its three Discord ids optional, since a web game has none -- with every rule about the lobby and setup as a method that refuses with `RuleRefusal`: `lobby_join`/`observe`/`leave`, a web room's seat moves (`take_seat`, `vacate_seat`, `seat_ai`, `unseat_ai`, over `ai_seats` and its one reading `ai_holds`), `configure` over `GAME_SETTINGS` and `open_settings`, `start_lobby`, `pick_team` over `excluded_teams` and `teams_open_to` -- the one reading a team picker offers from, on either frontend -- the coin and the sides, and `coin_is_owed` / `home_choice_owed_by`), `RuleRefusal`, `Team`, `TEAM_PAIRS`, `GameMode` (training, basic, advanced), `Formation` |
| `d12ball/render.py` | Board, matchup and dice image rendering (Pillow); `TEAM_COLORS` |
| `d12ball/dice_brief.py` | The rendering briefs over the model's values, below `render.py` so both frontends draw the same picture: `render_contest_dice` (a `ContestDice`'s sides as the skill-test dice), `challenge_side` (a player as the challenge and shot images draw them), and `maneuver_challenge_brief` / `score_attempt_brief` (the whole of each matchup image: its sides and its caption). All were the cog's -- [web-app.md](docs/design/web-app.md), "The dice" |
| `d12ball/cards.py` | The twelve maneuvers as cards -- the printed face, the shared back, the hand the bot shows |
| `d12ball/player_cards.py` | The roster as cards, over `cards.py`: printed, and posted by `/d12ball team_reference` in the face the game's mode plays |
| `d12ball/personal_abilities.py` | **The personal abilities (Law 21)**: `PersonalAbility`, and `PERSONAL_ABILITIES` -- the one table tying a catalog id to an ability, with the sheet sentence each row was built from (a test holds the two together) -- and every number the abilities change. `RulesEngine.has_personal_ability` and `skills` are the questions over it -- [species-abilities.md](docs/design/species-abilities.md) |
| `d12ball/species_cards.py` | The four species abilities as a three-card reference set: printed, and posted by `/d12ball species_abilities_reference` in the dark palette (`DARK_REFERENCE` in `cards.py`) |
| `d12ball/role_cards.py` | The six basic role abilities as a one-card reference set: printed, and posted by `/d12ball role_abilities_reference` in the dark palette (`DARK_REFERENCE` in `cards.py`) |
| `d12ball/boards.py` | The field, jumbotron and team boards, print-ready for the tabletop game. **Only the field board is tabloid**; the jumbotron is a letter sheet landscape, and the team board half a letter one. The field board comes out three ways: the tabloid sheet, and its own two letter halves, which taped along the cut are that same board. The team board comes out twice: one board, and a letter page carrying two |
| `d12ball/box_art.py` | The printed things around the game rather than in it: the box cover, one side (the box is square), the one-page sale sheet -- which is the box's underside for now -- and the playtest card whose back carries the survey QR, all on white, because a dark cover is a press run nobody wants to pay for; plus a night cover and banners (a wide one and the Screentop table's 1280x720) for screens. Every claim on them is read from the game and every quoted rule is the books' own, word for word; the picture of the game is the printed board with the Screentop table's own meeples on it, and the ball is a d12 drawn as a solid made of something. `scripts/render_box_art.py` is its CLI -- [box-and-sale-sheet.md](docs/design/box-and-sale-sheet.md) |
| `scripts/render_token_models.py` | The three condition tokens as 3D-printable, double-sided models, traced from the bot's own token art: one-piece multi-material 3MFs and single-filament halves -- [printed-tokens.md](docs/design/printed-tokens.md) |
| `d12ball/rulebooks.py` | The two rulebooks as PDFs: the markdown subset, the Charter's build-time numbering, the reportlab layout. `scripts/build_rulebooks.py` is its CLI -- [rulebooks.md](docs/design/rulebooks.md) |
| `d12ball/rulebook_figures.py` | The Learn to Play's illustrations, as real match states rendered by `render.py` and annotated; written to `docs/rulebooks/figures/` by `--figures` |
| `d12ball/rules_doc.py` | Reads `docs/living-rules.md` for the two rules commands |
| `d12ball/stats.py` | Every statistic `/d12ball stats` reports, as a fold over `MatchState.events`, and which tables each report holds -- the web page's `/stats` posts the same ones. No Discord and no game flow |
| `d12ball/tutorial.py` | The scripted opening a tutorial game plays -- the five beats as data, and the rails |
| `d12ball/data/` | `players.json`, `basic_rules.json`, `maneuvers.json`, `species.json` -- regenerated whole by the import scripts, never edited by hand |
| `d12ball/images/` | Card art, emoji, the four species icons (ink and coloured) |
| `d12ball/fonts/` | Bundled DejaVu and Racing Sans One, loaded by absolute path |
| `gamesaves/d12ball/service.py` | **`GameService`**, the one door for a change to a game (ARCHITECTURE.md, part 2): `apply_action`, `begin`, `resume`, `run_step`, each load-apply-save-once-return, and `GameResult`, what a frontend renders. `run` answers for an AI side wherever the loop reaches its question, batched by the frontend's `Batching.carry_answer`. The setup methods that need no turn -- `create_game`, the lobby moves, `configure`, `pick_team`, `flip_coin`, `choose_home_or_visiting`, `rematch` after the game, and `abandon` -- are each a thin door over a rule on `D12BallGame` -- [game-service.md](docs/design/game-service.md) |
| `gamesaves/d12ball/storage.py` | Persistence to `data/d12ball_games.json` -- or the file named: `load_games`/`save_games` take a `path`, and the web app names `WEB_GAMES_FILE`, `data/d12ball_web_games.json`, in the same format -- and the legacy-save migrations. The two failure flags are per file -- [gotchas.md](docs/design/gotchas.md) |
| `gamesaves/d12ball/archive_export.py` | Writing one finished game's export to disk for `/debug export_archived_games` |
| `gamesaves/d12ball/hub.py` | The per-guild hub message pointers, in `data/d12ball_hubs.json` |
| `webapp/` | **The web frontend, a system of its own**: `python3 -m webapp` runs it as its own process, with no token, over its own games (`data/d12ball_web_games.json`) and its own `GameService`, engine and locks, built from the same model the cog's are (`server.build_service`). It shares the model with the bot and nothing at runtime; no game is on both. `server.py` (the aiohttp app, the routes, `main`), `journal.py` (what has been said in each game, as the log reads it, in `data/d12ball_web_journal.json` so it survives a restart, never the save), `present.py` (the tokens as the bot's own emoji, `PROMPT_PICTURES` -- the matchup a question is asked over, by kind -- and one control builder per `PromptKind`, off `PendingPrompt.options` as `to_dict` writes them and nothing else, each control in Discord's colour for it -- `GAME_OVER`'s the rematch, the one control that posts to a room route rather than answering the match), `board.py` (the position as a layout the page draws in the bot's board layout, every value the PNG asks the rules for asked of the same function), `pictures.py` (the model's own card faces, maneuver cards, dice, prompt pictures and emoji, served -- a roll's dice picked by its detail's shape, a prompt's picture -- the shot, the challenge -- by its kind through `present.PROMPT_PICTURES`), `identity.py` (who is reading: a name and an id in a signed cookie, stored nowhere), `rooms.py` (the web app's own state per room -- admins and who has been in -- in `data/d12ball_web_rooms.json`, never the save), `chat.py` (what the people in a room have said, under their cookie's names, bounded per room, in `data/d12ball_web_chat.json`, never the save), `keys.py` (the one secret the cookie is signed under), `aids.py` (the reading room: the rules as `rules_doc`'s sections headed with the Charter's build-time numbers, the two rulebooks as PDFs set in memory, and the reference commands' pictures, which of them a room gets the engine's answer) and `static/` (the front door -- my rooms, open rooms, a room or the AI -- the web games' numbers, and one page: the board and the prompt, or before kickoff the room's table, beside the jumbotron, the game log and the chat, in Discord's colours -- and the Rules & aids panel over both, `aids.js`). The chat is people talking, never the model's voice, and goes nowhere near the service. It imports neither `discord` nor `cogs`, nothing in the bot imports it, and it never names the bot's games file -- [web-app.md](docs/design/web-app.md) |
| `gamelocks.py` | One `asyncio.Lock` per game, and one `GameLocks` per process (the bot's and the web app's each their own): held around a click's whole answer, the apply *and* what it puts up -- [web-app.md](docs/design/web-app.md) |
| `scripts/` | CLI tools used repeatedly (not one-off scratch work) |
| `tests/roster.py`, `tests/save_patches.py`, `tests/flow_stubs.py`, `tests/ai_answers.py` | Naming a test's player by role; suppressing saves; stubbing a step on whichever side of the seam runs it; asking the AI a question the way the service does -- [testing.md](docs/design/testing.md) |
| `docs/living-rules.md` | **The D12Ball Charter: Laws of the Game -- the whole ruleset as it currently stands.** The one thing to check a mechanic against. Twenty-one Laws in two Parts; the printed edition numbers every paragraph at build time (`scripts/build_rulebooks.py charter`) -- [rulebooks.md](docs/design/rulebooks.md) |
| `docs/learn-to-play.md` | The illustrated Learn to Play: basic mode in sixteen-odd pages, every rule citing its Law. Not a copy of the rules -- a lesson that cites them |
| `docs/rules-log.md` | Every rules change, dated and sourced; what is still open; where upstream is behind |
| `docs/gambit-matrix.md` | The worksheet the gambits were built from, cut to what is still open. **Nothing in it is a rule** |
| `docs/tts-module.md` | The worksheet the Tabletop Simulator module is being built from -- the four decisions already taken, the five phases and the in-TTS stop each ends on, what the convenience scripts may and may not do. **Nothing in it is a rule** |
| `docs/web-app.md` | The worksheet the web app is being built from -- the split reviewed against a second frontend (sixteen findings, three reproduced through `driver.answer`, each marked with where it stands on the migration), the nine decisions taken in its review, and what each migration step owes the web app that `docs/architecture-migration.md` does not spell out. **Nothing in it is a rule** |
| `docs/web-app-next.md` | The worksheet the web app's next steps are being done from, under the author's decision of 2026-09-25 that **the web app and the bot are two parallel systems sharing the model and nothing at runtime** -- no mixed games, its own process, its own games file. What that changes in the shipped design and what it costs, why it still stays in this repository, the decisions taken in its review (rooms whose first two arrivals are the coaches and the rest observers, a seat that may change hands mid-game and an admin who may kick one, the `K:\` machine, the wire tree kept), eleven steps in the order they pay off with a Claude Code prompt per step -- including a chat in the room, the web games' statistics read on Discord (the one read across the line), and the rulebooks and player aids on the page -- and what is deliberately not on the list. **Nothing in it is a rule** |
| `docs/rulebooks/` | The worksheet the two rulebooks are built from -- the plan, the Charter and Learn to Play outlines, and the committed figure sketches. **Nothing in it is a rule** |
| `ARCHITECTURE.md` | **The target architecture**: four parts (model, `GameService`, Discord frontend, web frontend), the shared `GameResult`, what to remove and the migration order. A change under `d12ball/`, `gamesaves/d12ball/` or `cogs/` is reviewed against it |
| `docs/architecture-migration.md` | The worksheet the migration to `ARCHITECTURE.md` is being done from -- what did not conform on 2026-09-21, and the ten steps in order. **Nothing in it is a rule** |
| `docs/design/` | The design notes this file points at -- one topic per file |

## Hard rules

These hold everywhere. Each has its reasoning in the design doc named beside it.

**Rules and data**
- **Read [docs/living-rules.md](docs/living-rules.md) before changing anything that models the game.** Several mechanics exist only in the code, so a bug and a deliberate decision look identical there; take rules questions to the author (inline comments on a docs PR have worked far better than chat) rather than inferring them. A rules change is the living rules plus a dated `docs/rules-log.md` entry, as its own commit. -- [rules-and-data.md](docs/design/rules-and-data.md)
- **Don't guess a sheet gid; run the import scripts.** `gid=0` is a stale tab that still answers. Every ability comes in twice (`ability`, `ability_short`) from the sheet's own columns -- **never shorten an ability in code**, and `strip_formula_escape` runs on every ability column.
- **The only row order that matters is the `player cards` tab's**: it is each team's roster order, and the standard deal starts the first of each role, so re-sorting that tab changes who starts. Every other tab's order means nothing -- the `advanced_abilities` tab is read by `player_id` -- so ignore a re-sort there, and never sort the roster in the importer. -- [rules-and-data.md](docs/design/rules-and-data.md)
- The rules commands read `docs/living-rules.md` itself; there is no second copy of the rules text anywhere in the bot.

**State and saves** -- [gotchas.md](docs/design/gotchas.md)
- **The match is saved by `GameService` and nothing else.** A click goes through `GameService.apply_action`, the bot's own steps through `run`, and each writes the match once before it returns; no view and no presenter saves a match (ARCHITECTURE.md, "Persistence"). An admin command that edits the position by hand writes through `service.persist`, never `to_dict` + `save_games`. `save_games` alone is only for a change to the game record -- and a change to the record before kickoff (a seat taken, a setting, a team, the coin) is a setup method on the service, which saves it; `cogs/d12ball_views` binds `save_games` nowhere. -- [game-service.md](docs/design/game-service.md)
- **A new `MatchState` field goes in `MATCH_SAVED_FIELDS`** (or `MATCH_EXPLICIT_FIELDS` when it needs its own handling); the suite fails until it does. The wire format is not the table's to change.
- **Legacy fallbacks stay** (`player_board`, `tie_mode`, `ceded`, `legacy_maneuver_key`, the reshuffle migration, the `shootout_test` resume kind, ...) until no half-finished game can predate them. Both developers run the bot against their own saves. Don't add migration passes; don't rename saved keys.
- `data/` is untracked runtime state, per checkout. Never commit it. `save_games` never raises and a save failure never fails the turn.
- **`d12ball/prompts.py`'s `pending` is the only reading of "what is this match waiting on?"**, and `pending_prompt` (asked) and `owed_step` (owed) are its two readers -- exactly one answers for any position. `pending_turn_view` is the Discord mapping over the first, and `view_for_prompt` the only place a `PromptKind` becomes a view; `GameService.resume` runs the second, and `driver.answer` refuses every action while it answers. A second copy of that chain is how a resume comes to offer a different prompt from the one a restart restores. -- [recovery.md](docs/design/recovery.md)
- **A view builds its buttons from `PendingPrompt.options` and nothing else, and an adapter refuses against the same list.** A candidate list, a distance, a hand, a rail computed in a view is a second reading the driver cannot see; if a prompt needs something it does not carry, its options grow a field in `d12ball/prompts.py` and both sides read it. **The position refuses with `RuleRefusal`**, never a bare `ValueError`: that is the one exception `driver.answer` turns into a `Refusal`, and anything else out of a step is a bug. -- [model-discord-split.md](docs/design/model-discord-split.md)
- `MatchState.record_goal` and `record_event` are the only writers of the goal log and the event log; nothing in the game may read the event log to decide a rule. -- [clock-and-records.md](docs/design/clock-and-records.md)
- **Maneuvers are keyed** (`low_pass`, `double_team`), never held or compared by display name; `RulesEngine.maneuver_name` is the only way back to a name, for wording alone. -- [maneuvers.md](docs/design/maneuvers.md)
- **`RulesEngine.maneuver_tiers` is the only answer to which cards a coach may play, and it is asked per side.** A gambit is held only by a coach whose team is behind (`may_play_gambits`), so the two hands on one prompt can be six cards and three -- the buttons, the hand image and the click that answers all ask it, once each per side. -- [maneuvers.md](docs/design/maneuvers.md)
- **Nothing reads `game.advanced_maneuvers`, `game.species_abilities`, `PlayerDefinition.species`, `advanced_ability` or `advanced_skills` to decide a rule, and nothing keys a rule on a player id.** `RulesEngine.gambits_apply`, `species_abilities_apply`, `has_species_ability`, `has_personal_ability` and `skills` are the answers. -- [species-abilities.md](docs/design/species-abilities.md)

**Discord**
- **Rate limits: the fix is always fewer requests, never slower ones.** Every edit to any message in a channel shares one ~five-in-five-seconds bucket; only the board message may be edited through the channel; `BOARD_REFRESH_INTERVAL` stays above five seconds; a cascade of the bot's own steps is one message and one board refresh at the end; render once, upload twice (`png=`); only `post_new_play_board` pins. **Read [rate-limits.md](docs/design/rate-limits.md) before adding any send, edit or pin to a game flow.**
- A new prompt or announcement sent after a click's own answer goes through `send_new_prompt`, or it renders as a reply to the wrong message.
- Every render goes through `asyncio.to_thread`. Pillow is CPU-bound and blocks the heartbeat.
- **Use `logging`, not `print`.** ERROR reaches #logs and means somebody must act; INFO/WARNING are console-only. The sink never logs its own failures. -- [logging.md](docs/design/logging.md)
- **Nothing rolls dice on its own.** Every roll waits behind a button either coach may press; a roll is nobody's question (`asked_sides`), so the AI answers choices and never dice. -- [maneuvers.md](docs/design/maneuvers.md)
- **Nothing in the model holds an emoji, builds a mention, or names a channel, a row or a message.** A sentence names a team, a badge, a condition, a species or the coach it addresses with a token from `d12ball/tokens.py`, and the cog renders every token once, at its door (`D12Ball.rendered` over a `GameResult`, `render_text` for a sentence it composes itself) -- never in a view. What a Discord layout needs said (which row is yours) is the cog's caption over the model's sentence, not a word in it. -- [model-discord-split.md](docs/design/model-discord-split.md), "Tokens"
- **Every draw the game makes is `engine.rng`**, and every d12 is rolled by `scripted_or_random(engine, ...)`; nothing in `d12ball/` reads the module `random`. A test seeds `engine.rng` and patches `random.Random.randint`. -- [testing.md](docs/design/testing.md)
- **Authorization is `SafeView.may_act_for` / `may_act_in_game`** (the coach a button belongs to, or a `manage_channels` helper). `game_participant_ids` is a fact, not a gate. The permission is read with `is True`, never truthiness -- a Mock is truthy and turns every gate into a no-op silently. -- [permissions.md](docs/design/permissions.md)

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
- **Nothing printed is tested** -- the box art, the printed boards, the printed player, role and species cards, the rulebooks and their figures (the author, 2026-09-23). A change there is checked by rendering it and looking; don't add a test for it.
- **Suppress saves through `tests/save_patches.py`** (`suppressed_cog_saves`, which reaches the cog mixins' record saves and the service's one match save; no view saves, so there is nothing else to patch). A patch on a package name reaches none of its submodules. A full run must not create `data/`.
- `EveryMatchupResolvesTests` and `TutorialPlaythroughTests` drive the real cog; a recorder or a flow change is tested there, not only in a unit test.
- **`tests/test_model_purity.py` ratchets `d12ball/` and `gamesaves/d12ball/` importing no `discord` and defining no `async def`, and the game importing without Pillow; the four goldens (`test_golden_transcript.py`, `test_golden_advanced.py`, `test_golden_windows.py`, and `test_golden_service.py`, the tutorial through `GameService` with its tokens intact) pin the tutorial, a free advanced game, a whole game through full time and the shootout, and the model's own voice, byte for byte; `tests/test_driver_full_game.py` plays a whole game and the tutorial through `driver.apply` with no frontend imported.** All six are the safety net under the model/Discord split, and the last two are what a web app inherits. The three cog goldens record what the bot *sends*, so a change to the rendering that is faithful leaves them alone. -- [model-discord-split.md](docs/design/model-discord-split.md)

**Git and collaboration** -- [collaboration.md](docs/design/collaboration.md)
- **Every task starts on a fresh branch off an up-to-date `main`** -- `git checkout main && git pull --ff-only && git checkout -b <topic>` before the first edit, never on `main` itself and never on the last task's branch, which may already be merged or still in review.
- **Never force-push a branch that has been pushed.** Feature branches are short-lived and land on `main` by PR. Either developer may be running the bot from the working tree at any time.
- **The live bot is the Windows checkout at `K:\...\fool-bot`**; a traceback from a `K:\` path is it, and a fix on the Mac has not reached it until that checkout has pulled and restarted. `.env`, `data/` and saved games are per checkout. One bot per token.
- Don't commit one-off diagnostic scripts; `scripts/` is for tools run more than once.
- Verify git and environment behaviour before asserting it; before concluding "it works here but not there", establish what actually differs between the hosts.

## The model and the Discord layer

These are the rules the model/Discord split is made by, and the standard a
change under `d12ball/` or `cogs/d12ball/` is reviewed against. They were
written in the worksheet the split was built from and moved here when
Phase 1 landed, because a settled rule has exactly one home; the worksheet
went with Phase 6, the last phase, and what it recorded that outlives it
is in [docs/design/model-discord-split.md](docs/design/model-discord-split.md).
**The split is done**: `d12ball/flow/driver.py` runs every step of a turn
and answers every prompt, the cog is a frontend over it, and
`tests/test_driver_full_game.py` plays a whole game with no frontend
imported. **The web app is done too**, and it is what the split was
for: `webapp/` plays the same game over HTTP with no `cogs` import,
and [docs/design/web-app.md](docs/design/web-app.md) is its design.
Since 2026-09-25 it is a separate system -- its own process and its
own games, sharing the model and nothing at runtime -- and
[docs/web-app-next.md](docs/web-app-next.md) is what is built next.
The review the split was held to is [docs/web-app.md](docs/web-app.md),
which the code still cites by finding number.

1. **The model may not import `discord`, and may not be `async`.** Both
   halves matter. No-discord is the obvious one; not-async is the one that
   gets given away quietly, because the first `await` in a model function
   is what drags an event loop, an interaction and a rate-limit bucket in
   behind it. A step that wants to be async wants to send something, and
   sending is the frontend's. The line is mechanical, so it is tested
   mechanically -- see
   [model-discord-split.md](docs/design/model-discord-split.md).
   - **Both halves hold**: `d12ball/` imports no `discord` and contains
     no `async def`. The guard is a ratchet on something true, and the
     reason it is cheap is the reason it is there -- a convenience at a
     time is how it would erode.

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
   anywhere a web app could hear it. `pending(engine, game, match)`
   in `d12ball/prompts.py` is that same chain, returning a `PendingPrompt`
   where somebody is asked and a `FollowOn` where the bot owes the next
   step -- `pending_prompt` and `owed_step` read one each -- and
   `D12Ball.view_for_prompt`, the mapping from kind to
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
     the record -- never an `interaction`. `GameService.run` runs the
     chain and saves once; `D12Ball.present` is the whole of the Discord
     side: redraw if the board moved, post what was said, put up what
     is asked -- [game-service.md](docs/design/game-service.md).
   - **`StepResult.next` has a second shape, `FollowOn`: the step the
     driver runs next.** A member of the closed `FollowOnStep` enum with
     its arguments, turned into a call by one table,
     `d12ball.flow.driver.MODEL_STEPS`, which covers the enum exactly. A
     step is *named* rather than called where the boundary is one a
     frontend has something to decide at -- a message of its own, a
     picture, a board to put up before anything else moves -- so the
     enum is the record of where one thing ends and the next begins.
     Closed rather than a callable, so nothing on either side can reach
     a step by spelling its name. (It was transitional through Phases
     2-5, when the cog ran the members that had not moved; that table
     is gone.)
   - **The narration is the result's, never the follow-on's.** The loop
     joins the lines on a space and hands them to whatever comes next as
     its `lead_in`, which is why a resolved maneuver is still one message
     and one board refresh. How the lines go together is the frontend's
     (principle 8), so nothing in the model says.
   - **Where one message ends and the next begins is `own_message`, and
     it is the frontend's.** `driver.advance` takes the set of steps
     whose lines must not carry forward and hands back a
     `NarrationGroup` per boundary, each tagged with the step that said
     it; the cog reads the tag and posts one message, or one per block
     (`DRIVER_OWN_MESSAGE`, `DRIVER_BLOCKS_PER_MESSAGE` in
     `cogs/d12ball/core.py`). The model reports only where one thing
     ends and the next begins, which is not a free choice -- joining two
     events into one paragraph would be the frontend rewording the
     position. A group may be empty: the challenge image rides on a
     walk-in that says nothing for a defender already on the ball.
   - **A picture is keyed on what it rides on.** A prompt's picture --
     the field strip, the hand of cards, the composition, the coach's
     half-field, the final board -- is `D12Ball.render_prompt`'s, keyed
     on the `PromptKind`. A picture of a *position* is a stop: the loop
     stops after a step the frontend names (`stop_after`: the loose
     ball's snapshot, the tail of a maneuver) and after any result that
     opens a new play (`StepResult.new_play`, the one flag beside
     `board_changed`, which the cog pins on), hands back `stopped_on`
     with the step's own result, and the frontend re-enters the loop
     once the picture is up. Nothing in the model knows that a pin is
     a pin.

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
   - **The save is the service's.** `GameService.run` runs the chain
     through every stop the frontend asked for and writes the match
     once, before it returns and so before anything is posted. A view
     renders only after `apply_action` has come back, which is why no
     view saves: the four rolls that used to save early by hand (a
     failed dice upload must not let the next click roll again) are
     covered by the same line as everything else. The run-back cascade
     saves this way too: one write after the whole cascade, before the
     prompt goes out. -- [game-service.md](docs/design/game-service.md)
   - **It does not touch the bare `save_games` calls.** Those save the
     *game record* alone -- a message id, a status, a tutorial flag --
     and have no match to write, so they stay exactly where they are.
     The number is not a constant and is not quoted here; count it
     before quoting it.

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
| Formations, the deal, `placement_spaces_in_zone`, stacking | [formations-and-occupancy.md](docs/design/formations-and-occupancy.md) | Shapes are data per board; occupancy is coverage, not a limit; who re-deals |
| Setup, halftime, full time, the coaching window, substitutions, `CoachingOccasion`, the kickoff-space hold | [coaching-choice.md](docs/design/coaching-choice.md) | Five occasions on one flow and one message; four substitution budgets; what survives on the match |
| Challengers, walk-ins, `contest_candidates`, declining a challenge, the uncontested maneuver | [sending-a-player.md](docs/design/sending-a-player.md) | Distance is the measure; two candidates and ties; a count not a flag |
| `ManeuverActionPromptView`, `send_field_prompt`, any prompt that asks a distance | [maneuver-prompt.md](docs/design/maneuver-prompt.md) | Why the prompt is public and never edited; the field strip under six prompts |
| Maneuver keys, gambits and who may play one, `maneuver_tiers`, `resolving_maneuver`, `gambit_cost`, `settled_maneuver_winner`, injury tests, own goals | [maneuvers.md](docs/design/maneuvers.md) | Rank decides; a gambit needs a reason; benefit and cost are two questions; every roll is a coach's and what outlives the wait |
| `GameMode`, `GAME_MODE_BUTTONS`, `gambits_apply`, `species_abilities_apply`, the personal abilities, `has_personal_ability`, `skills`, Boost, Volatile, Lithium Powered, Slimey, Mind Pull, Smooth, `check_for_ball_arrival`, `ignite`, `exhaustion_threshold`, Overdrive, `set_ball_space` / `restart_ball_at` | [species-abilities.md](docs/design/species-abilities.md) | Three modes, and why `basic` kept its saved value; the personal-ability table and the one skill reading; the roll funnel and the ignition die; the arrival gate, and which of its two halves spends the path |
| The clock, `advance_time`, `GoalRecord`, `events`, `stats.py` | [clock-and-records.md](docs/design/clock-and-records.md) | The clock never stops; the goal log; what the statistics are and are not |
| `end_period`, the shootout, its two ephemeral menus | [shootout.md](docs/design/shootout.md) | Every game is settled; `advance_shootout` is the one reading; the secret orders |
| `can_attempt_score`, `ShotDefender`, the High Pass distances and overshoot | [shooting.md](docs/design/shooting.md) | Range is not a zone; halving is per defender; the passer never receives their own pass |
| `begin_loose_ball`, `contest_noun`, anything announcing where the ball landed | [loose-balls.md](docs/design/loose-balls.md) | What is standing on the space decides; only an empty space is loose; the High Pass exemption |
| `ball_carrier_id`, `begin_run_back`, `new_play`, `assigned_positions`, `continue_run_back` | [possession-and-turnovers.md](docs/design/possession-and-turnovers.md) | Steal vs new play; the run-back exemption is the carry; who runs back is two questions |
| `may_call_time_out`, `pending_time_out`, `finish_time_out` | [time-out.md](docs/design/time-out.md) | Not a turnover; charged not asked; the free pickup |
| `d12ball/tutorial.py`, any rail, `begin_turn`, `d12ball/flow/gates.py`, `tutorial_gate` | [tutorial.md](docs/design/tutorial.md) | Five real turns from the standard deal; nothing moves a meeple between beats; the Continue gate is a prompt |
| Adding a method to the cog, moving one between mixins | [cog-structure.md](docs/design/cog-structure.md) | Why mixins, why the order carries nothing, why `commands.GroupCog` is last |
| `botlog/`, log levels, the deploy notice, `FOOLBOT_LOG_*` | [logging.md](docs/design/logging.md) | Opt-in mirror per bot; what level means; reconnects are weather until they are not |
| `BoardRefresher`, `refresh_match_image`, any `channel.send`/edit/pin in a flow, `setup_hook`'s sync | [rate-limits.md](docs/design/rate-limits.md) | The measured invariants of the board gate, and every 429 batch that set them |
| `render.py`, meeples, the matchup image, `render_field_image`, fonts | [board-image.md](docs/design/board-image.md) | Three board images and which is whose; the 76px meeple; the hash-verified refactor |
| `cards.py`, `player_cards.py`, `species_cards.py`, `role_cards.py`, the species icons, hand images, the three reference commands | [cards.md](docs/design/cards.md) | One layout for print and Discord; what the sheet can't carry (`EXTRA_ROLES`, `EXTRA_NOTES`); the icon as one flat ink; which card face a game posts |
| `boards.py`, the print sheets, the half sheets, end zones, zone rows | [printed-boards.md](docs/design/printed-boards.md) | Tabloid, the token silos, no die values, why the field board is portrait; why a half sheet is a cut of the finished board and never a second layout, and what the seam is allowed to cross; the jumbotron's own letter sheet, why the token supplies are a strip down its side and what the score track's length is traded for; the team board's own paper, its two files, and why it measures in inches |
| `Team`, `TEAM_COLORS`, `TEAM_PAIRS`, `excluded_teams`, `ai_team_pool`, player ids, `team_for_player`, `duplicate_card_id`, `species` | [teams-and-players.md](docs/design/teams-and-players.md) | Eight teams on two axes; a player fielded on both sides as two cards; the emoji PNGs |
| Channel names, archiving, `/debug export_archived_games` | [channels-and-archive.md](docs/design/channels-and-archive.md) | The number after the prefix; export before delete; the permission gate rides on the group |
| `setup_hub`, `LobbyView`, `HUB_ROLES`, the d12 emoji | [hub-and-lobby.md](docs/design/hub-and-lobby.md) | Two hub messages; a lobby is a `SETUP` game with nothing decided; what Start Game finalises |
| Any gate on a button or command; `HelperConfirmationView` | [permissions.md](docs/design/permissions.md) | A coach first, then a helper; a helper holds no side; the confirmation is an exception |
| `/d12ball resume`, `abandon_game`, `restore_shootout_menus`, `on_ready` re-arming | [recovery.md](docs/design/recovery.md) | What a restart strands and why; states handed back to the routine that drives them |
| `to_dict`/`from_dict`, `storage.py`, the startup sweep, the full-image link, bundled file names | [gotchas.md](docs/design/gotchas.md) | Every fallback and why it stays; the swallowed save; the case-sensitive name |
| Writing or moving a test; patching `save_games` | [testing.md](docs/design/testing.md) | The package-split patch trap; the stray-save guard; naming by role |
| Deploying, the `K:\` host, `update_main_bot.ps1`, `run_web_app.ps1`, a 10062 | [collaboration.md](docs/design/collaboration.md) | Two machines, one live bot; one bot per token; running the web app beside it -- the `.env`, HTTPS only, the tunnel |
| `d12ball/box_art.py`, `scripts/render_box_art.py`, the box panels, the sale sheet, the playtest card and its QR | [box-and-sale-sheet.md](docs/design/box-and-sale-sheet.md) | Why everything printed is white and what the night cover and the banners are for; the box cut from the folded field board; why the box may not word a rule for itself; why the playing time and the age are the author's and dated rather than worked out here, and the strapline the one line in the box's own voice; the printed board as the picture, the meeple read from the table's own path and the d12 that is a solid made of something; what a banner is, why it is not a cropped cover and why it is laid out in shares; why the sale sheet is components rather than prose, what its QR points at, and why it is the underside for now; the flat mark on the board against the solid on a cover; the cover's four and why their names are written down; the QR drawn module by module and its size floor |
| `scripts/render_token_models.py`, the 3D-printed tokens | [printed-tokens.md](docs/design/printed-tokens.md) | Which faces share a token and why; the art traced, not redrawn, and the three things the nozzle changes; 19 mm because of the silo; flush inlay against glued halves |
| `d12ball/rulebooks.py`, `d12ball/rulebook_figures.py`, `scripts/build_rulebooks.py`, anything in `docs/rulebooks/` | [rulebooks.md](docs/design/rulebooks.md) | The Charter is the living rules renumbered, not a copy; numbering at build time; the figures are the renderer's; the markdown subset that fails the build rather than printing wrong |
| `gamesaves/d12ball/service.py`, `GameService`, `GameResult`, `Narration`, `Batching`, `carry_from`; `DiscordBatching`, `D12Ball.present`, `post_group`, `dispatch_step_result`, `apply_action`, `resume_game`, `reset_turn`, `SafeView.apply`; `owed_step`, `OWED_STEP_NAMES`, `STEP_OWED`, `turn_reset_refusal`, `tests/prompt_fixtures.py`'s owed and AI cases, `tests/test_d12ball_game_service_resume.py`; `tests/cog_steps.py`; **the AI**: `d12ball/ai.py`, `AIStrategy.choose`, `driver.ai_action`, `asked_sides`, `NOBODYS_QUESTIONS`, `Batching.carry_answer`, `AI_ANSWER_CARRY`, `Narration.prompt`/`.action`, `post_ai_answer`, `MAX_AI_ANSWERS`, `tests/ai_answers.py`, `AIAnswerTests`; **setup and the lobby**: `create_game`, `configure`, `pick_team`, `flip_coin`, `choose_home_or_visiting`, `rematch`, the lobby moves, the `D12BallGame` methods under them and the readings a table draws from (`open_settings`, `teams_open_to`, `coin_is_owed`, `home_choice_owed_by`), `GAME_SETTINGS`, `open_new_game`, `open_lobby`, `lobby_start`, `tests/test_game_service_setup.py` | [game-service.md](docs/design/game-service.md) | One door and one save; why the result is groups with snapshots rather than strings; batching stays the frontend's, including the answer's own lines and the AI's; the presenter saves nothing; recovery is the service's, off the one reading, and which positions are the bot's to run; the AI is a client of the service, asked whatever a coach is and never a roll, and how its run back stays one message; setup and the lobby as service methods over rules on the record, with the randomness the engine's |
| `webapp/`, `webapp/identity.py`, `webapp/rooms.py`, `WEB_ROOMS_FILE`, `webapp/chat.py`, `WEB_CHAT_FILE`, `webapp/journal.py`, `WEB_JOURNAL_FILE`, `D12BallGame.take_seat`/`vacate_seat`/`seat_ai`/`unseat_ai`, `ai_seats`, `ai_holds`, `tests/test_game_seats.py`, `gamelocks.py`, `d12ball/wire.py`, `GameService.listeners`, `SafeView._scheduled_task`, `RulesEngine.cyborg_condition_ids`, `webapp.server.main`/`build_service`, `WEB_GAMES_FILE`, `tests/test_web_app.py`, `tests/test_web_table.py`, `tests/test_web_board.py`, `tests/test_web_purity.py`, `tests/test_web_journal.py`, `tests/test_game_locks.py`, `tests/test_wire_shapes.py`, `webapp/aids.py`, `tests/test_web_aids.py`, `RulesEngine.maneuver_reference_tier`, `species_cards.REFERENCE_FACES`, `rulebooks.book_bytes`, `FOOLBOT_WEB_*` | [web-app.md](docs/design/web-app.md) | What a second frontend may not do and how it is measured; the wire shapes and why they are one-way; who is on the other end of a request and what is not sent to them; why it is its own process over its own file, and the fences both ways; what the lock is actually for; why a page sees the other coach's turn; the page's two columns, and why the board is HTML in the bot's layout with the model's own cards on it; the chat, why it is the room's own file and not the game's, why it rides on the poll, and why it is not the model's voice; rooms and seats -- the cookie, why nothing is stored, why a seat may change hands mid-game, why an empty seat is not the AI's and what `ai_seats` says, the AI in either seat, why roles are the frontend's file, why the seat names follow the coin; the room's table -- the front door, why every question on the table is the record's, why there is no separate Begin, the rematch as a room of its own; the rules and the player aids -- why PDFs and not an HTML book, why the numbers come from the Charter build, why the two reference choices moved below the cog |
| `d12ball/prompts.py`, `pending_turn_view`, `view_for_prompt`, `render_prompt`, `tests/prompt_fixtures.py`; `PendingPrompt.options`, `OPTIONS`, `with_options`, the option dataclasses, `SafeView.prompt_options`, `OVERDRIVE_ROLLERS`; `d12ball/flow/`, `StepResult`, `FollowOn`, `MODEL_STEPS`, `driver.advance`, `driver.answer`/`apply`, `Action`, `Refusal`, `RuleRefusal`, `REQUIRED_ARGUMENTS`, `_rail`, `d12ball/flow/rolls.py`, `tests/test_d12ball_driver_actions.py` (`LEGAL_ACTIONS`, `REFUSED_ACTIONS`), `tests/flow_stubs.py`, `dispatch_step_result` and its stops (`DRIVER_STOPS`, `DRIVER_OWN_MESSAGE`, `post_stop`, `post_narration_group`), `SafeView.answer`, `tests/low_pass_fixtures.py`, `tests/dribble_fixtures.py`; `tests/test_model_purity.py`, the four goldens, `tests/golden/`, `tests/test_driver_full_game.py`, anything that could add a `discord` import, an `async def` or a `PIL` import under `d12ball/` or `gamesaves/d12ball/`; **the tokens**: `d12ball/tokens.py`, `DiscordTokens`, `D12Ball.rendered`, `render_text`, `coach_name`, `address_coach`, `build_maneuver_action_caption`, `tests/test_d12ball_tokens.py`, `tests/test_golden_service.py`; `RulesEngine.rng`, `scripted_or_random` | [model-discord-split.md](docs/design/model-discord-split.md) | Why the chain moved whole and what a prompt may carry; one kind per view class and one picture per kind; why the loop is the model's and where it stops; why an action names a prompt rather than a step, and which three carry a side; what `answer` refuses and why authorising is not one of them; how the split is measured; the purity ratchets and why they run in a subprocess; what a token is and why a coach is a number; the goldens' seeded RNG and what each does not cover; the Python-version and root-test gotchas |

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

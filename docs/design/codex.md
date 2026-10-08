# The Codex bot

Design notes for fool-bot; the map is [CLAUDE.md](../../CLAUDE.md), the rules are [living-rules.md](../living-rules.md).

This repository runs two Discord bots. fool-bot plays D12 Ball; the
**Codex bot** plays Sirlin Games' *Codex: Card-Time Strategy*, starting
from the basic game -- one hero a side, Bashing (Troq Bashar) against
Finesse (River Montoya), the ten neutral starters as both decks, the
tower and the surplus as the only add-ons. It is modelled on the D12
Ball bot and built from [../codex-bot.md](../codex-bot.md), the
worksheet whose steps it is; this note is what those steps settled, one
section per decision as it lands.

Step 1 stood it up: the entry point, the shared bot class, the card
data and its import, `/codex card` and `/codex rules`, the runner.
Step 2 wrote the model whole -- the state, the record, the engine, the
prompts, the flow and the driver -- and a test that plays a game to a
destroyed base through the driver alone. Step 3 put it on Discord as
far as the opening position: the service and its file, `/codex lobby`,
the game's channel, the board, and each player's hand shown to them
alone. The model's purity rules hold for `codex/` and `gamesaves/codex/`
(`tests/test_model_purity.py`): no `discord`, no `async def`, Pillow
only in `codex/render.py`.

**Nothing hidden is ever written where another player can read it** --
a hand, a deck's order, a discard pile's contents, an unanswered tech
choice, a hired worker's card: not into a public message, not into a
log line, not into the #logs mirror. Codex is a hidden-information game
and D12 Ball never was, so nothing in the shared code guards this for
it; every step that touches a hidden zone says in its PR where it
checked. In step 1 nothing hidden existed yet; step 2's narration is
checked below, in "What the narration may say".

## Its own process, its own token

`codexbot.py` is its own process, beside `foolbot.py` and
`python3 -m webapp`, reading `CODEX_DISCORD_TOKEN` from the same `.env`,
with its own state file (`data/codex_bot_state.json`), its own pid and
logs, and -- from step 2 -- its own games file. Nothing is shared with
fool-bot at runtime (worksheet decision 1, the author's choice of
2026-10-07: a Codex cog inside fool-bot was not chosen, and would have
put one game's rate-limit buckets and crashes under the other's).

- **The name is a matcher argument.** `update_main_bot.ps1` finds every
  fool-bot by `foolbot\.py` in a process's command line and stops each
  one ("One bot per token" in [collaboration.md](collaboration.md)), so
  the entry point's name must not contain `foolbot.py`, or the updater
  would stop and count the Codex bot as a second fool-bot. `codexbot.py`
  does not; `run_codex_bot.ps1` matches `codexbot\.py`, which neither a
  foolbot nor `-m webapp` carries. Each script stops exactly its own.
- **The state file is its own because the keys are the same.**
  `data/bot_state.json` holds the command tree's fingerprint and the
  last build announced; two bots writing one file would each find the
  other's fingerprint there and re-sync their commands on every start,
  which is the rate-limited request the fingerprint exists to save.
- **The bot class is shared, not copied.** `gamebot.py` holds `GameBot`
  and the command-sync gate, moved out of `foolbot.py` with what
  `foolbot.py` hard-coded made parameters: the extensions, the state
  file, the variable that forces a sync (`FOOLBOT_COMMAND_SYNC`,
  `CODEX_COMMAND_SYNC`) and the message-content intent. fool-bot keeps
  the intent, which a game channel's export needs; the Codex bot is
  slash commands and buttons, so it asks for no privileged intent and
  there is one less switch in the Portal. `foolbot.py` keeps every name
  `tests/test_command_sync.py` patches, and its `GameBot` is a subclass
  passing today's values.
- **`botlog` is shared once it knows which bot it is.**
  `configure_logging(prefix, bot_name, state_file)`; the Codex bot's
  `CODEX_LOG_*` fall back to the `FOOLBOT_LOG_*` values, so one `.env`
  and one #logs channel serve both and every notice names its bot
  (the author, 2026-10-07; "Two bots read these" in
  [logging.md](logging.md)).
- **It carries no `/roll`, no coins and no Tethys deck** (the author,
  2026-10-08): one bot, one game.

## The cards are data

Every card's text, type, cost, stats and tech level, every hero's three
bands, and Sirlin's rulings come from the Codex Card Database's
repository, `rgdelato/codex-cards-gatsby`, through
`scripts/import_codex_cards.py`, and nothing else (worksheet decision
6). The rule is `d12ball/data/`'s: **regenerated whole, never edited by
hand, the import the only way** -- each file's header says so and names
its source.

- **The source is pinned.** The script fetches the ten `raw_data` files
  at the commit in `SOURCE_SHA` (`10f8952`, the repository's master on
  2026-10-08 -- its last commit is of 2019), so a re-import is the same
  import until somebody moves the pin on purpose; `--offline <dir>`
  reads the same files from a checkout and writes the same output.
- **All of it comes in at once**: 310 cards, 22 tokens, 8 buildings, the
  two worker cards (four workers and five) and 20 heroes, so a later spec is code, not data. A
  record has a `kind` -- `card`, `token`, `building`, `worker` -- read
  from its starting zone. Two records with one name collapse to the
  first: a token's two printed faces, and each colour's copy of the
  worker card, which differ only in their colour.
- **A card is keyed by its slug** and never held or compared by its
  name; `CardCatalog.name` is the one way back, for wording alone. The
  slug is the database's own (`toSlug` in its `createCardJSONData.js`):
  lowercase, whitespace to `_`, every other non-word character dropped
  -- `trojan_duck`, and `regularsized_rhinoceros` for
  "Regular-sized Rhinoceros", which is the database's page address.
- **The glyphs become tokens** the way `codex/tokens.py` reads them: ⤵
  `{exhaust}`, ◎ `{target}`, ① ② ... `{gold:n}`, → `{arrow}`. The
  model writes tokens and the cog renders them at its door
  (`cogs.codex_helpers.CodexTokens`), as D12 Ball's do; nothing else in
  the text is reworded. `{codex}` is the bot's own mark.
- **The rulings are the official rules of the game** (the author,
  2026-10-08). `codex/rulings.py` reads them -- `rulings_for(slug)` for a
  card's, `keyword_rulings(keyword)` for the `General` group's -- each
  with its author and date. A ruling that names two records ("Dancer /
  Angry Dancer") rules on each. Where the rulebook's text and a ruling
  differ, the ruling governs.
- **The copyright question** was the author's, answered on 2026-10-07:
  the texts, the rulings and the art are Sirlin Games' words and
  pictures, reproduced in this public repository as the fan database
  and the Screentop module reproduce them. The alternatives set aside
  were the facts alone in the tree with the prose fetched per checkout,
  the bot speaking only in its own words, and a private home for the
  prose.

**The art comes in the same run, and the author ran it** (2026-10-08,
on the Mac). The session that wrote step 1 could reach the card data
but neither image host, so the author imports the art where both
answer, and commits it; a session finishes the rest from what was
committed. Two sources:

- **The cards' own pictures**: each card's and hero's, by its
  `sirlins_filename`, from `codexcards-assets.surge.sh` into
  `codex/images/cards/<slug>.jpg`, 330 by 450 -- all 330 the host has.
  `.gitignore`'s old, unanchored `cards/` (for print output that used
  to land in a folder of that name) matched this folder too, and
  `git add` skips an ignored file without a word, so the first commit of
  the art carried none of the pictures; a negation for
  `codex/images/cards/` beside it is what lets them in.
- **The Screentop module's sheets** (@GRAG/Codex, whose spec one
  GraphQL query to `api.screentop.gg` returns with every sheet's URL):
  the playmat whole as `codex/images/board/playmat.png`, and seven
  sheets kept whole under `codex/images/board/sheets/` as the source
  their pieces are cut from. **The cells are pinned in `BOARD_SHEETS`**,
  each from one look at the sheet: a grid per sheet, and each piece's
  index -- or its index and a quarter turn, for the tiles and spec
  cards the sheet stores on their side, so they read upright as the
  playmat prints them. `--cut-only` cuts them again from the committed
  sheets with no network, so a change to a pin is made and checked
  anywhere.

What is under `codex/images/board/`, and what each is named by:

| Folder | What | Named by |
| --- | --- | --- |
| `playmat.png` | One player's mat: the hero slots, the five patrol slots with their bonuses, the add-on slot, the base and the Tech I to III places, the workers, the discard and the draw | -- |
| `buildings/` | The base and the three tech buildings as tiles, the four add-ons as cards | the building's slug |
| `tokens/` | All 22 tokens' faces, two printed under another name: "Ghost" is `daigo_stormborne`, "Elemental" `water_elemental` | the token's slug |
| `specs/` | The twenty spec cards | the spec, as a slug |
| `backs/` | `card`, `hero`, `token` | -- |
| `patrol/` | The five slots' icons, white on the module's blue; the first printed "Patrol Leader", the rulebook's squad leader | the slot |
| `damage/`, `levels/`, `time_runes/` | Damage 1 to 9; a hero's level 2 to 8 and `max`; time runes 1 to 6 | the number |
| `chits/` | Single counters: `damage_1`, `damage_3`, `level_1`, `levels_3`, `plus_rune`, `minus_rune`, `two_step` (the +2/+2 with two dancers), and a blue `swirl` and an orange `house` nobody has said the module's use of, named for what they show | what it shows |

Left uncut: the twelve maps, a variant the basic game does not play, and
the sheets' label cells, which the playmat prints. `Card.picture` is a
card's own art wherever there is one -- the database's picture, or a
token's or a building's face -- so `/codex card dancer` and `/codex card
tower` answer with theirs; the worker card alone has none.

**The emoji are drawn here and uploaded by hand.** Application emoji
belong to one application and there is no upload code, so
`scripts/render_codex_emoji.py` draws `gold`, `exhaust` and `target`
into `codex/images/emoji/`, and cuts `troq_bashar` and `river_montoya`
from their cards' art at a square pinned per hero (`FACES`), since no
one crop finds two faces drawn in two places; `codex.png` is the
medallion cut from the module's card back,
and the author uploads each to the Codex application under its file's
name. `CodexTokens` picks each up by that name and shows a word until
it is there.

## The model, before a line of Discord

Step 2 copied D12 Ball's shapes into `codex/` -- `MatchState` and its
saved-fields table, the record, `RulesEngine`, `PendingPrompt` and
`pending`, `StepResult` and `FollowOn`, the driver -- keeping the names,
so whoever reads one bot reads the other (worksheet decision 2). What
differs is what Codex asks that D12 Ball never did: a secret answered
on the other player's turn, a dozen actions in one turn, and undo.

- **The whole game runs through `codex.flow.driver.apply`.**
  `tests/test_codex_driver_full_game.py` plays Bashing against Finesse
  from the deal to a destroyed base under a simple policy, every
  position round-tripping through `to_dict`, `from_dict` and
  `validate`, and checks in a fresh interpreter that neither `discord`
  nor anything under `cogs/` was imported. Run with `-v`, it prints the
  game's narration in plain words: the transcript the author reads for
  wording. Where the bot owes a step (the turn's start, the draw, the
  end of the turn) the test runs it as the service's resume will.

### The prompt kinds

| Kind | Asked of | What it asks |
| --- | --- | --- |
| `MAIN_ACTION` | the active player | hire, summon, level, play, build, attack, or end the main phase -- the options are the engine's `legal_actions`, each card in the hand with its cost and why it may not be played |
| `CHOOSE_DEFENDER` | the active player | which of `legal_defenders` the declared attacker takes, or `cancel` to take the attacker back; asked after the attacker, so a misclick costs nothing (decision 11) |
| `PATROL` | the active player | slot to unit or hero, any left empty; ends the main phase (UMR p. 10) |
| `TECH_CHOICE` | the choice's owner | the picks from their codex, within the bounds -- two, or none to two at ten workers (UMR p. 5) |
| `TECH_CONFIRM` | the choice's owner | `confirm` or `change`; the turn begins only once it is answered |
| `GAME_OVER` | nobody | a base is destroyed (UMR p. 2); answering it is refused until step 7's rematch |

The bot owes three steps, which `owed_step` names and a resume runs:
`BEGIN_TURN` (the ready phase and the upkeep), `DRAW_PHASE` and
`BEGIN_TECH` (the end of the turn). `driver.MODEL_STEPS` covers
`FollowOnStep` and `driver.ANSWERS` covers `PromptKind`, exactly, which
`tests/test_codex_driver_actions.py` holds.

- **An attacker is a ref, not a card.** An action names a unit
  `unit:<id>` and the hero `hero`, and a defender also `base`, `tech1`
  to `tech3` or `add_on`. The declared attacker is saved
  (`MatchState.attacking`) while the defender is asked, so a restart
  between the two clicks asks the same question.

### The standing prompt

The tech choice is chosen secretly while the opponent plays (worksheet
decision 8; the author, 2026-10-08). `pending` stays one reading with
one answer, the active player's; `standing_prompts(engine, match)` lists
what the other player may answer meanwhile -- `TECH_CHOICE`, from the
moment their turn ends until their next one begins, each answer
replacing the picks. Their turn opens on `TECH_CONFIRM` (or on
`TECH_CHOICE` itself where they never picked), and `begin_turn` refuses
to run until the picks are confirmed; the confirmed cards go face-down
into the discard pile in the ready phase, and only then leave the
codex.

- **A tech action names its seat** (`arguments["player"]`), because
  both players can have one open at once -- the player whose turn
  begins confirms theirs while the one whose turn just ended picks.
  `driver.answer` finds the open prompt of that kind and seat among the
  pending one and the standing ones; authorising the clicker is the
  frontend's, as always.
- **What a tech prompt holds is its owner's**: their codex and their
  picks. A frontend sends it to them alone.

### Undo's groundwork: the snapshots and the journal

Decision 11's two saved fields are in the first commit of the model.
`begin_turn` ends by taking a **snapshot** -- the position as saved,
without the snapshots and the journal themselves, at the start of the
main phase, once the gold is collected -- keeping the last three, and
emptying the **journal**. `driver.apply`, the one door every action
goes through, records each applied action with the random outcomes it
consumed: every shuffle's order, which a step hands back in
`StepResult.drawn` and nobody else ever sees (it is left out of the
wire). An action during which a turn began is not recorded, since the
snapshot it led to already holds its effects.

- **`engine.shuffle` is the only shuffle**, and takes a recorded order
  back: `history.replay` rebuilds a point in a turn from its snapshot
  and a prefix of the journal, handing each action's recorded orders to
  the engine instead of drawing, so the replay is byte for byte
  (`tests/test_codex_history.py` replays a turn whose draw reshuffles,
  with an engine of another seed) and **an undo past a draw deals the
  same cards**.
- **The two undos are over the snapshots alone**:
  `undo_to_turn_start` restores this turn's snapshot and
  `undo_to_previous_turn` the one before, trimming the later ones.
  `undo_targets` says which are open. Who may ask for which -- the
  opponent's consent for the second -- is step 4's frontend. A tech
  answer the other player gave during an undone turn goes with it.

### The vanilla engine and `UNIMPLEMENTED`

The engine plays every card of the set for its cost and its numbers
(decision 7). `codex.effects.UNIMPLEMENTED` lists every card whose text
it does not honour -- in step 2, every card of the basic set with any:
36 slugs, the two heroes' bands, the two tokens and the two add-ons
among them -- written out rather than computed, so the commit that
takes a card out of it is the commit that gives it a handler.
`tests/test_codex_effects.py` pins the set and checks it is exactly the
set's cards with text. **Nothing is ignored silently**: the line that
plays such a card ends "(its text is not played yet)".
`codex.keywords` reads the keyword table off the texts -- a keyword is
read where a line opens with one, so Sneaky Pig's "Arrives: Gets
stealth this turn" is an effect and not a keyword -- present and inert
until step 5.

What the vanilla engine does play is the board's own rules: gold and
its cap, the once-a-turn hire, the draw and the once-a-phase reshuffle,
the hero's summon, levels, bands and the heal at a band, summoning
runes and the kill's two levels, the tech buildings with their worker
counts and their finish at the end of the turn, the rebuild for 0, the
add-on slot, arrival fatigue, the three attack priorities, simultaneous
damage, the patrol slots' bonuses (the lookout's resist waits on
targeting, step 6), what each kind of card does when destroyed, and the
base at 0. Each is in `tests/test_codex_rules.py` with its page.

- **Three readings the rulebook left open, settled by the author on
  2026-10-08**: a tech building needs the one below it *finished* (so
  Tech I and Tech II are never built in one turn); a new add-on
  replaces the one in the slot, which is destroyed and deals its 2 to
  the base; and the first player chooses tech at the end of their first
  turn like every other turn.

### The saved fields

**The save format is the contract from step 2 on.** Every class saved
inside a match -- `MatchState`, `PlayerState`, `HeroState`,
`CardInstance`, `BuildingState`, `AddOnState` -- has a `SavedField`
table (`codex.components.SAVED_FIELDS`) giving each field its fallback
for a save older than it, and `tests/test_codex_components.py` fails on
a field its table does not name, the guard `MATCH_SAVED_FIELDS` is for
D12 Ball. Mutable fields are copied each way; the snapshots, the
journal and the events are deep-copied, since each nests the position.
`validate` checks a loaded match against itself -- ids unique, every
slug a card, one patroller a slot, no count below zero -- and raises
`ValueError`, a corrupt save rather than a rule. `CodexGame` holds the
match as its saved dict, as D12 Ball's record does; its file,
`data/codex_games.json`, is step 3's.

- **Two fields beyond the worksheet's list** were needed: each card
  and hero carries `armor` (what is left of the squad leader's armour
  this turn, set when a turn begins), the hero its `patrol_slot`, and
  the match `attacking`. Each is in its table with its fallback.

### What the narration may say

Every line is in the model's voice with tokens -- `{player:1}`,
`{card:iron_man}`, `{hero:troq_bashar}`, `{gold:3}` -- and is public.
So a draw is a count ("discards 3 and draws 5"), a reshuffle is said
without the order, a hire never names the card trashed, and a tech
choice is "has chosen their tech" and, when confirmed, a count of cards
into the discard. `test_nothing_hidden_is_said` in the full-game test
checks the hire and tech lines name no card. The event log holds card
identities (a hire's card among them) and stays in the save, which the
bot never exports (the author, 2026-10-07).

### Naming by slug in the tests

`tests/codex_positions.py` stages a position by card slug --
`put(match, seat, "iron_man", patrol="elite", damage=1)`. D12 Ball's
tests name a player by role because its roster is data the author
revises; Codex's cards are fixed data imported whole at a pinned
commit, so a test says exactly the card it means.

## The reference commands

`/codex card <name>` answers in the channel with the card's picture
attached, and under it, as plain text -- nothing in this bot is an
embed (the author, 2026-10-07) -- the name, the type line, the cost and
numbers (a hero's three bands), the text, Sirlin's rulings with their
authors and dates, and the database's page. `/codex rules <keyword>`
answers with a keyword's rulings as the official rules they are.
Both autocomplete (over every card and hero, and over the `General`
group's keywords) and both fit Discord's 2000 characters by counting the
rulings that do not fit and leaving them to the link, measured after
the tokens are rendered. No rulebook text is bundled and
`docs/living-rules.md` is not touched (worksheet decision 12).

## The service and its file

`gamesaves/codex/` is D12 Ball's two modules copied (decision 2):
`storage.py` writes `data/codex_games.json` -- the temporary file
renamed over the real one, never raising, the two per-file failure
flags -- with no legacy migration, since the save format has been the
contract from step 2; and `service.py` is `GameService`, whose lobby
moves (`create_game`, `take_seat`, `leave`, `start`, `abandon`,
`set_board_layout`) are each a thin door over a rule on `CodexGame`,
saving once, and whose `apply_action`, `run` and `resume` each load,
apply, save once and return a `GameResult`. Two things differ from
D12 Ball's:

- **An action goes through `driver.apply`, never `driver.answer`**,
  because `apply` is where the journal is written. So the service may
  not split an answer from what follows it (no `carry_from`), and an
  action's run is never stopped part-way: a stop would cut what the
  journal records as one action in two. `Batching.stop_after` is
  honoured where the bot runs its own steps -- `start` and `resume` --
  which are never journalled.
- **The result carries the standing prompts** beside the pending one,
  and its JSON carries neither: a prompt lists a hand or a codex, which
  is its asked player's alone, and a result is everybody's.

`load` does not make the `data/` folder (D12 Ball's does): building the
cog loads the games, and a load that made the folder would make it
wherever a test builds one. The first save makes it.

## The lobby and the channel

**`/codex lobby` opens the game's channel and posts the lobby in it**
(the author, 2026-10-08, on trying step 3: the lobby belongs in the
channel the game is played in). The worksheet's decision 10 had it
posted where the command is typed; the author's later word governs.
The channel is `codex-<n>` under **Codex Games**, created if missing,
and open to the whole server -- anyone can look in, talk and take a
seat -- as D12 Ball's lobby channels are; the person who typed the
command is told where it is, privately. A channel that cannot be made
opens no lobby. The lobby is a line per seat and **Play Bashing**,
**Play Finesse**, **Leave**, **Start**, persistent (fixed custom ids
carrying the game id), re-armed on startup. A seat taken or given up
edits the lobby in place through the click's own response, which
spends nothing from the channel's edit bucket. Start is either seated
player's, or a game helper's -- the lobby asks no confirmation, as
D12 Ball's does not.

**A test game seats one person on both sides** (`/codex lobby
test_game:True`, the author, 2026-10-08), as D12 Ball's test games do.
The record's rules are what change: `take_seat` sits a person already
seated down on the other side too rather than moving them, `leave`
frees both seats, and `seats_of` reads both. A click acts for
`seat_for(user, active)` -- the seat whose turn it is, where the clicker
holds it -- so **My hand**, **Codex** and `/codex hand` show the side
that is playing, and their captions name it. Nothing is hidden from one
person playing both hands, so nothing more is needed; the tech choice
on the other side's turn is step 4's to word.

**Start turns that channel into the game's**, in one edit: renamed
`codex-<n>-<p1>-vs-<p2>` (capped at 100 characters) and closed to
everybody's messages but the players'. The service deals and runs the
first turn's ready phase and upkeep in one save, the lobby is edited
once to say the game has started, its buttons gone, and the first
turn's message goes up under it, pinned. The categories are the Codex
bot's own -- **Codex Games** and **Codex Archive** -- not PBD's, whose
names `/debug`'s reset and the pin rollover match and whose
fifty-channel cap is D12 Ball's.

- **Anyone in the server may read the channel; the two players and the
  bot may write in it** (question 8 of the worksheet, the author,
  2026-10-08: the hands are ephemeral, so a watcher sees the table and
  nothing more). The step's prompt also said "the permissions D12
  Ball's channels get", which hide a started game from `@everyone`; the
  author's later answer was taken, and the PR asks.
- **fool-bot's hub points at the lobby** the one way Discord allows
  across applications, a command mention (decision 10): `codexbot.py`
  writes its top-level command ids to `data/codex_command_ids.json`
  after each sync -- or, on a start that skipped the sync, once from a
  fetch when the file is missing -- and `build_hub_message` reads it for
  `</codex lobby:ID>`, falling back to the command's name in plain text.
  It is the one file read across the line, and fool-bot only reads it.
  The line's wording is the author's to give; until then it is a
  placeholder.
  Its heading carries the Codex medallion as **fool-bot's own**
  application emoji, `codex` (`CODEX_HUB_EMOJI_NAME`), uploaded from
  `codex/images/emoji/codex.png`: the Codex bot's upload belongs to the
  Codex application and fool-bot cannot use it. `/d12ball setup_hub`
  fetches it, so an upload takes without a restart.
- **There is no button that fills in `/codex lobby`.** Discord gives a
  bot no way to put text in somebody's message box: a button's click
  goes only to the application that posted it, a link button only
  opens a URL, and no URL prefills the composer. The command mention
  is the one thing that does, and the hub carries it.

## Who may act, shared

`cogs/game_auth.py` holds the gates both bots ask -- `game_participant_ids`,
`is_game_helper`, `may_act_for_coach`, `may_act_in_game`, the helper's
confirmation marker and exception -- and `send_new_prompt`, moved out of
`cogs/d12ball_helpers.py`, which re-exports every name, so nothing else
under `cogs/d12ball*` changed. They read the record's two seat ids,
which `D12BallGame` and `CodexGame` spell alike ([permissions.md](permissions.md)).
The Codex `SafeView` has no helper confirmation yet: in step 3 no button
acts for a player but the lobby's, so its gates let the seated players
alone through, and step 4 brings the confirmation with the panel.

## The board on Discord

**One public message per turn** (decision 5): the board as its picture,
the turn's lines as its text, the game's buttons under it. Everything
else the bot shows is ephemeral.

- **The board is the module's playmat with the position laid on it**
  (`codex/render.py`): the hero as its card in the first hero slot with
  its level chit -- or the slot empty with a time-rune chit for its
  summoning runes while it is in the command zone; patrollers in their
  five slots; the Tech I to III tiles in their places, faint where
  unbuilt, tagged *building* while under construction and *destroyed*
  when they are, with damage chits; the base's damage on the mat's own
  base, which the mat prints (the module's base tile was tried and
  doubled the printed base); the add-on's card in its slot; the draw
  pile as the card back with its count on a tag below the medallion;
  the discard and the workers as counts; the play zone's other units as
  their cards across the mat's middle, in a grid of square cells so a
  card turned sideways (exhausted) fits too, each with damage and rune
  chits and *arrived* when it came this turn. A strip along each mat's
  top names the player, the spec and the hero, and counts the gold, the
  hand, the codex and the base; the active player's strip is lit.
  Composed at the mat's own size and scaled by `BOARD_SCALE` (0.6),
  about 2 MB.
- **The layout is the game's**, on the record (`board_layout`, not the
  match's, so an undo does not take it back): stacked, or side by side
  with the first player's mat on the left. **Swap view** flips it for
  everyone and the board goes up through the gate.
- **Stacked is the table seen from the active player's side** (the
  author, 2026-10-08): their mat at the bottom, the other player's
  above it and turned round to face them, so the two patrol zones face
  each other across the gap as they do across a table, and the picture
  turns with the turn (`stacked_seats`, the one reading of which seat
  is near). The far mat is turned whole -- its cards, chits and counts
  read upside down, as the far side of a table does -- but the strip
  above it is the bot's words, not the mat's, and stays the right way
  up: a name and four counts nobody should have to turn a phone for.
  A finished game is seen from where it was left. Side by side turns
  neither mat: two mats read left to right are a desk, not a table.
- **Swapping the view changes the message's shape**, and what the
  reader sees in between is the client's. A stacked board is tall and
  a side-by-side one wide, so the one edit that replaces the picture
  also re-lays the message out, and Discord's apps draw the picture
  they have into the box they are moving to while the new one loads --
  the slice of board seen mid-swap. The bot sends one edit and cannot
  send less; the one thing in its hands is how long the new picture
  takes to arrive, which is its size (about 2 MB as PNG at
  `BOARD_SCALE`; measured 2026-10-08, the same board is about 340 KB as
  JPEG at quality 85 and 220 KB as WebP), a trade of the card text's
  crispness the author has not been asked to make.
- **The write gate is D12 Ball's `BoardRefresher`**, shared rather than
  copied: what it reached into D12 Ball for is a parameter -- the view
  kept on the message (`keep_view`; D12 Ball's home/visiting buttons
  once inert, the Codex bot's `TurnMessageView`), when the full-image
  link may go up (`links`; D12 Ball's once the sides are chosen, the
  Codex bot's always), which message is the board (`message_of`; the
  Codex record's `turn_message_id`), the message's text (`text_for`,
  which D12 Ball does not pass) and the game's name in the log. Each
  defaults to D12 Ball's, so its tests build it as they did. An edit
  whose picture and text are both unchanged is skipped.
- **The turn's lines are held in memory**, by game, in the model's
  tokens, and rendered at the door (`CodexTokens`: `{player:n}` the
  seat's name, `{card:slug}` and `{hero:slug}` in bold, the hero's emoji
  where uploaded). After a restart the message's text stands as it was
  until `/codex resume` re-posts the table; the gate leaves the text
  alone (`text_for` answers `None`) where it has not seen the lines.

## Hidden information on Discord: the ephemeral shape, as tried

Decision 4's shape, tried for the first time in step 3: **My hand** on
the turn message answers the clicker alone, ephemerally -- their hand
pictured by `render_hand` (each card's own art, numbered, its cost after
reductions on a coin, greyed where it may not be played, which is the
engine's `hand_rows`) and their discard pile listed as text. **Codex**
answers with their own codex pictured by `render_codex`, every card with
a badge of the copies left and faint at none, under a menu -- Everything,
Tech I, Tech II, Tech III, Spells -- that re-renders the picture in place
(the engine's `codex_remaining`, by `codex_views`). A watcher who
presses either is told the table is not theirs. Nothing is stored: each
press makes a fresh ephemeral message, and `/codex hand` answers the
same. Where it was checked that nothing hidden is public: the turn
message's text is the narration alone (`test_the_turn_message_names_no_card_in_a_hand`),
`GameResult.to_dict` writes no prompt, and no log line in the cog names
a card.

## Running it

On the Mac, from the checkout, with `CODEX_DISCORD_TOKEN` in `.env`:

```bash
python3 codexbot.py
python3 scripts/import_codex_cards.py      # re-import the cards and the art
python3 scripts/render_codex_emoji.py --in-place
python3 scripts/render_codex_sample.py --out /tmp/codex   # the board, a hand, a codex
```

On the live host, `scripts\run_codex_bot.cmd` restarts it and
`scripts\deploy.cmd` runs it straight after `update_main_bot` -- see
"The Codex bot" in [collaboration.md](collaboration.md). `CODEX_COMMAND_SYNC=force`
syncs the command tree regardless of the fingerprint, as
`FOOLBOT_COMMAND_SYNC` does for fool-bot.

There is **one Developer Portal application** for it, the live one,
created by the author on 2026-10-07, and **no test application**
(2026-10-08): a second application would need its own emoji uploaded
and its own invite for a bot that, in these steps, only two people
test. So one Codex bot runs at a time -- a session testing from the Mac
stops the live host's first, or runs before the live host runs one at
all.

# The Codex bot

Design notes for fool-bot; the map is [CLAUDE.md](../../CLAUDE.md), the rules are [living-rules.md](../living-rules.md).

This repository runs two Discord bots. fool-bot plays D12 Ball; the
**Codex bot** plays Sirlin Games' *Codex: Card-Time Strategy* whole:
every printed card of the seven colours, all twenty heroes, the basic
game -- one hero a side, Bashing (Troq Bashar) against Finesse (River
Montoya), the ten neutral starters as both decks, the tower and the
surplus as the only add-ons -- and the standard one, three heroes a side
from any colours, with the heroes' hall and the tech lab. It is modelled
on the D12 Ball bot and built from [../codex-bot.md](../codex-bot.md),
the worksheet whose steps it is; this note is what those steps settled,
one section per decision as it lands.

Step 1 stood it up: the entry point, the shared bot class, the card
data and its import, `/codex card` and `/codex rules`, the runner.
Step 2 wrote the model whole -- the state, the record, the engine, the
prompts, the flow and the driver -- and a test that plays a game to a
destroyed base through the driver alone. Step 3 put it on Discord as
far as the opening position: the service and its file, `/codex create_game`,
the game's channel, the board, and each player's hand shown to them
alone. Step 4 put the whole turn there -- the panel, the turn message
rolled over at the turn's end, the tech choice during the opponent's
turn, the undos and the resume -- so two people can finish a game
on the vanilla engine. Step 5 gave the engine the combat keywords, so
every card whose text is a keyword plays in full and the tower is worth
building. Step 6 gave it the rest: the spells, the arrives and attacks
triggers, the heroes' bands, the abilities, the static grants and costs,
the ongoing spells with their tokens and partners, and the upkeep's
effects and their order -- so every card of the basic set does what it
says and `UNIMPLEMENTED` is empty. Step 8 gave a game its end -- a
concession, a player's or a helper's abandon, the rematch, the channel moved to the
archive -- and pinned a whole game through the service in a golden.
Step 9 moved what the two games turned out to share to one home,
`gamekit/` and `botkit/` ("What the two games share"). Step 10 made the
standard game playable -- three heroes a side, the hero limit, the spec
at Tech II, the heroes' hall and the tech lab, the multicolour costs --
and landed red and green, played for their numbers ("The standard
game"); steps 11 to 13 gave every colour its text, two at a time ("Red
and green", "Purple and black", "White and blue"), and after step 13
`UNIMPLEMENTED` is empty for good. The model's
purity rules hold for `codex/` and `gamesaves/codex/`
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
  `{exhaust}`, ◎ `{target}`, ① ② ... `{gold:n}`, → `{arrow}`; the
  narration's own are `{player:n}` (a seat's name), `{to:n}` (a seat
  addressed -- a mention on Discord), `{card:slug}` and `{hero:slug}`. The
  model writes tokens and the cog renders them at its door
  (`cogs.codex_helpers.CodexTokens`), as D12 Ball's do; nothing else in
  the text is reworded. `{codex}` is the bot's own mark.
- **The rulebook is the Unofficial Manual Rewrite v1.3**
  (https://gitlab.com/omniraptorr/codex-rules/-/raw/main/Codex_UMR_v13w.pdf?inline=true),
  which the author prefers to the official rulebooks
  (https://sirlingames.com/rulebooks) and which should agree with them on
  every matter (2026-10-08). Its pages are cited as `UMR p. n`, its Card
  FAQ is pp. 19-22, and every card is read against it as well as the
  database -- step 6's were, on 2026-10-08. It is committed at
  `docs/codex/Codex_UMR_v13w.pdf` (the author, 2026-10-08), the copy
  every `UMR p. n` cites, so a session with no network reads the same
  page; the bot quotes none of it. **Since 2026-10-11 the official
  rulebook governs** (the author: "the official rulebook and the FAQs on
  the database are the official source of the rules; the unofficial
  rules ... may be wrong sometimes"): the Core Set's "Rulebook version
  46" is committed at `docs/codex/Codex_Core_Set_Rulebook.pdf`, cited
  as `Rulebook p. n` by the number printed at the foot of its pages (its
  contents table runs one page ahead of them), and where it and the UMR
  differ the rulebook's reading is taken and the UMR's noted. The
  multiplayer worksheet ([codex-multiplayer.md](../codex-multiplayer.md))
  was the first read against it and lists the differences it found on
  the two modes; nothing already built from the UMR was re-read, so a
  disagreement found later in a duel's rule is a question for the author.
- **The rulings are the official rules of the game** (the author,
  2026-10-08). `codex/rulings.py` reads them -- `rulings_for(slug)` for a
  card's, `keyword_rulings(keyword)` for the `General` group's -- each
  with its author and date. A ruling that names two records ("Dancer /
  Angry Dancer") rules on each. Where the rulebook's text and a ruling
  differ, the ruling governs -- the Card FAQ's included: **the database's
  rulings come before everything else** (the author, 2026-10-10, on Bird's
  Nest's limit of two).
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
  the playmat whole as `codex/images/board/playmat.png`, and eight
  sheets kept whole under `codex/images/board/sheets/` as the source
  their pieces are cut from. **The cells are pinned in `BOARD_SHEETS`**,
  each from one look at the sheet: a grid per sheet, and each piece's
  index -- or its index and a quarter turn, for the tiles and spec
  cards the sheet stores on their side, so they read upright as the
  playmat prints them. `--cut-only` cuts them again from the committed
  sheets with no network, so a change to a pin is made and checked
  anywhere. A sheet not pinned yet comes in whole first, from a machine
  that can reach Screentop (the cloud sessions' network policy refuses
  it): `--list-sheets` names every sheet the module has, and
  `--fetch-sheet NAME` keeps one under `sheets/` and cuts nothing, so
  its cells are looked at, pinned in `BOARD_SHEETS` and cut with
  `--cut-only` like the rest -- the colours' card sheets, for their
  worker cards, were the first. **The six colours' card sheets are not
  committed** (the author, 2026-10-10): 15 to 20 MB each, 106 MB in
  all, for twelve worker cards of about 1 MB together, so they are in
  `.gitignore` and their cuts are committed alone. `--cut-only` keeps
  the cuts of a sheet that is not on disk and fails only where one of
  them is missing, naming the `--fetch-sheet` that brings the sheet
  back; a cut no cell is pinned for still goes. The neutral sheet,
  committed before, stays.

What is under `codex/images/board/`, and what each is named by:

| Folder | What | Named by |
| --- | --- | --- |
| `playmat.png` | One player's mat: the hero slots, the five patrol slots with their bonuses, the add-on slot, the base and the Tech I to III places, the workers, the discard and the draw | -- |
| `buildings/` | The base and the three tech buildings as tiles, the four add-ons as cards | the building's slug |
| `tokens/` | All 22 tokens' faces, two printed under another name: "Ghost" is `daigo_stormborne`, "Elemental" `water_elemental` | the token's slug |
| `workers/` | The two worker cards' faces off the neutral card sheet -- x4, printed "Player 1", and x5, "Player 2" -- which the database does not picture (the author, 2026-10-08: the module has them) | the worker card's slug |
| `worker_colors/` | Each colour's two worker cards off its own card sheet, the neutral ones' layout in its own art and ink (cells 14 and 15, 38 and 39 on Green's; pinned 2026-10-10), drawn on the board for a side whose starting deck is that colour. Not catalog cards, so beside `workers/` rather than in it: that folder holds the catalog's faces and nothing else | `<colour>_x4`, `<colour>_x5` |
| `specs/` | The twenty spec cards | the spec, as a slug |
| `backs/` | `card`, `hero`, `token` | -- |
| `patrol/` | The five slots' icons, white on the module's blue; the first printed "Patrol Leader", the rulebook's squad leader | the slot |
| `ground/` | `leather`: a plain patch of the playmat's leather, 860 by 168 from below its logo, cut by `PLAYMAT_CUTS` as the patrol slots are -- what the board's panels are laid on, mirror-tiled (the author, 2026-10-09) | what it is |
| `patrol_slots/` | The five patrol slots as the playmat prints them, 200 by 273, and each one's bonus strip under it, 200 by 41 (`<slot>_bonus`) -- cut from `playmat.png` itself rather than a sheet, at the boxes pinned in `PLAYMAT_CUTS` beside `BOARD_SHEETS` (from the design canvas's plan board, 2026-10-08), and re-cut by `--cut-only` with the rest: the board's patrol zone is drawn from them, the mat's own slots (the author, 2026-10-08) | the slot |
| `damage/`, `levels/`, `time_runes/` | Damage 1 to 9; a hero's level 2 to 8 and `max`; time runes 1 to 6 | the number |
| `chits/` | Single counters: `damage_1`, `damage_3`, `level_1`, `levels_3`, `plus_rune`, `minus_rune`, `two_step` (the +2/+2 with two dancers), a blue `swirl` nobody has said the module's use of, and the orange `house`, the module's mark on a building under construction or destroyed (the author, 2026-10-08), both named for what they show | what it shows |

Left uncut: the twelve maps, a variant the basic game does not play;
the sheets' label cells, which the playmat prints; and the neutral
sheet's other 34 cards, which the database pictures. `Card.picture` is a
card's own art, and every card has one -- the database's picture, or a
token's, a building's or a worker card's face -- so `/codex card
dancer`, `/codex card tower` and `/codex card worker x4` answer with
theirs.

**The emoji are drawn here and uploaded by hand.** Application emoji
belong to one application and there is no upload code, so
`scripts/render_codex_emoji.py` draws `gold`, `codex_exhaust` (not
`exhaust`, which D12 Ball's emoji already has) and `target`
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
| `MAIN_ACTION` | the active player | hire, summon, level, play, build, attack, detect with the tower (step 5), use an ability (step 6), or end the main phase -- the options are the engine's `legal_actions`, each card in the hand with its cost and why it may not be played, each ability with why it may not be used |
| `CHOOSE_DEFENDER` | the active player | which of `legal_defenders` the declared attacker takes, or `cancel` to take the attacker back; asked after the attacker, so a misclick costs nothing (decision 11) |
| `PATROL` | the active player | slot to unit or hero, any left empty; ends the main phase (UMR p. 10) |
| `TECH_CHOICE` | the choice's owner | the picks from their codex, within the bounds -- two, or none to two at ten workers (UMR p. 5), which the ask says with the worker count; Asked in the main phase too, before its actions, where an undo to the turn's start took the turn's tech back |
| `TECH_CONFIRM` | the choice's owner | `confirm` or `change`; the turn begins only once it is answered |
| `OBLITERATE_CHOICE`, `SPARKSHOT_TARGET`, `OVERPOWER_TARGET` | the active player | the three choices inside an attack, each asked only where there is something to choose ("The keywords", below) |
| `TARGET` | the effect's controller -- the active player | what a part of a spell, a trigger or an ability chooses, asked as the part resolves and only where there is more than one thing it could choose ("Targeting and the effects", below); since step 11 a part that picks *up to* some number offers `done`, and a pick from the asked player's own hand or codex is a private ref (`hand:<slug>`, `codex:<slug>`) the bot pictures to them alone ("Red and green", below) |
| `DIVIDE_DAMAGE` | the active player | where the next point of a divided damage goes (Ember Sparks, Burning Volley), one point a click until the amount is placed, or `cancel` ("Red and green", below) |
| `MODE_CHOICE` | the effect's controller | which of a "choose one" spell's modes -- or Land Octopus's upkeep choice -- is done; never asked when boosted, since "if you boosted, choose both", or where only one mode can be done |
| `APPEL_STOMP_TOP` | the active player | `top` or `discard`: where Appel Stomp goes once it has resolved |
| `UPKEEP_ORDER` | the active player | which of the upkeep effects whose order changes something goes first -- healing beside Star-Crossed Starlet's damage, and since step 11 Dothram Horselord beside a death or a sacrifice; never a gain ("Red and green", below) |
| `GAME_OVER` | nobody | a base is destroyed (UMR p. 2), or a player conceded (`MatchState.conceded`); answering it is always refused -- playing again is a new record (`GameService.rematch`), not an answer ("The end of a game", below) |

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

- **A pick made in its owner's own ready phase is confirmed as it is
  made** (the author, 2026-10-10: "they just picked it"). Where the
  turn opens on `TECH_CHOICE` -- they never picked during the other's
  turn, or pressed **Change** on the confirmation -- the save is the
  choice and the turn begins on it, picks or none: only a choice made
  earlier, during the other player's turn, is shown back for
  confirming. `_answer_tech_choice` reads it off the seat: the active
  player's tech prompt is always their ready phase's, since only the
  other player's stands.

- **A tech action names its seat** (`arguments["player"]`), because
  both players can have one open at once -- the player whose turn
  begins confirms theirs while the one whose turn just ended picks.
  `driver.answer` finds the open prompt of that kind and seat among the
  pending one and the standing ones; authorising the clicker is the
  frontend's, as always.
- **What a tech prompt holds is its owner's**: their codex and their
  picks. A frontend sends it to them alone.
- **Nothing stands in a test game** (`tech_stands`; the author,
  2026-10-09). One person plays both sides there, and a choice standing
  for the side whose turn it is not reached them beside the other
  side's: the Lock's follow-up was the picker of the side that had just
  ended its turn, and My hand -- from the third turn on, where the
  side whose turn began had never picked during the other's -- that
  side's own picker, two in a row with nothing to say whose was whose.
  So in a test game `standing_prompts` is empty, the picker is the
  pending prompt in its owner's ready phase, and the pick made there is
  the choice: `_answer_tech_choice` confirms it at once, since there is
  nothing earlier to review, and the turn begins on the save. Nobody
  owes tech before their first turn has ended, so the second side's
  first turn opens on its main phase as before. The reading is the
  model's, off the record's `test_game`, as D12 Ball's model reads its
  own: a cog hiding the standing prompt would be a second reading of
  what the match waits on. A real game is unchanged.

### Undo's groundwork: the snapshots and the journal

Decision 11's two saved fields are in the first commit of the model.
A turn starts with a **snapshot** -- the position as saved, without the
snapshots and the journal themselves -- keeping the last three, and
emptying the **journal**. **Where the turn opens on its player's tech,
the snapshot is the hand-over** (`begin_tech`, since 2026-10-10), before
the choice or its confirmation and the ready phase it runs, which the
journal then records as the turn's first entries -- so an undo to the
turn's start asks the tech again -- the confirmation where the picks
were made during the other's turn, the picker otherwise -- and the
ready phase runs again on the answer (the
author, 2026-10-10: "offer to confirm tech but also redo the ready
phase"). Where no tech is owed -- a player's first turn -- `begin_turn`
takes it at the start of the main phase, once the gold is collected,
after the ready phase and the upkeep (`_open_main`, which takes none
where the turn has one). Either way the patrol lock that ends the turn
before is not journalled: the snapshot it led to holds its draw. `driver.apply`, the one door every action
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
  opponent's consent for the second -- is step 4's frontend. **An undo
  to a turn's start asks the tech again.** Where the turn's snapshot
  is its hand-over, the restored position asks it by itself: the
  active player's standing picks wait for their confirmation, offered
  again (`TECH_CONFIRM`, with **Change** to pick anew), and the other
  player's picks, made during the turn, are gone with it; the
  confirmation runs the ready phase and the upkeep again -- the
  upkeep's order asked again where it was asked -- and a reshuffle in
  that upkeep shuffles afresh, since the tech may have changed what the
  discard pile holds. Nobody is told to choose again but a player with
  no picks standing (`tech_started_over`). **Where the snapshot is the
  main phase's opening** -- a turn that owed no tech, or a game saved
  before the hand-over became the start -- the undo clears every tech
  choice, a confirmed one too, and asks it again (the author,
  2026-10-10: "undo should clear the choices and make them choose
  again", and "including confirmed one"): `start_tech_over` does it
  inside `_restore`, for either undo:
  - **The active player's picks** went into the discard pile in the
    ready phase, before the snapshot, which on its own does not say
    which cards they were. So the ready phase keeps them on the player
    as **`teched`** (`[]` for a choice of none, `None` where no tech was
    owed) -- a saved field added for this, `None` in an older save,
    whose undo leaves the confirmed picks be. The undo takes them back
    out of the discard pile (the latest copy; the deck, then the hand,
    where an upkeep draw shuffled them in) and into the codex, and the
    choice is owed again. `pending` asks it **in the main phase**,
    before the turn's actions, and its confirmation settles it there
    (`turn.settle_tech`, the ready phase's own code, saying the count
    again): rolling back to before the ready phase instead would run
    the upkeep twice.
  - **The other player's picks**, never confirmed before their own
    turn, are cleared, even one made before the turn's start and so in
    its snapshot.
  - **The snapshot is replaced** with the position the choice is asked
    again on, so a second undo, and a replay of the journal (Appel
    Stomp's cancel), start there.
  The service's undo says `history.tech_again` on the turn message for
  each seat asked again, addressed to them -- said whether or not they
  had picked, so it tells nobody that they had. In a test game nothing
  is said: one person plays both sides, and the panel is the picker.
- **The fine undo is over the journal** (the author, 2026-10-10:
  "points between actions only"). `undo_points` replays this turn's
  journal once from its snapshot (`replay`'s `each`) and names each
  point the active player may go back to: before each action of theirs
  that began where the position asked the main phase's menu or the
  patrol's (`BETWEEN_ACTIONS`) and changed the position -- not inside
  a spell or an attack, which the cancel covers; not before a tech
  answer or the upkeep's order (`OPENING_KINDS`: the active player's
  own choice or confirmation, which opens a turn's journal where its
  snapshot is the hand-over, the upkeep's order where it was asked, and
  the other player's choice whenever it comes), which is no action of
  the turn and numbers none; and not an attacker declared and taken
  back, which changed nothing. Each point
  carries the lines the action said, to be named by, and the journal's
  length it was offered at, so a pick from a menu the turn has moved on
  from is refused. `undo_to` replays the journal cut at the point
  (`cut`: the prefix plus the other player's tech answers after it --
  the same cut a spell's cancel makes, so one function makes both) and
  returns what the turn now says: the kept actions' lines, then the
  undone line (`UNDONE_SOME`). It starts nobody's tech over, so the
  service says nothing to the other player (`_undo`'s
  `restarts_tech`). **A card off the top of a deck closes every point
  before it** -- a card seen cannot be unseen, the rule the cancel
  already keeps -- read off the replay as `StepResult.drew`, set at the
  three doors a card leaves a deck's top by (`draw_cards`, Vir's
  exchange and his play off the top), while **the start of the turn
  stays open as it was** (the author, 2026-10-10: "closed, but keep the
  start of turn as is"). A journal the rules no longer replay -- a game
  saved before a rule changed -- closes the fine undo and leaves the
  snapshots' two standing. Nothing into the previous turn: the journal
  is this turn's (the author, 2026-10-10) -- but for its end, below.
- **The end of a turn may be taken back by the player who ended it**,
  with nobody's consent, while the turn after it has done nothing but
  open (the author, 2026-10-13: "when you end turn and the other player
  hasn't yet taken any steps -- need to be able to undo that"). So a
  turn's journal is no longer thrown away when the next one starts:
  `snapshot` keeps it on the ended turn's own snapshot, under
  `ENDED_JOURNAL` -- inside the saved `turn_snapshots`, no new field;
  a snapshot taken before 2026-10-13 has none, and its end is not
  offered. `end_of_turn_owner` names the seat (the ended snapshot's
  `active`, so an extra turn's player too) while: this turn's snapshot
  is the latest and the ended one's is just before it; this turn's
  journal holds its opening alone (`OPENING_KINDS` -- the confirmation
  and the ready phase it ran are taken back with it, and the other
  player's tech pick made since is dropped, asked again when the turn
  ends again); no card has left a deck's top in that opening; and the
  game is not over. `undo_end_of_turn` replays the ended turn from its
  snapshot to its journal's **last point between actions**
  (`BETWEEN_ACTIONS`): its patrol, before the lock -- the lock is not
  journalled where the next snapshot was taken inside it, and where it
  was (a choice between the lock and the next turn's start: the stash,
  the upkeep's order of a turn that owed no tech) the point is still
  before it. The other player's tech answers after the point are kept
  (`cut`); nobody's tech is started over. It says the ended turn's
  lines up to there and `UNDONE_END`. The ended turn's snapshot becomes
  the latest again, without its journal, so the fine undo and the
  start of the turn are open over it as they were. **The end-of-turn
  draw is taken back after its player has seen it**: locking again
  draws the same cards off the deck's top unless the deck ran out, when
  the reshuffle is a new one (the drawn hand is not journalled, being
  the next turn's start).

### The vanilla engine and `UNIMPLEMENTED`

**`UNIMPLEMENTED` was empty from step 6 to step 9**: every card of the
basic set plays its text, and `tests/test_codex_effects.py` says where
each one's text lives -- a keyword the engine reads, or a row of the
tables in `codex.effects` ("Targeting and the effects", below). **It is
not empty since step 10**, which landed red and green played for their
numbers: 90 slugs, every red or green card, hero and token whose text is
more than keywords the engine reads -- the six heroes' bands among them
-- written out and pinned. **Step 11 emptied it again**, in five commits
("Red and green", below), and `test_unimplemented_is_empty` holds it there.

- **The landed set and the landed colours are one decision in two
  places.** `codex.effects.LANDED_SET` is every card the engine reads --
  the basic set, `RED` and `GREEN`, each a colour's ten starters, its
  three specs' thirty-six, its three heroes and its tokens -- and the
  keyword table and the static tables are read over it.
  `codex.cards.LANDED_COLORS` (neutral, red, green) is what the lobby
  offers heroes of, and refuses the rest of "not in this bot yet". Each
  pair's step extends both.
- **A card whose whole text is keywords plays in full** the moment it
  lands: Mad Man's haste, Nautical Dog's frenzy, Centaur's overpower,
  Chameleon's stealth, Huntress's sparkshot and anti-air, Barkcoat Bear's
  resist and overpower, and the Hunter token's anti-air. A card in
  `UNIMPLEMENTED` still plays the keywords it opens a line with
  (Chameleon Lizzo's haste), as Brick Thief's resist did in step 2.
- **A keyword the table does not know is not half-read**: a line that
  opens with deathtouch, long-range, ephemeral, boost or untargetable --
  or "Flying, long-range", which opens with nothing the reader takes
  whole -- is read as nothing, and its card is unimplemented.

What follows is how it got to empty the first time.

The engine played every card of the set for its cost and its numbers in
step 2 (decision 7); step 5 took the keywords out of
`UNIMPLEMENTED` -- Timely Messenger, Helpful Turtle, Fruit Ninja,
Revolver Ocelot, Eggship, Harvest Reaper, Backstabber, Cloud Sprite,
Leaping Lizard and the tower play in full, since their whole text is a
keyword (or, for the tower, its detection and its damage). A card with a
keyword *and* something else stays: Brick Thief has its resist and owes
its arrives trigger, Sneaky Pig has its haste and owes its stealth,
Trojan Duck obliterates and owes its 4 to a building. The Angry Dancer's
unstoppable is played, and it stays in the set beside the Dancer it is
flipped from, which nothing can make until step 6. What follows describes
step 2's engine. `codex.effects.UNIMPLEMENTED` lists every card whose text
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

### The keywords

Step 5 made `codex/keywords.py` the table the engine reads (worksheet
decision 7): `body_keywords(body)` is every keyword a thing in play has
and `has_keyword` / `keyword_x` the two questions over it, and
`RulesEngine` asks them wherever a keyword changes an answer. **Nothing
else reads a card's text to decide a rule**, and nothing in `cogs/`
knows a keyword at all -- the panel's buttons and menus are the prompts' options, as
always.

- **A keyword comes from three places**: the card's printed text (read
  where a line *opens* with a keyword, so Sneaky Pig's "Arrives: Gets
  stealth this turn" is an effect and not a keyword), a hero's bands up
  to the level it has reached (`hero_keywords`: Troq has readiness from
  8, not before), and **the patrol slot** -- the lookout grants resist 1,
  which is the one slot bonus that is a keyword rather than arithmetic.
  Step 6's granted abilities (Nimble Fencer's haste, Blademaster's swift
  strike, Maestro's exhaust) come in through the same function.
- **What stacks is a table** (`keywords.STACKING`, UMR p. 16 with
  Sirlin's rulings on each): frenzy, resist and sparkshot stack, so Brick
  Thief in the lookout slot is resist 2; anti-air and overpower do not,
  so two instances read as one. Healing is each card's own ability rather
  than a stacking keyword -- two Helpful Turtles heal twice because each
  heals once. Sparkshot stacks in the engine as the ruling says, though
  nothing in the basic set has it twice (the author, 2026-10-08: "build
  it according to the rules"): each instance deals its 1 to a neighbour,
  so two go to one patroller or one to each, `sparkshot_count` saying how
  many.
- **Who may be attacked, and who may be ignored.** `may_be_attacked`
  answers the first -- a flier only by a flier or an anti-air attacker, an
  invisible card only while patrolling or detected -- and
  `blocking_patrollers` the second: a patroller stops an attacker only
  on its own level ("you only stop an attacker if it's on the *same*
  level as you"), so a ground patroller never stops a flier and a flying
  patroller never stops a ground attacker, anti-air or not, since anti-air
  *may* shoot up but is never forced to. `ignores_patrollers` is the
  third answer -- unstoppable, or stealth and invisible while no detector
  sees it -- and `defender_rows` says which of the three it was, so the
  panel's buttons can say why a defender is legal ("flying", "stealth",
  "unstoppable"). That
  reason is about getting past the zone, so a patroller the attacker
  takes anyway is said as what it is -- "squad leader" or "patroller" --
  never "flying" beside the squad leader it is
  attacking.
- **A flier flew over the patrollers it had to get past**
  (`flown_over`), and each of those with anti-air deals its ATK to it:
  every ground patroller when it attacks something not patrolling, and the
  squad leader alone when it attacks another patroller, since patrollers
  of its own priority were never in its way (Sirlin, 2016-03-14). Where
  the attacker could have ignored the patrol zone without flying, no fly
  over happened and nothing shoots.
- **The tower is a detector and a gun** (UMR p. 9). On an opponent's turn
  it detects the first hidden attacker *the moment it attacks*, so
  `detected_by` reads an unspent detection as already seeing the
  attacker -- which is why a stealth attacker cannot sneak past a fresh
  tower -- and `declare_attack` spends it. It then deals 1 damage to
  every attacker it can see, which is anything not hidden and the one
  hidden thing it detected, whatever that attacker is attacking, and
  simultaneously with the rest of the combat damage, swift strike
  included. On its owner's own turn the detection is an action instead
  (`detect`, offered in `MainActionOptions.detect`), naming one hidden
  card of the opponent's for the rest of the turn. Both are once a turn,
  and `begin_turn` makes it new again. **A detection names a seat as
  well as a ref** (2026-10-16): a hero's ref is its slug, so in a mirror
  game at a table two opponents' copies of one hero share it, and were
  one candidate that, detected, showed both. `DetectOption.seats` gives
  each candidate's seat (on the wire only where there are several), the
  action takes `against` and refuses an ambiguous ref without it, as the
  levels' recipient does, and the tower keeps `detected_seat` beside
  `detected` -- written only while set, so a save from before matches
  the ref alone, as it did. `detected_by` takes the side the thing is
  on; every caller knows it.
- **The damage lands in two batches** (`codex.flow.combat._resolve`):
  swift strike's first, then everything else, with deaths taken between
  them, so a card destroyed by swift strike deals nothing back and two
  swift strikers are simultaneous. The tower's damage joins the first
  batch there is, which is what "simultaneously as the swift strike"
  means. Sparkshot's 1 and overpower's excess ride with the attacker's own
  damage. **Overpower's excess is what is left once the patroller is
  destroyed** -- its remaining HP *and* its armor -- so the patroller takes
  exactly what destroys it and the rest goes on (the author, 2026-10-08:
  "if the overpowering attacker destroys a patroller with armor, the
  excess damage goes to anything else it could attack"); Reaper's 6 into
  a 1/2 squad leader with armor 1 destroys it with 3 and carries 3; a building's damage is applied after the lines are said, since
  buildings deal nothing back and kill nobody.
- **Readiness does not exhaust, and attacks once a turn**, which is why
  `CardInstance` and `HeroState` gained `attacked_this_turn` (cleared when
  a turn begins, on both sides); `may_attack_with` is the one reading of
  whether something may attack, haste's "no arrival fatigue" among it.
  Frenzy X is in `attack_value`, on its controller's turn alone, and
  healing X in the upkeep.

### Which choices an attack asks, and which it does not

**An attack is one action with choices inside it.** Three of the keywords
ask something, and each is asked only where there is something to
choose -- one adjacent patroller is no question. So the attack stands
half-resolved on `MatchState.combat` (the attacker, the defender, what
has been chosen and the stage it waits at), `pending` reads that stage as
`OBLITERATE_CHOICE`, `SPARKSHOT_TARGET` or `OVERPOWER_TARGET`, and the
answer carries the attack on from exactly there. The journal records the
whole attack as the one action it is, which is why a stop may not cut it
in two (`GameService`, above).

| Asked | When | What |
| --- | --- | --- |
| `OBLITERATE_CHOICE` | two or more of the defending player's units are equally the lowest tech | which one obliterate takes, once per point of X, and a new defender (`CHOOSE_DEFENDER` again) where obliterate took the first |
| `SPARKSHOT_TARGET` | both slots beside the one attacked are filled | which neighbour takes the 1 damage -- once per instance of sparkshot, so a stacked one may put both on one neighbour or one on each |
| `OVERPOWER_TARGET` | more than one thing could take the excess | where it goes -- the other patrollers it could have attacked, or anything of theirs with HP where there are none |

Not asked: whether to use flying, stealth, invisibility or unstoppable
(they widen what may be attacked, and the choice is the defender); which
anti-air patrollers shoot (every one flown over); whether the tower
detects on the defender's turn (it does, the first time it can); the
order of the damage (swift strike's is the rule, not a choice). The
attack preview the step's prompt set aside -- what would happen if this
attacker took that defender -- is **not built**: the board shows the
position.

**Once an attack has begun it cannot be taken back.** **Cancel** under
the defender buttons is still there for a misclick on the attacker, since
nothing has happened then; after the defender is chosen, obliterate may
have destroyed something and the tower may have spent its detection, so
`cancel_attack` refuses while `MatchState.combat` stands.

### Targeting and the effects

Step 6 is everything with text that is not a keyword. **The text is
data, the handlers are the flow's**: `codex.effects.EFFECTS` holds each
spell's, trigger's and ability's text as its parts, each part naming
what it may choose (`Part.choose`, a filter the engine answers) and what
it does (`Part.does`, a handler in `codex.flow.resolve.DOES`), beside
the sentence it was built from; `TEXT` says which card has which and
when -- `play`, `arrives`, `attacks`, `ability` -- a hero's keyed by the
band that prints it and read the way its keywords are (Troq's attacks
trigger from 5, River's ability from 3; `printing_band` reads the key
back, so Troq's base damage is said as his "middle level band's
ability" -- `band_name`, "first level", "middle level" or "max level" by
where the band is on the
card -- the author, 2026-10-10); and the static texts are a
handful of small tables the engine asks (`GUIDES`, `MAESTROS`,
`GRANTS_SWIFT_STRIKE`, `TECH_0_DISCOUNT`, ...).

- **An effect is a frame on `MatchState.resolving`**, worked part by
  part until a part has a choice to ask or the stack is empty -- the
  shape an attack's choices have on `MatchState.combat`, for the same
  reason: the journal records the cast as one action, and a restart
  between two clicks asks the same question. Frames run oldest first,
  so a spell's frame goes in before the Dancer each Harmony owes for it
  and Bloom has completely resolved before its Dancer exists (Harmony's
  ruling). An effect's frame names what it is, who controls it, the card
  it comes from and the spell being cast, which goes to the discard, into
  play (an ongoing spell) or to Appel Stomp's question when its parts
  are done.
- **A target is chosen as its part resolves**, never all at once
  (Final Smash's ruling), and **asked only where there is a choice**: a
  part with one thing it could choose takes it, and a part with nothing
  is skipped and said nothing about -- "do as much as you can". A spell
  is playable when one of its parts can resolve, and refused with "no
  target" when none can.
- **A target is on either side of the table**, so an answer names it
  `"<seat>:<ref>"` (`2:unit:7`, `1:base`) -- a hero and a building are not
  unique by ref alone. Every effect may choose what its text allows,
  your own things included: Wrecking Ball may hit your own base, Brick
  Thief may repair an opponent's building, Hired Stomper may hit itself
  ("mandatory, own units and itself included").
- **A repair offers what it can mend, your own first**
  (`RulesEngine._repair_candidates`; the author, 2026-10-15: "should
  only offer valid repair targets"). The damaged buildings alone are
  offered. Brick Thief's ruling makes an undamaged building a legal
  choice that does nothing, and the one use of that is not to mend an
  opponent's: so wherever any building on the table is undamaged
  (`RulesEngine.has_undamaged_building`), the question offers **Done**
  too, labelled **Repair nothing** on the panel
  (`resolve.may_repair_nothing`; the author, 2026-10-15: "it's
  effectively the same and is a lot clearer to the player", and "even
  when you can repair your own buildings, so long as there is at least
  one undamaged building somewhere"), rather than an undamaged building
  as a target -- and so a lone damaged building is asked about, never
  taken unasked (`least_picks`).
  Nothing damaged anywhere skips the part, said nothing about, as any
  part with nothing to choose. The candidates are listed
  **your side first** for a repair, where every other filter lists the
  opponent's first -- what a repair helps is yours, what a damage part
  hurts theirs. `RulesEngine.building_damaged` is the one reading of
  "damaged", Earthquake's too. **On the panel an opponent's target is
  red and your own blurple** (`build_target`, `build_divide`; the
  author, 2026-10-15), so whose a button is reads before its words.
- **`RulesEngine.target_rows` is the one reading of what may be
  chosen**: the filter's candidates, less an opponent's invisible card
  their tower has not detected (your own are always targetable, the
  invisible ruling), each with the **resist** choosing it costs -- left
  out where the player cannot pay it from what the spell left them, and
  paid as it is chosen -- and, **where an opposing flagbearer is among
  them and this cast has not yet targeted one, the flagbearers alone**.
  The flagbearer is checked per part, against what this cast has
  already taken (Final Smash's ruling, 2016-03-19), and one whose resist
  cannot be paid forces nothing (the flagbearer ruling). Your own
  flagbearer forces nothing. Only a part with the {target} symbol answers
  to resist and the flagbearer; Discord, which has none, takes every one
  of the opponent's tech 0 and I units.
- **The abilities are actions** (`MAIN_ACTION`'s `ability`, offered in
  `MainActionOptions.abilities` with why each may not be used): River's
  sideline from level 3, Maestro's damage on each Virtuoso, and
  Harmony's "stop the music". An exhaust is a cost, so it needs the card
  held since the turn began or haste (Maestro's ruling; arrival
  fatigue); a sacrifice is not, so Harmony may stop the music the turn
  it arrives.
- **Arrives and attacks triggers** go on the stack when the unit is
  played and when it attacks. An attack resolves its attacker's
  triggers after the defender is chosen -- and after obliterate -- and
  before the damage (`TRIGGERS` among combat's stages), once, and where
  one destroyed the defender the attacker chooses again, as after
  obliterate. Troq's 1 to the base can end the game before the damage.
- **A spell or an ability may be taken back while it asks a target**
  (the author, 2026-10-08): `TARGET`'s `cancel`, offered where
  `TargetOptions.cancellable` says. A cancel does not unpick the cast by
  hand -- a part may already have resolved unasked, a resist been paid,
  a card destroyed -- it **replays the turn** from its snapshot up to
  the action that played it (`history.replay`, the frame's
  `cancel_from`), so everything comes back exactly: the gold, the card to
  its place in the hand, the exhausted card readied. A tech choice the
  other player saved meanwhile is replayed after, since it is theirs.
  Neither the cancel nor what it took back stays in the journal or the
  event log, so a later replay of the turn is still byte for byte. Two
  things are not cancelled: a trigger, which is no choice and must
  resolve; and a cast that has drawn its caster a card (Appel Stomp),
  since a card seen cannot be unseen -- the reason an undo deals the
  same cards.

**What happens to a card is `codex.flow.board`'s, whoever did it**, so a
unit The Boot destroys dies exactly as one destroyed in combat does -- to
its owner's discard, with the scavenger's gold or the technician's card
(The Boot's ruling) -- and a hero killed by Wither gives the kill's two
levels as a combat kill does. **`settle` is the position's own
consequences**, run after every part and after combat: a unit or hero at
0 HP or with damage equal to its HP is destroyed, through armor (Discord's
and Wither's rulings); a channeling spell whose controller has no hero of
its spec is sacrificed, without Harmony's flip (Harmony's ruling); Two
Step is sacrificed once a partner has left play or its controller's
control.

- **A grant is in effect exactly while its card is in play under its
  controller** (Blademaster's ruling), so it is never stored: the engine
  reads it off the position each time it is asked. `body_keywords(body,
  match)` adds Blademaster's swift strike and Nimble Fencer's haste for
  Virtuosos (herself included) to what a card prints, and
  `unit_stats(card, match)` adds each Grounded Guide's +1 ATK or +2/+1
  (stacking), Two Step's +2/+2 while both partners are held, and
  Star-Crossed Starlet's +1 ATK per damage. **Both take the match**: a
  caller that leaves it out gets the printed card. A grant that ends can
  kill -- a Virtuoso holding damage on a Guide's +1 HP -- which `settle`
  takes.
- **A this-turn effect is a modifier** on the card or hero
  (`{kind, amount, until}`): Intimidate's -4 ATK, Discord's -2/-1, and
  Sneaky Pig's stealth as `{kind: "keyword"}`, all removed by the turn's
  end on both sides. ATK is floored at 0 once everything is added, the
  elite's +1 and frenzy included (Intimidate's ruling).
- **The costs**: `effective_cost` gives a Maestro's controller their
  Virtuosos for 0 and River at 5 her controller's tech 0 units for 1 less,
  never below 0 (River's ruling) -- so Blademaster, a Virtuoso, is free
  beside a Maestro.
- **Tokens** are units with no card behind them: summoned into play,
  trashed when they leave it, never in a hand, a deck or a discard pile.
  Harmony's Dancer is limited to three -- **counted across both faces**,
  Dancers and Angry Dancers: "the same card but flipped" (the author,
  2026-10-08) -- and
  "stop the music" flips each Dancer its player controls by changing its
  slug to the Angry Dancer's (`flipped` set), its runes and damage kept and
  nothing arriving (the Dancer ruling).
- **Two Step's partners are its `attached`**, chosen as two `TARGET`
  parts among its controller's units not already partnered (Two Step's
  ruling). **It is played only with two partners to choose**
  (`Effect.whole`): "Sacrifice this spell if either partner leaves play or
  leaves your control" (UMR p. 22, the Card FAQ) speaks of a Two Step that
  has both (the author, 2026-10-08). It is the one effect that does not
  "do as much as it can" (UMR p. 16): **a card's own entry in the Card
  FAQ wins over a general rule** (the author, 2026-10-08), as a specific
  rule does over a general one.
- **Two readings the rulebook settles** (UMR v1.3, read card by card
  against the database on 2026-10-08): a building under construction
  can't be dealt damage the turn it was started (p. 8; p. 9 for
  add-ons), so it is not offered to Wrecking Ball, Brick Thief's damage,
  Trojan Duck or Maestro's ability; and a hero's kill gives two levels
  only "when you destroy an *opponent's* hero" (p. 10) -- a hero killed by
  its own controller's spell gives nobody levels (`board.destroy`'s
  `cause`).
- **The upkeep order is asked only where it changes something**: healing
  and Star-Crossed Starlet's damage both due, so healing her first or
  after decides whether she survives (Starlet's ruling). `begin_turn`
  then stops in the upkeep with an `UPKEEP_ORDER` frame on the stack, and
  the answer runs the effects in that order and opens the main phase.
  The answer is journalled like any action where the turn's snapshot is
  its hand-over (a turn that opened on its tech), so an undo to the
  turn's start runs the upkeep again and asks the order again; where
  the snapshot is the main phase's opening, after the upkeep, it never
  does. The surplus's card is drawn first, since nothing it does is
  ordered against the others.

Every line is the model's, with tokens: "{card:spark} deals 1 to
{player:2}'s {card:iron_man}", "{player:1} pays {gold:1} for its resist",
"{card:harmony} summons a {card:dancer} token for {player:2}". A card
drawn is a count, never a name -- Appel Stomp's draw, the surplus's -- and
a card returned to a hand is named, since it was in play.

### Red and green

Step 11 made every red and green card, hero and token do what it says,
in five commits -- the keywords, the costs and resources, the spells,
triggers and abilities, the static grants and printed overrides, and the
upkeep, the end of the turn and the tokens -- `UNIMPLEMENTED` shrinking
in each and empty at the end. The General rulings of the keywords it
added are pinned in `tests/test_codex_keywords.py` (fourteen), and every
ruling on the pair's cards and heroes in `tests/test_codex_card_rulings.py`
(101: 88 on the cards, 13 on the heroes), each test's docstring the
ruling's own words and a ratchet counting them.

- **The keywords added**: deathtouch (one damage that lands destroys --
  so `lethal_damage` is 1, and overpower or Stampede carries the rest on,
  UMR p. 18), long-range (no damage
  back from the defender, `damage_back`), ephemeral (dies at the end of
  any turn), untargetable (out of `target_rows`, never out of combat),
  boost X (below) and channeling. `read_keywords` reads a line of
  keywords joined by commas whole -- "Flying, haste, long-range, resist 2"
  -- and a line with anything else in it as nothing, so a sentence is
  never half-read. **What stacks** is unchanged from step 5: resist,
  frenzy, obliterate and armor add up, a keyword with no number does not.
  A keyword a card has only while the position says so -- Tiny
  Basilisk's against tech 0, Stalking Tiger's stealth on its own turn,
  Midori's flying at 8, Mimic's -- is the engine's `_conditioned_keywords`,
  never a saved modifier.
- **Boost** is offered beside a card's play, as `PlayableCard.boost` with
  its own why-not; a boosted play is one more argument on the same
  action (`play`, `boost=True`), the frame carries `boosted`, and a part
  marked `when="boosted"` or a mode choice reads it. A card put into play
  by something else (Feral Strike, Sanatorium, Cinderblast Dragon's free
  spell) is never boosted: boost is paid "when you play this".
- **The printed override and the order of grants.** What a card is
  before anything grants it something is its `printed` dict -- Chaos
  Mirror's swapped ATK, Polymorph: Squirrel (a 1/1 green Squirrel with no
  abilities, its runes, damage and attachments kept), Mimic's copy. A
  card's numbers and keywords are then a `Profile` built from that base,
  with every grant applied **in the order it began to apply**: a grant's
  time is the later of its source's and the unit's own `sequence`
  (`MatchState.next_sequence`, given out as anything enters play, and to
  a hero's band as it is reached), and on a tie "has no abilities" goes
  first -- so Master Midori's "units with no abilities get +1/+1" is lost
  by a unit given an ability after it, and kept by one given it before
  (the FAQ's Behind the Ferns and Midori examples).
- **Control that returns.** Kidnapping sets `returns_to` on the unit
  it steals; the end of that turn gives it back where it is still in
  play (its ruling). Dothram Horselord changes sides at his controller's
  upkeep to whoever has the greater total ATK (units and heroes, him
  included), which overrides an older one-time steal ("newer triggers
  beat older triggers", his ruling).
- **The coin in the journal.** Rickety Mine's flip is `engine.flip_coin`,
  drawn from `rng` and recorded in `StepResult.drawn` as
  `["@coin", side]` beside the shuffles, so a replayed journal lands the
  same side byte for byte (`test_rickety_mines_coin_is_replayed_byte_for_byte`).
- **The trash** is out of the game: in no pile and no count, never a
  death (`board.trash`). A trashed worker is a count down
  (`trash_worker`), so Land Octopus's two workers and a hire's card are
  never named. A **sacrificed unit dies**, though -- the rulebook's
  "Dies" covers it, as the author confirmed on 2026-10-09 -- so its dies
  triggers and Bloodburn's rune fire.
- **The end of the turn**, after the draw and before the buildings
  finish (`turn.end_of_turn`), on both sides, in this order: every
  ephemeral unit dies; Bloodrage Ogre returns to its owner's hand where
  it neither arrived nor attacked this turn, on its controller's turn
  alone; Chameleon Lizzo returns at the end of any turn; Bloodlust's 1
  damage; a kidnapped unit goes back. What that sets off resolves before
  the tech choice is asked. This turn's modifiers, armor and Chaos
  Mirror's swap go in `begin_tech`; Polymorph and Ferocity last until
  their caster's next upkeep.
- **"Your units get" is continuous** (the author, 2026-10-09). Stampede
  and Ferocity are not snapshots of the units in play when they resolve:
  each is an entry on its caster's side (`PlayerState.lasting`), and the
  engine reads it for every unit that side controls while it lasts -- a
  unit arriving later that turn has Stampede's +3 ATK and its excess to
  the base, or Ferocity's armor piercing and swift strike, and a unit
  taken from that side loses them. Stampede's +3 armor is the one part
  spent as it is hit, so it is granted as each unit comes under the side
  (`board.lasting_armor`) rather than read. Stampede's entry goes in
  `begin_tech`, Ferocity's at its caster's next upkeep.
- **The tokens' limits.** A token carries a limit only where its card
  prints one: Harmony's Dancers (3, the Angry Dancers and a polymorphed
  Dancer counted, a stolen one taking a side past it) and Bloodburn's
  blood runes (4). Every other token -- Squirrels, Hunters, the borrowed
  Shark and Water Elemental (`BORROWED_TOKENS`, landed beside the pair)
  -- is unbounded.
- **The two prompt kinds.** `DIVIDE_DAMAGE` places divided damage a
  point a click, the split saved on the frame, Hotter Fire's +1 added
  once to the total; `MODE_CHOICE` asks a "choose one" -- never when
  boosted. Both are buttons on the panel. A `TARGET` over the asked
  player's own hand or codex (Sanatorium, Feral Strike, Cinderblast
  Dragon, Calamandra's discard) is pictured to them alone
  (`private_choices`); the cog test holds none of it reaches the channel,
  and Feral Strike's fetch is named because the card says "reveal them".
- **Which upkeep orders are asked.** The upkeep is a frame on the stack
  (`upkeep_order`, with `due` and `ordered`, an older frame without them
  recomputed). A gain -- the surplus's draw, Gemscout Owl's gold,
  Galina's -- changes nothing about the rest and is run, not asked. The
  order is asked only where it decides something: healing beside
  Star-Crossed Starlet, and Dothram beside a death or a sacrifice
  (Starlet's damage, Land Octopus's choice), since his side follows the
  total ATK. Land Octopus's own choice is a `MODE_CHOICE`, asked even
  alone, and only "workers" where two can be trashed.
- **Hotter Fire** is `engine.damage_bonus`, read off the frame's
  `origin` -- the red card the effect came from, Rickety Mine's tails
  among them -- and never combat damage. A dies line Pirate-Gang
  Commander grants is the dying unit's, so it gets the +1 only where that
  unit is red (the author, 2026-10-09).
- **Read as the author answered** (2026-10-09): Dothram's total ATK
  counts heroes as well as units; Feral Strike boosted fetches before it
  puts into play, so a unit just fetched may go into play in the same
  cast.
- **A position settles whenever the stack empties**, not only when a
  frame finishes, so a second copy of a legendary unit played with
  nothing to resolve -- a second Galina -- is destroyed on arrival.

### Purple and black

Step 12 made every purple (the Vortoss Conclave: Past, Present, Future)
and black (the Blackhand Scourge: Demonology, Disease, Necromancy) card,
hero and token do what it says, in six commits -- the colours landed for
their numbers, time and the keywords, the forms of death, black's
effects, purple's, and the upkeep, the extra turn and the tokens --
`UNIMPLEMENTED` filled by the first and empty at the last, which
`tests/test_codex_effects.py` now asserts. The General rulings of the
three keywords it added are pinned in `tests/test_codex_keywords.py`
(ten), and every ruling on the pair's cards and heroes in
`tests/test_codex_card_rulings.py` (122: 107 on the cards, 15 on the
heroes), each test's docstring the ruling's own words and a ratchet
counting them. The Forecast X ruling about three time runes and the
Two Lives, Illusion and Entangling Vines rulings name cards of colours
not yet landed: each is pinned for the part that is purple's or
black's, and the rest waits for step 13.

- **Time and the future** (UMR p. 17). A time rune is a count on a card
  (`time_runes`) or a hero (Prynn). **Fading X** puts X on a card as it
  arrives and takes one off at each of its controller's upkeeps; the last
  one gone, the card is sacrificed (`board.remove_time_rune`, which also
  carries Rememberer, always sacrificed first). **Forecast X** never
  plays a card into play: `board.to_future` puts it in its player's
  `future` with X runes and its id, and the last rune gone it arrives
  (`arrive_from_future`) -- a unit with arrival fatigue and its arrives
  trigger, needing nothing it needed to be played, so it arrives even
  after its tech building is destroyed (the ruling, and
  `test_a_forecast_unit_arrives_with_its_triggers_after_its_building_is_gone`);
  a spell resolves. A card in the future is untargetable and unaffected
  by everything but what names time runes -- Time Spiral, Temporal
  Research's count -- and is addressed `future:<id>`. The board draws it
  greyed after the units, its rune chit on it.
- **The forms of death.** *Destroyed*, *sacrificed* and *dies* stay one
  path (`board.destroy`, with `forced` for a sacrifice and `combat` for
  combat damage), and three things stand in its way, in this order:
  **Soul Stone** saves first (its damage removed, the stones sacrificed,
  nothing that pays on a death paying), then **indestructible**
  (`board.spare`: exhausted, its damage gone, the cards attached to it
  discarded, its runes kept, and never sacrificed at all), then **can't
  leave play** (Gilded Glaxx while its controller has gold). **Disable**
  (UMR p. 16) exhausts and sidelines a card and keeps it from readying
  at its next ready phase (`disabled`, cleared there). Rune damage --
  Plague Spitter's -1/-1 runes -- is still combat damage for anything
  that asks (its ruling). Blackhand Dozer's base damage has a floor
  (`damage_base(by=)`).
- **The graveyard.** The discard is a pile, as before; Black's
  **Graveyard** building keeps `buried` entries, each `{slug, owner}`,
  addressed `buried:<id>:<n>`, its limit read off the card, and the
  board counts them on its card ("Buried 3"). Playing a buried unit is
  `why_not_play_buried`; Vir's top-of-deck play `why_not_play_top`. A
  buried unit with Boost may be played boosted, its boost paid on top
  (the Graveyard says "play", and the boost ruling lets a played card be
  boosted): after the pick a `MODE_CHOICE` asks "play it" or "play it
  boosted", the second disabled where the unit has no boost or the gold
  does not cover both (the author, 2026-10-10: "boost applies when you
  'play' a card and that's what graveyard does").
- **The weakest** (UMR p. 18) is `engine.weakest`: the lowest tech unit
  with the least ATK, passing over what the effect cannot take -- one
  that can't be sacrificed, or, to destroy, one that is indestructible or
  can't leave play -- and whoever resolves the effect chooses among the
  tied -- Sacrifice the Weak's caster for both sides. `lowest_tech` is
  Death Rites' and the Dozer's.
- **A decision the active player cannot make.** On an opponent's turn
  an effect that asks a decision does not resolve (UMR p. 14), so a
  "Max level:" text reached there that chooses is lost
  (`board.max_level_reached`); a choice that is the opponent's own --
  Banefire Golem's sacrifice, Carrion Curse's discards -- is asked of
  whoever the card says. **A look at hidden cards** (Carrion Curse's at
  the opponent's hand, Vir's at the top of the deck, the discard) is a
  `TARGET` whose `shown` lists everything seen and whose rows are what
  may be picked; `private_choices` pictures `shown` to the asker alone,
  and `tests/test_codex_cog_turn.py`'s `CarrionCurseTests` holds that
  the channel hears none of it until a card is discarded.
- **The extra turn.** Double Time appends its caster to
  `MatchState.extra_turns`; `begin_tech` gives the next turn to the
  first seat waiting there instead of the other player -- and, in a
  free-for-all, ahead of a playoff ("Multiplayer") -- so two Double
  Times are two extra turns, three turns in a row (its ruling). The
  tech choice in an extra turn is the standing prompt as in any turn,
  asked in the ready phase and confirmed there.
- **The debt.** Promise of Payment sets `promised`; the next card
  played that turn -- from hand, from a Graveyard, off the deck with Vir,
  or a spell another card casts in between -- costs 0, and its printed
  gold cost becomes `debt` (`actions.spend_promise`): never reduced by
  anything and never the boost, which is still paid. A hire, a build or
  an ability is not playing a card. The debt is paid in the upkeep, after
  the workers' gold, in the order the active player chooses among the
  upkeep's effects -- asked wherever anything else is due beside it (the
  author, 2026-10-10: "upkeep abilities can be done in any order
  according to the active player's choice"); unpaid, the game is lost
  -- `lost_by_debt`, GAME_OVER's third way beside a destroyed base and a
  concession. A promise spent on nothing is cleared in `begin_tech`.
- **The upkeep's new items**, in the order the active player asks
  where it decides something: fading (cards and Prynn), forecast, Doom,
  Banefire Golem (asked beside Plague Lord, since its sacrifice may
  change Plague Lord's count), Plague Lord (every -1/-1 rune on either
  side, during its controller's upkeep alone, its own base included),
  the Shrine of Forbidden Knowledge's damage, and the debt, ordered
  against all of them.
  Yesterday's Golgort counts combat damage to a building alone, dealt by
  any of its controller's units or heroes (its ruling; the card's
  wording, as the author confirmed on 2026-10-10).
- **The subtypes and the colour are rules.** Demons (`is_demon`), Buffs
  and Debuffs (`BUFF_SUBTYPES`, which Vandy's Sentries and the
  untargetable-by-buffs readings ask) and a card's colour (`color_of`,
  for black invisibility and the Graveyard) are read off the catalog
  and the printed override, never off a name. Metamorphosis turns heroes
  into Demons by a modifier; Skeletons are black tokens; Second
  Chances' "choose randomly" is `engine.pick`, journalled as
  `["@pick", slug]` beside the coin and the shuffles, so a replay returns
  the same unit (`test_second_chances_random_return_is_replayed_byte_for_byte`).
- **As the author answered** (2026-10-10): Blackhand Resurrector
  summons a hero that still has summoning runes, but never past the
  hero limit -- a dead hero is no target while the side is at it; Soul
  Stone applies before indestructible; Rememberer is always the first
  sacrificed; a token Max Geiger trashes comes back like any unit;
  Yesterday's Golgort counts combat damage alone; the upkeep's effects,
  Promise of Payment's debt among them, go in the active player's order;
  a unit played from the Graveyard may be boosted;
  Carrion Curse shows the hand even where nothing in it may be
  discarded.

### White and blue

Step 13 made every white (the Whitestar Order: Discipline, Ninjutsu,
Strength) and blue (the Flagstone Dominion: Law, Peace, Truth) card,
hero and token do what it says, in six commits -- the colours landed for
their numbers, the keywords and the copies, the zones and the rules a
player is put under, white's effects, blue's, and the last of the tables
-- and after it every printed card plays and the lobby offers all twenty
heroes. `UNIMPLEMENTED` is empty for good: `tests/test_codex_effects.py`
asserts it over every card the data holds, and that the seven sets add
up to the whole catalog but for the two worker counters and the
Mercenary token, which no card summons and which has no text. The
General rulings of the keywords it added -- illusion, stash, arrival
fatigue, detector, flagbearer -- are pinned in
`tests/test_codex_keywords.py`, whose tables now cover the whole General
group; the 92 rulings on the pair's cards and heroes (79 and 13) in
`tests/test_codex_card_rulings.py`, whose ratchet now counts every
ruling the data holds on a card, a hero or a token (343), so a
re-import that adds one fails loudly.

- **The illusion and the copy.** An Illusion is read off the subtype
  (`RulesEngine.is_illusion`) or an `illusion` modifier -- Hallucination's
  this turn, a Quince copy's for good -- and dies the moment it is
  targeted, before the rest of the effect (`resolve._targeted_away`, with
  Smoker's return to the hand beside it). A **copy** is
  `CardInstance.copy_of`: the copied card's slug, read wherever the
  engine asks what a card *is* (`text_slug`, `card_of`, `tech_level`) --
  the printed card, its printed override read first and none of its
  runes, attachments or modifiers, and nothing arrives (the copy
  rulings). Manufactured Truth's ends with the turn, a `copy` modifier
  keeping what the card was; Quince's middle ability trashes its copy at
  the end of the turn, once; his max level's copy is trashed when he or
  its original leaves (`board.settle`). A Mirror Illusion that copies
  something is no longer a "Mirror Illusion" for his abilities, and still
  counts to his limit of two (his rulings).
- **The jail.** A unit its opponent's Jail catches goes from the hand
  to the Jail's `jailed` slot -- `{slug, owner, boosted}`, not in play
  and not arriving -- and is released, arriving then, boost and all,
  when the next one takes its place; it is discarded with the Jail.
  Forecast units never go there (the jail rulings).
- **The rules a player is put under** are reasons a card may not be
  played, read in `why_not_playable` so the panel and the refusal say
  the same: Censorship Council's one card a turn from the hand (a "put
  into play" is no play), Reputable Newsman's `number` (the spells and
  upgrades of that printed cost), Oathkeeper's `oath` (no card from the hand
  but workers, or no draw/discard phase, while he is in play) and Building
  Inspector's surcharge on the first building of a turn
  (`built_this_turn`). **The silence** is `PlayerState.silenced`: Free
  Speech's, until after that player's next turn; their heroes cast no
  spells, lose their band texts and keywords, and one summoned or levelled
  meanwhile arrives with nothing (its rulings).
- **The stash.** Bigby's keyword: at the draw phase the `STASH` prompt
  asks whether to keep a card, the hand's cards as its options; one kept
  is one fewer drawn, so the hand ends the size it would have without
  it. The kept card is pictured to its owner alone and never named.
- **The one standing reveal.** Eyes of the Chancellor's "Opponents play
  with their hands revealed" is `RulesEngine.hands_visible_to(match,
  seat)`: the hands `seat` sees. The cog pictures them on that player's
  own panel and hand message (`revealed_files`), never in the channel,
  and `tests/test_codex_cog_turn.py` holds that the channel hears
  nothing. A look -- Martial Mastery's, Lawful Search's, Community
  Service's -- is a `TARGET` whose `shown` is the pile, as Carrion
  Curse's was, asked even with nothing to pick; Flagstone Spy's look,
  which no prompt carries, stands on its player's panel for the rest of
  the turn (`looked_hand`).
- **The attack that costs gold.** Morningstar Pass and Setsuki while
  she does not patrol: `attack_toll` names the gold, the defenders a
  player cannot pay for are not offered, and `declare_attack` charges it.
- **The base that flies.** Lawbringer Gryphon: the base is attacked as
  a flier is, only by fliers and anti-air (`may_be_attacked`).
- **Two Birds, however many Nests.** Bird's Nest summons Birds up to two
  in all, whether it is played or re-summons at its upkeep: each Nest
  sees the Birds in play and puts none past the limit (its ruling). The
  author settled it on 2026-10-10 over the Card FAQ, which reads as a
  second Nest summoning two more: **where the database's rulings and the
  Card FAQ differ, the database governs.**
- **Prevention and doubling.** Morningstar Pass prevents all damage to
  its controller's other buildings, the base among them (the card calls
  it a building); Focus Master spends a rune on exactly lethal damage --
  1 of deathtouch's, never a patroller whose excess overpower or Stampede
  carries on; Doubling Barbarbarian doubles every gain of ATK, HP and
  armor, runes and the squad leader's included, never healing; Safe
  Attacking's armor is given per attack and taken back after it.
- **Control that follows a card.** Mind Control's unit is controlled by
  whoever controls the spell (Assimilate's ruling), and goes back to
  whoever had it before when the spell leaves play -- a
  `mind_controlled` modifier on the unit, worked in `board.settle`.
- **The building that is disabled.** Injunction disables a tech
  building through its owner's next turn: no card of its level, no
  building above it built, a tech III already standing untouched (its
  rulings).
- **The saved fields**, each with its fallback: on a card `copy_of`
  (`None`), `jailed` (`None`: the Jail's slot), `oath` (`None`) and
  `number` (`None`); on a hero `runes` (`{}`: Grave's sword and Two
  Lives' crumbling rune); on a side `silenced` (false),
  `played_from_hand` (0) and `built_this_turn` (false); and on a tech
  building `disabled` (false). The crumbling, focus, insurance and sword
  runes on a card are kinds in its `runes` (step 11's field); Insurance
  Agent remembers the unit he insured as an `insures` modifier, so a
  second rune is a marker and a copy insures nothing. The golden's final
  match was re-recorded for these keys alone, every one at its default;
  the transcript did not change.
- **As the author answered** (2026-10-10): Training Grounds levels one
  of its controller's heroes, never an opponent's; True Power of Storms
  may be played with fewer than two cards that cost 3, or discard just
  one, and then does nothing (its ruling: nothing is targeted);
  Jurisdiction's spell needs no hero of its spec.
- **Still open, built as the card reads** and listed in the PR: Reputable
  Newsman's number is compared with a card's printed cost, and Mind
  Control may be attached to any tech 0, I or II unit, its caster's own
  included.

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
  and hero carries `armor` (what is left of the squad leader's armor
  this turn, set when a turn begins), the hero its `patrol_slot`, and
  the match `attacking`. Each is in its table with its fallback.
- **Step 5 added four**, each with its fallback, since the save format is
  the contract: `attacked_this_turn` on a card and a hero (readiness
  attacks once a turn), `detected` on the add-on (what the tower has
  detected this turn; `detected_seat` beside it since 2026-10-16, written
  only while set), and `combat` on the match -- the attack standing
  half-resolved while a choice inside it is asked, so a restart between
  two clicks asks the same question.
- **Step 6 added four more**, each with its fallback: `plus_runes`,
  `minus_runes` and `modifiers` on the hero, since Bloom, Wither and
  Intimidate take a hero as readily as a unit, and `resolving` on the
  match -- the effects under way while a target, Appel Stomp's place or
  the upkeep's order is asked. It also put to use the three fields step 2
  laid down on a card: `modifiers`, `attached` (Two Step's partners) and
  `flipped` (an Angry Dancer, whose `slug` the flip changes). The combat
  dict gained a `triggered` key, read with a default, so an attack saved
  by step 5 goes on as it would have.
- **Step 8 added one**, `conceded` on the match (`None` where the game
  ended on a destroyed base, and in an older save), and five on the
  record, each read with a default: `final_message_id`,
  `rematch_game_id`, `rematch_of`, `rematch_specs` and `kept_heroes`
  ("The end of a game", below). The last two, and step 10's
  `rematch_decks`, went with **Keep heroes** on 2026-10-20: `from_dict`
  drops them from an older save, and a newer save never writes them,
  which an older checkout reads with its defaults.

- **Step 10 added five on a side and one on the add-on**, each with its
  fallback, and changed two keys' shape ("The standard game", below):
  `specs` (a list; an older save's `spec` read as a list of one),
  `heroes` (a list of hero states; an older save's `hero` read as a list
  of one), `deck_color` ("neutral"), `tech2_spec` (`None`) and
  `constructed_once` (false) on the player, and `spec` (`None`) on the
  add-on. On the record: `mode` ("basic"), `player_specs` as lists (a
  string read as a list of one), `player_decks` (every seated seat
  "neutral" where the key is missing) and `rematch_decks` beside
  `rematch_specs`.

- **Step 11 added thirteen**, each with its fallback: on a card `runes`
  (`{}`: blood, growth and feather runes beside the +1/+1 and -1/-1),
  `returns_to` (`None`: whom a stolen card goes back to), `attached_hero`
  (`None`: a hero Spirit of the Panda or Final Showdown is on), `printed`
  (`None`: the printed override) and `sequence` (0); on a hero `printed`
  (`None`) and `bands` (`{}`: when each band was reached); on a side
  `discards_at_main_end` (false, Desperation), `spells_played` (0),
  `peace` (false, Moment's Peace), `arrived_from_hand` (false, Drakk's
  first unit) and `lasting` (`[]`: Stampede and Ferocity on that side's
  units); and `sequence` (0) on the match. A save made before step 11
  reads every card and band as having entered at 0, so its grants apply
  in the order the ids give.

- **Step 12 added thirteen**, each with its fallback: on a hero
  `time_runes` (0), `disabled` (false) and `trashed` (`[]`: what Prynn's
  max level ability trashed, each `{slug, owner, controller, id}`,
  returned to play when she leaves it); on a card `time_runes` (0), `disabled`
  (false), `buried` (`[]`: a Graveyard's units, each `{slug, owner}`)
  and `made_by` (`None`: the card whose arrival summoned a token -- Terras
  Q's Warlocks shackle him alone); on a side `future`
  (`[]`: the forecast cards, saved as a card in play is), `skip_draw`
  (false, Prynn's fading), `promised` (false) and `debt` (0, Promise of
  Payment); and on the match `extra_turns` (`[]`, Double Time) and
  `lost_by_debt` (`None`). The golden's final match was re-recorded for
  these keys alone -- every one at its default, nothing else changed.

- **Step 13 added eight**, each with its fallback ("White and blue",
  above): on a card `copy_of`, `jailed`, `oath` and `number` (each
  `None`); on a hero `runes` (`{}`); on a side `silenced` (false),
  `played_from_hand` (0) and `built_this_turn` (false); and `disabled`
  (false) on a tech building. The golden's final match was re-recorded
  for these keys alone.

- **The thread and the in-place lobby added one on the record**, `venue`
  ("channel" where the key is missing or unknown): where the game is
  played ("The lobby and the channel", below).

- **The discard told added one on the side**, `discards_untold` (`[]`):
  the cards an effect discarded from that hand, each `{slug, by}`
  ("What the narration may say", below). The golden's final match was
  re-recorded for this key alone, at its default.

- **The lasting effects' tags added one key, not a field**: a modifier
  on a card or a hero, and an entry in a side's `lasting`, carries
  `from`, the slug of the card or hero whose effect left it -- stamped
  by `resolve.does`, the one call every part of an effect is done
  through, off the frame's `by` token, so no part's handler writes it.
  It is read by the board alone, for a tag's colour; nothing decides a
  rule by it. An older save's have none, and their tags are drawn on
  the plain purple. The golden's final match holds no modifier, and
  was left as it was.

### What the narration may say

Every line is in the model's voice with tokens -- `{player:1}`,
`{card:iron_man}`, `{hero:troq_bashar}`, `{gold:3}` -- and is public.
So a draw is a count ("discards 3 and draws 5"), a reshuffle is said
without the order, a hire never names the card trashed, and a tech
choice says nothing while it is made -- it is announced only in its
owner's ready phase, as a count of cards into the discard (the author,
2026-10-08: the other player has no reason to hear that it was picked). `test_nothing_hidden_is_said` in the full-game test
checks the hire and tech lines name no card. The event log holds card
identities (a hire's card among them) and stays in the save, which the
bot never exports (the author, 2026-10-07).

**A card an effect discards from a hand is a count in public and a name
to its owner** (the author, 2026-10-11: "it should let you know which
card was discarded at the start of your turn"). Thieving Imp, Cursed
Crow and Shadow Blade discard at random, and Carrion Curse's caster
chooses, so the owner either never saw which card went or saw only the
caster pick it; the channel hears "{player:1} discards a card at random
for {card:thieving_imp}" and no more. The card is kept on the side as
`PlayerState.discards_untold` (`{slug, by}`, `by` the effect's token)
and `pending` puts a line per card -- "{card:thieving_imp} made you
discard {card:argonaut}." -- on the prompt's `told` where the question
is the active player's own, so it reaches them on **every panel of
their own turn**, under the ask (`panel_caption`), and is emptied as
that turn ends (`begin_tech`) -- the author, 2026-10-11: "keep the note
for the whole turn instead". The first version spent it on the turn's
first answer, so it was said once; the author preferred it standing
through the turn. It is not on a question
asked of them during the opponent's turn: the ask was for their own.
It is state rather than a reading of the event log because the log
decides nothing; the turn-start snapshot holds it, so an undo or a
cancel, which rebuild the turn from its snapshot, bring it back with
the rest. Discards the player chooses themselves --
Calamandra's, a cost, Desperation's hand -- are not told: they know.

**Every line that moves a player's gold says why, and where it now
stands: "{gold:3} left" where it went down, "now {gold:5}" where it went
up** (the author, 2026-10-16). A spend ends on its own sentence --
"{player:1} plays {card:tenderfoot} 1/2 for {gold:1}. {gold:3} left." --
and a gain on its own clause -- "collects {gold:5} from 5 workers: now
{gold:5}", "gains {gold:1} from {card:gemscout_owl}: now {gold:4}", "collects
a bounty of {gold:1}: now {gold:2}". A steal says both sides: "{player:1}
steals {gold:1} from {player:2} and is now at {gold:4}; {player:2} has
{gold:0} left" (`stolen`, the whole clause). **A card's stats go with its
name and the price after them** -- "plays {card:tenderfoot} 1/2 for
{gold:1}", "summons {hero:river_montoya} 2/3 for {gold:2}" (never "level
1": a hero is always summoned at 1) -- so the line reads as what was bought
and then what it cost. A building or an upgrade card is named and no more
("plays {card:...} for {gold:3}."), what it is on the board. A level that reaches a new
band says what the band did, as the hero's own doing: "levels
{hero:river_montoya} to 3 for {gold:2}: they reach a new band, are now
3/4, and heal." -- `board.new_band`, on every level line, paid, a kill's
or an effect's; "they", since the cards carry no pronoun for their heroes
(the author, 2026-10-16). The
reason is never left to be inferred: resist is its own line naming what is
targeted and with what ("pays {gold:1} for resist to target {player:2}'s
{card:brick_thief} with {card:spark}. {gold:2} left." -- the author:
"resist for spells needs to be spelled out"), a repair says its price,
and Promise of Payment's debt says it is the debt. A line paying 0 says
no total (`gold_left` is empty for it), as a move that costs nothing says
nothing.

The wording is three helpers in `codex/flow/turn.py` -- `gold_left`,
`gold_now`, `stolen` -- called by each sentence that moves gold, since
the total belongs on the sentence that says why. A first version said
the total once, in the driver, on the end of an answer's last line,
which could not miss a spend but put the total on whatever line came
last ("{card:sneaky_pig} has stealth this turn. {gold:6} left.") and
said nothing for a gain at the upkeep. What it guarded against -- a way
of paying that forgets to say so -- is held instead by
`tests/test_codex_driver_full_game.py`: `play` asserts, for every action
of every whole game it plays (the duel, the standard games, each colour
pair, the free-for-alls, the dragons), that a seat whose gold changed
has its new total said as "left" or "now". The main phase's ask says
the seat's gold as well ("{player:1}'s main phase, currently {gold:5}."):
the lines above it may have scrolled away by the time the panel is read,
and the ask is re-read after every action, so it is always the total now
(the author, 2026-10-18; it was the seat's name alone from 2026-10-16).

**A line that damages a building or the base says where it now stands,
out of its most** ("deals 3 to {player:2}'s base, now at 17/20") -- an attack, overpower's
or Stampede's excess, a spell's, a trigger's or an ability's damage, a
destroyed building's 2 to its base ("deals 2 to their base, now at
18/20"), and a building card's damage ("deals 3, now at 1/4"). A line
whose damage destroys it says no count: the next line says it is
destroyed (the author, 2026-10-09; the "now at" wording 2026-10-10).
`board.left_after` is the one wording for a tech building and the
add-on, `base_left_after` for the base, asked before the damage lands, since
their damage in combat lands after the lines are said; `board.card_left`
is a building card's, asked after, since a card's damage lands first.
**Combat names a building as every other line does** (`board.named`):
"{player:2}'s Tech I building", and the add-on by its card,
"{player:2}'s {card:surplus}" -- never "add-on" (the author,
2026-10-10). The fighter takes its name when the fight begins, while the
add-on is still there to name.
**Healing and repair are said the same way.** The upkeep's healing names
its source and each card it healed, with where it now stands --
"{card:helpful_turtle}'s healing 1 heals {player:1}'s {hero:troq_bashar}
1, now at 4/4" -- and says nothing where nothing was damaged; a repair
ends "now at 4/5" (`board.now_at`) (the author, 2026-10-10).

### Naming by slug in the tests

`tests/codex_positions.py` stages a position by card slug --
`put(match, seat, "iron_man", patrol="elite", damage=1)`. D12 Ball's
tests name a player by role because its roster is data the author
revises; Codex's cards are fixed data imported whole at a pinned
commit, so a test says exactly the card it means.

## The reference commands

`/codex card <name>` answers with the card's picture and nothing else
(the author, 2026-10-08): the card already shows its
name, its cost, its numbers and its text. Two options, both off unless
asked for, add words **under** the picture -- `text:True` the name, the
type line, the cost and numbers (a hero's three bands) and the printed
text; `rulings:True` Sirlin's rulings with their authors and dates --
and the database's page under whichever is there, as plain text:
nothing in this bot is an embed (the author, 2026-10-07). Discord draws
a message's text above its attachment, so the words are a follow-up to
the picture's response, a second message that sits straight beneath it
(the author asked for the rulings below the picture, not above). Every
card has a picture in the tree; one missing from a checkout is answered
with the card's text whether or not that was asked for, since a lookup
that shows nothing answers nothing. The answer is ephemeral, the
asker's alone, and its follow-up with it; `public:True` posts both in
the channel instead (the author, 2026-10-09). `/codex rules <keyword>` answers
in the same shape (the author, 2026-10-12): the keyword and its reminder
text alone by default, `rulings:True` adding Sirlin's rulings as the
official rules they are, ephemeral unless `public:True`. A keyword with
no reminder text answers with its rulings whether or not they were asked
for, for the reason a card with no picture answers with its text.
Both autocomplete (over every card and hero, and over the `General`
group's keywords) and both fit Discord's 2000 characters by counting the
rulings that do not fit and leaving them to the link, measured after
the tokens are rendered. The bot serves no rulebook text and
`docs/living-rules.md` is not touched (worksheet decision 12); the
rulebook's PDF under `docs/codex/` is for the developers to read.

## The service and its file

`gamesaves/codex/` is D12 Ball's two modules copied (decision 2):
`storage.py` writes `data/codex_games.json` -- the temporary file
renamed over the real one, never raising, the two per-file failure
flags, all `gamekit.storage`'s since step 9 -- with no legacy migration, since the save format has been the
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

**`/codex create_game` opens the game's channel and posts the lobby in it**
(the author, 2026-10-08, on trying step 3: the lobby belongs in the
channel the game is played in). The command was `/codex lobby` until the
author renamed it `/codex create_game`, 2026-10-10 (by way of
`/codex start_game` the same day, never released); the cog's method is
still `lobby`, since `start_game` is the lobby's **Start**. The worksheet's decision 10 had it
posted where the command is typed; the author's later word governs.
The channel is `codex-<n>` under **Codex Games**, created if missing,
and open to the whole server -- anyone can look in, talk and take a
seat -- as D12 Ball's lobby channels are; the person who typed the
command is told where it is, privately.

**Where the bot may not make a channel, the game is played in a thread;
where it may make neither, in the channel the command was typed in**
(the author, 2026-10-10). `open_game_place` tries the three in turn:
the channel under Codex Games; a public thread named `codex-<n>` in the
typed-in channel (a week's auto-archive, the longest, since a post
wakes it anyway); and that channel itself. A place made whose lobby
cannot be posted is deleted and the next tried. The record says which it
is, `venue` -- "channel", "thread" or "here" (`codex.game.VENUES`;
"channel" in an older save) -- since what is done to the place depends
on whose it is: a thread is the bot's, renamed at Start and archived at
the end, a rematch taking it out of the archive, and so does **any click or
`/codex` command on an open game or lobby** in a thread Discord archived
after a week idle (the author, 2026-10-10; `wake_thread`, called from
`SafeView.interaction_check` and the cog's own, which discord.py runs
before every slash command -- one request, before the answer, only while
the thread is archived), since a message in an archived thread cannot
be edited; a channel the game was only opened in is not, and is never renamed or moved. Any failure to
make the channel falls through, not only a refused permission -- a full
category is as much a reason to use a thread. **A channel holds one game
at a time**: the third place is refused while a Codex game or lobby is
open in it (`open_game_for_channel`), since every command finds its game
by the channel it is typed in. Nowhere to post opens no lobby, and the
asker is told what the first two places need (Manage Channels, Create
Public Threads). The pins in a thread or a borrowed channel need Manage
Messages there; a pin refused is logged and the game goes on, as past
the pin cap.

The lobby is a line per seat and, since step 10,
**Basic game** / **Standard game**, **Leave**, **Start**, a menu of the
heroes or the colours' decks and **Mixed colors** ("The standard
game", below) -- **Play
Bashing** and **Play Finesse** until then -- persistent (fixed custom ids
carrying the game id), re-armed on startup. A seat taken or given up
edits the lobby in place through the click's own response, which
spends nothing from the channel's edit bucket. Start is either seated
player's, or a game helper's -- the lobby asks no confirmation, as
D12 Ball's does not.

**A test game seats one person on both sides** (`/codex create_game
test_game:True`, the author, 2026-10-08), as D12 Ball's test games do.
The record's rules are what change: `take_seat` sits a person already
seated down on the other side too rather than moving them, `leave`
frees both seats, and `seats_of` reads both. A click acts for
`seat_for(user, active)` -- the seat whose turn it is, where the clicker
holds it -- so **My hand**, **Codex** and `/codex hand` show the side
that is playing, and their captions name it. Nothing is hidden from one
person playing both hands, so nothing more is needed. The tech choice
is the one thing a test game plays differently: each side's is chosen
in its own ready phase, from My hand, and nothing stands during the
other side's turn ("The standing prompt", above). On Discord the Lock
closes the panel with "Patrol locked: Bashing's turn is over. **My
hand** opens Finesse's turn, its tech choice first." -- the sides named
by their teams (`team_name`: "Blackhand Scourge", "Feral/Fire/Bashing"),
since both are the one person -- and sends no picker
(on the webhook, the defer and the panel clicked edited to that line),
**Tech** says where
the choice is made, and Save tech in the ready phase turns the panel
into the turn's actions, the turn message edited.

**Start turns that channel into the game's**, in one edit: renamed
`codex-<n>-<p1>-vs-<p2>` (capped at 100 characters), its permissions
left as the lobby's -- a thread renamed the same way, a channel the game
was only opened in left alone. The service deals and runs the
first turn's ready phase and upkeep in one save, the lobby is edited
once to say the game has started, its buttons gone, and the first
turn's message goes up under it. The categories are the Codex
bot's own -- **Codex Games** and **Codex Archive** -- not PBD's, whose
names `/debug`'s reset and the pin rollover match and whose
fifty-channel cap is D12 Ball's.

- **Anyone in the server may read the channel and talk in it**, from
  the lobby to the end (question 8 of the worksheet, and the author on
  2026-10-08: watchers may post). The hands are ephemeral, so a watcher
  sees the table and nothing more. Unlike D12 Ball's, whose started
  games are hidden from `@everyone`, nothing changes the channel's
  permissions at Start.
- **fool-bot's hub points at the lobby** the one way Discord allows
  across applications, a command mention (decision 10): `codexbot.py`
  writes its top-level command ids to `data/codex_command_ids.json`
  after each sync -- or, on a start that skipped the sync, once from a
  fetch when the file is missing -- and `codex_lobby_mention` reads it
  for `</codex create_game:ID>`, falling back to the command's name in plain
  text. It is the one file read across the line, and fool-bot only
  reads it. The mention is the button's reply, below, and not in the
  message: the hub's Codex block is a general description of the game,
  as the D12 Ball block is, and names neither the decks the bot plays
  nor a command (the author, 2026-10-08 -- the button is how you learn
  the command). `build_hub_message` reads nothing for it.
  Its heading carries the Codex medallion as **fool-bot's own**
  application emoji, `codex` (`CODEX_HUB_EMOJI_NAME`), uploaded from
  `codex/images/emoji/codex.png`: the Codex bot's upload belongs to the
  Codex application and fool-bot cannot use it. `/d12ball setup_hub`
  fetches it, so an upload takes without a restart.
- **The hub's Codex button answers with the command, privately.**
  `NewGameHubView` carries **Codex** beside **D12 Ball** (custom id
  `d12ball:hub:codex`, the medallion as its emoji). It cannot open a
  Codex lobby itself: Discord delivers a click only to the application
  that posted the button. And no bot can type into somebody's message
  box -- a link button only opens a URL, and no URL prefills the
  composer. So the button answers ephemerally with
  `codex_lobby_prompt()`: the `</codex create_game:ID>` mention, which puts
  the command in the clicker's box when clicked, one Enter from a lobby
  (the author asked for the button, 2026-10-08). A hub posted before
  it gains the button at the next `/d12ball setup_hub`.

## Who may act, shared

`cogs/game_auth.py` holds the gates both bots ask -- `game_participant_ids`,
`is_game_helper`, `may_act_for_coach`, `may_act_in_game`, the helper's
confirmation marker and exception -- and `send_new_prompt`, moved out of
`cogs/d12ball_helpers.py`, which re-exports every name, so nothing else
under `cogs/d12ball*` changed. They read the record's two seat ids,
which `D12BallGame` and `CodexGame` spell alike ([permissions.md](permissions.md)).
The Codex `SafeView` carries D12 Ball's helper confirmation since step
4 -- Confirm/Cancel in place of the view's buttons, the confirming click
marked on its `interaction.extras` -- and exactly one button asks for
it: the opponent's **Agree** to an undo to the previous turn. The panel
needs none, because it is ephemeral to the player who opened it: no
one else can see it to press it.

## The board on Discord

**One public message per turn** (decision 5): the board as its picture,
the turn's lines as its text, the game's buttons under it. Everything
else the bot shows is ephemeral.

- **The board is drawn element by element** (`codex/render.py`, step
  7, from the author's design canvas of 2026-10-08,
  https://claude.ai/artifact/2gJhY3oDWjVNvweAW1XY7f): each player is a
  panel (`render_panel`) built from the module's pieces and the cards'
  own art, at the pixels the canvas was drawn at times `DRAW_SCALE`
  (1.3 since 2026-10-12, below), Roboto Slab for every word and number.
  The measures here are the canvas's, at a scale of 1.
  - **Cards are 200 by 273** (the art at 61%; 260 by 355 as drawn)
    **in square cells of 273**, 16 between, so an exhausted card lies in its cell on its side at
    full size, turned a quarter clockwise with the exhaust glyph on the
    cell's top corner (the author, 2026-10-08: A of the canvas's three
    ways -- dimmed in place, and a smaller card, were the others).
  - **The width is the mat's top row** (the author, 2026-10-10: the
    board need not be so wide when it is empty -- as wide as the play
    mat, the building column, three heroes and five patrol slots): the
    building column, then the command zone and the patrol zone side by
    side, and the grid under those two with as many columns as fit, and
    never fewer than five (`grid_columns`, `MIN_GRID_COLUMNS`) -- six in
    the standard game, five in the basic -- read from how many heroes a
    player has, so the picture's width holds from turn to turn: 2004
    wide, or 1625 (2608 and 2114 as drawn). It was seven columns and 2203 in the standard game,
    the three command-zone plates taking three cells of the first row.
    The basic game's top row fits only four cells; four was tried and
    put a mid-game side's fifth card on a second row, 289 taller for 45
    narrower, so the basic grid stays five and runs 45 past its last
    patrol slot (the author, 2026-10-10, from the two pictured side by
    side). Rows are added as the position needs them, so the height
    follows it -- about 740 a panel with one row, 289 more a row --
    which the gate already allows for.
  - **On the left, the buildings**, 136 wide, bottom-aligned, top to
    bottom: the add-on slot (a dashed outline, or the add-on's card at
    136 by 193, as wide as the tiles and aligned with them), Tech III,
    II and I as the module's tiles at 136 by 97, and the base. The
    add-on was 82 by 114 and could not be read at Discord's size; a
    card's size (195 by 273) beside the patrol slots was tried the same
    day and was too large, and the add-on stays with the other
    buildings, as wide as the tech buildings. At the canvas's 160 wide
    that made the column 728 tall against the one-row grid's 629, so
    every building and chit is drawn at 0.85 of the
    canvas's size (`BUILDING_SCALE`), which makes the column exactly as
    tall as the patrol zone and one row (the author, 2026-10-09: the
    buildings a little smaller, so the column is the one-row grid's
    height); a test holds the two equal. A tech building is greyed and
    half seen until built, in colour once built, carries the module's house chit while under
    construction (UMR p. 8: from when it is paid for to the end of the
    turn) and is dark with the house chit when destroyed. Beside the
    chit, a strip runs across the middle of the tile, rising from its bottom left to its top right at 10 degrees -- UNDER
    CONSTRUCTION on gold, DESTROYED on red -- a little past its edges,
    as tape wrapped round it (`lay_strip`; the author, 2026-10-10: the
    chit alone did not make either clear). The add-on under
    construction carries the same strip, and a destroyed base -- seen
    only on a finished game's board -- goes dark with DESTROYED across
    it. It was level for its first hour; the author asked for the slant,
    just off level, top right to bottom left -- falling to the right instead
    would run its first word under the house chit. Every
    building's picture prints its full HP in a heart; a damaged one's
    heart carries the HP it has now instead, rather than a damage chit
    beside it (the author, 2026-10-09). The heart is the picture's own:
    a heart drawn over it in the canvas's flat red did not look like the
    print's glossy one (the author, the same day), so `wiped_heart`
    finds the heart by its red, wipes its white-and-black figures with
    the heart's own red blended in, and `building_picture` writes the
    new number there, white edged black in Roboto Slab stretched to the
    print's broader figures. The print's face is not bundled; that
    stretch is the nearest the bundled one comes.
  - **Across the top, the command zone and then the patrol zone**, in
    the mat's order. **The command zone is one plate** (`command_zone`,
    the author, 2026-10-10: the three heroes one command zone rather
    than three), as tall as the patrol zone, a card-sized slot per hero
    in the team's order: the hero lying in it at a card's size with its
    time-rune chit while off the field, the slot a dashed outline marked
    HERO, as the mat marks it, while the hero is on the field, and
    COMMAND ZONE under them. **The slots stand in the plate's middle**
    (the author, 2026-10-12), its edge showing on every side, and
    COMMAND ZONE is centred in the margin under them, at 19 rather
    than 13 (`COMMAND_LABEL_SIZE`): at the top of the plate, as a
    patroller stands over its bonus, a hero hid the plate's edge behind
    it, and read as a card on the table rather than one in the zone --
    above all on the far panel, seen from the other end. The
    patrol zone is the mat's own five slots with
    their bonus strips under them, cut from the playmat ("The cards are
    data"), **each on its own holder** of the mat's blue, packed side by
    side 12 apart, 16 after the command zone; a patroller's card covers
    its slot, chits and all, and the bonus stays under it. They were
    one blue band the grid's width, each slot centred in a 273 column
    (the author, 2026-10-09: the holders individually, to save the
    space between the cards). What that leaves at the row's right end
    stays empty. A slot needs only a card's width, not a
    cell's, because a patroller is never exhausted: exhausting one
    sidelines it.
  - **The grid**: first the worker card, under the command zone (the
    author, 2026-10-10: the count off the nameplate and onto the
    Screentop module's worker card): x4, printed "Player 1", for the
    seat that went first, x5, "Player 2", for the other (UMR p. 3), in
    the colour of the first hero whose colour the starting deck is --
    `PlayerState.deck_color`, since the first hero names the deck
    (the author, 2026-10-10) -- so the basic game's is the neutral,
    brown card. The module has a worker card per colour, each its own
    art (Red's a pirate, Green's a nymph) on the neutral card's layout;
    `worker_face` takes `worker_colors/<colour>_x4.png`, and the
    neutral `workers/worker_x4.png` for a colour with none. Its printed count is wiped --
    the figures and their edge blended into the box by `wiped_workers`,
    as a building's heart is. Each colour prints them in its own ink,
    black to white, which no one band of colour finds on all seven, so
    where they stand is found once, by the rosy ink on the neutral card
    (`worker_figures`), and wiped on every colour's; the ink under them
    is the face's own. The workers the player has now are written in
    their place, "x8", in that ink, in Roboto
    Slab's regular weight edged dark, as tall as the print's digit and
    narrowed to fit the box (`worker_card`). It takes a cell, so the
    basic game's first row holds four cards beside it and a fifth starts
    the second. Then the heroes on the field (the level chit top left),
    then the units, each with
    its damage chits on the foot of its art (`ART_FOOT`), clear of the
    ATK and HP the card prints, which a chit over the stats hid (the
    author, 2026-10-09), its rune chits hanging over its right edge a
    little below its middle (`RUNE_CENTRE`), Two Step's chit on a
    dance partner just left of the stats pill, the damage chits' size,
    and drawn as one picture with it (`beside_pill`, `PARTNER_CHIT`), so
    it follows the pill onto an exhausted card's turned corner and a
    copy's number stays between it and the cost (the author,
    2026-10-15: it stood at the card's foot, bottom left, and then a
    little smaller than the damage chits). Centred on the pill it would
    rise past the `OVERHANG` round the card, so its top stops there and
    it hangs a little below the pill's line (`pill_rise`); and ARRIVED
    the turn it came, on the foot of its art against the left edge,
    opposite the damage chits (the author, 2026-10-10: it sat over the
    card's text, 44 above its foot).
  - **A named rune -- blood, growth, corpse, focus, a feather -- is a
    swirl chit in its colour with its count**, top right under the
    stats pill (`rune_chit`, `NAMED_RUNE`), never a word (the author,
    2026-10-11). The chits are the module's blue swirl chit recoloured
    as the board is drawn -- its blue the colour's and its yellow swirl
    kept -- on white the white cards' own frame, #e8e9e5, and a lighter
    gold swirl (`RUNE_CHIT_COLORS`; a white card's tag is true white,
    `WHITE_TAG`), the number small enough that the swirl shows round
    it -- one for each of
    the six colours, so nothing is committed; the count is drawn on it,
    so any number fits. A rune's colour is the card's that puts it there
    (`RUNE_COLORS`: Bloodburn's blood red, Corpse Catapult's corpse
    black), or the colour of the card it sits on for a kind not in the
    table -- a crumbling rune, Two Lives', white on Garus Rook and blue
    on Justice Juggernaut. A single rune alone -- a feather, a crumbling
    rune -- has no number. Words stay only where a chit cannot say
    which: a feather rune, on a unit whose own text never names one,
    keeps a "Feather" tag, and a copy, a jail, a number and an oath
    stay tags. **Every tag is the colour of the card it comes from**
    (`label_colors`, the author, 2026-10-11), at `MARK_SIZE`, a little
    smaller than it was: the feather green (Fairie Dragon), a copy
    blue (Manufactured Truth, `COPY_FROM`), a jail's, a number's and an
    oath's the card that holds it (Jail; Reputable Newsman's number
    alone, "3"; Oathkeeper of Kor Mountain's "Play no cards" or "Skip
    draw/discard", `OATH_TAGS`), a Graveyard's units by name in its
    black, the units Prynn's max level ability has trashed by name on
    her in her purple, "Trashed" said once, on the first -- "Trashed:
    Iron Man", then "Tiger Cub" under it (the author, 2026-10-19: what
    comes back when she leaves play, which the board said nowhere
    else), a long name cut with an ellipsis to the card's width
    (`cut_tag`, which the lent tag uses too), and the old purple for a
    neutral card. The tags are `rune_marks`'.
  - **Time runes are in the same column**, first, as the purple chit
    of the card they are on (a fading card, Prynn, a card in the
    future), with FUTURE in the waiting card's colour under them (the
    author, 2026-10-11: the label beside its rune, and the rune where
    every other is), at the damage chits' size, `TIME_RUNE`, larger than
    a named rune's (the author, 2026-10-21: it read too small beside the
    damage). The module's own time-rune chit, 1 to 6, is left
    to a hero's summoning runes in the heroes' zone. +1/+1 and -1/-1
    keep the module's chits over the right edge.
  - **ARRIVED and DISABLED are grey tags of the same size as every
    other** (`STATE_FILL`), stacked at the foot of the art against the
    left edge -- states rather than anything a card of a colour put
    there, so neither carries a colour. A lent patroller's tag joined
    them on 2026-10-15, under both: "Lent from bo", the zone it lies
    in not its owner's (multiplayer, "The board").
  - **Every tag is one height, its words centred on their capitals**
    (`pill`), and **the tags stand on one grid of rows** (`lay_tags`),
    the lowest on the art's foot: the marks down the right edge, the
    states up the left, each state in the lowest row no mark reaches
    across to, never above `TAG_CEILING`, the cost's and the stats'
    (the author, 2026-10-12: "Skip draw/discard" lay over DISABLED).
    The damage chits keep the foot of the art on the right, and step
    left of a rune chit or a mark standing beside the foot (`lay_damage`;
    the author, 2026-10-12: a rune chit hid the damage); a tag over no
    more than a chit's top point (`TAG_SLACK`) moves neither, and is
    drawn over it. ARRIVED and DISABLED go round the damage too, ARRIVED
    always the lower; with no row free -- a damaged, disabled card that
    arrived this turn with a rune chit -- one lies over the chit's edge.
  - **What an effect leaves on a unit or a hero for a while is a tag
    too** (`effect_tags`, the author, 2026-10-12): a modifier to the end
    of the turn, to a seat's next upkeep or to Vandy's doom that the
    stats pill cannot show -- a keyword by its own name ("Haste",
    "Invisible", "Resist 1"), one lost ("Not flying"), and Doomed,
    Illusion, Can't attack, Can't level up, Bloodlust (`MODIFIER_TAGS`)
    -- and Kidnapped on a unit that goes back at the end of the turn.
    The tag says the effect alone, never how long it lasts, and is in
    the colour of the card it came from (the modifier's `from`). Where
    one card's modifiers come together, one tag says them all, or none
    is needed (`TAGGED_AS`): Gargoyle is "Not indestructible" alone, its
    flying, ATK and attacking coming with it; a kidnapped unit is
    Kidnapped alone, its haste coming with it; Poisonblade Rogue's own
    attack has none; Rampant Growth's +2 ATK and +2 armor and Dinosize's
    +6 and +6, which the pill shows, are tagged by name all the same
    (the author, 2026-10-12).
  - **An effect across a whole side is tagged by its card's name on
    every unit it reaches** -- Ferocity, Stampede and Dreamscape, and
    Might of Leaf and Claw on its controller's units and heroes while it
    has five growth runes (the author, 2026-10-12: they change how each
    unit fights). Which bodies it reaches is the engine's answer,
    `RulesEngine.auras_on` -- the controller's `lasting`,
    `under_dreamscape` for a tech 0, I or II unit on either side, the
    growth grant where `growth_holds`, the one reading the +5/+5 is
    applied by too -- handed to the renderer with the stats by
    `board_reading`, which the cog passes where it passed `body_stats`;
    the renderer takes either. **A unit kept from attacking and patrolling for now is tagged by
    what holds it** (the author, 2026-10-13: a unit missing from the
    patrol menu said nothing of why), in the colour of the card that
    does (`BARRED_TAGS`): "Shackled" on Terras Q while his Warlocks are
    in play, "Entangled" on a unit under Entangling Vines -- each card's
    own word, since both bar attacking as well as patrolling and "Can't
    patrol" said half of it (the author, the same day). **A card's own printed "can't
    patrol" is never tagged** -- Land Octopus, Makeshift Rambaster,
    Pestering Haunt, Justice Juggernaut, Daigo Stormborne, Gargoyle --
    since the face already says it and a tag would only repeat it (the
    author, the same day: only a condition is worth a tag). Which card
    keeps a unit out, if any, is `RulesEngine.barred_by`, beside
    `cant_patrol_as_printed`; `patrol_candidates` and `may_attack_with`
    both read it, and `board_reading` hands it over as its fourth value
    (`Stats.barred_by`). Exhaustion is the card's own state, and
    Moment's Peace is across a whole side, so neither is tagged.
    A player's other lasting effects --
    Moment's Peace, Free Speech, a debt -- are for the side of the
    board, not yet drawn. A modifier for good (Metamorphosis, Fox's Den
    School), an attached spell and a changed controller are not tagged
    yet either.
  - **A unit's and a hero's ATK and HP as they stand, on a pill hanging
    over the card's top right corner** (`stat_pill`, the author,
    2026-10-11; `STAT_OVERHANG`, since inside the corner it covered
    too much of the art): what the
    card prints is not what it fights with once Two Step, a Grounded
    Guide, a rune or its own text has had its say, and the board was
    the one place a player could not read the difference. The numbers
    are the engine's `board_reading` -- `body_stats`, with the elite's
    +1 ATK added while the body patrols there, capped and floored as
    `attack_value` does, because the slot's bonus is what it fights
    with and a pill that left it out read one less than the attack did;
    frenzy, which `attack_value` adds on its controller's turn alone, is
    not on it (the author, 2026-10-15)
    -- which the cog hands the renderer
    (`stats=`) so that nothing in `render.py` works out a stat; HP is
    what is left, its damage taken off, and the damage chits stay
    beside it. ATK is on the card's own black and HP on its red, a
    step brighter than the print's heart (`STAT_HP`); a stat that is
    not what the face shows prints -- a hero's, its level's band;
    a polymorphed unit's, the Squirrel's -- turns slate for ATK or
    maroon for HP, close to its plain colour, the same whether it is up
    or down, since the number says which. Tried and turned down on the
    way (a sketch the author reviewed): a copy of the card's printed
    square and heart, enlarged; green and orange for up and down, then
    teal, gold, blue and violet pairs; the top left, over the cost.
    The top right was the rune chits', so they moved down the right
    edge, clear of the pill above and the damage chits on the art's
    foot. The pill's foot is toward its player's edge of the table:
    upside down on the far side, as that side's cards are (the author,
    on the first build, which kept it the viewer's way up there), and
    level with the table on an exhausted card, on the turned card's
    top right, over its cost (the author again: drawn on the card, it
    lay on its side with it) -- on a hero, just left of its level chit,
    which the quarter turn carries to that same corner (the author,
    2026-10-15: the pill covered the level); a copy's number, which is matched to a button, still reads
    upright, and moves left of centre on a standing card to sit
    between the cost and the pill. Only units and heroes on the field
    carry one: not a hero in the command zone, a building card, an
    upgrade or a spell. **Its armor, while it has any, is a number on a
    steel-blue shield after the HP** (`armor_shield`, `STAT_ARMOR`; the
    author, 2026-10-12: a squad leader's 2 HP read as all it could take,
    when its armor takes the first point). It is the body's own `armor`
    -- what is left of it this turn, every source already added in by
    the flow -- so the renderer reads it as it reads damage and works
    nothing out; at 0 no shield is drawn. The shield is as tall as the
    pill's middle, its flat top and its point level with the pill's
    top and foot (the author, 2026-10-12: the first build's stood
    4 px taller, and drew its shape 2 px inside the picture each
    way), overlaps the pill's rounded end, and widens for two
    figures.
  - **The gold is a coin beside the worker card**: the gold emoji's coin
    with the count on it, all but as wide as the space between the
    building column and the worker card's face (`GOLD_COIN`), at the
    card's foot -- level with the base in a one-row panel (`gold_coin`;
    the author, 2026-10-18: "that should be the way money is shown").
    Its first day it was only as wide as `BUILDING_GAP`, and too tiny
    to read; beside the worker card rather than the base because the
    worker card is always upright, where the cell beside a taller
    panel's base may hold an exhausted card lying across it. On the far panel its
    count is drawn upside down, so it reads upright once the panel is
    turned -- the one part of a turned body that is not the upright
    one rotated.
  - **A nameplate along the panel's outer edge**, 56 tall: the player,
    then right beside the name hand, deck, discard and codex, a word and
    a count each -- beside the name rather than at the plate's far end,
    where on a wide board they sat a panel's width from the player they
    count (the author, 2026-10-18) -- then their team by `codex.formatting.team_name` -- a
    colour's three heroes by the deck's own name, "Blood Anarchs", any
    other team by its specs in the order chosen, "Fire/Feral/Bashing",
    and the basic game's one hero by its spec, "Bashing" (the author,
    2026-10-10: never the heroes' names; "Red · Jaina Stormborne,
    Captain Zane, Drakk Ramhorn" from step 10 until then); the workers
    are counted on the worker card in the grid instead. The active
    player's carries a rule and "<name>'s turn <n>" in a pill, both in
    its first hero's colour (`turn_colors`, below), the player by the
    name the cog passes -- "perrytom's turn 7".
  - **The turn is the player's, not a hero's** (the author,
    2026-10-09): a standard game's deck has three heroes, so "Troq's
    turn 7" -- the wording the first draft of step 7 took from the
    design canvas, by a hand-kept table of short names (`SHORT_NAMES`,
    `Hero.short_name`, since "Captain's turn 3" names nobody) -- would
    have had to pick one. The table went with the wording; nothing
    else read it, and the catalog holds nothing by hand again.
  - **Why the mat went**: on the mat the cards sat in its printed
    places, about 200 pixels wide on a picture 1838 by 1088 a side,
    most of it the mat's art and places the position did not use. The
    panel keeps the card at the same pixels in about three fifths of
    the area, so at any size Discord shows the board, the cards come out
    larger, and nothing is drawn for a place the position does not use
    beyond those that must be seen empty -- a patrol slot, a tech
    building, the add-on, the command zone. The playmat stays imported
    as the reference the layout was taken from; nothing draws it but
    the pieces cut from it.
  - **The ground is the mat's leather** (the author, 2026-10-09: leather,
    so long as it does not make the board load much slower): a plain
    patch of it below the Codex logo, cut like the patrol slots
    (`ground/leather.png`), mirrored across and down into a tile that
    meets itself, and tiled under each panel from its top left
    (`leather_ground`). The far panel's leather turns with it, so the
    far side reads as one mat turned. The space between the panels
    stays flat (#15100c). Measured that day against the flat ground the
    canvas sketched (#231a14), the leather costs about a fifth more
    bytes -- 70 KB to 86 KB for the opening, 111 KB to 133 KB for a
    busy mid-game board -- a few hundredths of a second on a phone's
    connection, and still well under the 220 KB the mat board was.
  - **Composed at `DRAW_SCALE` times those pixels** -- 1.3 since
    2026-10-12 -- and saved as WebP at quality 85 (`WEBP_QUALITY`), about
    350 to 700 KB -- the encoding every picture the bot uploads has, the
    hand, the codex and the tech picker since 2026-10-09 (below). Every
    measure of the board is written at a scale of 1 and passed through
    `px`, so the picture is the canvas's drawn larger, every chit, pill,
    word and gap in proportion; the board pieces cut at a card's size
    (the patrol slots and their bonuses) and the leather are resized to
    it (`sized`). It is composed at that size rather than scaled after,
    since a picture scaled up gains no detail. The hand, the codex and
    the deck have their own measures and are not scaled.
    - The history: the composed board was scaled by 0.6 until
      2026-10-09, when a card's name read when the picture was zoomed
      but not its rules text or a hero's level bands; at 0.8 they were
      still soft; at 1 (the author, 2026-10-09) a card was 200 by 273,
      two and a half times the bytes of 0.6 -- the staged mid-game board
      137 KB to 332 stacked. A hero's level bands, the smallest type any
      card prints, were still mush zoomed at 200 by 273, and the author
      asked for the heroes sharper (2026-10-12). Every card's art is the
      same 330 by 450, so a hero is sharper only with more pixels, and a
      hero larger than the other cards was ruled out: the whole board a
      bit bigger, not the art's full size (1.65), "just a bit bigger so
      the font is readable". At 1.3 a card is 260 by 355 and the bands
      read; the staged mid-game board went from 368 KB to 523 stacked
      and 382 to 558 side by side, the standard game's from 484 to 714.
      The change was checked byte for byte: at `DRAW_SCALE` 1 every
      sample picture hashes as it did before `px` was put in.
- **The layout is the game's**, on the record (`board_layout`, not the
  match's, so an undo does not take it back): stacked, stacked the same
  way up (`stacked_upright`), or side by side with the first player's
  mat on the left. **Swap view** flips the two stacked ones for
  everyone -- and from side by side goes back to stacked -- and the
  board goes up through the gate. Side by side is reached by
  `/codex side_by_side` alone, which toggles it with stacked (the
  author, 2026-10-12: the button between the two stacked boards, side
  by side behind a command). The button's label names the layout it
  goes to: "View: same way up", "View: facing", or "View: stacked"
  from side by side.
- **Stacked the same way up** is the stacked board with neither panel
  turned: the other player's above, read as it would be from its own
  seat, its nameplate under it beside the divider, so every card on
  the table reads without turning a phone -- what the turned board
  gives up to look like a table.
- **Stacked is the table seen from the active player's side** (the
  author, 2026-10-08): their panel at the bottom, the other player's
  above it and turned round to face them, so the two patrol zones face
  each other across the gap as they do across a table, and the picture
  turns with the turn (`stacked_seats`, the one reading of which seat
  is near). The far panel's body is turned whole -- its cards and chits
  read upside down, as the far side of a table does -- but its
  nameplate is the bot's words and stays the right way up, on the
  panel's outer edge, above: a name and its counts nobody should have
  to turn a phone for. A 52-pixel divider between the two reads
  "<NAME>'S TURN <N>", the same name, bold and dark on a white pill
  between two grey rules -- taller and brighter than the canvas's
  36 pixels of faint capitals, which did not read at Discord's size
  (the author, 2026-10-09: the turn more prominent, not gold, and not
  cream). **The divider is white in every game** (`DIVIDER_TURN`): the
  hero's colour, below, is the nameplate pill's alone (the author,
  2026-10-09), so the loud mark is the same from game to game and the
  colour is read where the hero is named beside it.
- **The nameplate's mark is the active player's first hero's colour**
  (the author, 2026-10-09): its pill and its rule, in the colour of the
  hero of the deck's first spec (`turn_colors`: `PlayerState.specs[0]`,
  `CardCatalog.hero_for`, `Hero.color`) -- so the nameplate says whose
  turn it is twice, by the player's name and by their deck's colour,
  and in the standard game the two sides' marks differ. `TURN_COLORS` holds the seven colours the cards come in
  as a fill, the ink that reads on it and an edge: Neutral is tan (the
  plates' ink, `PLATE_INK`, with dark words), Red, Green, Blue and
  Purple a mid tone of the card frame's with white words, White white
  with dark words, and Black a near-black with white words and a grey
  edge (`QUIET`), because a black pill on this ground has no outline
  without one -- and its rule is drawn in the edge, since a black rule
  on the leather vanished (seen on the seven-colour sheet). Nothing
  else reads a card's colour; the table is keyed as `Hero.color`
  spells it, lowered. Their first day the nameplate's marks were gold
  and the divider's teal, and the author asked for both replaced: gold
  is the currency's -- the coin and every cost badge -- so a gold pill
  beside the gold count said two things in one colour, and teal sat
  between the two patrol zones' blue and read as a shade of it. A sheet
  of six fixed candidates (raspberry, plum, violet, white, and two
  mixes) rendered at Discord's scale (the board's, then 1) came first, and a
  violet nameplate over a white divider was taken from it, before the
  author decided the colour should be the hero's rather than fixed --
  first on both marks, then on the nameplate's alone, the divider
  white. Checked the same way: all seven colours on the nameplate, on
  the staged mid-game board at Discord's scale. Green sits near
  ARRIVED's and Blue near the patrol zone's; both are the cards' own
  colours and the mark is not the board's to recolour.
- **No cream** (the author, 2026-10-09): the canvas's light words were a
  warm cream and its quiet ones a tan; the board, the hand and the
  codex draw them neutral -- white (`WORD`, `INK`) and grey (`QUIET`). A finished game is seen from
  where it was left.
  Side by side turns neither panel and puts an 80-pixel divider
  between them, the same words standing: two panels read left to right
  are a desk, not a table. Where the two are of different heights, the
  shorter is filled between its body and its nameplate, so the
  nameplates stay level.
- **Swapping the view changes the message's shape**, and what the
  reader sees in between is the client's. A stacked board is tall and
  a side-by-side one wide, so the one edit that replaces the picture
  also re-lays the message out, and Discord's apps draw the picture
  they have into the box they are moving to while the new one loads --
  the slice of board seen mid-swap. The bot sends one edit and cannot
  send less; the one thing in its hands is how long the new picture
  takes to arrive, which is its size. As PNG the board was about 2 MB;
  measured 2026-10-08, the same board is about 340 KB as JPEG at
  quality 85 and 220 KB as WebP, and at 1:1 the three are hard to tell
  apart, so the board is WebP (the author, 2026-10-08) -- the smallest
  of the three, and Discord shows it natively. That shortens the moment
  rather than removes it.
- **The hand, the codex and the tech picker are WebP too** (2026-10-09:
  the author found the codex's cards slow to load). They were PNG,
  which spent 855 KB on a twelve-card codex and the tech picker's, and
  419 KB on a five-card hand; WebP at the board's quality spends 168 KB
  and 63 KB, and at 1:1 the card text is the same. Each goes up on a
  click -- **My hand** and the panel, **Codex** and each choice of its
  menu, each tech pick -- uploaded by the bot and fetched by the client
  every time, so the wait is the file's size twice over. The card
  files themselves were not what was slow: 330 by 450 JPEGs of 65 to
  130 KB, the smallest the pictures are drawn from, and `/codex card`
  alone posts one as it is; drawing takes a quarter of a second
  whichever the encoding. `WEBP_QUALITY` is the one number
  (`BOARD_QUALITY` until then), and the attachments are `.webp`.
- **A picture already up is not drawn or uploaded again** (2026-10-09:
  the author found the cards still slow after WebP). What the bot
  controls in a click that pictures cards is three things -- drawing,
  the upload, and whether the client has to fetch a new file at all --
  and the panel spent all three on pictures it had just sent: every
  in-place edit (**Back**, a menu, the tech picker's redraw) drew the
  same hand again and uploaded it as a new file, which the client then
  fetched as one. Three changes, none to what is drawn (the hand, the
  codex views and the tech picker byte-identical before and after,
  SHA-256, and the sample script's eighteen pictures):
  - **Each picture is named by its bytes** (`picture_file`:
    `codex-hand-<digest>.webp`, `codex-<view>-<digest>.webp`,
    `codex-tech-<digest>.webp`), so an edit in place knows the message
    already carries it, and `kept_pictures` hands Discord the
    attachment it has rather than a file: no upload, and the client
    shows the picture it already loaded. The name is the only state --
    an ephemeral message is stored nowhere, and a restart loses
    nothing. A message sent afresh (My hand, Tech, `/codex resume`)
    has nothing to keep and uploads, as before.
  - **The same picture asked again is the bytes already drawn**:
    `render_hand` and `render_codex` keep the last `RENDERED_KEPT` (32)
    each, keyed on what they draw -- **My hand** clicked twice, the
    codex reopened, a view chosen again, the hand the in-place edit
    names before it is kept.
  - **Each card's art is scaled once per size** (`scaled_card`): a
    fifth of a warm render was resizing the same 330 by 450 JPEGs.
    Measured that day on a development container, not the live host,
    a twelve-card codex drawn anew went from about
    0.14 s to 0.10 s, a hand from 0.13 s to 0.07 s; asked again, both
    are free. Two thirds of what is left is the WebP encoding itself.
  What remains is Discord's -- the upload from the live host, its
  processing and the client's fetch -- which the bot cannot measure
  from here and does not shorten except by sending fewer bytes.
- **No click reads the host's disk, and what each picture costs is
  logged** (2026-10-09: the author found the cards slow a third time,
  after WebP and after the kept pictures). The two fixes before had
  taken what the bot's own drawing had to give: measured again that
  day on the Mac, a five-card hand is drawn in about 40 ms and a
  twelve-card codex in 50, the stacked board in 150 to 300, and the
  WebP encoding is about half of each at Pillow's default effort
  (`method=4`) -- its fastest saves 25 ms a picture for a tenth more
  bytes, its slowest spends 50 ms to save a fiftieth, so the setting
  stays. What was left in the bot's hands was three things:
  - **The live host's disk.** Its checkout is a mounted Google Drive
    letter (collaboration.md, "Two machines, one live bot"), which may
    hand a file over from the cloud rather than the disk, and the bot
    is restarted on every deploy -- so the first hand and the first
    codex of a game after one read their cards' art through it, a
    file at a time, and `/codex card` opened its file on the event
    loop. Now **every file a picture is drawn from is read into memory
    as the bot starts** (`render.preload_pictures`, off the event
    loop, started by `cog_load` and cancelled by `cog_unload`): the
    cards' art, the board's pieces and the emoji the pictures borrow --
    not the module's sheets nor the playmat, never drawn -- and the two
    fonts: 447 files, 44 MB, held for the process's life.
    `bundled_bytes` is the one way a bundled file is read, and what the
    preload missed is read once on first use; a file it cannot read is
    a warning, and nothing is drawn differently (the sample script's
    thirty-one pictures byte-identical before and after, SHA-256). The
    line it logs says what the host's disk took: "Codex pictures read
    into memory: 447 files, 44 MB, in 0.1 s" on the Mac.
  - **The acknowledgement before the board.** An action deferred its
    click, then drew and posted the board, then sent the panel: the
    defer is a round trip of its own that nothing after it waited for.
    It goes out beside the board now (`TurnPanelView.act` and
    `undo_to_turn_start`, `asyncio.gather`), which takes it off the
    panel's path.
  - **Numbers from the host.** The bot could not say where a slow
    picture's time went, so every picture a click puts up logs one
    INFO line -- console-only (logging.md) -- with what it cost to
    draw and what the write that carried it took: the board posted
    (a new turn's, or `/codex resume`'s; the gate's edit logs none),
    the panel sent or edited in place, the hand, the deck, a
    codex view, a card (`cogs.codex_helpers.elapsed_ms`,
    `pictures_size`). The next report is read off the console
    (`show_logs.cmd`) before anything is guessed: a long draw is the
    host's CPU or its disk, a long send is the host's uplink or
    Discord, and what follows the send is the client's fetch, which
    the log cannot see.
  What remained then was the design's floor: an action that put something in
  public was **two new pictures** -- the board on the message posted
  again, the hand on the panel sent afresh under it -- each uploaded by
  the bot and fetched cold by every client, which a kept attachment
  cannot touch, since only an edit keeps one and both messages are new.
  Taking one of the two away is a change to the shape the author chose
  (the panel under the board; "The panel"), so it was put to them
  rather than made, two ways: the panel edited in place after an
  action, keeping its hand where the hand did not change and sitting
  above the board posted again; or the hand on an ephemeral message of
  its own, edited only when it changes, with a panel of buttons alone
  sent under the board. **The author chose the second, and it was built
  and undone the same day** (2026-10-09; #504's third commit and its
  revert): the panel's buttons without the cards' pictures beside them
  made no sense to them -- a panel that asks which card to play has to
  show the cards -- so the panel pictures the hand again, and its
  upload on every action stands as the price of that. The first way,
  the panel edited in place and sitting above the board, was not tried
  then; **since 2026-10-12 it is the shape** ("The turn message,
  edited"), with the board edited rather than posted, so the hand's
  picture is kept wherever it did not change.
- **The hand's and the codex's cards are a bit smaller** (the author,
  2026-10-09, with the above): the art at 0.7 and at 8/15 -- 231 by
  315 in a hand, 176 by 240 in a codex view, the deck and the tech
  picker (`HAND_CARD`, `CODEX_CARD`), from 0.8 and 0.6 -- which takes
  about a sixth off each picture's bytes: the staged mid-game hand
  87 KB to 72, the twelve-card codex 164 to 134, the standard game's
  seventy-two 590 to 477. The badges, the numbers and the picked pill
  keep their size, so they read a little larger on the card. The
  board's cards are the canvas's and `/codex card` posts the card's own
  file, so neither moved.
- **The write gate is D12 Ball's `BoardRefresher`**, shared rather than
  copied: what it reached into D12 Ball for is a parameter -- the view
  kept on the message (`keep_view`; D12 Ball's home/visiting buttons
  once inert, the Codex bot's `TurnMessageView`), when the full-image
  link may go up (`links`; D12 Ball's once the sides are chosen, the
  Codex bot's always), which message is the board (`message_of`; the
  Codex record's `turn_message_id`), the message's text (`text_for`,
  which D12 Ball does not pass) and the game's name in the log. Each
  defaults to D12 Ball's, so its tests build it as they did. An edit
  whose picture and text are both unchanged is skipped, and **one whose
  picture is unchanged edits the text alone** -- no upload, the
  attachment and its full-image link left as they are
  (`BoardRefreshState.picture_digest`; the author, 2026-10-12: "When
  only the text changes, it shouldn't draw the picture again - only
  edit the text"). Nor is the picture drawn again: `render_match_png`
  keeps each game's last board with what it was drawn from
  (`board_key` -- the match without its history, the turn snapshots,
  the journal and the events, which change with every action whether
  or not the table moved; the layout; the seats' names) and hands the
  same bytes back for the same key (`Codex.boards_drawn`). The gate
  writes every action's edit, **Swap view**'s and the full-image link
  ("The turn message, edited", below), and is handed each post -- a
  new turn's, `/codex resume`'s -- as the board it keeps
  (`BoardRefresher.posted`): the window runs from it, and its link is
  owed.
- **The turn's lines are held in memory**, by game, in the model's
  tokens, and rendered at the door (`CodexTokens`: `{player:n}` the
  seat's name, `{card:slug}` and `{hero:slug}` in bold, the hero's emoji
  where uploaded). After a restart the message's text stands as it was
  until `/codex resume` re-posts the table; the gate leaves the text
  alone (`text_for` answers `None`) where it has not seen the lines.

## Hidden information on Discord: the ephemeral shape, as tried

Decision 4's shape, tried for the first time in step 3: **My hand** on
the turn message answers the clicker alone, ephemerally -- their hand
pictured by `render_hand` (each card's own art, numbered, its printed
cost left in view and, where a reduction or a surcharge changes it,
the change beside it in a small pill, "−1" on light grey or "+1" on dark
grey -- a coin over the printed one read as the printed cost, so River's
discount looked missing; the pill was first "now 2" in gold, then the
difference on green and red, until the author settled on two greys,
since the coin is gold and the game already uses green and red (the
author, 2026-10-15) -- greyed where it may not be played, which is the engine's
`hand_rows`) under its count alone; the discard pile was
listed beside it as text until the author found it read as the hand
(2026-10-11: "Don't list my discard pile"), and **My deck** shows it
in its own frame. **Codex**
answers with their own codex pictured by `render_codex`, every card with
a badge of the copies left and faint at none, under a menu -- Everything,
Tech I, Tech II & III (one view since the author's 2026-10-12, "fold
tech 3 into tech 2"), Spells, and one view per spec once a deck is
more than one (the standard game's, step 10) -- that re-renders the
picture in place (the engine's `codex_remaining`, by `codex_views`; the
views are named by `codex.formatting.codex_view_name`). **A codex of
one spec -- the basic game's twelve -- is shown whole, always, with no
menu** (the author, 2026-10-20: "with 1v1 basic game, always show ALL
the codex"): `codex_views` is Everything alone for it, so the Codex
button and the tech picker both show every card and offer nothing to
narrow -- twelve cards are two rows, nothing to filter. A dragon's
teammate's codex still puts a menu up, the two players' Everything. **Which cards a
view holds is one reading**, `RulesEngine.codex_view_rows`: a tech level
is every card printed with it, a building or an upgrade as much as a
unit (the author, 2026-10-09: "not meant to show units only but all
tech cards" -- the first reading showed units alone, which lost nothing
in the basic game and dropped Anarchy's Tech II building, say), the
spells are the rest, so the four together are the whole codex and a
card is in exactly one; the tech picker narrows by the same function.
**My deck** shows every card a player owns, wherever it is (the
author, 2026-10-09: "all the cards that are in your deck, which
includes all the cards you've added with tech ... minus all the cards
you removed by making them workers"). It is the engine's one reading,
`RulesEngine.own_deck`, worked out from where the cards are rather than
kept as a list, since nothing in the save records the deck as a whole:
the hand, the draw pile, the discard pile, the owner's cards in play on
either side (a stolen unit is still its owner's; a token is nobody's,
being trashed when it leaves), and a spell of theirs being cast -- an
effect frame's `spell`, or Appel Stomp waiting on its place. A tech
choice joins it at the ready phase, when the picks reach the discard
pile, and not before; a hired card is trashed and so gone. It is
pictured by `render_deck` as one picture of four parts, **each in a
frame headed with its name** -- "Hand", "In play" (the owner's cards on
either side and a spell of theirs being cast), "Discard pile" and
"Deck" (the draw pile) -- in that order (the author, 2026-10-10: "one
image but with the frames around separating the different parts";
2026-10-15: "Should show what's in play as a zone. Then 'rest of deck'
can be 'deck'", where in play had been folded into a "Rest of deck"
with the draw pile). **The frames are packed to fill the rows**
(`deck_layout`; the author, 2026-10-15: "should fill the rows"): the
first reading put each frame on a row of its own wherever two would
pass eight cards (`DECK_COLUMNS`), so a hand of two sat alone beside an
empty width. Now every way of cutting the frames, in order, into rows
is tried -- four frames are eight ways -- each row as few lines of
cards tall as lets its frames, each in as few columns as fit its cards,
total eight columns or fewer; the shortest picture is taken, then the
one with the fewest empty card places, then the one whose frames wrap
least, which is what lays a hand of five in a row of its own rather
than two columns tall beside the discard pile. A frame of two cards
always lies them side by side, whatever its row's height (the author,
2026-10-15: "a 2 card frame has to include the cards horizontally"),
the first reading having stacked a hand of two into one column beside
a two-line discard pile. A row narrower than the
widest has its last frame stretched to the picture's edge, so the
right edges line up. Each part is in the deck's order -- the starting cards first
and then each tech level -- and shows each card once with its copies
there on its badge, so a card with one copy in the hand and another in
the draw pile shows in both (the author, 2026-10-09: "I want the cards
in hand to appear together. A second copy of the same card would show
up again outside of the box"; "also show which cards in the discard").
The hand's frame is drawn in the neutral white the words are and the
other three in the quiet grey, not gold: the author asked for no gold
there, gold being the tech picker's mark (its first day, the deck was
the codex grid with the hand's copies framed in gold on each card,
which left a hand's cards scattered through the deck). The split is
the engine's, `OwnDeck.held`, `played`, `discarded` and `pile` beside the
whole `cards`, so the view computes nothing; `render_deck` shares one card
tile with `render_codex` (`codex_tile`), whose output the extraction
left byte-identical. Its caption is the total alone, "Total cards in
deck: 13." (the author, 2026-10-09: "cut down on text"), where it
first counted every place in words; the picture says where the cards
are, and the draw pile's order is never shown, its cards being in the
"Deck" frame in the deck's order. A tech choice not yet in the
discard pile is not listed, there or anywhere in it (the author, 2026-10-09). The button is on the turn
message, beside **My hand**, for either player whoever's turn it is
(the author, 2026-10-09: "include it in the public message"); under the
other player's hand (`HandView`, beside **Codex** and **Show board**); after the hand's
buttons on the main-phase panel; and beside **Save tech** on the picker
and on the confirmation. Each press is **a message
of its own** (`send_deck`), not an edit of what it was pressed on, so
the hand, the panel or the picker stays up beside it while the deck is
looked at; like the Codex browser, it is reference and answers nothing.
A watcher who presses either is told the table is not theirs. Nothing is stored: each
press makes a fresh ephemeral message, and `/codex hand` answers the
same. Where it was checked that nothing hidden is public: the turn
message's text is the narration alone (`test_the_turn_message_names_no_card_in_a_hand`),
`GameResult.to_dict` writes no prompt, and no log line in the cog names
a card. Since step 4 My hand answers the active player with the panel
instead (below), and step 4's checks are: every line the channel is
sent or edited to through a turn -- a card played, a worker hired, the
turn's end, a tech choice saved -- is the header, the cog's caption, or
a line of the model's narration (`test_the_hand_never_reaches_the_channel`);
the panel, the tech picker and the confirmation are ephemeral and sent
to their asked player alone; the undo's public question names the
players and nothing else; and the cog's new log lines name a game, never
a card.

## The turn on Discord

Step 4 is the whole turn, driven from **one ephemeral panel** for the
active player and summarised in **one public message per turn**, both
edited in place as the turn goes on.
`tests/test_codex_cog_turn.py` drives it through the cog with Discord
faked -- `tests/codex_cog_fakes.py` logs every request by route -- and
plays a whole game through the panels to a destroyed base, every click
held to the request budget below, with the pictures stood in for by
dotted-name patches on `cogs.codex.core`. Those reach the cog only while
`sys.modules` still holds the modules the tests imported, which is why
the bot test that loads the extension and closes the bot restores it
("A bot test that loads an extension leaves `sys.modules` as it found
it" in [testing.md](testing.md)).

### The panel

**My hand** on the turn message is one button with two answers by who
clicked (the author, 2026-10-08): the active player gets the panel for
whatever the match asks them, the other player their hand pictured and
nothing to press. The panel is the view for `MAIN_ACTION` and
`CHOOSE_DEFENDER` (`TurnPanelView`), for `PATROL` (`PatrolView`), and
for the tech prompts (`TechChoiceView`, `TechConfirmView`) --
`view_for_prompt`'s table, the only place a kind becomes a view. **My
hand always shows the hand** (the author, 2026-10-09): where the turn
waits on its player's tech, My hand sends the hand pictured with
`TechGateView` under it -- **Tech** and **My deck** in place of the
turn's actions -- rather than the confirmation alone, which left a player
unable to see their hand before confirming. It is `view_for_prompt`'s
too, asked with `gate` for the two kinds a turn may open on
(`TECH_GATE_KINDS`), so a kind still becomes a view in one place.

The patrol panel asks "To end your main phase, assign patrollers." --
the model's ask, with no seat named because the panel goes to the asked
player alone -- and its button is **Lock in patrol zone** (the author,
2026-10-19, in place of "<name>, lock your patrollers: the main phase
ends." and **Lock patrol**).

- **One ephemeral message at a time, edited in place.** Each click
  answers through the service and the panel is built afresh from the
  new prompt's options, and **edited into the panel clicked**
  (`put_panel`). Where the click put something in public
  (`goes_public`: something said or moved, the turn's end, a base
  fallen), the click is deferred and the turn message brought up to
  date first -- so the panel's turn lines (below) carry what the click
  said -- and the panel edited through `edit_original_response`; where
  it put nothing in public -- a mode opened, a patrol slot, a tech pick
  before saving -- with `interaction.response.edit_message`. Every one
  of these goes through **the interaction's own webhook**, not the
  channel: it spends nothing from the channel's ~five-in-five bucket
  the turn message lives in (rate-limits.md). The bot cannot find an
  ephemeral message again, so every entry point (My hand, **Tech**,
  `/codex resume`) makes a fresh one and the cog never looks for an
  old panel. From 2026-10-09 to 2026-10-12 an action sent the panel
  afresh under the turn message posted again and deleted the one
  clicked, so the panel always sat below the board; the author went
  back to editing both (2026-10-12: "go back to editing the board and
  hand messages rather than reposting them"), and `/codex resume`
  brings the board back down when talk has pushed it up.
- **Discord's phone apps leave a new picture in an ephemeral message a
  grey box; nothing the bot sends fixes that** (2026-10-15 to
  -18). Every new picture in an ephemeral message -- the hand, the
  panel, the codex, `/codex card`'s own JPEG -- shows as a grey box of
  its size in the iPhone and Android apps, for both developers, while
  the desktop app shows it at once and the public board always loads.
  Not the format, not the size, not the edit in place (**My hand**'s
  fresh message stalls too). The phone app loads the picture the next
  time it draws the message anew: switching channels and back, or a
  click that keeps the picture (`kept_pictures`) while its words or
  buttons change.
  - **Tried and removed: a redraw** (#592, #616; removed 2026-10-17).
    Each new ephemeral picture was edited again with the attachments
    it already carried and nothing else, 1 s later and then 3 s later.
    The edit landed both times and the picture stayed grey, so an edit
    that changes nothing in the message does not make the phone apps
    draw it again, however late. It cost every player one request a
    picture, the desktop's included, for nothing, so it went.
  - **Tried and removed: the words changed invisibly** (#624; removed
    2026-10-18). The same redraw, 1 s after the picture, edited the
    message's words alone, a zero-width space put on their end or
    taken off. The edit landed and the picture stayed grey, so a change
    to the words that the eye cannot see does not do it either. What a
    click does that these edits do not is unproven: the click's edit is
    the interaction's own answer (an update of the clicked message),
    where the bot's edits went through the interaction's webhook, and
    its change is visible. The bot cannot answer an interaction nobody
    clicked, so that is not a fix it can send.
  - **What is left** is moving the pictures out of ephemeral messages
    -- a direct message to the player, which is an ordinary message
    and loads as the public board does, or a picture hosted elsewhere
    and named by its address -- and the author chose neither for now
    (2026-10-18): on a phone, a click that redraws, or a channel
    switched and back, shows the picture.
- **The turn's lines head the hand message, and no other ephemeral
  one** (the author, 2026-10-12: "add the turn log to the ephemeral
  message with the hand"; then "only in the hand message and the
  public turn message. Not in any other ephemeral messages"). A panel
  pictured with the hand -- the main phase, Appel Stomp's place, a
  stash and the tech gate (`TURN_LOG_KINDS`, `panel_parts`' `hand`)
  -- and the other player's hand (`send_hand`,
  **My hand** and `/codex hand`) open on "**This turn**" and the turn
  message's lines so far, quoted, above their own words
  (`Codex.with_turn_log`), so what the opponent did reads beside the
  hand without scrolling up to the board. A panel pictured with a side
  of the board, a hidden pile's choices or the codex -- the defender, a
  target, **Attack...**, the tech picker and the tech confirmation --
  does not, nor the deck, the codex browser or the undos; any other
  mode opened on the main phase's panel keeps it, its picture being
  the hand still. The first cut put the lines on
  every panel, so they would not come and go as the panel turned to a
  target, and the author narrowed it the same day. The lines are the ones the
  turn message carries, the cog's memory of the turn rendered at the
  door, and public, so nothing hidden moves. Past Discord's 2000
  characters the earliest fold into "*and n more*" as on the turn
  message, and the panel's own words are never cut; where this process
  has not seen the turn's lines (after a restart, until `/codex
  resume`), or the turn has said nothing, there is no log. A panel is
  edited only when its own player clicks, so its log stands as of
  their last click while the other player acts.
- **A panel is always drawn as an answer to something.** The author
  asked for it to stand alone rather than as a reply to the turn
  message (2026-10-09). Discord ties every message an interaction makes
  to the interaction -- a button's answer carries the message clicked
  (`interacted_message_id`), a follow-up the click's first answer
  (`original_response_message_id`) -- and its client draws that as the
  strip above the message; there is no field to leave it off, and an
  ephemeral message can only be made by an interaction. So the panel
  opened from **My hand** is drawn as an answer to the turn message,
  and keeps that strip through every edit.
- **Its picture is the hand**, numbered, greyed where it may not be
  played, each card's printed cost and by how much it is changed
  beside it where it is -- `render_hand` over
  `MainActionOptions.hand`, a field the prompt grew for it so the
  picture and the buttons read one list. **A target's picture is a
  side of the board, not the hand** (the author, 2026-10-09: the hand
  is no help choosing what to wither): the defender, obliterate's,
  sparkshot's and overpower's choices and an effect's `TARGET` are
  pictured with one player's panel alone, upright and at the board's
  scale (`render_side`, `PANEL_SIDE_KINDS`) -- the opponent's, or the
  asked player's own where every target the prompt offers is theirs;
  where the targets are on both sides, as Wither's may be, **both sides
  stacked** (the author, 2026-10-09), the stacked board seen from the
  player choosing (`render_board`'s `near`, the active player's by
  default) -- `side_shown`, since what is chosen from is on the table. Appel
  Stomp's place, about the player's own draw pile, keeps the hand.
  **Attack...** pictures the player's own side in place of the hand
  while the attacker is chosen, what may attack being on the table
  (the author, 2026-10-12), then the defender's the opponent's, and
  **Back** or the attack's end puts the hand up again. The hand is not
  kept beside a side through an attack: two pictures on one message
  are laid side by side at half the width, which the author ruled out
  for this (2026-10-12), so the hand is uploaded again when it comes
  back. An edit in place otherwise keeps a picture the message already
  carries (`kept_pictures`): a level bought, a building built or
  anything that changes the panel's text and not its hand uploads
  nothing -- the turn's lines over the hand are text -- and the hand
  is uploaded only where its picture changed, a card in or out of it
  or a cost or its greying moved with the gold.
  `render_prompt` gives the main phase no picture of its own (the
  board on the turn message is its board); the tech picker's is the codex with the
  picks framed in gold and counted (`render_codex`'s `picked`), the
  confirmation's the picks as a hand, alone (the author, 2026-10-12:
  "remove the hand from the 'confirm tech' view - need to see what's
  confirmed there").
- **The main phase is rows of buttons, not menus** (the author,
  2026-10-09, after a turn through the four selects step 4 built --
  Play a card..., Build..., Attack with..., Level up...). A message
  carries five rows of five buttons, and the panel fills them in three
  groups, each starting a row of its own (`TurnPanelView.place`): the
  **actions row** -- **Hire worker**, **Attack...**, then a button per
  hero that summons it or levels it up ("The standard game", below):
  step 10 gave the heroes a row of their own, since three did not fit
  beside three actions, and they came back when **Undo...** moved to
  the end; **the
  hand**, a button per card in the hand's order, "3. Bloom (2 gold)",
  numbered as the picture numbers it (`hand_numbers`) and disabled where it may not
  be played now, as the picture greys it, so the row and the picture
  agree card for card -- at most two rows (`HAND_ROWS`), a hand
  rarely being more than one; and **the board's row** -- **Build** per
  building that may be built now ("Build Tower (3 gold)"), and the
  next tech building up where it may not, disabled with why ("Build
  Tech II (4 gold): Tech I is destroyed", "...: needs 8
  workers") -- `BuildOption.next_up`, the engine's: a tech building
  not standing that is the first, or the one above a building its
  player has had, so a destroyed Tech I is rebuilt first and Tech II
  says so, where Tech III at the opening says nothing (the author,
  2026-10-11); placed after everything that may be done, so a full row
  gives it up first --
  **Detect...** where there is a tower, and each ability, in the
  card's own words ("Sacrifice Harmony: stop the music"), disabled with
  its reason where it may not be used now, unless its card is exhausted
  or arrived this turn -- and always last, in this order, **My deck**,
  **Codex**, **Show board**, **Undo...** and **End main phase** (the
  author, 2026-10-09; **Codex** 2026-10-10: "need to have the codex
  button in my hand's menu"; **Show board** 2026-10-15, "The resume
  path"), which `place`'s `last` never crowds out: a board's button
  gives up its place to them first. **Codex** answers as the turn
  message's does, in a message of its own beside the panel
  (`Codex.send_codex`), and so do the **Codex** under the other
  player's hand (`HandView`) and under the tech gate's. **Hire worker** and every **Build** are green and **Attack...**
  red, beside **End main phase**'s red (the author, 2026-10-09), so the
  panel's three kinds of spending read apart at a glance; the rest
  stay blurple or grey. **Level up...** opens the
  levels the hero may reach (the author, 2026-10-15): the panel turns
  into a button per level from the next one up to the card's maximum,
  each with what it costs -- "Level 4 (2 gold)", ": new band" where the
  level starts one and ": max level" on the last, off the card -- those
  the gold does not reach greyed out and disabled (the author,
  2026-10-15: what the next band would cost is worth seeing before it
  is affordable), and **Back**, and the one click buys every
  level up to it in a single action (`levels`). Opening it spends nothing
  public, like **Attack...**. A hero one level short of their max skips
  it (the author, 2026-10-15): the picker would hold that one level and
  nothing greyed out beyond it, so the hero's button is **Level up
  Jaina to max level (1 gold)** and buys it at once. It was a level a click before (2026-10-09),
  which made a player reaching a band press once per level, each press
  a write to the turn message; `HeroOption.level`, the hero's level
  now, is what the buttons count from. **Attack...** turns the panel into what may attack,
  one button each as `ref_label` names it ("Older Brother 2/2"), and
  **Back**; the attacker's button asks the defender next, in the same
  panel, and opening the mode spends nothing public, like Hire's and
  Undo's. What does not fit the five rows is left out, the groups
  placed first having the earlier claim -- in practice rarely: the hand
  is cut at ten distinct cards, and the board's row loses what passes
  two -- the last five take the rest of it -- where the hand needs a
  second row
  (`test_the_main_phase_is_rows_of_buttons`,
  `test_a_big_hand_leaves_the_boards_row`). Every button that answers
  with one choice off the options is a `PanelButton` carrying that
  choice -- `("play", slug)`, `("attack", ref)` -- so the fakes press
  it by what it chooses, never by its label.
- **Built from the options and nothing else.** A control the engine
  says no to is disabled with its reason as its label ("Hire a worker:
  already hired", "Attack: nothing can attack", "Summon Orpal Gloor:
  Hero limit is 2", "Vandy Anadrose: at its max level" -- the
  author's wording, 2026-10-11); a group with nothing to offer is one
  disabled button saying why ("Nothing can be built now", unless a
  next tech building already says why), so the
  panel keeps its shape. **Hire worker** turns the panel into the hand, a button
  per card numbered as the picture (the one hired with is trashed
  unseen), the question the menu's placeholder used to carry written
  under the prompt's ask (the view's `caption`, which `panel_caption`
  reads, as the tech and patrol views' are); **Undo** the choices
  `history.undo_targets` says are open. The attacker is named the same
  way over the defender's buttons, and each is labelled with why it is
  legal -- "squad
  leader", "patroller", "flying", "unstoppable vs. base", in brackets
  after its name -- and nothing where the defender has no patrol at
  all, the button the name alone (the author, 2026-10-15) -- which is the engine's
  (`defender_rows`, carried as `DefenderOptions.why`), not the view's.
  A building among them is green and the rest blurple, and every
  building's label, here and on any other button, carries the HP it has
  left -- "Tech I (5 HP)", "Base (17 HP)", the base capitalised on a
  button though not in the narration -- read from `building_hp_left`;
  a building's reason shares its HP's bracket, "Base (20 HP, flying)".
  The reasons are kept short for a button -- "stealth vs. units",
  "unstoppable by tech 0", "Demon, unstoppable", "unblocked" (the
  author, 2026-10-15).
  **Nothing the turn panel asks is a menu any more**: the tower's
  detection and the three choices inside an attack -- obliterate's tie,
  sparkshot's neighbour, overpower's excess -- are buttons too, what
  their placeholders said (how many obliterate has left, how much of
  sparkshot's damage is still to place, how much overpower carries
  over) written under the ask as the view's caption. The author's word
  came in three parts through 2026-10-09 -- the main phase, then the
  hire's card, the defender and the targets, then the rest -- and the
  menus left on the Codex bot are the patrol lock's two and the tech
  picker's, below, and the codex browser's views.
- **An effect's questions are the same panel going on** (step 6): a
  `TARGET` is a button per thing the part may choose, each labelled
  with whose it is, what it costs in resist and whether the flagbearer
  rule forces it, under the ask, which says what the part does; Appel
  Stomp's place and the upkeep's order are buttons too.
  The abilities are buttons on the board's row -- they shared the last
  row's menu with the hero's levels until 2026-10-09. One the engine
  says no to is there too, disabled, its reason in brackets before what
  it does ("Vir Garbarean (your draw pile is empty): look at the top
  card of your draw pile"), so the cut to 80 characters never takes the
  reason, and placed after every one that may be used, so a full row
  gives these up first: an ability that vanished without a word left
  the player guessing why (the author, 2026-10-11). **Except a card
  that is exhausted or arrived this turn**: the board already shows
  it, so its ability is left off rather than greyed (`EXHAUSTED` and
  `ARRIVED`, the two reasons the panel reads); every other cost still
  shows. The reasons are short (the author, 2026-10-11): "no target"
  (`NO_TARGET`, a spell in the hand's too), "not enough gold", and for
  runes a note card by card (`RUNES_SHORT`): how many a card that keeps
  gaining them needs ("needs 2 blood runes"), and that one given them
  once has spent them ("javelin already thrown", "no +1/+1 runes
  left"). Vir's three deck
  abilities say "your draw pile is empty" rather than "no target", and
  his middle one, on a top card that can't be played, says that much
  and not which card or why -- the card is hidden. An ability that
  grants stealth is refused while its card already has it -- "already
  has stealth" -- since stealth does not stack and Calamandra's second
  use would be two cards discarded for nothing (the author,
  2026-10-12). The panel's picture
  stays the hand.
- **Copies of one card are numbered, on the button and on the board**
  (the author, 2026-10-11, over two buttons both reading "Your Bone
  Collector 3/3"). Wherever a player has more than one copy of a card
  in play, `formatting.copy_number` counts them from 1 in the order
  the play zone holds them -- the order they came into play, since
  nothing reorders it -- patrolling or not; `ref_label` writes the
  number after the name, "Bone Collector #2 3/3", so every menu that
  names a unit carries it, and the board draws the same "#2" on a
  white tag across the card's top edge, on one line with the stats
  pill and a little smaller than it (`Lying.copy`, `copy_tag`; the
  author, 2026-10-11). A copy keeps its number while the ones before it stay
  in play. The far panel is turned round whole, so its tags are drawn
  upside down before the turn and read upright after (`turned`, passed
  down from `render_panel`): a number is matched to its button, so
  unlike ARRIVED it must read the right way up. A board with no copies
  is byte-identical to before. A first try named copies by their place
  and state ("2nd, arrived") from what the picture already showed; the
  author chose plain numbers marked on the board instead.
- **The patrol lock is two menus, not five.** A message carries five
  rows of components; five slot menus would leave no row for **Lock
  patrol**, which stands alone in its row as the misclick guard
  (decision 11). So one menu picks the slot, each named with what holds
  it, and the next what patrols it -- the candidates not placed
  elsewhere, or nobody -- moving on to the next empty slot; **Clear**
  empties all five. Nothing is applied until Lock.
- **Who may click it**: the player it asks, alone -- anybody else is
  refused ephemerally (`NOT_YOUR_PANEL`). A stale panel -- a second one
  opened before the first moved the game on -- is refused with the
  driver's own words (`STALE_CLICK`), since the driver checks every
  action against what the match is waiting on.

### The tech choice on Discord

The Lock that ends a turn turns the panel into the tech picker, sent
under the new turn message with nothing above the picker's own lines --
how many to tech, the deck, what is picked so far: the picker is what
says the turn is over (the author, 2026-10-12).
**Tech** on the turn message reopens it -- for the player whose turn it
is not, and for the active player only while their own turn waits on
their tech (below) -- all through the opponent's turn; each **Save tech**
replaces the last, privately: **nothing is said in the channel** -- not
the cards, and not that a choice was made. The choice is announced in
its owner's ready phase alone, as "puts 2 tech cards into their discard
pile" (the author, 2026-10-08).

**A choice saved is its picks, not the picker** (the author,
2026-10-12: "once tech has been selected, remove the codex view and
the save tech button"). After **Save tech** -- and from **Tech**, while
a saved choice stands -- the panel is `TechSavedView`: the picks
pictured alone, as the confirmation pictures them, "Your tech: ...",
**Change** and **My deck**. Change opens the picker in place on the
saved picks; nothing is answered until it saves again. Which of the two
a `TECH_CHOICE` shows is `TechOptions.saved` -- the owner's
`tech_choice` is not `None` -- since **Tech nothing** saves no picks
and `picks` alone cannot tell that from a choice never made.

**One card at a time, each card once** (the author, 2026-10-10). The
menu names each card by `card_label` -- "Centaur 3/4", no gold cost
(the author, 2026-10-11) -- offers each card the shown view holds
once, whatever its copies, and takes one pick a click: "Choose your first card of 2...", then
"...second...". A second copy is the same card picked again while the
codex has another left; the caption counts it ("Iron Man ×2"), and
**Clear** starts the picks over. Once every pick is made the menu is
closed, saying so. The first reading had a line per copy and cut the
menu at Discord's 25 -- which, under Everything, left most of a
standard game's thirty-six card codex unreachable; a view of more
cards than one menu holds is now split over as many menus as it needs
(`MENU_ROWS`, three, each labelled with the cards it runs from and to),
none cut short. **Save tech** is held to the bounds, and where ten
workers allow none (UMR p. 5) **Tech nothing** saves the empty choice;
the ask says so by its range. **The ask is the count and when it is
owed** -- "To start your turn, you must tech 2 cards." in the player's
own turn, "Before your next turn, you must tech 2 cards." while the
choice stands through another's (`standing_prompts`), and "... tech 0-2
cards." where the workers allow none (the author, 2026-10-11,
2026-10-20); under the hand's picture, before the picker is open, the
gate's caption says how to open it, on the ask's own line (its
`caption_runs_on`) -- "Click *Tech* to open the tech menu.", where it
was "**Tech** opens it; the turn's actions come after it." on a line
of its own. The first reading named the
player, said the cards came from the codex, said when they reach the
discard pile and, where none was allowed, why; read at the start of the
player's own turn, "when your next turn begins" was confusing, and the
rest was more text than the choice needed: the panel is the player's
alone, the turn message names whose it is, and **Tech nothing** is the
button for none. The ask carries no dash (the author, 2026-10-10).

**The picker says nothing of whether a card could be played now.** A line
per card saying what it needed ("needs tech II building", "needs River
Montoya in play"), in the menu and under each card in the picture, was
built and looked at, and taken out (the author, 2026-10-10).

The caption is the picks alone ("Your pick: Iron Man, Eggship."): a
line counting the deck by tech level was built and taken out (the
author, 2026-10-12) -- **My deck** shows the deck the picks join.

**The picker is narrowed by a Show menu** (the author, 2026-10-09: the
whole codex at once is too much to pick from -- "need a way to filter
and look just at several pieces, by tech level, by spec"). Its first
row is the same menu the Codex button carries -- Everything, Tech I to
III, Spells, and in the standard game one spec (`codex_view_menu`, over
the engine's `codex_views`), with the picker's opening view first (below);
in the basic game there is one view, the whole codex, and no menu
-- and choosing one re-renders the picture
and rebuilds the cards' menu from that view alone
(`codex_view_rows` over `TechOptions.codex`, so the picker reads the
prompt's list, narrowed by the engine, and computes nothing). **The
picks are kept across views**: a card picked under Tech I stays picked
while Tech II is shown; the caption lists every pick ("Your pick: Iron
Man, Eggship."). It does not say which view is shown: the Show
menu above the cards already does (the author, 2026-10-11).
Save is held to the bounds by the driver whatever view is shown. A change of
view is the picker's own edit through the interaction's webhook and
spends nothing public, like a pick before saving. Save sends the picks
whatever view is shown. After Save, or from **Tech**, the picker opens
on its opening view again: which view was shown is not remembered, since
the picker is an ephemeral message made afresh each time.

**The picker opens on the part a choice is likeliest made from** (the
author, 2026-10-20): before the player's first Tech II building, every
Tech I card and every spell ("Tech I & Spells"); once one is built, the
spec chosen for it -- its Tech II and III -- and every spell, every
spec's ("Anarchy Tech II & III, Spells"). A Tech II destroyed since
still counts, its spec being kept (`tech2_spec`); a standard game's
Tech II cannot be built without one. The basic game's codex has no
focused view: it opens whole, with neither a Show menu nor **Whole
codex** (the author, 2026-10-20 -- before, it was focused as the
standard game's is, Tech I & Spells and then its one spec's Tech II and
III and the spells). The spells are
every spec's, not the Tech II spec's alone (the author, 2026-10-20).
**Whole codex** beside the buttons shows everything, and on any other
view the same button, named for the opening view, goes back to it. The
reading is the engine's -- `tech_focus_view`, and `tech_opening_view`,
which falls back to Everything where the focused view has no copy left,
so the picker never opens on an empty menu -- carried on the prompt as
`TechOptions.opening` and `TechOptions.views` (the Show menu: the
focused view first, then `codex_views`), so the view reads its options
and computes nothing. The focused view is the picker's alone; the Codex
button's menu is unchanged.

From the third turn on the new turn opens on its player's confirmation:
the new turn message says it waits on them to confirm their tech (the
cog's caption, `TECH_WAIT`, gone once the ready phase has run -- worded
"to choose their tech" where the picker is asked instead, because they
never picked, or because the game is a test game). It does not name
**Tech**, which is under the message already (the author, 2026-10-19:
"The second tech is redundant"). **Tech** on the turn message, pressed by the player whose
turn it is while the turn waits on their tech, opens it at once:
`TechConfirmView` -- the picks pictured, **Confirm** and **Change** --
or the picker (the author, 2026-10-09: "clicking tech should let them
pick tech"), whose save begins the turn with nothing to confirm; at any other point in their own turn it says the tech is
not theirs to press now. **My hand** opens the confirmation at once
where the picks were saved, the picks pictured alone (the author,
2026-10-10: the step between was a click every turn for nothing;
2026-10-12, the hand taken off it, which showed it before the picks
from 2026-10-09's "clicking my hand should always show a player their
hand", so what is confirmed is what is seen). Where nothing was picked it
sends the hand pictured with `TechGateView` under it, whose Tech opens
the picker in place.
Confirm runs the ready phase and the upkeep, and the panel becomes the
turn's actions, the hand pictured on it, under the turn message posted
again. The prompt asked for the
confirmation to be sent "as the follow-up to the opponent's Lock when
they are present"; a follow-up reaches only the clicker, so it is not
sent to the other player -- the turn message's mention and its caption
point them at Tech instead.

### The turn message, edited

**Nothing the Codex bot posts uses " -- "** (the author, 2026-10-19):
a heading takes a colon ("**Turn 7**: …", "**Codex game 5**: …"), an
aside brackets or a comma, and a second clause its own sentence. The
dashes stay in comments and docstrings, which nobody in a game reads,
and in `botlog/`, whose notices fool-bot posts too.

Each turn's message is posted when the turn begins: its text
"**Turn 7**: @perrytom (Bashing)" -- the model's heading, whose turn
as a mention, which that post pings and no later one does -- then the
turn's lines, the model's with
their tokens rendered at the door; the board as its picture; and
**My hand**, **My deck**, **Tech**, **Codex**, **Undo**, **Swap view**
-- and no **Concede**, which is under the hand menus alone (below,
"The end of a game"). **After
each action it is edited in place** with the new lines and the
re-rendered board, through the gate (`refresh_match_image`,
`BoardRefresher`) -- one of the channel's requests, coalesced with the
gate's window where clicks come faster than it. The text stays under
2000 characters: past that the earliest lines fold into "*and n
more*", since the board carries the position.

- **Back to editing** (the author, 2026-10-12). From 2026-10-09 the
  message was posted again at the foot of the channel after every
  action and the old one deleted, so the table was always the channel's
  last message with the panel under it -- two of the channel's requests
  an action, with no coalescing, since the panel had to go up under
  the board. The author went back to editing both the board and the
  panel; when talk in the channel has pushed the board up out of sight,
  `/codex resume` posts it again at the foot ("The resume path").
  `/codex board` shows the board too, but to the asker alone and with
  no buttons.
- **Each finished turn is pinned, the current one never** (the author,
  2026-10-09). The message pinned at a turn's start would be deleted at
  its first action, and pinning each post again would put the pin's own
  notice -- a system message -- under the board every action, which is
  what the post is for. So a turn's message is pinned once the turn
  ends and it stands (`stand_turn_message`), **before** the next turn's
  message is posted, so the notice lands above the new board; the pins
  read as the game's history turn by turn. The last turn of a finished
  game is pinned the same way, before the winner's line. An undo to the
  previous turn deletes that turn's standing message, and its pin with
  it. Discord caps a channel's pins; a pin it refuses is logged and the
  turn stands unpinned.
- **A write that fails is the gate's to log**: the action is saved,
  the panel still goes up, and the message stands a board behind until
  the gate's next write or `/codex resume`.

- **The heading is the model's, and it is not narration** (the author,
  2026-10-08). "**Turn 7**: @perrytom (Bashing)" is
  `codex.formatting.turn_heading(match)`: the turn, its player
  *addressed* -- `{to:n}`, a token the cog draws as a mention and plain
  text as the name -- and their team, `team_name(player.specs)`, as the
  nameplate names it: one spec in the basic game, a colour's deck by its
  name ("Blood Anarchs") and a mixed team by its specs
  ("Fire/Feral/Bashing"). The cog puts it at the head of every turn message and
  never folds it, so it reads even while the turn waits on its tech, and
  after a restart that lost the turn's lines. The model used to open
  each turn with a narration line of its own as well ("**Turn 7** --
  perrytom's turn."), which under the heading said it twice; that line
  is gone. **The turn's end is narration**: "**End of turn 7**:
  perrytom (Bashing).", naming the player and their deck as the
  heading does (the author, 2026-10-08), the
  last line of `begin_tech`, so the model's own transcript still reads
  turn by turn and the turn's message stands with its close; the event
  log's `turn_ended` records which turn. The cog closes a turn's message
  on that step (`split_at_turn_end`, the group `BEGIN_TECH` closes),
  never by comparing turn numbers of its own.
- **The end of a turn is a joint the frontend names.** An action is
  never stopped part-way (the journal records it whole), so a picture
  of the position where the turn ended cannot be a stop. Instead
  `driver.advance` takes `draw_after` -- the Discord batching names
  `BEGIN_TECH` -- and closes a group there carrying the position as it
  stood (`history.position`, no snapshots). The old message's last edit
  is that group's lines and that board, **without its buttons**, and it
  stands as the turn's summary; what the next turn's start said goes on
  the next message. The standing picture lights the player whose turn
  it was.
- **Two messages, one gate.** The gate (`BoardRefresher`) only ever
  writes the current turn's message (`message_of`). Every post of it
  is made under the gate's own lock, so no edit of the gate's lands on
  a message on its way out, and handed to the gate after. The old
  message's last edit is written by the cog directly, under the same
  lock, and then the gate is forgotten, so its next write is the new
  message's. The game's end is the same last edit, then one public
  line -- the model's "wins" sentence -- with the final board,
  rendered once and uploaded twice.
- **What the cog remembers**, in memory only: the turn's lines, and
  each recent turn's *first lines* -- what its message said when it
  first went up, before the turn's snapshot: the ready phase's lines
  where the turn owed no tech, nothing where it waited on its tech,
  since the tech answer's lines are the journal's then -- which is what
  an undo puts back above what it says. After a restart
  neither is known: the gate leaves the message's text alone until the
  turn ends or `/codex resume` re-posts the table.

### The requests per click

Measured with the fakes, and held on every click of the whole-game test:

| Click | The channel's bucket | The interaction's webhook |
| --- | --- | --- |
| My hand, the active player | **0** | 2: the private defer, the panel its follow-up, the hand pictured on it -- with **Tech** alone under the picture while the turn waits on their tech |
| My hand, the other player | **0** | 2: the private defer, the hand its follow-up |
| Tech under the hand, or Tech on the turn message, while the turn waits on its player's tech | **0** | 2: the defer and the panel's edit, or the private defer and the confirmation its follow-up |
| An action in the main phase (play, hire, build, summon, level, attack, the defender) | **1**: the turn message edited through the gate | 2: the defer, the panel edited in place |
| A choice that moves nothing public and draws nothing (a patrol slot, Hire worker, Undo... opening its choices) | **0** | 1: the panel's edit |
| A choice that moves nothing public and draws a picture (End main phase, a tech pick before saving, the tech picker's Show menu and Clear, Change on saved picks, Attack... picturing what may attack, a view chosen in the codex's menu) | **0** | 2: the defer, the panel's edit |
| Save tech | **0**: nothing is said until the owner's ready phase | 2: the defer, the picker edited to the saved picks |
| Lock in patrol zone (the turn's end) | **3**: the old message's last edit, its pin, the new one's post | 2: the defer, the panel edited into the tech picker |
| The attack that destroys a base | **3**: the last edit, its pin, and the winner's line with the board | 2 |
| Concede, the first click | **0** | 1: the confirmation |
| Concede the game (step 8) | **3**: the last edit, its pin, and the winner's line with the board and Rematch -- then the channel's move to Codex Archive, on the channel's own route | 1 |
| Rematch (step 8) | **1**: the new lobby -- after the channel's move back to Codex Games, on its own route | 1: the button taken off |
| Undo to the start of the turn | **1** | 2 |
| Undo to a point of the turn (the menu) | **1** | 2 |
| Undo to the previous turn | **1** to ask (the public question), then **3** on Agree: the restored turn's post, the current one's delete, the previous turn's standing one's delete | 2 on Agree: the question answered in place, the fresh panel |
| Take back the end of my turn | **3**: the restored turn's post, the current one's delete, the restored turn's standing one's delete | 3: the Undo menu sent, the click answered in place, the fresh panel |
| A lobby click -- a seat taken, the mode or the variant changed, a third seat's pick (multiplayer step 4) | **0** | 1: the lobby edited in place |
| **Swap view**, or `/codex side_by_side`, on a table of several | **1**: the board through the gate | 1: the defer, or the ephemeral answer |
| My hand, **Tech** of any seat of a table (step 4) | **0** | 2, as the duel's |
| **My deck**, **Codex** -- of any seat, from the turn message, the hand, the panel or the tech picker | **0** | 2: the private defer, the picture its follow-up |
| Lock in patrol zone on a table's turn, the undo to the previous turn, a table's rematch | as the duel's: **3**, **1** then **3**, **1** | as the duel's |
| **Repair base** on a free-for-all's panel | **1**: the turn message through the gate, as any action | 2: the defer, the panel edited in place |
| A slot or a patroller chosen in the patrol view, an opponent's open slot among them | **0** | 1: the panel's edit |
| Lock in patrol zone that lends | **3**, as the duel's Lock | 2, as the duel's |
| An action by either teammate of a dragon (multiplayer step 6) | **1**: the turn message through the gate | 2: the defer, the clicker's own panel edited in place |
| A dragon teammate's stale click -- the team moved on, or the other's action stands part-way | **0** | 2: the defer, the panel edited in place to the prompt as it stands |
| The first lock of a dragon's turn | **1**: the turn message through the gate | 2: the defer, the panel edited to the waiting panel |
| The second lock (the team's turn ends) | **3**, as the duel's Lock | 2, as the duel's |
| **Tech** by a dragon seat while the teammate owes a choice | **0** | 3: the private defer, the clicker's own answer its follow-up, the teammate's picks (or that they have not chosen yet) |
| **Switch to <name>** on a dragon test game's panel | **0** | 2: the defer, the panel edited in place to the other seat's |
| Concede in a dragon, the second click | **1**: the public question to the teammate | 1: the confirmation edited |
| Its **Agree** | **3**, as the duel's concession | 1: the question edited in place |

**A click behind a busy game is acknowledged before it waits.** Every
click on a game holds its lock across the whole answer -- the board
written, the panel drawn and edited --
which can take longer than the three seconds Discord waits for a
click's first response. The next click queued behind it then failed on
its own `defer` with a 10062, its action never applied: **Level up**
pressed on the live host on 2026-10-11, most likely while the click before it was
still putting its pictures up. The apply was ruled out by measure (about
10 ms a click to the end of a 26-turn game, the save included), which
left the wait. So the panel's views, `UndoView` and `UndoConfirmView`
-- and since 2026-10-20 the turn message's (`TurnMessageView`), the
other player's hand menu (`HandView`, and the dragon's `WaitingView`
under it) and the codex browser (`CodexBrowser`) -- set
`acknowledges_while_waiting` (`botkit.views.GameLockedView`): a
click that finds its game's lock held is deferred at once, and then
waits. Every answer those views make works on a click answered already
-- `edit_clicked` edits the message clicked through the webhook
(`edit_original_response`), `send_answer` sends a follow-up,
`acknowledge` skips a defer already made (`cogs/codex_views/base.py`).
The cost is one webhook request, and only on a click that would
otherwise have waited unanswered: an in-place edit becomes the defer
and the edit; an action's two stay two, since its defer is the one
it would have made anyway. Nothing in the channel's bucket changes. The
lobby and D12 Ball's views do not opt in -- their callbacks answer with
`interaction.response` directly -- and wait as before. The turn
message's buttons did not either until **My deck** and **Codex** on it
could be the click queued behind a panel putting its pictures up, with
nothing sent while it waited (the author's review of PR #663).

**A picture is acknowledged before it is drawn.** Every answer that
pictured something -- the panel (`show_panel`, through `panel_parts`),
the other player's hand (`send_hand`), a dragon's waiting panel
(`put_waiting`), the deck, the codex and a view chosen in its menu, the
tech picker's redraw (`_put_picker`), **Attack...**'s side of the board
-- drew it and then sent it, or the edit carrying it, as the click's
first response. On the live host on 2026-10-20 **Codex** under the
hand's picture, while the turn waited on a tech choice
(`TechGateView`), failed on that response with a 10062 -- not behind a
busy game, since a panel's click waiting on the lock is deferred first,
so the click's own draw and upload, or the event loop held up as long,
outlasted the three seconds. Now each draws through
`drawn_acknowledged` (`cogs/codex_views/base.py`): the click is
acknowledged first and the drawing runs beside the acknowledgement's
round trip (`asyncio.gather`, the acknowledgement started first) --
privately, as a "thinking" message the answer then fills as its
follow-up, where the answer is a message of its own
(`acknowledge_privately`), and as a plain defer where it edits the
message clicked (`acknowledge`). A click deferred already -- by the
lock, or by an action putting something in public -- is left as it is.
The cost is one webhook request on each such click, counted in the table
above; nothing in the channel's bucket. A choice that only changes the
panel's buttons (**Hire worker**, **Undo...**, a patrol slot) draws
nothing and is answered in one, as before.

**How late a click was acknowledged is logged before the
acknowledgement goes out** (`_log_click_age`: the host's clock against
the interaction's id, Discord's, so a host clock that is off by a second
is off by that second here): INFO, console-only, one line a defer. A defer that fails
with a 10062 fails before any picture's line is logged, so this is the
line that says whether the click arrived late -- the lock, a stalled
event loop -- or the bot was slow after it.

The gate's full-image link adds one settling edit after a burst of
clicks, at most one per interval, as it does for D12 Ball (step 3 turned
the link on for Codex); the fakes upload nothing it could link, so the
table counts the board's own writes. A turn of a dozen clicks is at
most a dozen edits, fewer where the gate's window folds a burst into
one trailing write.

### The undos, and who may take each

**Undo** on the panel offers what `history.undo_targets` says is open
(`GameService.undo_targets`) under the fine undo's menu, the points
`history.undo_points` offers (`GameService.undo_points`); the cog
decides nothing about what a snapshot or the journal holds. **The patrol lock carries it too** (`PatrolView`,
beside **Clear**): **End main phase** is the one click that leaves the
main phase without locking anything, and a player who pressed it too
soon had no way back -- the snapshot is the main phase's start, so the
undo to the start of the turn reopens it. Both panels open the same
undo mode (`_open_undo`); from the patrol lock, **Back** puts up the
patrol as it was assigned so far (`back_to`) rather than the position's
fresh one, since the assignment is the view's alone until it is locked.
**The turn message carries Undo as well** (`TurnMessageView`, between
**Codex** and **Swap view**; the author, 2026-10-10), so an undo needs
no panel open: it answers the active player alone, ephemerally, with
`UndoView` -- the same two choices, no **Back**, since there is no
panel to go back to -- and tells the other player it is not theirs.
`UndoView` holds the seat and the turn it was opened on and refuses a
click once the game has moved on, since an ephemeral message outlives
the turn it was asked on and **To the start of my turn** would
otherwise undo a turn it was not opened on. Opening it is the click's
own response and spends nothing in the channel; each undo then costs
what it costs from the panel (the table above).

- **To the start of my turn** is the active player's alone, with nobody's
  consent: `GameService.undo_to_turn_start` restores the turn's snapshot
  and saves once; the turn message is edited to its first lines
  and "Undone to the start of the turn." (`history.UNDONE`) and the
  restored board, and the panel edited in place from the restored
  prompt -- the tech confirmation where the turn opened on picks made
  during the other's turn, the picker where it opened on the picker,
  whose answer runs the ready phase again and posts its lines under
  the undone line (the author, 2026-10-10).
- **To before an action of this turn** -- the fine undo's menu, above
  the two buttons wherever they are offered (the panel's undo mode, the
  patrol lock's, the turn message's `UndoView`), one option a point,
  newest first and at most a select's worth (`undo_menu`) -- is the
  active player's alone too, since nothing it takes back exceeds what
  the start of the turn takes back unasked. An option is labelled by
  the cog, `Codex.undo_choices`: the action's number and the first line
  it said with its tokens as words, since a select's option carries no
  markup (`CodexTokens.plain`: the seat's name, a card's name bare) --
  "2. perrytom plays Timely Messenger for (1): 1/1." -- or, for the one
  main-phase action that says nothing, its button's own name (**End
  main phase**, `SILENT_ACTIONS`). Its value names the point and the
  journal's length it was offered at, and the model refuses a pick the
  turn has moved on from. `GameService.undo_to` saves once and the cog
  does what the turn-start undo does (`_own_undo`): the turn message
  edited -- its first lines, then `result.lines`, which for this
  undo are the kept actions' lines and "Undone some actions."
  (`history.UNDONE_SOME`), so the message reads as the turn now
  stands -- and the panel edited in place. The line names no action
  number: the numbers are the menu's, and on the message, where the
  undone lines are gone, "before action 8" read as nothing (the
  author, 2026-10-13).
- **Take back the end of my turn** is on the turn message's **Undo**
  for the player who ended the turn before -- the one undo open to a
  player whose turn it is not -- while `GameService.end_of_turn_owner`
  names them (in a test game, the one person holding both seats), and
  needs nobody's consent: the other player has done nothing but open
  their turn. `Codex.undo_end_of_turn` makes the restored turn current
  as the undo to the previous turn does (`_previous_turn_back`): its
  message posted at the foot of the channel with its lines and "The
  end of the turn is taken back." (`history.UNDONE_END`), this turn's
  message and the restored turn's standing one deleted, and a fresh
  panel -- the patrol -- for its player. A click on the other player's
  open panel is refused by the model as stale (`driver.STALE_CLICK`).
  Once it is closed, **Undo** tells the player who ended the turn
  before "Your opponent has already started their turn."
  (`OPPONENT_STARTED`, off `history.previous_turn_owner`), whatever
  closed it (the author, 2026-10-13); anybody else whose turn it is not
  is told it is the active player's.
- **To the start of the previous turn** unwinds the opponent's turn
  too, so it posts a public question naming them (`UndoConfirmView`):
  **Agree** is the opponent's -- or a game helper's, behind the helper's
  confirmation -- and never the asker's; **Refuse** is either player's.
  The question holds the turn it was asked on and is refused once the
  game has moved past it. On Agree, `undo_to_previous_turn` restores the
  older snapshot; the restored turn's message is posted at the foot of
  the channel with its first lines and the undone line, the restored
  board and its buttons; the current turn's message is deleted, and so
  is the previous turn's standing one, pinned until then
  (`CodexGame.previous_turn_message_id`, a record field step 4 added,
  `None` in an older save), since that turn is current again; and the
  opponent, now the active player, gets a fresh panel under it. Where
  the previous message is not known (an older save, or a second such
  undo in a row), there is nothing more to delete. Not persistent:
  after a restart the asker asks again.

### The resume path

A restart loses every panel -- they are ephemeral and live in the old
process -- and nothing else: the question is the model's (`pending`).
The turn message's buttons are re-armed from `turn_message_id`, so **My
hand** after a restart asks the same question with the same options
(`tests/test_codex_resume.py`, including a declared attacker waiting on
its defender). `/codex resume` runs any step the bot owes, posts the
turn message again at the foot of the channel -- the old one deleted,
the player whose turn it is pinged -- and hands the clicker their panel
afresh -- the
actions for the active player, the open tech picker for the other.
**It is also how the board is brought back down** when talk in the
channel has pushed it up (the author, 2026-10-12): with no restart
behind it there is no step owed and the turn's lines are still known,
so all it does beyond the post is the ping and the fresh panel.

**Show board** does the same from the hand menu, with no command to
type (the author, 2026-10-15: "Codex hand menu should have a show
board button that reposts the board and also a new hand menu below").
It is under the other player's hand (`HandView`, and so under a
dragon seat's `WaitingView`), under the tech gate (`TechGateView`) and
among the main-phase panel's last buttons, and `Codex.show_board`
answers all three: the click deferred, the turn message posted again
at the foot of the channel through `post_turn_message(replace=True)`
-- the old one deleted -- then the hand menu
**My hand** would answer the clicker with (`send_hand_menu`: the panel
for the active player, the hand for the other) sent afresh as the
click's follow-up, so it sits under the board, and the menu pressed
deleted through the click's webhook, so one stands. It runs no owed
step, as `/codex resume` does: a hand menu is only up while the
process that sent it is, so there is none to run. **Where the turn
message is the channel's last message already** (`last_message_id`,
read off the cache, no request), it is not posted again -- a post and
a delete of the channel's bucket for nothing (rate-limits.md) -- and
the hand menu alone comes again. **The repost pings the players whose
turn it is where somebody else pressed it, and nobody where one of them
did** (the author, 2026-10-18, going back on 2026-10-15's "nobody
pinged"): the message it deletes is the one whose post pinged them, and
a mention in a deleted message is lost -- kime, in a free-for-all, was
never pinged for their turn after another player pressed Show board.
Like `/codex resume`'s, a repost
after a restart, before this process has seen the turn's lines,
carries the heading alone.

## The end of a game

Step 8 is what a game needs after its last turn ("Finishing a game" in
the worksheet). **No statistics and no archive export for this bot**
(the author, 2026-10-07): a finished game's channel is moved out of the
way and nothing is written from it.

- **A game ends with a winner one of two ways**: a destroyed base
  (`codex.flow.turn.damage_base`, UMR p. 2), or a concession
  (`codex.flow.turn.concede`). A concession is the model's: the seat
  conceding loses, the other wins, `MatchState.conceded` remembers who
  gave up -- a saved field step 8 added, `None` in an older save -- and
  the match waits on `GAME_OVER`, whose ask is the winner alone,
  "{player:1} wins!", however the game ended -- the turn's lines have
  said how -- posted as a heading under the final board (the author,
  2026-10-15). Either
  seat may concede,
  whoever's turn it is; refused once the game is over.
- **A concession is not an action the journal records.** It answers no
  prompt -- it is open to both players at any moment -- so it is a door
  of the service's own, `GameService.concede`, as the undos are,
  rather than a `PromptKind`. Nothing is undone past a finished game
  (`history.undo_targets`), so there is nothing for the journal to
  replay.
- **The record follows the match in the same save**: `GameService.persist`
  finishes the record (`CodexGame.finish`, `GameStatus.FINISHED`) once
  its match has a winner, however it ended, so nothing downstream
  compares the two. `/codex resume`, Swap view and the panel all stop at
  a finished record.
- **Concede is under the hand menus, never on the public turn
  message** (the author, 2026-10-18: "remove the concede button from
  the board, it should only be in the hand button"). It sat on the turn
  message until then, a red button beside the board that anybody's slip
  could press. It is now under every menu **My hand** opens: the main
  phase's panel, after **End main phase** among its last buttons
  (`TurnPanelView`), the other player's hand (`HandView`, and so a
  dragon seat's `WaitingView`) and the tech gate (`TechGateView`) --
  `concede_button`, which gives none in a free-for-all. The panel's
  other modes -- a defender's choice, the patrol, the tech picker --
  carry none: the player concedes from the main phase, the hand, or
  `/codex concede`. A busy panel defers its click first, so the
  confirmation goes out as a follow-up there (`send_answer`).
- **Concede is the clicker's own side, behind a second click.** **Concede**
  under a hand menu and `/codex concede` both answer ephemerally with
  `ConcedeConfirmView` -- **Concede the game** or **Cancel** -- held to the
  seat it was asked for (in a test game, the side whose turn it was) and
  to the person who asked. No helper concedes for a player. The first
  click spends nothing public; the second is the game's end below.
- **The end on Discord** is what step 4 built for a destroyed base, with
  two things after it: the turn message's last edit without its buttons,
  pinned as every finished turn is, the public line naming the winner with the final board -- now carrying
  **Rematch** (`RematchView`, persistent, its message kept on the record
  as `final_message_id`) -- and then **the channel moved to Codex
  Archive** (`archive_channel`), its name and permissions left as they
  are -- a game's thread archived instead, and a channel it was only
  opened in left where it is ("The lobby and the channel"). The move is
  a request on the channel's own route, not the messages' edit bucket,
  so the end spends three from the bucket: the edit, the pin and the
  line.
- **`/codex abandon` is either player's own, or a helper's** (the
  author, 2026-10-09: "any player should be able to abandon their own
  game"): the game played in the channel, or the lobby open in it, ends
  with no winner through `GameService.abandon`; the turn message (or the
  lobby) stands without its buttons -- the turn message pinned, as every
  message that stands as a turn's summary is -- one public line says it was
  abandoned and by whom, and the channel is archived. An abandoned game
  offers no rematch. A seated player may abandon only the game they sit
  in -- the channel's own -- and a game helper (Manage Channels) any; a
  watcher is refused privately. Unlike Concede it asks no second click:
  it is a command typed in the game's channel, not a button beside the
  others.
- **`/codex admin`'s gate is read at run time**: Discord carries a
  default permission on a top-level command and not on a subcommand of
  `/codex`, so `/codex admin` is listed to everyone and refuses anybody
  without Manage Channels ("Who may act, shared" is otherwise unchanged).
  The author is content with the archive and the startup sweep as built
  (2026-10-09).
- **Rematch** (either player, or a helper, as the lobby's Start) opens a
  new lobby through `GameService.rematch` -- a rule on the record,
  `CodexGame.rematch`: the same seats, the same people or the one person
  of a test game, in the same channel, the same mode and variant, and
  **every seat choosing its heroes and deck again**, as in a lobby
  `/codex create_game` opened. Until 2026-10-20 a duel's rematch swapped
  the two teams and offered **Keep heroes**; the author asked for a plain
  lobby instead (2026-10-20), as the multiplayer rematch already was.
  The button comes off its line in the click's own response, the channel
  moves back under Codex Games -- a thread comes out of the archive --
  since a game is about to be played in it, and the lobby is posted
  there. The finished record remembers its rematch (`rematch_game_id`),
  so a second press finds the lobby. **Who goes first is drawn again** at
  Start, as every game's is (`RulesEngine.new_match`).
  Start renames the channel for the new game's number, as any Start does.
- **`/codex admin reset_channels`**, for the test server: every channel
  named `codex-<n>` outside Codex Archive deleted -- `/debug`'s
  `delete_channel_with_retries`, with its backoff -- and every game of the
  server not in an archived channel dropped (`GameService.drop_games`),
  after the word "confirm", as `/debug reset_channels` does for D12 Ball.
  A game in a thread or in a borrowed channel is dropped while it is open
  -- its thread deleted -- and kept once over, its thread archived.
  The gate is `/debug`'s, guild only and Manage Channels, read at run time
  for the reason above.
- **The startup sweep** re-arms an open lobby's buttons, the current turn
  message's buttons for a game still being played -- never an older
  turn's, which stand as summaries -- and a finished game's **Rematch**
  while no rematch has been opened from it. An abandoned game's messages,
  and every turn message of a finished game, are left as they stand.
- **Nothing hidden in a log line.** Step 8 audited every logging call under
  `cogs/codex*` and `gamesaves/codex/`. One could name a card in a hand:
  `SafeView.on_error` logged the item clicked with `%r`, and a button's
  repr carries its label -- "3. Bloom (2 gold)" on a panel -- at ERROR,
  which #logs mirrors. It now logs the view's class, the item's kind and
  the game id (`test_a_clicks_error_names_no_label`). The rest log message
  ids, game ids, numbers and Discord's errors; the storage's "invalid saved
  game" line can carry `validate`'s sentence, which names a slug only where
  the slug is not a card at all.

### The golden

`tests/test_codex_golden.py` is the Codex bot's safety net, D12 Ball's
`test_golden_service.py` copied: **a seeded whole game of Bashing against
Finesse through the Codex `GameService`** -- `create_game`, the two seats,
`start`, `apply_action` for every answer and `resume` for every step the
bot owes, with the default `Batching()` -- every `GameResult` written
down as the service handed it back (its groups and their steps, what was
carried, the prompt and its ask, the standing prompts' kinds) and the
final save beside it, in `tests/golden/codex_service_transcript.txt` and
`codex_service_final_match.json`, byte for byte.

- **The seed is the full-game test's**, `SEED = 20261008`, and so is the
  policy (`test_codex_driver_full_game.choose`, which reads the prompt's
  options and nothing else); on it the game runs 275 answers to Troq
  Bashar destroying Finesse's base. `FOOLBOT_UPDATE_GOLDEN=1 python3 -m
  unittest tests.test_codex_golden` re-records it, as the D12 Ball
  goldens are.
- **It pins the model's voice with its tokens intact**, before any
  frontend draws one. So a faithful change to rendering -- the emoji, the
  mentions, the message layout, the board's picture -- leaves it alone;
  a change to the model's wording or to what the game does re-records it,
  and **the pull request that re-records it says so and shows the diff**.
  The rule is written in the test's docstring and in its failure message.
- **Nothing hidden is written into it**: a prompt's options are never
  described (a hand and a codex are their asked player's), and the test's
  own action lines leave out a hire's card and a tech choice's picks --
  `test_nothing_hidden_is_written` holds both. The final save holds every
  hand, as any save does; it is a test fixture, never a message.
- **What it does not cover**: a concession, an undo, an abandon or a
  rematch (`tests/test_codex_ending.py`, `tests/test_codex_history.py`);
  a test game, whose tech is chosen in each side's own ready phase;
  whatever the policy never does -- the tower's detection, an ability it
  does not reach, an attack's choice that never comes up on this seed;
  and everything the cog renders, which `tests/test_codex_cog_turn.py`
  plays through the fakes.

## What the two games share

Step 9 was decision 2's second half: with two games running, the generic
and the particular could be told apart by diffing them. Every pair step
1 to 8 copied was compared definition by definition, docstrings and
comments aside; **what was identical, or differed only by the game's
name, moved to one home, and both games import it** -- `gamekit/` for
the model's side, `botkit/` for Discord's. The leaves steps 1 and 3
moved (`gamebot.py`, `botlog/`'s parameters, `cogs/game_auth.py`, the
`BoardRefresher`'s parameters) were the pattern and stay where they
went. Each game's old module keeps the old name, re-exported, so no
call site moved; no save, golden or game changed. About 480 lines left
the two games for 470 in the two packages, docstrings included.

`gamekit/` is held to the model's rules -- no `discord`, no `async def`,
no Pillow or reportlab -- and imports neither game; `botkit/` imports
neither game either (`tests/test_shared_kits.py`, a ratchet of its own,
because `tests/test_model_purity.py` is one of the six safety-net tests).

**What moved**

- `gamekit/wire.py` -- `jsonable`, the one conversion to the wire.
- `gamekit/driver.py` -- `MOVED_ON` and `STEP_OWED`, the two refusals
  both drivers word alike.
- `gamekit/tokens.py` -- `Resolver`, a frontend's signature for a token.
- `gamekit/service.py` -- `StopHandling`, the three answers at a stop.
- `gamekit/saved.py` -- `SavedField`, one row of a match's save table.
- `gamekit/storage.py` -- the games file's guarded read
  (`read_games_file`) and write (`save_games`), and `PROJECT_ROOT` and
  `DATA_FOLDER`. **Each game still owns its two failure-flag sets and its
  logger, and hands them in on every call**, so a test that swaps a
  game's set reaches the write. Whether a load makes the folder is a
  parameter, since D12 Ball's does and the Codex bot's does not.
- `botkit/channels.py` -- `slugify_channel_part`,
  `get_or_create_category` and `CHANNEL_NAME_MAX_LENGTH`, which the
  Codex helpers had been importing from `cogs/d12ball_helpers.py`, the
  other game's module.
- `botkit/views.py` -- `GameLockedView`, the per-game click lock both
  `SafeView`s now stand on.

**What stays in each game, and why**

- `flow/result.py` -- `FollowOn` is the same shape, but it is typed by,
  and reads back into, each game's own closed `FollowOnStep`; the enum
  is the point (nothing reaches a step by spelling its name), and a
  shared class would need it injected. `Headline` (a seat against a side
  and a roll's working) and `StepResult` (Codex's `drawn`) differ.
- `prompts.py`'s `Action` -- the same, for `PromptKind`.
- `flow/driver.py` -- the loop is the same idea and different code: D12
  Ball's `speaks_lines` and an answer's `detail`, Codex's `draw_after`,
  the journal and the replayed draws in `apply`. `Refusal` carries `law`
  in one and `cite` in the other.
- `tokens.py` -- the grammar differs: every D12 Ball token carries an
  argument, and Codex's glyphs are bare, so `TOKEN_PATTERN`, `render`
  and `find` read different patterns.
- `gamesaves/<game>/storage.py`'s load loop -- D12 Ball migrates legacy
  ids and builds the record by its constructor; Codex has no migration
  and reads with `from_dict`.
- `gamesaves/<game>/service.py` -- `Batching`, `Narration`, `GameResult`
  and `GameService` are typed by each game's steps, prompts and record,
  and differ in substance (the AI's carry, the standing prompts, the
  journal's door).
- `cogs/<game>_views/base.py` -- the helper's confirmation (D12 Ball's
  carries the message, a label and custom ids; Codex's neither), the
  gates (a coach against a seat) and `apply` differ.
- The channel's name -- each bot's prefix, and D12 Ball's game name in
  place of the players -- and each bot's categories. `pin_board_message`
  and `add_full_image_button` were never copied: the Codex bot pins its
  finished turn, not a board.
- `scripts/run_codex_bot.ps1` against `run_web_app.ps1` -- the same
  script around a different process: the command line it matches, the
  pid and log names, the check before it starts. Sharing it would be a
  PowerShell module the live host loads, and none of it can be run here.
- The test ratchets -- each package-shape test pins its own package with
  its own exemptions (Codex's re-export check skips constants, its mixin
  check counts app commands, D12 Ball's walks the stray-save guard), and
  `tests/test_model_purity.py` is a safety-net test.

**Where the line was drawn.** A whole definition moved; a member of a
class that differs in substance stayed with its class, though its body
is the same -- `GameService.next_game_number`, `abandon`, `save`, `game`
and `waiting_on`, `Batching.at_stop`, `GameResult.refused`,
`Narration.drawn`, `DriverRun.ran`, the cog's `locks` property. Sharing
those would mean a common base class each game's service or cog
inherits half its door from, which is a design change rather than a
move. One-line idioms -- a module's `LOGGER`, a private one-line copy
helper -- are not copies.

## The standard game

Step 10 is the game the rulebook calls the game: three heroes a side, a
codex of seventy-two, all four add-ons (UMR p. 3). Everything before it
was written so that it fits, and this step is where the hero became a
list. It lands red and green as data the vanilla engine plays for its
numbers ("The vanilla engine and `UNIMPLEMENTED`"), so that a standard
game can be played at all -- three neutral heroes do not exist -- and so
that step 11 starts from a game that runs. A basic game may seat any
landed hero from this step on: the Core Set's first game is a basic
game of Calamandra against Jaina (p. 3), and a seat picked from a menu
of heroes makes no distinction the rules do not.

### The lobby's picks: the colours' decks, Mixed colors, and the first hero

The lobby is rebuilt from the record on every change
(`cogs/codex_views/lobby.py`): its first row **Basic game** / **Standard
game** -- either seated player's, a helper's, or anyone's while nobody
sits -- **Leave** and **Start**.

**A lobby opens on the standard game** (the author, 2026-10-15:
`LOBBY_MODE` in `cogs/codex/lobby.py`, which `/codex create_game` hands
to `GameService.create_game`). The service's own default and the
record's stay "basic", since a save older than step 10 is a basic game
and the tests and the golden stage one; which game a new lobby offers
first is the frontend's choice, not a rule. **While the lobby is on the
basic game its text carries a warning** naming the two matchups the
basic game is recommended for (`BASIC_MATCHUPS`, the author,
2026-10-15): Bashing against Finesse, the neutral pair the bot was built
from, and Fire against Feral -- Jaina against Calamandra, the Core
Set's own first game (Rulebook p. 3). It is a line in the lobby rather
than a message of its own, so it costs no request: the mode click
already edits the lobby through its own response, and everybody
choosing a hero sees it, not only whoever clicked. The menu still
offers every hero; the warning recommends and refuses nothing.

Under the first row, by the mode:

- **The basic game: a menu of the landed heroes**, one pick, which
  seats the clicker with that hero. A menu because twenty heroes, when
  all six colours have landed, do not fit two rows of buttons.
- **The standard game: a button per colour's deck, by its name, and
  Mixed colors** (the author, 2026-10-10: instead of the menu of every
  hero). A colour's deck is its three heroes played together -- red's
  the **Blood Anarchs**, green's the **Moss Sentinels**, purple's the
  **Vortoss Conclave**, black's the **Blackhand Scourge**, white's the
  **Whitestar Order** and blue's the **Flagstone Dominion**
  (`COLOR_DECK_NAMES`; `CardCatalog.color_decks`, every landed colour
  with three heroes, so neutral's two make none) -- six since step 13,
  so with **Mixed colors** they take two rows, five to a row as
  Discord allows, and a test game's two sides four. Red and green's
  names are on Sirlin's own site; the author confirmed all six
  (2026-10-10). Each button carries its colour after the name --
  "Blood Anarchs (Red)" -- because a deck's name alone does not say
  which colour it is to somebody new to the game (the author,
  2026-10-12). One click seats the clicker with the three. **Mixed colors** answers the clicker alone,
  ephemerally (`MixedTeamView`), with two menus: **the first hero --
  "its colour is your starting deck"** -- and the other two. Both
  filled, the seat is taken through the service as the buttons take it,
  the picker says the team, the first hero and the deck, and the lobby
  is edited through the channel (`refresh_lobby`), since the click
  answered is the picker's -- one edit, in a channel where nothing else
  is edited before Start. Each menu opens on the seat's team where it
  has one, so changing the first hero is one pick. A record refusal --
  a hero twice -- is shown in the picker. Discord's multi-select menu
  does not say which value was picked first, which is why the first
  hero is a menu of its own.

**The first hero names the starting deck** (the author, 2026-10-10:
make it clear which hero is first, and so the deck). UMR p. 3 lets a
player take the starting cards of any of their heroes' colours; the
record holds a team in the order chosen and settles the deck as the
first hero's colour (`CodexGame._settle_deck`), neutral included, so the
choice is made by choosing the order and there are no deck buttons any
more. `choose_deck`, still the service's, puts the first hero of that
colour at the front. The lobby's line per seat says it: "**Fire/Feral/
Bashing** (Jaina Stormborne first, then Calamandra Moss, Troq Bashar);
the Red starting deck". A lobby saved before this with a deck chosen
from another of its heroes' colours keeps it -- `seat_complete` reads
any of them -- since a half-set lobby outlives the commit.

A **test game** shows the picks twice, one set per side, since one
person plays both: the basic game's two menus, or a row of deck buttons
and **Mixed colors** per side, "P1: Blood Anarchs (Red)", its team lit.
Changing the mode keeps every seat's player and clears its heroes -- a
team of one is no team of three. The catalog names the
heroes, and the cog's old `SPEC_HEROES` table went.

**The multicolour costs are the engine's and stay so** ("The multicolour
costs, and where the surcharge is remembered", below): the lobby
changes how a team is picked, not what it pays, and a test plays a mixed
team picked in the lobby to its opening position and checks both costs
against a colour's own three.

The rules are the record's (`CodexGame`, refusing with `RuleRefusal`,
UMR pp. 3-4): as many heroes as the game takes, no hero twice, every one
of a colour the bot has landed -- refused "not in this bot yet" with no
page, since the rulebook allows it and the bot does not play it yet. A
basic game's deck is its hero's colour; a standard game's the first
hero's. Both seats may choose the same hero, or the same colour's
deck -- **mirror games are fine** (the author, 2026-10-09). Start waits
on both seats complete -- heroes and deck. A rematch's lobby starts
with every seat's picks empty, as a new one does.

### The record's keys, the match's fields, and the hero refs

`player_specs` stays the saved key and holds a list per seat; a hero is
its spec's one hero (`CardCatalog.hero_for`), so a spec names a hero and
nothing is saved twice. `PlayerState` has `specs`, `heroes` and
`deck_color`; `new_match` deals each seat its deck's starters and the
codex of every spec. The saved fields and their fallbacks are in "The
saved fields", above.

**A hero is `hero:<slug>`** wherever an action, an attack, a target or
a patrol names it -- the bare `hero` of steps 2 to 9 named the side's one
hero. A save or a journal older than step 10 still says `hero`, and
reads as the side's first hero: `MatchState.from_dict` rewrites an attack
standing half-resolved, a tower's detection and an effect under way
(`upgrade_hero_refs`), and `driver.answer` rewrites an older journal's
actions as it replays them (`_upgrade_refs`). `summon` and `level` name
their hero (`arguments["hero"]`); one that names none -- an older
journal's -- is the first.

**The golden was re-recorded** for exactly that: normalising
`hero:<slug>` back to `hero` and `specs`/`heroes` back to `spec`/`hero`,
the old and the new final match are identical, and the transcript
differs only on the action lines that name a hero. Commit 3 added
`tech2_spec` (null) and `constructed_once` to it, and nothing else.

### The hero limit, as the ruling words it

`RulesEngine.hero_limit` is the heroes_hall ruling, the one reading (UMR
p. 6, p. 9): three with an active tech III, or an active tech II and an
active heroes' hall; two with either; one otherwise -- active being
built, finished and standing. A summon past it is refused citing p. 6
("Hero limit is 1", on the button). A dead hero in the command zone
does not count, so another may be summoned at once (p. 6: "you can
immediately summon a different hero to replace it"), and losing a
building removes nobody. The upkeep takes one summoning rune off each
hero (p. 5); readiness, armor and arrival fatigue are each hero's.

### The spec at Tech II, and the tech lab's

In a standard game constructing tech II chooses a spec among the
player's heroes' (UMR p. 8): the build action carries `spec`, the
`BuildOption` lists the choices, the driver refuses a missing or a
foreign one citing p. 8, and `PlayerState.tech2_spec` keeps it --
unchanged by the building's destruction and its rebuild ("You don't get
to change this spec"). A tech lab carries its own (`AddOnState.spec`):
chosen as it is built where the tech II's is chosen, from the other
specs -- **never the tech II's own** (the author, 2026-10-09); built without one where it is not, and chosen together with the
tech II's when that is built (`lab_spec`, the tech_lab ruling). A
destroyed lab loses its spec; a rebuilt one may choose another (p. 9).
A tech II or III card is playable only of the tech II's spec or a
finished lab's (`chosen_specs`; "You can't immediately play cards of the
new tech"), and `why_not_playable` says which is missing. A basic game's
one spec is chosen by the rule and never asked, and its `tech2_spec`
stays `None`. On the panel, **Build Tech II** in a standard game turns
the panel into the spec choice, a button per spec and **Back** -- the
shape **Attack...** has -- and **Build Tech lab** the same where a tech
II's spec is chosen; where a lab waits on its spec, the Tech II's row
and then the lab's, whose button builds. The heroes' hall needs nothing.
The basic game builds the tower and the surplus alone (p. 3).

### The multicolour costs, and where the surcharge is remembered

`team_colors` is the heroes' colours less neutral ("the neutral heroes
don't count as an additional color", p. 4). With two or more, the first
tech building or add-on the player constructs costs 1 more (pp. 4, 8,
9), and `PlayerState.constructed_once` remembers that it has been paid:
set by any construction, a rebuild for 0 included, so the first
construction is the first whatever it is. The build option shows the
cost it will charge.

A starting spell costs 1 more where no hero of its colour is in play
(p. 4: "when played by a hero of the wrong color"), never a neutral one
(`wrong_color_surcharge`). **The caster is the engine's** (`caster`): a
spec spell's own hero; a starting spell's, a hero of its colour where
there is one, otherwise the first in play. Nobody is asked, because
nothing in the sets this bot plays turns on which hero cast a starting
spell, and the cheapest caster is the one any player would choose. A
spec spell needs its spec's hero in play, an ultimate that hero at its
maximum level since the turn began (p. 7). Channeling stays by spec.

### The levels' recipient

A kill's two levels (UMR p. 10) go to the killing side's one hero in
play; with none, nobody gains them; with more than one, **the active
player is asked** -- `LEVEL_GAIN`, a button per hero in play -- because
the active player makes every decision (p. 14). **The hero's own
controller never decides on an opponent's turn** (the author,
2026-10-09): p. 10's "choose one hero to gain the levels" speaks of a
kill on your own turn, so where a defending patroller kills the
attacking hero and the defender has two heroes in play, the active
player chooses which of the defender's gains them. The question is a frame
put at the front of `MatchState.resolving` where the kill happened
(`board.level_gain_owed`), on the attack's stack or the effect's, so
nothing after the kill resolves before it; the answer pops it and the
stack goes on. A kill by a player's own effect still gives nobody levels.

### Building cards and upgrades in play

Red and green's starters have them (Bloodburn, Rich Earth, Verdant
Tree), so they are things in play from this step (UMR p. 7): played from
the hand for their cost, with the tech building and the spec their level
needs, arriving with arrival fatigue; neither attacks nor patrols. **A
building card** has HP: it may be attacked once the patrol zone allows
("anything with HP", p. 10), a damage spell may choose it as a building
and **a repair takes its damage off** (the author, 2026-10-09: "you can
repair building cards"); destroyed, it goes to its owner's
discard and **deals nothing to the base** -- p. 8 says that of tech
buildings and add-ons. **An upgrade** has no HP and cannot be attacked.
Their text waits in `UNIMPLEMENTED` with the rest of red and green's.

### What the board draws for all of it

`render.heroes` reads `player.heroes`, so a standard panel's command
zone has three slots and its grid six columns ("The board on Discord").
The nameplate names the team (`team_name`) -- "Blood Anarchs",
"Fire/Feral/Bashing", "Bashing" in the basic game -- and its mark is
still the first hero's colour, which is the starting deck's. The add-on
slot draws the heroes' hall's and the tech lab's cards from
`buildings/`; the spec chosen at Tech II is its spec card
(`specs/<spec>.png`, cut at step 1), over the tile's lower right with
its cost and heart left clear and hanging into the gap before the grid
-- large enough to read on Discord, which the first, half its size, was
not (the author, 2026-10-13) -- and a lab's spec card lies
on the lab's. Building cards and upgrades lie in the grid after the
units. The codex is three binders, but it is shown by tech level (the
author, 2026-10-10, who first asked for it spec by spec and then
"organizing by tech level rather than spec"), and then on 2026-10-12
with each spec's later cards kept together: `codex_counts` lists every
Tech I card, then each spec's Tech II and Tech III together ("tech 3
should be grouped with tech 2"), then each spec's spells with its
ultimate last ("ultimate spells should be grouped with their hero's
spells"), each group spec by spec as the deck names them and then by
cost and name (`RulesEngine.codex_order`). Every view, the tech
picker's too, narrows that one list, so all of them read in the same
order; a spec's own view is its twelve in the same order. A card with
no copies left keeps its place, faint at x0, so the grid stands still
while a codex empties (the author: "keep this structure steady even if
some cards are taken in the middle"). Where the grid breaks is the
engine's too, `codex_places` -- each card's row and column -- and
`render_codex` draws the cards there, the grid as big as the places it
uses. Where a codex is more than one spec, the Everything, Tech II & III
and Spells views are laid out by spec: Tech I runs on, a row of six; each
spec's Tech II and III are a block two cards wide and three high, Tech
III last, in the bottom right (the author, 2026-10-20); and each spec's four spells are a block two cards wide, two
on top and two below, the specs' blocks side by side, so a spec's tech
and spells sit in the same two columns (the author, 2026-10-20: tech 2
and 3 "as a block of 2x3 instead of row"; until then each spec's six
were a row of their own -- the same rows either way, 1 + 3 + 2). One
spec's Tech II and III alone, as a `tech2spec:` view holds them, stay
a line (the author, 2026-10-20: "single spec view should not use this
block") -- a block of two would leave four columns empty. Tech I, a spec's
own view, and a codex of one spec run on.
The
Everything view of seventy-two (36 cards, two copies each) at
`CODEX_COLUMNS` -- six; twelve, a row a spec, was tried and put back --
measured 495 KB as WebP, 1154 by 1538 (477 KB in the data's order; 591 KiB and 1286 by 1718 before
the cards were made a bit smaller, "The board on Discord") -- far under
Discord's upload limit, so it is not narrowed -- and each spec has its
view. `scripts/render_codex_sample.py` renders
a standard game's board, hand and codex beside the basic game's.

The six heroes' faces are emoji like Troq's and River's: `FACES` in
`scripts/render_codex_emoji.py` pins a square per hero, and
`EMOJI_NAMES` asks the Codex application for each.

## Multiplayer

The free-for-all and the two-headed dragon were built in the seven
steps of [docs/codex-multiplayer.md](../codex-multiplayer.md), which
keeps the steps, their prompts and the author's answers to its
questions. **This section is the one home of what the series settled**,
by subject rather than by step, with the reasoning; where the author
overruled what a step or a decision proposed, it says what replaced it.
The step that built each thing is named in brackets where a reader
tracing a commit needs it.

Throughout, the two-player game is **the duel**, and it changed in
nothing a player can see: `tests/test_codex_golden.py` passed unrecorded
through every step, the request table above holds click for click, and
every field the series added is written to a save only where it is set,
so a duel's save is the bytes it always was and reads on a checkout
older than the series.

### Which rules govern

**The official rulebook and Sirlin's rulings** (the author, 2026-10-11,
overriding the Codex series' preference for the UMR): the Core Set's
"Rulebook version 46" at `docs/codex/Codex_Core_Set_Rulebook.pdf`, cited
as `Rulebook p. n` by the number at the foot of its pages -- the two
modes are p. 13 (Two-Headed Dragon) and p. 14 (Free-for-all), with p. 4
(the tower), p. 5 (the patrol slots), p. 11 (a dead hero's levels) and
p. 19 (armor) -- and the rulings in `codex/data/rulings.json`, which
govern where they and the rulebook's text differ. The UMR
(`docs/codex/Codex_UMR_v13w.pdf`, UMR p. 11-12 for the modes) is the
source **only where the rulebook and the rulings are silent** (the
author, 2026-10-14, question 13), and a citation of it says so. The
worksheet's "Where the UMR differs from the rulebook" lists every
disagreement found on these modes; in each the rulebook's reading was
built -- Mercenaries arrive at the first upkeep rather than "begin" in
play, a dead hero's levels go to an opposing hero rather than one of
yours, a team never holds two of one add-on -- and where the rulebook is
silent (the playoff's current turn) the UMR's was. One the worksheet
recorded as the UMR's reading, the tower's detection in a dragon, the
author overrode in favour of the team's one tower ("Attacking a dragon",
below).

### The five readings

Each question the bot used to answer by the idiom `2 if x == 1 else 1`
has **one reading** (step 1), so that the modes changed readings rather
than 66 sites; the PR of every step showed these empty:

    grep -rnE "2 if .* == 1 else 1" codex cogs/codex cogs/codex_views cogs/codex_helpers.py
    grep -rnE "[!=]= match\.active|match\.active [!=]=" codex cogs/codex cogs/codex_views

- **`codex/seats.py` is the reading; the engine's methods are its
  door.** `opponents(match, seat)` (every seat not on `seat`'s team, in
  seat order), `turn_seats(match)` (whose turn it is), `acting_seats`
  (who may act now: `turn_seats` less a seat that has locked, or all of
  them once every one has), `next_seat` (whose turn follows) and
  `turn_order(match, after)` (seat order, wrapping, from a seat) are
  functions of the match alone, so the renderer and the save code, which
  hold no engine, ask the same thing the rules do; `RulesEngine`'s
  methods of those names are one-line doors over them. Nothing computes
  the other seat inline, and nothing asks `seat == match.active`: "is it
  this seat's turn" is `seat in turn_seats(match)`. `turn_seats` and
  `acting_seats` differ only in a dragon, where a teammate who has
  locked is still taking their turn -- their Frenzy still counts, their
  tower is not a defender's.
- **No "other seat" is worked out by hand** (2026-10-16): the engine's
  `defending_seat` asks `sole_opponent` -- which takes the refusal's
  words, "Choose whose forces to attack first." there -- and the save's
  `read_defending_seat` and `upgrade_hero_refs` ask `opponents` and
  `sole_opponent`, the second only for a save of two seats, the only kind
  that holds the bare `hero` it rewrites. `other_team` refuses outside a
  dragon, as `sole_opponent` refuses a table, rather than raising a
  StopIteration a generator would swallow.
- **`sole_opponent` marks a site that must be a duel's.** Where a rule
  reads "the opponent" and the duel's one is the whole answer, the code
  asks `sole_opponent`, which refuses a table with several opponents
  rather than answering for one of them; steps 2 and 5 gave each such
  site a real answer, and what is left -- the duel's two board
  compositions, `rivals` outside a dragon -- is a duel's by construction.
  `rivals` is the side that wins when a seat's side loses a two-sided
  game: the duel's one opponent, or a dragon's other team.
- **A base is read through `MatchState.base_of` and written through
  `set_base`**, the only code outside the field's definition, its
  `SavedField` and the deal that names `base_hp`. `base_seat` says
  whose `base_hp` a seat's base is -- their own, or their dragon's
  head's -- and `base_cap` the most a base holds (20, a dragon's 30).
- **The attack carries the seat attacked.** `MatchState.against` is the
  seat a declared attack is against, kept beside `attacking` and
  cleared with it, and `combat["against"]` the same for the attack
  under way, written to a save only while set; a save from before reads
  the one opponent (`components.read_defending_seat`).
  `engine.defending_seat(match, against)` is the reading. The defender
  chain takes an optional `against`, so a prompt builds its rows per
  opponent, and `DefenderOptions` carries each row's `seats` (on the
  wire only where there are several). **An effect frame is against a
  seat it names** (`top["against"]`, read by `_against`), set by what
  started it -- the attack's defending seat, the chosen opponent, a
  death's controller.
- **The controller of a card is `MatchState.controller_of`** (the
  engine's `seat_of` is its door): the borrower while a hero is lent,
  the owner otherwise. `PlayerState.heroes_in_play` is the heroes a
  player *controls*, `heroes_on_table` every one in play,
  `MatchState.patrollers(seat)` a patrol zone as it stands with the
  heroes lent into it, and `hero_on(seat, ref)` / `board.body_of`
  resolve either spelling of a hero's ref.

### The variant and the seats

- **The variant is the record's and the match's** (decision 2):
  `codex.game.VARIANTS` names the duel, the free-for-all and the
  two-headed dragon; `CodexGame.variant` is the lobby's until Start
  (`set_variant`, a service door beside `set_mode`) and
  `MatchState.variant` the match's own copy, **which every rule reads**
  -- a match outlives its lobby. The hero count stays `mode`; the two
  are independent axes, as the rulebook has them. A duel writes no
  `variant` key.
- **The variant is read one way** (2026-10-16, after the review of
  2026-10-15): `is_duel`, `is_free_for_all` and `is_dragon`, the same
  three on `MatchState` and on `CodexGame`, in the shape of `base_of`.
  Nothing compares `variant` to a string outside them and `new_match`,
  which names `DUEL`, `FREE_FOR_ALL` and `TWO_HEADED_DRAGON`, and nothing
  reads `match.dragons` for its truth -- only `seats.py` reads the teams
  it holds. They were 13 string compares on the match, 25 on the record
  and 39 truth tests on `dragons`, some mixed in one expression. **A line
  worded three ways is `game.by_variant(variant, duel=, free_for_all=,
  dragon=)`**, which names all three, so none falls through to the duel's
  wording -- how several duel lines reached a table before #601: the
  undo's label, "has already started their turn", the tech button's
  "changed during your opponent's turn". Lines that branch on more than
  the variant (a team of one seat's extra turn) keep their own
  conditions over the predicates.
- **The record's seats are a list** (decision 3): `CodexGame.seats`,
  `{id, name}` per seat as long as `seat_count`, an empty seat keeping
  its number. The four `player_1_*` / `player_2_*` keys are still
  written for the first two seats, because D12 Ball's record spells them
  so and `cogs/game_auth.py`'s Protocol reads them; they are properties
  over the list named in `LEGACY_SEAT_KEYS`, which the loader keeps
  beside the record's fields -- without it a save from before the list
  came back after a restart with nobody seated. `seat_user_id`,
  `seat_name`, `seat_ids` and `seats_of` are the readings the cogs use.
  `codex_helpers.seat_label` is the cog's one way to name a seat in a
  line it composes ("Player n" where the record has no name),
  `seat_labels` several joined with "and", and `mention_ids` the users
  of several seats to ping, each once.
- **A seat is any positive number the match has.** `validate` accepts
  two to five players in seat order; `first`, `active`, `winner` and
  `conceded` any seat it has; `tokens.player` and `tokens.addressed`
  any positive seat. Nothing names 1 and 2.
- **The lobby** has a row of variants -- **Duel** / **Free-for-all** /
  **Two-headed dragon** -- under the mode's, either seated player's, a
  helper's, or anyone's while nobody sits. A free-for-all's record has
  five seats and starts from three complete ones; its seats are taken in
  order and close up when a player leaves (`_close_gaps`), because turn
  order is seat order. A dragon's has four, `CodexGame.teams()` --
  `DRAGON_TEAMS`, seats 1 and 2 against 3 and 4, the deal's pairs -- the
  one reading of its sides, headed "Team 1" and "Team 2"; nothing closes
  up there (a dragon's seat order is not its turn order), so a player
  who wants the other team leaves and sits again. `start_refusal` is the
  one wording of why Start waits. A message has five rows, and the
  mode's and the variant's leave three for picks, so a test game shows
  the picks of as many seats as fit (`LobbyView.pick_seats`), a window
  from the first seat not yet chosen for, each labelled "P3: Blood
  Anarchs".
- **The channel** is `codex-<n>-ffa-<p1>-<p2>-<p3>` for a free-for-all
  and `codex-<n>-<p1>-<p2>-vs-<p3>-<p4>` for a dragon, its teams joined
  by `-vs-` as the duel's two seats are (`channel_name`, capped at 100;
  step 6's prompt overriding step 4's guess of a `2hd` word);
  `CHANNEL_NAME_PATTERN` still reads the number. `/codex games` lists
  every seat, a dragon's as "ann and bo vs cy and dee".

### The free-for-all: the deal, the order and the ending

- **The Mercenaries are an upkeep effect, as the rulebook has them**
  (Rulebook p. 14; decision 6). The third, fourth and fifth players in
  turn order from the first drawn are owed 1, 2 and 3
  (`PlayerState.mercenaries_owed`, written only while owed); their first
  upkeep puts them in play, first among its effects and never ordered,
  as tokens made by no card with the ordinary arrival fatigue. The
  UMR's "begin with them in play" is not the rulebook's.
  `seats.turn_order` is the one reading of "from the first".
- **The ending is the most base HP, and a tie plays off** (decision 5;
  questions 13, 15, 16, 17, 20 and 22, all the author's of 2026-10-14).
  A destroyed base goes through `turn.base_destroyed`: a sole leader
  wins at that moment; a tie fills `MatchState.playoff` with the tied
  seats **at that moment**, in turn order from the seat after the
  active one, and `MatchState.tied` keeps the whole list, since the
  playoff empties as it is played and the comparison after it is among
  the tied alone. The current turn runs to its end first -- the UMR's
  reading, the rulebook being silent -- and changes nothing about who is
  tied. `next_seat` hands the playoff out ahead of the order;
  `begin_tech` pops it and, once it has emptied, compares again: a
  winner, or the playoff filled again ("Still tied"). **Double Time's
  extra turn comes first** (the author, 2026-10-16: "extra turn
  first", the rulebook being silent): the card says "after this one",
  so a seat owed one (`seats.owes_extra_turn`) takes it straight after
  the turn that earned it, ahead of the playoff, which then runs in the
  order it was filled; and the comparison after the last playoff turn
  waits for an extra turn that turn earned. Before this the playoff
  went first and the extra turn was in practice lost, since the active
  seat after the playoff was no longer the one it was owed to. While
  anyone is tied only a tied player's base falling counts, and the game
  ends then on the comparison among the tied. **A debt unpaid is a base
  destroyed**: the base to zero, the comparison then. **A destroyed base
  is no longer a defender** (`_standing` leaves a base at 0 out): the
  whole-game test showed tied players attacking a fallen base forever.
  The finished game's ask says the score, and `GameOverOptions` carries
  `winners` and every seat's `base_hp`.
- **There is no concession in a free-for-all** (the author,
  2026-10-11): `turn.refuse_concession`, behind
  `GameService.check_concession`, refuses it citing Rulebook p. 14; no
  hand menu has **Concede**, and `/codex concede` says why.

### "An opponent's", the plurals, and a kill

- **"An opponent's" is asked; a plural is every opponent** (decision
  11). An effect whose text names one opponent is in
  `effects.AN_OPPONENT` with the part that first needs to know which; at
  a table of several, where nothing has set the frame against a seat,
  `resolve.opponent_owed` asks a `TARGET` over each opponent's base
  ("choose an opponent") before that part, and the answer sets the
  frame's `against`. It is never asked of a duel, whose one row is taken
  unasked, nor of a dragon's other team where the effect hits a base,
  since they share one (`resolve._one_base`, the Captured Bugblatter
  ruling). A frame something else set against a seat -- an attack's,
  a death's, a damaged building's -- is never asked. The plurals reach
  every opponent (`resolve._each_opposing`, `effects.EACH_OPPOSING_BASE`,
  and `effects.EACH_OPPONENTS_ONE` for Hooded Executioner), and "each
  opponent's base" is each *base* there is, a dragon's one hit once
  (the Drakk Ramhorn ruling). Martial Mastery's look at a hand is an
  opponent chosen (question 21). The audit of every card that says
  "opponent" is in step 2's PR (#579).
- **A dead hero's levels go to any opponent's hero, the active player
  choosing** (Rulebook p. 11; question 18): `board.destroy` offers every
  in-play hero of every opponent of the dead hero's **controller** --
  the controller, not the owner, for a lent hero -- and
  `LevelGainOptions.seats` names each hero's seat, so a mirror game's
  two of one hero are told apart. **A hero already at its maximum level
  is not offered them** (the author, 2026-10-15: "they can't gain any
  more level at max"; built in its own PR, #596):
  `RulesEngine.takes_kill_levels` is the one reading, asked by
  `board.destroy` and by `LevelGainOptions`, so where one hero can still
  gain it gains them unasked, and where none can nobody does. The duel's
  golden did not change; the free-for-all's and the dragon's were
  re-recorded, since each offered a maxed hero once.
- **Moment's Peace removes its caster's things from the units'
  defenders, and nothing else**: a unit may attack while any opponent is
  not at peace. **The tower** detects and damages only an attacker of
  what its owner's side controls, and **each opponent's patrol zone**
  protects that opponent alone. Armor refreshes on every turn for every
  seat (Rulebook p. 19).

### The free-for-all's additions: repair and free gold

Both behind `match.variant == "free_for_all"` (Rulebook p. 14; decision
7). The free-for-all's golden was re-recorded once for them (step 3),
since the free gold adds a line and changes the gold the policy plays
on.

- **Repair is a `MAIN_ACTION` option, `repair_base`**: `RepairOption`
  (cost 3, `allowed`, `why_not`) on `MainActionOptions.repair`, `None`
  and absent from the wire outside a free-for-all, as often a turn as
  the gold goes, through `base_of` / `set_base`, journaled as every
  action is; refused at 20, under 3 gold, and in a duel -- and **once
  the base is destroyed** ("the base is destroyed", 2026-10-16): a base
  at 0 is out of the game and no defender, and its player reaches their
  own main phase with it only after a debt unpaid at their upkeep left
  a tie. Repairing it from 0 put it back among the defenders, and its
  second fall was announced again.
  - **On Discord it is a button on the panel's board row** (the panel
    step, 2026-10-15): **Repair base (3 gold)**, green among what may be
    built where the engine allows it, and greyed with its reason --
    "Repair base (3 gold): the base is undamaged" -- among the refused
    builds where it does not, which a full row gives up first
    (`TurnPanelView.build_actions`, choice `("repair",)`). It is built
    from `MainActionOptions.repair` and nothing else, so a duel's and a
    dragon's panel, where that is `None`, carry no such button; the
    click answers `MAIN_ACTION` with "repair" and costs what any action
    does ("The requests per click"). The board's row rather than the
    actions row because the base is on the board, and because a
    standard game's actions row is full already -- a sixth button there
    would take one of the hand's two rows.
- **Free gold is read where a unit is destroyed, from who did it**
  (question 19). `board._is_a_kill` is the one reading of "whenever
  *you* kill": the killer is the active seat when combat did it and
  `cause` otherwise, and it is a kill when the killer is the active
  seat and the card is controlled **at that moment** by one of its
  opponents (a card lent to an opponent is theirs). 1 gold, to
  `BOUNTIES_A_TURN` (3) from `PlayerState.bounties` (cleared in the
  ready phase), the gold cap respected, said at the end of the destroy
  line. A hero or a building never pays. Anything the state of the
  table kills, or an effect its own controller set off, is nobody's
  kill. Two cards say "the active player" does it -- Blackhand Dozer and
  Orpal Gloor's max level -- so `effects.ACTIVE_PLAYER_ACTS` names them
  and `resolve.cause_of` gives their frame's cause as the active seat;
  Obliterate's kills carry the attacker as their `cause`.

### Lending is a control change

(Rulebook p. 14; decision 7; units and heroes, question 9.)

- `PatrolOptions.zones` lists each opponent's empty slots as
  `(seat, slots)` (`RulesEngine.lending_zones`, a free-for-all's alone,
  on the wire only where there are some), and the patrol answer takes
  `lent`, `{seat: {slot: ref}}`, beside the `assignment` that is the
  owner's own zone: the same slot name can be the owner's and a
  borrower's, so one map cannot say both, and an older journal and the
  duel read as before.
- `board.lend` moves a unit into the borrower's play zone, `controller`
  the borrower and `CardInstance.lent` set (saved only while set);
  nothing else on the card changes and no Arrives trigger fires. A hero
  stays on its owner's list with `HeroState.lent_to` and the slot, and
  the borrower's zone names it `<owner seat>:hero:<slug>`
  (`lent_hero_ref`, the spelling `attached_hero` uses, because two
  players can field the same hero). Every reading of it goes through
  `controller_of` ("The five readings").
- **It comes home at the borrower's upkeep**: `board.return_lent` runs
  first in the upkeep -- out of the zone, `controller` its owner's, into
  the owner's play zone and never their patrol zone, no trigger, not
  readied, since the borrower's ready phase already readied it as
  theirs. A turn order that goes round the table brings every other
  seat's turn between a lock and the owner's next, so a card is home
  before its owner needs it.
- **A lent card that dies pays its owner** (the scavenger's gold, the
  technician's card) and leaves play to its owner's discard pile; a lent
  hero goes to its owner's command zone with its two summoning runes,
  its levels to an opponent of its controller. A hero pays the
  scavenger's and technician's bonuses as a unit does, lent or not --
  "Finds 1 gold for you if it dies while patrolling" (Rulebook p. 7)
  names no kind of card -- always to its owner (`board._patrol_payout`).
- **Taking the end of a turn back takes the lending back**: the undo
  replays to the last point before the lock, and the lock is journaled
  only where a choice is asked before the next turn begins.
- **A sidelined lent patroller goes home** (the author, 2026-10-15: a
  unit as a hero, at once). A loan is a slot in the borrower's zone: a
  lent hero never stands in the borrower's play zone, only in the slot
  `lent_to` and `patrol_slot` name, and `validate` holds a lent hero to
  patrolling; a lent unit stands in their play zone, but the author
  reads the loan as the slot for it too, so the two end alike and the
  rulebook's upkeep return is for what is still patrolling then. So
  `board.sideline(match, body)` -- every sideline's one door: Appel
  Stomp's and Calypso Vystari's `sideline` part, the Grappling Hook's,
  Boot Camp's, a disable's, Oathkeeper's, Entangling Vines' -- sends a
  lent patroller home with the slot, which is exactly what `return_lent`
  does (it now calls `sideline` for each): a unit into its owner's play
  zone and never their patrol zone, `controller` and `lent` back, a
  hero with `lent_to` cleared; nothing else changed, no trigger. Put
  there rather than in `resolve._sideline` because the reading is what
  sidelining *is* for a lent patroller, not what one card does, and a
  second sideline site would otherwise leave a hero lent to nobody's
  zone, which no click could load (the review of 2026-10-15). The line
  names it where it now stands -- "sidelines {player:3}'s
  {hero:troq_bashar}", the owner -- because `board.named` reads a ref
  that no longer finds its card or hero on that seat's side where it
  stands now (`match.instance`, the owner's `hero_by_ref`), as a lent
  patroller is always named where it stands. Boot Camp gives its rune
  before it sidelines, since the target names the card on the
  borrower's side and the card is gone from there after.
- **A control change ends a loan.** `board.gain_control` clears `lent`
  with the slot: a card Ogre Recruiter takes from its borrower is the
  taker's, not borrowed -- the borrower's upkeep used to send a stolen
  card "home" and undo the steal -- and one its owner takes back is
  simply theirs, where `lent` left standing read as "lent to its own
  owner" and the save would not load. `board.home_seat` is the one
  reading of the seat a card answers to beyond its controller -- its
  owner while lent, its controller otherwise -- for who a dying lent
  card pays and for **where a card taken for a while goes back to**:
  Kidnapping's `returns_to` and Mind Control's `before` are the home
  seat, so a lent card kidnapped or mind-controlled goes back to its
  owner, not to the borrower (the author, 2026-10-15), since the taking
  ended the loan and the borrower would otherwise keep for good a card
  they only borrowed, and nothing in the save remembers a loan across a
  taking (the save format may not grow for it).
- **The borrower's zone is read with its lent heroes.**
  `RulesEngine._hero_refs_of(match, seat)` is the one reading of the
  heroes on a side as that side names them: their own in play and the
  heroes lent into their zone, as `match.patrollers` spells them.
  `_things_in_play` (and so `_standing`, `holder_of` and the tower's
  candidates) and Wight's "unstoppable when attacking heroes" read it,
  so a flier or an unstoppable attacker facing a zone whose only
  patroller is a lent hero is offered the hero beside the base, as any
  patroller it may take is, where before the hero was on nobody's list
  -- `player.play` and the owner's `heroes_in_play` -- and only a
  blocking patroller was offered.
- **A lent hero is its controller's to every effect that says so**
  (2026-10-16, after the review of 2026-10-15).
  `MatchState.heroes_controlled(seat)` is the one reading of the heroes a
  seat controls -- its own in play and not lent out (`hero:<slug>`),
  then those lent into its zone (`<owner seat>:hero:<slug>`) -- and
  `_hero_refs_of` reads it. What "you have", "your", "that opponent
  controls" and "each opposing" read is on it: Inverse Power Ninja's
  count, a hero's band grants (Midori's, Calamandra's, Drakk's), Stalking
  Tiger's Feral hero, the target lists that take any side's heroes (any
  unit or hero, a time rune, runes, a flier, Boot Camp's), Dothram's total
  ATK, Plague Lord, Molting Firebird, Death and Decay, Banefire Golem,
  channeling's "the correct hero", Orpal's, and the dead hero's levels
  and their prompt (`board.destroy`, `_level_options`, the answer through
  `hero_on`). What reads every unit and hero in play -- Wandering Mimic,
  Bloodlust -- reads `heroes_on_table`, so a lent hero is on its owner's
  list there; Maximum Anarchy and Spreading Plague build their rows
  through `heroes_controlled`, so a lent hero is named as its side names
  it. What is the owner's stays on `heroes_in_play` and the hero list:
  the hero limit, summoning, the command zone, healing and the upkeep's
  own effects, and every effect of the seat's own turn, which a lent-in
  hero never meets, since it goes home first thing in the borrower's
  upkeep. **The levels of a hero that dies may go to a hero lent to an
  opponent** of its controller, that opponent's to give, the same
  reading question 18 took for the dead hero (built so; the PR asks).
  Grants such as Training Grounds and Hero's Monument were already
  worked out per hero through `seat_of`. A lent hero keeps the **Final
  Showdown** its owner attached to it: the spell stays in its caster's
  play, `<owner>:hero:<slug>`, which `_hero_profile` reads for a lent
  hero beside the controller's play. And a lent hero's button names it:
  `formatting.ref_label` resolves either spelling (`hero_on`), where it
  had printed the bare `3:hero:troq_bashar`.
- **On Discord a loan is a destination in the patrol view** (the panel
  step, 2026-10-15; `PatrolView`). Where the options carry `zones`,
  each opponent's open slots follow the owner's five in the slot menu --
  "<name>'s elite: empty", the seat named by `seat_label` -- and the
  second menu asks "Who is lent to <name> as elite?" for one; the
  caption lists each loan under the owner's five, "**Lent to <name> as
  elite**: Tenderfoot 1/2". The view keeps one map keyed by destination
  (`<seat>:<slot>` for a borrower's, the slot's name for the owner's) so
  a card placed anywhere is offered nowhere else, and **Lock in patrol zone**
  splits it (`split_assignment`): `lent`, `{seat: {slot: ref}}` with
  the seat a string as a journal read back has it, beside `assignment`
  where something is lent, and `assignment` alone where nothing is, so
  a duel's and a dragon's answer is as it was. **Clear**, **Nobody** and
  **Undo...**'s **Back** treat a loan as a slot. Two menus still hold:
  the owner's five and at most four opponents' open slots are a
  select's twenty-five. Choosing moves on to the owner's next empty
  slot, never into an opponent's zone unasked. The view words only the
  destination; what lending does is the model's line at the lock.

### The dragon: the teams, the one base, the two prompts

- **The teams and the deal** (decision 9; question 1: `dragon` in the
  code, "team" in what the bot says). `MatchState.dragons` (saved, `[]`
  otherwise) holds the two pairs, `DRAGON_TEAMS`, the first seat of each
  its head. `seats.dragon_of`, `teammate`, `other_team` and `opponents`
  read it, so a teammate is never an opponent and everything that asks
  `opponents` -- the tower's reach, Moment's Peace, a hand revealed, a
  dead hero's levels, "an opponent's" -- means the other team's two.
  `new_match` draws the first *team*, deals both its seats 4 workers
  and the other's 5, and every base `base_cap`'s 30.
- **The team's one base is its head's `base_hp`** through `base_seat`;
  **the second seat's is dealt and never read** -- a number in the save
  that means nothing, kept from being read by the `base_hp` grep. A
  destroyed tech building or add-on deals its 2 to the team's base, and
  a line names the base for its team (`formatting.base_owner`), however
  the attack or the effect named the seat. **A team never holds two of
  the same add-on** (Rulebook p. 13): `build_option` refuses one the
  teammate has, citing the page.
- **What a teammate sees** (decision 13; questions 4 and 14):
  `engine.team_sees` is the teammate in a dragon and nobody otherwise;
  `hands_visible_to` folds it in, and `shown_to` -- behind
  `codex_remaining`, `own_deck` and `tech_picks_of` -- refuses a codex,
  a deck or a tech choice that is neither the viewer's own nor the one
  `team_sees` names. Nothing else of the teammate's is shown, and a
  borrower or a watcher sees nothing hidden.
- **`match.active` is whichever teammate is acting** -- a deviation
  from step 5's prompt, which kept it the team's head. 145 sites in
  `codex/` read `match.active` as "the seat doing this" (every action,
  the attack under way, a frame's `cause`), and giving each a seat of
  its own would have been a second reading of the same thing. So the
  driver runs an action **with the seat that answered it active**
  (`driver.answer`) and puts the team's head back between actions
  (`driver.settle_active`, once nothing stands half-resolved); every
  reading made on a seat's behalf -- its prompt's options and ask -- is
  made under `seats.as_active`. **A prompt's options are built one way,
  `prompts.asked_options`**, with the asked seat active where it is one
  of the turn's seats: `_finished` and `driver.advance` both ask it.
  Until 2026-10-16 `advance` rebuilt the run's following prompt with
  plain `with_options`, before `apply` settled the head, so after a
  teammate's action the head's question carried the teammate's hand
  (the review of 2026-10-15; nothing read it yet, since the cog asks
  `pending_prompts`). The questions that are the team's do not
  move: `turn_seats` is the active seat's dragon, the same for both
  teammates, and `next_seat` and the snapshots rest on the head
  (`seats.head_of`).
- **The dragon's two seats are two pending prompts** (decision 8).
  `pending` stays the one reading and takes a `seat`; `pending_all`
  lists everything the team waits on and `pending_prompts` its
  questions, one per acting seat; `pending_prompt` keeps its one-seat
  reading for the duel and the free-for-all and raises `SeveralAsked`
  where a dragon has more than one, so nothing reads one teammate's
  prompt for the team's. Where one teammate's action stands
  half-resolved -- an effect under way, an attack declared, a choice
  inside it -- the team's question is that one alone, and the other's
  click is refused "Waiting on {player:n}'s attack." (`_half_resolved`):
  the bot serialises what the rulebook calls simultaneous.
  `GameResult.prompts` carries the list (empty outside a dragon, never
  on the wire).
- **Every action names its seat in a dragon.** `ARGUMENTS` allows
  `player` on every kind; the driver finds the prompt of the action's
  seat, fills `player` in where an older journal leaves it out, and
  journals the action with it, so a replay is exact. A duel's and a
  free-for-all's actions are never given one, which is why their
  journals are the bytes they were.

### The dragon's team turn

- `begin_turn` readies both teammates in seat order, takes the turn's
  one snapshot, then runs each teammate's upkeep in seat order, the
  second's after the first's has run to its end and carried on its frame
  (`then`), so a question the first's upkeep asks stands where a
  restart finds it. **The turn opens on both teammates' tech
  confirmations** (`TECH_CONFIRM` or `TECH_CHOICE`) and begins once both
  are settled.
- **Each seat's patrol lock is its own** (`PlayerState.locking`,
  `locked`, cleared with the next team turn): the first lock ends that
  seat's actions, the second the team's main phase; the draw runs for
  both (a stash answered per seat, `stash_choice`) and the "End of turn"
  line and the turn's heading name both players
  (`formatting.turn_heading`). Both teammates owe their tech choice,
  which stands through the other team's turn (`standing_prompts` is
  every seat outside the turn).
- **An extra turn is one seat's alone** ("you means you", Rulebook
  p. 13): Double Time's `extra_turns` names a seat, `MatchState.solo` is
  that seat while it runs, and `turn_seats` and `acting_seats` are that
  seat -- the teammate neither readies nor acts.
- **The team's end.** A destroyed base is the other team's win:
  `MatchState.winner` is the winning team's head and `conceded` the
  conceding team's, `GameOverOptions.winners` both players, and the
  lines name both (`formatting.side_names` and `side_verb`: "{player:1}
  and {player:2} win!"), and the finished game's ask is the same words
  -- a destroyed base is on the final board, so it says no more (the
  author, 2026-10-15). A teammate who cannot pay Promise of Payment's debt
  loses for the team (question 17).

### Attacking a dragon

- **The other team's two patrol zones are one** (Rulebook p. 13;
  `RulesEngine._pooled_rows`): a squad leader of either, the attacker
  choosing which; else any patroller of either; else anything with HP of
  either and the shared base once. Each zone's own rows are `_foe_rows`,
  so stealth, flying and unstoppable are read zone by zone, and a zone
  the attacker passes protects nothing of the partner's. The defender
  prompt lists each row with its seat.
- **The tower is the team's one** -- a team never holds two of one
  add-on (`team_tower`) -- and **detects for the whole team**, whichever
  of them or their cards is attacked, and deals its 1 to an attacker of
  anything the team controls (`detecting_tower`, `towers_seeing`). The
  author decided this on 2026-10-14 (question 26), overriding both the
  plan's narrower "you means you" reading and step 5's first cut, which
  let each teammate's tower detect for the shared base. On its owner's
  own turn the teammate's *Detect* uses it too.
- **Overpower's excess** may go to anything the attacked team controls,
  read with the duel's priority over the team (`overpower_team`;
  question 25, as built). **Moment's Peace** removes its caster's cards
  and the shared base from the units' defenders, not the teammate's.

### The words: "friendly", "your", "you"

- **"Friendly" is a flag on an effect's part** (decision 10).
  `Part.friendly` is set on the eight parts whose text says it and reads
  the things of the seat the part is relative to *and its teammate's*
  (`target_candidates`' `friends`, `dragon_of`): Aged Sensei, Bloom,
  Forest's Favor, Sparring Partner, Eyes of the Chancellor, Max Geiger's
  max level, Vandy Anadrose's friendly unit, and Orpal Gloor's
  "friendly to the dead unit", relative to the dead unit's controller
  (`units_of_against`). Focus Master and the five Healing cards read
  the teammate by the engine (`focus_prevents`, the healing upkeep).
  `test_codex_dragon.FriendlyTests` holds the fourteen texts to the
  flags, and that no part saying "your" carries one.
- **"Your", "you control" and a count of what "you have" stay the
  controller's**, and so does Mythmaking's malus (an *opponent's*
  legendary units). **Nobody spends a teammate's gold, uses a
  teammate's abilities or patrols in a teammate's zone** -- each is
  impossible by construction, and `YouMeansYouTests` holds each.
  Dothram Horselord's "a player with more total ATK" is read per seat
  (question 24).
- **A line a table reaches says nothing a duel's shape implied**
  (2026-10-15, a sweep after step 7): Reputable Newsman's ask says
  "opponents can't play" as the card does; Dothram's stays line says
  "no player has more total ATK than each other player", the card's
  words, and names each player's total, since a bare list is seat
  order; Stampede's line names the base the excess goes to through
  `base_owner` where the opponents share one (the duel's, the other
  team's), and "the base of the opponent they attack" at a
  free-for-all, where it is whichever the unit attacks (`combat`). The
  cog's own lines went the same way: the hand and the test game's tech
  refusals count no seats, a free-for-all's test-game lobby line says
  "every seat", and the undo's button names the other team.

### The board

The author settled the boards from step 2's pictures (question 2,
2026-10-14; decision 14), replacing the worksheet's first proposal of a
free-for-all stacked alone.

- **A free-for-all has two views, every panel upright** -- a table of
  five has no "across". **Stacked** (`render._compose_table`): the
  active player's panel at the bottom under the turn's divider, the
  others above in turn order, the next to play nearest. **Side by
  side** (`_compose_rows`): rows of two from the bottom, the active
  player and the next to play under the divider -- three players one
  panel above two, four two above two, five three rows with one at the
  top, a lone panel centred -- and the turn's pill over the acting
  player's own panel rather than the board's middle. Beside the
  turn's pill on the same divider, a second, quieter one names whose
  turn is next, "NEXT: KIME" (`render.DIVIDER_NEXT`, `seats.next_seat`
  -- an extra turn and the playoff included), in both views and every
  table size. Side by side it is centred over the panel right of the
  active player's, the next to play's, as the turn's is over the active
  player's (the author, 2026-10-20); stacked, where no panel is to the
  right, the two pills are centred together. A long name is cut with an
  ellipsis where the pill would pass the turn's or the rule's end. A finished game
  names nobody. The author asked for it on the divider rather than in
  the room beside a lone top panel, which four players and the stacked
  view do not have (2026-10-20). Three or four open
  side by side and five stacked (`CodexGame.start`); **Swap view**
  toggles the two (`swapped_layout(layout, table=True)`), and `/codex
  side_by_side` is the same toggle. The record's `board_layout` keeps
  its spellings: "side_by_side" is the rows of two, "stacked_upright"
  draws as "stacked".
- **A dragon is two rows of two** (`render._compose_dragon`): the acting
  team's row at the bottom, its head on the left, under the divider,
  which names both teammates ("PERRYTOM AND ANN'S TURN 9") or the one
  seat of an extra turn; the other team's row above, turned whole to
  face it as the duel's far panel is -- so its head's buildings are at
  the far corner where the duel's far base is -- or the same way up;
  **Swap view** flips between the two, and `/codex side_by_side`
  answers that a dragon's board is the two rows of two. **Each team's
  one base is drawn in both teammates' columns with JOINT on it** (the
  author, 2026-10-15), a level band along the tile's foot
  (`JOINT_STRIP`, `lay_band`) so the base's name and heart stay clear;
  this replaced decision 14's base drawn once in the head's column with
  the second column a tile shorter, which step 6's first cut built. The
  base tile's heart carries the base's HP where it is not the 20 it
  prints, so a dragon's 30 reads as 30.
- **Every composition is built from three pieces** (step 7):
  `_even_panels` (a row's panels drawn at its tallest's height),
  `_pair_strip` (one or two panels two columns wide, a quiet rule
  between) and `_stack` (strips over the turn's divider and the bottom
  one); `compose_board` makes the divider's label once, from
  `turn_seats`. A TARGET whose rows lie on several seats is pictured
  with the table stacked, on one seat that seat alone (`side_shown`).
  `scripts/render_codex_sample.py` draws three, four and five players
  both ways (`ffa-*`, three and five also from seat 2) and a dragon both
  ways and from the other team (`dragon-*`).
- **A lent patroller is drawn in the borrower's slot, tagged with its
  lender's name, and nowhere else** (2026-10-15, after the panel step
  found a lent hero in no picture). `render_body` reads a zone through
  `MatchState.patrollers(seat)` -- the one reading that carries a hero
  another player lent into it, `<owner seat>:hero:<slug>` -- and
  resolves either spelling of a hero's ref through `hero_on(seat, ref)`;
  its card, its level chit and its stats are what the engine's
  `board_reading` gives for a hero on that side, `controller_of` being
  the borrower while it is lent, so the elite's +1 and the borrower's
  growth grants show on it and the owner's do not. The owner's side
  draws it nowhere, with no code saying so: its command-zone slot is
  empty because the hero is in play, and the grid and the owner's own
  slots are read off the owner's readings (`heroes_in_play`,
  `PlayerState.patroller`), which leave a lent hero out -- so the
  owner's panel with the hero lent is the panel with the hero in its
  own slot, pixel for pixel outside that slot's tile, which
  `tests/test_codex_render.py` holds. **The tag is "Lent from bo"**,
  the lender's name as the nameplate spells it, a state tag in the
  grey of ARRIVED and DISABLED (`lay_states`, the lowest of the three,
  on the foot of the art), on a lent unit as much as a lent hero
  (`CardInstance.lent`, `HeroState.lent_to`): a lent unit sits in the
  borrower's play zone and was drawn as theirs unmarked, and whose it
  is matters when it dies (it pays its owner) and at the borrower's
  upkeep (it goes home), so the two are marked alike. The first cut
  said LENT alone, and the author asked for the name (2026-10-15):
  LENT says the card is not the borrower's, not whose, and on a table
  of five the hero's art and the owner's empty command zone are a
  slower way to tell; the possessive "BO'S" came next, and the author
  asked for the sentence instead, which also keeps the name's own
  spelling rather than shouting it. A name is the frontend's, so
  `render_board`'s and `render_side`'s `names` are handed down through
  `render_panel` to `render_body` and `grid_cells` (the cog's
  `side_file` passes its `seat_names`; a lent unit sidelined off its
  slot waits in the borrower's grid for the upkeep, so the grid reads
  them too), the owner read off the ref (`split_lent_ref`) or the card
  (`owner`); a caller that gives no names gets "Lent" (`lent_tag`). A
  Discord name runs to 32 characters, so the name is cut with an
  ellipsis to `LENT_TAG_WIDTH`, the card's width inside `lay_states`'
  margin.
  Every sample picture was hashed before and after: the duel's, the
  dragon's and the standard game's are byte-identical, and so is the
  lender's own side; only the free-for-all's changed.

### On Discord: the turn message and the panels

- **The turn message names and pings the seats whose turn it is**:
  the model's heading, `post_turn_message` pinging `turn_seats`
  (`mention_ids`). The turn's footer names the one seat a free-for-all's
  turn waits on, or a dragon's two.
- **A question per seat, never the team's one.** The cog reads a
  seat's question with `pending`'s `seat` (`Codex.prompt_for`) and the
  turn's caption with `pending_prompts`, so nothing on Discord asks
  `pending_prompt` of a dragon. Every action a dragon panel sends names
  its seat (`PanelView.act`).
- **My hand** answers by the clicker's seat: an acting seat's panel,
  any other seat its hand. **Tech** finds the clicker's standing choice
  (every seat whose turn has ended holds one), and in a dragon then
  sends the teammate's picks pictured read-only, or "<name> has not
  chosen their tech yet." (`Codex.send_teammate_tech`). The Codex
  browser offers "<name>'s codex: <view>" after the clicker's own. Every
  picture of a dragon seat's hand carries the teammate's under it,
  captioned "<name>'s hand: 5 cards." (`revealed_caption`, which names
  an Eyes of the Chancellor's reveal by player wherever there is more
  than one opponent; the duel's "Their hand" stands).
- **Two panels at once, each edited by its own player's clicks**
  (decision 13). A public click edits the turn message through the gate
  and the clicker's panel in place; the other panel stands as it was,
  since the bot reaches an ephemeral message only through its own
  player's interaction. Its next click is checked against the options as
  they stand, and where refused `PanelView.refuse` edits it in place to
  the prompt as it now stands, the reason above it (outside a dragon a
  refusal is said privately, `SafeView.refuse`). A seat asked nothing
  now -- the teammate's action part-way, the team's confirmations owed
  by the teammate, or this seat locked -- gets **the waiting panel**
  (`Codex.put_waiting`, `WaitingView`) with **Back to my turn**.
- **A test game's one person holds both acting seats**: My hand puts
  up the first unlocked teammate's panel with a question
  (`Codex.acting_seat_for`) and **Switch to <name> (<team>)**, which
  edits the panel in place to the other's (the author, 2026-10-15,
  replacing step 6's first cut, which sent a new message each time and
  piled the panels up).
- **The panels of a table.** A defender button names the side it was
  offered on where the same ref stands on two (`against`); the tower's
  detection labels each thing by the opponent whose it is
  (`RulesEngine.holder_of`).
  The standing board of the turn that ended is lit for
  `history.previous_turn_owner`, read off the snapshots, since on a
  table the seat before the active one is not the previous turn's
  (playoffs and Double Time make it neither) -- and seated as that
  turn was: `previous_turn_solo`, off the same snapshot, says whether
  it was one seat's extra turn, which `turn_seats` reads before the
  team, so a dragon's turn that stood on either side of a Double Time
  is headed and lit for who took it, not for the turn after it
  (`roll_over`; 2026-10-15, when it carried the new turn's `solo`).
  A target's row names its seat's player -- "fencer's base" -- for
  anyone but the panel's own seat, a teammate's included, where the
  duel said "Their" (2026-10-15): "their" says nothing with several
  other seats, and one spelling serves every table; "Your" stays, and
  a test game, whose seats are one person's, names a side by its team.
- **The free-for-all's two additions are on the panel** since
  2026-10-15, built from the options alone: **Repair base** on the
  board's row ("The free-for-all's additions") and each opponent's open
  slots as destinations in the patrol view ("Lending is a control
  change"). Steps 3 and 4 had left both to each other, and PR #595's
  body said PR #593 was adding the repair; #593 is Brick Thief's
  targeted repair of a building, not the base's.

### Who may undo, concede and abandon

(Decision 15, the author's of 2026-10-11, and its two later undos.)

- **To the start of my turn**, and the fine undo to before an action of
  this turn: any acting seat's, without consent -- in a dragon either
  teammate's, the team's turn and the teammate's actions included, since
  the undo to the turn's start takes those back unasked too (question
  7). `start_tech_over` asks both teammates' picks again.
- **To the start of the previous turn** asks whoever's turn it unwinds:
  `previous_turn_owner`, the snapshot's active seat, in a free-for-all
  (the button reads "(asks the player before you)"); the other team in a
  dragon ("(asks the other team)", `previous_turn_label`), the public
  question mentioning both, either of whom may **Agree**
  (`UndoConfirmView.agreeing`), never the asker's teammate.
  A helper may agree behind the confirmation, and anyone at the table
  may **Refuse** -- the duel's consent, kept (question 12).
  **Whose a turn was is one reading, `history.previous_turn_owners`**:
  the snapshot's `solo` seat alone where the turn was one seat's extra
  turn, else the team of its `active` seat, else that seat -- what
  `turn_seats` read while it ran. An extra turn is "you means you"
  (Rulebook p. 13), so its take-back and the agreement to unwinding it
  are that seat's alone, and the teammate who did not play it is
  offered neither (2026-10-15; until then the cog widened the owner to
  the team on both counts). The public question then reads as a
  free-for-all's -- "your turn", "the player whose turn it was".
- **Take back the end of my turn** is the seat that ended the turn
  (`end_of_turn_owner`) in a free-for-all, either player of the team
  that did (`end_of_turn_owners`) in a dragon -- the one seat whose
  extra turn it was, alone -- while nobody whose turn it now is has
  acted; once closed it names who started --
  "{player:n} has already started their turn." or "The other team has
  already started their turn." (`opponent_started`,
  `OTHER_TEAM_STARTED`) -- where the duel keeps "Your opponent".
- **Concede**: none in a free-for-all; **in a dragon it needs both
  teammates** (question 6). Who may concede at all is the model's to
  say: a click from somebody holding no seat goes to `check_concession`
  with `None` and is refused in its words, "Only a player of the game
  can concede it.", in every variant (2026-10-15; the cog used to answer
  it with "the game's two players"). The first click is the clicker's own
  ephemeral confirmation; its second posts a public question naming the
  teammate (`TeamConcedeView`, modelled on `UndoConfirmView`, not
  persistent: after a restart the asker asks again) -- **Agree** the
  teammate's or a helper's behind the confirmation, never the asker's;
  **Refuse** either teammate's -- and on Agree the service's `concede`
  ends the game, the other team winning.
- **Abandon** is unchanged in every variant: a seated player's own game
  or a helper's; one player may abandon a game of five (question 11).
- **Rematch** is a fresh pick of heroes (decision 16; question 8): the
  same seats and, in a dragon, the same teams, every seat's heroes
  cleared (`CodexGame.rematch`), and the first player or team drawn
  again at Start. Since 2026-10-20 the duel's rematch is the same.

### The goldens and the whole-game test

Three goldens, each a seeded game through its `GameService` with the
tokens intact: the duel's (`codex_service_*`, never re-recorded by the
series), a three-player free-for-all's (`codex_ffa_*`, re-recorded once
in step 3) and a dragon's (`codex_dragon_*`, re-recorded once in step
6). `tests/test_codex_driver_full_game.py` plays three to five players
and the dragon, basic and standard, with nothing of `cogs/` imported;
its policy answers every seat (decision 18: no AI), through `answer`,
which names the seat asked in a dragon -- the golden asks it the same
way. `tests/test_codex_cog_free_for_all.py` and
`tests/test_codex_cog_dragon.py` drive the cog with Discord faked, a
person a seat and one person on every seat, and the request table above
gained their rows without changing any it had.

### What step 7 moved to one home

Whatever steps 2 to 6 wrote twice moved to one place, with the tests
unchanged and every picture the sample script draws byte-identical by
SHA-256:

- **The model**: `seats.other_team` (the render's and `next_seat`'s two
  spellings of "the other pair"); `next_seat`'s fallback through
  `turn_order`; `MatchState.base_seat` through `dragon_of`; the deal's
  teams from `game.DRAGON_TEAMS` and its base HP from `base_cap`; a
  part's friends through `dragon_of`; `formatting.side_names` and
  `side_verb` (the flow's and the prompt's joins and four "win"/"wins");
  `resolve._one_base` (the Captured Bugblatter test written twice); and
  `RulesEngine.holder_of`, defined twice since step 4, the first
  shadowed and never run, now once.
- **The board**: `_even_panels`, `_pair_strip`, `_stack`, the label made
  once, and a free-for-all read by its variant rather than a count of
  players.
- **The cogs**: `codex_helpers.seat_label`, `seat_labels` and
  `mention_ids` over fourteen inline "seat_name or Player n", three
  joins and two ping lists; the cog's uncalled `questions` (the
  service's `waiting_all`) removed; `PanelView.refuse` outside a dragon
  is `SafeView.refuse`.
- **The tests**: `lock` and `attack` in `test_codex_free_for_all`
  (`end_turn` and `attack_base` over them, the additions' copies gone);
  `labels` and `end_main_and_lock` in `codex_cog_fakes`; `answer` and
  `numbered_seats` in `test_codex_driver_full_game`, which the golden
  imports; the sample script's `table_putter` and `set_table`.

What was left in two places on purpose: the wording that differs by
variant (the undo's and the concession's sentences say different things
in a duel, a free-for-all and a dragon, so a shared helper would be a
phrase table, not one reading); `TeamConcedeView` and `UndoConfirmView`,
which share a shape but not a gate, a timeout or a message; and the
service's handful of `waiting_all(...) if match.dragons` reads, each
with its own condition.

### Not yet, and still open

- **A dragon panel made stale by the teammate's click** is refreshed
  only by its own player's next click, as decision 13 says; nothing
  pushes it.

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

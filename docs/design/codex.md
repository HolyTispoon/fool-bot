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
destroyed base through the driver alone; nothing on Discord plays it
yet (step 3). The model's purity rules hold for `codex/` from its
first commit (`tests/test_model_purity.py`): no `discord`, no
`async def`, Pillow only in `codex/render.py`, which a later step
writes.

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

**The art comes in the same run, and is not in the tree yet.** The
import fetches each card's and hero's picture by its `sirlins_filename`
from `codexcards-assets.surge.sh` into `codex/images/cards/<slug>.jpg`
(330 by 450), and cuts the Screentop module's sheets (@GRAG/Codex,
whose spec one GraphQL query to `api.screentop.gg` returns) into
`codex/images/board/`. The session that wrote step 1 could reach the
card data but neither image host, so it committed the data alone; and a
sheet's cells are pinned in `BOARD_SHEETS` only after somebody has
looked at the sheet, so until then the import saves each unpinned sheet
whole under `board/sheets/` and reports it rather than guessing a grid.
`tests/test_codex_cards.py`'s art tests skip, saying why, until
`codex/images/cards/` exists. `/codex card` answers without a picture
until then.

**The emoji are drawn here and uploaded by hand.** Application emoji
belong to one application and there is no upload code, so
`scripts/render_codex_emoji.py` draws `gold`, `exhaust` and `target`
into `codex/images/emoji/` (the heroes' two faces once their art is
imported), `codex.png` is the medallion cut from the module's card back,
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

- **Two readings the rulebook leaves open are built the strict way**
  and asked on the step's PR: a tech building needs the one below it
  *finished* (so Tech I and Tech II are never built in one turn), and
  an add-on is refused while the slot holds one rather than replacing
  it.

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

## Running it

On the Mac, from the checkout, with `CODEX_DISCORD_TOKEN` in `.env`:

```bash
python3 codexbot.py
python3 scripts/import_codex_cards.py      # re-import the cards and the art
python3 scripts/render_codex_emoji.py --in-place
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

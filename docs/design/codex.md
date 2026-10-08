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
alone. Step 4 put the whole turn there -- the panel, the turn message
rolled over at the turn's end, the tech choice during the opponent's
turn, the two undos and the resume -- so two people can finish a game
on the vanilla engine. Step 5 gave the engine the combat keywords, so
every card whose text is a keyword plays in full and the tower is worth
building. Step 6 gave it the rest: the spells, the arrives and attacks
triggers, the heroes' bands, the abilities, the static grants and costs,
the ongoing spells with their tokens and partners, and the upkeep's
effects and their order -- so every card of the basic set does what it
says and `UNIMPLEMENTED` is empty. The model's purity rules hold for `codex/` and `gamesaves/codex/`
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
  page; the bot quotes none of it.
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
  the playmat whole as `codex/images/board/playmat.png`, and eight
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
| `workers/` | The two worker cards' faces off the neutral card sheet -- x4, printed "Player 1", and x5, "Player 2" -- which the database does not picture (the author, 2026-10-08: the module has them) | the worker card's slug |
| `specs/` | The twenty spec cards | the spec, as a slug |
| `backs/` | `card`, `hero`, `token` | -- |
| `patrol/` | The five slots' icons, white on the module's blue; the first printed "Patrol Leader", the rulebook's squad leader | the slot |
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
| `MAIN_ACTION` | the active player | hire, summon, level, play, build, attack, detect with the tower (step 5), use an ability (step 6), or end the main phase -- the options are the engine's `legal_actions`, each card in the hand with its cost and why it may not be played, each ability with why it may not be used |
| `CHOOSE_DEFENDER` | the active player | which of `legal_defenders` the declared attacker takes, or `cancel` to take the attacker back; asked after the attacker, so a misclick costs nothing (decision 11) |
| `PATROL` | the active player | slot to unit or hero, any left empty; ends the main phase (UMR p. 10) |
| `TECH_CHOICE` | the choice's owner | the picks from their codex, within the bounds -- two, or none to two at ten workers (UMR p. 5) |
| `TECH_CONFIRM` | the choice's owner | `confirm` or `change`; the turn begins only once it is answered |
| `OBLITERATE_CHOICE`, `SPARKSHOT_TARGET`, `OVERPOWER_TARGET` | the active player | the three choices inside an attack, each asked only where there is something to choose ("The keywords", below) |
| `TARGET` | the effect's controller -- the active player | what a part of a spell, a trigger or an ability chooses, asked as the part resolves and only where there is more than one thing it could choose ("Targeting and the effects", below) |
| `APPEL_STOMP_TOP` | the active player | `top` or `discard`: where Appel Stomp goes once it has resolved |
| `UPKEEP_ORDER` | the active player | which of healing and Star-Crossed Starlet's damage goes first, asked only where both are due |
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

**`UNIMPLEMENTED` is empty from step 6**: every card of the basic set
plays its text, and `tests/test_codex_effects.py` says where each one's
text lives -- a keyword the engine reads, or a row of the tables in
`codex.effects` ("Targeting and the effects", below). The table's job
is done until the next spec (step 9) brings cards the engine has not
met; a card with text nothing plays fails that test until it is
handled or listed. What follows is how it got there.

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
knows a keyword at all -- the panel's menus are the prompts' options, as
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
  panel's menu can say why a defender is legal ("it flies over the patrol
  zone", "it sneaks past the patrol zone", "it is unstoppable").
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
  and `begin_turn` makes it new again.
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

**Once an attack has begun it cannot be taken back.** **Cancel** on the
defender menu is still there for a misclick on the attacker, since
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
trigger from 5, River's ability from 3); and the static texts are a
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
  is playable when one of its parts can resolve, and refused with "it
  has nothing it could target" when none can.
- **A target is on either side of the table**, so an answer names it
  `"<seat>:<ref>"` (`2:unit:7`, `1:base`) -- a hero and a building are not
  unique by ref alone. Every effect may choose what its text allows,
  your own things included: Wrecking Ball may hit your own base, Brick
  Thief may repair an opponent's building, Hired Stomper may hit itself
  ("mandatory, own units and itself included").
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
  the answer runs the effects in that order and opens the main phase --
  **the turn-start snapshot is taken there, after the upkeep**, so an undo
  to the start of the turn never asks the order again. The surplus's card
  is drawn first, since nothing it does is ordered against the others.

Every line is the model's, with tokens: "{card:spark} deals 1 to
{player:2}'s {card:iron_man}", "{player:1} pays {gold:1} for its resist",
"{card:harmony} summons a {card:dancer} token for {player:2}". A card
drawn is a count, never a name -- Appel Stomp's draw, the surplus's -- and
a card returned to a hand is named, since it was in play.

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
  detected this turn), and `combat` on the match -- the attack standing
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

### Naming by slug in the tests

`tests/codex_positions.py` stages a position by card slug --
`put(match, seat, "iron_man", patrol="elite", damage=1)`. D12 Ball's
tests name a player by role because its roster is data the author
revises; Codex's cards are fixed data imported whole at a pinned
commit, so a test says exactly the card it means.

## The reference commands

`/codex card <name>` answers in the channel with the card's picture
and nothing else (the author, 2026-10-08): the card already shows its
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
that shows nothing answers nothing. `/codex rules <keyword>` answers
with a keyword's rulings as the official rules they are.
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
`codex-<n>-<p1>-vs-<p2>` (capped at 100 characters), its permissions
left as the lobby's. The service deals and runs the
first turn's ready phase and upkeep in one save, the lobby is edited
once to say the game has started, its buttons gone, and the first
turn's message goes up under it, pinned. The categories are the Codex
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
  for `</codex lobby:ID>`, falling back to the command's name in plain
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
  `codex_lobby_prompt()`: the `</codex lobby:ID>` mention, which puts
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

- **The board is the module's playmat with the position laid on it**
  (`codex/render.py`): the hero as its card in the first hero slot
  while it is in the command zone, a time-rune chit on the card for
  its summoning runes; once summoned it is on the field like any other
  unit, so it lies in the play zone with the units, first among them,
  with its level chit -- or in its patrol slot (the author,
  2026-10-08: the mat's hero slots are where the heroes off the board
  wait, three of them for the standard game's three; the board used to
  keep the hero in its slot while in play and leave the slot empty
  while it was in the command zone, which read the wrong way round);
  patrollers in their five slots; the Tech I to III tiles in their places, faint where
  unbuilt, tagged *building* while under construction and *destroyed*
  when they are, with damage chits; the base's damage on the mat's own
  base, which the mat prints (the module's base tile was tried and
  doubled the printed base); the add-on's card in its slot; the draw
  pile as the card back with its count on a tag below the medallion;
  the discard and the workers as counts; the play zone's cards -- the
  hero, then the units -- across the mat's middle, in a grid of square
  cells so a card turned sideways (exhausted) fits too, each with
  damage and rune chits and *arrived* when it came this turn. A strip along each mat's
  top names the player, the spec and the hero, and counts the gold, the
  hand, the codex and the base; the active player's strip is lit.
  Composed at the mat's own size, scaled by `BOARD_SCALE` (0.6) and
  saved as WebP at quality 85 (`BOARD_QUALITY`), about 220 KB; the
  hand and the codex pictures stay PNG.
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
  takes to arrive, which is its size. As PNG the board was about 2 MB;
  measured 2026-10-08, the same board is about 340 KB as JPEG at
  quality 85 and 220 KB as WebP, and at 1:1 the three are hard to tell
  apart, so the board is WebP (the author, 2026-10-08) -- the smallest
  of the three, and Discord shows it natively. That shortens the moment
  rather than removes it.
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
active player and summarised in **one public message per turn**.
`tests/test_codex_cog_turn.py` drives it through the cog with Discord
faked -- `tests/codex_cog_fakes.py` logs every request by route -- and
plays a whole game through the panels to a destroyed base, every click
held to the request budget below.

### The panel

**My hand** on the turn message is one button with two answers by who
clicked (the author, 2026-10-08): the active player gets the panel for
whatever the match asks them, the other player their hand pictured and
nothing to press. The panel is the view for `MAIN_ACTION` and
`CHOOSE_DEFENDER` (`TurnPanelView`), for `PATROL` (`PatrolView`), and
for the tech prompts (`TechChoiceView`, `TechConfirmView`) --
`view_for_prompt`'s table, the only place a kind becomes a view.

- **One ephemeral message, edited by its own interactions.** Each click
  answers through the service and the panel is edited in place with
  `interaction.response.edit_message`, built afresh from the new
  prompt's options. That edit goes through **the interaction's own
  webhook**, not the channel: it spends nothing from the channel's
  ~five-in-five bucket the turn message lives in (rate-limits.md), and
  it is the one thing an ephemeral message can be edited by -- the bot
  cannot find an ephemeral message again, so every entry point (My hand,
  **Tech**, `/codex resume`) makes a fresh one and the cog never looks
  for an old panel.
- **Its picture is the hand**, numbered, greyed where it may not be
  played, each card's cost after reductions -- `render_hand` over
  `MainActionOptions.hand`, a field the prompt grew for it so the
  picture and the menu read one list. **Play a card** names each
  playable card by its number in the picture. `render_prompt` gives the
  main phase and the defender no picture of their own (the board on the
  turn message is theirs); the tech picker's is the codex with the
  picks framed in gold and counted (`render_codex`'s `picked`), the
  confirmation's the picks as a hand.
- **Built from the options and nothing else.** A control the engine
  says no to is disabled with its reason as its label ("Hire: a worker
  has been hired this turn"); a menu with nothing to offer is a disabled
  menu saying why, so the panel keeps its shape. **Hire worker** opens
  a menu of the hand's cards (the one hired with is trashed unseen);
  **Undo** the choices `history.undo_targets` says are open. The
  defender menu labels each defender with why it is legal -- "squad
  leader", "patroller", "nothing is patrolling" -- which is the engine's
  (`defender_rows`, carried as `DefenderOptions.why`), not the view's.
- **An effect's questions are the same panel going on** (step 6): a
  `TARGET` is one menu of what the part may choose, each labelled with
  whose it is, what it costs in resist and whether the flagbearer rule
  forces it; Appel Stomp's place and the upkeep's order are buttons. The
  abilities share the panel's last row with the hero's levels -- **Level
  up or use an ability...** -- because a message has five rows and the
  other four are taken; only an ability that may be used now is in the
  menu. The panel's picture stays the hand.
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

The Lock that ends a turn closes the panel ("your turn is over") and
sends the tech picker as an ephemeral follow-up to the same click.
**Tech** on the turn message reopens it -- for the player whose turn it
is not, alone -- all through the opponent's turn; each **Save tech**
replaces the last, privately: **nothing is said in the channel** -- not
the cards, and not that a choice was made. The choice is announced in
its owner's ready phase alone, as "puts 2 tech cards into their discard
pile" (the author, 2026-10-08). The menu has a line per
copy left in the codex, so two copies of one card can be picked.

From the third turn on the new turn opens on its player's confirmation:
the new turn message says it waits on them to confirm their tech (the
cog's caption, `TECH_WAIT`, gone once the ready phase has run), and My
hand is `TechConfirmView` -- the picks pictured, **Confirm** and
**Change**. Confirm runs the ready phase and the upkeep, and the panel
becomes the turn's actions in place. The prompt asked for the
confirmation to be sent "as the follow-up to the opponent's Lock when
they are present"; a follow-up reaches only the clicker, so it is not
sent to the other player -- the turn message's mention and its caption
point them at My hand instead.

### The turn message, and the two-message gate

Each turn's message is posted when the turn begins: its text
"**Turn 7** -- @perrytom (Bashing)" -- the model's heading, whose turn
as a mention, which the post pings and no edit does -- then the turn's
lines, the model's with
their tokens rendered at the door; the board as its picture; and
**My hand**, **Tech**, **Codex**, **Swap view**. It is pinned and the
previous one unpinned. After each action it is edited through the gate
with the new lines and the re-rendered board. The text stays under
2000 characters: past that the earliest lines fold into "*and n more*",
since the board carries the position.

- **The heading is the model's, and it is not narration** (the author,
  2026-10-08). "**Turn 7** -- @perrytom (Bashing)" is
  `codex.formatting.turn_heading(match)`: the turn, its player
  *addressed* -- `{to:n}`, a token the cog draws as a mention and plain
  text as the name -- and their deck, `deck_name(player.specs)`, one
  spec in the basic game and "Anarchy/Blood/Fire" for the standard
  game's three. The cog puts it at the head of every turn message and
  never folds it, so it reads even while the turn waits on its tech, and
  after a restart that lost the turn's lines. The model used to open
  each turn with a narration line of its own as well ("**Turn 7** --
  perrytom's turn."), which under the heading said it twice; that line
  is gone. **The turn's end is narration**: "**End of turn 7** --
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
  writes the current turn's message (`message_of`). The old message's
  last edit is written by the cog directly, under the gate's own lock
  so no gate write lands on it after, and then the gate is forgotten,
  so its next write is the new message's. The game's end is the same
  last edit, then one public line -- the model's "wins" sentence --
  with the final board, rendered once and uploaded twice.
- **What the cog remembers**, in memory only: the turn's lines, and
  each recent turn's *first lines* -- what its message said when its
  main phase opened -- which is what an undo puts back. After a restart
  neither is known: the gate leaves the message's text alone until the
  turn ends or `/codex resume` re-posts the table.

### The requests per click

Measured with the fakes, and held on every click of the whole-game test:

| Click | The channel's bucket | The interaction's webhook |
| --- | --- | --- |
| An action in the main phase (play, hire, build, summon, level, attack, the defender) | **1**: the turn message's edit through the gate | 1: the panel's edit |
| A choice that moves nothing public (End main phase, a patrol slot, a tech pick before saving, Undo's menu) | **0** | 1 |
| Save tech | **0**: nothing is said until the owner's ready phase | 1 |
| Lock patrol (the turn's end) | **4**: the old message's last edit, the new one's post, its pin, the old one's unpin | 2: the panel closed, the tech picker sent |
| The attack that destroys a base | **2**: the last edit and the winner's line with the board | 1 |
| Undo to the start of the turn | **1** | 1 |
| Undo to the previous turn | **1** to ask (the public question), then **3** on Agree: the old message's edit, its pin, the current one's delete | 2 on Agree: the question answered in place, the fresh panel |

The gate's full-image link adds one settling edit after a burst of
clicks, at most one per interval, as it does for D12 Ball (step 3 turned
the link on for Codex); the fakes upload nothing it could link, so the
table counts the board's own writes. A turn of a dozen clicks is about a
dozen edits spread over the gate's six-second windows, which coalesces
any that come faster into one trailing edit.

### The two undos, and who may take each

**Undo** on the panel offers what `history.undo_targets` says is open
(`GameService.undo_targets`); the cog decides nothing about what a
snapshot holds.

- **To the start of my turn** is the active player's alone, with nobody's
  consent: `GameService.undo_to_turn_start` restores the turn's snapshot
  and saves once; the turn message goes back to its first lines and
  "Undone to the start of the turn." (`history.UNDONE`), the board
  through the gate, and the panel re-renders from the restored prompt.
- **To the start of the previous turn** unwinds the opponent's turn
  too, so it posts a public question naming them (`UndoConfirmView`):
  **Agree** is the opponent's -- or a game helper's, behind the helper's
  confirmation -- and never the asker's; **Refuse** is either player's.
  The question holds the turn it was asked on and is refused once the
  game has moved past it. On Agree, `undo_to_previous_turn` restores the
  older snapshot; the previous turn's message
  (`CodexGame.previous_turn_message_id`, a record field step 4 added,
  `None` in an older save) is edited back to its first lines and the
  undone line, with the restored board and its buttons, and pinned
  again; the current turn's message is deleted -- the one deletion in
  the flow -- and the opponent, now the active player, gets a fresh
  panel. Where the previous message is not known (an older save, or a
  second such undo in a row), a fresh turn message is posted instead.
  Not persistent: after a restart the asker asks again.

### The resume path

A restart loses every panel -- they are ephemeral and live in the old
process -- and nothing else: the question is the model's (`pending`).
The turn message's buttons are re-armed from `turn_message_id`, so **My
hand** after a restart asks the same question with the same options
(`tests/test_codex_resume.py`, including a declared attacker waiting on
its defender). `/codex resume` runs any step the bot owes, re-posts the
turn message pinned, and hands the clicker their panel afresh -- the
actions for the active player, the open tech picker for the other.

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

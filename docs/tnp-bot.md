# The New Project on Discord: Humans against Humans

**This is a worksheet, not a specification.** It was written on
2026-11-04 from the author's ask: start building *The New Project* (TNP)
into the Discord bot, with only Humans against Humans to begin with. Both
seats play the Human faction and both are people; there is no AI. It was
written against the Google Drive folder **The New Project** (the
rulebook, the glossary, the player aide, the unit sheet, map 3.3 and the
Human base board) and against what the repository already has: the
model/Discord split, `GameService`, the driver, `gamekit/`, `botkit/`,
the board gate, and the Codex bot as the nearest precedent. **Nothing in
it is a rule.** The questions under "Questions for the author" have to be
answered before the steps get their prompts, because several of them
decide what the model holds.

## What was found

### The sources, and which one wins

| File in Drive | Version | What it gives |
| --- | --- | --- |
| `Rules/Rulebook - The New Project 3.docx` | v3, "everything is simultaneous" | setup, the turn, the battle procedure, the glossary |
| `Rules/Glossary.docx`, `Rules/player aide 3-5.pdf` | aide 3-5 | the traits; a turn order that **has** a Production phase (the rulebook's text does not) |
| `Units/The New Project unit sheet v3.xlsx` | v3 | four tabs: Humans, XzzzX, Space Dragons, Technology -- costs, the three attack values, initiative, traits, scouting, count |
| `Player boards/green human base board v4 constructed.png` (and blue) | v4 | production caps, max supply, unit costs in materials and gold, the upgrades, "max 2 tech facilities" |
| `Map and territories/map3.3.pdf` / `map3.3-1.png` | 3.3 | fifteen territories, two bases, the resource counts; `map2.1`/`map2.2` are older |
| `Cards and tokens/` | -- | the tech tokens, tech cards and tactic deck art (not yet read) |

The files disagree in places, and those places are listed below. **The
plan assumes the newest file wins** (board v4 over rulebook v3), and
asks the author wherever that guess decides something.

### The game, in the terms the code will use

- **Two seats, Blue and Green**, both Humans. Each has a **base** (an area
  on the map, outside the fifteen territories), a **player board** (the
  production facilities), a hand of **technology cards**, an available
  **resource pool** (materials and gold), and **units**, each either
  available, deployed, in a territory's defense spot, or stranded.
- **The map**: territories 1 to 15 and the two bases, each territory with
  its resource tokens (blue minerals, orange minerals, gems, counted down
  as they are harvested), a controller or none, its defenders, and a
  stranded flag per seat.
- **The turn is simultaneous.** In each phase both seats act, and nothing
  is revealed until both are done: Infrastructure (spend the pool on
  units, buildings and upgrades, all of which complete at Production),
  Deployment (units go face down into the attack spots A and B -- C with
  *Command and Control CPU* -- each with a territory card, and into
  defense spots), March (A for both, then B, then C; within a slot, in
  ascending territory number: neutral conquest, battle, control and
  stranded, harvest), Production, Trade, Cleanup.
- **A battle** is up to six rounds. Each round: scouting advantage, the
  battle line (alternate placement, engaging and flanking), the
  declaration to retreat, damage in initiative order (the attacker rolls
  first within a group), and victory. A base under attack adds the
  emergency base defense, can't retreat, and puts two base cards at the
  ends of the line, where two hits destroy a facility.
- **The game ends when an attack on a base succeeds.**
- **The Human faction**: fourteen units (Worker, Mercenary, Stealth
  Sniper, Cyborg Soldier, Jeep, Tank, The Transformer, Chopper Carrier,
  Viper Spy Plane, Fighter Bomber, Smart Mines, Rocket Launcher, Laser
  Cannon), four facilities (Barracks, Factory, Airport, Base Defenses),
  each with an infrastructure upgrade and one or two unit upgrades, and
  the Technology tab's 44 card rows (blue-mineral economy techs,
  orange-mineral military techs that name Human units, gem techs).

### The map, as read from map 3.3

The map has to be drawn again by code (the author, 2026-11-04), so the
adjacency becomes data. This is **my reading of the picture, to be
confirmed**; three borders meet at a point and might not count as
adjacent, and those are marked with "?".

| Area | Adjacent to | Resources |
| --- | --- | --- |
| Blue base | 10, 13, 14 | -- |
| Green base | 11, 12, 15 | -- |
| 1 (centre) | 2, 3, 4, 5, 6, 7 | -- |
| 2 | 1, 5, 7, 8, 10 | -- |
| 3 | 1, 4, 6, 9, 11, 12? | -- |
| 4 | 1, 3, 7, 9 | 10 blue, 10 orange |
| 5 | 1, 2, 6, 8 | 10 orange, 10 blue |
| 6 | 1, 3, 5 | 8 gems |
| 7 | 1, 2, 4 | 8 gems |
| 8 | 2, 5, 13, 14, 10? | -- |
| 9 | 3, 4, 12, 15 | -- |
| 10 | Blue base, 2, 14, 8? | -- |
| 11 | Green base, 3, 12 | -- |
| 12 | Green base, 9, 11, 15, 3? | 10 orange |
| 13 | Blue base, 8, 14 | 10 orange |
| 14 | Blue base, 8, 10, 13 | 10 blue |
| 15 | Green base, 9, 12 | 10 blue |

The two sides are not mirror images. Green's 12 touches four areas and
lies between 15 and 11; Blue's 13 touches three. Whether that is
deliberate is question 14.

### What is new to this repository

- **Simultaneous turns.** D12 Ball and Codex both have a player whose
  turn it is. TNP has two seats answering the same phase at once,
  privately, with a reveal once both are done. The nearest precedent is
  the Codex two-headed dragon, where two prompts are pending at once
  (`codex/prompts.py`, `pending_all`, `SeveralAsked`). The secret tech
  choice in Codex (`standing_prompts`) is the precedent for a secret
  answer waiting until the reveal.
- **Hidden information everywhere.** Production happens behind a screen,
  units are deployed face down, and tactic cards are played face down.
  Codex worked out the shape for this on Discord: one public message,
  and each player's own view in an ephemeral panel ("Hidden information
  on Discord: the ephemeral shape, as tried", in
  [codex.md](design/codex.md)).
- **A battle is long.** It can run six rounds, each with a battle line
  placed force by force, a retreat declaration and a target chosen per
  force. On Discord that is a lot of clicks, and every one has to fit
  the rate-limit rules ([rate-limits.md](design/rate-limits.md)).

## The decisions

These are recommendations unless marked as the author's. The ones the
author has not yet seen are repeated as questions below.

1. **Humans against Humans only, with no AI** (the author, 2026-11-04).
   Both seats are the Human faction and both are played by people. The
   faction is still a field on the seat from the first commit, so XzzzX
   and Space Dragons come in later as data plus their own rules, without
   a migration.
2. **Its own process and token, like Codex** (recommended): a
   `tnpbot.py` beside `foolbot.py` and `codexbot.py`, with
   `TNP_DISCORD_TOKEN`, its own state file, its own games file, and the
   `/tnp` command group. The author chose this for Codex on 2026-10-07 so
   that one game's rate-limit buckets and crashes do not land on the
   other's ([codex.md](design/codex.md), "Its own process, its own
   token"), and a game with six-round battles is the most expensive of
   the three on requests. The alternative is a cog in fool-bot (cheaper
   to stand up, but it shares fool-bot's buckets). This is question 1.
3. **The split from the first commit.** A `tnp/` package holds the
   model, held to the model's rules (no `discord`, no `async def`, no
   Pillow outside `tnp/render.py`) by a purity test. A
   `gamesaves/tnp/` holds `GameService` and the storage, and
   `cogs/tnp/` plus `cogs/tnp_views/` are the frontend. It takes the
   shared pieces as they are: `gamekit/` (wire, driver constants, token
   resolver, `SavedField`, storage), `botkit/` (channels,
   `GameLockedView`), `cogs/game_auth.py`, `gamebot.GameBot` and
   `BoardRefresher`. It copies the shapes of `prompts.py`,
   `flow/result.py` and `flow/driver.py`, as Codex did.
4. **The rules are committed as a document the code is checked
   against**: `docs/tnp-rules.md`, the rulebook v3 transcribed, with the
   answers to the questions below folded in and each change dated in a
   log beside it. This plays the part `docs/living-rules.md` plays for
   D12 Ball: an ambiguity goes to the author, never into the code as a
   guess.
5. **The unit and tech data are imported, never typed in.** A
   `scripts/import_tnp_data.py` reads the unit sheet (the `.xlsx` from
   Drive, through the same route as `scripts/import_from_workbook.py`)
   into `tnp/data/humans.json` and `tnp/data/technology.json`. Units and
   techs are keyed by slug (`stealth_sniper`, `command_and_control_cpu`)
   and never by name. The per-board numbers the sheet does not carry
   (production caps, max supply, upgrade costs, trade rates) become a
   small hand-kept `tnp/data/human_board.json`, transcribed from the v4
   board and checked by the author, because they exist nowhere in the
   sheet. The map is the same kind of data: `tnp/data/map.json` (areas,
   adjacency, resources, and the outline of each area for drawing).
6. **The map and the player board are drawn by code** (the author,
   2026-11-04). `tnp/render.py` draws the map (areas, numbers, resource
   counts, control markers, stranded tokens, and the face-down stacks the
   opponent can see), each seat's player board (facilities, upgrades,
   what is queued and what is built, supply left), and the battle (the
   line as columns, each force's count and damage, the round track, the
   base cards). Area outlines are data, so the same drawing can redraw
   the map whenever the author changes it. The unit art in Drive goes on
   the tokens if the author wants it, through an import script, as Codex
   does with its art.
7. **One reading of what the game is waiting on, and it can be both
   seats.** `tnp/prompts.py`'s `pending` returns the prompts open now
   (both seats' in a simultaneous phase, or one seat's during a battle
   line) or the step the bot owes. A simultaneous phase moves on when
   both seats have locked in. Until then a seat may change its own plan,
   and its locked-in answer is held on the match the way Codex's tech
   choice is, so a restart loses nothing.
8. **Within a battle, the choice rolls the dice.** A force's target is
   the player's choice, and picking it rolls that force's dice at once,
   shown in the same message. D12 Ball's rule that "nothing rolls dice on
   its own" exists because there a roll is a moment of its own; here a
   battle of six rounds would double its clicks for no decision. Every
   draw comes from `engine.rng`, seeded in the tests. This is question 15.
9. **One public message per phase, edited in place; private panels for
   everything secret.** The public message holds the map, the phase, and
   who has locked in. Each seat's player board, hand and plan live in its
   own ephemeral panel, opened from a button on that message. A battle
   gets its own message, edited round by round through the board gate.
10. **Undo comes later.** Codex had undo from its first commit, and the
    journal is the shape to copy, but in a simultaneous phase a seat can
    already change its plan until it locks in, which covers most of what
    undo is for. A real undo is listed under "Later" and is question 16.

## Questions for the author

Answered questions move into `docs/tnp-rules.md` and the step prompts.

**Rules the files disagree on**

1. **One bot or two?** Should TNP be its own process with its own token
   (recommended, as Codex was), or a cog in fool-bot?
2. **How hit values work.** The keyword table says Weak hits only on a 6,
   Fair on 4 to 6, and Strong misses only on a 1. The battle text says
   "an attack value of 3 hits on 3 or less, sixes always miss, a value
   above 5 is still 5, an attack rate of 0 rolls one die per two units
   and hits on 1s". The tech cards add +1 and +2, flanking adds +1, and
   each column skipped costs −1. One reading reconciles all of it, and
   the odds come out the same as the keyword table's: **Weak = 1, Fair =
   3, Strong = 5, Can't = X; hit on a roll at or under the value after
   modifiers, capped at 5, and a 6 always misses.** Is that the rule?
3. **Production.** The aide has a Production phase between March and
   Trade, and the rulebook's text leaves it out. Is the order
   Infrastructure, Deployment, March, Production, Trade, Cleanup, with
   what is placed in Infrastructure finished at that turn's Production
   and deployable next turn?
4. **Emergency base defense before or after Tactical Command?** The
   rulebook's body puts it before, and its own summary and the aide put
   it after.
5. **Tech facilities: two (board v4) or three (rulebook v3)?**
6. **The basic game.** The tech decks are "in an advanced game", but
   harvesting draws tech cards and trading turns cards into resources.
   What does a harvest give in the basic game? Should the first build be
   the basic game, the advanced game, or the advanced game alone?
7. **Trade rates.** The rulebook says they are on the player board, but
   board v4 has none. What does each card trade for, at the normal rate
   and at the emergency (base defense) rate, and what do Jewler and
   Trader change?
8. **Gold.** The sheet's column is "Gems" and the board shows a coin.
   Is gold the resource, and does it only come from trading cards? Is
   the starting pool 5 materials and 0 gold?
9. **What building costs.** The board gives the infrastructure upgrades
   (1 material each), but not the cost of building the Factory or the
   Airport, nor the unit upgrades (Stealth, Cyborg, Robotic facility,
   Fighter Bomber, Laser Cannon). What are those costs?
10. **Movement.** Attacking needs a path of controlled territories from
    the base. What does "moves like air units" mean for air units and
    for a chopper with its load? Can air units attack a territory with
    no controlled path?
11. **Spots.** Is it attack spots A and B for everyone, with C only
    through *Command and Control CPU*? Is there one defense spot per
    controlled territory plus the base's? Does an empty controlled
    territory stay controlled?
12. **What the opponent sees at deployment.** How many face-down units
    are on each spot? Which territory card is beside each attack spot,
    or only that one is there?
13. **The battle line.** Is it formed again every round, as the rulebook
    lists, or once and then only changed when a force dies? On Discord,
    re-forming every round is the biggest single cost in clicks.
14. **The map.** Is the adjacency table above right, including the three
    "?" corners (8 with 10, 3 with 12)? Is the asymmetry between 12 and
    13 deliberate? And is map 3.3 the map?
15. **The dice.** Is it all right for the target choice to roll the dice
    (decision 8), rather than a separate Roll button?
16. **Undo.** Is changing your plan before you lock in enough to start
    with, with a real undo later?
17. **A successful attack on a base.** Does an attack on an undefended
    base win at once? Does a defender who survives six rounds hold even
    if the base cards took hits?

## The steps

In the order they pay off. Each step is one branch off an up-to-date
`main` and one PR, with the suite green and no file under `d12ball/` or
`codex/` changed unless the step says so. Each ends on a **stop**: the
thing the author looks at before the next step is worth starting. The
prompts are written once the questions are answered.

| # | Step | Size | Stop |
| --- | --- | --- | --- |
| 1 | The rules, the data and the bot standing up | medium | `docs/tnp-rules.md` read and approved by the author; `/tnp unit tank` answers in the test server |
| 2 | The battle, with no frontend | large | a test fights any two Human forces to a result with the seeded `engine.rng`, covering scouting, flanking, the position modifiers, tough, repair, splash, retreat and the base cards |
| 3 | The map and the player board, drawn by code | medium | the author compares the drawn map and boards to map 3.3 and board v4 and approves them |
| 4 | A whole game through the driver | large | a test plays Blue against Green from setup to a fallen base through `driver.apply` with nothing from `cogs/` or `discord` imported |
| 5 | The lobby, the channel and the opening position | medium | two people reach turn 1 on Discord, each with a player board the other cannot see |
| 6 | The simultaneous turn on Discord | large | two people play Infrastructure to Cleanup, with neutral conquests and a harvest; a restart mid-phase keeps both plans |
| 7 | Battles on Discord | large | two people fight a battle on Discord round by round, and the request count per round is measured and within the gate |
| 8 | Finishing a game | small | a base falls, the game ends, offers a rematch and is archived; a seeded whole game is pinned byte for byte as the golden |
| 9 | The technology cards | large | tactic cards, building techs and tech facilities all play, every Human tech row does what it says, and the import covers the whole Technology tab |
| -- | Later, and not now | -- | XzzzX and Space Dragons; an AI; undo; a web page like the Codex site |

### 1. The rules, the data and the bot standing up

Transcribe the rulebook into `docs/tnp-rules.md` with the answers folded
in, and start `docs/design/tnp.md`. Write `scripts/import_tnp_data.py`
(the Humans and Technology tabs into `tnp/data/`), plus the hand-kept
`human_board.json` and `map.json`, each checked by a test against the
other (every unit a facility builds exists, every adjacency goes both
ways, every resource is on a territory). Stand up `tnpbot.py` (or the
cog, if question 1 goes that way) through `gamebot.GameBot` with
`/tnp unit` and `/tnp rules`. Add the `tnp` series to
`scripts/claim_web_step.py`, a row to the map in `CLAUDE.md`, and the
deploy script beside `run_codex_bot.ps1`.

### 2. The battle, with no frontend

`tnp/battle.py`: forces formed from revealed units, scouting advantage
and its count of forced placements, the battle line (engaged columns and
flanking), retreat, damage by initiative group with the attacker first,
hit values per question 2, the position modifier, tough, repair, splash,
the base cards and the facility they destroy, and victory after six
rounds. Each choice inside a battle is a prompt kind (place a force,
declare a retreat, pick a target), so the battle runs through the same
driver as the rest of the game. This comes before the turn because it
holds the riskiest rules and is self-contained.

### 3. The map and the player board, drawn by code

`tnp/render.py` and `scripts/render_tnp_sample.py`: the map from
`map.json`'s outlines, the player board from `human_board.json`, and the
battle line. Fonts bundled and loaded by absolute path, every render
off the event loop, and the pictures put in front of the author. Nothing
here is tested beyond size, as with every other picture
([board-image.md](design/board-image.md), "Look at the image").

### 4. A whole game through the driver

`tnp/components.py` (`MatchState`, the seats, the map's state, the
saved-field table from the first commit), `tnp/game.py` (the record and
the lobby's rules), `tnp/engine.py`, `tnp/prompts.py` (both seats asked
at once), `tnp/flow/` (infrastructure, deployment, march, conquest,
control and stranded, harvest, production, trade, cleanup) and the
driver, with `GameService` in `gamesaves/tnp/`. The deliverable is the
test that plays a game to a fallen base with no frontend imported, plus
the purity ratchet.

### 5. The lobby, the channel and the opening position

`/tnp create_game`, two seats taken by people, the channel opened the
way Codex opens its own, the setup, and the opening position: the public
map message, and each seat's player board in its own panel.

### 6. The simultaneous turn on Discord

Each phase's panel per seat: the queue in Infrastructure, the stacks and
territory cards in Deployment, the trade, and **Lock in**. Then the
reveal, the march's narration as one message per slot, and the map
redrawn once per slot through the gate. Resuming after a restart reads
the plans saved on the match.

### 7. Battles on Discord

A battle's own message and picture. Placement in the battle line, the
retreat declaration and the target choices go to whichever seat is
asked, each click edits the battle message, and the dice are shown. The
requests per round are counted with a fake like `tests/codex_cog_fakes.py`
and kept within the five-in-five bucket.

### 8. Finishing a game

The base falls, concede, abandon, rematch, the channel archived, and
the golden: a seeded whole game through `GameService` recorded byte for
byte.

### 9. The technology cards

Tactical Command (face down, both at once, revealed together),
building techs and their slots, tech facilities and their cap (question
5), every Human tech row's effect as data in the way `codex/effects.py`
holds Codex's, and the harvest drawing from the three decks. If question
6 makes the advanced game the only game, this step moves to after step
4, and steps 6 and 7 carry its panels.

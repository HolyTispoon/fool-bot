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
| `vassal module.png` (Vassal module folder) | -- | the Vassal module's Blue board: the **conversion rates**, the Factory's and Airport's build costs, "max 2 tech facilities", the deployment board's attack spaces A, B and C; the Cyborg Soldier's air rating differs from the sheet (question 18) |
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

The map has to be drawn again by code (the author, 2026-11-04), so
the adjacency becomes data. **This table is measured, not read by
eye**: each territory of map 3.3 was flood-filled and traced, and two
areas are adjacent where their outlines meet. Two pairs meet at a single
point, 8 with 10 and 9 with 11, mirroring each other, and **both are
adjacent** (the author, 2026-11-05). 3 and 12 do not touch. The traced
outlines are what the canvas drawing of the map uses, and will be
`map.json`'s.

| Area | Adjacent to | Resources |
| --- | --- | --- |
| Blue base | 10, 13, 14 | -- |
| Green base | 11, 12, 15 | -- |
| 1 (centre) | 2, 3, 4, 5, 6, 7 | -- |
| 2 | 1, 5, 7, 8, 10 | -- |
| 3 | 1, 4, 6, 9, 11 | -- |
| 4 | 1, 3, 7, 9 | 10 blue, 10 orange |
| 5 | 1, 2, 6, 8 | 10 orange, 10 blue |
| 6 | 1, 3, 5 | 8 gems |
| 7 | 1, 2, 4 | 8 gems |
| 8 | 2, 5, 10, 13, 14 | -- |
| 9 | 3, 4, 11, 12, 15 | -- |
| 10 | Blue base, 2, 8, 14 | -- |
| 11 | Green base, 3, 9, 12 | -- |
| 12 | Green base, 9, 11, 15 | 10 orange |
| 13 | Blue base, 8, 14 | 10 orange |
| 14 | Blue base, 8, 10, 13 | 10 blue |
| 15 | Green base, 9, 12 | 10 blue |

The two sides are not mirror images, though the two corners are. Green's 12 touches four areas and
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
2. **A cog in fool-bot, not a bot of its own** (the author,
   2026-11-04). `cogs/tnp/` is loaded by `foolbot.py` beside
   `cogs.d12ball`, under fool-bot's token, as the `/tnp` command group,
   with its own games file (`data/tnp_games.json`) through
   `gamekit.storage`. There is no new process, token, deploy script or
   `.env` variable. This differs from Codex, which the author put in its
   own process on 2026-10-07 so that one game's rate-limit buckets and
   crashes would not land on the other's ([codex.md](design/codex.md),
   "Its own process, its own token"), so two things follow:
   - **Requests.** Discord's limits are per channel and per
     interaction, and each TNP game gets its own channel, so a TNP
     battle does not slow down a D12 Ball game's channel. What the two
     games share is the application's global limit and the bot's
     gateway connection. Step 8 measures the requests per battle round
     against the five-in-five channel bucket, as D12 Ball's gate does.
   - **Crashes.** An exception in the TNP cog has to stay in the TNP
     cog. A view's errors go through its `SafeView`, and the cog's
     startup sweep catches and logs a bad saved game rather than raising
     out of `cog_load`, so a broken TNP save cannot stop fool-bot from
     loading D12 Ball. Step 6 tests the second point: a corrupt
     `data/tnp_games.json` leaves D12 Ball's cog loaded.
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
8. **A d12, and within a battle the choice rolls the dice.** Every die
   is a d12 (the author, 2026-11-05; question 2). A force's target is
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

1. ~~**One bot or two?**~~ Answered (the author, 2026-11-04): a cog in
   fool-bot. See decision 2.
2. ~~**How hit values work.**~~ Answered (the author, 2026-11-05):
   **a d12**. Weak hits only on a 12, Fair on 6 and above, Strong on 3
   and above; a 12 always hits and a 1 always misses. The hit values are
   on the player board, which is being redrawn, so the new numbers go on
   it. Every dice modifier is being adjusted for the d12: the list is in
   "The dice modifiers, for the d12" below. Still to confirm: that +N
   means "hits on N lower" (Fair +2 hits on 4 and above), so a 12 still
   hits and a 1 still misses whatever the modifiers. And that the d6
   battle text's "a value above 5 is still 5" and "an attack rate of 0
   rolls one die per two units" go, since the 12 and the 1 bound the
   roll and no Human unit has a 0.
3. **Production.** The aide has a Production phase between March and
   Trade, and the rulebook's text leaves it out. Is the order
   Infrastructure, Deployment, March, Production, Trade, Cleanup, with
   what is placed in Infrastructure finished at that turn's Production
   and deployable next turn?
4. **Emergency base defense before or after Tactical Command?** The
   rulebook's body puts it before, and its own summary and the aide put
   it after.
5. **Tech facilities: two (board v4 and the Vassal module) or three
   (rulebook v3)?**
6. ~~**The basic game.**~~ Answered (the author, 2026-11-05): there is
   no basic game and no advanced game. The tech cards are always used:
   the three decks are shuffled at setup, harvesting draws from them, and
   tactic cards, building techs and tech facilities all play from the
   first game.
7. ~~**Trade rates.**~~ Answered from the Vassal module (the author,
   2026-11-05, pointing there): a mineral card trades for 2 materials or
   1 gold, a gem card for 3 materials or 2 gold; in emergency production
   a mineral card gives 1 material (no gold) and a gem card 1 material or
   1 gold. Still to confirm: a card trades for materials *or* gold, not
   both (Jewler and Trader read that way), and blue and orange minerals
   trade alike.
8. **Gold.** The sheet's column is "Gems" and the board shows a coin.
   Is gold the resource, and does it only come from trading cards? Is
   the starting pool 5 materials and 0 gold?
9. **What building costs.** Partly answered from the Vassal module: the
   Factory costs 2 materials, and the Airport 3 and needs a Factory. Each
   unit upgrade box (Stealth, Cyborg, Robotic facility, Fighter Bomber,
   Laser Cannon) shows one material icon, as the infrastructure upgrades
   do for their 1 material, so the reading is 1 material each. Is it?
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
14. **The map.** ~~Are the two corner contacts adjacent?~~ Answered
    (the author, 2026-11-05): 8 with 10 and 9 with 11 are adjacent. Still
    open: is the asymmetry between 12 and 13 deliberate, and is map 3.3
    the map? These are notes Q2 and Q3 on the canvas drawing of the map
    and the board, where each open question is pinned beside what it is
    about.
15. **The dice.** Is it all right for the target choice to roll the dice
    (decision 8), rather than a separate Roll button?
16. **Undo.** Is changing your plan before you lock in enough to start
    with, with a real undo later?
17. **A successful attack on a base.** Does an attack on an undefended
    base win at once? Does a defender who survives six rounds hold even
    if the base cards took hits?
18. **The Cyborg Soldier against air.** The unit sheet and board v4 say
    Fair; the Vassal module says Weak. Which?

## The dice modifiers, for the d12

Every card and rule that changes a roll, as unit sheet v3 and rulebook
v3 word them, so the author can set each one's d12 value (the author,
2026-11-05). They were all written for a d6. On a d12 each step of +1
is worth half as much (one face in twelve rather than one in six), so
the straight translation is to double each number. The last column is
that translation, a starting point and not a decision.

The three ratings have moved too:

| Rating | d6 (keyword table) | d12 (the author) |
| --- | --- | --- |
| Weak | 6 only: 1 in 6, 17% | 12 only: 1 in 12, 8% |
| Fair | 4 to 6: 3 in 6, 50% | 6 to 12: 7 in 12, 58% |
| Strong | 2 to 6: 5 in 6, 83% | 3 to 12: 10 in 12, 83% |

So Strong stays the same, Fair gets a little better, and Weak gets half
as likely to hit.

**Tech cards that add to a roll** (Technology tab; count, type and cost
as the sheet has them):

| Card | Deck | Type | Count | Text | d6 | Doubled |
| --- | --- | --- | --- | --- | --- | --- |
| Arm Workers | orange minerals | tactic | 2 | Workers get +1 attack | +1 | +2 |
| Enhancing Drugs | orange minerals | tactic | 2 | Mercenaries get −1 initiative, +2 for all rolls; each hit kills 2 mercenaries | +2 | +4 |
| Advanced Targeting | orange minerals | tactic | 2 | Cyborgs gain +2 air | +2 vs air | +4 vs air |
| Positioning | orange minerals | tactic | (blank) | Jeeps and Tanks gain +1 when attacking forces they are engaged with (no penalty for adjacent columns, −1 for 2 away etc.) | +1, and the column penalty eased by one | +2, and eased by 2 |
| Air Cover | orange minerals | tactic | (blank) | Choppers and Vipers gain +3 vs. air | +3 vs air | +6 vs air |
| Heat Seeking Missile | orange minerals | tactic | 2 | Viper gains +2 attack | +2 | +4 |
| Explosives | gems | tech facility, 1 material | 3 | Stealth Snipers gain +4 vs. base defense or when targeting base (short text: "inf. gain +4 vs. base") | +4 vs base | +8 vs base |
| AA Missiles | gems | building tech | 3 | Attached units gain +2 vs. air | +2 vs air | +4 vs air |
| Lasers | gems | building tech | 3 | Attached units gain +2 vs. Arm. | +2 vs armored | +4 vs armored |
| Grenades | gems | building tech | 3 | Attached units gain +2 vs. inf. | +2 vs infantry | +4 vs infantry |
| Specialized Training | gems | building tech | 3 | Attached unit get +1 for all rolls | +1 | +2 |

**Tech cards that give rerolls** (no number to change, but each is
worth more on a d12, where a miss is more often a near miss):

| Card | Deck | Type | Count | Text |
| --- | --- | --- | --- | --- |
| Ammo Depos | orange minerals | tech facility, 1 material | 2 | Gain 2 rerolls each battle |
| Extra Large Ammo Depos | orange minerals | tech facility, 3 materials | 2 | Gain 4 rerolls each battle |

**The rules' own modifiers** (rulebook v3, "Battle procedure"):

| Modifier | Rulebook text | d6 | Doubled |
| --- | --- | --- | --- |
| Flanking | "placing their Forces ... behind existing forces as flanking (gain +1 bonus)" | +1 | +2 |
| Position | "minus one per column you are skipping" | −1 a column | −2 a column |
| The base cards | "always with at least −1 position modifier" | −1 at least | −2 at least |
| The cap | "if your attack value is higher than 5 ... your value is still 5 before position modifiers" | 5 | goes, if the 12 and the 1 bound the roll (question 2) |
| Attack rate 0 | "may roll 1 die for each two units and score a hit on 1s" | -- | goes (question 2) |

Not listed, because they change no roll: the cards that remove units or
hits rather than modify dice (Snipe, Super Cannon, Exploding Smoke
Shells, Shields, Bunkers, Attached Mechanics, Medic on Board), and the
ones that change initiative or scouting alone (Radars, Jet Engines,
Satellite Connection). Two rows have no count in the sheet (Positioning
and Air Cover, as well as Shields), so the importer will refuse them
until the sheet gives one.

## The steps

In the order they pay off. Each step is one branch off an up-to-date
`main` and one PR, with the suite green and no file under `d12ball/` or
`codex/` changed unless the step says so. Each ends on a **stop**: the
thing the author looks at before the next step is worth starting. The
prompts are written once the questions are answered.

| # | Step | Size | Stop |
| --- | --- | --- | --- |
| 1 | The rules, the data and the bot standing up | medium | `docs/tnp-rules.md` read and approved by the author; `/tnp unit tank` and `/tnp card grenades` answer in the test server |
| 2 | The battle, with no frontend | large | a test fights any two Human forces to a result with the seeded `engine.rng` and a d12, covering scouting, flanking, the position modifiers, tough, repair, splash, retreat and the base cards |
| 3 | The map and the player board, drawn by code | medium | the author compares the drawn map and boards to map 3.3 and board v4, with the d12 hit values, and approves them |
| 4 | A whole game through the driver | large | a test plays Blue against Green from setup to a fallen base through `driver.apply` with nothing from `cogs/` or `discord` imported, harvesting from the three decks and trading cards for resources |
| 5 | The technology cards | large | tactic cards, building techs and tech facilities all play; every Human tech row does what it says, with the author's d12 values |
| 6 | The lobby, the channel and the opening position | medium | two people reach turn 1 on Discord, each with a player board and hand the other cannot see |
| 7 | The simultaneous turn on Discord | large | two people play Infrastructure to Cleanup, building with tech cards, with neutral conquests and a harvest; a restart mid-phase keeps both plans |
| 8 | Battles on Discord | large | two people fight a battle on Discord round by round, tactic cards included, and the request count per round is measured and within the gate |
| 9 | Finishing a game | small | a base falls, the game ends, offers a rematch and is archived; a seeded whole game is pinned byte for byte as the golden |
| -- | Later, and not now | -- | XzzzX and Space Dragons; an AI; undo; a web page like the Codex site |

### 1. The rules, the data and the bot standing up

Transcribe the rulebook into `docs/tnp-rules.md` with the answers folded
in, and start `docs/design/tnp.md`. Write `scripts/import_tnp_data.py`
(the Humans and Technology tabs into `tnp/data/`), plus the hand-kept
`human_board.json` and `map.json`, each checked by a test against the
other (every unit a facility builds exists, every adjacency goes both
ways, every resource is on a territory). Add the `cogs/tnp/` cog to
fool-bot's extensions in `foolbot.py` with `/tnp unit`, `/tnp card` and
`/tnp rules`.
That changes fool-bot's command tree, so the PR says the live host
needs a command sync. Add the `tnp` series to
`scripts/claim_web_step.py` and rows for the new packages to the map in
`CLAUDE.md`.

### 2. The battle, with no frontend

`tnp/battle.py`: forces formed from revealed units, scouting advantage
and its count of forced placements, the battle line (engaged columns and
flanking), retreat, damage by initiative group with the attacker first,
the d12 hit values and modifiers (question 2), taking a modifier from a
card as an input so step 5 only supplies them, the position modifier,
tough, repair, splash, the base cards and the facility they destroy,
and victory after six rounds. Each choice inside a battle is a prompt kind (place a force,
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
control and stranded, harvest drawing from the three decks, production,
trade -- cards for resources at the board's rates -- and cleanup) and the
driver, with `GameService` in `gamesaves/tnp/`. The deliverable is the
test that plays a game to a fallen base with no frontend imported, plus
the purity ratchet.

### 5. The technology cards

The cards' effects, now that the decks are dealt and traded in step 4:
Tactical Command (face down, both at once, revealed together), building
techs and their slots, tech facilities and their cap (question 5), and
every Human tech row's effect as data in the way `codex/effects.py`
holds Codex's, with the d12 values the author sets from "The dice
modifiers, for the d12". The tech cards are in every game (question 6),
so this comes before anything goes on Discord, and steps 7 and 8 carry
its panels.

### 6. The lobby, the channel and the opening position

`/tnp create_game`, two seats taken by people, the channel opened the
way Codex opens its own (in a **TNP Games** category, apart from D12
Ball's), the setup, and the opening position: the public map message,
and each seat's player board in its own panel. The persistent views are
re-armed at startup, and a test shows that a corrupt TNP games file
leaves D12 Ball's cog loaded (decision 2).

### 7. The simultaneous turn on Discord

Each phase's panel per seat: the hand, building techs and tech
facilities and the queue in Infrastructure, the stacks and
territory cards in Deployment, the trade, and **Lock in**. Then the
reveal, the march's narration as one message per slot, and the map
redrawn once per slot through the gate. Resuming after a restart reads
the plans saved on the match.

### 8. Battles on Discord

A battle's own message and picture. The tactic card chosen in secret,
placement in the battle line, the
retreat declaration and the target choices go to whichever seat is
asked, each click edits the battle message, and the dice are shown. The
requests per round are counted with a fake like `tests/codex_cog_fakes.py`
and kept within the five-in-five bucket.

### 9. Finishing a game

The base falls, concede, abandon, rematch, the channel archived, and
the golden: a seeded whole game through `GameService` recorded byte for
byte.

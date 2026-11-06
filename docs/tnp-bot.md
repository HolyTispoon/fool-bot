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
it is a rule.** The questions under "Questions for the author" were
answered by 2026-11-05, and the steps' prompts were written from the
answers. The author answered them in the doc **TNP
Open Questions and Dice** (https://claude.ai/artifact/CwXvSPjLSaNaYyVtDkx1TY),
which also holds the dice modifiers' d12 values, and on the canvas
drawing of the map and the board
(https://claude.ai/artifact/4hRVXBPhYeKDHyoUSwnank); each answer was
recorded here as it came.

## What was found

### The sources, and which one wins

| File in Drive | Version | What it gives |
| --- | --- | --- |
| `Rules/Rulebook - The New Project 3.docx` | v3, "everything is simultaneous" | setup, the turn, the battle procedure, the glossary |
| `Rulebook - The New Project 3` (Google Doc, the folder's root, edited 2026-10-25) | v3, **the newest copy** | the .docx's text with two changes: a second way to win -- "harvest 51% of the planet's resources" -- and Emergency Base Defense before Tactical Command; two open comments of the author's from 2017 (faction tech decks, emergency production) |
| `Rules/Glossary.docx`, `Rules/player aide 3-5.pdf` | aide 3-5 | the traits; a turn order that **has** a Production phase (the rulebook's text does not) |
| `Units/The New Project unit sheet v3.xlsx` | v3 | four tabs: Humans, XzzzX, Space Dragons, Technology -- costs, the three attack values, initiative, traits, scouting, count |
| `Player boards/green human base board v4 constructed.png` (and blue) | v4 | production caps, max supply, unit costs in materials and gold, the upgrades, "max 2 tech facilities" |
| `Map and territories/map3.3.pdf` / `map3.3-1.png` | 3.3, **the map** (the author, 2026-11-05) | fifteen territories, two bases, the resource counts; `map2.1`/`map2.2` are older |
| `vassal module.png` (Vassal module folder) | -- | the Vassal module's Blue board: the **conversion rates**, the Factory's and Airport's build costs, "max 2 tech facilities", the deployment board's attack spaces A, B and C; the Cyborg Soldier's air rating, Weak, which the author chose over the sheet's Fair (question 18) |
| `Cards and tokens/` | -- | the tech tokens, tech cards and tactic deck art (not yet read) |

The files disagree in places, and those places are listed below. **The more
recent design wins** (the author, 2026-11-05): board v4 over rulebook
v3, and the Google Doc's 2026 changes (the 51% win, Emergency Base
Defense first) over both. A sentence the 2026 edit left alone is as old
as the .docx, so the edit date alone does not make it newer -- the tech
facility cap is two, as the board says. Every 2018 file was uploaded
the same day, so where the dates cannot order them, the author is
asked.

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
  is revealed until both are done. Infrastructure and Deployment are
  done at the same time, in one phase (the author, 2026-11-05):
  Infrastructure (spend the pool on
  units, buildings and upgrades, all of which complete at Production),
  Deployment (units go face down into the attack spots A and B -- C with
  *Command and Control CPU* -- each with a territory card, and into
  defense spots), March (A for both, then B, then C; within a slot, in
  ascending territory number: neutral conquest, battle, control and
  stranded, harvest), Production and Trade (one phase), Cleanup.
- **A battle** is up to six rounds. Each round: scouting advantage, the
  battle line (alternate placement, engaging and flanking), the
  declaration to retreat, damage in initiative order (the attacker rolls
  first within a group), and victory. A base under attack adds the
  emergency base defense, can't retreat, and puts two base cards at the
  ends of the line, where two hits destroy a facility.
- **The game ends** when an attack on a base succeeds, or when a seat
  has harvested 51% of the map's resources (question 17).
- **The Human faction**: thirteen units (Worker, Mercenary, Stealth
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

**The two sides mirror each other** under a half turn (the author,
2026-11-05: "12 is like 14"): 10 with 11, 14 with 12, 13 with 15, 8 with
9, 2 with 3, 5 with 4 and 7 with 6, every border matching. The minerals
are swapped between partners: 14 holds blue and 12 orange, 13 orange
and 15 blue, so each base has one of each beside it.

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
     gateway connection. Step 7 measures the requests per battle round
     against the five-in-five channel bucket, as D12 Ball's gate does.
   - **Crashes.** An exception in the TNP cog has to stay in the TNP
     cog. A view's errors go through its `SafeView`, and the cog's
     startup sweep catches and logs a bad saved game rather than raising
     out of `cog_load`, so a broken TNP save cannot stop fool-bot from
     loading D12 Ball. Step 5 tests the second point: a corrupt
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
   "The dice modifiers, for the d12" below. A modifier adds to the
   number rolled (the author, 2026-11-05): a Fair unit at +2 that rolls
   a 4 has a 6, and hits. The 12 and the 1 are the die's face, so a
   rolled 12 hits and a rolled 1 misses whatever the modifiers. The
   d12 value of each modifier is the author's (the table below). Two
   rules of rulebook v3's d6 text, where a unit hits on its attack value
   or less and a 6 always misses, were settled after an explanation (the
   author, 2026-11-05):
   - **The cap goes.** The d6 text held a value lifted by tech cards at
     5 and took the column penalty off after. On the d12 every modifier
     simply adds to the roll, and only the rolled 1 limits it: a Strong
     unit (3+) with Explosives (+6 vs base) attacking the base at −1
     hits on anything but a 1.
   - **Attack rate 0 stays: it is the older name of "Can't"** (the
     author). The rating is called **Poor**, and the board shows it as
     **X** where the others show 3+, 6+ and 12 (the author, 2026-11-05,
     on the canvas: "instead of can't call it poor", "show X"). The
     sheet and board v4 spell it Can't; the importer reads Can't, Poor
     or X as Poor. A Poor force still attacks, rolling **one die for
     each two units** and needing a 12, as Weak does -- the d12's
     counterpart of the d6's 1s -- so a modifier adds to its roll like
     any other. Many Human units are Poor against something (the Jeep,
     the Tank and Smart Mines against air, the Rocket Launcher against
     infantry, the Chopper Carrier against infantry and armour), so the
     rule is in the basic game. The d6 text's "an attack rate of X can
     never attack that type" is not built: no rating can never attack.
     The dice are **rounded down** (the author, 2026-11-05): a lone
     Poor unit rolls none, and three roll one.
3. ~~**Production.**~~ Answered (the author, 2026-11-05):
   **Production and Trade are one phase**, after March and before
   Cleanup. The turn is Infrastructure and Deployment (one phase, done
   at the same time -- the rulebook's casual mode, the author's choice
   on 2026-11-05), March, Production and Trade, Cleanup; what is placed in Infrastructure is finished in
   that turn's Production and Trade and deployable the next turn.
   **Cleanup clears every attack and defense spot** (the author,
   2026-11-05): each seat deploys its defenders again every turn, and
   only stranded units stay where they are. A battle's winner leaves
   its survivors in the territory's defense spot for the rest of that
   March, so a later attack there fights them, and Cleanup then clears
   them too.
4. ~~**Emergency base defense before or after Tactical Command?**~~
   Before: the newest rulebook (the Google Doc) has it in the body's
   order, Form Forces, Emergency Base Defense, Tactical Command.
5. ~~**Tech facilities: two or three?**~~ Answered (the author,
   2026-11-05): **two**, as board v4 and the Vassal module say. The
   rulebook's three is older text: the Google Doc's 2026 edit left that
   sentence as the 2018 .docx has it.
6. ~~**The basic game.**~~ Answered (the author, 2026-11-05, correcting
   an earlier answer the same day): **the basic game draws no cards**. A
   harvest takes the mineral and gem tokens themselves into the seat's
   pool, and they trade for materials or gold at the conversion rates.
   The advanced game is the one with the three tech decks, where a
   harvest draws a card instead, and **the card is the mineral**: it
   trades at the same conversion rates or is used for its ability (the
   author, 2026-11-05). Humans against Humans is built as the
   basic game first, and the tech cards are the last step.
7. ~~**Trade rates.**~~ Answered from the Vassal module (the author,
   2026-11-05, pointing there): a mineral trades for 2 materials or 1
   gold, a gem for 3 materials or 2 gold; in emergency production a
   mineral gives 1 material (no gold) and a gem 1 material or 1 gold. In
   the basic game these are the tokens harvested; in the advanced game,
   the cards drawn. A mineral or gem trades for materials or gold,
   either but not both, and blue and orange minerals trade alike (the
   author, 2026-11-05).
8. ~~**Gold.**~~ Answered (the author, 2026-11-05): the sheet's
   "Gems" column is **gold**, the board's coin; it comes only from
   trading minerals and gems, and the pool starts at 5 materials and 0
   gold.
9. ~~**What building costs.**~~ Answered: the Factory costs 2
   materials, and the Airport 3 and needs a Factory (the Vassal module);
   each unit upgrade -- Stealth, Cyborg, Robotic facility, Fighter
   Bomber, Laser Cannon -- costs 1 material (the author, 2026-11-05,
   confirming the one material icon on each Vassal upgrade box). The
   Barracks (the author, 2026-11-05): its upgrade
   "enables a second upgrade", so a Barracks without it builds Stealth
   or Cyborg, not both.
10. ~~**Movement.**~~ Answered (the author, 2026-11-05): air units
    may attack any territory, with no path of controlled territories, but
    cannot take one. If air units alone win against an enemy-held
    territory, it becomes **neutral**. **Corrected** (the author,
    2026-11-05, replacing the earlier "neutral in both cases" for the
    second case): a seat that defends a territory it already holds with
    air units alone, and wins, **still holds it**. Holding a territory
    means a ground unit once took it and its control token was placed;
    air units cannot take a territory, but they can defend one already
    held. Neither
    rulebook says more than that a neutral territory is taken by
    revealing a ground unit, that a chopper's stack "moves like air
    units", and that a carried unit "cannot retreat via an air route".
11. ~~**Spots.**~~ Answered (the author, 2026-11-05, "correct", after
    the question was asked again as three):
    - *How many attacks a turn?* Two, one from attack spot A and one
      from B; a third, C, only with *Command and Control CPU* (the
      advanced game).
    - *Where can units be left to defend?* In any territory the seat
      holds, and in its base.
    - *A territory held with nobody left in it:* still the seat's, until
      an enemy takes it.
12. ~~**What the opponent sees at deployment.**~~ Answered (the author,
    2026-11-05): **nothing**. Deployment is done behind a screen, and
    neither side sees anything until March, when the piles are resolved
    one at a time. On Discord, each seat deploys in its own private
    panel, and nothing of it is public until March reveals each pile as
    it resolves.
13. ~~**The battle line.**~~ Answered (the author, 2026-11-05): it is
    formed every round, but **only unengaged forces are placed**. In
    round 1 that is every force; in later rounds, only the forces whose
    opponent was destroyed or retreated, so fewer. On Discord a round
    asks for placement only when a seat has an unengaged force.
14. ~~**The map.**~~ Answered (the author, 2026-11-05): 8 with 10 and 9
    with 11 are adjacent, the two sides mirror each other, and map 3.3 is
    the map.
15. ~~**The dice.**~~ Answered (the author, 2026-11-05): yes, the
    target choice rolls the dice in the same click (decision 8), and
    every roll is shown.
16. ~~**Undo.**~~ Answered (the author, 2026-11-05): yes, changing the
    plan before locking in is enough to start with; a real undo comes
    later (decision 10).
17. ~~**Winning.**~~ Answered (the author, 2026-11-05), as read: a seat
    wins by harvesting 51% of the planet's resources -- map 3.3 holds 96
    tokens (40 blue minerals, 40 orange, 16 gems), so 49 tokens taken off
    the map, whatever the card drawn in the advanced game -- or by a
    successful attack on a base. An attack on an undefended base wins at
    once, and a defender who survives six rounds holds, whatever hits
    the base cards took.
18. ~~**The Cyborg Soldier against air.**~~ Answered (the author,
    2026-11-05): **Weak**, as the Vassal module says; the unit sheet and
    board v4 say Fair. The data is imported from the sheet, so the
    sheet's cell is to be corrected to Weak before step 1's import,
    rather than the value patched in code.

## The dice modifiers, for the d12

The tech cards are the advanced game's (question 6); the rules' own
modifiers at the end apply in both. Every card and rule that changes a
roll, as unit sheet v3 and rulebook
v3 word them, so the author can set each one's d12 value (the author,
2026-11-05). They were all written for a d6. On a d12 each step of +1
is worth half as much (one face in twelve rather than one in six), so
the straight translation is to double each number. The last column is
that translation, a starting point. The author set the values in the
last column (the author, 2026-11-05), and those are what is built; the
rules' own modifiers keep their d6 numbers.

The three ratings have moved too:

| Rating | d6 (keyword table) | d12 (the author) |
| --- | --- | --- |
| Poor, shown X (Can't on the sheet) | 1 only, one die per two units | 12 only, one die per two units |
| Weak | 6 only: 1 in 6, 17% | 12 only: 1 in 12, 8% |
| Fair | 4 to 6: 3 in 6, 50% | 6 to 12: 7 in 12, 58% |
| Strong | 2 to 6: 5 in 6, 83% | 3 to 12: 10 in 12, 83% |

So Strong stays the same, Fair gets a little better, and Weak gets half
as likely to hit.

**Tech cards that add to a roll** (Technology tab; count, type and cost
as the sheet has them):

| Card | Deck | Type | Count | Text | d6 | Doubled | The author's d12 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Arm Workers | orange minerals | tactic | 2 | Workers get +1 attack | +1 | +2 | **+3** |
| Enhancing Drugs | orange minerals | tactic | 2 | Mercenaries get −1 initiative, +2 for all rolls; each hit kills 2 mercenaries | +2 | +4 | **+4** |
| Advanced Targeting | orange minerals | tactic | 2 | Cyborgs gain +2 air | +2 vs air | +4 vs air | **+3 vs air** |
| Positioning | orange minerals | tactic | (blank) | Jeeps and Tanks gain +1 when attacking forces they are engaged with (no penalty for adjacent columns, −1 for 2 away etc.) | +1, and the column penalty eased by one | +2, and eased by 2 | **+3, and eased by 1** |
| Air Cover | orange minerals | tactic | (blank) | Choppers and Vipers gain +3 vs. air | +3 vs air | +6 vs air | **+6 vs air** |
| Heat Seeking Missile | orange minerals | tactic | 2 | Viper gains +2 attack | +2 | +4 | **+3** |
| Explosives | gems | tech facility, 1 material | 3 | Stealth Snipers gain +4 vs. base defense or when targeting base (short text: "inf. gain +4 vs. base") | +4 vs base | +8 vs base | **+6 vs base** |
| AA Missiles | gems | building tech | 3 | Attached units gain +2 vs. air | +2 vs air | +4 vs air | **+3 vs air** |
| Lasers | gems | building tech | 3 | Attached units gain +2 vs. Arm. | +2 vs armored | +4 vs armored | **+3 vs armored** |
| Grenades | gems | building tech | 3 | Attached units gain +2 vs. inf. | +2 vs infantry | +4 vs infantry | **+3 vs infantry** |
| Specialized Training | gems | building tech | 3 | Attached unit get +1 for all rolls | +1 | +2 | **+2** |

**Tech cards that give rerolls** (no number to change, but each is
worth more on a d12, where a miss is more often a near miss):

| Card | Deck | Type | Count | Text | The author's d12 |
| --- | --- | --- | --- | --- | --- |
| Ammo Depos | orange minerals | tech facility, 1 material | 2 | Gain 2 rerolls each battle | **no change** |
| Extra Large Ammo Depos | orange minerals | tech facility, 3 materials | 2 | Gain 4 rerolls each battle | **no change** |

**The rules' own modifiers** (rulebook v3, "Battle procedure"):

| Modifier | Rulebook text | d6 | Doubled | The author's d12 |
| --- | --- | --- | --- | --- |
| Flanking | "placing their Forces ... behind existing forces as flanking (gain +1 bonus)" | +1 | +2 | **+1** |
| Position | "minus one per column you are skipping" | −1 a column | −2 a column | **−1 a column** |
| The base cards | "always with at least −1 position modifier" | −1 at least | −2 at least | **−1 at least** |
| The cap | "if your attack value is higher than 5 ... your value is still 5 before position modifiers" | 5 | goes, if the 12 and the 1 bound the roll (question 2) | **goes** |
| Attack rate 0 (Poor) | "may roll 1 die for each two units and score a hit on 1s" | 1s, half the dice | -- | **12 only, half the dice** (question 2) |

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
thing the author looks at before the next step is worth starting. Each
step's prompt is below, after the preamble every prompt begins with.

| # | Step | Size | Stop |
| --- | --- | --- | --- |
| ~~1~~ | ~~The rules, the data and the bot standing up -- landed; what it settled is in docs/design/tnp.md~~ | medium | `docs/tnp-rules.md` read and approved by the author; `/tnp unit tank` answers in the test server |
| ~~2~~ | ~~The battle, with no frontend -- landed; what it settled is in docs/design/tnp.md~~ | large | a test fights any two Human forces to a result with the seeded `engine.rng` and a d12, covering scouting, flanking, the position modifiers, tough, repair, splash, retreat and the base cards |
| ~~3~~ | ~~The map and the player board, drawn by code -- landed; what it settled is in docs/design/tnp.md~~ | medium | the author compares the drawn map and boards to map 3.3 and board v4, with the d12 hit values, and approves them |
| ~~4~~ | ~~A whole basic game through the driver -- landed; what it settled is in docs/design/tnp.md~~ | large | a test plays Blue against Green from setup to a win -- a fallen base, or 51% harvested -- through `driver.apply` with nothing from `cogs/` or `discord` imported, harvesting tokens and trading them |
| ~~5~~ | ~~The lobby, the channel and the opening position -- landed; what it settled is in docs/design/tnp.md~~ | medium | two people reach turn 1 on Discord, one of them from a **TNP** button on the hub, each with a player board the other cannot see |
| ~~6~~ | ~~The simultaneous turn on Discord -- landed; what it settled is in docs/design/tnp.md~~ | large | two people play Infrastructure to Cleanup, with neutral conquests, a harvest and a trade; a restart mid-phase keeps both plans |
| 7 | Battles on Discord | large | two people fight a battle on Discord round by round, and the request count per round is measured and within the gate |
| 8 | Finishing a game | small | a game is won, ends, offers a rematch and is archived; a seeded whole basic game is pinned byte for byte as the golden |
| 9 | The advanced game: the technology cards | large | the advanced game chosen in the lobby; harvests draw from the three decks, and tactic cards, building techs and tech facilities all play on Discord; every Human tech row does what it says, with the author's d12 values; `/tnp card grenades` answers |
| -- | Later, and not now | -- | XzzzX and Space Dragons; an AI; undo; a web page like the Codex site |

### Claiming a step

The series does not exist yet: **step 1's prompt adds it** -- one entry
in `SERIES` in `scripts/claim_web_step.py`
(`"tnp": ("docs/tnp-bot.md", "tnp-step", "TNP step")`), plus the
`--series` help string and the module docstring, which list the series
by hand. From then on `python3 scripts/claim_web_step.py --series tnp
<n>` claims a step as the other series are claimed. A step lands by
striking its row above (`| ~~n~~ | ~~title~~ -- landed; what it settled
is in docs/design/tnp.md | ... |`). No cloud routine runs this series;
a person starts each step.

## Preamble

Every step's prompt begins with this block. A session given a step reads
it first, then the step's own prompt below.

```text
You are working in the fool-bot repository on The New Project (TNP),
planned in docs/tnp-bot.md: the author's simultaneous-turn strategy
game, built as a cog in fool-bot -- the /tnp group, under fool-bot's
token, with no process, token or deploy script of its own -- Humans
against Humans, both seats people, no AI, the basic game first and the
technology cards last. Read that worksheet first: "The game, in the
terms the code will use", the map table, the ten decisions and every
answered question are the scope. Then docs/tnp-rules.md and
docs/design/tnp.md once step 1 has written them, then
docs/design/model-discord-split.md, docs/design/game-service.md and
docs/design/codex.md, the nearest precedent (a model package of its
own, its service, its views, its hidden information). Read the rest of
docs/design/ only where a step names a file.

Start on the branch the claim script made (git fetch && git checkout
tnp-step-<n>), in a worktree of your own if another session may be
using the checkout. Never work on main.

Hard rules for every step:
- tnp/ and gamesaves/tnp/ import no discord, define no async def, and
  import Pillow only in tnp/render.py. The purity ratchet enforces it
  from step 2; do not loosen it.
- docs/tnp-rules.md is the rules. A mechanic is checked against it and
  its test cites the section. A question it does not answer goes to the
  author in the PR's "## Questions to the author", never into the code
  as a guess. A rules change is the rules doc plus a dated line in its
  change log, in its own commit.
- Where the sources disagree, the more recent design wins (the author,
  2026-11-05), and docs/tnp-bot.md records every disagreement already
  settled. Do not reopen one.
- A rule is a question the model answers and the cog asks. Nothing in
  cogs/tnp* decides a rule or computes a candidate list, a cost, a
  legal target or a hit number; a view builds its controls from
  PendingPrompt.options and nothing else, and the driver refuses what
  the options do not offer with RuleRefusal, never a bare ValueError.
- Units, facilities, upgrades and techs are keyed by slug, never by
  name. tnp/data/humans.json and tnp/data/technology.json come from
  scripts/import_tnp_data.py and are never edited by hand: a wrong value
  is corrected in the sheet and imported again. tnp/data/human_board.json
  and tnp/data/map.json are the hand-kept exceptions, each checked by a
  test against the imported data.
- The dice: a d12 a unit. Weak hits on 12, Fair on 6+, Strong on 3+;
  Poor, shown X (the sheet's Can't, the old attack rate 0), rolls one
  die for every two units, rounded down, and needs a 12. A modifier
  adds to the number rolled, with no cap; a rolled 12 always hits and
  a rolled 1 always misses. A modifier's d12 value is the author's column of "The
  dice modifiers, for the d12". Every draw is engine.rng; a test seeds
  it.
- Hidden information: a seat's queue, deployment, hand and plan are
  that seat's alone until the phase reveals them. Nothing hidden goes
  into a public message, a log line or the #logs mirror; say in the PR
  where you checked.
- The save format is the contract from the first commit: every
  MatchState field is in its SavedField table, and a saved key is never
  renamed.
- The cog lives inside fool-bot (decision 2), so an exception in it
  stays in it: its startup sweep logs a game it cannot load and goes on,
  and nothing in cogs/tnp* may stop cogs.d12ball from loading.
- Rate limits: the fix is always fewer requests, never slower ones.
  Read docs/design/rate-limits.md before adding any send, edit or pin;
  a game's public messages are edited through BoardRefresher's gate,
  and a cascade of the bot's own steps is one edit.
- Nothing under d12ball/, gamesaves/d12ball/, cogs/d12ball*, codex/,
  gamesaves/codex/ or cogs/codex* changes unless the step names the
  file and says why. A leaf both games need is moved into gamekit/ or
  botkit/, not copied, and the old module keeps re-exporting its name.
- Nothing rendered is tested for how it looks: render it
  (scripts/render_tnp_sample.py once step 3 adds it), look, and put the
  picture in the PR.
- tests/ is flat: every TNP test helper is named tnp_<thing>.py, and
  every TNP module that binds save_games is listed in
  tests/save_patches.py's tables.
- Run python3 -m unittest discover -s tests before the PR; a full run
  must not create data/. The PR is against the template and carries a
  "## Questions to the author" section ("None." when empty) and a
  "## For the author" section in two parts: what to do on the live host
  after merging (a deploy, a command sync, any Discord-side setup, or
  "Nothing to do on the live host"), and what can be tried in the test
  server now, command by command, with what should happen. It strikes
  this step's row in docs/tnp-bot.md. When the step settles something
  the worksheet only proposed, write it into docs/design/tnp.md with the
  reasoning, and add a row to CLAUDE.md's tables only for a new module
  or a new hard rule.
```

### 1. The rules, the data and the bot standing up

Everything the later steps stand on that is not the game: the rules as
one document, the data, the cog in fool-bot and the design note.

```text
Step 1 of docs/tnp-bot.md. Nothing has landed before it. Also read
docs/design/rules-and-data.md (the import-script rule TNP's data
inherits), docs/design/cog-structure.md and docs/design/rate-limits.md
("setup_hook's sync").

Five commits, in this order.

1. The claim series. scripts/claim_web_step.py gains
   "tnp": ("docs/tnp-bot.md", "tnp-step", "TNP step") in SERIES, and
   the --series help string and the module docstring list it. Claim
   this step with it (python3 scripts/claim_web_step.py --series tnp 1)
   and continue on tnp-step-1.

2. The rules. docs/tnp-rules.md: the newest rulebook, the Google Doc
   "Rulebook - The New Project 3" (Drive id
   1AyI95xh3zGv1luNFApS1w4hiQVhR4C_U2aYWNNCvL3k, read through the Google
   Drive connector), transcribed, with the glossary (Rules/Glossary.docx)
   and the player aide's turn order folded in, and every answer under
   docs/tnp-bot.md's "Questions for the author" written into the section
   it changes: the d12, its ratings and the author's modifier values,
   no cap, Poor (shown X) as the old attack rate 0; Production and
   Trade one phase; deployment hidden until March; only unengaged forces placed
   in a later round's battle line; air units unable to take a
   territory but able to defend one already held; the spots; two tech facilities; the conversion rates; gold
   and the starting pool; the build and upgrade costs; the Barracks
   upgrade; the two ways to win. Number the sections so code and tests
   can cite them ("TNP 5.3"). A change log at its foot: one dated line
   per answer, with where it came from. Leave the XzzzX and Space
   Dragons rules out, and mark the advanced game's sections as step 9's.
   A question the transcription turns up that the answers do not settle
   is listed in the PR, not chosen.

3. The data. scripts/import_tnp_data.py <file>: the unit sheet "The New
   Project unit sheet v3.xlsx" (Drive id 1NhVe5RxaHVzrfSv6GXtKk8wS1eS14JqG;
   the .xlsx exported through the Google Drive connector, or the JSON
   the connector saves, as scripts/import_from_workbook.py reads one).
   Its Humans tab (Building, Type, Name, Materials, Gems -- which is
   gold -- inf, arm, air, Initiative, Ability, picture, Count, trait1,
   trait2, scouting, trait3) goes into tnp/data/humans.json, and its
   Technology tab (Count, Title, Type, Materials, ability, iconn,
   colorr, Short Ability) into tnp/data/technology.json, each whole,
   keyed by slug, with a header saying it is regenerated and never
   edited by hand. The ratings are Strong, Fair, Weak and Poor, the
   sheet writing Poor as Can't (Can't, Poor and X are all read as
   Poor); any other value is
   refused; a tech row with no Count (Positioning, Air Cover and
   Shields today) is reported and left out. Before running it, look at
   the sheet's Cyborg Soldier vs air cell: the author chose Weak
   (question 18). If it still says Fair, say so in the PR and ask the
   author to correct the sheet; do not patch the value.
   tnp/data/human_board.json, kept by hand from board v4 and the Vassal
   module as docs/tnp-bot.md records them: the four facilities and
   which start built, their production caps before and after the
   infrastructure upgrade, the build costs (Factory 2 materials; Airport
   3 and needs a Factory), each unit upgrade's 1 material, the Barracks
   upgrade enabling a second unit upgrade, max supply, the conversion
   rates (a mineral 2 materials or 1 gold, a gem 3 materials or 2 gold;
   in emergency production a mineral 1 material and a gem 1 material
   or 1 gold), the starting pool (5 materials, 0 gold) and the limits
   (two tech facilities; 8 Smart Mines and Rocket Launchers deployed
   together).
   tnp/data/map.json: the seventeen areas with docs/tnp-bot.md's
   adjacency and resources, and each area's outline as a polygon. The
   outlines are traced from map3.3-1.png (Drive id
   1gbEjaRHk7H5VRVW2ME6P5EqfmQTMuWio) by a script under scripts/ that
   flood-fills each area and traces it, as the worksheet's table was
   measured; check its adjacency against the table.
   tnp/catalog.py reads all four: Unit, Facility, Upgrade and Tech
   dataclasses, a catalog by slug with name(slug) the one way back to a
   name, and the map's areas and adjacency.
   tests/test_tnp_data.py: every unit a facility builds is in
   humans.json and every Human unit has a facility; the adjacency is
   symmetric and maps onto itself under the half turn the worksheet
   gives (10 with 11, 14 with 12, 13 with 15, 8 with 9, 2 with 3, 5 with
   4, 7 with 6); the resources total 96 tokens (40 blue minerals, 40
   orange, 16 gems); each base touches one blue and one orange
   territory; every rating is one of the four.

4. The cog. cogs/tnp/ assembles Tnp(commands.GroupCog,
   group_name="tnp", group_description=...) -- the description passed
   explicitly and under 100 characters, or the sync fails inside
   setup_hook -- from one mixin, reference.py: /tnp unit <name>, with
   autocomplete over the catalog, answering with the unit's cost, its
   three ratings with their d12 numbers, initiative, traits, supply and
   the facility and upgrade that build it; and /tnp rules <section>
   over docs/tnp-rules.md. Plain text, no embed. foolbot.py loads
   cogs.tnp beside the others, and cog_load logs, never raises, when
   the data is missing. This changes fool-bot's command tree: the PR
   says the live host needs a command sync.

5. The design note and the map. docs/design/tnp.md, started: what TNP
   is; why a cog and not a bot (decision 2, with the requests and the
   crashes); the data, where each file comes from and which are kept by
   hand; and the sources and which wins. CLAUDE.md gains rows for
   tnp/, cogs/tnp/, scripts/import_tnp_data.py and the outline tracer,
   and a "Read this before touching" row for docs/design/tnp.md.

The stop: the author reads docs/tnp-rules.md and approves it, and
/tnp unit tank answers in the test server.
```

### 2. The battle, with no frontend

The riskiest rules in the game, and self-contained, so they come before
the turn. Each choice inside a battle is a prompt kind, so the battle
runs through the same driver as the rest of the game.

```text
Step 2 of docs/tnp-bot.md. Step 1 has landed: docs/tnp-rules.md, the
data, the catalog and the cog. Read the rules' battle sections closely;
every rule this step builds cites its section.

The model's shape begins here, copied from Codex's: tnp/prompts.py
(PromptKind, PendingPrompt with its options, Action, pending),
tnp/flow/result.py and tnp/flow/driver.py (apply, the one door), over
gamekit's SavedField, jsonable, MOVED_ON, STEP_OWED and Resolver as
they are. tnp/engine.py holds rng. tnp/battle.py holds the battle as a
saved state of its own (BattleState, with its SavedField table), so a
battle survives a restart mid-round.

What it covers, each with a test citing its section:
- Forces formed from the revealed units, one unit type a force.
- The scouting advantage, and the order of placement it decides (the
  author, 2026-11-05): with an advantage of N, the side without it
  places N forces before the advantaged side places one, and the sides
  then alternate one at a time (confirmed, the author, 2026-11-05);
  with no advantage, the defender places first.
- The battle line: a force engaging one column,
  flanking beside or behind the line at +1. Each round only unengaged
  forces are placed -- in round 1 every force, later only those whose
  opponent was destroyed or retreated (the author, 2026-11-05); a round
  with nothing to place asks nothing.
- The retreat declaration: the attacker first, and only if it does
  not retreat is the defender asked (the author, 2026-11-05). A base's
  defender
  cannot retreat, would-be stranded units cannot retreat, a retreat is
  a defeat, and the retreating seat does not attack that round.
- Damage by initiative group, lowest first; within a group the attacker
  rolls first, then the defender, and the group's losses come off only
  when the whole group has rolled, so a unit destroyed by its own group
  still shoots, and one destroyed by an earlier group does not (the
  author, 2026-11-05). A force's target is its controller's
  choice, and choosing it rolls that force's dice in the same action
  (decision 8). The number rolled is the die plus every modifier --
  flanking +1, the position modifier −1 a column skipped, the base
  cards' −1 at least, and modifiers handed in from outside, which step 9
  supplies from the cards -- against the rating's number for the
  target's type: Strong 3, Fair 6, Weak 12, Poor 12 with one die for
  every two units. No cap; a rolled 12 hits and a rolled 1 misses.
- Hits remove units; Tough takes two; Repair, Splash and every other
  trait the glossary gives a battle. "Adjacent" means a force in a
  neighbouring column or a force flanking it (the author,
  2026-11-05): Repair takes a Worker from a force adjacent to the hit
  Mechanical unit's -- no Human unit is both Mechanical and Repair --
  and Splash removes an infantry unit from an adjacent force.
- A base under attack: the emergency base defense, before Tactical
  Command; one base card at each end of the line (the author,
  2026-11-05), attacked with the armoured rating, since a building is
  armoured (the author, 2026-11-05); a force with 2 or more hits on
  the base destroys one thing, the attacker's choice (the author,
  2026-11-05): one upgrade of a facility, or, once a facility has no
  upgrades left -- an upgrade must be destroyed before its facility -- the Factory or
  the Airport itself -- the Barracks and Base Defenses cannot be
  destroyed (the author, 2026-11-05) -- and one thing an attack; an attack on an undefended base wins at once;
  a defender who survives six rounds holds, whatever the base cards
  took. Base Defense units (Smart Mines, Rocket Launchers, the Laser
  Cannon) never go into an attack spot, but roll like any other unit
  when their base is attacked (the author, 2026-11-05).
- Air units cannot take a territory: one won by air units alone is
  neutral. They can defend one already held: a defender with only air
  units left that wins keeps the territory (the author, 2026-11-05).
- The end: six rounds, a retreat, or one side with no force left.

Each choice is a prompt kind -- PLACE_FORCE, DECLARE_RETREAT,
CHOOSE_TARGET -- whose options carry every legal choice, and the driver
refuses anything else. tests/tnp_battles.py stages a battle by unit
slug and count; tests/test_tnp_battle.py fights any two Human forces to
a result through driver.apply with engine.rng seeded;
tests/test_tnp_purity.py starts the ratchet over tnp/.

Poor's dice are rounded down (the author, 2026-11-05): a lone Poor
unit rolls none, and three roll one.

The stop: the test fights any two Human forces to a result with the
seeded engine.rng and a d12, covering scouting, flanking, the position
modifiers, tough, repair, splash, retreat and the base cards.
```

### 3. The map and the player board, drawn by code

```text
Step 3 of docs/tnp-bot.md. Steps 1 and 2 have landed. Read
docs/design/board-image.md first: "Look at the image", and the fonts.

tnp/render.py, the one TNP module that imports Pillow, and
scripts/render_tnp_sample.py:
- The map, from map.json's outlines: each area tinted by its
  controller, its number, the resource tokens left on it, the stranded
  markers, the two bases in their seats' colours, and, during March,
  each pile as it is revealed. Nothing of a seat's deployment is drawn
  before March reveals it (question 12).
- A seat's player board, from human_board.json and humans.json: the
  four facilities, their caps, what is built and what is queued, the
  upgrades, each unit's cost, its ratings as d12 numbers (Strong 3+,
  Fair 6+, Weak 12, Poor shown as X), initiative,
  traits and supply left, the limits and the conversion rates. The
  layout the author has seen is the canvas's Human base board
  (https://claude.ai/artifact/4hRVXBPhYeKDHyoUSwnank).
- The battle: the line as columns, each force's unit, count and damage,
  the flanking forces beside it, the round track and the base cards.
Fonts are bundled and loaded by absolute path (d12ball/fonts/ may be
read by absolute path, never copied). Every render goes through
asyncio.to_thread in the cog. The sample script renders the opening
position, a mid-game map, both seats' boards and a battle in round 3
into a folder you name. The tests check only each PNG's size.

The stop: the author compares the drawn map and boards to map 3.3 and
board v4, with the d12 hit values, and approves them. Put every picture
in the PR.
```

### 4. A whole basic game through the driver

```text
Step 4 of docs/tnp-bot.md. Steps 1 to 3 have landed. Also read
docs/design/codex.md's "Multiplayer" (pending_all and SeveralAsked, two
prompts open at once) and its standing tech choice (standing_prompts,
an answer held secret until a reveal): the two precedents for a
simultaneous phase.

The model of the whole basic game:
- tnp/components.py: MatchState -- the turn and the phase; the map's
  state (each area's controller or none, resources left, defenders,
  the stranded flags); each seat's faction (humans alone for now, a
  field from the first commit), facilities built and upgraded, pool of
  materials, gold, minerals and gems, units by state (available,
  queued, deployed, defending, stranded), its plan for the phase and
  whether it is locked in; the battle in progress -- every class with a
  SavedField table.
- tnp/game.py: TnpGame, the record: two seats, Blue and Green, taken by
  people; the lobby's rules as methods refusing with RuleRefusal; the
  advanced game a setting from the start, though only the basic game
  plays until step 9.
- tnp/prompts.py: pending returns the prompts open now -- both seats'
  in a simultaneous phase, one seat's in a battle line -- or the step
  the bot owes. A seat may change its plan until it locks in; the phase
  resolves once both have. The plan is held on the match, so a restart
  keeps it.
- tnp/flow/: Infrastructure and Deployment, one phase a seat answers
  at once, with one Lock in (the author, 2026-11-05) -- Infrastructure
  (spend the pool on units, facilities and upgrades, all finished at
  Production and Trade) and Deployment (units
  face down into attack spots A and B, each with a target territory --
  C only with Command and Control CPU, in the advanced game -- and into
  the defense of any territory the seat holds and of its base); March
  (A for both seats, then B, then C; within a slot in ascending
  territory number: neutral conquest by revealing a ground unit,
  battle through step 2's battle, control and stranded, harvest by
  Workers -- tokens off the map into the pool); Production and Trade,
  one phase (the queue built and deployable next turn; minerals and
  gems traded at the conversion rates, each for materials or for gold
  and never both, blue and orange alike; emergency production);
  Cleanup (every attack and defense spot cleared back to the seat's
  available units, except stranded units, which stay). Air units attack any territory with no path of held
  territories; an attack won by air units alone leaves the territory
  neutral, but air units defending a territory already held keep it.
  A territory held with nobody left in it stays held until an enemy
  takes it.
- The two ways to win: a successful attack on a base, or 49 of the
  map's 96 tokens harvested by one seat.
- gamesaves/tnp/service.py (GameService: apply_action through
  driver.apply, run, resume, GameResult) and gamesaves/tnp/storage.py
  (data/tnp_games.json through gamekit.storage, with its own two
  failure flags).

tests/test_tnp_driver_full_game.py plays Blue against Green from setup
to a win through driver.apply with nothing from cogs/ or discord
imported, harvesting tokens and trading them: once to a fallen base,
once to 51%. The purity ratchet extends to gamesaves/tnp/, and every
MatchState field is checked against its table as Codex's are.

The stop: that test passes, and docs/design/tnp.md says what a
simultaneous phase is and where a locked plan is kept.
```

### 5. The lobby, the channel and the opening position

```text
Step 5 of docs/tnp-bot.md. Steps 1 to 4 have landed. Also read
docs/design/permissions.md, docs/design/channels-and-archive.md and
docs/design/codex.md's "The lobby and the channel" and "Hidden
information on Discord".

/tnp create_game posts a lobby with two seats, Blue and Green, each
taken by a person -- there is no AI -- and Start once both are filled.
Start opens the game's channel the way the Codex cog opens its own, in a
TNP Games category apart from D12 Ball's and Codex's, named
tnp-<n>-<blue>-vs-<green>, and posts the public message: the map, the
turn and the phase, who has locked in, and a button that opens the
clicker's own panel, ephemeral, with their player board, their pool and
what they may do. cogs/tnp_views/ holds the views: a SafeView over
botkit's GameLockedView and cogs/game_auth.py's gates; no view saves.
The persistent views are re-armed at startup, and the startup sweep
logs and skips a game it cannot load.
tests/test_tnp_isolation.py: a corrupt data/tnp_games.json leaves
cogs.d12ball loaded and its commands answering (decision 2).

The hub (the author, 2026-11-05). Also read docs/design/hub-and-lobby.md.
The hub's games message gains a **TNP** button beside D12 Ball's and
Codex's. Unlike Codex's, it opens a lobby itself, since TNP runs in
fool-bot's own application. A click does what D12 Ball's button does:
a private lobby channel for the clicker in the TNP Games category,
with /tnp create_game's lobby posted in it, and that channel becomes
the game's channel at Start. This step names the D12 Ball files it
changes and why:
- cogs/d12ball_views/lobby.py: NewGameHubView gains the button,
  custom_id "d12ball:hub:tnp", which names no game and no guild, like
  the other two. Its callback finds the TNP cog by name on the bot and
  calls its open_lobby. The view imports nothing from cogs/tnp*, so a
  TNP that failed to load leaves the hub working: the click is answered
  privately with "TNP isn't available right now" and logged at ERROR.
- cogs/d12ball_helpers.py: build_hub_message gains a TNP block under
  Codex's. Draft its description from the rulebook's Overview, and put
  it in the PR's questions for the author to approve or rewrite, as the
  D12 Ball block is the author's own copy.
- docs/design/hub-and-lobby.md: the third button and why it opens a
  lobby where Codex's cannot.
The hub's existing message shows the new button only once it is edited,
so the PR's "For the author" says to run /d12ball setup_hub again in the
hub channel on the live host after the deploy. A test clicks the new
button with cogs.tnp loaded and with it missing.

The stop: two people reach turn 1 on Discord, one of them having
started from the hub's TNP button, each with a player board the other
cannot see.
```

### 6. The simultaneous turn on Discord

```text
Step 6 of docs/tnp-bot.md. Steps 1 to 5 have landed. Read
docs/design/rate-limits.md whole before adding a send or an edit.

Each phase's panel per seat, built from PendingPrompt.options:
Infrastructure and Deployment on one panel, done at the same time --
the queue (what to build, its cost against the pool, the facility
caps) and the stacks (units into attack spots A and B,
a target territory each, and into the defenses), Production and
Trade's trades, and Lock in, the plan editable until then. The public
message shows who has locked in and nothing of either plan. When both
have locked in, March reveals: one message per slot, A then B, each
pile's resolution as its lines, the map redrawn once per slot through
the gate, every conquest and harvest named. A battle met in March stops
the march with a line saying battles arrive in step 7; the test game
avoids one. A restart mid-phase reads the plans saved on the match and
puts both panels back. Count the requests a whole turn makes with a
fake like tests/codex_cog_fakes.py, and give the number in the PR.

The stop: two people play Infrastructure to Cleanup, with neutral
conquests, a harvest and a trade; a restart mid-phase keeps both plans.
```

### 7. Battles on Discord

```text
Step 7 of docs/tnp-bot.md. Steps 1 to 6 have landed. Read
docs/design/rate-limits.md again: a battle is the longest run of clicks
in the game.

A battle gets its own message, with step 3's battle picture, edited in
place round by round through the gate. Placement in the battle line,
the retreat declaration and the target choices go to whichever seat is
asked, from the prompt's options; the retreat declaration asks the
attacker, and then the defender only if the attacker stayed. Choosing a target rolls that
force's dice in the same click, and every roll is shown: the dice, the
number each needed and why (the rating and each modifier). A round with
nothing to place asks nothing. When the battle ends, March goes on from
where it stopped. The requests per round are counted with a fake like
tests/codex_cog_fakes.py and kept within the five-in-five channel
bucket; give the numbers in the PR.

The stop: two people fight a battle on Discord round by round, and the
request count per round is measured and within the gate.
```

### 8. Finishing a game

```text
Step 8 of docs/tnp-bot.md. Steps 1 to 7 have landed. Also read
docs/design/codex.md's "The end of a game" and "The golden".

A win -- a fallen base or 49 tokens harvested -- announced once, the
public message showing the final map; /tnp concede, behind a second
click; /tnp abandon, a player's own game or any for a helper; Rematch;
and the channel moved to a TNP Archive category. The golden:
tests/test_tnp_golden.py plays a seeded whole basic game through
GameService and pins what the model says byte for byte under
tests/golden/tnp_service_*, re-recorded with FOOLBOT_UPDATE_GOLDEN=1
only for a change to the model's wording or the game, which the PR
says.

The stop: a game is won, ends, offers a rematch and is archived; a
seeded whole basic game is pinned byte for byte as the golden.
```

### 9. The advanced game: the technology cards

```text
Step 9 of docs/tnp-bot.md. Steps 1 to 8 have landed. Read the rules'
advanced sections, every Technology row in tnp/data/technology.json,
and "The dice modifiers, for the d12" in docs/tnp-bot.md, whose last
column is the author's value for each card.

The advanced game as a lobby setting. The three decks (blue minerals,
orange minerals, gems; the Technology tab's colorr column) are shuffled
at setup from engine.rng, and a harvest draws a card from the matching
deck instead of taking the token. The card is the mineral: it trades at
the conversion rates or is played for its ability (question 6), and the
51% count is still tokens taken off the map. Then the cards' effects:
Tactical Command (tactic cards face down, both seats at once, revealed
together, after the emergency base defense); building techs and their
slot, one per production facility; tech facilities and their cap of
two; Command and Control CPU's attack spot C; and every Human tech
row's effect as data, the way codex/effects.py holds Codex's, each
modifier at the author's d12 value and handed into step 2's battle as
the outside modifier it was built to take. A row whose Count the sheet
leaves blank (Positioning, Air Cover, Shields) is asked about in the
PR, never given a count here. The panels of steps 6 and 7 grow a hand,
the building techs, the tech facilities and the tactic card, all
private until revealed; /tnp card <name> joins the reference commands.
A test per card pins what it does.

The stop: the advanced game is chosen in the lobby; harvests draw from
the three decks, and tactic cards, building techs and tech facilities
all play on Discord; every Human tech row does what it says, with the
author's d12 values; /tnp card grenades answers.
```

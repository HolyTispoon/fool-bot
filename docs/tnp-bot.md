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
decide what the model holds. The author answers them in the doc **TNP
Open Questions and Dice** (https://claude.ai/artifact/CwXvSPjLSaNaYyVtDkx1TY),
which also holds the dice modifiers' d12 values, and on the canvas
drawing of the map and the board
(https://claude.ai/artifact/4hRVXBPhYeKDHyoUSwnank); each answer is
recorded here as it comes.

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
  is revealed until both are done: Infrastructure (spend the pool on
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
   "The dice modifiers, for the d12" below. A modifier adds to the
   number rolled (the author, 2026-11-05): a Fair unit at +2 that rolls
   a 4 has a 6, and hits. The 12 and the 1 are the die's face, so a
   rolled 12 hits and a rolled 1 misses whatever the modifiers. The
   d12 value of each modifier is the author's (the table below). **Still
   open**, asked again with an explanation (the author asked for one,
   2026-11-05): two rules of rulebook v3's d6 text. On the d6 a unit
   hits on its attack value or less, and a 6 always misses.
   - *The cap*: "if your attack value is higher than 5 (through
     technological modifiers), your value is still 5 before position
     modifiers". Tech cards can lift a value no higher than 5, and the
     column penalty is taken off after: a unit whose bonuses would make
     its value 7, shooting two columns over, hits on 3 or less. On the d12,
     where modifiers add to the roll, the same rule would read: **the
     tech cards' bonuses can bring the number needed down to 2 at best,
     and the column penalty is applied after that.** Without it, a big
     bonus swallows the penalty: a Strong unit (3+) with Explosives (+6
     vs base) attacking the base at −1 hits on anything but a 1; with
     it, the +6 brings the 3+ to 2+, the −1 makes it 3+, and it hits on
     10 in 12.
   - *Attack rate 0*: "a Force with an attack rate of 0 may roll 1 die
     for each two units and score a hit on 1s" -- a rating below Weak.
     No Human unit has a 0 (each rating is Strong, Fair, Weak or X,
     can't), so in Humans against Humans the rule never applies. The
     reading: leave it out until a faction with a 0 is built.
3. ~~**Production.**~~ Answered (the author, 2026-11-05):
   **Production and Trade are one phase**, after March and before
   Cleanup. The turn is Infrastructure, Deployment, March, Production
   and Trade, Cleanup; what is placed in Infrastructure is finished in
   that turn's Production and Trade and deployable the next turn.
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
    cannot hold one. If air units alone win against an enemy-held
    territory, it becomes **neutral**; and a held territory whose
    defenders are air units alone is neutral too ("neutral in both
    cases"). The reading built on: air units fight in a defence, but a
    territory left with only air units on it is nobody's. Neither
    rulebook says more than that a neutral territory is taken by
    revealing a ground unit, that a chopper's stack "moves like air
    units", and that a carried unit "cannot retreat via an air route".
11. **Spots.** The author found the question unclear (2026-11-05); it
    is asked again as three, each with the reading built on if the
    author agrees:
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
| The cap | "if your attack value is higher than 5 ... your value is still 5 before position modifiers" | 5 | goes, if the 12 and the 1 bound the roll (question 2) | open (question 2) |
| Attack rate 0 | "may roll 1 die for each two units and score a hit on 1s" | -- | goes (question 2) | open (question 2) |

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
| 1 | The rules, the data and the bot standing up | medium | `docs/tnp-rules.md` read and approved by the author; `/tnp unit tank` answers in the test server |
| 2 | The battle, with no frontend | large | a test fights any two Human forces to a result with the seeded `engine.rng` and a d12, covering scouting, flanking, the position modifiers, tough, repair, splash, retreat and the base cards |
| 3 | The map and the player board, drawn by code | medium | the author compares the drawn map and boards to map 3.3 and board v4, with the d12 hit values, and approves them |
| 4 | A whole basic game through the driver | large | a test plays Blue against Green from setup to a win -- a fallen base, or 51% harvested -- through `driver.apply` with nothing from `cogs/` or `discord` imported, harvesting tokens and trading them |
| 5 | The lobby, the channel and the opening position | medium | two people reach turn 1 on Discord, each with a player board the other cannot see |
| 6 | The simultaneous turn on Discord | large | two people play Infrastructure to Cleanup, with neutral conquests, a harvest and a trade; a restart mid-phase keeps both plans |
| 7 | Battles on Discord | large | two people fight a battle on Discord round by round, and the request count per round is measured and within the gate |
| 8 | Finishing a game | small | a game is won, ends, offers a rematch and is archived; a seeded whole basic game is pinned byte for byte as the golden |
| 9 | The advanced game: the technology cards | large | the advanced game chosen in the lobby; harvests draw from the three decks, and tactic cards, building techs and tech facilities all play on Discord; every Human tech row does what it says, with the author's d12 values; `/tnp card grenades` answers |
| -- | Later, and not now | -- | XzzzX and Space Dragons; an AI; undo; a web page like the Codex site |

### 1. The rules, the data and the bot standing up

Transcribe the rulebook into `docs/tnp-rules.md` with the answers folded
in, and start `docs/design/tnp.md`. Write `scripts/import_tnp_data.py`
(the Humans and Technology tabs into `tnp/data/`), plus the hand-kept
`human_board.json` and `map.json`, each checked by a test against the
other (every unit a facility builds exists, every adjacency goes both
ways, every resource is on a territory). Add the `cogs/tnp/` cog to
fool-bot's extensions in `foolbot.py` with `/tnp unit` and
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

### 4. A whole basic game through the driver

`tnp/components.py` (`MatchState`, the seats, the map's state, each
seat's pool of materials, gold, minerals and gems, the saved-field table
from the first commit), `tnp/game.py` (the record and the lobby's rules,
with the advanced game a setting from the start though only the basic
one plays until step 9), `tnp/engine.py`, `tnp/prompts.py` (both seats
asked at once), `tnp/flow/` (infrastructure, deployment, march,
conquest, control and stranded, harvest -- tokens off the map into the
pool -- production, trade at the conversion rates, cleanup, and the two
ways to win) and the driver, with `GameService` in `gamesaves/tnp/`. The
deliverable is the test that plays a game to a win with no frontend
imported, plus the purity ratchet.

### 5. The lobby, the channel and the opening position

`/tnp create_game`, two seats taken by people, the channel opened the
way Codex opens its own (in a **TNP Games** category, apart from D12
Ball's), the setup, and the opening position: the public map message,
and each seat's player board in its own panel. The persistent views are
re-armed at startup, and a test shows that a corrupt TNP games file
leaves D12 Ball's cog loaded (decision 2).

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

A win -- a fallen base or 51% harvested -- concede, abandon, rematch,
the channel archived, and the golden: a seeded whole basic game through
`GameService` recorded byte for byte.

### 9. The advanced game: the technology cards

The advanced game as a lobby setting: the three decks shuffled at
setup, and a harvest drawing a card from the matching deck rather than
taking the token: the card is the mineral, traded at the conversion
rates or played for its ability (question 6). Then the cards' effects: Tactical Command
(face down, both at once, revealed together), building techs and their
slots, tech facilities and their cap (question 5), and every Human tech
row's effect as data in the way `codex/effects.py` holds Codex's, with
the d12 values the author sets from "The dice modifiers, for the d12".
The panels of steps 6 and 7 grow a hand, the building techs, the tech
facilities and the tactic card; `/tnp card` joins the reference
commands.

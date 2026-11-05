# The New Project: the rules

**This is the rules of *The New Project* (TNP) as the bot plays them.**
It is the newest rulebook -- the Google Doc *Rulebook - The New Project
3* in the Drive folder **The New Project**, edited 2026-10-25 --
transcribed, with the glossary (`Rules/Glossary.docx`) and the player
aide's turn order (`Rules/player aide 3-5.pdf`) folded in, and every
answer the author gave to the questions in
[docs/tnp-bot.md](tnp-bot.md) written into the section it changes.
Each change is dated in the log at the foot. Where the sources
disagree, the more recent design wins (the author, 2026-11-05); the
worksheet records each disagreement and how it was settled.

The code is checked against this document, and a test cites the
section it holds the code to ("TNP 6.7"). A question this document does
not answer goes to the author; it is never settled in the code by a
guess.

Two things are left out for now: the XzzzX and Space Dragons factions,
whose rules and traits come in with them, and **the advanced game**,
whose sections are marked *step 9's* -- they are transcribed so the
whole game is in one place, but nothing before step 9 builds them.

## 1. The game

### 1.1 The story

> Space travel turned out to be a lot less exciting than science
> fiction has promised -- in the entire known universe, no life forms
> were found and the vast majority of planets turned out to be dreary
> and deserted places. Nonetheless, many of these sad pieces of stone
> have minerals that are dear in the context of Earth's decaying
> environmental state, and some of them even have rare precious gems
> that can power advanced technologies. That ginormous void, spotted
> with desolate treasure troves, attracted competing guilds of space
> navigation that travel the galaxies, harvest planets clean of their
> resources and trade them around in the gravity-free market.
> Typically, they find no one on the planets they go to, but every now
> and then they stumble upon each other on a forsaken planet, and even
> more rarely they stumble upon something worse...
>
> You are a junior captain in one such navigation guild. You've been
> tasked with gathering the resources on one of these empty planets.
> The file you received is named THE NEW PROJECT, and there isn't much
> information on the planet you're going to. You are to harvest at
> least 51% of the planet's resources (the rest you're supposed to use
> for your operation) or you cannot come home. Alas, as you arrive you
> discover that you're not the only one to make this planet your
> project.

### 1.2 Overview

In *The New Project* players run competing harvesting operations on a
single planet with finite resources. They spend the resources they
gather, their tactics and their skills on building their base,
producing military units and running their harvesting operation. TNP is
mostly a tactical combat game: you produce units and deploy them around
the map, outsmarting your opponent. Much of the action takes place
behind a screen -- you produce units in secret, deploy them face down,
and reveal them only when the attack is launched. To win you have to
outsmart your opponent, and bluff them.

**Everything is simultaneous.** Both seats play each phase at the same
time, and nothing either does in secret is revealed until the phase
says so.

The bot plays two seats, **Blue** and **Green**, both the Human
faction, both played by people (the author, 2026-11-04). The seat's
faction is still part of the game, so the other factions can be added.

### 1.3 Winning

A seat wins in either of two ways (the author, 2026-11-05):

- **A successful attack on the opponent's base** (6.10). An attack on
  an undefended base succeeds at once.
- **Harvesting 51% of the planet's resources.** Map 3.3 holds 96
  resource tokens (2.1), so a seat that has taken 49 tokens off the map
  by harvesting (5.8) wins. Every token counts the same, a blue
  mineral, an orange mineral or a gem, and a token counts once it is
  taken off the map, whatever the seat does with it afterwards. **The
  count is checked at Cleanup** (5.10), not as the token is harvested
  (the author, 2026-11-05). Two seats cannot both have 49 of 96.

## 2. The components

### 2.1 The map

The map is **map 3.3** (the author, 2026-11-05): fifteen territories,
numbered 1 to 15, and the two bases, **Blue's base** on the left and
**Green's base** on the right, which are areas of the map but not
territories. Two areas are **adjacent** where their borders meet. 8 and
10 meet at a single point, as do 9 and 11, and both pairs are adjacent
(the author, 2026-11-05); 3 and 12 do not meet.

| Area | Adjacent to | Resource tokens |
| --- | --- | --- |
| Blue's base | 10, 13, 14 | -- |
| Green's base | 11, 12, 15 | -- |
| 1 | 2, 3, 4, 5, 6, 7 | -- |
| 2 | 1, 5, 7, 8, 10 | -- |
| 3 | 1, 4, 6, 9, 11 | -- |
| 4 | 1, 3, 7, 9 | 10 blue minerals, 10 orange minerals |
| 5 | 1, 2, 6, 8 | 10 orange minerals, 10 blue minerals |
| 6 | 1, 3, 5 | 8 gems |
| 7 | 1, 2, 4 | 8 gems |
| 8 | 2, 5, 10, 13, 14 | -- |
| 9 | 3, 4, 11, 12, 15 | -- |
| 10 | Blue's base, 2, 8, 14 | -- |
| 11 | Green's base, 3, 9, 12 | -- |
| 12 | Green's base, 9, 11, 15 | 10 orange minerals |
| 13 | Blue's base, 8, 14 | 10 orange minerals |
| 14 | Blue's base, 8, 10, 13 | 10 blue minerals |
| 15 | Green's base, 9, 12 | 10 blue minerals |

That is 96 tokens: 40 blue minerals, 40 orange minerals and 16 gems.
The two halves of the map mirror each other under a half turn: 10 with
11, 14 with 12, 13 with 15, 8 with 9, 2 with 3, 5 with 4 and 7 with 6.
The minerals are swapped between partners, so each base has one
territory of blue minerals and one of orange beside it.

Each territory is **neutral** or **held** by a seat. A seat holds a
territory once one of its ground units has taken it and its control
token is on it (5.5, 6.11), and goes on holding it with nobody left in
it, until an enemy takes it (the author, 2026-11-05).

### 2.2 Resources and the pool

- **Minerals** come in two colours, **blue** and **orange**, and
  **gems** are the third resource. They are the tokens on the map, and
  a seat gets them only by harvesting (5.8). In the basic game the
  token itself goes into the seat's pool (the author, 2026-11-05).
- **Materials** and **gold** are what a seat spends. They come only
  from trading minerals and gems (5.9) -- the unit sheet's "Gems"
  column is gold, the board's coin (the author, 2026-11-05).
- A seat's **available resource pool** holds its materials, gold,
  minerals and gems. What is in it before Infrastructure is **open
  information**: the board keeps it outside the seat's screen.

### 2.3 Units

A unit is **infantry**, **armored** or **air**. Each has:

- **Three ratings**, its attack against infantry, armored and air: each
  **Strong**, **Fair**, **Weak** or **Poor** (4.1). The unit sheet and
  board v4 spell Poor *Can't*; the board shows it as **X** (the author,
  2026-11-05).
- An **initiative**: which group it shoots in, lowest first (6.7).
- Its **traits** (7) -- Scouting with a number, Tough, Mechanical,
  Repair, Harvest, Splash, Transport, Transformation, Base Defense.
- A **cost** in materials, and for some units gold, paid at the
  facility that builds it (2.4).
- Its **supply**: the most units of that kind a seat may have at once
  -- the board's "total number of units available of each kind".

The units, their costs, ratings, initiative, traits and supply are the
unit sheet's (`The New Project unit sheet v3.xlsx`, the Humans tab),
imported into `tnp/data/humans.json` and shown by `/tnp unit`; this
document does not keep a second copy of them. The Human faction has
thirteen units: Worker, Mercenary, Stealth Sniper and Cyborg Soldier
(infantry, the Barracks); Jeep, Tank and The Transformer (armored, the
Factory); Chopper Carrier, Viper Spy Plane and Fighter Bomber (air, the
Airport); and Smart Mines, Rocket Launcher and Laser Cannon (armored,
Base Defenses).

**The Cyborg Soldier's rating against air is Weak** (the author,
2026-11-05, as the Vassal module has it). Board v4 says Fair; the unit
sheet said Fair too, and was corrected on 2026-11-05.

### 2.4 The player board

Each seat's player board is its base: the four **production
facilities**, each with the units it builds, their costs, the
facility's **production cap** -- the most units it can produce each
Production and Trade phase -- and its upgrades. Board v4 and the
Vassal module give them; `tnp/data/human_board.json` keeps them.

| Facility | At the start | To build it | Production cap | Infrastructure upgrade | Unit upgrades |
| --- | --- | --- | --- | --- | --- |
| Barracks | built | -- | 4 | cap 8, and a second unit upgrade | Stealth (Stealth Sniper), Cyborg (Cyborg Soldier) |
| Factory | not built | 2 materials | 3 | cap 6 | Robotic facility (The Transformer) |
| Airport | not built | 3 materials, and a Factory | 2 | cap 4 | Fighter Bomber |
| Base Defenses | built | -- | 4 | cap 8 | Laser Cannon |

- **An infrastructure upgrade** costs 1 material (the unit sheet).
- **The Airport needs a Factory already built**: one finished in an
  earlier turn's Production and Trade. A seat cannot place both in the
  same Infrastructure (the author, 2026-11-05).
- **A destroyed facility** (6.9) can be built again, at its cost. An
  Airport goes on producing after its Factory is destroyed, and a
  Factory may be destroyed while an Airport stands (the author,
  2026-11-05); a new Airport still needs a Factory built.
- **A unit upgrade** costs 1 material (the author, 2026-11-05) and lets
  the facility build its upgraded unit.
- **The Barracks** builds one of its two upgraded units, Stealth or
  Cyborg, not both, until its infrastructure upgrade, which "enables a
  second upgrade" (the author, 2026-11-05).
- **At most 8 Smart Mines and Rocket Launchers may be deployed
  together** -- the board's "can only deploy 8 total unupgraded base
  defense units (Rocket + Mines)".
- *Step 9's:* at most **one building tech per production facility**,
  and at most **two tech facilities** at any time (the author,
  2026-11-05, as board v4 and the Vassal module say; the rulebook's
  three is older text).

### 2.5 Spots

Each seat deploys onto its own **deployment board**, behind its screen:

- **Attack spots A and B**: two attacks a turn, one from each. A third,
  **C**, only with the tech *Command and Control CPU* -- the advanced
  game (the author, 2026-11-05).
- **Defense spots**: one for any territory the seat holds, and its
  **base defense spot** (the author, 2026-11-05).

Each stack placed in a spot goes with the territory it attacks or
defends; the base has its own spot.

## 3. Setup

- The map, with each territory's resource tokens on it (2.1).
- Each seat takes its player board, its screen, its deployment board
  and its faction's units.
- Each seat starts with **3 Workers, 3 Mercenaries and 5 materials**,
  and no gold (the author, 2026-11-05). Its Barracks and Base Defenses
  are built; its Factory and Airport are not (2.4).
- Every territory starts neutral.
- *Step 9's:* the three technology decks -- blue minerals, orange
  minerals and gems -- shuffled (8.1).

## 4. The dice

### 4.1 A d12 a unit

Every die is a **d12** (the author, 2026-11-05). A force rolls one die
for each unit in it, and each die that reaches the number its rating
needs against the target's type is a hit:

| Rating | Shown | Hits on | The chance of a die |
| --- | --- | --- | --- |
| Strong | 3+ | 3 and above | 10 in 12 |
| Fair | 6+ | 6 and above | 7 in 12 |
| Weak | 12 | 12 | 1 in 12 |
| Poor | X | 12, with one die for every two units | 1 in 12 |

**A rolled 12 always hits and a rolled 1 always misses**, whatever the
modifiers.

### 4.2 Modifiers

A modifier **adds to the number rolled**, with no cap (the author,
2026-11-05): a Fair unit at +2 that rolls a 4 has a 6, and hits. The
d6 rulebook's cap of 5 is gone. Only the rolled 1 limits a roll, so a
Strong unit at +6 hits on anything but a 1.

The rules' own modifiers, in both games:

| Modifier | Section | d12 |
| --- | --- | --- |
| Flanking | 6.5 | +1 |
| Position | 6.7 | −1 a column |
| Attacking a base card | 6.9 | −1 at least |

The technology cards' modifiers are the advanced game's (8.5).

### 4.3 Poor

A Poor rating is the d6 rulebook's attack rate 0 under another name
(the author, 2026-11-05). A Poor force still attacks: it rolls **one
die for every two units, rounded down**, and needs a 12, like Weak. A
lone Poor unit rolls no die, and three roll one. A modifier adds to its
roll like any other. No rating means a force can never attack a type of
unit; the d6 text's "attack rate of X" is not built.

## 5. The turn

### 5.1 The phases

A turn has four phases, each played by both seats at once (the player
aide's turn order, with Production and Trade made one phase and
Infrastructure and Deployment done at the same time -- the author,
2026-11-05):

1. **Infrastructure and Deployment** (5.2, 5.3), done together, in
   secret. Each seat may change its plan until it locks in; the phase
   ends when both have.
2. **March** (5.4), attack spot A for both seats, then B, then C.
3. **Production and Trade** (5.9).
4. **Cleanup** (5.10).

The rulebook's competitive mode, in which Infrastructure has to be
finished before Deployment, is not built.

### 5.2 Infrastructure

A seat may spend resources from its available pool:

- **On units**: placed on the facility that builds them, at that unit's
  cost, up to the facility's production cap (2.4) and the unit's supply
  (2.3).
- **On a facility**: the Factory or the Airport, at its cost (2.4).
- **On an upgrade**: a facility's infrastructure upgrade, or a unit
  upgrade (2.4).

Nothing is built at once. Everything placed in Infrastructure is
finished in that turn's Production and Trade (5.9) and can be deployed
the next turn. A facility is used only once it has finished building in
an earlier turn: a seat cannot place units on a facility it is building
this turn.

*Step 9's:* a seat may also put building techs and tech facilities from
its hand into play (8.3, 8.4).

### 5.3 Deployment

A seat places units from its available units into its attack and
defense spots (2.5), and each stack with the territory it attacks or
defends:

- **Nobody sees anything** of the other seat's deployment until March,
  which reveals each pile as it resolves (the author, 2026-11-05).
- A **stranded** unit (5.7) cannot be deployed.
- **Base Defense units** (Smart Mines, Rocket Launchers, the Laser
  Cannon) go only into the base defense spot, never into an attack spot
  (7).
- **A ground unit attacks a territory only along a path**: there must
  be a path of held territories from the seat's base to the territory
  attacked -- that is, the target is adjacent to the seat's base, or to
  a territory the seat holds that its held territories join to its
  base. Attacks resolve A, then B, then C, so a seat may plan an attack
  on a territory it cannot reach yet, in the hope that it will hold the
  territories between by the time that attack resolves.
- **Air units attack any territory**, with no path (the author,
  2026-11-05).

### 5.4 March

In order, both seats resolve attack spot A, then both resolve B, then
both resolve C. Where two attacks resolve in the same spot, they go in
**ascending territory number**: 1 first, 2 second, and so on. Each
attack is resolved through four steps, 5.5 to 5.8, before the next
begins.

### 5.5 Neutral conquest

If the territory attacked is neutral and nobody else is fighting for
it, the attacker may reveal **one ground unit** (infantry or armored)
from the attacking pile to take it: the seat's control token goes on
it. **Air units cannot take a territory** (the author, 2026-11-05).

### 5.6 Battle

If the territory is held by the other seat, or the other seat attacks
it too, there is a battle (6). A harvest may still follow it.

### 5.7 Control and stranded

The winner of a battle places its control token on the territory,
except where the attacker won with air units alone (6.11). The
attacker's units that survive stay in the territory's defense spot for
the rest of March, so a later attack there fights them (the author,
2026-11-05).

If the territory taken leaves any territory a seat holds no longer
joined to that seat's base by its held territories, that seat's units
there are **stranded**: a Stranded token goes on the territory's
defense spot. If a seat takes a territory adjacent to one where its
units are stranded, that Stranded token is removed.

### 5.8 Harvest

If the territory has resource tokens left and the winning attacker has
**Workers** in the attacking pile, it harvests: **for each Worker, one
token is taken off the territory**. In the basic game the token goes
into the seat's pool (the author, 2026-11-05); *step 9's:* in the
advanced game the seat draws a card from that resource's deck instead
(8.1).

The only way to harvest a territory is to attack it from an attack
spot, even one the seat already holds. Workers defending a territory do
not harvest.

### 5.9 Production and Trade

One phase (the author, 2026-11-05), both seats at once:

- **Production.** Everything placed in Infrastructure is finished: the
  units join the seat's available units, ready to deploy next turn, and
  the facilities and upgrades are built.
- **Trade.** A seat may trade the minerals and gems in its pool for
  materials or gold at the board's conversion rates (the Vassal
  module, the author, 2026-11-05):

  | Token | Materials | or gold |
  | --- | --- | --- |
  | A mineral, blue or orange | 2 | 1 |
  | A gem | 3 | 2 |

  Each token trades for materials **or** for gold, never both, and
  blue and orange minerals trade alike (the author, 2026-11-05). What
  a seat gains goes into its available pool.

### 5.10 Cleanup

**Every attack and defense spot is cleared** (the author, 2026-11-05):
every unit in one goes back to its seat's available units, and each
seat deploys its defenders again every turn. Only **stranded** units
stay where they are.

Then each seat's harvested tokens are counted: a seat that has taken 49
or more off the map wins (1.3).

## 6. Battle

A battle is fought between the **attacker** and the **defender** over
one territory, or a base.

### 6.1 Forming forces

First, which seat is the attacker:

- If one seat holds the territory, the other seat is the attacker.
- If both seats attack a neutral territory, the seat with the scouting
  advantage (6.4) chooses whether to be the attacker or the defender.
  With no advantage, the seat with the lower total of initiative
  values over all its units there is the defender. If the totals are
  equal, each seat rolls a die and the higher roll counts as the higher
  initiative (the author, 2026-11-05): the seat that rolls higher is the
  attacker and the seat that rolls lower the defender. Equal rolls are
  rolled again (the author, 2026-11-05).

The attacker reveals every unit in its attacking pile, Workers
included, and forms them into **forces**: all its units of one kind are
one force. The defender reveals its units in the territory's defense
spot and forms its forces the same way. The attacker's units then go
into that territory's defense spot with it, so if the other seat
attacks the territory later in March it fights them.

A seat with no units in the battle has lost it: an attack on a held
territory with nobody defending it wins at once, and so does an attack
on an undefended base (1.3).

### 6.2 Emergency base defense

If the attack is on a base, the defending seat may spend what is in its
available pool, and trade minerals and gems at the **emergency rates**,
to produce base defenses:

| Token | Materials | or gold |
| --- | --- | --- |
| A mineral | 1 | -- |
| A gem | 1 | 1 |

- **The units join the battle at once**, in the base defense spot (the
  author, 2026-11-05).
- **At most the Base Defenses' production cap** -- 4, or 8 with its
  infrastructure upgrade -- a count of its own, apart from what the
  turn's Infrastructure queued at Base Defenses (the author,
  2026-11-05).
- **The supply limits apply** (2.3), and so does the limit of 8 Smart
  Mines and Rocket Launchers deployed together (2.4) (the author,
  2026-11-05).
- **A Laser Cannon** only once the Laser Cannon upgrade is built (the
  author, 2026-11-05).

This comes before Tactical Command (the newest rulebook's order).

### 6.3 Tactical Command

*Step 9's.* Each seat may play one tactic card from its hand, face
down; the cards are revealed together and last for this battle alone
(8.2). The basic game has no cards, and goes on to the rounds.

### 6.4 The round, and the scouting advantage

A battle is up to **six rounds**. Each round is 6.4 to 6.10 in order.

Each seat totals the scouting points of its units in the battle -- each
unit adds its Scouting number, so a force of three Viper Spy Planes
(Scouting 4) adds 12. The seat with the higher total has the **scouting
advantage**, as large as the difference. Equal totals give no
advantage.

### 6.5 The battle line and flanking

The battle line is two lines of forces facing each other. A force
placed opposite an opposing force forms a **column** with it, and both
are **engaged**.

- **Each round, only unengaged forces are placed** (the author,
  2026-11-05). In round 1 that is every force; later, only the forces
  whose opponent was destroyed or retreated. A round in which neither
  seat has an unengaged force places nothing.
- **Who places first.** With an advantage of N, the seat without it
  places N forces before the seat with it places one, and the seats
  then alternate one force at a time. With no advantage, the defender
  places first, and the seats alternate (the author, 2026-11-05).
- **The first placement.** The defender's first force starts the line,
  and the attacker must engage it, by placing a force of its own in
  front of it. Then the attacker must place another force next to an
  existing force.
- **An unengaged force must be engaged.** While the other seat has an
  unengaged force in the line, the force a seat places must engage one
  of them, in front of it (the author, 2026-11-05).
- **When one seat has no forces left to place**, the other places its
  forces at either end of the line, between any two columns, or
  **behind** a force of its own already in the line, as **flanking**:
  a flanking force gains **+1** on its rolls (4.2). A flanking force is
  adjacent to the force it stands behind, and to that force's
  neighbours (the author, 2026-11-05).
- A **Base Defense** unit cannot flank (7).

### 6.6 Declaring a retreat

The attacker may declare a retreat. Only if it does not is the
defender asked (the author, 2026-11-05).

- The defender of a **base** cannot retreat.
- **A force retreats only if it has a path home**: a path of
  territories its seat holds from the territory of the battle to its
  base, so that it would not be stranded (5.7). A force with no such
  path cannot retreat (the author, 2026-11-05: "so long as there's a
  path to the base, units can retreat"). This is the rulebook's
  "would-be stranded units cannot retreat". **An air force always
  retreats**, path or none (the author, 2026-11-05); ground units a
  Chopper Carrier carried still need the path (7).
- If either seat retreats, the battle ends after this round, and the
  retreating seat does not attack this round.
- **A retreat is a defeat.** A force always retreats to its seat's
  base.

### 6.7 Damage

Forces deal damage by **initiative group**: group 1 first, then 2, and
so on up. Within a group, the attacker rolls for all its forces in that
group first, then the defender. **The group's losses come off only when
the whole group has rolled**, so a unit destroyed by its own group
still shoots, and one destroyed by an earlier group does not (the
author, 2026-11-05).

To attack, a force's seat **chooses the opposing force it targets**,
and the force rolls its dice -- one a unit, or one for every two units
if its rating against that type is Poor (4.3). Choosing the target
rolls the dice at once (the author, 2026-11-05). Each die is the
number rolled plus every modifier (4.2), against the rating's number
for the target's type (4.1).

**The position modifier** is an engaged force's alone: attacking a
force in another column, it takes **−1 for each column** it reaches
across -- −1 for the next column, −2 for the one after -- and attacking
within its own column, none. **An unengaged force takes no position
modifier** -- an unengaged force is usually a flanking one (the author,
2026-11-05). The base cards are the exception: every force attacking
one takes at least −1 (6.9).

### 6.8 Hits

Each hit removes one unit from the force attacked, except:

- **Tough** (7): a Tough unit hit is damaged -- a damage token covers
  its icon -- and a damaged Tough unit hit is removed. It takes two
  hits. **A damaged Tough unit always takes a hit before an undamaged
  one** in its force (the author, 2026-11-05).
- **Repair** (7): when a Mechanical unit is hit, its seat may remove a
  Worker from a force adjacent to the hit unit's force to ignore the
  hit (the author, 2026-11-05).
- **Splash** (7): when a force with Splash damage hits, its seat may
  also remove one infantry unit, Tough or not, from a force adjacent to
  the one it hit (the author, 2026-11-05).

**Adjacent** means a force in a neighbouring column, or a force
flanking it (the author, 2026-11-05).

### 6.9 The base cards

When a seat defends its base, a **base card** stands at each end of
its line, one at either end (the author, 2026-11-05).

- A force may attack a base card instead of a force. A base card is a
  building, attacked with the force's **armored** rating (the author,
  2026-11-05). **No force can engage a base card, so every force
  attacking one is at least −1 for position** (4.2): an engaged force
  takes −1 for each column from its own to the base card's place beyond
  the end of the line, and an unengaged force -- alone in its column,
  or flanking -- takes −1. A flanking force still gains its +1 (6.5)
  (the author, 2026-11-05).
- **A force that scores 2 or more hits on a base card destroys one
  thing**, the attacker's choice (the author, 2026-11-05): one upgrade
  of one of the defender's facilities, or, once a facility has no
  upgrades left, the Factory or the Airport itself. An upgrade must be
  destroyed before its facility, and the **Barracks and Base Defenses
  cannot be destroyed**. *Step 9's:* the rulebook also lets it destroy
  a tech facility or a building tech.
- **One thing an attack.** However many forces hit the base cards, an
  attack on a base destroys at most one thing.
- **Base Defense units** roll like any other unit when their base is
  attacked (the author, 2026-11-05).

### 6.10 Victory

At the end of each round:

- If a seat retreated, the battle is over, and the other seat wins it.
- If a seat has no units left, it has lost, and the other seat wins.
- Otherwise, the round track moves up one and the next round begins,
  until the sixth round; **after six rounds, the defender wins if it
  still has units**, whatever the base cards have taken (the author,
  2026-11-05).

**An attack on a base succeeds** when the attacker wins the battle, and
that seat wins the game (1.3).

### 6.11 After the battle

- **The attacker wins**: it takes the territory -- its control token
  goes on it -- and its surviving units are placed in the territory's
  defense spot.
- **The defender wins**: it keeps the territory, and its surviving
  units go back to the territory's defense spot. If the attacker still
  has units, they retreat to their seat's base.
- **Air units cannot take a territory** (the author, 2026-11-05). If
  the attacker wins against a held territory with air units alone, the
  territory becomes neutral. **A defender that wins with only air units
  left keeps a territory it already held** (the author, 2026-11-05,
  correcting "neutral in both cases" the same day): air units cannot
  take a territory, but they can defend one already held.

## 7. Traits

The glossary's traits, as the Human units carry them. A unit's traits
are the icons on its card, which the unit sheet lists.

- **Base Defense**: must be placed in the base defense spot, never in an
  attack spot, and cannot flank. "Cannot attack" in the glossary means
  it never goes into an attack spot; it rolls like any other unit when
  its base is attacked (the author, 2026-11-05).
- **Mechanical**: can be repaired, and uses special techs.
- **Harvest**: gathers resources after an attack (5.8).
- **Repair**: when an adjacent Mechanical unit is hit, this unit may be
  removed to ignore the hit (6.8).
- **Scouting N**: adds N to its seat's scouting total (6.4).
- **Tough**: takes two hits to remove (6.8).
- **Splash damage**: when this force hits, an infantry unit may also be
  removed from an adjacent force, Tough or not (6.8).
- **Transformation**: *step 9's.* With the tech *Advanced Robotics*,
  The Transformer can become an air unit: after the tactic cards are
  revealed, its seat chooses whether its Transformers are armored or
  air for this battle. Without it, The Transformer is armored.
- **Transport**: Chopper Carriers carry ground troops, and the whole
  stack moves like air units. Regular capacity is any one of: 3
  Mercenaries or Workers, 2 Stealth Snipers or Cyborg Soldiers, 2
  Jeeps, or 1 Tank or Transformer, without mixing. *Step 9's:* with the
  tech *Improved Carrier Capacity*, 4 infantry, 3 Jeeps or 2 Tanks or
  Transformers. In the basic game too (the author, 2026-11-05):
  - a carried stack is deployed in one attack spot with its Chopper
    Carriers, and needs no path (5.3), as air units do;
  - its ground units fight as their own forces, and can take the
    territory (5.5, 6.11);
  - a unit carried cannot retreat by an air route: it retreats as any
    force does, only with a path home (6.6).

## 8. The advanced game

*All of section 8 is step 9's.* The advanced game is chosen in the
lobby; the basic game plays until step 9.

### 8.1 The technology decks

Three decks, shuffled at setup: **blue minerals**, the economy techs;
**orange minerals**, the military techs, which name Human units; and
**gems**, the advanced techs. A harvest draws one card from the deck of
the resource harvested for each Worker, in place of the token (5.8).
**The card is the mineral** (the author, 2026-11-05): it trades at the
conversion rates (5.9, 6.2) as the token would, or is used for its
ability. The Technology tab of the unit sheet holds every card,
imported into `tnp/data/technology.json`.

A card is one of three kinds:

### 8.2 Tactic cards

Played face down in Tactical Command (6.3), one a seat, revealed
together, lasting for that battle alone and discarded when it ends.
Most help one or two kinds of units; a tactic card whose units are not
in the battle is discarded without effect.

### 8.3 Building techs

Attached to a production facility, giving abilities to the units it
produces: the card slides under the player board. One building tech a
facility (2.4).

### 8.4 Tech facilities

Built in the base, giving abilities to all of a seat's units. Each
costs the materials printed on it, placed on the card behind the
seat's screen. At most two at any one time (2.4); to build another, a
seat may discard one it has.

### 8.5 The cards' modifiers

The cards that add to a roll, at the author's d12 values (2026-11-05):

| Card | Deck | Kind | d12 |
| --- | --- | --- | --- |
| Arm Workers | orange minerals | tactic | +3 |
| Enhancing Drugs | orange minerals | tactic | +4 |
| Advanced Targeting | orange minerals | tactic | +3 vs air |
| Positioning | orange minerals | tactic | +3, and the position modifier eased by 1 |
| Air Cover | orange minerals | tactic | +6 vs air |
| Heat Seeking Missile | orange minerals | tactic | +3 |
| Explosives | gems | tech facility | +6 vs base |
| AA Missiles | gems | building tech | +3 vs air |
| Lasers | gems | building tech | +3 vs armored |
| Grenades | gems | building tech | +3 vs infantry |
| Specialized Training | gems | building tech | +2 |

*Ammo Depos* (2 rerolls a battle) and *Extra Large Ammo Depos* (4) are
unchanged on the d12 (the author, 2026-11-05). Positioning, Air Cover
and Shields have no count on the unit sheet, so they are not in the
deck until the sheet gives one.

## Change log

One line per change, dated, with where it came from.

- 2026-11-05: Transcribed from the Google Doc *Rulebook - The New
  Project 3* (edited 2026-10-25), with `Rules/Glossary.docx` and the
  turn order of `Rules/player aide 3-5.pdf`; the XzzzX and Space
  Dragons rules left out. (TNP step 1.)
- 2026-11-04: Humans against Humans, both seats people, no AI -- 1.2.
  (The author, docs/tnp-bot.md decision 1.)
- 2026-11-05: Every die a d12; Strong 3+, Fair 6+, Weak 12; a rolled 12
  hits and a rolled 1 misses -- 4.1. (The author, question 2.)
- 2026-11-05: A modifier adds to the number rolled, with no cap; the d6
  cap of 5 dropped -- 4.2. (The author, question 2.)
- 2026-11-05: Attack rate 0 is the rating Poor, shown X, the sheet's
  Can't: one die for every two units, rounded down, needing a 12; no
  rating that can never attack -- 2.3, 4.1, 4.3. (The author, question
  2.)
- 2026-11-05: The rules' modifiers on the d12: flanking +1, position −1
  a column, the base cards −1 at least -- 4.2, 6.5, 6.7, 6.9. (The
  author, "The dice modifiers, for the d12".)
- 2026-11-05: Production and Trade one phase; Infrastructure and
  Deployment done at the same time; Cleanup clears every spot but the
  stranded -- 5.1, 5.9, 5.10. (The author, question 3.)
- 2026-11-05: Emergency Base Defense before Tactical Command -- 6.2,
  6.3. (The newest rulebook's order, question 4.)
- 2026-11-05: Two tech facilities, as board v4 and the Vassal module
  say -- 2.4, 8.4. (The author, question 5.)
- 2026-11-05: The basic game draws no cards: a harvest takes the token
  into the pool; in the advanced game the card drawn is the mineral --
  2.2, 5.8, 8.1. (The author, question 6.)
- 2026-11-05: The conversion rates, normal and emergency; a token for
  materials or gold, never both; blue and orange alike -- 5.9, 6.2.
  (The author from the Vassal module, question 7.)
- 2026-11-05: The unit sheet's Gems column is gold; gold only from
  trading; the pool starts at 5 materials and no gold -- 2.2, 3. (The
  author, question 8.)
- 2026-11-05: The Factory 2 materials, the Airport 3 and a Factory, a
  unit upgrade 1 material; the Barracks' upgrade enables a second unit
  upgrade -- 2.4. (The author from the Vassal module, question 9.)
- 2026-11-05: Air units attack any territory with no path and cannot
  take one; won by air alone, a held territory becomes neutral, but a
  defender left with only air units keeps one it held -- 5.3, 5.5,
  6.11. (The author, question 10, corrected the same day.)
- 2026-11-05: Attack spots A and B, C only with Command and Control
  CPU; defense in any held territory and the base; a territory held
  with nobody in it stays held -- 2.1, 2.5. (The author, question 11.)
- 2026-11-05: Nothing of a deployment is seen until March reveals each
  pile -- 5.3. (The author, question 12.)
- 2026-11-05: Each round only unengaged forces are placed -- 6.5. (The
  author, question 13.)
- 2026-11-05: Map 3.3 is the map; 8 with 10 and 9 with 11 adjacent;
  the two halves mirror each other -- 2.1. (The author, question 14.)
- 2026-11-05: Choosing a target rolls the dice at once -- 6.7. (The
  author, question 15 and decision 8.)
- 2026-11-05: The two ways to win: a successful attack on a base, or 49
  of the map's 96 tokens harvested; an undefended base falls at once;
  a defender who survives six rounds holds -- 1.3, 6.1, 6.10. (The
  author, question 17.)
- 2026-11-05: The Cyborg Soldier is Weak against air -- 2.3. (The
  author, question 18; the sheet still says Fair.)
- 2026-11-05: With an advantage of N the other seat places N forces
  first, then the seats alternate; with none, the defender first --
  6.5. (The author, docs/tnp-bot.md step 2.)
- 2026-11-05: A flanking force is adjacent too -- 6.5, 6.8. (The
  author, docs/tnp-bot.md step 2.)
- 2026-11-05: The attacker declares a retreat first, and the defender
  is asked only if it does not -- 6.6. (The author, docs/tnp-bot.md
  step 2.)
- 2026-11-05: An initiative group's losses come off once the whole
  group has rolled -- 6.7. (The author, docs/tnp-bot.md step 2.)
- 2026-11-05: Adjacent means a neighbouring column or a flanking force;
  Repair takes a Worker from an adjacent force; Splash an infantry unit
  from an adjacent force -- 6.8. (The author, docs/tnp-bot.md step 2.)
- 2026-11-05: One base card at each end of the line, attacked with the
  armored rating; 2 hits destroy one thing, the attacker's choice, an
  upgrade before its facility, never the Barracks or Base Defenses, one
  thing an attack; Base Defense units roll when their base is attacked
  -- 6.9, 7. (The author, docs/tnp-bot.md step 2.)
- 2026-11-05: Equal initiative totals over a neutral territory: each
  seat rolls a die, and the higher roll counts as the higher initiative
  -- 6.1. (The author, answering PR #704.)
- 2026-11-05: A force placed while the other seat has an unengaged
  force in the line must engage one -- 6.5. (The author, answering PR #704.)
- 2026-11-05: The position modifier is an engaged force's alone; an
  unengaged force, usually a flanking one, takes none -- 6.7. (The
  author, answering PR #704.)
- 2026-11-05: A damaged Tough unit always takes a hit before an
  undamaged one -- 6.8. (The author, answering PR #704.)
- 2026-11-05: The Airport needs a Factory already built, finished in an
  earlier turn -- 2.4. (The author, answering PR #704.)
- 2026-11-05: The 51% win is checked at Cleanup -- 1.3, 5.10. (The
  author, answering PR #704.)
- 2026-11-05: The higher roller of an initiative tie is the attacker;
  equal rolls are rolled again -- 6.1. (The author, answering PR #704.)
- 2026-11-05: Emergency base defenses join the battle at once, at most
  the Base Defenses' cap counted apart from the turn's production, the
  supply limits applying, a Laser Cannon only once its upgrade is built
  -- 6.2. (The author, answering PR #704.)
- 2026-11-05: Chopper Carriers carry in the basic game: a carried
  stack needs no path, its ground units fight and can take the
  territory, and retreat only with a path home -- 7. (The author,
  answering PR #704.)
- 2026-11-05: A force retreats only with a path of held territories to
  its base -- the rulebook's "would-be stranded" -- 6.6. (The author,
  answering PR #704.)
- 2026-11-05: A destroyed facility can be built again; an Airport goes
  on producing after its Factory is destroyed, and a Factory may be
  destroyed while an Airport stands -- 2.4. (The author, answering PR
  #704.)
- 2026-11-05: Every force attacking a base card is at least −1, an
  unengaged one exactly −1, and a flanking one still +1 -- 6.9. (The
  author, answering PR #704.)
- 2026-11-05: Emergency base defenses count toward the 8 Smart Mines
  and Rocket Launchers deployed together -- 6.2. (The author, answering
  PR #704.)
- 2026-11-05: An air force always retreats, with no path home -- 6.6.
  (The author, answering PR #704.)

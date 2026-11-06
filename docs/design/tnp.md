# The New Project

Design notes for fool-bot; the map is [CLAUDE.md](../../CLAUDE.md), the rules are [tnp-rules.md](../tnp-rules.md).

*The New Project* (TNP) is the author's simultaneous-turn strategy
game: two seats harvest a planet's minerals and gems, build a base,
deploy units face down into attacks and defenses, and fight battles of
up to six rounds over the territories of one map. It is being built
into fool-bot from [../tnp-bot.md](../tnp-bot.md), the worksheet whose
steps it is, starting with **Humans against Humans, both seats people,
no AI** (the author, 2026-11-04), the basic game first and the
technology cards last. This note is what those steps settled, one
section per decision as it lands.

Step 1 stood it up: the rules as one document, the data and its import,
the map's outlines traced from the map's own picture, the catalog over
them, and the `/tnp` group in fool-bot with `/tnp unit` and
`/tnp rules`. Step 2 built the battle, with no frontend, through the
model's own driver. Step 3 drew the map, the player board and the
battle by code.

## A cog in fool-bot, not a bot of its own

The author decided on 2026-11-04 that TNP is a cog in fool-bot: the
`/tnp` group, loaded by `foolbot.py` beside `cogs.d12ball`, under
fool-bot's token, with no process, token, deploy script or `.env`
variable of its own. That is the other way from Codex, which the author
put in its own process on 2026-10-07 so that one game's rate-limit
buckets and crashes would not land on the other's ([codex.md](codex.md),
"Its own process, its own token"). Two things follow, and the code is
held to both.

- **Requests.** Discord's limits are per channel and per interaction,
  and each TNP game will get its own channel, so a TNP battle does not
  slow a D12 Ball game's channel. What the two share is the
  application's global limit and the gateway connection. Step 7
  measures a battle round's requests against the five-in-five channel
  bucket ([rate-limits.md](rate-limits.md)).
- **Crashes.** An exception in the TNP cog stays in it. `Tnp.cog_load`
  reads the data and, when it cannot, logs at ERROR and goes on with no
  catalog -- it never raises, because an exception out of `cog_load`
  fails `load_extension`, which fails `setup_hook`, which stops fool-bot
  starting at all, D12 Ball with it. Every command then answers that
  TNP is unavailable. `cogs.tnp` is loaded after `cogs.d12ball`, and the
  cog's `cog_app_command_error` answers and logs a command's own error.
  Step 5 adds the test that a corrupt `data/tnp_games.json` leaves
  D12 Ball loaded.

A command-tree change is a sync: the live host needs one after the
deploy that adds or changes a `/tnp` command (`FOOLBOT_COMMAND_SYNC`,
[rate-limits.md](rate-limits.md), "setup_hook's sync").

## The split from the first commit

`tnp/` is the model, held to the model's rules from its first commit:
no `discord`, no `async def`, Pillow only in `tnp/render.py`.
Step 1's modules are already words and readings over data, so the
`/tnp unit` answer is the model's (`tnp.formatting.unit_lines`) and the
cog only posts it -- including the d12 numbers, which are
`catalog.Rating`'s, not a computation in the cog. The purity ratchet
over `tnp/` started in step 2 with the first rule:
`tests/test_tnp_purity.py` holds `tnp/` (and `gamesaves/tnp/` once it
exists) to no `discord`, no `async def`, Pillow only in
`tnp/render.py`, no import of a cog, and `random` imported only by
`tnp/engine.py`, so every draw is `engine.rng`.

## The rules

[docs/tnp-rules.md](../tnp-rules.md) is the rules, playing the part
`docs/living-rules.md` plays for D12 Ball. It is the newest rulebook,
the Google Doc *Rulebook - The New Project 3* (edited 2026-10-25),
transcribed, with the glossary and the player aide's turn order folded
in, and each of the author's answers written into the section it
changes, dated in the log at its foot. Its sections are numbered by
hand -- `## 6. Battle`, `### 6.7 Damage` -- so a test cites one as
"TNP 6.7"; there is no renumbering script, because there is no printed
edition whose numbers it would have to follow. A section that moves
keeps its number unless nothing cites it yet.

What is left out, and why: the XzzzX and Space Dragons rules and their
traits (Heal, Evolve, Carry, Strength in numbers, Fire breath), which
come in with those factions; and the competitive mode, in which
Infrastructure finishes before Deployment, which the author did not
choose. The advanced game's sections are transcribed and marked *step
9's*, so the whole game is in one place.

`/tnp rules` serves a section by number or title (`tnp/rules_doc.py`),
reading the file rather than a copy. Discord renders neither a markdown
table nor a link to a neighbouring file, and keeps every line break, so
a table goes out as a code block of padded columns, a local link as its
words, and the file's hard-wrapped lines are joined back into their
paragraphs. A section too long for one message is split at a paragraph.

## The data

Four files under `tnp/data/`, read by `tnp/catalog.py` into frozen
dataclasses keyed by slug. Two are imported, two are kept by hand, and
each hand-kept number that the sheet also carries is checked against
it by `tests/test_tnp_data.py`.

| File | Where it comes from | How it changes |
| --- | --- | --- |
| `humans.json` | the unit sheet's **Humans** tab (`The New Project unit sheet v3.xlsx`, Drive) | `scripts/import_tnp_data.py`; never by hand |
| `technology.json` | the unit sheet's **Technology** tab | `scripts/import_tnp_data.py`; never by hand |
| `human_board.json` | board v4 and the Vassal module, as the worksheet records them | by hand |
| `map.json` | the worksheet's map table; each outline traced from `map3.3-1.png` | adjacency and resources by hand; outlines by `scripts/trace_tnp_map.py` |

**The importer** reads the workbook the Drive connector exports -- the
`.xlsx`, or the JSON the connector saves -- as
`scripts/import_from_workbook.py` does for D12 Ball, because a cloud
session may not reach the sheet's export URLs. It reads each tab by its
headers and refuses what it would otherwise have to guess: a rating
other than Strong, Fair, Weak or Poor (the sheet's *Can't*, *Poor* and
*X* all read as Poor, TNP 4.3), and a unit type, Building, trait icon,
tech type or deck its tables do not know. A row it cannot use and need
not refuse -- the Humans tab's total of the Count column, the three
tech rows with no Count (Positioning, Air Cover, Shields) -- is
reported and left out. Names are kept as the sheet spells them; a
spelling is the sheet's to fix, which is how "Jewler", "Heat seeking
missle" and "Surpisingly valuable side-effects" became "Jeweler", "Heat
seeking missile" and "Surprisingly valuable side-effects" on
2026-11-05, and "Convertors" and "Hasted distillations" the author's
"Converters" and "Rapid Distillation", their slugs with them.

- **A unit's traits are its icons**, the sheet's trait1 to trait3, not
  its Ability text, because the icons are what the board and the
  Vassal module show and the text is incomplete: the Tank's says
  "Tough, mechanical" and its icons add Splash. The text is kept whole
  beside them.
- **The "Gems" column is gold** (the author, 2026-11-05), and the Count
  column is the unit's supply: board v4's "max supply" matches it unit
  for unit, which the test holds.
- **The Building column names the facility and the unit upgrade**, by a
  table in the importer: "Barracks Stealth Upgrade" is the Barracks and
  its Stealth Upgrade, "Airport Upgrade" is the Airport and its Fighter
  Bomber Upgrade. That last one is why the unit upgrades have slugs of
  their own (`fighter_bomber_upgrade`): the sheet also has an
  infrastructure row named "Airport upgrade", and slugs share one
  namespace.
- **The rows with a name and no Building are the infrastructure
  upgrades**, imported with their cost and text; `human_board.json`
  holds the caps as numbers, and the test checks the cap each row's text
  names is the board's.

**The sheet's Cyborg Soldier against air.** The author chose Weak,
as the Vassal module has it (question 18), but the sheet still said Fair
when step 1 first imported it (the workbook last modified 2018-10-19).
It was corrected in the sheet, not in code: at the author's word
(2026-11-05) the one cell, and the three names above, were changed in
the `.xlsx` itself -- its XML edited in place, so nothing else in the
workbook moved -- and the import run again. The connector cannot
replace a Drive file's content, so the author uploaded the corrected
workbook by hand, as a new file beside the old one; the old one went to
the trash, and the importer's `SOURCE` and the data's `source` name the
new file's Drive id, 1NhVe5RxaHVzrfSv6GXtKk8wS1eS14JqG. Its contents are
the corrected workbook's member for member, and importing it changes no
unit or card.
`tests/test_tnp_data.py` now holds Weak (TNP 2.3).

**The player board** (`human_board.json`) holds what exists nowhere in
the sheet: each facility's cap before and after its infrastructure
upgrade, whether it starts built, its build cost and what it needs, the
units it builds and its unit upgrades, how many unit upgrades it allows
(the Barracks one, two after its upgrade -- the author, 2026-11-05), and
whether a base attack may destroy it (never the Barracks or Base
Defenses -- the author, 2026-11-05); the unit upgrades at 1 material
each; max supply; the conversion rates, normal and emergency, an
emergency mineral's gold `null` because the Vassal board offers none;
the starting pool and units; and the limits (two tech facilities, one
building tech a facility, 8 Smart Mines and Rocket Launchers deployed
together); and each Chopper Carrier's capacity by the unit carried (`transport`, TNP 7, the author, 2026-11-06), checked against the units' traits.

**The map** (`map.json`) is the worksheet's table -- seventeen areas,
their adjacency and resources, confirmed by the author on 2026-11-05 --
and each area's outline as a polygon in `map3.3-1.png`'s pixels (2339 x
1654), for step 3 to draw. The outlines are traced, not drawn:
`scripts/trace_tnp_map.py` flood-fills each area from a seed point, the
map's lines (anything darker than 200) being the walls, fills the holes
its digits and icons leave, traces the outline and simplifies it to
within 1.5 pixels. It then grows each area by 9 pixels, a little more
than the thickest line, and calls two areas adjacent where the grown
shapes overlap. On map 3.3 every shared border overlaps by more than
2,000 pixels and the two point contacts, 8 with 10 and 9 with 11, by
392 and 716; 3 and 12 not at all -- the table to the pixel. The script
writes only the outlines and refuses to write when its adjacency
differs from the table, so a change to the map is a change to the table
first. The test holds the table symmetric, its own mirror under the
half turn the author gave, at 96 tokens, and each base beside one blue
and one orange territory.

**The catalog** reads the four into `Unit`, `Facility`, `Upgrade` (an
infrastructure upgrade or a unit upgrade, by `kind`), `Tech` and
`Area`, with `Catalog.name` the one way from a slug back to a name;
`load` refuses a slug used twice across the tables. `Rating` is the d12
(TNP 4.1): `target` is the number to reach, `shown` the board's
spelling (3+, 6+, 12, X), and `dice` the dice a force rolls -- for Poor
one for every two units, rounded down.

## The sources, and which one wins

Where the files disagree, **the more recent design wins** (the author,
2026-11-05): board v4 over rulebook v3, and the Google Doc's 2026 edit
(the 51% win, Emergency Base Defense before Tactical Command) over
both. A sentence the 2026 edit left alone is as old as the .docx, so
the edit date alone does not make it newer: the tech facility cap is
two, as the board says, not the rulebook's three. Every 2018 file was
uploaded the same day, so where the dates cannot order them the author
was asked. [../tnp-bot.md](../tnp-bot.md) lists every source and every
disagreement settled; none is reopened in the code.

## The battle

Step 2 built the battle (TNP 6) before the turn, because it holds the
riskiest rules and stands alone. It is the model's shape copied from
Codex's: `tnp/prompts.py` (`PromptKind`, `PendingPrompt` with its
options, `Action`, `pending`), `tnp/flow/result.py`,
`tnp/flow/driver.py` (`apply`, the one door), over `gamekit`'s
`SavedField`, `jsonable`, `MOVED_ON`, `STEP_OWED` and `Resolver` as
they are. `tnp/engine.py` holds the catalog and `rng`; `tnp/battle.py`
holds the state and every reading over it; `tnp/flow/battle.py` holds
the steps that change it.

**A battle is a saved state of its own.** `BattleState`, with its
`SavedField` table, is saved whole under `MatchState.battle` -- the
match's only field until step 4 adds the turn around it -- so a battle
survives a restart mid-round: `tests/test_tnp_battle.py` saves one
part-way through, loads it into a fresh engine with the same `rng`
state, and plays it to the same bytes.

**It is self-contained, by snapshot.** What a battle needs from the
rest of the game is handed to `begin_battle` as it opens and kept on
the state: each seat's path home (TNP 6.6), the defending base's built
facilities and upgrades (TNP 6.9), the defender's pool and supply room
for an emergency defense (TNP 6.2), and the outside modifiers step 9's
cards will supply (TNP 4.2, as rows of seat, unit, target type and
value). What it decides goes back the same way: `outcome` (the winner,
how, who controls the territory, whether a base fell, the survivors
with their damage, whose survivors go home), the structures after the
base card's hit, the pool after the emergency spend and the units it
produced. Nothing changes on a map or a board mid-battle that the
battle would need to read again, so a snapshot loses nothing, and the
March (step 4) is the one place the result lands. The alternative --
the battle reading and writing seat state step 4 has not designed yet --
would fix that design here without its context.

**Each choice is a prompt kind**, whose options carry every legal
answer, and the driver refuses anything else with `RuleRefusal`
(cited, "TNP 6.5"): `CHOOSE_ROLE` (both seats attacked a neutral
territory and one has the scouting advantage), `EMERGENCY_DEFENSE`,
`REPOSITION_FLANKERS`, `PLACE_FORCE`, `DECLARE_RETREAT`, `CHOOSE_TARGET` (which rolls the dice
at once, decision 8), `REPAIR`, `SPLASH` and `DESTROY`. A question with
no choice in it is not asked: an emergency defense the defender could
not pay for, a force with no die to roll at anything (a lone Poor unit,
TNP 4.3) and a target it would roll no die at, a base card's hit with
only one thing left to destroy. Every answer is one seat's -- a battle
asks one seat at a time -- so no battle action names a seat; step 4's
simultaneous phases are the first that will.

**The three joints are owed steps**: `BEGIN_ROUND` (the scouting
advantage, the unengaged forces lifted out, who places first),
`CLOSE_GROUP` (Repair asked, then the group's losses together) and
`END_ROUND` (TNP 6.10). They are where a frontend may want to redraw:
step 7 edits the battle message round by round, and names
`END_ROUND` as its batching boundary.

**The line** is a list of columns, each with at most one force a seat
in front and at most one flanking behind each front force (TNP 6.5,
the author, 2026-11-06). A force is `"<seat>:<unit>"`, since a seat's
units of one kind are one force; the base cards are the targets
`base_left` and `base_right`, standing just beyond the line's two
ends, so every force's position modifier against one is the columns
from its own to there -- at least −1, since no force can engage one
(TNP 6.9). A flanking force "is in the same column as the force it stands
behind", so adjacency is by column alone: two forces of one seat are
adjacent in the same column or neighbouring ones (TNP 6.5, 6.8).
Repair takes a Worker from a force adjacent to the hit one; Splash an
infantry unit from a force adjacent to the one hit, of the hit force's
seat, once a roll, a damaged unit first. **Every force takes −1 a
column** to whatever it attacks, a force or a base card
(`position_modifier`, the author, 2026-11-06: "any force can attack
forces in other columns with −1 penalty per column"), **and a flanker
adds +1** (`flank_modifier`): +1 at the opposing force in its own
column, none one column away, −1 two away, the same against a base card
-- one rule with a bonus on top, rather than a flanker's table of its
own.

**Placing is by turns** (TNP 6.5, the author, 2026-11-06). The
advantage's opening placements are a run (`run_left`); then a seat's
turn engages every unengaged enemy force it can, places one new force
for the other seat to engage, and ends -- `answer_place` passes the
turn on a new column while the other seat still has forces to place.
Once the other seat is all placed and engaged, the seat places the rest
of its own one after another, flanking where a force has no flanker
yet, or as new columns. `slots` is the one reading of where; the turn
is the placement's consequence, so it lives with the answer and leaves
`slots` as it was. At a round's start every unengaged force in front
is lifted to be placed again, and a flanking force behind it goes with
it; a flanker behind an engaged pair stays where it stands unless its
seat repositions it -- `REPOSITION_FLANKERS`, asked of the attacker and
then the defender, only where one has a flanker, before the placing
begins, because a flanker that is moved is placed with the others under
the same turns. Keeping is the default answer, since it is what most
players want (the author, 2026-11-06).

**A retreat with no path home is partial** (TNP 6.6, 7, the author,
2026-11-06). The air units go, and the Chopper Carriers take what the
action's `carried` names, up to `human_board.json`'s `transport`
capacity, one kind a carrier; the ground units left behind stay and
fight, and the battle goes on. The retreating units are `leaving`: they
roll no dice (`firing`), may be hit, and leave at `END_ROUND` into
`withdrawn`, which the outcome carries. Only a retreat that takes every
unit ends the battle as a defeat. A force a carry splits stays one
force, and its hits come off the units staying first: the retreating
units are hit only once every unit they were leaving behind is
destroyed (the author, 2026-11-06), so `_withdraw` takes home what is
left of the carried count. Its damaged units count among those
staying -- the one reading here that is the code's, not the author's.

**The losses come off at the group's end** (TNP 6.7): a roll adds to
the target's hits; Splash and Repair's Workers are units removed
outright; at `CLOSE_GROUP` each hit Mechanical force with Workers
beside it is asked first, then each force takes its hits one at a time
-- a damaged Tough unit removed before an undamaged one is damaged --
and then its removals. Repair is asked there, not as the hit lands,
because that is when the unit would come off.

**What the author settled on PR #708** (2026-11-06), all in
docs/tnp-rules.md and its log: flankers kept where they stand or repositioned each round; an
undefended base is offered its emergency defense before it falls; both
sides destroyed together is nobody's battle, the territory as it was;
the retreat and the placing turns above; one flanker a force, in its
force's column, +1 on top of the −1 a column; a split force's hits on those
staying first; Splash once a roll, from the side hit, a damaged unit
first.

## The pictures

Step 3 drew the map, a seat's player board and the battle by code
(decision 6), in `tnp/render.py`, the one TNP module that imports
Pillow. `scripts/render_tnp_sample.py --out <dir>` renders the opening
map, a mid-game map in March, both seats' opening boards, a mid-game
board and two battles in round 3 -- one for a territory, one for a
base -- fought through `driver.apply` with a seeded `engine.rng`.
`tests/test_tnp_render.py` checks each is a PNG of its layout's size and
nothing more: a picture is checked by looking at it
([board-image.md](board-image.md), "Look at the image").

**A brief, filtered before it is drawn.** The map and the board are
drawn from `tnp/briefs.py`'s `MapBrief` and `BoardBrief`, plain
dataclasses with no Pillow in them, so the model can build one and the
purity ratchet still holds. A brief is already what its viewer may see:
`MapBrief` carries who holds each territory, the tokens left, the
Stranded tokens and the piles March has revealed -- there is no field a
deployment could be put in before its reveal (TNP 5.3, question 12) --
and `BoardBrief` is one seat's own board, queue included, which the
frontend shows to that seat alone (TNP 5.2). The renderer decides
nothing about who sees what, so a picture cannot leak by a branch
someone forgot. The battle needs no brief: `BattleState` is public and
already one picture's worth. Step 3 builds only the opening briefs
(`opening_map`, `opening_board`, from TNP 3); step 4, which puts the map
and the seats on `MatchState`, adds the readings that build a brief from
a match, which is why the mid-game samples are staged by hand.

**The map** is `map.json`'s traced outlines filled over a dark ground,
so the gaps between them are map 3.3's own lines, thick and thin where
the original has them, rather than a stroke of one width drawn over
every border. It is drawn at twice its size and reduced, for smooth
edges. Each area's marks -- its number, a held territory's control
shield, the tokens left (a resource with none left is not drawn), a
Stranded token per seat, the revealed piles' discs -- are stacked on its
widest part, found by eroding the filled outline until the last pixels
standing (the pole of inaccessibility), so a number sits clear of its
borders whatever shape a later map gives it, and no position is kept by
hand. A territory is tinted by who holds it, a base in its seat's
stronger tint with its shield. A revealed pile is a disc on the map --
its spot's letter, or a white shield for a defense spot, a disc so it
never reads as a control token -- and a card under the map with its
units, in the order March revealed them.

**The board** follows the canvas the author saw (the Human base board):
the seat's colour as the header with the available pool beside it,
which is open information (TNP 2.2); the four facilities as columns,
each with its current production cap (the upgraded one once its
infrastructure upgrade is built), what it is producing, and whether it
is built, being built or what it costs; its units, then each unit
upgrade with the units it unlocks; and its infrastructure upgrade in a
dashed box with the sheet's own text. A unit card carries board v4's
type colour (infantry green, armored red, air blue), its cost, its three
ratings as `Rating.shown` -- 3+, 6+, 12, X -- over the rating's name,
initiative, traits as `formatting.TRAIT_NAMES` spells them, and supply
left. A unit its seat cannot build yet, its facility or upgrade not
finished, is faded rather than hidden, as the printed board shows every
unit. The footer is the d12's numbers, the limits and the conversion
rates, normal and emergency, each read from `human_board.json`.

**The battle** is the line as columns: the defender's row above the
middle line and the attacker's below, each seat's flanking forces on
the outside of its front row, the rows named at the left. A force tile
is its unit, its count, its type's stripe, and chips for its damage
tokens, this group's hits and removals not yet taken off (TNP 6.7), the
units retreating and whether it has rolled. A base battle has its two
base cards at the line's two ends in the defender's row, attacked as
armored, with the base's structures and what the base card destroyed
under the field. The round track, the scouting advantage and the group
rolling are in the heading, and the forces not yet placed in a tray at
each seat's edge.

**Fonts** are D12 Ball's Roboto Slab, read by absolute path from
`d12ball/fonts/` and never copied. The pictures name a seat "Blue" or
"Green" and no player: a mention cannot be drawn, and the message the
picture rides on names the players.

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
battle by code. Step 4 built the whole basic game around the battle --
the turn, the record, the service and the games file -- and played it
to both wins through the driver alone. Step 5 put it on Discord as far
as turn 1: the lobby, the game's channel, the table and each seat's
panel, and the hub's **TNP** button. Step 6 put the turn on Discord:
each seat's controls, March posted attack spot by attack spot, the
trade, Cleanup -- everything but a battle.

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
`tnp/engine.py`, so every draw is `engine.rng`. Since step 4 it covers
`gamesaves/tnp/` too.

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
match's only field until step 4 added the turn around it -- so a battle
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

## The turn

Step 4 built the turn (TNP 5) around step 2's battle, in the same
shapes. `tnp/components.py` holds the match: the turn and the phase,
each area (`AreaState`: its controller, its tokens left, its Stranded
tokens), each seat (`SeatState`: its faction, what is built, its pool,
its units at the base, what its Infrastructure queued, the tokens it
has harvested, and its plan), the defense spots by area and seat
(`Pile`, units with their damage), the attack piles March has not
reached, the attack being resolved, what March has revealed, and the
winner -- each class with its own `SavedField` table, held to its
fields by `tests/test_tnp_turn.py`. `tnp/turn.py` holds the readings --
what a seat's held territories join to its base, whether a pile
reaches, what a seat owns and may build, and the checks on a plan and
a trade -- and `tnp/flow/turn.py` the steps. `tnp/game.py` gained the
record, `TnpGame`; `gamesaves/tnp/` the service and `data/tnp_games.json`.

**A simultaneous phase.** Infrastructure and Deployment, and Production
and Trade's trade, ask both seats at once (decision 7): `PLAN` and
`TRADE` are prompt kinds asked of each seat that has not locked in, and
in the trade only of a seat with a mineral or a gem, since a question
with no choice is not asked. `tnp.prompts.pending_all` is the one
reading -- every prompt open, or the step the bot owes -- and `pending`
the one thing where there is one, raising `SeveralAsked` where both
seats are asked, as Codex's two-headed dragon does
([codex.md](codex.md), "Multiplayer"). An answer to a simultaneous kind
names its seat (`Action.seat`); `driver.answer` finds that seat's
prompt and refuses an action without one. Once both have locked in the
phase is the bot's to move on: `REVEAL` and `SETTLE_TRADES` are owed
steps.

**Where a locked plan is kept: on the match.** A seat's answer is its
whole plan -- a dict of what to build, which facilities and upgrades,
each attack spot's target and units, each defense's units
(`tnp/turn.py`'s docstring has the shape) -- or its whole trade, and it
lives on `SeatState.plan` with `locked`, saved with the match. `save`
keeps it, checked as it is saved so a locked plan is always one the
rules allow; `lock` locks in the plan given or the one saved; and a
locked seat is asked nothing more. So a restart mid-phase reads both
plans back -- `GameService.resume` puts the unlocked seat's prompt up
with its saved plan in its options -- which is Codex's standing tech
choice held on the match ([codex.md](codex.md)) and is why there is no
undo yet: a plan can be changed until it is locked (decision 10). A
whole plan rather than a click at a time because the model then checks
one thing, not a history of edits; step 6's panel sends the whole plan
again with every change (below, "The turn on Discord").

**Hidden until revealed.** A plan prompt's options carry the seat's
plan and its units, so it is its asked seat's alone, and
`GameResult.to_dict` writes no prompt. What is said in public is said
by the steps, and they say only what the rules reveal: a save says
nothing; a lock-in that the seat has locked in; the reveal what each
seat paid -- the pool is open information (TNP 2.2) -- and never what
for; production that the queues are finished, and nothing of them; a
trade in full, its tokens and its gains being the pool's. March
reveals as it resolves: a battle reveals every unit in it (TNP 6.1), a
neutral conquest the one ground unit revealed to take the territory
(TNP 5.5), and a harvest the Workers that did it. The rest of a pile
that took a neutral territory stays face down in its spot.
`MatchState.revealed` is the public record of what March showed, which
`tnp.briefs.map_brief` builds the map from -- **one entry a pile** (a
seat's units from one spot at one area), a pile shown twice, as a
conquest's unit and then its harvesting Workers, keeping the most of
each unit ever shown rather than the two showings added (PR #712: the
map had drawn "1 Worker" and "3 Worker" as two piles); `board_brief` is the
seat's own. `tests/test_tnp_driver_full_game.py` holds that the plan
phase and its reveal name no unit.

**March, attack by attack.** `MARCH` is an owed step that resolves one
attack -- A for both seats, then B, within a spot in ascending
territory number, a base after every territory -- so step 6 can post
each as its own lines. A pile that no longer reaches its target as its
attack resolves (no path of held territories, and ground units its
Chopper Carriers cannot carry, TNP 5.3, 7) sends its ground units back
to its base unrevealed, and its air units, where it has any, attack
alone -- they must (the author, 2026-11-06). Otherwise: two seats at one area, or a held territory, or
the other seat's units already standing there, or a base, is a battle
through `begin_battle`, with each seat's attacking pile and its units
in the area's defense spot as its forces and the base's structures,
pool and supply room handed in; a neutral territory nobody contests is
always taken by revealing a ground unit -- `CONQUER` asks which only
where the pile has more than one kind -- and a territory the seat holds
is harvested. **A harvest from a territory of two kinds is the seat's
choice** (the author, 2026-11-06): `HARVEST` asks it, with the attack
still resolving, only where the Workers take less than all that is
left; otherwise the tokens are taken at once. `SETTLE_BATTLE` is the owed step that puts a battle's
`outcome` on the map: survivors, control, the Stranded tokens, the
emergency spend and the base card's destruction, the harvest, and a
fallen base's win. Battles are fought through the battle's own prompts
in the middle of the phase, so a battle in March is one seat's question
at a time.

**The Stranded tokens** (TNP 5.7) are placed where a change of control
cuts a held territory off from its seat's base with its units in it --
comparing what each seat's held territories joined before and after --
and lifted only once the territory is joined to the base again: taking
a territory beside it lifts the token where that makes the path, and
not otherwise (the author, 2026-11-06, reading TNP 5.7's "takes a
territory adjacent" as needing a path). A seat that loses a territory
loses its token there. Cleanup leaves stranded piles where they are,
their units, not being at the base, cannot be deployed, and nobody
deploys into a cut-off territory: defenders go only where the base
joins (TNP 2.5, the author, 2026-11-06).

**The winning checks.** A fallen base wins at once, in
`SETTLE_BATTLE`; 49 tokens harvested is counted at Cleanup (TNP 1.3,
5.10), after the trade. The service finishes the record in the same
save as the match that has a winner.

**What the author settled on PR #710** (2026-11-06), all in
docs/tnp-rules.md and its log: a neutral territory reached with a
ground unit is always taken, and the rest of the pile stays face down;
the seat chooses the kind its Workers harvest; a pile with no path
sends its ground units home and its air units on; air units and a
carried stack attack a base with no path; units queued at a facility
destroyed that turn are lost with their cost; **a damage token lasts
the battle alone**, so `settle_battle` puts the survivors in the spot
with none (`Pile.damaged` stays in the save format, written empty);
a base resolves last in its spot; defenders go only where the base
joins; both seats at a held territory fight with the holder's pile
beside its defenders; the Stranded token as above; and an air-only
pile at an uncontested neutral territory waits in its spot.

**The whole game through the driver.** `tests/tnp_games.py` plays a
game with simple strategies that read each prompt's options as a view
would; `tests/test_tnp_driver_full_game.py` plays Blue against Green to
a fallen base and to 51%, every position round-tripped through its save
before the next question, and checks in a fresh interpreter that no
`discord` and no `cogs` was imported.

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
already one picture's worth. Step 3 built the opening briefs
(`opening_map`, `opening_board`, from TNP 3); step 4 added the readings
that build a brief from a match (`map_brief`, `board_brief`), after the
mid-game samples were staged by hand.

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
hand. **The marks never cross the area's border** (the author,
2026-11-06): `_placement` measures the box the marks fill, with 8
pixels' clearance, against the filled outline, and moves them to the
nearest place it fits whole; where no place does, it tries the number
over the rest side by side, then everything in one line, then each of
those smaller, down to 65% (`MARK_SCALES`), which still keeps every
word at 16 pixels or more. Only territory 12, a sliver, ever needs it:
80% for its number and token, 65% with every mark at once.
`crossing_areas` is the same measure as a reading, and
`tests/test_tnp_render.py` holds it empty for the opening map and for
every mark on every territory at once. The Stranded token reads
"Stranded" in its seat's colour, which says whose -- a seat's name in
it made it the widest mark. A territory is tinted by who holds it, a base in its seat's
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

**The battle** is the line as columns: the attacker's row above the
middle line and the defender's below (the author, 2026-11-06), each
seat's flanking forces on the outside of its front row, the rows named
at the left. A force tile
is its unit, its count, its type's stripe, and chips for its damage
tokens, this group's hits and removals not yet taken off (TNP 6.7), the
units retreating and whether it has rolled. A base battle has its two
base cards at the line's two ends in the defender's row, attacked as
armored, with the base's structures and what the base card destroyed
under the field. The round track, the scouting advantage and the group
rolling are in the heading, and the forces not yet placed in a tray at
each seat's edge.

**Sized for Discord, and white** (the author, 2026-11-06, on the first
renders: "a lot of the writing is too small", and an off-white is made
white). Discord shows a picture at a third of its width or less until
it is opened, so no word is drawn smaller than `render.SMALLEST`
(16 pixels) on a picture 1,600 to 1,700 wide, and the map's marks --
its numbers, tokens, Stranded tokens and pile discs -- are larger
still: a resource token is a 56-pixel pill, one a row, since two side by
side do not fit territories 4 and 5 at that size (the author,
2026-11-06: too small at 46 pixels, too big at 66, where it crossed
the territory lines). Every fill is white or a colour that means something: a chip is
white with an outline, a rating's cell green, amber, red or grey, a
held territory its seat's tint. No beige or cream is left.

**No unit art** (the author, 2026-11-06, answering decision 6's open
offer): the board and the battle name a unit and colour it by its type,
and the Drive's unit pictures are not imported.

**The board's footer keeps the advanced game's limits** (the author,
2026-11-06) -- one building tech a facility, two tech facilities --
marked as the advanced game's, because board v4 prints them.

**Fonts** are D12 Ball's Roboto Slab, read by absolute path from
`d12ball/fonts/` and never copied. The pictures name a seat "Blue" or
"Green" and no player: a mention cannot be drawn, and the message the
picture rides on names the players.

## The lobby, the channel and the table

Step 5 of the worksheet. **`/tnp create_game` and the hub's TNP button
are one method**, `Tnp.open_lobby` (`cogs/tnp/lobby.py`): a channel
`tnp-<n>` under **TNP Games** (else a thread, below), the lobby posted in it, and the person
who asked already sat as Blue. The number is the guild's next
(`GameService.next_game_number`). The category is TNP's own, apart from
D12 Ball's PBD categories -- whose names `/debug`'s reset and the pin
rollover match -- and from the Codex bot's.

- **A channel, else a thread** (the author, 2026-11-06, answering PR #711's question:
  "should fall back on a thread"). `open_game_place` tries a channel of
  its own first; where the bot may not make one (no Manage Channels), a
  public thread named `tnp-<n>` in the channel the lobby was asked for
  in -- the hub's channel, for the hub's button -- with a week's
  auto-archive, the longest. The record says which, `TnpGame.venue`
  ("channel" or "thread"; "channel" in a save from before it). A thread
  is renamed at Start as a channel is, and **any click or `/tnp`
  command on an open game in an archived thread first takes it out of
  the archive** (`wake_thread`, from `SafeView.interaction_check` and
  the cog's own) -- one request, only while archived -- since a message
  in an archived thread cannot be edited. Codex's third place, the
  channel the command was typed in, is not offered. A place whose lobby
  cannot be posted is deleted and the next tried; where neither can be
  made, `GameService.discard_game` forgets the lobby and the asker is
  told what each needs.
- **The channel is open to the whole server** (and a thread is public),
  from the lobby to the end, as Codex's is: anyone may read it, talk in it and take the free
  seat. D12 Ball hides a started game from `@everyone`; TNP need not,
  since nothing hidden is ever in the channel (below).
- **The lobby** (`cogs/tnp_views/lobby.py`, `LobbyView`, persistent) is
  **Sit as Blue**, **Sit as Green**, **Leave** and **Start**. Every move
  is a service method over the record's own rule (`TnpGame.take_seat`,
  `leave`, `start`, each refusing with `RuleRefusal`), and a seat taken
  or given up edits the lobby through the click's own response, which
  spends nothing from the channel's bucket. Start is either seated
  player's or a game helper's, with no confirmation, as in D12 Ball's
  and Codex's lobbies. A **test game** (`/tnp create_game
  test_game:True`) lets one person sit in both seats, the record's rule
  since step 4. There is no setting for the advanced game: `set_advanced`
  refuses it until step 9, so a button would only say no.
- **Start** deals the opening position through `GameService.start` (one
  save), renames the channel `tnp-<n>-<blue>-vs-<green>` (each player's
  name slugged, capped at 100 characters), closes the lobby through the
  click's own response -- its buttons gone -- and posts **the table**
  under it. Three requests on the channel's bucket: the lobby's send
  when it opened, the rename, the table's send
  (`tests/test_tnp_cog_lobby.py` counts them).
- **The table** is the game's one public message: the map
  (`map_brief`, public by construction, captioned "Turn 1 · Infrastructure
  and Deployment"), and the model's lines (`tnp.formatting.table_lines`):
  the turn and the phase, and in a phase both seats answer at once,
  each seat "is planning", "has locked in", or, in the trade, "has
  nothing to trade". Who is asked is read off `pending_prompts`, the one
  reading, and nothing of a plan is read at all. **My board**
  (`TableView`, persistent) is its one button. Since step 6 it is
  edited through `BoardRefresher`'s gate (below, "The turn on Discord").
- **The seat tokens are rendered at the door** (`cogs/tnp_helpers.py`,
  `TnpTokens`): `{seat:blue}` is "**Blue** (Alice)", the seat and its
  player's name -- never a mention, so the table pings nobody and an
  edit cannot either. A unit, a facility, an upgrade and an area are
  `tnp.tokens.plain`'s words.
- **The startup sweep** (`CoreMixin.restore_saved_views`, run by
  `cog_load`) re-arms each open lobby's `LobbyView` and each playing
  game's `TableView` by message id. A game whose match no longer loads is
  logged with its traceback and skipped, the others re-armed; a playing
  game with no table message is logged at ERROR, since somebody has to
  run **`/tnp resume`**, which runs any step the bot owes
  (`GameService.resume`) and posts a fresh table. `load_games` already
  skips a game it cannot read, and a games file that is not JSON leaves
  TNP with no games and **D12 Ball loaded and answering**
  (`tests/test_tnp_isolation.py`, decision 2). A click on any TNP view
  while the data has not loaded is told TNP is unavailable
  (`SafeView.interaction_check`).

**The hub's TNP button** is in [hub-and-lobby.md](hub-and-lobby.md): it
finds this cog by name and calls `open_lobby`, so it opens a lobby where
Codex's button can only name a command.

## Hidden information on Discord

A seat's queue and deployment are its own until the phase reveals them
(TNP 5.2, 5.3). On Discord that is Codex's shape ([codex.md](codex.md),
"Hidden information on Discord"): **the public message says nothing
hidden, and what is hidden is ephemeral, to its seat's player alone.**

- **My board** answers the clicker privately, deferred first (a board
  drawn and uploaded can outlast Discord's three seconds), with **one
  ephemeral message a seat they hold** -- both, in a test game, where
  nothing is hidden from one person playing both. Each is the seat's
  player board (`render_board` over `board_brief`, captioned "Turn 1":
  the phase's name collided with the pool in the board's header), and
  the panel's words: whose board, the pool, the prompt's ask and what
  its options offer -- the units to build with their cost and the most
  of each, the facilities and upgrades, the units at the base, the
  attack spots and the territories a ground unit has a path to now. All
  of it is read off `PendingPrompt.options`; the cog computes none of
  it. A watcher is told the boards are the players'. Step 6 put the
  controls on the panel (below).
- **Where it was checked**: the table's text is `table_lines`, which
  reads `locked` and the asked seats and no plan
  (`test_nothing_of_a_plan_reaches_the_channel` saves a plan and reads
  the table); the map is `map_brief`, which holds no pile March has not
  revealed; the boards are sent with `ephemeral=True` and drawn for the
  asked seat alone (`test_my_board_answers_each_player_alone_with_their_own_board`);
  and the log lines `cogs/tnp*` writes name a game and nothing of a
  seat's -- `SafeView.on_error` logs the view's class and the item's
  kind, never the item, whose label will name a seat's units. A
  refusal is shown to the clicker alone and never logged.


## The turn on Discord

Step 6 of the worksheet: two people play a turn from Infrastructure and
Deployment to Cleanup on Discord. Everything but a battle -- a battle
met in March is named, and the game waits there for step 7.

**A panel a seat, its controls from its prompt's options.** **My board**
answers with the seat's board and its panel, ephemeral, and the panel's
controls are `cogs/tnp_views/panel.py`'s, one view a turn prompt kind
(`panel_view`, the one mapping): the plan (**What to change** -- the
units to build, the facilities and upgrades, attack spots A and B, each
defense -- then that part's menus, **Lock in** and **Clear plan**), the
trade (a token kind, how many for materials and how many for gold,
**Lock in**, **Clear trade**), March's **Ground unit to reveal**, and the
harvest's counts and **Take**. Every menu is built from
`PendingPrompt.options` -- the units to build with their most, the
targets with whether a ground unit has a path now, the units at the
base, the defenses, the tokens held -- and the panel's words are
`tnp.formatting`'s (`plan_lines`, `plan_offer_lines`, `trade_lines`),
off the same options: the saved plan and what its Infrastructure costs
(`PlanOptions.cost`), the saved trade and what it gains
(`TradeOptions.gains`), both added to the options for this, since a
cost is the model's to work out.

- **Every change is a save through the service.** A menu choice sends
  the whole plan again (`PLAN`, `save`), which the model checks as it
  saves (`check_plan`). So the draft is never the panel's: it is on the
  match from the first click, a refusal -- six units from a Barracks of
  four -- is shown at the panel's head with its section and the plan
  stays as it was saved, and **a restart keeps both plans**: **My
  board** opens a fresh panel over the plan saved on the match.
  `tests/test_tnp_cog_turn.py` restarts the cog between two plans and
  locks both in. What the panel holds itself is only what is not yet an
  answer (`PanelState`): which part is being changed, the unit a count
  is for, an attack's target before any unit is in it -- the model drops
  an attack with no units, so a target alone would be lost -- and a
  harvest's counts before **Take**.
- **A click redraws the panel in place, through the click's own
  response**, which spends nothing from the channel's bucket; the board
  under it is drawn again only where the turn or the phase moved since
  it was drawn (`PanelState.drawn`), deferred and edited through the
  click's webhook. A panel answers clicks for an hour (`PANEL_TIMEOUT`,
  Codex's), and is not persistent: after that, or a restart, **My
  board** opens a fresh one over what is saved. Nothing is lost by it.
- **Only the seat's player may click it** -- both seats', in a test game.
  A helper may not: the panel is a seat's hidden plan.

**The table is edited through the write gate** (`BoardRefresher`,
[rate-limits.md](rate-limits.md)), shared with D12 Ball and Codex: the
table message, `TableView`, and `table_lines` as the text beside the
map. A lock-in that leaves the other seat still answering edits the
table's text alone -- who has locked in, nothing of either plan -- and
posts nothing, the table saying it; the map, unchanged, is not
uploaded. No full-image link (`links` off): the map opens by a click on
it, and a link is a second request after every upload. The table's
first post is handed to the gate (`posted`), so the gate's first edit
skips what is already up.

**March, an attack spot a message.** The second lock-in runs the whole
turn the bot owes -- the reveal, every attack, Production, and where no
seat has a token to trade, the trades and Cleanup -- in one call, so
the service has to say where one attack spot ends and the next begins
and what the map looked like there; by the end of the call Cleanup has
taken the revealed piles off it.

- **`StepResult.part`** is the model's report of where: a March
  attack's spot, "A" or "B", on the lines that attack said, and on a
  conquest's or a harvest's answer. It says where one thing ends, never
  how lines are put together.
- **The cog's batching stops the run after each March attack**
  (`Batching.stop_after`, `cogs/tnp/core.py`'s `STOPS`), and the service
  closes a group at each stop with its part and **the frontend's
  picture of the position there** (`Batching.picture`: the cog hands
  back the map's brief, public by construction), then runs on. An
  answer whose lines name a part is a group of its own, never the
  lead-in to the next part's.
- **The cog posts one message an attack spot** (`messages_for`): the
  groups of one part together, with the map as that spot's last attack
  left it, then one message for the rest -- March's end, Production,
  the trades, Cleanup -- without a picture, the table carrying the map.
  The reveal's lines lead into the first spot's. A message ends on what
  is asked now: a seat's March question with its ask, or both seats'
  plans or trades, and where they are answered -- **My board** on the
  table, linked by the table's message link (no request: the link is
  built from its ids).
  **Whoever is asked is pinged there** (the author, 2026-11-06, on
  PR #712): their mention on that last message, each person once, with
  `allowed_mentions` naming them alone; nothing else TNP posts pings
  anyone, the table and the seat tokens included. A battle that waits
  for step 7 pings nobody: nothing on Discord can answer it yet.
- **The map is drawn per spot on that spot's message, not on the
  table.** The worksheet asked for the table's map redrawn once a slot
  through the gate; but the gate coalesces writes inside its window and
  a trailing write draws the position as it is when it runs, so the
  per-spot maps of one call would never be on the table -- and by then
  Cleanup has cleared what March revealed. On its own message each
  spot's map stays in the channel's history, for the same send it
  would have cost anyway; the table goes to the position at the end of
  the call, through the gate, once.
- **A battle met in March** posts its opening lines and "battles arrive
  in step 7"; the panel of a seat asked a battle's question says the
  same, and the game waits there.

**The requests a whole turn spends** from the channel's bucket,
measured by `test_a_whole_turn_from_infrastructure_to_cleanup` over
`tests/codex_cog_fakes.py`'s channel, from the first plan click to turn
2, for a turn with two neutral conquests -- one asking which unit is
revealed -- a harvest each and both seats trading: **ten**, five sends
and five table edits. Blue's lock-in: one edit (the text). Green's: the
reveal and attack A's opening, with its map, a send, and the table, an
edit. Blue's conquest: attack A's rest and B's, each a send with its
map, March's end and Production a send, and the table an edit. Blue's
trade: one edit. Green's: the trades, Cleanup and turn 2 a send, and
the table an edit. Every plan click, every panel and every **My board**
is an interaction's own route and spends none of it. With the gate's
real six-second window, edits inside one window collapse into one
trailing write, so the count is at most this.

**Hidden information, where it was checked.** The panels are ephemeral
and their words are the seat's own options; the table's text is
`table_lines`, read before and after each lock-in; what is posted is the
model's narration, which says only what the rules reveal (above, "The
turn"); and the per-spot maps are `map_brief`'s.
`test_a_whole_turn_from_infrastructure_to_cleanup` holds that no unit
and no target of either plan is in anything the channel was sent or
edited to before the reveal, and `test_a_lone_lock_in_edits_the_table_and_posts_nothing`
that a lock-in says only that. The cog's log lines name a game and
nothing of a seat's; a refusal is shown to the clicker alone.

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
`/tnp rules`. The game itself begins in step 2.

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
no `discord`, no `async def`, Pillow only in `tnp/render.py` (step 3).
Step 1's modules are already words and readings over data, so the
`/tnp unit` answer is the model's (`tnp.formatting.unit_lines`) and the
cog only posts it -- including the d12 numbers, which are
`catalog.Rating`'s, not a computation in the cog. The purity ratchet
over `tnp/` starts in step 2, when the first rule lands.

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
together).

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

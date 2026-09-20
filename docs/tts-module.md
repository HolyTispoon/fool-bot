# A Tabletop Simulator module for D12 Ball

**This is a worksheet, not a specification.** It is the plan the Tabletop
Simulator (TTS) module is being built from, in the shape of
`model-discord-split.md`: the decisions already taken are at the top so
nobody re-opens them, the phases each end on a stop where a person loads
the thing in TTS, and the answered parts get cut as they land. When the
module ships, what survives of this moves to `docs/design/tts-module.md`
and this file goes. **Nothing in it is a rule.**

The goal is the game on a virtual table, built from the same data and
renderers the bot plays from, so that a rules change, an import or an art
fix reaches the table the way it reaches the print-and-play kit -- by
re-running a script -- and nothing on the table is typed by hand from the
sheet.

## Decided, 2026-09-20

These four were settled by the author before the plan was written and are
the constraints the rest is built under.

1. **The assets are hosted on GitHub**, in a second repository, not on
   Steam Cloud. See "Two repositories" for what goes where and why the
   split falls where it does.
2. **Meeples are meeples.** A three-dimensional pawn on the table, not a
   flat disc of the bot's board and not a cardboard standee of the
   player's portrait. See "The meeple".
3. **The module ships with convenience scripts**: setting a game up,
   saving and resetting a coach's arrangement, and the like. Not with the
   rules. See "The scripts, and the line they do not cross".
4. **The Workshop item is public.** Which makes the art a licensing
   question rather than a private one -- see "Open questions".

## What a TTS module is

A TTS mod is a **save file**: one JSON document listing every object on
the table with its type, its transform and the URLs of its images or
meshes, plus a Lua script and a text blob of saved script state. You load
it from the Saves folder, and you publish it to the Steam Workshop from
inside the game. Nothing about it needs TTS to *make*; it needs TTS to
*look at*, which is where the stops below come from. The pieces D12 Ball
needs, in TTS's own vocabulary:

| Component | TTS object | Source in this repo |
| --- | --- | --- |
| Field board | `Custom_Board` with three **states** (6, 7, 9 spaces), so one object is flipped between sizes rather than three boards cluttering the table | `boards.render_field_board`, per size |
| Jumbotron (clock, score, token silos) | `Custom_Board` | `boards.render_jumbotron_board` |
| Team board, one per coach | `Custom_Board` | `boards.render_team_board`. The printed sheet stacks two panels to save paper; that is a printing economy, not a rule, so the table gets two boards |
| Maneuver cards, 12 per coach | `DeckCustom` over one face sheet and one shared back | `cards.render_maneuver_card`, `render_maneuver_card_back`, tiled by `cards.print_sheet` |
| Player cards, 9 per team, a back of their own each | `DeckCustom` with a face sheet and a matching back sheet (`UniqueBack`) | `player_cards`, which already produces the paired sheets |
| Species reference, 3 double-sided | `DeckCustom`, `UniqueBack` | `species_cards.render_species_card_set` |
| Meeples, 9 per team | `Custom_Model` -- see "The meeple" | Generated mesh; colour from `render.TEAM_COLORS` |
| The ball; one d12 per coach | Stock `Die_12`, the ball tinted apart | Nothing to render |
| Exhaustion, Exhausted, Injured, Damaged tokens | `Custom_Token` in an `Infinite_Bag` each | `d12ball/images/emoji/` |
| Clock and score markers | Stock cubes | Nothing to render |
| The two coaches' hands | Two hand zones, which hide cards from the other coach | -- |
| The rules | `Custom_PDF` | `docs/living-rules.md` -- see "Open questions" |

Two mechanics the table has to carry that the pieces alone do not:

- **Maneuvers are chosen in secret.** A hand zone per coach is the whole
  of the answer; a card played face down in front of the board and flipped
  together is the reveal. The shootout's secret orders go the same way.
- **Any number of meeples may share a space.** TTS meeples do not stack;
  they cluster. A space on the 7-board prints wider than it is deep (see
  `FieldGeometry.space_inches`), so a snap point sits at each space's
  centre and the coaches shove. This is the physical table's problem too,
  and the bot's board solves it with a `draw_meeple_group` the table
  cannot have.

## What the repo already supplies

Most of the work is done, and was done for the print-and-play kit
(`scripts/generate_print_and_play_kit.py`, "The print-and-play kit" in
`docs/design/cards.md`). What the module reuses, unchanged or nearly:

- **Every card and board at 300 dpi**, from the four render scripts the
  kit already runs.
- **Geometry without rendering.** `boards.FieldGeometry.space_bounds`
  says where each space is; `boards.cell_inches` says how big the clock
  and score cells are and `JumbotronGeometry.clock_cell` / `score_cell`
  where; `boards.card_slot_inches` sizes the team board's card slots.
  These exist so the CLI can report and the suite can assert a size
  rather than read it off a render, and that is exactly what a snap point
  needs: a coordinate the builder computes rather than types.
- **A deck sheet.** `cards.print_sheet(cards, columns)` tiles cards into
  a grid, and `player_cards` already builds a front sheet and a
  row-reversed back sheet per team for duplex printing. TTS slices a
  sheet on a uniform grid, which this nearly is.
- **Stable space names.** `render.space_code` gives H1, M2, V3; the
  builder labels snap points with them and the scripts remember an
  arrangement as a list of them, so an arrangement in the module reads
  like one in a Discord message.
- **The one hex per team.** `render.TEAM_COLORS`, with species teams
  inheriting through `TEAM_PAIRS`, tints the meeples, the dice and the
  markers. Nothing in the module carries a colour of its own.
- **The data.** `players.json`, `basic_rules.json` (`standard_setup`,
  `board_layouts`, `formations`), `species.json`. The scripts' tables are
  generated from these, never typed.

What the kit and the module do **not** share is the print economies.
Bleed, the 1/8-inch margin around every card and board, and the gaps
between cards on a sheet are for a guillotine; TTS wants none of them and
a sheet with margins slices wrong. So the renderers grow a mode rather
than the module reusing the kit's output.

## The scripts, and the line they do not cross

**The scripts move objects and remember where they were. They never
judge a play.** No legality check, no resolution, no "who won", and --
the CLAUDE.md rule holds on the table as it does in the channel --
**nothing rolls dice on its own**.

The reasoning is the model/Discord split's principle 10, applied to a
third frontend: the moment the table has a rule of its own it has a
second copy of the rules, in Lua, that no import script regenerates and
no test in this repo runs. The web app is forbidden exactly that, and the
web app at least shares a language with the model. The engine is Python
and TTS scripts are Lua (MoonSharp, Lua 5.2); there is no way to run
`RulesEngine` on the table, and porting it is the failure mode the split
exists to prevent.

What an *enforced* table would look like, so nobody reaches for the Lua
port when the itch comes: TTS scripts can make HTTP requests
(`WebRequest`), so once the split's Phase 6 has produced a driver that
runs a turn from a request, a hosted service over `d12ball/flow` could
referee a TTS game the way it will referee the web app, with the Lua
reduced to "send the click, apply the `StepResult`". That is a phase of
the *other* worksheet and not of this one. Until then the coaches are the
referee, as they are at a physical table, with the living rules in a PDF
beside the board.

Within that line, the convenience the module ships:

| Script | What it does | What it reads |
| --- | --- | --- |
| **Set up a game** | Puts the field on the chosen size, deals each side's nine player cards onto its team board, stands each meeple on the space the standard deal gives its card's zone, deals twelve maneuver cards to each hand, zeroes the clock and score, and puts the ball on home's kickoff space showing 1 | `standard_setup`, `board_layouts` and the kickoff space, generated from `basic_rules.json`; the team pairs, from `TEAM_PAIRS` |
| **Save arrangement** (one button per side) | Reads each of that side's fielded meeples against the field's snap points and records a space code per meeple in the script state, which TTS carries inside the save | The field's snap points, labelled with `space_code` |
| **Reset to arrangement** (one per side) | Moves that side's meeples back to the recorded spaces. This is what a new play does in the rules ("Every fielded meeple on both sides goes back to the space its coach's arrangement puts it on"); the coaches press it after a goal, a miss or a ball out of bounds. It does not decide that a new play has happened | The saved state |
| **Clock and score** | Nudge buttons on the jumbotron that move the markers a cell at a time, so a coach never has to drag a cube along a track of sixteen | `cell_inches` and the cell geometry, generated |

Halftime, substitutions and exhaustion are deliberately not scripted.
Each is coaches moving things, which is what a Coaching Choice is, and a
token on a card is counted by eye at a physical table too.

**Save arrangement is a button and not automatic** for the same reason
the Coaching Choice's `finish` is a button in the bot: the arrangement is
the shape the coach *finished on*, and only the coach knows when they
have finished. Recording on every drop would record the scramble a steal
forces, which the rules say never changes an arrangement.

**The scripts' data is generated, never written.** The builder emits a
`data.lua` (the standard deal, the layouts, the kickoff spaces, the
rosters with `player_with_role` for each meeple's name, the team hexes)
from the JSON files and the model, and the hand-written `Global.lua`
requires it. A rules import that changes the standard deal reaches the
table by rebuilding, and the suite can assert the generated table against
the JSON it came from. The CLAUDE.md rule on abilities holds: an ability's
text reaches a meeple's description from `players.json` through the
builder, and is never shortened in Lua.

## Two repositories

**`fool-bot` holds everything a person types. The asset repository holds
everything a script generates.** Suggested name `HolyTispoon/d12ball-tts`;
it is the author's to name.

Why a second repository and not the kit's gitignored folder:

- **TTS loads by URL and caches by URL.** A player who has loaded the
  module once keeps the image under that URL until they clear their
  cache, so a URL whose content changes shows different tables to
  different players. Every version of the module therefore needs URLs
  that never change content. A raw GitHub URL pinned to a **tag**
  (`raw.githubusercontent.com/<owner>/<repo>/<tag>/<file>`) is exactly
  that, and a branch URL is exactly not; the builder takes the tag and
  bakes it into every URL in the save.
- **Generated output never enters `fool-bot`'s history.** `print/`,
  `cards/` and the kit are gitignored today for that reason, and a
  hundred-odd PNGs plus a mesh re-rendered on every art fix would bury
  the code's history under binaries. The asset repository is *only*
  history of that kind, which is what it is for.
- **The Workshop item points at one tag.** Publishing is: build from
  `fool-bot` into a checkout of the asset repository, commit, tag, push,
  load the save in TTS, publish. Re-publishing is the same with a new tag,
  and the old tag keeps every earlier subscriber's table intact.

What goes where:

| `fool-bot` | Asset repository |
| --- | --- |
| `d12ball/tts.py` -- the builder: the object list, the snap points from the geometry, the deck definitions, the URL scheme. Pure Python; it is under the purity ratchet like `boards.py` and that is fine, it has no reason to want `discord` or `async` | `assets/<tag>/…` -- the sheets, boards, tokens, the meeple mesh; every URL in the save resolves here |
| `scripts/build_tts_mod.py` -- the CLI: renders in TTS mode into a checkout of the asset repository and writes the save beside them | `D12 Ball.json` -- the save, with the tag's URLs baked in |
| `tts/Global.lua` -- the hand-written script | `data.lua`, generated, and the save carries both inline in its `LuaScript` field |
| `tests/test_tts.py` -- see "Tests" | `README.md` -- generated the way the kit's is, saying what tag, what date, what checkout |
| A "TTS" mode on the four render scripts and on `print_sheet` | Nothing hand-written at all |

## The meeple

**TTS ships no meeple of its own.** The Objects menu wears a meeple
icon, which is what makes this worth writing down, but the stock
components behind it are dice, chess and checkers, chips, dominoes, go
stones, the player pawn and a handful of figurines. A meeple on a TTS
table comes from a Workshop mod (Meeple-o-Rama and the CGS Prototyping
Kit are the ones people point at) as a custom model saved out of somebody
else's game -- a mesh hosted on somebody else's Steam Cloud, under
somebody else's licence, at a URL nobody here controls. So a meeple is a
`Custom_Model` either way, and the only question is whose mesh.

A `Custom_Model` needs a mesh URL and optionally a texture; a mesh with no
texture takes the object's `ColorDiffuse`, which is how one mesh serves
eight teams from `TEAM_COLORS` with no per-team asset.

**The mesh is generated by the repo, not downloaded.** A meeple is a flat
silhouette with thickness, which is a polygon extruded into an OBJ file:
a few dozen lines of Python over an outline drawn once and kept as data
in `d12ball/tts.py`, the way a card layout is. Three reasons over a
Workshop or Thingiverse mesh: the item is public, and somebody else's
mesh is a licence to check and credit on a Workshop page; a Workshop
mesh lives at a URL that can go away (Meeple-o-Rama's page is already
flagged incompatible), and the two-repository rule above exists so that
no asset on the table is at a URL the tag does not pin; and a generated
meeple's shape is data like everything else on the table, so the next
person who wants it a little fatter edits a polygon rather than a
binary. The same mesh serves as its own collider.

**Identity.** A team-coloured pawn does not say which player it is. What
the first version carries is TTS's own hover text: the meeple's
**nickname is `player_with_role`** (`Hellguard [FB]`, the same spelling as
a button in the bot, and the only spelling), and its **description is the
player's ability** from `players.json`, so hovering a meeple reads its
card. A **role badge on the body** -- a planar texture on the chest with
the role icon and species icon the bot already has at 256 px -- is the
obvious next step and is an open question below, because it turns one
mesh into thirty-six textured ones and the author should say whether the
hover text is enough before anybody draws it.

**Scale.** The printed-boards note sizes a meeple's base at about half an
inch and a space at no less than three-quarters, which is the ratio the
table keeps: the builder has one constant, TTS units per inch, chosen so
a card sliced from a deck sheet comes out the size of TTS's stock card,
and everything -- boards, snap points, the meeple's footprint -- is
placed through it. It is a constant to be read off the table in Phase A
and then never touched.

## Phases

Each ends on a **stop**: a person loads the result in TTS and looks. That
cannot happen in CI or in a remote session, which is why the phases are
cut where they are -- every one lands something a person can see, and
nothing in a later phase is worth starting until the earlier stop has been
looked at.

| Phase | What lands | Stop |
| --- | --- | --- |
| **A** | The TTS mode on the renderers (no bleed, no sheet margins, every image at most 4096 px on a side since TTS downscales past that -- the tabloid field board at 3300 x 5100 is the one that has to shrink). The asset repository, with one tag. A save **made by hand in TTS** from those images, which is what calibrates the units-per-inch constant | The table laid by hand: boards, decks, dice, bags. A coach can play a half with nothing scripted |
| **B** | `d12ball/tts.py` and `scripts/build_tts_mod.py`: the save emitted whole, with snap points from the geometry, the three-state field, the decks, the hands, the bags, the rules PDF. `tests/test_tts.py` | The emitted save loads and matches the hand-made one. Snap points land on the printed spaces |
| **C** | The meeple: mesh generated, coloured per team, named and described per player | Thirty-six meeples on the table, hover text read |
| **D** | `Global.lua` and the generated `data.lua`: set up, save and reset arrangement, clock and score. Script state surviving a save and reload | A whole game played through with the scripts, including a reload mid-game |
| **E** | The Workshop item, published from a tag. The asset repository's README. This worksheet cut down to `docs/design/tts-module.md` and its CLAUDE.md rows | Somebody who is not either developer subscribes and plays |

Phase A before B rather than B straight off because the constant B needs
is measured on a table, not derived; building the emitter first would
mean guessing it and then re-emitting. The stops are also where the
render questions get answered by eye, which the suite cannot do for the
kit either ("Look at the image" in CLAUDE.md).

## Tests

What the suite can hold without TTS present:

- **The save is valid JSON and every URL in it resolves** to a file the
  same build wrote, so a renamed asset cannot ship as a broken table.
- **Counts.** A snap point per space per board size (6, 7, 9), plus the
  zone-assignment rows; a card per maneuver in each maneuver deck; nine
  per team; the clock's sixteen cells and the score track's thirteen.
- **The generated `data.lua` round-trips** to the JSON it was built from,
  so the standard deal on the table is the one in `basic_rules.json`.
- **The builder is deterministic**: two builds from one checkout and one
  tag produce byte-identical saves, which is what lets a diff of the
  asset repository mean something.
- **The TTS render mode is hash-verified the way a drawing refactor is**:
  with bleed and margins off it must produce the same pixels as the print
  mode does inside the trim, so the mode is a crop and not a fork.

The suite does not check the table, and cannot; that is the stops.

## Open questions

For the author, and the answers belong in a review comment rather than a
guess in this file:

1. **The asset repository's name**, and whether it is created empty by
   hand or by the first `build_tts_mod.py` run.
2. **A role badge on the meeple**, or is the hover text enough? Deciding
   after Phase C, with the plain meeples on the table, costs nothing.
3. **The rules PDF.** `docs/living-rules.md` is Markdown and TTS shows a
   PDF; the kit copies the Markdown. Either the build converts it (a
   pandoc dependency for one file) or the module carries the rules as a
   TTS notebook, which is plain text and loses the tables. Or a link on
   the Workshop page and nothing on the table.
4. **Licensing on a public item.** The fonts are fine (DejaVu, and Racing
   Sans One under the OFL). The thirty-six portraits in
   `d12ball/images/player_images/` and the card art need a line on the
   Workshop page saying whose they are, and the author is the one who
   knows.
5. **Which board size the module opens on.** The rules say 7 is the
   default and the field object's first state should agree; the bot's
   own default is what to check it against.
6. **The advanced tier.** The species cards and the advanced player-card
   backs ship in every build (a table can turn them face down); the
   question is only whether Set up a game offers the species teams, or
   whether that is a later script.

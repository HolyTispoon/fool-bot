# Team colors, dual rosters, and species

Design notes for fool-bot; the map is [CLAUDE.md](../../CLAUDE.md), the rules are [living-rules.md](../living-rules.md).

## Team colors

**Eight teams along two axes, since the 2026-08-17 reshuffle.** The
original four **color** teams (Orange, Teal, Purple, Slime) went from a
fixed nine-player roster each to a mixed one -- 3 of their own species
plus 2 of each other -- and the four **species** teams that mix was
drawn from (Fire Demons, Cyborgs, Telekinetics, Oozes) became rosters of
their own: the pre-reshuffle grouping, unchanged in membership, just
under a new `Team` key. A coach may now field a player under either of
two identities. `Team` in `d12ball/game.py` holds all eight, and
`TEAM_PAIRS` (plus the `paired_team()` helper next to it) is the one
source of truth for which color and which species share a hex --
`TEAM_COLORS[Team.FIRE_DEMONS] = TEAM_COLORS[Team.ORANGE]`, and so on,
because Orange *was* Fire Demons' own color before the reshuffle mixed
its roster. `COLOR_TEAMS`/`SPECIES_TEAMS` are the two four-tuples, for
anything that needs the axis rather than the pairing (the team picker's
two button rows, mostly).

Each team's color is still one hex value, defined once as `TEAM_COLORS`
in `d12ball/render.py`, and every place a team's color is drawn -- card
borders, the skill numbers and name on a card, board tokens, the matchup
image's `team_color`, and the coaching image -- reads that dict rather
than carrying a hex value of its own. **No new hexes were added for the
species teams** -- `TEAM_COLORS` fills them in from `TEAM_PAIRS` after
the four color entries, so there is still exactly one hex per color
anywhere in the code.

| Team | Hex |
| --- | --- |
| Orange | `#FFA500` |
| Teal | `#008080` |
| Purple | `#9e4dff` |
| Slime | `#66FF00` |
| Fire Demons | same as Orange |
| Cyborgs | same as Teal |
| Telekinetics | same as Purple |
| Oozes | same as Slime |

- **A team's name for display is `team_display_name(team)`, in
  `d12ball/game.py`, never `team.value.title()`.** `str.title()` doesn't
  turn an underscore into a space -- `"fire_demons".title()` is
  `"Fire_Demons"` -- which was a real, live bug the moment a team's
  value carried one. Every call site that used to write `.value.title()`
  on a `Team` now calls this instead. It lives next to `Team` itself
  rather than in a cog module, because `d12ball/components.py` needs it
  too and cogs import from `d12ball`, never the other way around.
- **A player's team is no longer the player's to carry.**
  `PlayerDefinition` in `d12ball/components.py` has no `team` field --
  dual roster membership is the whole reason for this change, and a
  player belonging to two rosters at once cannot coherently have one
  intrinsic team. `players.json` is a flat `"players"` table (36
  entries: name, role, species, stat_overrides, keyed by id) plus a
  `"teams"` table (8 entries, `{"player_ids": [9 ids]}`) that resolves
  ids into it -- so a dual-membership player's record is written once,
  not twice. `load_player_catalog` builds every `TeamDefinition` from
  the same shared `PlayerDefinition` objects, and `TeamDefinition`'s
  existing "exactly 9 unique players" check is unchanged, holding
  independently for every one of the eight rosters.
  - **`MatchState.team_for_player(player_id)`** is the one answer to
    "which of this player's two rosters is *this match* fielding them
    as" -- checked against `field_players` plus both benches, the same
    roster-membership test used elsewhere in the match logic. Every
    display call site that used to read `player.team` calls this
    instead (`format_role_bracket` and its ~90 callers, the matchup/
    score-attempt `challenge_side` builder, the injury-die render, the
    board's card borders and meeple tokens) -- most already had a
    `match` or `setup` in scope, so this was mechanical at nearly every
    site. Two real bugs surfaced doing this sweep, both silently
    assuming a card's own `.team` always matched whichever side it was
    on, which stopped being true the moment dual membership existed:
    `d12ball/render.py`'s space-occupant stack grouping and
    `cogs/d12ball.py`'s `/ref` command side-detection. Both now check
    board/roster membership directly instead.
  - **A message names a player through `D12Ball.player_label`**, which
    forwards to `RulesEngine.format_player_label`, `format_role_bracket`'s
    body moved onto the engine so it can read both emoji dicts off
    itself (see "The dict lives on the engine" in
    [naming-and-wording.md](naming-and-wording.md), which now covers
    `team_emojis` the same way it always covered `role_emojis`), with
    the team always `match.team_for_player`, since the definition
    cannot answer it. Ninety-odd sites spelled all three out, which put
    the same forty characters of lookup in front of every player's name
    in the codebase and was the whole of why two files carried
    eighty-odd lines past 100 columns. `player_id_label` is the same
    thing for a caller holding a card id rather than a definition.
    `format_role_bracket` itself is still right for a caller with a
    `TeamSetup` rather than a match, which already knows the side.
    Not to be confused with `CoachingView.player_button_label`, which
    is the name on a *button*: the position instead of the team emoji
    (every card in that flow is the clicking coach's own), cut to
    Discord's 80-character limit. The name and role inside both are the
    same string -- see [Naming a player](naming-and-wording.md#naming-a-player).
- **A player's id is `{slug(name)}_{role}`, not team-prefixed.**
  `hellguard_fullback`, globally unique, because a player's own color
  team is no longer part of their identity -- it can't be, when they
  have two. The old scheme was `{old_color}_{slug(name)}`
  (`orange_hellguard`); see the legacy-migration Gotcha below for what
  that means for a game saved under it.
- **A team may not play its own pair, and the reason is the color.**
  `TEAM_COLORS` gives Fire Demons Orange's own `#FFA500`, so that one
  match would draw both sides' cards, meeples and tokens in the same
  color -- and the board is where a coach reads which meeples are
  theirs. `D12BallGame.excluded_teams` (`d12ball/game.py`) drops a
  chosen team's `paired_team()` from the other side's options, the
  same way it already dropped the team itself; the team picker greys
  out by it, `D12BallGame.pick_team` refuses a stale click against it,
  and the AI's draw (`AIStrategy.choose_team`, through
  `GameService.pick_team`) is from `ai_team_pool`, the same reading --
  nobody is holding Dinky's buttons, so that pool is the only check a
  solo game has.
  - **It is not a rule about shared rosters, and must not be rewritten
    as one.** Every other color/species matchup shares players too --
    a color team is 3 of its own species plus **2 of each other**, so
    it overlaps all four species teams and the pairing is only the
    largest of the four. Those matchups are offered and are meant to
    be: the shared players are fielded twice, once a side. See "One
    player, both sides" below.
  - **Enforced at the picker, not in `MatchState` or `D12Ball`.** Every
    path that creates a match reads
    `game.player_1_team`/`player_2_team`, and those are only ever set
    through the picker. Don't add a second enforcement point in the
    data layer: two places checking the same rule is how they drift
    apart. What holds the one place up is
    `test_every_matchup_the_picker_offers_builds_a_match`
    (`tests/test_d12ball_coin_toss.py`), which walks every pair the
    picker will offer and builds the match the coin flip is about to
    build.

- **The team-picking step is now its own screen, not shared with game
  settings.** Eight teams need two rows a side (a color row and a
  species row) where four needed one, which leaves nothing for the
  mode/board-size/AI-opponent buttons that used to share the view.
  Settings moved to their own step -- costing nothing new, since
  `CoinFlipView` already carried them alongside the flip button with
  rows to spare. A normal game's two sides still share one screen,
  whichever human clicks picks their own side; a **test game** (one
  person playing both sides) used to show both sides' rows at once and
  now prompts Player 1 then Player 2 in turn on the same message, each
  getting the full two-row budget rather than splitting it.
- **The `team_*.png` application emoji (`d12ball/images/emoji/`) are a
  second copy of the same colors, and the only one that has to be.**
  (The `role_*.png` beside them are the role badges, uploaded the same
  way and carrying no team colour -- see "Naming a player" in [naming-and-wording.md](naming-and-wording.md).)
  They are uploaded to Discord's Developer Portal separately (see
  `TEAM_EMOJI_NAMES` in `cogs/d12ball_helpers.py`) and shown next to a
  coach's name in chat, so they cannot read `TEAM_COLORS` at request
  time the way a rendered board can. A color change here means
  recoloring the matching PNGs, or the ring-and-letter emoji a coach
  sees stops agreeing with the color the board draws them in. The four
  species emoji share their paired color's ring for the same reason the
  boards do. They carried a letter at first -- **F**ire Demons,
  **C**yborgs, **K** for Telekinetics (Teal already has T), **Z** for
  Oozes (Orange already has O) -- picked to stay distinct from all
  eight teams' initials. `scripts/render_team_emoji.py` now draws that
  species' own silhouette into the ring instead (see "The species
  icons"), tinted to the ring's own colour with `species_icon` -- the
  same shape the player and species cards already carry, so a coach
  reads one icon for "this species" everywhere it appears rather than a
  letter here and a shape everywhere else. The ring's own geometry
  (the margin, the edge width, the face) is measured off the four
  color teams' shipped PNGs rather than invented, so a species emoji
  sits in an identical ring to `team_orange.png`; the four color teams'
  own letters are untouched, and the script only ever writes the four
  species names. `TEAM_EMOJI_FALLBACKS` gives each species team a
  themed unicode emoji (🔥🤖🔮🫧) distinct from the four plain colored
  circles, so the bot reads correctly before a PNG is uploaded --
  which, like the original four, is a manual Developer Portal step
  nothing here can do.
  - **That script writes two cuts of each, and only one of them is
    the bot's.** `team_fire_demons.png` and its three siblings are the
    silhouette alone and are what `TEAM_EMOJI_NAMES` looks up;
    `team_fire_demons_letter.png` and its three are the same ring with
    the species' initial merged into the silhouette. **Nothing in the
    bot reads the lettered four** -- they are uploaded under their own
    names so the application holds both, and switching to them is a
    one-value change in `TEAM_EMOJI_NAMES` rather than a re-upload
    over a name already in use.
  - **A letter's placement on its silhouette is written down, not
    derived**, in `LETTER_PLACEMENTS`. Two of the four sit at the ink's
    own mass centroid, which is what a broad solid shape wants; the
    other two are hand-placed because their art is *built around a
    hole* and a centroid puts the letter straight through it -- the C
    goes inside the cell's bolt cutout, and the K in the channel right
    of the spiral's centre, between where the inner stroke ends and the
    next line out. The Ooze's blob is turned 20 degrees as well, which
    is what lands its two bubbles in the Z's own gaps instead of across
    its strokes.
  - **Each letter overlaps its silhouette slightly, and that is the
    design rather than a tolerance.** A letter held clear of the ink
    reads as hovering over a picture; one that bites into it reads as
    part of one. So the sizes are past the largest that would clear the
    shape -- don't "fix" them back to a clean fit, and don't write a
    test asserting one.
  - **The silhouette is cropped to its own ink first**, where the plain
    set centres the art's whole padded square. That is why the two sets
    fill different fractions of the face (`BADGE_FACE_FRAC` against
    `ICON_FACE_FRAC`) and why the numbers are not interchangeable: one
    is measured against a shape, the other against a shape plus its
    margin.
- **Changing a team's color is `TEAM_COLORS` plus its emoji, and nothing
  else.** No other module should hold a team's hex value of its own --
  that duplication is exactly what let the two drift apart before. A
  species team's color is inherited through `TEAM_PAIRS`, so changing a
  color team's hex moves its species team's color with it for free;
  there is nothing to keep in sync by hand.

## One player, both sides

A player belongs to two rosters -- their color team and their species
team -- so **any color side meets any species side holding 2 or 3 of the
same people**. Those are played as two cards: the same person, in two
kits, exhausted, injured, substituted and sent about independently, and
free to challenge each other. Only the [paired teams](#team-colors) are
refused a fixture, and that is about the color they share, not the
players.

Everything in a match is keyed by a **card id**. It is the catalog
player's own id for the home copy and `duplicate_card_id` -- that id
plus `DUPLICATE_CARD_SUFFIX` -- for the visiting one, both in
`d12ball/components.py`. `catalog_player_id` maps a card id back, and
is a pure function of the string rather than a lookup on the match, so
anything holding a card id can resolve it.

- **Distinct ids are what make the two copies separate players of the
  game**, and that is the whole reason for the scheme. The board, both
  benches, the exhaustion counts, `injured`, the injury queue,
  `assigned_positions`, the shootout orders and every button's
  custom_id go on saying "this player" with one string, exactly as they
  did at four teams. The alternative was making all of them carry a
  side as well.
- **One suffix level is enough and always will be.** Two rosters can
  share a player and a match has two sides, so a third copy has nowhere
  to come from. `TeamDefinition`'s "9 unique players" check holds the
  other half of that up.
- **The visiting side is the one that carries the suffix**, applied in
  `create_standard_setup` through its `duplicate_ids`, which
  `MatchState.standard` fills from `PlayerCatalog.shared_player_ids`.
  Two teams on one axis share nobody, so it is empty for every match
  before the reshuffle and most of them since -- a home side's ids are
  always the catalog's.
- **`PlayerCatalog.player_by_id` hands back a definition carrying the
  card's own id**, not the catalog's. This is load-bearing: some ninety
  call sites resolve a card id to a `PlayerDefinition` and then read the
  id back off it to ask `match.team_for_player(player.player_id)` which
  side the card is on, and a definition answering with the catalog id
  would name the home copy every time -- wrong emoji, wrong color, on
  every message about that player. `player_index` in `d12ball/render.py`
  aliases both forms the same way, since the renderer indexes that dict
  in a dozen places.
  - The two copies are the same person, so they draw the same name,
    role, skills and portrait. **What tells them apart is the team
    color**, which is read off the match -- which is also why the
    paired teams cannot meet.
- **Anything walking a *roster* and asking the match about each player
  has to come through `TeamSetup.card_id_for`**, since a roster is the
  catalog's and a match is keyed by card. `/ref`'s roster listing is the
  one caller today; it was reading meeple positions under catalog ids,
  which for a duplicated visiting side finds the home copy's meeple or
  nothing at all.
- **`tests/roster.py` translates too.** `fielded` and `benched` name a
  player by role off the catalog on purpose -- see "The test suite" in [testing.md](testing.md) --
  so they are exactly the helpers that have to know which id this match
  holds that player under on that side.
- **The way to be sure this is transparent is to force it.** Making
  `MatchState.standard` suffix a visiting side's *whole* roster and
  running the suite puts a duplicate card through every flow the tests
  cover -- maneuvers, run backs, coaching windows, shootouts, saves,
  renders -- rather than only through the ones that thought to build an
  overlapping match. It passed clean when this landed, and it is a
  two-line patch worth re-running after anything that touches ids.

## Player species

A player's species and their team are two different things as of the
2026-08-17 roster reshuffle, where each color team became 3 of its own
associated species plus 2 of each other. `PlayerDefinition.species` in
`d12ball/components.py` carries it, read off a `Species` column by
`scripts/import_d12ball_players.py` the same way `Role` is --
lowercased and validated against a closed set (`EXPECTED_SPECIES`).
`SPECIES_TEAM` in the same script maps each species to its own team key
(`fire_demon -> fire_demons`), the way `Team` already named a color-team
row; add a species to both `EXPECTED_SPECIES` and `SPECIES_TEAM` (and a
color pairing to `TEAM_PAIRS`) together if a fifth is ever themed in --
there is no fifth color to pair it with today.

- **It is optional on load, unlike `role`.** A `players.json` written
  before the column existed still loads -- `load_player_catalog` reads
  it with `.get("species", "")` -- because the file is regenerated
  wholesale by re-running the import rather than migrated in place, and
  nothing forces both developers to have re-imported before pulling a
  commit that reads a new field. An empty species is not a fourth kind
  of species; it means the data predates the column.
- **It is no longer flavor data on its own -- it is what a species
  team's roster is drawn from**, and what the legacy-migration Gotcha
  below reconstructs a pre-reshuffle id from. Nothing about basic-mode
  rules reads it; it decides roster membership, not a mechanic.

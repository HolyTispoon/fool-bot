# Gambits — what is left

**Status: the maneuvers are built.** The six gambits are in
[living-rules.md](living-rules.md) under [Advanced
maneuvers](living-rules.md#advanced-maneuvers), and in the bot behind the game's mode, as of
2026-08-19. This file used to be the worksheet that got them there — every gambit
against every maneuver it could meet, with each assumption named and each undecided cell
marked. **All of that is deleted rather than kept in parallel**, which is what happens to a
worksheet's answered parts: the rules live in one place, and a second copy of a settled rule is
a second thing to keep in step.

Read the living rules for what the cards do. What is below is only what is still open, and none
of it stops a game being played.

---

## The interaction table is in the code, not here

The 6×6 grid the worksheet spent most of its length on collapsed to one sentence the author
gave on 2026-08-18: **"Rank alone decides."** Every gambit sits on a basic card's rank
and beats exactly what that card beats, so the grid is the existing 3×3 cycle repeated four
times and there is nothing to tabulate.

`ManeuverCatalog.resolve` is that, and
`tests/test_d12ball_components.py::test_a_gambit_resolves_exactly_as_its_counterpart`
walks the whole grid asserting that swapping either card for its counterpart cannot change the
outcome. That test is the table now. It is worth more than a table was, because it fails when
the data drifts.

---

## Still open

### The advanced player abilities

The other half of what the author asked for on 2026-08-17. **The data exists since
2026-09-22**: the sheet's `advanced_abilities` tab gives sixteen players an advanced role
ability and three of them advanced skill scores, and `scripts/import_d12ball_players.py`
carries both into `players.json` (`advanced_ability`, `advanced_skills`). What is not built is
the module that plays them -- nothing in the engine reads either field, and the back of a
printed player card (that player's advanced card, the author, 2026-08-12) still repeats the
basic sentence until the author says how it should show them.

A coach playing advanced mode today gets the gambits, the species abilities and the roster
they already know.

### Cross × Intercept may be inert

Intercept's cost removes a High Pass reception's contest, but a Cross that beat it
produces a **set-up**, not a contested reception. There is nothing there to skip, so the cost
does nothing in that one cell. It is written that way deliberately rather than special-cased —
worth a look in play, in case the author wants something else to happen there.

### Judgement calls the build made, worth confirming

It blocked nothing, and it is visible in play:

- **An Intercept with no field left ahead of it is a scoring opportunity** (the author,
  2026-08-19). The build takes that straight to the shot, the way a deflection's overshoot
  does — which skips Intercept's own speed-manipulation step, since there is no run back to
  hang it off. The shot still reads the speed the turnover reset.

(A second call -- Cross's cost as a push back on top of the deflection that beat it -- was
settled on 2026-09-27 and then replaced on 2026-10-03: the card that beats a Cross plays as
itself, and wins any contest it leads to without a roll. See `docs/rules-log.md`.)

---

## What it cost to build

Kept because it is the map of where advanced mode touches the code, and the next person
changing any of it should know these are load-bearing.

- **A maneuver's identity is no longer its printed name.** `match.offense_maneuver` held the
  string `"Low Pass"` and a dozen sites compared against those literals. It holds a **key**
  now (`low_pass`, `double_team`), and `legacy_maneuver_key` translates a game saved before
  that. This was the first step and it shrank every step after it.
- **Relations are by rank, not by name.** `defeats_rank` replaced `defeats`, because each rank
  carries two cards and naming one of them is naming half a relation.
- **The importer stopped validating one die face per side.** A gambit reused its
  counterpart's faces (one face each since 2026-10-03). The die has been off the rules since
  2026-08-17.
- **`pending_effect_continuation`** is what lets an effect reach past its own maneuver: a
  beaten Pinpoint hands the defense a Low Pass once the steal has settled. (Cross used to set
  the speed and *then* pick the pass out, until 2026-10-03.) It also holds a Double Team's
  partner once known, for the rest of that maneuver.
- **`pending_double_team`** carries a won Double Team's partner into the following maneuver,
  where they Merge as an Ooze does (2026-10-03; until then both defenders added their skill
  until a new play). The end of that next maneuver clears it, and a new play sooner.
- **A fourth `new_play=True` call site**: a Cross that finds nobody goes out of play.
  CLAUDE.md used to pin the count at three.
- **One back for all twelve printed cards**, since a coach in advanced mode holds both tiers
  and must not show which they are reading. Each node of the hexagon carries the two cards on
  its rank.

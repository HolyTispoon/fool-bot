# Advanced maneuvers — what is left

**Status: the maneuvers are built.** The six advanced cards are in
[living-rules.md](living-rules.md) under [Advanced
maneuvers](living-rules.md#advanced-maneuvers), and in the bot behind the game's mode, as of
2026-08-19. This file used to be the worksheet that got them there — every advanced maneuver
against every maneuver it could meet, with each assumption named and each undecided cell
marked. **All of that is deleted rather than kept in parallel**, which is what happens to a
worksheet's answered parts: the rules live in one place, and a second copy of a settled rule is
a second thing to keep in step.

Read the living rules for what the cards do. What is below is only what is still open, and none
of it stops a game being played.

---

## The interaction table is in the code, not here

The 6×6 grid the worksheet spent most of its length on collapsed to one sentence the author
gave on 2026-08-18: **"Rank alone decides."** Every advanced card sits on a basic card's rank
and beats exactly what that card beats, so the grid is the existing 3×3 cycle repeated four
times and there is nothing to tabulate.

`ManeuverCatalog.resolve` is that, and
`tests/test_d12ball_advanced_maneuvers.py::test_an_advanced_card_resolves_exactly_as_its_counterpart`
walks the whole grid asserting that swapping either card for its counterpart cannot change the
outcome. That test is the table now. It is worth more than a table was, because it fails when
the data drifts.

---

## Still open

### The three abilities that contradict their card

The sheet's `Interactions` column carries each advanced row's basic counterpart's role
abilities. Three of them contradict the card they sit on, and **none is applied** — each card
resolves without the ability rather than the code guessing at what was meant:

| Card | The ability it carries | Why it does not fit |
| --- | --- | --- |
| **Clear** | Fullback: "Block deflect: ball goes back 2" | Clear goes back 3, so the ability is a *reduction* |
| **Dribble Burst** | Playmaker: "may advance 2" | The burst runs to the goal; 2 is not a bonus |
| **Setup Pass** | Fullback: "High pass up to 4" | A fourth distance against a card that offers 0, 1 and 3 |

The two that do **not** contradict anything are inherited by rank and are live: the
Midfielder's +3 on a skill test, and the ball speed modifier a rank-D2 defense adds. Both only
ever change a skill test, which is why they carry over cleanly.

### The advanced player abilities

The other half of what the author asked for on 2026-08-17, and the half with no data: the
sheet's `Advanced` ability column is empty for all thirty-six players. Nothing can be imported
and nothing can be built until it is filled. It also holds up the back of a printed player
card, which is that player's advanced version (the author, 2026-08-12).

A coach playing advanced mode today gets six cards a side and the roster they already know.

### Setup Pass × Intercept may be inert

Intercept's cost removes a High Pass reception's contest, but a Setup Pass that beat it
produces a **set-up**, not a contested reception. There is nothing there to skip, so the cost
does nothing in that one cell. It is written that way deliberately rather than special-cased —
worth a look in play, in case the author wants something else to happen there.

### Judgement calls the build made, worth confirming

Neither blocked anything, and both are visible in play:

- **An Intercept with no field left ahead of it is a scoring opportunity** (the author,
  2026-08-19). The build takes that straight to the shot, the way a deflection's overshoot
  does — which skips Intercept's own speed-manipulation step, since there is no run back to
  hang it off. The shot still reads the speed the turnover reset.
- **Setup Pass's cost applies after the deflection that beat it**, so the ball goes back 3 (or
  1) and *then* a further 1–3 at the winning coach's choice. Where the deflection already
  overshot into a scoring opportunity, the shot happens and the push-back does not: the ball is
  already as far back as the field goes.

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
- **The importer stopped validating one die face per side.** An advanced card reuses its
  counterpart's faces. The die has been off the rules since 2026-08-17.
- **`pending_effect_continuation`** is what lets an effect reach past its own maneuver. Two do:
  Setup Pass sets the speed and *then* picks the pass out, and a beaten Precise Pass hands the
  defense a Low Pass once the steal has settled. A speed choice had always been the last human
  step of an effect.
- **`pending_double_team`** carries a won Double Team into the following maneuver, where both
  defenders add their defensive skill. A new play clears it, which is the only thing the card
  says ends it.
- **A fourth `new_play=True` call site**: a Setup Pass that finds nobody goes out of play.
  CLAUDE.md used to pin the count at three.
- **One back for all twelve printed cards**, since a coach in advanced mode holds both tiers
  and must not show which they are reading. Each node of the hexagon carries the two cards on
  its rank.

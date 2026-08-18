# Advanced maneuvers — the interaction matrix

**Status: settled enough to build from, and still not a ruleset.** Nothing here is in
[living-rules.md](living-rules.md) yet — a rule reaches that document once it can be stated
once, in the place it belongs. This is the table asked for on 2026-08-17: every advanced
maneuver against every maneuver it can meet, and which cost or benefit applies.

**Every question that blocked the table is answered.** The last of them, on 2026-08-18:

> only an outright win and outright lose of advanced maneuver carry the benefit/cost.

So the matrix has no undecided cells. What is left is listed under
[Still open](#still-open), and none of it holds the table up — it is detail inside three
of the six cards, plus the role abilities, plus asymmetric teams.

The six advanced maneuvers below are the sheet's own text as of 2026-08-18. They are still
**not** imported into `d12ball/data/maneuvers.json`, because the importer cannot read the tab
— see [What this costs in code](#what-this-costs-in-code).

---

## The rule the whole table rests on

**An advanced effect fires only on an outright result.** A maneuver won or lost on the cards
carries its benefit or its cost; a maneuver settled by a **skill test** carries neither, for
either side.

That covers more than the tie. A skill test is also how a maneuver resolves when the
[injured player's disadvantage](living-rules.md#playing-injured) downgrades a decisive win —
and the author confirmed separately that *"the answer does not change when it's forced by an
injury downgrade"*. So:

| The maneuver was settled by | Advanced effects |
| --- | --- |
| The cards, decisively | **the winner's benefit and the loser's cost** |
| A skill test — from a tie, a re-roll, or an injury downgrade | none, either side |
| An injured player's automatic loss of a tie | none — it was a tie on the cards |
| Nobody — the defense sent no challenger | cannot arise; an unchallenged maneuver is basic |

**Twenty-four of the thirty-six pairings are decisive and carry effects. Twelve are ties and
carry none.**

This also retires the problem the drafts had: three of the six costs name the maneuver that
defeated them — a steal, a pressure, a High Pass reception — and could not be read against a
tie. They now only ever fire where the maneuver that beats them actually resolved, which is
exactly what they were written for.

---

## The six cards

| Advanced | Replaces | Rank | On an outright win | On an outright loss |
| --- | --- | --- | --- | --- |
| **Precise Pass** | Low Pass | O1 | Ball to **any** teammate. Ball speed **+3**. | The defender plays an unopposed Low Pass after stealing. |
| **Dribble Burst** | Dribble Advance | O2 | Player and ball go to the **last space of the goal zone they attack**, defenders no obstacle, 1 exhaustion token per space. Then manipulate ball speed up to oSkill. | Possession is lost, and **ball speed is not reset to 1** before the defender manipulates it. |
| **Setup Pass** | High Pass | O3 | Adjust ball speed up to oSkill, **then** set up a scoring opportunity at **0, 1 or 3** spaces, with the speed modifier in its favour. | The defending coach sends the ball back **1, 2 or 3** spaces, where it is **loose**. |
| **Clear** | Block Deflect | D1 | Ball back **3** spaces. Overshoot may set up scoring. Ball speed **−3**. | **2 exhaustion.** |
| **Intercept** | Steal Intercept | D2 | Turnover. Defender and ball move **forward** 1, toward the goal they now attack. The interceptor keeps the ball and does not run back. | The High Pass reception is not contested. |
| **Double Team** | Pressure | D3 | Ball back **2**. The defender **and the teammate closest to where the play started** join, free of exhaustion; and on their **next** maneuver *both* challenge the ball holder, each adding dSkill. Overshoot risks an own goal. | The defender and that teammate each move 1 forward, away from their own goal. |

Two rulings that are **not** in the sheet and live only in the pull request:

- **Setup Pass cannot overshoot.** From the space closest to the goal with no teammate there,
  the pass goes **out**, and the other team gains possession. `0` means a teammate sharing the
  passer's space, so the 2026-08-12 rule that a passer never receives their own pass stands.
- **Intercept keeps the ball and does not run back**, as the basic interceptor does.

### The tab

Twelve rows on the `maneuvers` tab, basic then advanced, with a **`Mode`** column naming the
tier. `Time` now carries the flat costs the 2026-08-16 ruling set — 1 space minute for
everything except High Pass and Setup Pass at 2. `Die value` is still there and is to be
**ignored**.

---

## What is settled

### An advanced maneuver keeps its counterpart's rank

Every advanced row is **identical to its basic counterpart in every column but `Effect`**.
And the author, on whether an advanced card beats a basic one of the same rank: **"Rank alone
decides."**

So the defeat cycle is one cycle, and the hexagon on the back of the maneuver cards keeps
working for both sets.

### Advanced mode adds no new way to win a maneuver

The winner never depends on whether either card was advanced. The 6×6 grid is the existing
3×3 cycle repeated four times — twelve offense wins, twelve defense wins, twelve ties:

| Offense \ Defense | Block Deflect | Clear | Steal Intercept | Intercept | Pressure | Double Team |
| --- | --- | --- | --- | --- | --- | --- |
| **Low Pass** | *skill test* | *skill test* | **defense** | **defense** | **offense** | **offense** |
| **Precise Pass** | *skill test* | *skill test* | **defense** | **defense** | **offense** | **offense** |
| **Dribble Advance** | **offense** | **offense** | *skill test* | *skill test* | **defense** | **defense** |
| **Dribble Burst** | **offense** | **offense** | *skill test* | *skill test* | **defense** | **defense** |
| **High Pass** | **defense** | **defense** | **offense** | **offense** | *skill test* | *skill test* |
| **Setup Pass** | **defense** | **defense** | **offense** | **offense** | *skill test* | *skill test* |

What advanced mode adds is a consequence attached to winning and to losing outright.

### An unchallenged maneuver is always basic

The author: *"Advanced maneuver can only be played when a maneuver is challenged. When a
maneuver is unchallenged, only basic maneuvers can be played."*

This fits the turn as it already runs — all three routes into the unopposed branch settle it
**before** the offense is prompted to pick, so the hand offered is known at the moment it is
offered. It also makes declining a challenge a defensive weapon rather than only a saving:
sending nobody denies the offense their advanced cards.

Two consequences: **the unopposed case is off this matrix entirely**, and the offense needs
two hands drawn — three cards unchallenged, six challenged — where the defense needs only
one, since a defense that sends nobody plays no card at all.

### The costs are effects granted to the opponent

The author, on what currency the extra cost is paid in: *"the answer will be different for
each card. Include possession."*

Only Clear's is paid in something the game already counts. The other five are rules the
**opponent** gets to use — an unopposed Low Pass, a ball driven back and left loose, a
turnover keeping its speed, an uncontested reception, a pair of defenders shoved up the
field.

---

## Where each effect fires

Each advanced card has exactly two matchups where it gains its benefit, two where it pays its
cost, and two ties where nothing happens.

| Advanced card | Gains it, beating | Pays it, beaten by |
| --- | --- | --- |
| **Precise Pass** | Pressure, Double Team | Steal Intercept, Intercept |
| **Dribble Burst** | Block Deflect, Clear | Pressure, Double Team |
| **Setup Pass** | Steal Intercept, Intercept | Block Deflect, Clear |
| **Clear** | High Pass, Setup Pass | Dribble Advance, Dribble Burst |
| **Intercept** | Low Pass, Precise Pass | High Pass, Setup Pass |
| **Double Team** | Dribble Advance, Dribble Burst | Low Pass, Precise Pass |

---

## Every interaction, card by card

### Precise Pass — O1, the advanced Low Pass

| Played against | How it settles | For Precise Pass | For the opposing card |
| --- | --- | --- | --- |
| Block Deflect (D1) | **Tie** — a skill test decides it | *nothing — a skill test carries no effect* | — |
| Clear (D1) | **Tie** — a skill test decides it | *nothing — a skill test carries no effect* | *nothing — a skill test carries no effect* |
| Steal Intercept (D2) | **Steal Intercept** wins | **pays:** the defender plays an unopposed Low Pass after stealing | — |
| Intercept (D2) | **Intercept** wins | **pays:** the defender plays an unopposed Low Pass after stealing | **gains:** turnover, defender and ball **forward** 1 |
| Pressure (D3) | **Precise Pass** wins | **gains:** ball to **any** teammate, speed +3 | — |
| Double Team (D3) | **Precise Pass** wins | **gains:** ball to **any** teammate, speed +3 | **pays:** the defender and that teammate each move 1 forward, away from their own goal |

### Dribble Burst — O2, the advanced Dribble Advance

| Played against | How it settles | For Dribble Burst | For the opposing card |
| --- | --- | --- | --- |
| Block Deflect (D1) | **Dribble Burst** wins | **gains:** carry to the **last space of the attacking goal zone**, a token a space, defenders no obstacle; then manipulate speed up to oSkill | — |
| Clear (D1) | **Dribble Burst** wins | **gains:** carry to the **last space of the attacking goal zone**, a token a space, defenders no obstacle; then manipulate speed up to oSkill | **pays:** **2 exhaustion** |
| Steal Intercept (D2) | **Tie** — a skill test decides it | *nothing — a skill test carries no effect* | — |
| Intercept (D2) | **Tie** — a skill test decides it | *nothing — a skill test carries no effect* | *nothing — a skill test carries no effect* |
| Pressure (D3) | **Pressure** wins | **pays:** possession is lost, and **ball speed is not reset to 1** before the defender manipulates it | — |
| Double Team (D3) | **Double Team** wins | **pays:** possession is lost, and **ball speed is not reset to 1** before the defender manipulates it | **gains:** ball back **2**; the nearest teammate joins free, and on the **next** maneuver both defenders challenge, each adding dSkill |

### Setup Pass — O3, the advanced High Pass

| Played against | How it settles | For Setup Pass | For the opposing card |
| --- | --- | --- | --- |
| Block Deflect (D1) | **Block Deflect** wins | **pays:** the defending coach sends the ball back 1, 2 or 3 spaces, where it is **loose** | — |
| Clear (D1) | **Clear** wins | **pays:** the defending coach sends the ball back 1, 2 or 3 spaces, where it is **loose** | **gains:** ball back **3**, speed −3 |
| Steal Intercept (D2) | **Setup Pass** wins | **gains:** adjust speed up to oSkill, **then** a set-up at 0, 1 or 3 with the speed benefit | — |
| Intercept (D2) | **Setup Pass** wins | **gains:** adjust speed up to oSkill, **then** a set-up at 0, 1 or 3 with the speed benefit | **pays:** the High Pass reception is not contested |
| Pressure (D3) | **Tie** — a skill test decides it | *nothing — a skill test carries no effect* | — |
| Double Team (D3) | **Tie** — a skill test decides it | *nothing — a skill test carries no effect* | *nothing — a skill test carries no effect* |

### Clear — D1, the advanced Block Deflect

| Played against | How it settles | For Clear | For the opposing card |
| --- | --- | --- | --- |
| Low Pass (O1) | **Tie** — a skill test decides it | *nothing — a skill test carries no effect* | — |
| Precise Pass (O1) | **Tie** — a skill test decides it | *nothing — a skill test carries no effect* | *nothing — a skill test carries no effect* |
| Dribble Advance (O2) | **Dribble Advance** wins | **pays:** **2 exhaustion** | — |
| Dribble Burst (O2) | **Dribble Burst** wins | **pays:** **2 exhaustion** | **gains:** carry to the **last space of the attacking goal zone**, a token a space, defenders no obstacle; then manipulate speed up to oSkill |
| High Pass (O3) | **Clear** wins | **gains:** ball back **3**, speed −3 | — |
| Setup Pass (O3) | **Clear** wins | **gains:** ball back **3**, speed −3 | **pays:** the defending coach sends the ball back 1, 2 or 3 spaces, where it is **loose** |

### Intercept — D2, the advanced Steal Intercept

| Played against | How it settles | For Intercept | For the opposing card |
| --- | --- | --- | --- |
| Low Pass (O1) | **Intercept** wins | **gains:** turnover, defender and ball **forward** 1 | — |
| Precise Pass (O1) | **Intercept** wins | **gains:** turnover, defender and ball **forward** 1 | **pays:** the defender plays an unopposed Low Pass after stealing |
| Dribble Advance (O2) | **Tie** — a skill test decides it | *nothing — a skill test carries no effect* | — |
| Dribble Burst (O2) | **Tie** — a skill test decides it | *nothing — a skill test carries no effect* | *nothing — a skill test carries no effect* |
| High Pass (O3) | **High Pass** wins | **pays:** the High Pass reception is not contested | — |
| Setup Pass (O3) | **Setup Pass** wins | **pays:** the High Pass reception is not contested | **gains:** adjust speed up to oSkill, **then** a set-up at 0, 1 or 3 with the speed benefit |

### Double Team — D3, the advanced Pressure

| Played against | How it settles | For Double Team | For the opposing card |
| --- | --- | --- | --- |
| Low Pass (O1) | **Low Pass** wins | **pays:** the defender and that teammate each move 1 forward, away from their own goal | — |
| Precise Pass (O1) | **Precise Pass** wins | **pays:** the defender and that teammate each move 1 forward, away from their own goal | **gains:** ball to **any** teammate, speed +3 |
| Dribble Advance (O2) | **Double Team** wins | **gains:** ball back **2**; the nearest teammate joins free, and on the **next** maneuver both defenders challenge, each adding dSkill | — |
| Dribble Burst (O2) | **Double Team** wins | **gains:** ball back **2**; the nearest teammate joins free, and on the **next** maneuver both defenders challenge, each adding dSkill | **pays:** possession is lost, and **ball speed is not reset to 1** before the defender manipulates it |
| High Pass (O3) | **Tie** — a skill test decides it | *nothing — a skill test carries no effect* | — |
| Setup Pass (O3) | **Tie** — a skill test decides it | *nothing — a skill test carries no effect* | *nothing — a skill test carries no effect* |

---

## The nine advanced-against-advanced pairings

Six are decisive and stack both ways; three are ties and do nothing.

| # | Pairing | Winner | The winner gains | The loser also pays |
| --- | --- | --- | --- | --- |
| 1 | Precise Pass × Clear | **tie** | — | — |
| 2 | Precise Pass × Intercept | Intercept | turnover, forward 1, speed to dSkill | an **unopposed Low Pass** as well |
| 3 | Precise Pass × Double Team | Precise Pass | any teammate, speed +3 | both defenders pushed 1 up the field |
| 4 | Dribble Burst × Clear | Dribble Burst | run to the goal, then speed to oSkill | 2 exhaustion |
| 5 | Dribble Burst × Intercept | **tie** | — | — |
| 6 | Dribble Burst × Double Team | Double Team | back 2, second defender joins, next maneuver double-challenged | possession, at **un-reset speed** |
| 7 | Setup Pass × Clear | Clear | back 3, speed −3, may set up on its overshoot | the ball driven back 1–3 and left loose |
| 8 | Setup Pass × Intercept | Setup Pass | speed to oSkill, then a set-up | High Pass reception uncontested — *possibly inert* |
| 9 | Setup Pass × Double Team | **tie** | — | — |

Two of these are worth watching in play:

- **#6 is the heaviest cell in the game.** The defense takes the ball back two spaces, gains a
  second defender for free, has the next maneuver double-challenged, *and* receives possession
  of a ball still carrying whatever speed the offense pumped into it.
- **#8 may be inert.** Intercept's cost removes a High Pass reception's contest, but the winner
  is a *set-up*, not a contested reception. If there is no contest to skip, nothing happens.

---

## Still open

None of this blocks the table. All of it blocks building a particular card.

- **Dribble Burst's cost borrows machinery its defeaters do not have.** It is beaten by
  Pressure and Double Team; neither turns the ball over by itself, and neither has a
  speed-manipulation step — that is Steal Intercept's. So the cost grants the defense both.
  It is also **the first exception to "every turnover resets ball speed to 1"**, which is a
  flat rule today.
- **Double Team's two-challenger state is new machinery.** One challenger is an assumption
  throughout: `challenger_id` is a single field, the matchup image draws one against one, and
  the skill test adds one defensive skill. What ends the state besides a new play, what
  happens if the ball holder changes, and whether "where the play started" means the ball's
  space at the start of the maneuver or of the play, are all unstated.
- **Setup Pass**: whether a chosen distance landing on an empty space goes out the way the
  last-space case does, or is simply not offered.
- **Intercept**: whether it can run off the end of the field. It moves the new possessor
  *forward*, which the basic card cannot, so an interception with the ball already at that
  side's far end has nowhere to go.
- **Precise Pass** (Q10): how far "any teammate" reaches, whether the passer still moves
  forward 1 across a shared space, and whether the +3 is still capped at speed 12.
- **Clear**: whether the 2 exhaustion goes on the defender who played it.
- **The `Interactions` column** is unchanged, and three entries contradict their card: Clear
  carries "Fullback: ball goes back 2" against a 3-space clearance, Dribble Burst "Playermaker
  may advance 2" against a run to the goal, Setup Pass "Fullback can pass up to 4" against
  0/1/3.
- **Injured players** (Q13) against the advanced effects, beyond the downgrade ruling above.
- **Asymmetric teams**: whether one side may play standard against an asymmetric opponent
  (Q18), whether species abilities crossing team lines is intended, and whether **4-1-1 and
  2-1-3** belong here. Six on the field and nine in a squad are fixed; role *distribution* may
  vary later.

---

## What this costs in code

Two of these are **verified failures with reproductions**, not predictions.

- **The importer refuses the tab.** `scripts/import_d12ball_maneuvers.py` validates that each
  die face is used once per side; the advanced rows reuse their counterparts' faces, so it
  raises `Precise Pass: Die value(s) [1, 2] already used by another offense maneuver` at row
  seven. Retiring that validation is the same change "ignore the die value column" implies —
  it just isn't optional.
- **`ManeuverCatalog.relationships` raises on every advanced card.** It finds what defeats a
  maneuver by searching for an opponent whose `Defeats` names it, and nothing in the data says
  anything defeats Precise Pass, so it raises `StopIteration`. The basic cards still answer,
  but only because the basic defence rows happen to sort first — with six per side each
  relation has **two** members, and the function returns one name per relation. It needs
  widening, and rank is now the rule to widen it to.
- **A maneuver's identity is its display name.** `match.offense_maneuver` holds the string
  `"Low Pass"`, and around ten sites compare against those literals. The advanced cards have
  entirely different names, so a stable identifier separate from the printed name is needed.
- **Six of the twelve effects are new mechanisms.** An unopposed Low Pass granted to the
  defense, a ball driven back and left loose at the defender's choice, a turnover that skips
  the speed reset, an uncontested reception, a pair of defenders shoved up the field, and a
  two-challenger maneuver that persists into the next turn. None exists today.
- **Two effects reach past their own maneuver.** Dribble Burst charges exhaustion by distance,
  which no maneuver does; Double Team's double challenge lands on the *following* turn, which
  nothing does — it needs a persisted field and a rule for when it ends.
- **Setup Pass's failure is nearly free to build.** "Goes out" is the existing out-of-bounds
  outcome — new play, both sides reset, the gaining side picks the ball up. It does become a
  **fourth** `new_play=True` call site, where CLAUDE.md pins the count at three.
- **Intercept's run-back exemption is free.** `begin_run_back` derives it from
  `ball_carrier_id`, so the card only has to name the carrier.
- **Setup Pass's 0 is already computed.** `high_pass_receiver_candidates` is
  `scoring_opportunity_candidates` less the passer, which is exactly "a teammate sharing the
  passer's space".
- **The offense needs two hands drawn.** Three cards unchallenged and six challenged; the
  defense needs only the six. At the current one-row layout a seven-card hand renders each card
  about 75px wide in Discord against 131px today, so the challenged hand wants two rows.
- **`GameMode` is a single enum.** "One or both" makes it two independent switches on the
  saved game record.

# Advanced maneuvers — the interaction matrix

**Status: a worksheet, not a ruleset.** Nothing here is in [living-rules.md](living-rules.md)
— a rule reaches that document only once it is settled and can be stated once. This is the
table asked for on 2026-08-17: every advanced maneuver against every maneuver it can meet,
and which cost or benefit applies.

**Fourteen of the eighteen questions were answered on 2026-08-18**, and their answers are
recorded in place below. What is left is **two decisions** (‡T and ‡C) and **one blank** —
Double Team's cost, which the author has said he will finish.

The six advanced maneuvers are transcribed from the sheet's `maneuvers` tab, where they are
drafts. They have **not** been imported into `d12ball/data/maneuvers.json`, and cannot be
yet: the importer refuses the tab outright (see [What this costs in
code](#what-this-costs-in-code)).

---

## What an advanced maneuver is

From the author, 2026-08-17:

> Each maneuver now has an advanced version that, if it succeeds, is more impactful.
> However, if the maneuver is *defeated*, it has an additional cost.

A coach playing advanced holds **six cards** and picks one secretly each maneuver, as they
pick one of three now — "six cards laid out, as the physical game would have". But **only
when the maneuver is challenged**: against a defense that sends nobody, the offense plays
from the basic three.

---

## The six cards

| Advanced | Replaces | Rank | On success | When defeated |
| --- | --- | --- | --- | --- |
| **Precise Pass** | Low Pass | O1 | Ball to **any** teammate. Ball speed **+3**. | The defender plays an unopposed Low Pass after stealing. |
| **Dribble Burst** | Dribble Advance | O2 | Player and ball go to the **last space of the goal zone they attack**. Defenders in the way do not interrupt. 1 exhaustion token per space at the ordinary rate. The ball comes with them. | The pressured player does not go back with the ball. |
| **Setup Pass** | High Pass | O3 | Sets up a scoring opportunity at **0, 1 or 3** spaces, with the ball speed modifier **in its favour**. 0 means a teammate sharing the passer's space. **Cannot overshoot** — from the space closest to the goal with no teammate, the pass goes **out** and the other team gains possession. | The other team may set up a scoring opportunity after the resolution. |
| **Clear** | Block Deflect | D1 | Ball moves back **3** spaces. Overshoot may set up scoring. Ball speed **−3**. | Add exhaustion. *(How much is not stated — see [Q7](#answered).)* |
| **Intercept** | Steal Intercept | D2 | Turnover. Defender and ball move **forward** 1 — toward the goal they now attack. The interceptor keeps the ball and does not run back. | The High Pass reception is not contested. |
| **Double Team** | Pressure | D3 | Ball back **2**. A second defender **joins the space for free**, adding dSkill to a skill test — which is the only place it applies. Overshoot risks an own goal. | **Not yet written.** The author: *"I will complete this in due time."* |

### The tab

Six new rows on the existing `maneuvers` tab, twelve in all, basic then advanced, with a
**`Mode`** column saying which is which. The author has since fixed the `Time` column (it
was still carrying the distance-based costs the 2026-08-16 flat-cost ruling replaced) and
added the `Mode` header. `Die value` stays in the sheet and is to be **ignored**.

---

## What is settled

### An advanced maneuver keeps its counterpart's rank

Every advanced row is **identical to its basic counterpart in every column but `Effect`** —
same `Type`, `Rank`, `Defeats`, `Defeated by`, `Die value`. And the author, on whether an
advanced card beats a basic one of the same rank: **"Rank alone decides."**

So the defeat cycle is one cycle, and the hexagon on the back of the maneuver cards keeps
working for both sets.

### Advanced mode adds no new way to win a maneuver

Because rank is preserved, **the winner never depends on whether either card was advanced.**
The 6×6 grid is the existing 3×3 cycle repeated four times — twelve offense wins, twelve
defense wins, twelve ties:

| Offense \ Defense | Block Deflect | Clear | Steal Intercept | Intercept | Pressure | Double Team |
| --- | --- | --- | --- | --- | --- | --- |
| **Low Pass** | skill test | skill test | **defense** | **defense** | **offense** | **offense** |
| **Precise Pass** | skill test | skill test | **defense** | **defense** | **offense** | **offense** |
| **Dribble Advance** | **offense** | **offense** | skill test | skill test | **defense** | **defense** |
| **Dribble Burst** | **offense** | **offense** | skill test | skill test | **defense** | **defense** |
| **High Pass** | **defense** | **defense** | **offense** | **offense** | skill test | skill test |
| **Setup Pass** | **defense** | **defense** | **offense** | **offense** | skill test | skill test |

What advanced mode adds is a consequence attached to winning and to losing. The thirty-six
pairings collapse to nine outcomes plus a bonus/cost overlay, and everything below is that
overlay.

### An unchallenged maneuver is always basic

The author: *"Advanced maneuver can only be played when a maneuver is challenged. When a
maneuver is unchallenged, only basic maneuvers can be played."*

This fits the turn as it already runs — all three routes into the unopposed branch settle it
**before** the offense is prompted to pick, so the hand offered is known at the moment it is
offered. It also makes declining a challenge a defensive weapon rather than only a saving:
sending nobody denies the offense their advanced cards.

Two consequences: **the unopposed case is off this matrix entirely**, and the offense needs
two hands drawn (three cards unchallenged, six challenged) where the defense needs only one,
since a defense that sends nobody plays no card at all.

### The costs are effects granted to the opponent, and possession is one of them

The author, on what currency the extra cost is paid in: *"the answer will be different for
each card. Include possession."*

Only Clear's cost is paid in something the game already counts. The other four written costs
are rules the **opponent** gets to use, and possession being an available currency is what
makes Setup Pass's readable — a scoring opportunity needs a ball to shoot, and neither of its
defeaters turns one over by itself.

---

## The two lists

Asked for directly, on 2026-08-18: *"I need to see a list of all cases where an advanced
maneuver loses — either by winning outright or through a skill test — and consider the
possible costs for each of these situations. AND I need to see a list of all the cases where
the winning maneuver has a benefit because advanced as well."*

### Where an advanced card loses

Each has exactly four: the card that beats it, basic and advanced, and losing the skill test
at its own rank, basic and advanced.

| Advanced card | Cost as drafted | Loses outright to | Reads? | Tie-loss to | Reads? |
| --- | --- | --- | --- | --- | --- |
| **Precise Pass** | the defender plays an unopposed Low Pass after stealing | Steal Intercept, Intercept | ✅ | Block Deflect, Clear | ❌ nothing was stolen |
| **Dribble Burst** | the pressured player does not go back with the ball | Pressure, Double Team | ✅ | Steal Intercept, Intercept | ❌ nobody was pressured |
| **Setup Pass** | the other team may set up a scoring opportunity | Block Deflect, Clear | ✅ | Pressure, Double Team | ✅ |
| **Clear** | add exhaustion *(amount unstated)* | Dribble Advance, Dribble Burst | ✅ | Low Pass, Precise Pass | ✅ |
| **Intercept** | the High Pass reception is not contested | High Pass, Setup Pass | ✅ | Dribble Advance, Dribble Burst | ❌ there was no High Pass |
| **Double Team** | *draft cut off* | Low Pass, Precise Pass | ❓ | High Pass, Setup Pass | ❓ |

**Only Clear's cost survives all four**, and the three failures break for one structural
reason: each names a mechanic that only its decisive defeater performs.

### Where an advanced card wins

| Advanced card | Benefit | Beats outright | Wins the tie against ‡T |
| --- | --- | --- | --- |
| **Precise Pass** | ball to **any** teammate, speed +3 | Pressure, Double Team | Block Deflect, Clear |
| **Dribble Burst** | carry to the **last space of the attacking goal zone**, a token a space, defenders no obstacle | Block Deflect, Clear | Steal Intercept, Intercept |
| **Setup Pass** | a set-up at **0, 1 or 3**, ball speed in its favour | Steal Intercept, Intercept | Pressure, Double Team |
| **Clear** | ball back **3**, speed −3 | High Pass, Setup Pass | Low Pass, Precise Pass |
| **Intercept** | turnover, defender and ball **forward** 1 | Low Pass, Precise Pass | Dribble Advance, Dribble Burst |
| **Double Team** | ball back **2**, a second defender joins free (+dSkill on a test) | Dribble Advance, Dribble Burst | High Pass, Setup Pass |

### Why the two lists are not the same shape

**A benefit is context-free.** Each is one effect that fires identically whichever opponent
it beat, so it would read perfectly well on a skill-test win.

**A cost is context-bound.** Three of the five are written against the maneuver that
defeated them, and break when a same-rank skill test settles it instead.

So the argument for excluding skill tests is a symmetry argument, not a claim about the
benefit: the benefit would survive being won on a test; the cost would not, and taking one
without the other makes an advanced card safer to play into a tie than into a losing
matchup.

Three benefits change character sharply if a coin flip can win them — **Dribble Burst** (a
free run at the goal), **Setup Pass** (a shot out of turn) and **Intercept** (a turnover plus
ground).

---

## Every interaction, card by card

| Marker | The question |
| --- | --- |
| ‡T | Does a skill test count as winning or losing? — [Q3](#q3-does-losing-a-skill-test-count-as-being-defeated) |
| ‡C | Do a winner's bonus and a loser's cost both apply? — [Q5](#q5-do-both-sides-effects-apply-at-once) |

### Precise Pass — O1, the advanced Low Pass

| Played against | How it settles | For Precise Pass | For the opposing card |
| --- | --- | --- | --- |
| Block Deflect (D1) | **Tie** — a skill test decides | bonus if won. If lost, the cost names *Steal Intercept*, which has not happened ‡T | — |
| Clear (D1) | **Tie** — a skill test decides | bonus if won. If lost, the cost names *Steal Intercept*, which has not happened ‡T | the same from their end ‡T |
| Steal Intercept (D2) | **Steal Intercept** wins | **pays:** the defender plays an unopposed Low Pass after stealing | — |
| Intercept (D2) | **Intercept** wins | **pays:** the defender plays an unopposed Low Pass after stealing | **bonus:** turnover, defender and ball **forward** 1 |
| Pressure (D3) | **Precise Pass** wins | **bonus applies** | — |
| Double Team (D3) | **Precise Pass** wins | **bonus applies** | **pays:** *draft cut off* ‡C |

### Dribble Burst — O2, the advanced Dribble Advance

| Played against | How it settles | For Dribble Burst | For the opposing card |
| --- | --- | --- | --- |
| Block Deflect (D1) | **Dribble Burst** wins | **bonus applies** | — |
| Clear (D1) | **Dribble Burst** wins | **bonus applies** | **pays:** add exhaustion *(amount unstated)* ‡C |
| Steal Intercept (D2) | **Tie** — a skill test decides | bonus if won. If lost, the cost names *Pressure*, which has not happened ‡T | — |
| Intercept (D2) | **Tie** — a skill test decides | bonus if won. If lost, the cost names *Pressure*, which has not happened ‡T | the same from their end ‡T |
| Pressure (D3) | **Pressure** wins | **pays:** the pressured player does not go back with the ball | — |
| Double Team (D3) | **Double Team** wins | **pays:** the pressured player does not go back with the ball | **bonus:** ball back **2**, a second defender joins free (+dSkill on a test) |

### Setup Pass — O3, the advanced High Pass

| Played against | How it settles | For Setup Pass | For the opposing card |
| --- | --- | --- | --- |
| Block Deflect (D1) | **Block Deflect** wins | **pays:** the other team may set up a scoring opportunity | — |
| Clear (D1) | **Clear** wins | **pays:** the other team may set up a scoring opportunity | **bonus:** ball back **3**, speed −3 |
| Steal Intercept (D2) | **Setup Pass** wins | **bonus applies** | — |
| Intercept (D2) | **Setup Pass** wins | **bonus applies** | **pays:** the High Pass reception is not contested ‡C |
| Pressure (D3) | **Tie** — a skill test decides | bonus if won, cost if lost ‡T | — |
| Double Team (D3) | **Tie** — a skill test decides | bonus if won, cost if lost ‡T | the same from their end ‡T |

### Clear — D1, the advanced Block Deflect

| Played against | How it settles | For Clear | For the opposing card |
| --- | --- | --- | --- |
| Low Pass (O1) | **Tie** — a skill test decides | bonus if won, cost if lost ‡T | — |
| Precise Pass (O1) | **Tie** — a skill test decides | bonus if won, cost if lost ‡T | the same from their end ‡T |
| Dribble Advance (O2) | **Dribble Advance** wins | **pays:** add exhaustion *(amount unstated)* | — |
| Dribble Burst (O2) | **Dribble Burst** wins | **pays:** add exhaustion *(amount unstated)* | **bonus:** carry to the **last space of the attacking goal zone**, a token a space, defenders no obstacle |
| High Pass (O3) | **Clear** wins | **bonus applies** | — |
| Setup Pass (O3) | **Clear** wins | **bonus applies** | **pays:** the other team may set up a scoring opportunity ‡C |

### Intercept — D2, the advanced Steal Intercept

| Played against | How it settles | For Intercept | For the opposing card |
| --- | --- | --- | --- |
| Low Pass (O1) | **Intercept** wins | **bonus applies** | — |
| Precise Pass (O1) | **Intercept** wins | **bonus applies** | **pays:** the defender plays an unopposed Low Pass after stealing ‡C |
| Dribble Advance (O2) | **Tie** — a skill test decides | bonus if won. If lost, the cost names *High Pass*, which has not happened ‡T | — |
| Dribble Burst (O2) | **Tie** — a skill test decides | bonus if won. If lost, the cost names *High Pass*, which has not happened ‡T | the same from their end ‡T |
| High Pass (O3) | **High Pass** wins | **pays:** the High Pass reception is not contested | — |
| Setup Pass (O3) | **Setup Pass** wins | **pays:** the High Pass reception is not contested | **bonus:** a set-up at **0, 1 or 3**, ball speed in its favour |

### Double Team — D3, the advanced Pressure

| Played against | How it settles | For Double Team | For the opposing card |
| --- | --- | --- | --- |
| Low Pass (O1) | **Low Pass** wins | **pays:** *draft cut off* | — |
| Precise Pass (O1) | **Precise Pass** wins | **pays:** *draft cut off* | **bonus:** ball to **any** teammate, speed +3 |
| Dribble Advance (O2) | **Double Team** wins | **bonus applies** | — |
| Dribble Burst (O2) | **Double Team** wins | **bonus applies** | **pays:** the pressured player does not go back with the ball ‡C |
| High Pass (O3) | **Tie** — a skill test decides | bonus if won, cost if lost ‡T | — |
| Setup Pass (O3) | **Tie** — a skill test decides | bonus if won, cost if lost ‡T | the same from their end ‡T |

---

## The nine advanced-against-advanced pairings

Where both coaches played an advanced card, and effects can land on both sides at once.

| # | Pairing | Winner | The winner gets | The loser also pays |
| --- | --- | --- | --- | --- |
| 1 | Precise Pass × Clear | **tie** | — ‡T | — ‡T |
| 2 | Precise Pass × Intercept | Intercept | turnover, forward 1, speed to dSkill | an **unopposed Low Pass** as well |
| 3 | Precise Pass × Double Team | Precise Pass | any teammate, speed +3 | ❓ *draft cut off* |
| 4 | Dribble Burst × Clear | Dribble Burst | run to the goal | defense gains exhaustion |
| 5 | Dribble Burst × Intercept | **tie** | — ‡T | — ‡T |
| 6 | Dribble Burst × Double Team | Double Team | back 2, second defender free | handler retreats **without the ball** |
| 7 | Setup Pass × Clear | Clear | back 3, speed −3, may set up on the overshoot | **a second set-up** for the defense |
| 8 | Setup Pass × Intercept | Setup Pass | a set-up at 0, 1 or 3 | High Pass reception uncontested — *possibly inert* |
| 9 | Setup Pass × Double Team | **tie** | — ‡T | — ‡T |

Four things fall out of it:

- **‡T and ‡C are coupled.** If a skill test neither earns nor charges, three of these nine
  are ordinary maneuvers and advanced-against-advanced stacks in **six** cells, not nine.
  Deciding ‡C before ‡T risks re-deciding it.
- **#2 is the largest single event in the game as drafted.** The defense takes the turnover,
  gains a space *forward* where the basic steal concedes one, changes the speed, and then
  plays a free Low Pass — two maneuvers from one card.
- **#8 may be inert.** Intercept's cost removes a High Pass reception's contest, but the
  winner is a *set-up*, not a contested reception. If there is no contest to skip, nothing
  happens.
- **#7 stacks two set-ups** — one off Clear's own overshoot, one off Setup Pass's cost.

---

## The outcome ladder

A maneuver turn does not land in "won" or "lost". Row 1 is now off the table entirely: an
unchallenged maneuver is always basic.

| # | How the turn landed | Whose maneuver resolves | Bonus? | Cost? |
| --- | --- | --- | --- | --- |
| ~~1~~ | ~~Unopposed~~ | — | **cannot happen** — an unchallenged maneuver is basic | — |
| 2 | **Decisive on the cards** | the higher-ranked | **yes**, to the winner | **yes**, to the loser — every draft is written for this case |
| 3 | **Tie → skill test** | the test's winner | ‡T | ‡T, and three of the six costs cannot be read here |
| 4 | **Tie re-rolled** (another token each) | settled by the re-roll | as row 3 | as row 3 |
| 5 | **Injury downgrade** — a decisive win owed to an injured player becomes a test they must win — **won** | the injured player's | ‡T | ‡T |
| 6 | Same, **lost** | their opponent's | ‡T | ‡T |
| 7 | **Injured tie** — lost automatically with nothing rolled | the healthy player's | ‡T | ‡T |
| 8 | **Both injured in a tie** — an ordinary tie | as row 3 | as row 3 | as row 3 |

Rows 5 to 7 used to carry a marker of their own. The author has since settled it: *"the
answer does not change when it's forced by an injury downgrade"* — so they follow ‡T rather
than needing an answer apiece.

**One thing ‡T must be worded carefully to avoid breaking.** Double Team's benefit is the
second defender's +dSkill, which applies *only* on a skill test — so a rule reading "no
advanced effect on a skill test" would erase it. The distinction that keeps both answers
standing is between an effect **awarded for winning** and a modifier **applied while
resolving**: the second defender joins as part of playing the card, the way a Midfielder's
+3 and the ball speed modifier already do, neither of which is contingent on the outcome.

---

## Answered

Recorded in the numbering the pull-request threads use, so a reference to "Q9" keeps meaning
the same thing.

- **Q1 — how the choice is made.** A hand of six, picked per turn: *"I am imagining six cards
  laid out, as would the physical game would have."*
- **Q2 — advanced against basic of the same rank.** *"Rank alone decides."*
- **Q4 — the unopposed case.** Advanced cards may only be played when challenged.
- **Q6 — Double Team, partly.** The second defender's movement is **free**, and is *"relevant
  to skill tests only"*. The cost is still to be written.
- **Q7 — the currency.** Different for each card, and **possession is one of them**.
- **Q8 — Setup Pass.** 0 means a teammate sharing the passer's space; ball speed counts *for*
  the shot; it **cannot overshoot**, and from the closest space with no teammate the pass
  goes out and the other team gains possession.
- **Q9 — Intercept's direction.** Forward, toward the goal they now attack; the interceptor
  keeps the ball and does not run back.
- **Q11 — Dribble Burst.** The last space of the attacking goal zone; defenders do not
  interrupt; one token per space at the ordinary rate; the ball comes along.
- **Q12 — the `Interactions` column.** *"These interactions need updating. they were true for
  the basic maneuver but not necessarily for advanced ones."* What they become is still open.
- **Q15 — the sheet.** `Time` fixed, `Die value` to be ignored, `Mode` header added.
- **Q16 / Q17 — asymmetric teams.** Six on the field always; nine in a squad and three benched
  for now; role **abilities** change and the **distribution** of roles may change later; each
  **species** gets an ability shared by all its players; each player gets a modified version
  of their role ability.

### What Q11 costs a player

Worth recording next to the ruling, because the numbers are large. The boards are 2/2/2,
2/3/2 and 3/3/3, so the longest run is one less than the board size:

| Board | Longest run | Tokens | Exhausts |
| --- | --- | --- | --- |
| 6 | 5 | 5 | defensive skill ≤ 4 |
| 7 | 6 | 6 | defensive skill ≤ 5 |
| 9 | 8 | 8 | **every player in the game** — the highest defensive skill is 6 |

The cost is **deferred**: a score attempt causes no injury check, so the shot this sets up is
free, and the bill arrives at the player's next skill test, where safety is a d12 strictly
above their token count — 8 tokens is a **two-in-three** chance of injury. The payoff is
immediate and certain: they finish on the last space of the zone they attack, holding the
ball, with no space between them and the goal for a defender to stand in.

### What Q17 changes

Advanced mode's team half has three layers, and only one of them is team-shaped:

| Layer | Scope | Where it lives |
| --- | --- | --- |
| Species ability | every player of a species, **across all four teams** | nothing exists yet |
| Modified role ability | per player | the empty `Advanced` column |
| Role distribution | per team | changes the deal and the setups |

The middle and last are what "asymmetric teams" suggests. The first is not: after the
2026-08-17 reshuffle every team is three of its own species plus two of each other, so a
side's nine span all four species and the six they field carry a **mix** of species
abilities that changes with every substitution.

It also gives the back of a printed player card a definition for the first time — a modified
role ability plus a species ability — which is what has been holding those prints to one
side.

---

## Still open

### The two decisions

#### Q3: Does losing a skill test count as being defeated?

The injury-downgrade half is settled (rows 5 to 7 follow whatever this answer is). What is
left is the tie. See [the two lists](#the-two-lists): only Clear's cost survives a tie, and
the evidence points at **"defeated" meaning the maneuver that beats it resolved**. The
alternative is three more clauses, one per card whose cost names its defeater.

#### Q5: Do both sides' effects apply at once?

[The nine pairings](#the-nine-advanced-against-advanced-pairings). Worth deciding after Q3,
since Q3 removes three of the nine from consideration.

### The blank

**Double Team's cost.** Two cells of the grid cannot be evaluated without it.

### Not yet asked or answered

- **Q10 — Precise Pass.** How far does "any teammate" reach — the whole field, past anyone in
  the way? Does the passer still move forward 1 on a shared-space pass, and is the +3 still
  capped at speed 12?
- **Q13 — injured players** against the advanced effects, and whether a cost stacks on the
  [injury check](living-rules.md#the-injury-check) a skill test already owes.
- **Q14 — does the cycle hold advanced against advanced?** The sheet's `Defeats` column names
  only basic maneuvers. Reading it by rank is what makes this grid resolvable, and it is an
  inference rather than a statement. **This one now has teeth** — see below.
- **Q18 — may one side play standard** against an asymmetric opponent?
- **Q12's replacement text**, and whether a distance landing on an empty space is dropped
  from Setup Pass's menu or goes out like the last-space case.
- **Whether Intercept can run off the field.** It moves the new possessor *forward*, which
  the basic card cannot do, so an interception with the ball already at that side's far end
  has nowhere to go. The same shape as the Setup Pass case, and rare in the same way.

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
  widening, not patching. This is [Q14](#still-open) with consequences.
- **A maneuver's identity is its display name.** `match.offense_maneuver` holds the string
  `"Low Pass"`, and around ten sites compare against those literals — the effect dispatch
  table, the Midfielder's +3, the ball speed modifier a Steal Intercept adds, the turnover
  check. The advanced cards have entirely different names, so a stable identifier separate
  from the printed name is needed whatever else is decided.
- **Four of the six costs are new mechanisms.** An unopposed Low Pass granted to the defense,
  a set-up granted to the other team, a Pressure that leaves the ball behind, a High Pass
  reception that skips its contest. None exists today.
- **Two effects reach past their own maneuver.** Dribble Burst charges exhaustion by distance,
  which no maneuver does; Double Team moves a *second* defender onto the space and adds their
  skill to a test, which nothing in the game does.
- **Setup Pass's failure is nearly free to build.** "Goes out" is the existing out-of-bounds
  outcome — new play, both sides reset, the gaining side picks the ball up at a token a space.
  It does become a **fourth** `new_play=True` call site, where CLAUDE.md currently pins the
  count at three.
- **Intercept's run-back exemption is free.** `begin_run_back` derives it from
  `ball_carrier_id` rather than taking it as an argument, so the card only has to name the
  carrier.
- **Setup Pass's 0 is already computed.** `high_pass_receiver_candidates` is
  `scoring_opportunity_candidates` less the passer — teammates on the ball's space, excluding
  whoever threw it, which is exactly what "0 means a teammate sharing the passer's space"
  asks for.
- **The offense needs two hands drawn.** Three cards unchallenged and six challenged; the
  defense needs only the six. At the current one-row layout a seven-card hand renders each
  card about 75px wide in Discord against 131px today, so the challenged hand wants two rows.
- **`GameMode` is a single enum.** "One or both" makes it two independent switches on the
  saved game record.

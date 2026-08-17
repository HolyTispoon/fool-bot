# Advanced maneuvers — the interaction matrix

**Status: a worksheet, not a rule.** Nothing here has been played, and nothing here is in
[living-rules.md](living-rules.md) — a rule reaches that document only once the author has
settled it. This is the table asked for on 2026-08-17: every advanced maneuver against
every maneuver it can meet, and which cost or benefit applies in each case.

The six advanced maneuvers are transcribed below from the sheet's `maneuvers` tab, where
they are drafts. They have **not** been imported into `d12ball/data/maneuvers.json`, and
until the questions at the foot of this document are answered they should not be — several
of them cannot be applied as written.

Cells that depend on a ruling are marked with its symbol (‡T, ‡U, ‡C, ‡I) rather than
filled in with a guess.

---

## What an advanced maneuver is

From the author, 2026-08-17:

> Each maneuver now has an advanced version that, if it succeeds, is more impactful.
> However, if the maneuver is *defeated*, it has an additional cost.

So each card carries two things the basic version does not: an **upside on success** and a
**penalty on defeat**. The matrix exists because "succeeds" and "defeated" are not two
outcomes in this game — a maneuver turn lands in one of eight states, and only two of them
are unambiguous.

---

## The six cards

Transcribed from the `maneuvers` tab. The wording is the sheet's, lightly punctuated; the
last column is what each draft says happens when the card is defeated.

| Advanced | Replaces | Rank | On success | When defeated |
| --- | --- | --- | --- | --- |
| **Precise Pass** | Low Pass | O1 | Ball to **any** teammate. Ball speed **+3**. | The defender may play an unopposed Low Pass after stealing. |
| **Dribble Burst** | Dribble Advance | O2 | Player and ball move forward **all the way to the goal**, gaining exhaustion for the distance travelled. Manipulate ball speed up to oSkill. | The pressured player does not go back with the ball. |
| **Setup Pass** | High Pass | O3 | Set up a scoring opportunity at distance **0, 1 or 3**, with the ball speed benefit. | The other team may set up a scoring opportunity after the resolution. |
| **Clear** | Block Deflect | D1 | Ball moves back **3** spaces. Overshoot may set up scoring. Ball speed **−3**. | Add exhaustion. |
| **Intercept** | Steal Intercept | D2 | Turnover. Defender and ball move **forward** 1 space. Manipulate ball speed up to dSkill. | The High Pass reception is not contested. |
| **Double Team** | Pressure | D3 | Player and ball go back **2** spaces. Defender moves 1 forward, and **another teammate may join the space for free**, adding dSkill to a skill test. Overshoot risks an own goal. | *The draft is cut off — the sentence ends at "If defeated".* |

### What the tab looks like

Worth recording, because it is what an importer has to read. The advanced maneuvers are
**six new rows on the existing tab**, not new columns, and the tab has grown three columns
since it was last imported:

- an **unnamed tier column** (`Column 10` in the HTML export) holding `Basic` or `Advanced`;
- **`Defeated by`**, which the importer currently derives rather than reads;
- **`Interactions`**, which lists the role abilities touching that maneuver — something
  `d12ball/cards.py` currently derives by matching each role's ability sentence against the
  maneuver's name.

---

## What the drafts settle, and what they change

### A1 is confirmed by the data: an advanced maneuver keeps its counterpart's rank

Each advanced row is **identical to its basic counterpart in every column but `Effect`** —
same `Type`, `Rank`, `Defeats`, `Defeated by`, `Die value`, `Time` and `Interactions`.
Precise Pass is O1: it beats Pressure, loses to Steal Intercept, ties with Block Deflect,
exactly as Low Pass does.

So the defeat cycle is one cycle, and the hexagon on the back of the maneuver cards keeps
working for both sets. This was the assumption the whole grid rested on, and it is now
upstream's rather than mine.

### The consequence: advanced mode adds no new way to win a maneuver

Because rank is preserved, **the winner of a maneuver never depends on whether either card
was advanced.** The 6×6 grid is the existing 3×3 cycle repeated four times:

| Offense \ Defense | Block Deflect | Clear | Steal Intercept | Intercept | Pressure | Double Team |
| --- | --- | --- | --- | --- | --- | --- |
| **Low Pass** | skill test | skill test | defense | defense | offense | offense |
| **Precise Pass** | skill test | skill test | defense | defense | offense | offense |
| **Dribble Advance** | offense | offense | skill test | skill test | defense | defense |
| **Dribble Burst** | offense | offense | skill test | skill test | defense | defense |
| **High Pass** | defense | defense | offense | offense | skill test | skill test |
| **Setup Pass** | defense | defense | offense | offense | skill test | skill test |

Thirty-six pairings, nine outcomes, and a bonus/cost overlay on top. Everything below is
that overlay.

One thing the sheet does *not* say: `Defeats` and `Defeated by` name only the **basic**
maneuvers. Precise Pass "loses to Steal Intercept" — not "to Steal Intercept or Intercept".
Reading the cycle by rank is what makes advanced-against-advanced resolvable at all, and it
is an inference rather than a statement ([Q14](#q14-does-the-cycle-hold-advanced-against-advanced)).

### The costs are not a currency — they are effects granted to the opponent

This is the largest thing the drafts change about the shape of the question. Only one of
the six ("Clear: add exhaustion") is a cost paid in something the game already counts. The
other four that are written are **rules the opponent gets to use**:

- *Precise Pass* — the defender may play an unopposed Low Pass after stealing.
- *Dribble Burst* — the pressured player does not go back with the ball.
- *Setup Pass* — the other team may set up a scoring opportunity.
- *Intercept* — the High Pass reception is not contested.

So there is no single "what currency is the extra cost in" to answer; each card is its own
mechanism. That is a bigger build than a shared penalty would have been, and it is worth
knowing now rather than at stage four.

### Three of the six costs name the maneuver that defeated them

An advanced card is defeated in two different ways: **outright**, by the one maneuver a rank
below it, or by **losing a skill test** to the maneuver of its own rank. The drafts were
written for the first, and three of them cannot be read against the second:

| Card | Cost as drafted | Defeated outright by | Same-rank tie against | Does the cost read? |
| --- | --- | --- | --- | --- |
| Precise Pass | "…after **stealing**" | Steal Intercept / Intercept | Block Deflect / Clear | **No** — a Block Deflect steals nothing |
| Dribble Burst | "the **pressured** player…" | Pressure / Double Team | Steal Intercept / Intercept | **No** — nobody was pressured |
| Intercept | "the **High Pass** reception…" | High Pass / Setup Pass | Low Pass / Precise Pass | **No** — there was no High Pass |
| Setup Pass | "the other team may set up…" | Block Deflect / Clear | Pressure / Double Team | Yes, as written |
| Clear | "add exhaustion" | Dribble Advance / Dribble Burst | High Pass / Setup Pass | Yes, as written |
| Double Team | *(cut off)* | Low Pass / Precise Pass | Dribble Advance / Dribble Burst | — |

That is strong evidence for a particular answer to [Q3](#q3-does-losing-a-skill-test-count-as-being-defeated):
**a card is "defeated" only when the maneuver that beats it resolves, and losing a skill
test is not that.** It needs confirming, because the alternative is that each of the three
needs a second clause written for its tie.

---

## Every interaction, card by card

Six tables, one per advanced card, listing every card it can be played against — basic and
advanced — plus the case where no maneuver is played against it at all.

| Marker | The question |
| --- | --- |
| ‡T | Does losing a skill test count as being defeated? — [Q3](#q3-does-losing-a-skill-test-count-as-being-defeated) |
| ‡U | Does an unopposed maneuver earn its bonus? — [Q4](#q4-does-an-unopposed-maneuver-earn-its-bonus) |
| ‡C | Do a winner's bonus and a loser's cost both apply? — [Q5](#q5-do-both-sides-effects-apply-at-once) |

### Precise Pass — O1, the advanced Low Pass

**On success:** ball to **any** teammate, speed +3. **When defeated:** the defender may play an unopposed Low Pass after stealing.

| Played against | How it settles | What Precise Pass gets or pays | What the opposing card gets or pays |
| --- | --- | --- | --- |
| Block Deflect (D1) | **Tie** — a skill test decides | bonus if won. If lost, the cost as drafted names *Steal Intercept*, which has not happened ‡T | — |
| Clear (D1) | **Tie** — a skill test decides | bonus if won. If lost, the cost as drafted names *Steal Intercept*, which has not happened ‡T | the same from their end ‡T |
| Steal Intercept (D2) | **Steal Intercept** wins outright | **pays:** the defender may play an unopposed Low Pass after stealing | — |
| Intercept (D2) | **Intercept** wins outright | **pays:** the defender may play an unopposed Low Pass after stealing | **bonus:** turnover, and defender and ball move **forward** 1 |
| Pressure (D3) | **Precise Pass** wins outright | **bonus applies** | — |
| Double Team (D3) | **Precise Pass** wins outright | **bonus applies** | **pays:** **the draft is cut off — nothing is stated** ‡C |
| *no challenger sent* | **Precise Pass** succeeds unopposed | bonus? ‡U | — |

### Dribble Burst — O2, the advanced Dribble Advance

**On success:** carry the ball **all the way to the goal**, a token a space. **When defeated:** the pressured player does not go back with the ball.

| Played against | How it settles | What Dribble Burst gets or pays | What the opposing card gets or pays |
| --- | --- | --- | --- |
| Block Deflect (D1) | **Dribble Burst** wins outright | **bonus applies** | — |
| Clear (D1) | **Dribble Burst** wins outright | **bonus applies** | **pays:** add exhaustion *(how much is not stated)* ‡C |
| Steal Intercept (D2) | **Tie** — a skill test decides | bonus if won. If lost, the cost as drafted names *Pressure*, which has not happened ‡T | — |
| Intercept (D2) | **Tie** — a skill test decides | bonus if won. If lost, the cost as drafted names *Pressure*, which has not happened ‡T | the same from their end ‡T |
| Pressure (D3) | **Pressure** wins outright | **pays:** the pressured player does not go back with the ball | — |
| Double Team (D3) | **Double Team** wins outright | **pays:** the pressured player does not go back with the ball | **bonus:** ball back **2**, and a second defender joins for free (+dSkill) |
| *no challenger sent* | **Dribble Burst** succeeds unopposed | bonus? ‡U | — |

### Setup Pass — O3, the advanced High Pass

**On success:** a set-up at distance 0, 1 or 3, speed modifier in favour. **When defeated:** the other team may set up a scoring opportunity after the resolution.

| Played against | How it settles | What Setup Pass gets or pays | What the opposing card gets or pays |
| --- | --- | --- | --- |
| Block Deflect (D1) | **Block Deflect** wins outright | **pays:** the other team may set up a scoring opportunity after the resolution | — |
| Clear (D1) | **Clear** wins outright | **pays:** the other team may set up a scoring opportunity after the resolution | **bonus:** ball back **3** spaces, speed −3 |
| Steal Intercept (D2) | **Setup Pass** wins outright | **bonus applies** | — |
| Intercept (D2) | **Setup Pass** wins outright | **bonus applies** | **pays:** the High Pass reception is not contested ‡C |
| Pressure (D3) | **Tie** — a skill test decides | bonus if won, cost if lost ‡T | — |
| Double Team (D3) | **Tie** — a skill test decides | bonus if won, cost if lost ‡T | the same from their end ‡T |
| *no challenger sent* | **Setup Pass** succeeds unopposed | bonus? ‡U | — |

### Clear — D1, the advanced Block Deflect

**On success:** ball back **3** spaces, speed −3. **When defeated:** add exhaustion *(how much is not stated)*.

| Played against | How it settles | What Clear gets or pays | What the opposing card gets or pays |
| --- | --- | --- | --- |
| Low Pass (O1) | **Tie** — a skill test decides | bonus if won, cost if lost ‡T | — |
| Precise Pass (O1) | **Tie** — a skill test decides | bonus if won, cost if lost ‡T | the same from their end ‡T |
| Dribble Advance (O2) | **Dribble Advance** wins outright | **pays:** add exhaustion *(how much is not stated)* | — |
| Dribble Burst (O2) | **Dribble Burst** wins outright | **pays:** add exhaustion *(how much is not stated)* | **bonus:** carry the ball **all the way to the goal**, a token a space |
| High Pass (O3) | **Clear** wins outright | **bonus applies** | — |
| Setup Pass (O3) | **Clear** wins outright | **bonus applies** | **pays:** the other team may set up a scoring opportunity after the resolution ‡C |
| *this side sent nobody* | the card is never played | nothing applies | — |

### Intercept — D2, the advanced Steal Intercept

**On success:** turnover, and defender and ball move **forward** 1. **When defeated:** the High Pass reception is not contested.

| Played against | How it settles | What Intercept gets or pays | What the opposing card gets or pays |
| --- | --- | --- | --- |
| Low Pass (O1) | **Intercept** wins outright | **bonus applies** | — |
| Precise Pass (O1) | **Intercept** wins outright | **bonus applies** | **pays:** the defender may play an unopposed Low Pass after stealing ‡C |
| Dribble Advance (O2) | **Tie** — a skill test decides | bonus if won. If lost, the cost as drafted names *High Pass*, which has not happened ‡T | — |
| Dribble Burst (O2) | **Tie** — a skill test decides | bonus if won. If lost, the cost as drafted names *High Pass*, which has not happened ‡T | the same from their end ‡T |
| High Pass (O3) | **High Pass** wins outright | **pays:** the High Pass reception is not contested | — |
| Setup Pass (O3) | **Setup Pass** wins outright | **pays:** the High Pass reception is not contested | **bonus:** a set-up at distance 0, 1 or 3, speed modifier in favour |
| *this side sent nobody* | the card is never played | nothing applies | — |

### Double Team — D3, the advanced Pressure

**On success:** ball back **2**, and a second defender joins for free (+dSkill). **When defeated:** **the draft is cut off — nothing is stated**.

| Played against | How it settles | What Double Team gets or pays | What the opposing card gets or pays |
| --- | --- | --- | --- |
| Low Pass (O1) | **Low Pass** wins outright | **pays:** **the draft is cut off — nothing is stated** | — |
| Precise Pass (O1) | **Precise Pass** wins outright | **pays:** **the draft is cut off — nothing is stated** | **bonus:** ball to **any** teammate, speed +3 |
| Dribble Advance (O2) | **Double Team** wins outright | **bonus applies** | — |
| Dribble Burst (O2) | **Double Team** wins outright | **bonus applies** | **pays:** the pressured player does not go back with the ball ‡C |
| High Pass (O3) | **Tie** — a skill test decides | bonus if won, cost if lost ‡T | — |
| Setup Pass (O3) | **Tie** — a skill test decides | bonus if won, cost if lost ‡T | the same from their end ‡T |
| *this side sent nobody* | the card is never played | nothing applies | — |

---

## The outcome ladder

The tables above are the pairings. This is the part the drafts do not reach: a maneuver
turn does not land in "won" or "lost" but in one of eight states, and the two words in the
brief cover only rows 2 and 3.

Rows 5 to 8 exist because of the injured player's disadvantage (see [Playing
injured](living-rules.md#playing-injured)), which both takes wins away and hands them out.
Every one of them is a state an advanced card can be sitting in when the turn resolves.

| # | How the turn landed | Whose maneuver resolves | Advanced bonus? | Advanced cost? |
| --- | --- | --- | --- | --- |
| 1 | **Unopposed** — the defense sent no challenger | the offense's | ‡U | the defense played no card, so nothing to charge |
| 2 | **Decisive on the cards** | the higher-ranked | **yes**, to the winner | **yes**, to the loser — this is the case every draft is written for |
| 3 | **Tie → skill test** | the test's winner | ‡T | ‡T, and three of the six costs cannot be read here at all |
| 4 | **Tie re-rolled** (equal totals; another token each) | settled by the re-roll | as row 3 | as row 3 |
| 5 | **Injury downgrade** — a decisive win owed to an injured player becomes a test they must win — **won** | the injured player's | ‡T ‡I | ‡T ‡I |
| 6 | Same, **lost** | their opponent's | ‡T ‡I | ‡T ‡I |
| 7 | **Injured tie** — a tie against exactly one injured participant, lost automatically with nothing rolled | the healthy player's | ‡I | ‡I |
| 8 | **Both injured in a tie** — an ordinary tie | as row 3 | as row 3 | as row 3 |

‡I is [Q13](#q13-how-do-the-advanced-effects-read-against-an-injured-player).

Rows 5 and 6 are the awkward ones. A player who was owed a decisive win and is made to roll
for it *because they are injured* is in the one state where the cost falls on somebody the
cards said should have won — charging them reads as charging them twice for the injury.

---

## Open questions for the author

Eighteen. The first five block the matrix; the next seven are one per card and block its
effects; two more apply across all six; one is upstream housekeeping; the last three are
asymmetric teams.

### Blocking the matrix

#### Q1: Is advanced-vs-basic a per-turn choice?

Does a coach playing advanced hold **six cards** and pick one secretly each maneuver, or is
a side locked to one set for the game, or is it a game-level toggle so that both sides use
the advanced set or neither does? The tables assume the first, because the other two are
sub-grids of it.

#### Q2: Does an advanced card beat a basic card of the same rank?

The sheet says no by omission — an advanced row's `Defeats` and `Defeated by` are its basic
counterpart's, unchanged. Confirming that is enough. The alternative removes three of the
nine skill tests from any game where one coach plays advanced and the other does not, and
needs a second diagram on the card backs.

#### Q3: Does losing a skill test count as being defeated?

Three of the six costs name the maneuver that beat them — a steal, a pressure, a High Pass
reception — none of which happens when the card loses a same-rank skill test instead. See
[the table above](#three-of-the-six-costs-name-the-maneuver-that-defeated-them).

The reading that fits the drafts is: **"defeated" means the maneuver that beats it
resolved, and a lost skill test is not that.** The alternative is a second cost per card
for the tie, which is three more clauses to write.

The same question, harder, for rows 5 and 6 of the ladder: a player made to roll for a win
they were owed, because they are injured, and losing.

#### Q4: Does an unopposed maneuver earn its bonus?

The defense may send nobody rather than pay to walk a challenger in. If the bonus applies,
declining against Dribble Burst means conceding a run at the goal for free, which is a much
worse decline than it is today.

#### Q5: Do both sides' effects apply at once?

Nine of the thirty-six pairings are advanced-against-advanced and decisive. Some of those
stack heavily: **Precise Pass into Intercept** gives the defense the steal, the forward
move *and* an unopposed Low Pass — three effects off one maneuver. **Setup Pass into
Clear** gives the defense a 3-space clearance, its own possible set-up off the overshoot,
*and* the set-up the Setup Pass's cost hands them.

### One per card

#### Q6: Double Team's cost is missing

The draft ends mid-sentence at "If defeated". Nothing can be built for D3 until it is
finished.

#### Q7: Clear — how much exhaustion, and on whom?

"Add exhaustion" does not say how many tokens, or whether they go on the defender who
played the card or on somebody else. It is the only cost of the six paid in a currency the
game already counts.

#### Q8: Setup Pass — distances 0, 1 or 3, and who shoots from 0?

Three things here. A High Pass throws **2, 3 or 4**; this throws **0, 1 or 3**, which is a
different set rather than an extension of it. Distances that would run off the field are
currently dropped from the menu — does that still hold, and can this card overshoot?

And **distance 0 collides with a rule already settled**: a passer never receives their own
pass (2026-08-12), so a set-up on the ball's own space has no shooter unless a teammate is
standing there. Is 0 meant to set up a *teammate on the passer's space*, or is this card an
exception to that rule?

#### Q9: Intercept — forward for whom?

Basic Steal Intercept moves the defender and ball **back**, toward the goal the newly
possessing team defends. Intercept says **forward**. Read the same way that is toward the
goal they now attack — an interception that gains ground — which would make it strictly
better than the basic version in position as well as in speed. Confirming the direction
matters because "forward" and "back" mean opposite things to the two sides, and getting one
of these mirrored is a mistake this project has made before.

#### Q10: Precise Pass — how far is "any teammate"?

The basic Low Pass reaches at most 2 spaces, and a nearer teammate blocks a farther one in
the same direction. "Ball to any teammate" appears to drop both limits — the whole field,
past anybody in the way. Also: does the passer still move forward 1 when passing across a
shared space, and is the +3 still capped at speed 12?

#### Q11: Dribble Burst — all the way to where?

The last space of the attacking goal zone, or as far as the player chooses? What happens
when a defender is standing in the way — is the run stopped, or is nothing in the way? Is
the exhaustion 1 a space (which on board 9 could be six or seven tokens off one maneuver,
enough to make a healthy player Exhausted in a single turn)? And is the ball still left
with the handler at the end?

#### Q12: The `Interactions` column is stale on all six advanced rows

Each advanced row repeats its basic counterpart's role abilities, and three of them now
contradict the card:

- **Clear** sends the ball back 3, but carries "Fullback: ball goes back 2" — the ability
  makes the card *worse*.
- **Dribble Burst** runs to the goal, but carries "Playermaker may advance 2".
- **Setup Pass** offers 0, 1 or 3, but carries "Fullback can pass up to 4".

So: do role abilities apply to the advanced version at all, and if they do, what do these
three mean? The Midfielder's +3, the Winger's set-up, the Defender's steal and the
Striker's +3 have no such conflict and presumably carry over.

### Across all six

#### Q13: How do the advanced effects read against an injured player?

Rows 5 to 8 of the ladder, and whether an advanced cost stacks on top of the [injury
check](living-rules.md#the-injury-check) a skill test already owes.

#### Q14: Does the cycle hold advanced-against-advanced?

`Defeats` and `Defeated by` name only basic maneuvers, so the sheet never says what Precise
Pass does against Intercept. Reading it by rank is what makes the grid work; it should be
stated rather than inferred.

### Upstream housekeeping

#### Q15: Two columns are stale, and one has no name

- **`Time`** still says "distance traveled (1-2 space minutes)" for Low Pass and "(2-4)"
  for High Pass. The 2026-08-16 flat-cost ruling replaced those with 1 and 2, and
  `maneuvers.json` was edited by hand — so **re-running the importer today would revert
  it.** This wants fixing upstream before anything is imported. Do the advanced cards cost
  the same as their counterparts?
- **`Die value`** was retired from the rules on 2026-08-17 and can go.
- **The tier column has no header** (`Column 10`). It needs a name — `Mode` or `Tier` — for
  the importer to read it by.

### Asymmetric teams

The `Advanced` ability column in `basic_abilities` is still empty for all thirty-six
players, so there is nothing to import. Three questions decide how much can be built ahead
of it.

#### Q16: Is a team's special set per player or per team?

An `Advanced` ability per player card, a handful of team-wide rules, or both?

#### Q17: What does "unique role composition" allow?

Today every team is nine players — one of each of six starting roles plus three on the
bench — and the loader **refuses** anything else (`load_player_catalog`,
`default_formation_deal`). Which can vary: the bench of three, the six starting roles, the
total of nine, the roles existing at all?

Related, and worth settling in the same breath: **4-1-1 and 2-1-3** were set aside for
advanced mode on 2026-08-08 and fit no current board. Are they part of asymmetric teams?

#### Q18: Can the two sides differ?

"Each team can be played as the standard version or with a unique set" reads as a per-side
choice, so one coach could play standard against an asymmetric opponent. Intended, or must
both sides agree?

---

## What this costs in code

Not a plan — see the branch's pull request. Four things worth knowing while the questions
above are being answered, because they may change an answer:

- **A maneuver's identity is its display name.** `match.offense_maneuver` holds the string
  `"Low Pass"`, and around ten places compare against those literals: the effect dispatch
  table, the Midfielder's +3, the ball speed modifier a Steal Intercept adds, the turnover
  check, and the maneuver cards' own layout. The advanced cards have entirely different
  names, so a stable identifier separate from the printed name is needed whatever else is
  decided.
- **Four of the six costs are new mechanisms, not a shared penalty.** An unopposed Low Pass
  granted to the defense, a set-up granted to the other team, a Pressure that leaves the
  ball behind, a High Pass reception that skips its contest — each is a branch of its own in
  the resolution, and none of them exists today.
- **Two of the six effects reach past the maneuver they belong to.** Dribble Burst charges
  exhaustion by distance, which no maneuver currently does; Double Team moves a *second*
  defender onto the space and adds their skill to a test, which nothing in the game does.
- **Setup already refuses advanced mode** (`GameMode.ADVANCED`), and it is a single enum —
  basic or advanced. "Players can choose whether to add one or both" makes it two
  independent switches, which is a change to the saved game record.

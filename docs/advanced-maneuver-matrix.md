# Advanced maneuvers — the interaction matrix

**Status: a worksheet, not a rule.** Nothing here has been played, and nothing here
is in [living-rules.md](living-rules.md) — a rule reaches that document only once the
author has settled it. This is the table asked for on 2026-08-17: every advanced
maneuver against every maneuver it can meet, and which cost or benefit applies in each
case.

It is deliberately structured so that the blanks are visible. Two things are missing,
and they are different kinds of missing:

1. **The six advanced maneuvers themselves** — their names, effects, bonuses and extra
   costs are drafted in the Google Sheet and have not been pulled into the repo yet.
   Every table below names them as `Adv. <basic name>` and leaves the content blank.
   Filling [The six cards](#the-six-cards) is the whole of that gap.
2. **Five rulings**, listed in [Open questions](#open-questions-for-the-author). Those
   are not lookups — no source has them, and they decide the shape of the matrix rather
   than its contents. Cells that depend on one are marked with its symbol (‡T, ‡U, ‡C).

---

## What an advanced maneuver is

From the author, 2026-08-17:

> Each maneuver now has an advanced version that, if it succeeds, is more impactful.
> However, if the maneuver is *defeated*, it has an additional cost.

So each card carries two things the basic version does not: an **upside on success** and
a **penalty on defeat**. The matrix exists because "succeeds" and "defeated" are not two
outcomes in this game — a maneuver turn lands in one of eight states, and only two of
them are unambiguous.

---

## The six cards

To be filled from the sheet's advanced drafts. The rank column is the assumption
[A1](#a1-an-advanced-maneuver-keeps-its-counterparts-rank) — it is what makes the whole
grid below computable, so it is the first thing to confirm.

| Basic | Rank | Advanced name | Effect on success | Extra cost when defeated | Clock cost |
| --- | --- | --- | --- | --- | --- |
| Low Pass | O1 | *(to fill)* | *(to fill)* | *(to fill)* | *(to fill — basic is 1)* |
| Dribble Advance | O2 | *(to fill)* | *(to fill)* | *(to fill)* | *(to fill — basic is 1)* |
| High Pass | O3 | *(to fill)* | *(to fill)* | *(to fill)* | *(to fill — basic is 2)* |
| Block Deflect | D1 | *(to fill)* | *(to fill)* | *(to fill)* | *(to fill — basic is 1)* |
| Steal Intercept | D2 | *(to fill)* | *(to fill)* | *(to fill)* | *(to fill — basic is 1)* |
| Pressure | D3 | *(to fill)* | *(to fill)* | *(to fill)* | *(to fill — basic is 1)* |

---

## The assumptions this matrix is built on

Each of these is a reading, not a ruling. Every one of them changes the tables if it is
wrong, which is why they are stated separately from the tables themselves.

### A1: an advanced maneuver keeps its counterpart's rank

Adv. Low Pass is still O1: it beats Pressure, loses to Steal Intercept and ties with
Block Deflect, in whichever form those are played. This follows from "each corresponds
to one of the existing basic maneuvers" and is what keeps the defeat cycle a cycle — the
back of every maneuver card carries that hexagon, and a second set of ranks would need a
second hexagon.

### A2: advanced does not beat basic of the same rank

Rank alone decides. An advanced card is stronger in what it *does*, not in what it
*beats*, so Adv. Low Pass against Block Deflect is a tie exactly as Low Pass is. See
[the second grid](#if-advanced-broke-a-same-rank-tie-a2-rejected) for what the
alternative would look like — it is a real design fork, not a technicality, and it is
[Q2](#q2-does-an-advanced-card-beat-a-basic-card-of-the-same-rank).

### A3: the choice is per turn, from a hand of six

A coach holding the advanced set picks one of six cards each maneuver, secretly, exactly
as they pick one of three now. This is the widest reading and produces the largest
matrix; the two narrower ones (a per-team lock for the game, or a game-level toggle) are
sub-grids of it, so building for this covers them. It is
[Q1](#q1-is-advanced-vs-basic-a-per-turn-choice), and it is the single fact the shape of
everything downstream rests on.

### A4: a maneuver's effect is unchanged except where the advanced card says so

The advanced version resolves through the same machinery — a set-up is still a set-up, a
turnover is still a turnover, ball speed still moves the way the basic card moves it —
and the advanced text adds to that rather than replacing it. Anything the drafts state
in full overrides this.

### A5: role abilities apply to the advanced version of the same maneuver

A Playmaker still advances 2 on an Adv. Dribble Advance, a Fullback still throws 4 on an
Adv. High Pass, a Midfielder still adds 3 to a skill test for their own Adv. Low Pass or
Adv. Pressure, a Winger's Adv. Low Pass still offers its set-up. The abilities name a
maneuver, and the advanced version is that maneuver. This is
[Q10](#q10-do-role-abilities-carry-to-the-advanced-version).

---

## The master grid

Under A1 and A2, **the winner never depends on whether either card is advanced**. The
6×6 grid is the existing 3×3 cycle repeated four times:

| Offense \ Defense | Block Deflect | Adv. Block Deflect | Steal Intercept | Adv. Steal Intercept | Pressure | Adv. Pressure |
| --- | --- | --- | --- | --- | --- | --- |
| **Low Pass** | skill test | skill test | defense | defense | offense | offense |
| **Adv. Low Pass** | skill test | skill test | defense | defense | offense | offense |
| **Dribble Advance** | offense | offense | skill test | skill test | defense | defense |
| **Adv. Dribble Advance** | offense | offense | skill test | skill test | defense | defense |
| **High Pass** | defense | defense | offense | offense | skill test | skill test |
| **Adv. High Pass** | defense | defense | offense | offense | skill test | skill test |

That is the useful finding at the top of this document: **advanced mode adds no new way
to win a maneuver.** What it adds is a consequence attached to winning and to losing, so
the thirty-six pairings collapse to nine outcomes plus a bonus/cost overlay. Everything
below is that overlay.

### If advanced broke a same-rank tie (A2 rejected)

For comparison, and because it is the one alternative that would make the 6×6 grid mean
something. Every same-rank pairing where exactly one side is advanced becomes decisive:

| Offense \ Defense | Block Deflect | Adv. Block Deflect | Steal Intercept | Adv. Steal Intercept | Pressure | Adv. Pressure |
| --- | --- | --- | --- | --- | --- | --- |
| **Low Pass** | skill test | **defense** | defense | defense | offense | offense |
| **Adv. Low Pass** | **offense** | skill test | defense | defense | offense | offense |
| **Dribble Advance** | offense | offense | skill test | **defense** | defense | defense |
| **Adv. Dribble Advance** | offense | offense | **offense** | skill test | defense | defense |
| **High Pass** | defense | defense | offense | offense | skill test | **defense** |
| **Adv. High Pass** | defense | defense | offense | offense | **offense** | skill test |

This would remove three of the nine skill tests from any game where one coach is playing
advanced and the other is not, which is a large change to how often the d12 comes out. It
is recorded here as a fork, not a recommendation.

---

## Every interaction, maneuver by maneuver

Six tables, one per advanced card, each listing every card it can be played against —
basic and advanced — plus the case where no maneuver is played against it at all.

Read the last two columns as "what happens to my card" and "what happens to theirs".
Marked cells depend on a ruling:

| Marker | The question |
| --- | --- |
| ‡T | Does a skill test count as succeeding / being defeated? — [Q3](#q3-does-a-skill-test-count) |
| ‡U | Does an unopposed maneuver earn its bonus? — [Q4](#q4-does-an-unopposed-maneuver-earn-its-bonus) |
| ‡C | Do a winner's bonus and a loser's cost both apply when both sides played advanced? — [Q5](#q5-do-both-sides-effects-apply-at-once) |

### Adv. Low Pass — O1, offense

| Played against | How it settles | For Adv. Low Pass | For the opposing card |
| --- | --- | --- | --- |
| Block Deflect (D1) | Tie on the cards — a skill test settles it | bonus if the test is won, cost if it is lost ‡T | — |
| Adv. Block Deflect (D1) | Tie on the cards — a skill test settles it | bonus if the test is won, cost if it is lost ‡T | same, from their end ‡T |
| Steal Intercept (D2) | **Steal Intercept** wins outright | **I pay my cost** | — |
| Adv. Steal Intercept (D2) | **Adv. Steal Intercept** wins outright | **I pay my cost** | **their bonus applies** |
| Pressure (D3) | **Adv. Low Pass** wins outright | **bonus applies** | — |
| Adv. Pressure (D3) | **Adv. Low Pass** wins outright | **bonus applies** | **they pay their cost** ‡C |
| *nobody — the defense sent no challenger* | **Adv. Low Pass** succeeds unopposed | bonus? ‡U | — |

### Adv. Dribble Advance — O2, offense

| Played against | How it settles | For Adv. Dribble Advance | For the opposing card |
| --- | --- | --- | --- |
| Block Deflect (D1) | **Adv. Dribble Advance** wins outright | **bonus applies** | — |
| Adv. Block Deflect (D1) | **Adv. Dribble Advance** wins outright | **bonus applies** | **they pay their cost** ‡C |
| Steal Intercept (D2) | Tie on the cards — a skill test settles it | bonus if the test is won, cost if it is lost ‡T | — |
| Adv. Steal Intercept (D2) | Tie on the cards — a skill test settles it | bonus if the test is won, cost if it is lost ‡T | same, from their end ‡T |
| Pressure (D3) | **Pressure** wins outright | **I pay my cost** | — |
| Adv. Pressure (D3) | **Adv. Pressure** wins outright | **I pay my cost** | **their bonus applies** |
| *nobody — the defense sent no challenger* | **Adv. Dribble Advance** succeeds unopposed | bonus? ‡U | — |

### Adv. High Pass — O3, offense

| Played against | How it settles | For Adv. High Pass | For the opposing card |
| --- | --- | --- | --- |
| Block Deflect (D1) | **Block Deflect** wins outright | **I pay my cost** | — |
| Adv. Block Deflect (D1) | **Adv. Block Deflect** wins outright | **I pay my cost** | **their bonus applies** |
| Steal Intercept (D2) | **Adv. High Pass** wins outright | **bonus applies** | — |
| Adv. Steal Intercept (D2) | **Adv. High Pass** wins outright | **bonus applies** | **they pay their cost** ‡C |
| Pressure (D3) | Tie on the cards — a skill test settles it | bonus if the test is won, cost if it is lost ‡T | — |
| Adv. Pressure (D3) | Tie on the cards — a skill test settles it | bonus if the test is won, cost if it is lost ‡T | same, from their end ‡T |
| *nobody — the defense sent no challenger* | **Adv. High Pass** succeeds unopposed | bonus? ‡U | — |

### Adv. Block Deflect — D1, defense

| Played against | How it settles | For Adv. Block Deflect | For the opposing card |
| --- | --- | --- | --- |
| Low Pass (O1) | Tie on the cards — a skill test settles it | bonus if the test is won, cost if it is lost ‡T | — |
| Adv. Low Pass (O1) | Tie on the cards — a skill test settles it | bonus if the test is won, cost if it is lost ‡T | same, from their end ‡T |
| Dribble Advance (O2) | **Dribble Advance** wins outright | **I pay my cost** | — |
| Adv. Dribble Advance (O2) | **Adv. Dribble Advance** wins outright | **I pay my cost** | **their bonus applies** |
| High Pass (O3) | **Adv. Block Deflect** wins outright | **bonus applies** | — |
| Adv. High Pass (O3) | **Adv. Block Deflect** wins outright | **bonus applies** | **they pay their cost** ‡C |
| *no challenge made — this side sent nobody* | the card is never played | nothing applies | — |

### Adv. Steal Intercept — D2, defense

| Played against | How it settles | For Adv. Steal Intercept | For the opposing card |
| --- | --- | --- | --- |
| Low Pass (O1) | **Adv. Steal Intercept** wins outright | **bonus applies** | — |
| Adv. Low Pass (O1) | **Adv. Steal Intercept** wins outright | **bonus applies** | **they pay their cost** ‡C |
| Dribble Advance (O2) | Tie on the cards — a skill test settles it | bonus if the test is won, cost if it is lost ‡T | — |
| Adv. Dribble Advance (O2) | Tie on the cards — a skill test settles it | bonus if the test is won, cost if it is lost ‡T | same, from their end ‡T |
| High Pass (O3) | **High Pass** wins outright | **I pay my cost** | — |
| Adv. High Pass (O3) | **Adv. High Pass** wins outright | **I pay my cost** | **their bonus applies** |
| *no challenge made — this side sent nobody* | the card is never played | nothing applies | — |

### Adv. Pressure — D3, defense

| Played against | How it settles | For Adv. Pressure | For the opposing card |
| --- | --- | --- | --- |
| Low Pass (O1) | **Low Pass** wins outright | **I pay my cost** | — |
| Adv. Low Pass (O1) | **Adv. Low Pass** wins outright | **I pay my cost** | **their bonus applies** |
| Dribble Advance (O2) | **Adv. Pressure** wins outright | **bonus applies** | — |
| Adv. Dribble Advance (O2) | **Adv. Pressure** wins outright | **bonus applies** | **they pay their cost** ‡C |
| High Pass (O3) | Tie on the cards — a skill test settles it | bonus if the test is won, cost if it is lost ‡T | — |
| Adv. High Pass (O3) | Tie on the cards — a skill test settles it | bonus if the test is won, cost if it is lost ‡T | same, from their end ‡T |
| *no challenge made — this side sent nobody* | the card is never played | nothing applies | — |

---

## The outcome ladder

The tables above are the pairings. This is the part that actually needs deciding: a
maneuver turn does not land in "won" or "lost" but in one of eight states, and the two
words in the brief cover only rows 2 and 3.

Rows 4 to 7 exist because of the injured player's disadvantage (see
[Playing injured](living-rules.md#playing-injured)), which both takes wins away and hands
them out. Every one of them is a state an advanced card can be sitting in when the turn
resolves.

| # | How the turn landed | Whose maneuver resolves | Advanced bonus? | Advanced cost? |
| --- | --- | --- | --- | --- |
| 1 | **Unopposed** — the defense sent no challenger | the offense's | ‡U | the defense played no card, so nothing to charge |
| 2 | **Decisive on the cards** | the higher-ranked | **yes**, to the winner | **yes**, to the loser |
| 3 | **Tie → skill test** | the test's winner | ‡T | ‡T |
| 4 | **Tie re-rolled** (equal totals; another token each) | settled by the re-roll | as row 3 | as row 3 |
| 5 | **Injury downgrade** — a decisive win owed to an injured player becomes a test they must win — **won** | the injured player's | ‡T ‡I | ‡T ‡I |
| 6 | Same, **lost** | their opponent's | ‡T ‡I | ‡T ‡I |
| 7 | **Injured tie** — a tie against exactly one injured participant, lost automatically with nothing rolled | the healthy player's | ‡I | ‡I |
| 8 | **Both injured in a tie** — an ordinary tie | as row 3 | as row 3 | as row 3 |

‡I is [Q6](#q6-how-do-the-advanced-effects-read-against-an-injured-player).

Two things worth naming, because they are what makes this ladder awkward rather than
long:

- **Every maneuver turn ends with exactly one maneuver resolving.** There is no state
  where neither card takes effect, so "defeated" has a clean default reading: *my card
  was not the one that resolved*. Adopting that reading answers ‡T, ‡U and part of ‡I at
  once — and it is the reading the tables above are drawn under. The alternative, that
  only a decisive rank loss is a defeat, makes an advanced card strictly safer to play
  into a tie than into a mismatch, which may or may not be wanted.
- **A skill test already costs both participants a token**, and a re-roll costs another.
  If the advanced cost is also paid in exhaustion, row 3 charges the loser twice for one
  maneuver, and row 4 three times. That is [Q7](#q7-what-currency-is-the-extra-cost-in).

---

## Open questions for the author

Grouped by what they block. The first five are the matrix; the rest can be answered
while it is being built.

### Blocking the matrix

#### Q1: Is advanced-vs-basic a per-turn choice?

Does a coach playing advanced hold **six cards** and pick one secretly each maneuver, or
is a side locked to one set for the game, or is it a game-level toggle so that both
sides use the advanced set or neither does? A3 assumes the first. This decides whether
"Adv. Low Pass vs Block Deflect" is a pairing that can occur at all.

#### Q2: Does an advanced card beat a basic card of the same rank?

A2 says no — rank alone decides, and same rank is a tie however the two cards were
chosen. The alternative grid is
[above](#if-advanced-broke-a-same-rank-tie-a2-rejected). If the answer is no, advanced
mode never changes who wins a maneuver, only what winning and losing are worth.

#### Q3: Does a skill test count?

Three sub-questions, and they may not have the same answer:

- Is winning a skill test after a tie **succeeding** (bonus applies)?
- Is losing one **being defeated** (extra cost applies)?
- Does the answer change when the test came from an injury downgrade (rows 5 and 6)
  rather than from a tie?

#### Q4: Does an unopposed maneuver earn its bonus?

The defense can decline the challenge rather than pay to walk a player in. The offense's
card then succeeds with nothing to beat. Does the advanced bonus apply, and does that
make declining against an advanced card worse than declining against a basic one?

#### Q5: Do both sides' effects apply at once?

With both cards advanced, a decisive result means the winner's bonus *and* the loser's
extra cost. Both, or does one suppress the other?

### Blocking the effects

#### Q6: How do the advanced effects read against an injured player?

Injury already both withholds wins and hands them out. Does an advanced card change how
that works, and does the extra cost stack on top of an [injury
check](living-rules.md#the-injury-check) at the end of a test?

#### Q7: What currency is the extra cost in?

Exhaustion tokens, space minutes on the clock, ball speed, position, an injury check, a
lost declaration, something else? Each is a different mechanism in the code, so this is
the answer that most shapes the build. Please answer it per card if the six differ.

#### Q8: When is the cost paid?

At the moment the maneuver resolves, or at the start of that side's next turn? A cost
paid at resolution lands in the middle of an effect that may itself be moving the ball
and running players back.

#### Q9: Who pays it — the player or the team?

The handler / challenger who played the card, or the side as a whole? Exhaustion is a
player's; the clock and the declaration are a side's.

#### Q10: Do role abilities carry to the advanced version?

A5 assumes yes for all six: a Playmaker's extra space, a Fullback's 4-space throw and
2-space deflect, a Midfielder's +3 on a test, a Winger's set-up, a Defender's steal off a
won Pressure, a Striker's +3 on a set-up shot.

#### Q11: Does an advanced maneuver's clock cost differ?

Every maneuver costs a flat space minute except High Pass, which costs 2 (2026-08-16).
Is an advanced version the same, or is the clock one of the places the extra cost lands?

#### Q12: Can the advanced cards produce set-ups, own goals and turnovers as the basic ones do?

A4 assumes each advanced card resolves through its basic counterpart's machinery. If an
advanced Pressure can no longer overshoot into an own goal, or an advanced High Pass
resolves its overshoot differently, that needs saying — those are the branchiest paths in
the game.

### Asymmetric teams — before anything can be specified

The `Advanced` ability column in the sheet is still empty for all thirty-six players, so
there is nothing to import yet. Three questions decide how much can be built ahead of it:

#### Q13: Is a team's special set per player or per team?

An `Advanced` ability per player card (replacing or adding to their role ability), a
handful of team-wide rules, or both?

#### Q14: What does "unique role composition" allow?

Today every team is nine players — one of each of six starting roles plus three on the
bench — and the loader **refuses** data that is not
(`load_player_catalog`, `default_formation_deal`). A team with two Strikers and no
Winger, or with eight players, is not a data change but a change to what the game
considers a legal team. Which of these can vary: the six starting roles, the bench of
three, the total of nine, the roles existing at all?

#### Q15: Can the two sides differ?

"Each team can be played as the standard version or with a unique set" reads as a
per-side choice, so one coach could play standard against an asymmetric opponent. Is that
intended, or do both sides have to agree?

Two things already recorded that bear on this and should be confirmed rather than
assumed: the formations **4-1-1 and 2-1-3** were set aside for advanced mode on
2026-08-08 and fit no current board; and the back of a printed player card is that
player's advanced version (2026-08-12), which is what fills in once Q13 is answered.

---

## What this costs in code

Not a plan — see the branch's pull request for that. Three things worth knowing while
the questions above are being answered, because they may change an answer:

- **A maneuver's identity is its display name.** `match.offense_maneuver` holds the
  string `"Low Pass"`, and around ten places compare against those literals: the effect
  dispatch table, the Midfielder's +3, the ball speed modifier a Steal Intercept adds,
  the turnover check, and the maneuver cards' own layout. Advanced cards with different
  names need a stable identifier separate from the printed name — which is worth doing
  whatever the answers are.
- **The defeat cycle is drawn on the back of every maneuver card**, and every coach reads
  a matchup off it. A2 keeps that one hexagon; rejecting A2 needs a second diagram, or a
  hexagon that says what an advanced card does to a same-rank tie.
- **Setup already refuses advanced mode** (`GameMode.ADVANCED`), and it is a single enum
  — basic or advanced. "Players can choose whether to add one or both" makes it two
  independent switches, which is a change to the saved game record.

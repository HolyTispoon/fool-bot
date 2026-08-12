# D12 Ball — Living Rules

This is the authoritative reference for **basic mode**. It contains the current rules only; history, open questions, and upstream differences belong in [rules-log.md](rules-log.md).

## Contents

- [Game at a glance](#game-at-a-glance)
- [Field, teams, and terms](#field-teams-and-terms)
- [Setup](#setup)
- [Turn sequence](#the-turn)
- [Score attempts](#score-attempt)
- [Maneuvers](#maneuvers)
- [Ball speed, loose balls, and set-ups](#ball-speed-loose-balls-and-set-ups)
- [Turnovers, resets, and running back](#turnovers-resets-and-running-back)
- [Exhaustion and injury](#exhaustion-and-injury)
- [Coaching Choice](#coaching-choice)
- [Clock, halftime, and full time](#clock-halftime-and-full-time)
- [Extreme shootout](#extreme-shootout)
- [Quick reference](#quick-reference)

## Game at a glance

Two coaches each control nine players, six fielded and three on the bench. Play two 15-space-minute periods. The higher score wins; a tie goes to the [Extreme Shootout](#extreme-shootout).

On a turn, the possessing team makes a maneuver or, in range, a score attempt. A turnover either makes players run back or starts a new play, resetting both sides to saved arrangements.

## Field, teams, and terms

### Field, direction, and shooting range

The field is a row of spaces split left to right into home goal, midfield, and visitors goal. Home attacks visitors goal; visitors attack home goal. **Forward** means toward a team's attacking goal, **back** toward its defending goal.

| Board | Home | Midfield | Visitors |
| --- | ---: | ---: | ---: |
| 6 | 2 | 2 | 2 |
| 7 (default) | 2 | 3 | 2 |
| 9 | 3 | 3 | 3 |

A team is in **shooting range** when the ball is past the board's middle toward its attacking goal.

| Board | Visitors' range | Neither | Home's range |
| --- | --- | --- | --- |
| 6 | H1, H2, M1 | — | M2, V1, V2 |
| 7 | H1, H2, M1 | M2 | M3, V1, V2 |
| 9 | H1, H2, H3, M1 | M2 | M3, V1, V2, V3 |

Kickoff is the middle space on boards 7 and 9. On board 6, it is the midfield space nearer the kicking team's own goal. A restart never starts in the kicking team's range.

### Occupancy

Meeples may share spaces freely in ordinary play. Deliberate placement—at a Coaching Choice or during a run back—uses **coverage**: a team must cover every space in a zone it occupies before stacking another of its meeples there. Check coverage separately for each team.

### Teams and roles

A card's offensive skill is 1–6; defensive skill is its d6 inverse, so they total 7. Basic-mode teams are identical.

| Role | Off | Def | Ability |
| --- | ---: | ---: | --- |
| Fullback | 1 | 6 | High Pass up to 4; Block Deflect back 2. |
| Defender | 2 | 5 | A won Pressure also steals. |
| Midfielder | 3 | 4 | +3 on Low Pass and Pressure skill tests. |
| Playmaker | 4 | 3 | Dribble Advance may go 2. |
| Winger | 5 | 2 | Completed Low Pass may set up a shot. |
| Striker | 6 | 1 | +3 on a shot off a set-up. |

Each team has one Fullback, two Defenders, one Midfielder, two Playmakers, one Winger, and two Strikers. No role is tied to a zone outside setup.

### Terms

| Term | Meaning |
| --- | --- |
| Meeple / card | Current space / assigned zone. |
| Possession | Team controlling the ball. |
| Ball carrier | Named player who must take the next turn. |
| Arrangement | Coach's saved meeple spaces from a Coaching Choice. |
| New play / steal | Turnover types that reset or run back players. |
| Skill test | Opposed d12 roll. |
| Space minute | Game-time unit; a period has 15. |

The ball is a d12; its face is speed. Coaches use an action-selection d6 for secret maneuver choices and d12s for rolls.

## Setup

1. Choose a 6-, 7-, or 9-space board.
2. Toss a coin. Fortune gives the toss to the flipping coach; doom to the opponent. The winner chooses home or visitors. Home kicks off first; visitors kick off the second half.
3. Deal both sides into **2-2-2**: Fullback + Defender in own goal; Midfielder + Playmaker in midfield; Winger + Striker in opponent goal. The other Defender, Playmaker, and Striker go to the bench. Place meeples using coverage.
4. Home, then visitors, take a [Coaching Choice](#coaching-choice). Setup substitutions are unlimited and return players to the bench. Home finishes with a player on kickoff. Final positions become each side's first arrangement.
5. Put the ball, speed 1, on kickoff in home possession. Set clock to 0.

## The turn

1. The possessing team chooses a player on the ball and an action. A [ball carrier](#the-ball-carrier) must act. In range: shoot or maneuver. Outside range: maneuver, or [cede](#ceding-the-ball) if that side still holds its declaration.
2. Resolve the action and any set-up or own-goal roll.
3. Resolve a [loose ball](#loose-ball) if the possessing team has no player on the ball.
4. Resolve a turnover: run back after a steal; reset and offer Coaching Choices after a new play. Then make any outstanding placement.
5. Advance time by the action's cost, minimum 1.
6. At 15, use [last possession](#last-possession).

### The ball carrier

A player specifically left holding the ball takes their team's next turn. A carry lasts one turn; if that player is no longer on the ball, choose normally.

Dribble Advance, Steal Intercept, a completed Low Pass, a received 2-space High Pass, a won long-pass contest, and a loose-ball winner create a carrier. Block Deflect, restarts, kickoffs, and required pickups do not. A carrier is exempt from running back.

Pressure creates one too, but names a different player either side of the Defender's ability: ordinarily the handler, shoved back still holding the ball—including where they survived the own-goal roll—and, where a Defender's Pressure also stole it, the Defender.

## Score attempt

Shoot only from [shooting range](#field-direction-and-shooting-range). Choose a player on the ball; both coaches roll one d12.

| Side | Adds |
| --- | --- |
| Attack | Offensive skill + speed modifier; +3 for Striker off set-up |
| Defense | Full defensive skill of every opposing meeple on the ball's space, plus half the defensive skill—rounded up, per player—of every opposing meeple between the ball and the goal |

Each defender halves their own skill: two 5s in the way add 3 + 3, not 5.

Attack scores on an equal or higher total. A plain shot costs no exhaustion; a set-up shot gives its shooter 1 token after the roll.

Time costs one minute per space to the attacked end, including the starting space. Either result resets speed and starts a new play: a goal gives kickoff to the conceding side; a miss gives the defenders the space nearest their own goal.

## Maneuvers

### 1. Determine the players

The attacker is a possessing-team player on the ball. An opposing player already on the ball challenges automatically—it costs them nothing, so it is not declined. Otherwise defense **may** choose a player in the ball's zone, who moves to the ball and gains 1 token per space, or send nobody rather than pay for the challenge. With no challenger—nobody in the zone, or nobody sent—offense chooses and resolves a maneuver with no reveal or test.

### 2. Select and reveal

With a challenger, both coaches secretly choose a maneuver and reveal together. Each maneuver uses two faces of the selection die.

### 3. Who wins

The ranks form a rock-paper-scissors cycle. Same ranks tie.

| Offense | Block Deflect (D1) | Steal Intercept (D2) | Pressure (D3) |
| --- | --- | --- | --- |
| Low Pass (O1) | Tie | D2 wins | O1 wins |
| Dribble Advance (O2) | O2 wins | Tie | D3 wins |
| High Pass (O3) | D1 wins | O3 wins | Tie |

### 4. Skill test when they tie

Each player gains 1 token. Both roll d12 + attacker offense or challenger defense, plus applicable ability and modifier. A Midfielder adds +3 for Low Pass or Pressure; a Steal Intercept defender adds speed. Higher resolves their maneuver. Re-roll ties and give both another token. Exhausted participants then make an [injury check](#injury-check).

### The six maneuvers

| Maneuver | Rank / die | Effect | Time |
| --- | --- | --- | --- |
| Low Pass | O1, 1–2 | Nearest teammate ahead/behind within 2, or teammate sharing ball; speed +1. | Distance, min. 1 |
| Dribble Advance | O2, 3–4 | Handler and ball forward 1; adjust speed by offensive skill. | 1 |
| High Pass | O3, 5–6 | Throw forward 2–3 (Fullback 4); long throws can be contested. | Distance |
| Block Deflect | D1, 1–2 | Ball back 1 (Fullback 2); speed −1. | 1 |
| Steal Intercept | D2, 3–4 | Turnover; interceptor and ball back 1; adjust speed. | 1 |
| Pressure | D3, 5–6 | Handler and ball back 1; challenger forward 1. | 1 |

### Low Pass

Choose the nearest teammate up to two spaces ahead, nearest up to two behind, or another teammate sharing ball. A nearer teammate blocks a farther one. Choose the receiver if several teammates occupy the destination. The pass must reach a different player.

A shared-space pass advances the passer one space if possible. Increase speed by 1. With no destination, move the ball one space forward, increase speed, and resolve loose. A Winger's completed Low Pass may offer its receiver a [scoring opportunity](#scoring-opportunities) if in range.

### Dribble Advance

Move handler and ball forward one, then adjust speed up or down by up to offense. A Playmaker may advance two spaces.

### High Pass

Choose 2 or 3 spaces forward; a Fullback may choose 4. Offer only distances that land on distinct spaces. Within one space of the attacked end, every throw is an **overshoot** landing on the final space.

| Throw | Landing result |
| --- | --- |
| 2 spaces, teammate there | Received; offer a scoring opportunity. |
| 3–4 spaces, teammate there | Receiver must win a long-pass contest. |
| No teammate there | Loose ball. |

For a long-pass contest, receiver attacks. A defender already there contests automatically; otherwise defense may send a zone player, paying 1 token per space, or decline. No challenger means receiver keeps it. Roll offense versus defense; receiver adds speed. Loss is a steal.

On an overshoot to a teammate, choose the scoring opportunity or contest. Either subtracts speed from receiver's side. Without a teammate, it is loose.

### Block Deflect

Move ball back one (two for Fullback), never past defending end; reduce speed by 1 (minimum 1). Handler stays.

A Block Deflect turns nothing over on its own. Only one case does: the full deflection is clamped **and** a defending player is on the landing space. That side then gets a scoring opportunity, and only for it does possession flip and speed reset—and it is the following shot, not the deflect, that creates the new play. Any other deflect leaves possession alone, so if it left no possessing-team player on the ball, the ball is loose.

### Steal Intercept

Flip possession and reset speed; move interceptor and ball one space back for the new possessing team; then adjust speed by up to interceptor defense. Interceptor carries and does not run back.

### Pressure

Move handler and ball back one, challenger forward one. If handler is nearest own goal, resolve an [own goal](#own-goal). A Defender's won Pressure also steals unless own goal occurs (whether scored or avoided).

## Ball speed, loose balls, and set-ups

### Ball speed

| Speed | 1 | 2–3 | 4–5 | 6–7 | 8–9 | 10–11 | 12 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Modifier | 0 | +1 | +2 | +3 | +4 | +5 | +6 |

Modifier is speed ÷ 2, rounded down. Speed changes only through Low Pass, Dribble Advance, Block Deflect, and Steal Intercept. Every turnover resets speed.

Add speed only to a score attempt, a Steal Intercept test (defender), or a long High Pass contest (receiver). Overshot High Pass subtracts it. Loose-ball contests never use it.

### Loose ball

After every maneuver, the ball is loose if no possessing-team player is on it.

1. **Only opponent present:** they take it immediately.
2. **Empty; both sides can send:** last possessor decides first whether to send a zone player, then other coach decides. Sent players pay 1 token per space. If both arrive, roll a skill test: former possessor offense, other side defense.
3. **Empty; only one sends:** that player recovers without a test.
4. **Nobody sends or neither has a zone player:** out of bounds. Other side gains a new play, then moves any field player to the ball from anywhere for 1 token per space.

Sending nobody is always legal. A loose-ball win by the non-possessing side is a steal, except out of bounds, which is a new play.

### Scoring opportunities

A scoring opportunity is an optional, out-of-turn ordinary shot, only in range. Shooter gets 1 token after the roll; a Striker adds +3.

| Source | Shooter |
| --- | --- |
| Received 2-space High Pass | Receiver |
| Overshot High Pass to teammate | Receiver |
| Winger's Low Pass | Receiver |
| Overshot Block Deflect | Defending player on landing |

Declining costs nothing, except an overshot High Pass, whose alternative is its long-pass contest.

### Own goal

Only overshooting Pressure risks an own goal. Handler rolls 2d12, keeps higher, and adds offense. On 7+, avoid it. The roll costs 1 token but is not a skill test. On failure, opponent scores and conceding side restarts at kickoff, speed 1.

## Turnovers, resets, and running back

Every possession change resets speed.

| Cause | Kind | Consequence |
| --- | --- | --- |
| Steal Intercept, Defender Pressure, lost long pass | Steal | Run back; no Coaching Choice. |
| Loose ball won by other side | Steal | Run back; no Coaching Choice. |
| Goal, own goal, miss, out of bounds | New play | Reset; restarting side may declare. |
| Ceding | Cede | Reset; both sides receive windows. |

An overshot Block Deflect changes possession for its immediate scoring opportunity, but its goal or miss creates the new play.

**Only a turnover moves anyone.** A resolution that leaves possession where it was runs nobody back and resets nobody, however far out of position it left them—a receiver who won their long-pass contest, the defender who walked in and lost it, a side that recovered its own loose ball. Whoever is displaced stays displaced, and pays nothing for it, until a turnover comes.

### Resetting after a new play

Return every fielded meeple to its saved arrangement, free and before Coaching Choices. A run back never changes an arrangement. After a goal, conceding side must also put a player on kickoff, paying 1 token per space. After out of bounds, gaining side makes its required pickup after reset.

### Running back after a steal

Every non-carrier returns to any space in its card's zone, paying 1 token per space. Coach chooses spaces subject to [coverage](#occupancy). Carrier stays with ball and pays nothing.

### Ceding the ball

Outside range, the possessing side may cede rather than maneuver. Two conditions, both required: they are out of range, and they still hold their once-per-half declaration. So a side that has already declared this half cannot cede, and a side that cedes cannot declare for the rest of it. Nothing else has to be true—a side with nobody left to bring on may still cede, since the window is the whole Coaching Choice and not the substitution alone.

Ceding spends that declaration; gives other side possession on same space at speed 1; costs no time and causes no run back; and opens Coaching Choices for ceding side then receiving side, using ordinary half allowances. After both windows, receiving side must move a field player onto an unattended ball, paying 1 token per space.

In last possession, ceding ends the period and opens no windows.

## Exhaustion and injury

A player is **Exhausted** when tokens exceed defense.

| Source | Tokens |
| --- | --- |
| Maneuver test and each re-roll | 1 to each participant |
| Moving in to challenge, recover, or contest | 1 per space |
| Running back | 1 per space |
| Own-goal roll | 1 |
| Scoring opportunity | 1 after roll |

### Injury check

When a skill test resolves, every Exhausted participant rolls d12. Higher than current tokens is safe; otherwise injured. Count tokens gained for that test. Only skill tests cause checks.

### Injured players

Injured players lose all tokens, cannot gain more, and cannot make another check. Until subbed off: against a healthy opponent, a tied maneuver loses outright and a winning maneuver must win a test; in loose-ball or long-pass contests they add no offense or defense, but retain abilities and other modifiers. They need not be removed, but go permanently to back bench if subbed.

**The withheld skill is only ever in those two contests.** Everything else rolls in full, the forced test above included: an injured player made to win a skill test for their own maneuver still adds their offensive or defensive skill to it, and a score attempt is untouched.

The maneuver disadvantage is measured against a healthy opponent, so two cases escape it: both participants injured, which is an ordinary tie and an ordinary win; and an uncontested maneuver, which has no opponent to tie with and nobody to be made to roll, and so succeeds outright as always.

At halftime, every fielded player loses 1 token, then each coach chooses one player to lose 1 more.

## Coaching Choice

A Coaching Choice is a free pause. Take any number of actions in any order, then finish. It cannot put a meeple outside its card's zone or violate [coverage](#occupancy). Final positions become the arrangement—but only where the coach positioned something. A side that makes no positional change keeps the arrangement it already had, whatever open play left its meeples standing on. So a scramble never becomes a shape by default; it takes a coach to set one.

| Action | Rule |
| --- | --- |
| Formation | Re-deal fielded side into a new shape. |
| Substitution | Incoming player inherits outgoing zone and space. |
| Zone assignment | Swap fielded players in different zones, cards and meeples together. |
| Space positioning | Move a meeple within its zone; swap if needed for coverage. |

Shootout window offers substitution only; it neither restores nor saves an arrangement.

### Occasions and declarations

| Occasion | Substitutions | Order | Removed player |
| --- | --- | --- | --- |
| Setup | Unlimited | Kicking side, then other | Bench |
| New play | 2 per half | Declaring side, then reply | Back bench |
| Ceded ball | 2 per half | Ceding side, then receiver | Back bench |
| Halftime | 2, separate | Visitors, then home | Back bench |
| Before shootout | 1, separate | Home, then visitors | Back bench |

At a new play, restarting side may declare once per half. If it does, other side gets a reply; replying does not spend its declaration. Cede is an already-spent declaration. Halftime and shootout windows are independent.

### Changing formation

| Formation | Own goal | Midfield | Opponent's goal |
| --- | ---: | ---: | ---: |
| 2-2-2 | 2 | 2 | 2 |
| 2-3-1 | 2 | 3 | 1 |
| 1-3-2 | 1 | 3 | 2 |

Read formations from own goal forward. Re-deal fielded players by defensive skill, highest first, toward own goal first. Within a zone, place own-goal-nearest outward. Surplus stacks in center of a three-space zone or center-nearer space of a two-space zone; on board-6 midfield, stack toward own goal.

### Who may come on

While bench has a player, substitutions must use it. Once empty, healthy back-bench players may return. Injured players never may. A returning back-bench player loses half tokens, rounded up. No substitute remains only when bench is empty and every back-bench player is injured.

## Clock, halftime, and full time

Every turn costs at least one minute. Clock stops at 15.

### Last possession

When clock reaches 15, finish that action fully, even if it turns over. Whichever team holds the ball once it has resolved has last possession—the side that kept it, or the side a turnover just handed it to. Its next turnover ends the period immediately: no run back, reset, window, or remaining turnover effect.

### Halftime and full time

At halftime: apply recovery; visitors then home take Coaching Choices with two separate substitutions each; visitors finish with a player on kickoff; visitors start second half there at speed 1.

At full time, higher score wins. If tied, home then visitors take one-substitution shootout windows.

## Extreme shootout

Use the six fielded players after shootout substitution. Keep exhaustion and injury; no full-time recovery. Coaches secretly order six players and reveal the top pair.

Each pair rolls d12 + **offense**. Injured players add no skill. Higher scores; ties score for neither side and are not re-rolled. Tests cost no exhaustion, but Exhausted players still make injury checks.

Play six pairings, stopping early if trailing side cannot catch up. If level, play sudden death: each coach secretly chooses an unused player that round. Higher score wins game. After all six, begin a new round. Shootout goals go on scoreboard.

## Quick reference

| Roll | Dice | Result |
| --- | --- | --- |
| Score attempt | 1d12 each | Attack adds offense + speed; defense adds full on the ball, half beyond; ties score. |
| Skill test | 1d12 each | Applicable offense/defense; higher wins; re-roll ties. |
| Own goal | 2d12, keep higher | Add offense; 7+ avoids. |
| Injury check | 1d12 | Higher than token count is safe. |
| Shootout | 1d12 each | Add offense; higher scores; tie stands. |

**Turn:** choose → resolve → loose-ball check → turnover → time → last-possession check.

**Turnover:** reset speed → steal: run back; new play: reset and declaration; cede: reset and both windows.

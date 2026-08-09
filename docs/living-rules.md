# D12 Ball -- living rules

The complete rules of the game as they currently stand. Nothing else lives here: how the
rules got this way, what upstream still says, and what is still unanswered are all in
[rules-log.md](rules-log.md).

These are the **basic mode** rules -- the only mode that exists. Advanced mode (per-team
abilities) is planned and unspecified.

---

## Contents

- [Overview](#overview)
- [Terms](#terms)
- [Components](#components)
- [Setting up a game](#setting-up-a-game)
- [The turn](#the-turn)
- [Score attempt](#score-attempt)
- [Maneuver](#maneuver)
- [The six maneuvers](#the-six-maneuvers)
- [Ball speed](#ball-speed)
- [Loose ball](#loose-ball)
- [Scoring opportunities](#scoring-opportunities)
- [Own goal](#own-goal)
- [Turnovers and running back](#turnovers-and-running-back)
- [Exhaustion and injury](#exhaustion-and-injury)
- [Substitutions](#substitutions)
- [The clock, halftime and full time](#the-clock-halftime-and-full-time)
- [Extreme shootout](#extreme-shootout)
- [Quick reference](#quick-reference)

---

## Overview

D12 Ball is a fast playing fantasy sports game with tense last-ditch efforts and dramatic
comebacks, where two teams of fantasy creatures compete by maneuvering around the field,
manipulating the ball and outwitting the other team on their way to score epic goals.

Two coaches each control a team of nine players. The game runs over two periods of 15 space
minutes. The team with the most goals at the end wins.

## Terms

| Term | Meaning |
|---|---|
| **Space** | One area of the field. The ball and every meeple are always located on a space. |
| **Zone** | A group of adjacent spaces: home goal, midfield, visitors goal. |
| **Shooting range** | The far part of the field, from the middle to the goal a team attacks -- the only place they may [shoot](#score-attempt) from. Measured from the middle of the board, so it is not a zone: see [shooting range](#shooting-range). |
| **Player card** | contain a player's infor including their role, skill scores and ability. Its position on the team board shows the **zone** that player is assigned to. |
| **Meeple** | A player's token on the field. Shows the **space** that player is standing on right now. |
| **Field player** | One of the six players a team has on the field. |
| **Forward / back** | Forward is toward the goal a team is attacking; back is toward the goal it defends. Always relative to the team being spoken about. |
| **Possession** | Which team holds the ball. Tracked separately from the ball's space. |
| **Arrangement** | The spaces a coach last *put* their meeples on -- at setup, a substitution window, or halftime. A [new play](#resetting-after-a-new-play) puts them back on it. |
| **Turnover** | Possession changing hands, for any reason. |
| **Skill test** | The opposed d12 roll used to settle a tied maneuver, a loose ball, and a long High Pass. |
| **Space minute** | The unit of game time. A period is 15 of them. |

## Components

### The field

The field is a row of spaces, numbered left to right. Both coaches use the same numbering;
which team holds the ball is tracked separately, not by which half of a card the ball sits on.

The field comes in three sizes. **7 is the default**; 6 and 9 are variants. Each is divided
into three zones -- home goal, midfield, visitors goal, left to right:

| Board size | Home goal | Midfield | Visitors goal |
|---|---|---|---|
| 6 | 2 spaces | 2 spaces | 2 spaces |
| 7 | 2 spaces | 3 spaces | 2 spaces |
| 9 | 3 spaces | 3 spaces | 3 spaces |

The home team defends the home goal zone and attacks the visitors goal zone; the visiting
team does the reverse.

<a id="shooting-range"></a>
**Shooting range.** A team is **within shooting range** once the ball has passed the middle
of the field, and a [score attempt](#score-attempt) is the only thing that depends on it.
Range is measured from the middle of the *board*, not from a zone boundary -- it is not one
of the three zones, and it cuts across midfield:

| Board size | Visitors in range | Neither | Home in range |
|---|---|---|---|
| 6 | H1 H2 M1 | -- | M2 V1 V2 |
| 7 | H1 H2 M1 | M2 | M3 V1 V2 |
| 9 | H1 H2 H3 M1 | M2 | M3 V1 V2 V3 |

Each team's range is the far end of the field from where they start, so the home team's runs
to the right and the visitors' to the left. On the standard 7-space board it is three spaces,
which is less than half the field.

**A board with an odd number of spaces has a middle space that is in nobody's range** --
boards 7 and 9, where that space is also the [kickoff space](#components). On board 6 the
kickoff space is behind the kicking team's own range. Either way, no restart begins in range.

The board image marks where range begins with a dashed line -- two of them on boards 7 and 9,
either side of the space that is in nobody's.

**Occupancy.** Any meeples may share a space -- opposing or teammates alike -- and ordinary
play stacks them freely. What every deliberate placement -- setup, a substitution window,
halftime, a [run back](#running-back-after-a-steal) -- enforces is coverage, not a limit: a
team comes out of it with **every space of a zone it has players in occupied**, as far as its
players stretch, and any surplus stacked. Under most formation-and-board combinations no zone
ever holds more of a team's players than it has spaces, so that comes to one player per
space; a formation that puts more players in a zone than the zone has spaces -- 2-3-1 or
1-3-2 on board 6, whose midfield has two -- fills every space and doubles up the rest.

**The kickoff space** is where the ball starts every period and every restart after a goal:

- **Board 7 or 9:** the middle space of the board (the middle space of the midfield zone).
- **Board 6:** the midfield space closer to the kicking team's own goal.

The kicking team is whichever team takes possession at that restart.

### Player cards

A player card carries the player's role, skills and ability. The number on the card is the
player's **offensive skill**, 1 to 6. Their **defensive skill** is its d6 inverse -- the two
always sum to 7. The better a player is on offense, the worse they are on defense.

| Role | Offense | Defense | Ability |
|---|---|---|---|
| Fullback | 1 | 6 | Can pass up to 4 with a High Pass. When resolving Block Deflect, the ball goes back 2 spaces. |
| Defender | 2 | 5 | Steals the ball when resolving Pressure. |
| Midfielder | 3 | 4 | +3 on skill tests when attempting Low Pass or Pressure. |
| Playmaker | 4 | 3 | May advance 2 spaces when resolving Dribble Advance. |
| Winger | 5 | 2 | Can set up a scoring opportunity with a Low Pass. |
| Striker | 6 | 1 | +3 on scoring attempts off a set-up. |

Each ability is described in full with the maneuver it modifies, below.

### Teams

There are four teams -- Orange, Teal, Purple and Slime. Each has nine players: one Fullback,
two Defenders, one Midfielder, two Playmakers, one Winger and two Strikers. Six start on the
field and three sit on the bench.

Outside of setup, **no role is tied to any zone or space.** A substitution may leave a role
unfielded, and any card may be assigned to any zone.

### The ball

The ball is a d12, and the number showing is its [speed](#ball-speed), 1 to 12.

### Dice

Each coach has a six-sided **action-selection die** for choosing maneuvers secretly, and
rolls a d12 for every test and attempt in the game.

### Coins

A coin has a **fortune** face and a **doom** face, and is used for the opening toss. Coins
come in denominations (1 or 3, in bronze, silver or gold); the denomination is cosmetic.

### Player boards

Each coach has a player board with these areas:

| Area | Holds |
|---|---|
| Head Coach | The dice used to select maneuvers |
| Bench | Players who have yet to play |
| Back Bench | Injured players, and anyone subbed out |
| Home Goal Zone / Midfield Zone / Visitors Goal Zone | The player cards assigned to that zone |

## Setting up a game

1. **Choose the board size** -- 6, 7 or 9. 7 is the default.
2. **Choose how a tie is settled.** In **league mode** a level score at full time is the
   final result. In **tournament mode** a level score goes to the
   [extreme shootout](#extreme-shootout).
3. **Toss a coin.** Fortune wins the toss for the coach who flipped; doom hands it to their
   opponent. The winner chooses to be the **home** or the **visiting** team. The trade is
   deliberate: home kicks off the first half, the visitors kick off the second, so choosing
   visitor buys the second-half restart.
4. **Assign player cards to zones.** Every game starts in the **2-2-2 formation** -- two
   cards per zone -- dealt as the standard setup, one player of each role:

   | Zone | Players |
   |---|---|
   | Own goal | Fullback, Defender |
   | Midfield | Midfielder, Playmaker |
   | Opponent's goal | Winger, Striker |

   The remaining Defender, Playmaker and Striker go to the bench. A coach who wants a
   different shape changes it at their first [substitution window](#substitutions); nobody
   kicks off in one.
5. **Place meeples.** Each meeple goes on any space within its card's assigned zone, spread
   as [occupancy](#the-field) asks: every space of the zone taken before any space takes a
   second player. Under 2-2-2 that is one per team per space, and a three-space zone is left
   with a space empty. The home team must finish with a player standing on the kickoff space,
   since they kick off. This is each coach's first **arrangement**: every
   [new play](#resetting-after-a-new-play) puts their meeples back on these spaces until a
   substitution window or halftime sets new ones.
6. **Place the ball** showing **1** on the kickoff space, in the home team's possession. Set
   the clock to 0.

## The turn

Each turn runs in this order:

1. **The team in possession chooses** either a [score attempt](#score-attempt) or a
   [maneuver](#maneuver).
2. **Resolve it**, including any scoring opportunity or own-goal roll it produces.
3. **Check for a loose ball.** If the ball's space has no player from the team in possession,
   resolve it as a [loose ball](#loose-ball).
4. **If possession changed hands**, in this order: on a [steal](#steals-and-new-plays),
   every displaced player [runs back](#running-back-after-a-steal). On a
   [new play](#steals-and-new-plays), both sides
   [reset to their coaches' arrangement](#resetting-after-a-new-play), then the side that
   gained the ball may [declare substitutions](#substitutions). Either way, last comes any
   placement the resolution still owes (an out-of-bounds recovery, or filling the kickoff
   space after a goal).
5. **Advance the clock** by the turn's time cost. Time always advances by at least 1 space
   minute, and by 1 per space when the ball travels.
6. The clock stops at 15. Reaching 15 puts the game into
   [last possession](#the-clock-halftime-and-full-time).

## Score attempt

**The team in possession may shoot only from within [shooting range](#shooting-range).** A
shot is a run at the goal, not a punt from the back of the field: a team that has not carried
the ball past the middle of the field has no shot to take, and its turn is a
[maneuver](#maneuver). Range is the whole requirement -- anywhere inside it will do, and the
ball may be shot from the space it is already on.

**Exactly two dice are rolled, one by each coach.**

| Side | Rolls | Adds |
|---|---|---|
| Attack | one d12 | The shooting player's offensive skill, plus the [ball speed modifier](#ball-speed), plus 3 if a Striker is shooting off a set-up |
| Defense | one d12 | The defensive skills of **every** opposing meeple between the ball and the goal being attacked, including any on the ball's own space |

If the attacker's total is **equal to or higher than** the defense's total, they score.
Otherwise it is a missed attempt.

A plain score attempt costs **no exhaustion at all** -- not the shooter, not the defenders in
the way -- and never triggers an injury check, however exhausted anyone involved is. A shot
taken off a [set-up](#scoring-opportunities) costs the shooter 1 exhaust token, taken after
the roll.

**Time.** The attempt costs 1 space minute per space the ball travels, counting the space it
was shot from. A shot from the third space from the end of the field costs 3.

**Cleanup.** Either result turns the ball over and is a [new play](#steals-and-new-plays), so
both restarts reset the sides to their coaches' arrangement and open a substitution window,
and both reset the ball's speed to 1.

| Result | Restart |
|---|---|
| Goal | The scoring team's score goes up 1. The conceding team takes possession on the kickoff space. |
| Miss | The team that avoided conceding takes possession on the space closest to their own goal. |

## Maneuver

Most turns are maneuvers rather than shots. A maneuver runs in four steps.

### 1. Determine the two players

**The attacker** is a player from the team in possession standing on the ball's space. There
is usually only one.

**The challenger** comes from the defending team:

- If one of their players is already standing on the ball's **exact space**, that player is
  the challenger automatically -- no choice, no movement, no exhaustion. At most one of their
  players can be there, so this is never a choice between two.
- Otherwise their coach picks any of their players **in the ball's zone**. That player moves
  to the ball's space and gains **1 exhaust token per space travelled**.
- If the defending team has nobody in the ball's zone, there is no challenger and the
  maneuver **automatically succeeds** for the offense. The attacking coach still picks which
  offensive maneuver it is, and its effect resolves in full -- there is simply nothing to
  reveal it against.

### 2. Select and reveal

Both coaches secretly select a maneuver with their action-selection die -- the attacker an
offensive maneuver, the challenger a defensive one -- then reveal simultaneously. Each
maneuver occupies two faces of the die.

With no challenger there is nobody to reveal against: the attacker picks, nothing is
concealed, and step 3 and step 4 are both skipped -- the maneuver they picked is the one that
resolves.

### 3. Who wins

Maneuvers are ranked 1, 2, 3 on each side, in a rock-paper-scissors cycle. Each offensive
maneuver beats one defensive maneuver, loses to another, and ties with the third.

| | Block Deflect (1) | Steal Intercept (2) | Pressure (3) |
|---|---|---|---|
| **Low Pass (1)** | tie | Steal Intercept wins | Low Pass wins |
| **Dribble Advance (2)** | Dribble Advance wins | tie | Pressure wins |
| **High Pass (3)** | Block Deflect wins | High Pass wins | tie |

The winner resolves their own maneuver's effect. The loser's maneuver does nothing.

### 4. Skill test, when they tie

Two maneuvers of the same rank tie, and the two players challenge each other instead.

- **Each of the two gains 1 exhaust token** for entering the test.
- Each coach rolls **one d12** and adds their player's skill -- offensive for the attacker,
  defensive for the challenger -- plus any ability or game modifier that applies. A
  Midfielder attempting Low Pass or Pressure adds 3. The defense adds the
  [ball speed modifier](#ball-speed) when their maneuver is Steal Intercept.
- Higher total wins, and **resolves their own maneuver's effect**.
- **A tied total is re-rolled.** Both players gain another exhaust token each time, and the
  test is rolled again until it is decided.
- Once the test resolves, any participant who is [exhausted](#exhaustion-and-injury) --
  including one the test itself just pushed over the line -- rolls an injury check.

## The six maneuvers

| Maneuver | Side | Rank | Die | Beats | Time |
|---|---|---|---|---|---|
| Low Pass | offense | 1 | 1-2 | Pressure | distance travelled (min 1) |
| Dribble Advance | offense | 2 | 3-4 | Block Deflect | 1 space minute |
| High Pass | offense | 3 | 5-6 | Steal Intercept | distance travelled (2-4) |
| Block Deflect | defense | 1 | 1-2 | High Pass | 1 space minute |
| Steal Intercept | defense | 2 | 3-4 | Low Pass | 1 space minute |
| Pressure | defense | 3 | 5-6 | Dribble Advance | 1 space minute |

### Low Pass

> Ball to the nearest teammate ahead or behind, max 2 spaces; or to one sharing its space,
> and the passer moves forward 1. Ball speed +1.

A Low Pass has **at most three destinations**, and the attacking coach picks one:

- the **nearest** teammate ahead of the ball, up to 2 spaces away;
- the **nearest** teammate behind the ball, up to 2 spaces away;
- a teammate standing on the ball's **own space**.

**Nearest, not any.** A teammate two spaces ahead stops being a destination the moment
another teammate stands one space ahead. The choice is between directions, not between
distances.

**A pass must reach a different player.** Nobody passes to themselves to keep the ball. A
pass to the ball's own space is legal only when a *second* player of the same team is
standing there.

**Where the destination space holds more than one teammate, the passer says which of them
receives it** -- routine under a formation that stacks. The pick matters: the receiver is
who a Winger's ability offers the shot to.

**Passing across a shared space moves the passer.** The ball has not travelled, so what the
maneuver buys is the passer stepping one space forward; the receiver stays on the ball. At
the far end of the field, where there is nowhere to go, the passer stays put.

**Ball speed increases by 1**, whichever destination is picked.

**With no legal destination** -- no teammate within two spaces in either direction and none
sharing the ball's space -- the ball rolls **one space forward and is loose**, and its speed
still rises by 1. Both sides then contest it as a [loose ball](#loose-ball).

A Low Pass never risks an own goal, whichever direction it goes.

> **Winger ability.** Whenever a Winger completes a Low Pass -- any distance, including 0 --
> the offense may send the receiving player straight into a
> [scoring opportunity](#scoring-opportunities) from wherever the ball landed. There is no
> position requirement of any kind. Declining resolves the Low Pass normally.

### Dribble Advance

> Player and ball move forward 1 space. Manipulate ball speed (up to offensive skill).

The ball handler and the ball both move one space forward. The handler may then change the
ball's speed up or down by up to their offensive skill.

> **Playmaker ability.** A Playmaker may advance **2** spaces instead of 1.

### High Pass

> Ball moves forward 2-3 spaces. 2: received, and may set up for scoring. 3+: receiver must
> win a skill test to keep it, adding ball speed.

The attacking coach chooses the distance: **2 or 3 spaces** forward.

> **Fullback ability.** A Fullback may choose **4** as well.

What happens next depends on the distance and on who is standing where the ball lands:

| Distance | Landing space | Result |
|---|---|---|
| 2 | A teammate is there | **Received.** The offense may take a [scoring opportunity](#scoring-opportunities) with that receiver. Declining ends the maneuver with the ball received normally -- no contest. |
| 3 or 4 | A teammate is there | **The receiver must win a skill test to keep the ball**, even though a teammate caught it. See below. |
| any | Nobody from the offense is there | A [loose ball](#loose-ball), like any other maneuver that overshoots into empty or enemy territory. |

**The long-pass contest.** This is the one place in the game where a maneuver that landed on
a teammate is still contested. The receiver is the offense's contestant automatically. The
defense's contestant is whoever is already standing on that space; if they have nobody there,
their coach may send one player from the ball's zone, at the usual 1 token per space
travelled, or send nobody -- in which case the receiver keeps the ball with no test at all.

The test is the ordinary skill test: offensive skill against defensive skill, and **the
offense adds the [ball speed modifier](#ball-speed)** -- the one contest where a fast ball
helps the side holding it. Winning keeps possession and changes nothing else. Losing is a
turnover.

### Block Deflect

> Ball moves back 1 space. If it overshoots the goal, may set up scoring. Ball speed -1.

The ball moves **one space back** -- toward the goal the team in possession defends -- and
its speed drops by 1 (never below 1). The ball handler does not move.

> **Fullback ability.** A Fullback deflects the ball back **2** spaces instead of 1.

**Overshoot.** If the deflection is clamped short of its full distance -- the ball was
already close enough to the offense's own goal that there was nowhere left to put it -- and a
player from the **defending** team is standing on the space the ball ends on, that sets up a
[scoring opportunity](#scoring-opportunities) for the defense. Possession turns over to them,
the ball's speed resets to 1, and their player shoots at the goal the ball has just reached.
Everything the turnover would otherwise settle waits until that shot has resolved, and the
deflect itself neither resets anyone nor opens a substitution window -- the shot is a goal or
a miss, and that [new play](#steals-and-new-plays) does both.

A Fullback's 2-space deflect uses the same test: it sets up the opportunity when the full
2 spaces is what overshoots, not when 1 space would have.

Block Deflect costs a fixed 1 space minute, whether or not it was clamped and whether or not
a Fullback made it.

### Steal Intercept

> Turnover. Defender and ball move back 1 space. Manipulate ball speed after turnover (up to
> defensive skill).

In this order:

1. **Possession flips** to the intercepting team, and the ball's speed resets to 1 as on any
   turnover.
2. **The intercepting player and the ball each move back one space** -- back in the *new*
   possessing team's direction, toward the goal that team now defends. The ball stays with
   the interceptor.
3. **The interceptor may change the ball's speed** up or down by up to their defensive skill.
   This applies to the reset value of 1, not to whatever the speed was before the steal, so
   the result always lands within their defensive skill of 1.

The player who made the steal is **exempt from running back**; everyone else displaced by the
turnover still runs back as normal.

### Pressure

> Player and ball go back 1 space. Defender moves 1 forward. If it overshoots the goal, own
> goal risk.

The ball handler and the ball move one space back -- toward the goal their team defends --
and the challenger moves one space forward, following them.

**Own goal risk.** If the ball handler is already on the space closest to their own goal, so
that pushing them back further is impossible, the offense must roll to avoid an
[own goal](#own-goal). That takes priority over everything else in this maneuver.

> **Defender ability.** A Defender **also steals the ball** on a won Pressure: the movement
> above still happens, and possession flips in addition. If that same resolution triggers an
> own goal, the own goal takes priority and the steal does not also happen.

## Ball speed

The ball is a d12 and the number showing is its speed, 1 to 12. A faster ball makes scoring
easier and possession harder to keep.

| Ball speed | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Modifier | 0 | +1 | +1 | +2 | +2 | +3 | +3 | +4 | +4 | +5 | +5 | +6 |

The modifier is the speed halved, rounding down.

**Speed changes** only through: Low Pass (+1), Dribble Advance (up or down by the handler's
offensive skill), Block Deflect (-1), and Steal Intercept (up or down by the interceptor's
defensive skill, applied after the reset).

**Every turnover resets the speed to 1** -- a steal, a goal, a missed shot, a lost loose
ball, a lost long High Pass, a Defender's Pressure steal, and the second-half kickoff alike.

**The modifier applies in exactly three places:**

| Where | Who adds it |
|---|---|
| A score attempt | the attacker |
| A skill test where the defense chose Steal Intercept | the defense |
| A long High Pass's contest | the offense |

A genuine loose ball belongs to nobody yet, so neither side adds it there.

## Loose ball

**After every maneuver resolves, check the ball's space.** If it holds no player from the
team in possession, the ball is loose. This is a general check, not just something a pass
landing on an empty space triggers.

Resolve by which players are where:

**1. Only an opposing player is on that exact space.** They win the ball outright -- an
immediate, uncontested turnover. No test and no movement; that player was already standing
there.

**2. The space is empty and both teams have a player in the zone.** Each coach may send one
of their players in that zone. Both chosen players move to the ball's space and gain **1
exhaust token per space travelled**, then roll a skill test: the team that last had
possession uses offensive skill, the other uses defensive skill. Neither side adds the ball
speed modifier. Both players stay on the space whatever happens; the winner takes possession.

**3. The space is empty and only one team has a player in the zone** (or the other declines).
That team takes possession with no skill test. Their coach picks which of their players in
the zone recovers it; that player moves to the ball's space and gains 1 token per space
travelled. If it is the team that did *not* have possession, it is a turnover.

**4. Out of bounds -- neither team has a player in the zone, or neither coach sends one.**
The team that last had possession loses it. This is the one loose ball that is a
[new play](#steals-and-new-plays) rather than a steal -- the ball went dead rather than being
taken -- so both sides reset to their coaches' arrangement and the side that gained it gets a
substitution window. *Then* that side must get one of their field players onto the ball's
space -- from anywhere on the field, not just that zone -- at 1 token per space travelled.
(The placement comes last; done first, the reset would pull that player straight back off the
ball.)

**The team that last had possession answers first, and alone.** Where both coaches have
someone to send, they are asked one at a time, starting with the side losing the ball. The
ball is theirs to lose, and asking both at once would leave the second coach answering the
first coach's pick rather than the position.

**Sending nobody is always allowed.** A coach with a player in the zone may leave them where
they are. Declining costs nothing and moves nobody, and it is a real choice, so a coach with
exactly one candidate is still asked rather than having that player sent automatically. If
the side that last had possession declines and the other sends someone, that side takes the
ball. If both decline, the ball is out of bounds.

## Scoring opportunities

A scoring opportunity sends a player straight into an **ordinary score attempt**, out of turn.
It is always **offered as a choice**; declining resolves the maneuver normally.

**A set-up is offered only where the shot itself is legal** -- with the ball within
[shooting range](#shooting-range). What a set-up buys is a shot *out of turn*, not a shot from
anywhere, so a maneuver that would set one up short of range simply resolves as the maneuver
it was. A Block Deflect that overshoots is never affected: the ball has reached the space
closest to the offense's own goal, which is always deep in the deflecting team's range.

Three things set one up:

| Set-up | Shooter | Requirement |
|---|---|---|
| A **High Pass** of exactly 2 spaces | the receiver | A player from the passing team is standing on the landing space |
| A **Winger's Low Pass** | the receiver | None -- any distance, including 0 |
| A **Block Deflect** that overshoots | the deflecting team's player on that space | The deflect was clamped short, and one of their players is standing there |

The shot itself is an ordinary [score attempt](#score-attempt) in every way, with two
additions:

- **The shooter gains 1 exhaust token, after the roll.**
- **A Striker adds +3** to any scoring attempt off a set-up.

## Own goal

Only **Pressure** risks an own goal, and only on an **overshoot**: the ball handler is already
on the space closest to their own goal, so the push back has nowhere to go. There is no goal
space -- the field is only spaces.

The player who was holding the ball rolls **2d12 at an advantage -- take the higher result --
and adds their offensive skill. 7 or more avoids the own goal.**

The roll costs that player **1 exhaust token whether it succeeds or not**, on top of anything
the maneuver already charged. Like any other exhaustion gain it can push them over their
defensive skill and make them Exhausted, but it is not a skill test, so it owes no injury
check.

If the roll fails, the **opposing team's score goes up 1** and the game restarts exactly as
after any other goal: the conceding team -- the team that was in possession -- takes the ball
on the kickoff space at speed 1, and both sides reset to their coaches' arrangement.

## Turnovers and running back

**A turnover is possession changing hands, for any reason.** Every turnover:

- **resets the ball's speed to 1**;
- **puts players back where they belong** -- which of the two ways below depends on the kind
  of turnover it is.

### Steals and new plays

Every turnover is one of two things, and which it is decides both whether a
[substitution window](#substitutions) opens and how players get back into position:

| The ball changes hands because | Kind | Window | Players |
|---|---|---|---|
| A **Steal Intercept** wins | steal | no | run back |
| A **Defender's Pressure** steals it | steal | no | run back |
| A **loose ball** goes to the team that did not have it -- standing on it, sent for it unopposed, or won on the skill test | steal | no | run back |
| A **long High Pass** contest is lost | steal | no | run back |
| A **goal** | new play | yes | reset |
| An **own goal** | new play | yes | reset |
| A **missed score attempt** | new play | yes | reset |
| The ball goes **out of bounds** | new play | yes | reset |

A **steal** is the other team taking a live ball. Play never stopped, so neither coach gets
the pause: the ball's speed resets, everyone displaced [runs back](#running-back-after-a-steal)
at a token a space, and the game goes straight on.

A **new play** is the ball going dead and being brought back into play. Both sides
[reset to the arrangement their coaches set](#resetting-after-a-new-play), free of exhaustion,
and the side restarting gets a substitution window.

A **Block Deflect that overshoots** turns possession over without being either: the deflecting
team's shot follows immediately, and that shot is a goal or a miss, so the new play -- and its
window -- comes from the shot. The deflect's own turnover does neither.

**Only a turnover moves anyone.** A resolution that leaves possession where it was runs nobody
back, resets nobody and charges nobody, however far out of position it left them -- a receiver
who wins their High Pass contest, or a loose ball the possessing side recovers, both keep the
ball and both skip it. Whoever is displaced stays displaced until a turnover comes.

### Resetting after a new play

A new play puts **every fielded meeple on both sides** back on the space its coach last
**assigned** it -- at [setup](#setting-up-a-game), at their last
[substitution window](#substitutions), or at [halftime](#the-clock-halftime-and-full-time).
That arrangement is the shape a coach chose, and a new play is where the game hands it back.

- **It costs nothing.** No exhaust tokens, however far anyone has to come. This is not players
  running; it is the coach's shape reasserting itself.
- **Nobody chooses anything.** The spaces are whatever they last were, exactly.
- **It happens before the substitution window**, so a coach who declares rearranges from their
  own formation rather than from wherever open play scattered them, and a coach who passes has
  already had everything passing gives them.
- **A run back does not update it.** The scramble a steal forces is not a shape a coach chose,
  so the next new play undoes it. Only setup, a substitution window and halftime set the
  arrangement.

The two placements a restart still owes -- the kickoff space after a goal, and picking up an
out-of-bounds ball -- come *after* the reset and do cost their usual token a space, since
nothing guarantees the coach's arrangement puts anybody on the space in question.

### Running back after a steal

- Every player returns to a space in **the zone their card is assigned to**.
- **1 exhaust token per space travelled**, the same rate a challenger pays walking in.
- The coach **chooses** which space in the zone each of their players runs back to, subject to
  finishing with **no space in the zone left empty while another holds more than one of their
  players**.
  Where a zone has more spaces than players that is a real choice; where the counts match it
  is forced; where it holds more players than spaces, every space has to be covered and the
  surplus stacks wherever the coach likes -- four players into two spaces may finish 3+1 as
  readily as 2+2.
- That requirement is **per team**, and so is "empty": opposing meeples share spaces freely,
  and a space with only an opponent on it still counts as one this team has to cover.
- It therefore **separates teammates who ended up stacked** on one space within their own
  zone, whenever another space in that zone has none of their players on it. Once every space
  in the zone is covered the stack stands -- nobody is moved somewhere that does not help.
- **The stealing player is exempt.** The player who took the ball -- by Steal Intercept, or by
  a Defender's Pressure steal -- stays where they ended up; everyone else displaced still runs
  back. Where a stacked pair has to be separated, the exempt player is the one who stays put.

**After a goal**, once the reset is done, the conceding team must also get a meeple onto the
**kickoff space** to restart -- nothing guarantees their coach's arrangement puts anybody on
it. Whoever is nearest drops back onto it at one token per space.

**During last possession**, a turnover ends the period instead: see
[The clock](#the-clock-halftime-and-full-time).

## Exhaustion and injury

Players gain **exhaust tokens** for effort. A player is **Exhausted** as soon as they hold
**more tokens than their defensive skill**.

**Every way to gain a token:**

| Source | Tokens |
|---|---|
| Entering a maneuver's skill test | 1 each participant |
| Each re-roll of a tied skill test | 1 more each |
| Walking in to challenge a maneuver | 1 per space travelled |
| Contesting or recovering a loose ball | 1 per space travelled |
| Running back | 1 per space travelled |
| Rolling to avoid an own goal | 1, win or lose |
| Shooting off a set-up | 1, after the roll |

A plain score attempt costs nothing, to either side.

**Injury check.** An Exhausted player who takes part in a **skill test** must roll an injury
check when that test resolves: roll a d12, and if the result is **higher than their token
count** they are safe. Otherwise they are injured.

- Exhausted is judged **when the test resolves**, counting every token the player holds by
  then -- including the ones the test itself charged. A player the test pushed over their own
  defensive skill is exhausted for that same test and rolls its check. There is no snapshot
  of who was exhausted going in.
- **Only skill tests trigger injury checks.** Score attempts never do.

**Injured players:**

- immediately **lose all their exhaust tokens** and are no longer Exhausted;
- **cannot gain further tokens** and make no further injury checks;
- are **disadvantaged** until subbed off, in both of the ways a maneuver can be decided:
  - **A tie is a loss.** When their maneuver ties the opponent's, the injured player loses it
    outright and the opponent resolves their own maneuver's effect. There is no skill test, so
    neither player gains the token that entering one costs.
  - **A win has to be rolled for.** When their maneuver beats the opponent's outright, it does
    not simply win: the two roll a [skill test](#4-skill-test-when-they-tie), and the injured
    player must win it for their maneuver to stick. If they lose it, the opponent's maneuver
    resolves instead, even though it lost the ranking.
  - That skill test is an ordinary one in every other respect. In particular **a tied total is
    re-rolled**, as usual, until the test is decided;
  - **Both injured is neither disadvantaged.** When both participants are injured the tie is an
    ordinary tie and a decisive maneuver an ordinary win, because the disadvantage is measured
    against a healthy opponent and there is not one.
  - **An unchallenged maneuver still succeeds outright.** With no defender in the ball's zone
    there is nobody to tie with and no test they can be made to roll, so neither half of this
    bites;
- **add no skill modifier in a contest** -- keeping a long [High Pass](#high-pass), or
  contesting a [loose ball](#loose-ball). Their offensive or defensive skill does not go on the
  roll at all: they roll the bare d12. **It is only the skill.** Every other modifier still
  applies, notably the [ball speed modifier](#ball-speed) a receiver gets for keeping a long
  High Pass, and so does any role ability. Nothing outside a contest is affected: a maneuver's
  [skill test](#4-skill-test-when-they-tie) and a [score attempt](#score-attempt) are rolled as
  normal, so a Midfielder keeps their +3 on a Low Pass and a Striker keeps theirs off a set-up.
  (The [extreme shootout](#extreme-shootout) withholds the skill the same way; it says so
  there.);
- **do not have to be substituted.** Nothing compels their team to get them off. A coach may
  leave an injured player on the field, disadvantaged, for the rest of the game, and spend
  their declaration on something else;
- once subbed off, go to the **back bench and can never return**.

**Halftime recovery:** every fielded player loses 1 token, and each coach picks one of their
fielded players to lose an extra one.

## Substitutions

**A team may declare substitutions once per half**, when they take the ball for a
[new play](#steals-and-new-plays) -- a goal, an own goal, a missed attempt, or a ball out of
bounds. A steal opens no window, however the ball was taken.

**The declaring team** may:

- **sub out up to 2** of their field players, and
- **rearrange** their cards' zone assignments, and then place meeples freely.

**The other team may then reply**, subbing **1** player and rearranging their own. The reply
costs the answering side nothing -- it does not spend their own declaration -- so a team can
normally substitute twice in a half: once declaring, once replying. If the declaring team
passes, the reply goes with it; the reply exists only to answer a declaration.

**The window opens after the reset.** Both sides are already standing on the arrangement
their coaches set by the time the window is offered, so a coach who declares rearranges from
their own formation, and a coach who passes keeps it.

**Rearranging** moves cards between zones freely and **costs no exhaustion** -- the one way a
meeple moves in this game without paying per space. It is also the only way to change
formation, and the whole of it: every game kicks off in 2-2-2, and a rearrangement may leave
the team in any of the three.

| Formation | Own goal | Midfield | Opponent's goal |
|---|---|---|---|
| 2-2-2 | 2 | 2 | 2 |
| 2-3-1 | 2 | 3 | 1 |
| 1-3-2 | 1 | 3 | 2 |

The numbers read from the team's own goal forward, and each coach chooses their own. On board
6, whose midfield has two spaces, 2-3-1 and 1-3-2 put more cards in midfield than it has
spaces, which is what [occupancy](#the-field) is written for: the zone fills both spaces and
stacks the surplus. On board 7 or 9 every shape fits one card a space.

**Whatever a side finishes the window standing on becomes their arrangement**, and every
[new play](#resetting-after-a-new-play) from then on puts them back on it. A side that passes
sets nothing and keeps the arrangement it had.

Which card goes where is the coach's, not the formation's -- it fixes only how many go in
each zone. Once assignments are settled, the team places its meeples anywhere within their
new zones, subject to occupancy, still free. Where two zones are already full, two meeples
simply trade places.

Nothing requires a team to keep one of each role on the field. A substitution may leave a
role unfielded -- and has to be able to, since every bench is a Defender, a Playmaker and a
Striker and so could never replace a Fullback, Midfielder or Winger in kind.

**The two pools.** The bench and the back bench are separate, and this is the whole of the
"players who are subbed out cannot be subbed back in" rule:

- Anyone subbed out goes to the **back bench**, injured or not. The bench only ever drains.
- While anyone is on the bench, a team may sub in **only** from the bench.
- The **back bench may be drawn from only when the bench is empty and the team is subbing for
  an injured player.**
- **Injured players go to the back bench and can never be subbed in**, whatever the bench
  looks like.

**A player returning from the back bench loses half their exhaust tokens, rounded up.** They
are Exhausted or not according to what remains -- a player with enough tokens comes back still
exhausted.

**Halftime is not a declaration.** Each coach simply gets a declaring team's allowance -- up to
two swaps and a rearrangement -- independently, with no reply for the other team, and using it
does **not** spend that side's once-a-half declaration. Both sides still hold theirs for the
second half's open play.

## The clock, halftime and full time

Time advances every turn, by **at least 1 space minute**, and by 1 per space whenever the ball
travels. The clock stops at 15.

**Last possession.** When the clock reaches 15, the period is in **last possession**. Play
continues as normal until the ball turns over; when the team holding it loses possession, the
period ends.

- **The maneuver that takes the clock to 15 never ends the period, even when it is itself a
  turnover.** Last possession is the possession that *starts* at 15, so a steal, a goal or a
  missed shot that brings the clock up to 15 resolves in full -- run back or reset included --
  and hands last possession to whichever side it gave the ball to.
- **A turnover while last possession is already in force ends the period immediately.** No run
  back, no reset, no substitution window, and no resolution of whatever the causing maneuver
  still owed -- a Steal Intercept's
  fallback move and speed choice included. Play goes straight to halftime or full time.

**Halftime**, after the first period, in this order:

1. Every fielded player loses **1** exhaust token.
2. Each coach picks one of their fielded players to lose **1 more**.
3. Each coach may substitute and rearrange, as above -- independently of the other, with no
   reply, and without spending their once-a-half declaration.
4. Each coach may **reposition any of their fielded meeples to any space on the board**, in
   any zone, at no exhaustion cost. This is the only time placement is not zone-locked. The
   zone is free but the space is not: [occupancy](#the-field) still applies, so a coach may
   not leave a space of a zone they are standing in empty in order to stack elsewhere in it.
   The visiting coach must finish with a player on the kickoff space, since they kick off.
   Where each side finishes is their arrangement for the second half.
5. The second half starts with the **visiting team in possession on the kickoff space**, ball
   speed 1.

**Full time.** After the second period, the higher score wins.

- **League mode:** a level score is a tie, and the game ends there.
- **Tournament mode:** a level score goes to the [extreme shootout](#extreme-shootout).

## Extreme shootout

Tournament mode only, and only on a tie at full time.

Each coach secretly arranges their team of six players in any order they wish. Once the order
is set they may look at it but not reorder it.

Both coaches then reveal their top card simultaneously. Those two players roll a skill test,
each adding their **offensive** skill -- except an injured player, who adds no
[skill modifier](#exhaustion-and-injury) and rolls the bare d12. The winner scores a goal; a
tie scores for nobody.

This repeats for all six players, unless one team is already ahead by more goals than the
other can still score with the attempts remaining (leading 4-1 after five, there is no need to
roll a sixth). Six clashes is one **round**.

If a round ends level -- most commonly 3-3 -- the shootout continues one clash at a time. Each
coach chooses and simultaneously reveals one player who has not yet gone this round; they roll,
and if either side wins, they score and win the game.

## Quick reference

**Roles**

| Role | Off | Def | Ability |
|---|---|---|---|
| Fullback | 1 | 6 | High Pass up to 4; Block Deflect goes back 2 |
| Defender | 2 | 5 | Steals the ball on a won Pressure |
| Midfielder | 3 | 4 | +3 on skill tests for Low Pass and Pressure |
| Playmaker | 4 | 3 | Dribble Advance may go 2 spaces |
| Winger | 5 | 2 | Low Pass may set up a scoring opportunity |
| Striker | 6 | 1 | +3 on scoring attempts off a set-up |

**Maneuvers**

| Maneuver | Rank | Die | Effect | Time |
|---|---|---|---|---|
| Low Pass | O1 | 1-2 | Ball to the nearest teammate ahead or behind, max 2 spaces; or to one sharing its space, and the passer moves forward 1. Ball speed +1. | distance |
| Dribble Advance | O2 | 3-4 | Player and ball move forward 1 space. Manipulate ball speed (up to offensive skill). | 1 |
| High Pass | O3 | 5-6 | Ball moves forward 2-3 spaces. 2: received, and may set up for scoring. 3+: receiver must win a skill test to keep it, adding ball speed. | distance |
| Block Deflect | D1 | 1-2 | Ball moves back 1 space. If it overshoots the goal, may set up scoring. Ball speed -1. | 1 |
| Steal Intercept | D2 | 3-4 | Turnover. Defender and ball move back 1 space. Manipulate ball speed after turnover (up to defensive skill). | 1 |
| Pressure | D3 | 5-6 | Player and ball go back 1 space. Defender moves 1 forward. If it overshoots the goal, own goal risk. | 1 |

Same rank ties and goes to a skill test. O1 beats D3, O2 beats D1, O3 beats D2.

**Rolls**

| Roll | Dice | Attack adds | Defense adds | Threshold |
|---|---|---|---|---|
| Score attempt | 1 each | Offensive skill + ball speed modifier (+3 Striker off a set-up) | Defensive skills of every meeple between ball and goal | Attack >= defense scores |
| Skill test | 1 each | Offensive skill | Defensive skill | Higher wins; tie re-rolls |
| Own goal | 2d12, take the higher | Offensive skill | -- | 7+ avoids |
| Injury check | 1 d12 | -- | -- | Higher than the token count is safe |

A score attempt -- off a set-up or not -- may only be taken from within
[shooting range](#shooting-range).

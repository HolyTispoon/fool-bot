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
- [Coaching Choice](#coaching-choice)
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
| **Player card** | contain a player's information including their role, skill scores and ability. Its position on the team board shows the **zone** that player is assigned to. |
| **Meeple** | A player's token on the field. Shows the **space** that player is standing on right now. |
| **Field player** | One of the six players a team has on the field. |
| **Forward / back** | Forward is toward the goal a team is attacking; back is toward the goal it defends. Always relative to the team being spoken about. |
| **Possession** | Which team holds the ball. Tracked separately from the ball's space. |
| **Ball carrier** | The individual player holding the ball, when the last resolution left it with somebody in particular. They take their team's next turn: see [the ball carrier](#the-ball-carrier). |
| **Arrangement** | The spaces a coach last *put* their meeples on, at a [Coaching Choice](#coaching-choice). A [new play](#resetting-after-a-new-play) puts them back on it. |
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

#### Shooting range

A team is **within shooting range** once the ball has passed the middle
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
boards 7 and 9, where that space is also the [kickoff space](#the-kickoff-space). On board 6 the
kickoff space is behind the kicking team's own range. Either way, no restart begins in range.

The board image marks where range begins with a dashed line -- two of them on boards 7 and 9,
either side of the space that is in nobody's.

#### Occupancy

Any meeples may share a space -- opposing or teammates alike -- and ordinary
play stacks them freely. What every deliberate placement -- a
[Coaching Choice](#coaching-choice), a [run back](#running-back-after-a-steal) -- enforces is
coverage, not a limit: a
team comes out of it with **every space of a zone it has players in occupied**, as far as its
players stretch, and any surplus stacked. Under most formation-and-board combinations no zone
ever holds more of a team's players than it has spaces, so that comes to one player per
space; a formation that puts more players in a zone than the zone has spaces -- 2-3-1 or
1-3-2 on board 6, whose midfield has two -- fills every space and doubles up the rest.

#### The kickoff space

The kickoff space is where the ball starts every period and every restart after a goal:

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

### Team boards

Each coach has a team board with these areas:

| Area | Holds |
|---|---|
| Head Coach | The dice used to select maneuvers |
| Bench | Players who have yet to play |
| Back Bench | Injured players, and anyone subbed out |
| Home Goal Zone / Midfield Zone / Visitors Goal Zone | The player cards assigned to that zone |

## Setting up a game

1. **Choose the board size** -- 6, 7 or 9. 7 is the default.
2. **Toss a coin.** Fortune wins the toss for the coach who flipped; doom hands it to their
   opponent. The winner chooses to be the **home** or the **visiting** team. The trade is
   deliberate: home kicks off the first half, the visitors kick off the second, so choosing
   visitor buys the second-half restart.
3. **Deal both teams out.** Every team starts in the **2-2-2 formation** -- two cards per
   zone -- dealt as the standard setup, one player of each role:

   | Zone | Players |
   |---|---|
   | Own goal | Fullback, Defender |
   | Midfield | Midfielder, Playmaker |
   | Opponent's goal | Winger, Striker |

   The remaining Defender, Playmaker and Striker go to the bench. Each meeple goes on a
   space within its card's assigned zone, spread as [occupancy](#occupancy) asks: every space
   of the zone taken before any space takes a second player. Under 2-2-2 that is one per team
   per space, and a three-space zone is left with a space empty. In basic mode both teams are
   identical, so both are dealt the same way.
4. **Each coach takes a [Coaching Choice](#coaching-choice)** -- home first, since they kick
   off, then the visitors. Substitutions are unlimited here and a player taken off goes back
   to the bench: the game has not started, so nobody is spent and nothing is used up. A coach
   happy with the standard deal simply finishes without changing anything.

   The home team must finish with a player standing on the kickoff space, since they kick
   off. Where each side finishes is its first **arrangement**: every
   [new play](#resetting-after-a-new-play) puts their meeples back on these spaces until
   another Coaching Choice sets new ones.
5. **Place the ball** showing **1** on the kickoff space, in the home team's possession. Set
   the clock to 0.

## The turn

Each turn runs in this order:

1. **The team in possession chooses** either a [score attempt](#score-attempt) or a
   [maneuver](#maneuver), and which of their players on the ball's space takes it -- unless
   there is a [ball carrier](#the-ball-carrier), who takes it themselves.
2. **Resolve it**, including any scoring opportunity or own-goal roll it produces.
3. **Check for a loose ball.** If the ball's space has no player from the team in possession,
   resolve it as a [loose ball](#loose-ball).
4. **If possession changed hands**, in this order: on a [steal](#steals-and-new-plays),
   every displaced player [runs back](#running-back-after-a-steal). On a
   [new play](#steals-and-new-plays), both sides
   [reset to their coaches' arrangement](#resetting-after-a-new-play), then the side that
   gained the ball may declare a [Coaching Choice](#coaching-choice). Either way, last comes any
   placement the resolution still owes (an out-of-bounds recovery, or filling the kickoff
   space after a goal).
5. **Advance the clock** by the turn's time cost. Time always advances by at least 1 space
   minute, and by 1 per space when the ball travels.
6. The clock stops at 15. Reaching 15 puts the game into
   [last possession](#the-clock-halftime-and-full-time).

### The ball carrier

**The ball is carried by a player, not held by a space.** When a resolution leaves the ball
with somebody in particular -- the player who dribbled it there, the one who was shoved back
still holding it, the one who took it off them, the one it was passed to -- that player is the
**ball carrier**, and they take their team's next turn. Their coach does not choose again.

Without a carrier, the coach picks any of their players on the ball's space, as they always
have. A carrier is one of those players too; the rule takes the choice away, not the ball.

| The resolution | Carrier |
|---|---|
| **Dribble Advance** wins | The handler, who moved with the ball |
| **Pressure** wins | The handler, shoved back still holding it -- including when the own-goal roll is survived |
| **Pressure** wins for a **Defender** | The Defender, who stole it |
| **Steal Intercept** wins | The interceptor |
| **Low Pass** completes | The receiver -- the player the passer aimed at, which is the same player a Winger's set-up would offer the shot to |
| **High Pass** of 2 is received | The receiver, whether or not the set-up is offered or taken |
| A **long High Pass contest** is settled | Whoever won it -- the receiver who kept the ball, or the defender who took it |
| A **[loose ball](#loose-ball)** is settled | Whoever won it, on the skill test or unopposed |

**A contest is won by a player, not by a team.** Both contests end with one named player
standing on the ball having just fought for it, so both name a carrier however they were
settled -- on the roll, or because only one side sent anybody.

**Everything else leaves nobody carrying it**, and the coach chooses:

- a **[new play](#steals-and-new-plays)** and the [reset](#resetting-after-a-new-play) it
  brings, and the kickoff that starts each period -- the ball went dead;
- the two placements a restart owes -- **picking up an out-of-bounds ball**, and **filling the
  kickoff space** after a goal -- where the coach is already choosing who goes to the ball;
- a **Block Deflect**, which sends the ball back to a space rather than to a player.

**A carry lasts exactly one turn.** It is set by the resolution that ends a turn and spent by
the turn that follows; nothing carries over further than that.

**Carrying the ball is also what exempts a player from
[running back](#running-back-after-a-steal)**, so nothing that follows a turnover can move the
carrier off the ball before their turn comes. The two are one rule read from either end: the
ball's holder keeps it, and keeping it is why they stay put.

**A carrier who is somehow no longer on the ball when their turn comes does not carry it**,
and their coach chooses from whoever is.

**A carrier still chooses their action.** They may shoot as readily as maneuver, subject to
[shooting range](#shooting-range) like anyone else. What is fixed is who acts, not what they
do.

## Score attempt

**The team in possession may shoot only from within [shooting range](#shooting-range).** A
shot is a run at the goal, not a punt from the back of the field: a team that has not carried
the ball past the middle of the field has no shot to take, and its turn is a
[maneuver](#maneuver). Range is the whole requirement -- anywhere inside it will do, and the
ball may be shot from the space it is already on.

**Exactly two dice are rolled, one by each coach.**

| Side | Rolls | Adds |
|---|---|---|
| Attack | one d12 | The shooting player's offensive skill, plus the [ball speed modifier](#ball-speed) -- *minus* it, off a [High Pass that overshoots](#high-pass) -- plus 3 if a Striker is shooting off a set-up |
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
is usually only one, and where there is a [ball carrier](#the-ball-carrier) it is them.

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

**Only a distance that fits on the field is offered.** A longer pass that lands where a shorter
one already would is the same pass at a disadvantage -- it counts as an overshoot, so it pays
the [ball speed modifier](#ball-speed) the wrong way round and owes a contest the shorter one
does not. So a coach three spaces from the end of the field chooses 2 or 3 and a Fullback is
not offered 4; two spaces from the end, 2 is the only choice there is.

**With the ball 0 or 1 spaces from the end of the field there is no choice at all.** Every
distance lands on the same space, so the pass is an **overshoot** before anyone picks anything,
and it is resolved as one -- see below. (From the home side's end, that is the ball on H1 or H2
for a team attacking the home goal.)

What happens next depends on the distance and on who is standing where the ball lands:

| Distance | Landing space | Result |
|---|---|---|
| 2 | A teammate is there | **Received.** The offense may take a [scoring opportunity](#scoring-opportunities) with that receiver. Declining ends the maneuver with the ball received normally -- no contest. |
| 3 or 4 | A teammate is there | **The receiver must win a skill test to keep the ball**, even though a teammate caught it. See below. |
| any | Nobody from the offense is there | A [loose ball](#loose-ball), like any other maneuver that overshoots into empty or enemy territory. |

**Overshoot.** A pass is an overshoot when it is clamped short of the distance thrown -- the
ball ran out of field. Since only a distance that fits is ever offered, that means one thing:
**the ball was 0 or 1 spaces from the end**, so no distance fitted and none was asked for. The
ball ends on the space closest to the goal being attacked.

If a player from the **passing** team is standing on that space, the offense chooses between
two things, and **both pay the [ball speed modifier](#ball-speed) against them** -- the pass
arrived faster than anyone could settle it:

| Choice | What it is |
|---|---|
| **Take the shot** | A [scoring opportunity](#scoring-opportunities) with that receiver, with the modifier subtracted from the attempt |
| **Contest for the ball** | The long-pass contest below, with the modifier subtracted from the receiver's side of it |

There is no third option that settles the ball quietly: the receiver either shoots at a
disadvantage or fights to keep what they caught.

An overshoot with nobody from the passing team on that space sets nothing up and is a
[loose ball](#loose-ball) like any other, as the table says. A pass that cannot move the ball
at all -- it is already on the last space -- is an overshoot like any other.

**The long-pass contest.** This is the one place in the game where a maneuver that landed on
a teammate is still contested. The receiver is the offense's contestant automatically. The
defense's contestant is whoever is already standing on that space; if they have nobody there,
their coach may send one player from the ball's zone, at the usual 1 token per space
travelled, or send nobody -- in which case the receiver keeps the ball with no test at all.

The test is the ordinary skill test: offensive skill against defensive skill, and **the
offense adds the [ball speed modifier](#ball-speed)** -- the one contest where a fast ball
helps the side holding it. Winning keeps possession and changes nothing else. Losing is a
turnover.

**An overshoot that turns down its shot lands here**, with the modifier subtracted rather than
added. That is the second half of the overshoot's own choice, not a fallback: turning down the
shot does not settle the ball.

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

**One thing subtracts it instead.** A [High Pass that overshoots](#high-pass) pays the modifier
the other way round -- the ball came in too fast to settle, so the speed that would have helped
is what makes it hard to do anything with. That holds for both of the places the overshoot can
lead: the shot it sets up, and the long-pass contest a declined set-up falls into. Nothing else
in the game subtracts it, and the defense's Steal Intercept modifier is never affected -- the
intercept is settled before any pass is thrown.

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
it was. **An overshoot is never affected**, whichever maneuver it was: the ball has reached the
space closest to one goal or the other, which is always deep inside the shooting team's range.

Four things set one up:

| Set-up | Shooter | Requirement |
|---|---|---|
| A **High Pass** of exactly 2 spaces | the receiver | A player from the passing team is standing on the landing space |
| A **High Pass** that overshoots | the receiver | The ball was 0 or 1 spaces from the end, and a player from the passing team is standing where it lands |
| A **Winger's Low Pass** | the receiver | None -- any distance, including 0 |
| A **Block Deflect** that overshoots | the deflecting team's player on that space | The deflect was clamped short, and one of their players is standing there |

The shot itself is an ordinary [score attempt](#score-attempt) in every way, with two
additions:

- **The shooter gains 1 exhaust token, after the roll.**
- **A Striker adds +3** to any scoring attempt off a set-up.

An overshot High Pass adds a third: the [ball speed modifier](#ball-speed) is **subtracted**
from that shot rather than added to it. Nothing else about the attempt changes, and the
Striker's +3 is paid in full.

**Declining costs nothing and settles the ball, with one exception**: an overshot High Pass is
a shot or a [long-pass contest](#high-pass), so declining lands in the contest instead.

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
[substitution window](#coaching-choice) opens and how players get back into position:

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
**assigned** it, at their last [Coaching Choice](#coaching-choice). That arrangement is the
shape a coach chose, and a new play is where the game hands it back.

- **It costs nothing.** No exhaust tokens, however far anyone has to come. This is not players
  running; it is the coach's shape reasserting itself.
- **Nobody chooses anything.** The spaces are whatever they last were, exactly.
- **It happens before the substitution window**, so a coach who declares rearranges from their
  own formation rather than from wherever open play scattered them, and a coach who passes has
  already had everything passing gives them.
- **A run back does not update it.** The scramble a steal forces is not a shape a coach chose,
  so the next new play undoes it. Only a [Coaching Choice](#coaching-choice) sets the
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
- **The player holding the ball is exempt.** Whoever the turnover left
  [carrying](#the-ball-carrier) it stays where they ended up -- the interceptor, the Defender
  who stole it on a Pressure, the winner of a loose ball or a long High Pass. Running them
  back would move them off the ball they are holding and charge them for it. Everyone else
  displaced still runs back, and where a stacked pair has to be separated, the exempt player
  is the one who stays put.
- **A new play exempts nobody**, because nobody is carrying a dead ball. The
  [reset](#resetting-after-a-new-play) moves both sides whatever they were doing.

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

## Coaching Choice

**A Coaching Choice is the pause in which a coach may change their team**, and it is the same
four actions wherever it is offered. A coach takes as many of them, in any order, as they
like, and finishes when they are done. All four are **free of exhaustion** -- a Coaching
Choice is the one way a meeple moves in this game without paying per space.

| Action | What it does |
|---|---|
| **Formation** | Change the shape the team is in. Cards and meeples are then re-dealt automatically -- see [changing formation](#changing-formation). |
| **Substitution** | Take a field player off for one off the bench. The player coming on inherits the outgoing player's zone assignment and stands on their space. |
| **Zone assignment** | Exchange two field players in different zones. Both the cards and the meeples trade places, so the shape is unchanged and nobody is left standing outside their zone. |
| **Space positioning** | Move one meeple to another space in its own assigned zone. If that space is taken and the meeple is the only one of its team on the space it leaves, the two trade places instead. |

Only a formation change and a zone assignment move a card between zones; space positioning
never does. So a coach's cards and their meeples never disagree: **a Coaching Choice cannot
leave a meeple standing outside its own assigned zone**, and every arrangement one can reach
satisfies [occupancy](#occupancy) as a matter of course.

**Whatever a side finishes standing on becomes their arrangement**, and every
[new play](#resetting-after-a-new-play) from then on puts them back on it. A side that
declines the offer sets nothing and keeps the arrangement it had.

**A Coaching Choice opens on that arrangement**, whichever occasion it is: the side takes the
field on the spaces its coach last set, free of exhaustion, before the first choice is made.
A new play has [already reset](#resetting-after-a-new-play) both sides by the time it offers
the window, so this is only ever felt at halftime, where the first half ended wherever it
ended. A coach rearranges from their own shape and never from a scramble open play left them
in.

### When a Coaching Choice is offered

Three occasions offer it, and they differ only in **how many substitutions** they allow and
in who takes their turn first. The two coaches never coach at the same time.

| Occasion | Substitutions | Order | A player taken off goes to |
|---|---|---|---|
| [Setting up](#setting-up-a-game) | unlimited | the side kicking off, then the other | the **bench** |
| A [new play](#steals-and-new-plays) | out of that side's 2 for the half | the declaring side, then the other | the back bench |
| [Halftime](#the-clock-halftime-and-full-time) | 2, its own allowance | visitors, then home | the back bench |

**Setup is before the game**, so nobody has played and nobody is spent: substitutions are
unlimited and a player taken off goes back to the bench, where they can be brought on again.
This is the one exception to the two-pool rule below.

**A new play** -- a goal, an own goal, a missed attempt, or a ball out of bounds -- offers the
window to the side taking the ball. A steal opens no window, however the ball was taken.

- **A side may declare once per half.** The side taking the ball is offered the window; if
  they take it, the other coach gets one too when they have finished. If they pass, the reply
  goes with it -- the reply exists only to answer a declaration.
- **The window opens after the reset**, so both sides are already standing on the arrangement
  their coaches set by the time it is offered.
- Answering someone else's declaration does not spend a side's own, so a coach who has already
  declared this half can still be offered the window as a reply -- with whatever is left of
  their two substitutions, which may be none.

**Halftime is not a declaration.** Each coach gets one independently, with no reply, and it
does not spend that side's once-a-half declaration. Its two substitutions are **its own
allowance**, not drawn from either half's, so a side that spends two in each half and two at
halftime substitutes six times in a game.

### Changing formation

Every game kicks off in **2-2-2**, and a Coaching Choice is the only way to leave it.

| Formation | Own goal | Midfield | Opponent's goal |
|---|---|---|---|
| 2-2-2 | 2 | 2 | 2 |
| 2-3-1 | 2 | 3 | 1 |
| 1-3-2 | 1 | 3 | 2 |

The numbers read from the team's own goal forward, and each coach chooses their own. On board
6, whose midfield has two spaces, 2-3-1 and 1-3-2 put more cards in midfield than it has
spaces, which is what [occupancy](#occupancy) is written for: the zone fills both spaces and
stacks the surplus. On board 7 or 9 every shape fits one card a space.

**Changing formation deals the whole side out again**, cards and meeples both, so a coach is
never left to fill six slots by hand:

- The six field players are sorted by **defensive skill, highest first**, and dealt into the
  zones from the coach's own goal forward. The best defenders end up furthest back.
- Within a zone, they are placed from the space nearest that coach's own goal outward, one to
  a space, until every space of the zone is taken.
- Any surplus stacks on **one** space: the middle space of a three-space zone, or, in a
  two-space zone, the one nearer the middle of the board. Board 6's midfield is the only zone
  whose two spaces are equally near it, and there the surplus stacks on the space nearer that
  coach's own goal.

A coach who wants a different card in a different place uses **zone assignment** and **space
positioning** afterwards. Choosing the formation the team is already in changes nothing.

### Who may come on

Nothing requires a team to keep one of each role on the field. A substitution may leave a
role unfielded -- and has to be able to, since every bench is a Defender, a Playmaker and a
Striker and so could never replace a Fullback, Midfielder or Winger in kind.

**The two pools.** The bench and the back bench are separate, and this is the whole of the
"players who are subbed out cannot be subbed back in" rule:

- Anyone subbed out goes to the **back bench**, injured or not -- except at
  [setup](#setting-up-a-game), where they go back to the bench. The bench only ever drains.
- While anyone is on the bench, a team may sub in **only** from the bench.
- The **back bench may be drawn from only when the bench is empty and the team is subbing for
  an injured player.**
- **Injured players go to the back bench and can never be subbed in**, whatever the bench
  looks like.

**A player returning from the back bench loses half their exhaust tokens, rounded up.** They
are Exhausted or not according to what remains -- a player with enough tokens comes back still
exhausted.

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
3. Each coach takes a [Coaching Choice](#coaching-choice) -- the **visitors first**, since
   they kick off the second half, then the home coach. Each gets **two** substitutions of
   halftime's own allowance, and neither spends their once-a-half declaration, so both go
   into the second half still holding it.

   Each side takes the field on the arrangement its coach last set, free of exhaustion, as
   [any Coaching Choice opens](#coaching-choice): the first half ended wherever it ended, and
   nobody coaches out of a scramble.

   The visiting coach must finish with a player on the kickoff space, since they kick off.
   Where each side finishes is their arrangement for the second half.
4. The second half starts with the **visiting team in possession on the kickoff space**, ball
   speed 1.

**Full time.** After the second period, the higher score wins. **A level score goes to the
[extreme shootout](#extreme-shootout)**, in every game: there is no game in which a tie is
allowed to stand.

## Extreme shootout

How a game level at full time is settled. It is played by **the six players each team has on
the field** at the whistle, in the state the second period left them -- exhaustion counts,
injuries and all. Nobody comes on for it and nobody is substituted.

**Nobody recovers exhaustion at full time.** Halftime takes a token off every fielded player
and a second off one of them; the whistle takes nothing off anybody. A side that finished the
second half with players over their defensive skill goes to the shootout with them still
**Exhausted**, owing an injury check on every test they take part in.

Each coach secretly arranges their six in any order they wish. Once the order is set they may
look at it but not reorder it.

Both coaches then reveal their top card simultaneously. Those two players roll a
[skill test](#4-skill-test-when-they-tie), each adding their **offensive** skill -- except an
injured player, who adds no [skill modifier](#exhaustion-and-injury) and rolls the bare d12.
The winner scores a goal; **a tie scores for nobody and is not re-rolled**, which is the one
place in the game a tied skill test is left tied.

**A shootout skill test costs no exhaustion**, however many a player takes part in -- it is
not one of the [ways to gain a token](#exhaustion-and-injury). An **Exhausted** player still
rolls an **injury check** when a test they took part in resolves, the same as any other skill
test, and an injury landing in one round withholds that player's skill in a later one.

This repeats for all six players, unless one team is already ahead by more goals than the
other can still score with the attempts remaining (leading 4-1 with two to go, there is no
need to roll either of them). Six skill tests is one **round**.

If a round ends level -- most commonly 3-3 -- the shootout goes to **sudden death** and
continues one skill test at a time. Each coach chooses and simultaneously reveals one player
who has not yet gone **this round**; they roll, and if either side wins, they score and win
the game. When all six have gone the round ends and a new one begins with everybody eligible
again, still one test at a time.

The order set before the first round governs that round alone. Every sudden-death test is a
fresh choice.

**Shootout goals are goals**, and go on the scoreboard: a game level at 2:2 and settled 4-3 on
the shootout is a 6:5 win.

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
| [Shootout](#extreme-shootout) skill test | 1 each | Offensive skill | Offensive skill | Higher wins and scores; a tie scores for nobody and stands |
| Own goal | 2d12, take the higher | Offensive skill | -- | 7+ avoids |
| Injury check | 1 d12 | -- | -- | Higher than the token count is safe |

A score attempt -- off a set-up or not -- may only be taken from within
[shooting range](#shooting-range). The ball speed modifier is **subtracted** on a shot set up
by a [High Pass that overshoots](#high-pass), and added everywhere else.

Every maneuver above except Block Deflect leaves the ball with a particular player, who then
takes the next turn: see [the ball carrier](#the-ball-carrier).

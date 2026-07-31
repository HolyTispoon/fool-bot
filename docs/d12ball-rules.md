# D12 Ball -- rules

**Retrieved:** 2026-07-31 (first copied 2026-07-25)

D12 Ball's rules live in **two** upstream places, and neither one is complete on its own:

| Source | Holds | Reachable how |
|---|---|---|
| [Notion "living rules"](https://propheticfools.notion.site/D12-Ball-6c9e1ea7ca61825391e881ec5fbfdca5) | the narrative rules: setup, turn structure, scoring, exhaustion, substitutions, shootout | JS app -- a plain fetch returns an empty shell, so render it in a browser |
| [Google Sheet "Player cards"](https://docs.google.com/spreadsheets/d/1PKPpTseisPmM-tH6PMLbtsrYsZ_zG8smluP5VmHKcMw) | component data: player roles and abilities, maneuver die faces, player-board areas, coins | `.../export?format=csv&gid=<gid>` per tab |

Both are **prototype and expected to change.** This file is a point-in-time copy so the
rules are versioned alongside the code and a session without network access can read them.
Re-copy it as its own commit when upstream moves, so each rules change is a reviewable
diff.

A third body of rules exists only in the author's head. Some of it was written down for the
first time in his review of PR #10 and is collected under
"[Author clarifications](#author-clarifications)" below -- **read that section, because it
supersedes parts of the transcription that follows.** What is still unanswered is tracked in
[rules-open-questions.md](rules-open-questions.md).

The upstream page carries this note from the author:

> Note: the language of the rules is currently ambiguous at times, referring to both the
> humans who play the game as 'players' as well as the fictional characters on the field
> of play as 'players'. This ambiguity will be cleared up once proper terminology is picked.

### Changes since the 2026-07-25 copy

The Notion page moved very little. Only two action effects changed:

- **Low Pass** was "Ball moves forward 1-2 spaces"; it is now "Ball moves 1-2 spaces
  **forward or backward**".
- **Block Deflect** gained "**Ball speed decreases by 1.**"

Everything else on the page is unchanged, including all of its ambiguities. The
significant new material in this file is the spreadsheet data, which was not reachable
when this file was first written.

### About this transcription

- Wording is preserved as written upstream, including its typos and inconsistencies.
  Points where that wording is ambiguous for implementation are collected in
  [rules-open-questions.md](rules-open-questions.md) -- **not** here, so this file stays a
  clean copy of upstream.
- Typography normalized to ASCII per this repo's conventions. No wording changed.
- Images are not reproduced: a board/setup diagram, a rock-paper-scissors cycle diagram,
  and action icons. Text saying "in the picture above/below" refers to those.
- The spreadsheet's five tabs are `Sheet1` (gid 0, players), `Benches` (884760728),
  `older Field` (1743933596), `maneuvers` (1487033386), `Coins` (36115124). Tabs the code
  imports are `Sheet1` and `maneuvers`.

---

## Author clarifications

Answers given by the author (@HolyTispoon) reviewing
[PR #10](https://github.com/HolyTispoon/fool-bot/pull/10) on 2026-07-31. **These are rules,
and where they conflict with the transcription below, these win** -- the transcription is a
faithful copy of a page that is behind in places. They are kept in their own section so it
stays obvious which text came from upstream and which came from the author directly.

### Terminology and notation

- **"Clash roll" is renamed "skill test".** Not yet implemented.
- **Ignore "back" and "front".** They belong to an older variant. The Notion page was
  written when each zone was two cards; that "proved too confusing" and was abandoned.
  Spaces will be renotated `H1`, `H2`, ... and the Notion page has not been updated yet.
- The zone/space confusion throughout the Notion text is "human error", not a distinction.

### Board and setup

- **Board sizes are 6, 7 and 9. 7 is the intended default; 6 is now a variant.**
- On a 3-space zone the standard 2-2-2 setup deliberately leaves one space empty.
- **Kickoff depends on board size:**
  - boards **7 and 9** -- always from the **middle of the board**;
  - board **6** -- from the midfield space **closer to the goal of the team kicking off**.

### Coin toss

- The coin toss and the winner's choice of home or visiting is a **real rule**, not a bot
  convenience.
- The trade it creates is deliberate: home kicks off, visitors receive at halftime, so
  picking visitor buys the second-half restart.

### Score attempts

- **Exactly two dice are rolled.** Each *human* rolls one d12. The attacking side adds only
  the shooting player's offensive skill (plus the ball-speed modifier); the defending side
  adds the defensive skills of **all** its meeples standing between the ball and the goal.
  The Notion wording implies one roll per defender; it does not work that way.
- **Attacker total equal to or higher than the defence total scores.**

### Disadvantage

- **Disadvantage means rolling two dice and taking the lower result.** This was never
  written up in Notion. It applies to own-goal rolls and to injured players.
- Fullbacks avoid the disadvantage on own-goal rolls. They still have the worst modifier, so
  they end up "a bit better than 50%" while every other role adds a modifier to a
  disadvantaged roll. The author notes this may prove too harsh and needs more testing.

### Maneuvers

- The defence may choose **any** player in the ball's zone as the challenger -- not only one
  standing on the ball's exact space. The current bot behaviour is correct.
- **If there is no defending player in the ball's zone at all, there is no challenger and
  the offence's maneuver automatically succeeds.** This replaces the Notion rule about
  moving a player in from elsewhere and paying exhaustion per space.
- The ball-speed modifier applies to **Steal Intercept only**.
- A **backward low pass** still increases ball speed by 1, and if it reaches the passing
  team's own goal it does trigger an own-goal attempt.

### Scoring opportunities

Quoting the author:

> When a player succeeds in a high pass and the ball has enough movement to reach beyond the
> last space of the field, and there is at least one player from the offensive team in the
> last space closest to the opponent's goal, that sets up a scoring opportunity. The human
> player may choose one of the players in the zone near the goal to gain an exhaust token
> and do a 'score to shoot' roll to see if they can score a goal.

The striker's `+3` applies to **all** scoring attempts off a set-up -- normally from a high
pass, but also from a winger's low pass.

### Coins

The `Coins` exchange matrix is **not relevant to D12 Ball for now**. "Dinky" is the currency
unit and the Dinky AI is named after it; more and different AI opponents are planned.

---

## Overview

D12 Ball is a fast playing fantasy sports game with tense last-ditch efforts and dramatic
comebacks, where two teams of fantasy creatures compete by maneuvering around the field,
manipulating the ball and outwitting the other team on their way to score epic goals.

## Object of the game

Players control teams competing in a ball game. The goal is to score the most goals within
allotted time, or best their opponents in the extreme shootout in case of a tie at the end
of regular time. The game is played over two periods of 15 space minutes.

## Game setup

The board is made [of] 12 cards representing the field of play. One player is randomly
assigned to be home team player (red in the prototype).

Each player places 6 field cards so they ascend left to right from their perspective. Each
of the cards is called a 'space' and they are enumerated left to right from the player's
perspective. So home team space 1 is aligned with visitor space 6 and vice versa. These
aligned spaces are considered one and the same for the purpose of ball possession. They
serve to show which team has the ball.

The field is divided into 3 zones, each comprised of two pairs opposing spaces. Looking at
the Board left to right from the home team player perspective they are: Home Goal,
midfield, Visitors Goal. The spaces in each of the zones may be referred to from the
player's perspective as 'back' and 'front' -- for example, the third space from the left in
the picture below is 'back of the midfield' for the home team but 'front of the midfield'
for the visitor team. This matters for certain rules, for example: after conceding a goal,
the team that conceded gains possession of the ball in the back of the midfield. Likewise,
at the start of the game the home team starts with the possession at the back of the
midfield and after halftime the visitor team starts with possession at the back of the
midfield.

> **Superseded in two ways** -- see [Author clarifications](#author-clarifications).
> "Back"/"front" belongs to an abandoned variant, and the kickoff space now depends on board
> size: the middle of the board on 7 and 9, and on a 6-board the midfield space closer to
> the kicking team's own goal. The paragraph above, and the `older Field` tab's
> "Kickoff from here at the start of the game" annotation, both describe the 6-space field
> only.

### Player setup

Each player sets up their team. Each team is comprised of 6 starting players and 3 on the
bench that can be subbed in during the game. In setup each player card is assigned to one
of the three zones. Standard setup is 2-2-2. Once player cards have been assigned to a
zone, place the associated meeples/player tokens on spaces so that each token is on a space
in the zone that the player card is assigned to. Note: for now, we need one player of each
role on the field at the start o[f] the game.

To clarify: player cards are assigned to zones. This is the position the player is assigned
to by the coach, and that's the zone that players have to run back to (see players run back
in Cleanup). In contradistinction, player tokens/meeples are present on a specific space are
show which space a player stands on presently. As the game goes on, players will be running
around and moving from space to space, but every time there's a turnover they have to run
back to the position assigned to them by the coach as designated by the cards.

> (prototype comment: player assignment is now by zone but might be changed so that player
> cards are assigned to specific spaces TBD).

Place the ball with the 1 showing on the space 3 of the home team. Set the clock counter to
0. Each player takes their action selection die.

You are ready to play!

### Player board areas

From the spreadsheet's `Benches` tab. Each player board has a front and a back side with
the same areas, mirrored so the zone order runs the right way for whichever side of the
table you sit on.

| Area | Purpose |
|---|---|
| Head Coach | "Use dice to select your manuevers" |
| Bench | "Players who have yet to play go here" |
| Back Bench | "Injured players sit/crash here" |
| Home Goal Zone | "Place here the player cards of players assigned to this zone" |
| Midfield Zone | same |
| Visitors Goal Zone | same |

## Player cards

Player cards have all the attributes and abilities of any given player. The number of a
player card represents their offensive ability, ranging 1-6. Each player's defensive
ability is the d6 inverse of their offensive ability (i.e. the two numbers sum to 7). So
for example, the better a player is on offense the worse they are on defense and vice
versa.

Roles, skills and abilities from the spreadsheet's `Sheet1` tab (offense/defense), re-read
2026-07-31:

| Role | Off | Def | Ability |
|---|---|---|---|
| Fullback | 1 | 6 | No disadvantage on own goal rolls |
| Defender | 2 | 5 | Steals the ball when wins a maneuver with Pressure |
| Midfielder | 3 | 4 | +3 for dribble/advance |
| Playmaker | 4 | 3 | +3 for all passes |
| Winger | 5 | 2 | Can set up a scoring opportunity with a low pass |
| Striker | 6 | 1 | +3 for scoring off a set up |

> **`d12ball/data/players.json` is stale against this.** It still carries the Defender's old
> ability ("Can manipulate the ball when stealing" -- which the author has confirmed was a
> mistake) and the Striker's old "+3 for scoring off a high pass". Re-run
> `scripts/import_d12ball_players.py` to pick both up. The importer already skips the
> `Backside` rows the sheet has gained, so a re-import is safe.

The `+3` abilities are modifiers on the skill test (the roll formerly called a clash). None
of the six abilities is implemented yet.

There are four teams -- Orange, Teal, Purple and Slime -- of nine players each: one of each
role on the field plus three on the bench.

## Game structure

The game proceed according to the following phases:

1. The player with possession chooses one:
   - Score attempt
   - Maneuver
2. Advance time (aka cleanup)

### Attacker's choice

The player with possession must chose between attempting to score and maneuvering.
Depending on their choices and defender's reaction there would be implications for time
advances and cleanup but those don't happen until the attacker's choice phase is fully
resolved.

### Score attempt

If the player in possession is attending to score, they have to roll a challenge vs. all
the opposing players between them and the goal (including any on their own space). For
example, if the home team playmaker 4/3 attempting to score from zone 4 of the home team,
they have to roll a challenge vs. visitors players in visitor spaces 1-3, in the picture
above: 2/5, 5/2, 1/6. To roll a challenge, each player rolls a d12. The attacking player
adds their offensive skill modifier (+4 in this case) as well as the Ball's Speed modifier
(see below, Ball's speed), while all defending players add their defensive skill (5+2+6 in
this case). If the attacker rolls a higher number that is equal or higher than the defense,
they score! Otherwise it's a missed attempt.

> **Clarified.** Only **two** dice are rolled in total -- one per human, not one per
> defender. The attacker adds the shooting player's offensive skill plus the ball-speed
> modifier; the defender adds the defensive skills of every meeple between the ball and the
> goal. Attacker total **>=** defence total scores. See
> [Author clarifications](#author-clarifications).

Time advance: a scoring attempt advances the time by 1 space minute for each space the ball
has traveled through (including the one from which it originates). In the example above the
scoring attempt will advance time by 3 space minutes.

| | Time | Cleanup |
|---|---|---|
| Score | Spaces the ball traveled | Score tracker up 1; turnover; conceding team gains ball in their space 3 (back of the midfield) |
| Miss | Spaces the ball traveled | Turnover; conceding team starts from zone 1 (back of their Goal zone) |

### Maneuver

When the attacking player doesn't wish to attempt a score (which should be most of the
time), they maneuver which goes through the following steps.

**Determine players.** The player with possession picks a player to attempt a maneuver,
which has to be a player in the same space the ball (there would often be only one option).
Then, the player must pick a player in the same space to challenge the attacker (there
would often be only one choice). In the case where there are no players in the zone, the
defender must choose one of their other players to challenge the attacker. They move that
token to the space with the ball and the player that had to meet the challenge gains an
Exhaustion token for each space they had to travel.

> **Superseded.** The defence may pick **any** player in the ball's zone, not only one on
> the ball's exact space. And if there is no defender in the zone at all, there is **no
> challenger and the offence's maneuver automatically succeeds** -- nobody is walked in and
> no exhaustion is paid. See [Author clarifications](#author-clarifications).

**Select a maneuver.** Both players now use their dice to secretly select an action for
their fielded player to attempt, using their six sided action-selection die. The attacker
chooses an offensive action while the defender chooses an offensive action [sic -- see
open questions]. After both players have picked their action, they simultaneously reveal
their choice and play proceeds to resolution.

**Resolving maneuvers.** Offensive and defensive actions are related to each other in a
rock-paper-scissors like cycle where each offensive action defeats one defensive action, is
defeated by another and is tied with the third one.

After actions are revealed, players examine the table on the left to see if one has an
action that defeats another. For example, if the offensive player opted for a low pass and
the defensive player tried to steal -- the defensive player's action defeats the offensive
player's action.

If one player's action defeats their opponent's, they proceed to enact its SUCCESS clause.

When a player moves, move their player token an appropriate amount of steps, keeping them
on their side of the field.

### Challenges

> **The "Clash roll" described here is now called a skill test.** Not yet implemented.

When both players choose an action of the same 'rank' (i.e. they both choose a 'rock'), the
players on the field are now challenges each other. Each of the challenging players adds an
exhaustion token (see Exhaustion below) and both players now resolve a Clash dice roll. To
resolve a clash, each human player rolls a d12 and adds any appropriate modifiers, including
their fielded player's skill modifier (for the attacker it would be their attack skill and
for the defender their defense skill). In addition, some abilities and game effects may add
additional modifiers. For example, the speed of the ball is added as a modifier in attempts
to steal the ball (see below, Ball's speed).

> NOTE: In a Clash roll, players are encouraged to roll the dice at the same time and make
> sure the dice hit each other for perfect simulation of the clash between players!

### Turnover

A turnover means the ball changes possession, which means it moves from one player's area
of the field (either the top or bottom part of a pitch card) to the other team.

### Actions display

3 offense actions, 3 defense actions. Rank and die values are from the spreadsheet's
`maneuvers` tab; each maneuver occupies two faces of the six-sided action-selection die.
Two actions of the same rank tie, which is what sends a maneuver to a clash roll.

| Action | Side | Rank | Die | Defeats | Effect | Time |
|---|---|---|---|---|---|---|
| Low Pass | offense | 1 | 1-2 | Pressure | Ball moves 1-2 spaces forward or backward. Ball speed increases 1. | distance traveled (1-2 space minutes) |
| Dribble Advance | offense | 2 | 3-4 | Block Deflect | Player and ball move forward 1 space. Manipulate ball speed up to player's offensive skill. | 1 space minute |
| High Pass | offense | 3 | 5-6 | Steal Intercept | Ball moves forward 2-3 spaces. If ball reaches goal, set up a scoring opportunity. | distance traveled (2-3 space minutes) |
| Block Deflect | defense | 1 | 1-2 | High Pass | Ball moves back 2 spaces. If reaches offense's goal, chance for own goal. Ball speed decreases by 1. | 2 space minutes |
| Steal Intercept | defense | 2 | 3-4 | Low Pass | Turnover. Ball moves back 1 space. Manipulate ball speed up to defensive skill. | 1 space minute |
| Pressure | defense | 3 | 5-6 | Dribble Advance | Player and ball go back 1 space. Defender moves 1 forward. | 1 space minute |

### Own goal

Roll with offense skill, disadvantage. Need 7+ to avoid.

> **"Disadvantage" means rolling two d12 and taking the lower result** -- never stated
> upstream. Fullbacks are exempt from the disadvantage on this roll.

### Ball's speed

The ball is a d12 and the number it is showing represents the ball's speed. As the speed of
the ball increases, so does the ball's speed modifier which affects scoring and stealing
attempts -- when the ball is faster it is easier to score but also harder to keep possession!

The speed of the ball increases by 1 with each low pass. When a player dribble advances,
they can manipulate the speed of the ball -- increasing or decreasing it up to their offense
skill. When a player steal intercepts the ball they can manipulate it by increasing or
decreasing the speed of the ball up to their defensive skill.

| Ball speed | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Modifier | 0 | +1 | +1 | +2 | +2 | +3 | +3 | +4 | +4 | +5 | +5 | +6 |

> The table is exactly integer division by two: `modifier == speed // 2` for all twelve
> values.

## Cleanup

During the cleanup phase:

The time advances an amount of time depending on the action that occurred during the turn.
Time always advances at least 1 space minute but when the ball travels across the field,
either when it's passed or when it shot towards the goal, time advances by the number of
spaces that the ball has traveled. To advance the time, count up the clock counter by the
number of space minutes that have passed. When the clock timer reaches 15, the game into the
last possession (see End of Time).

If the goal was shot towards the goal, the ball now turns over. If a goal was scored, the
game restarts from the middle (back of the midfield) and if it wasn't, the game restarts
from goal of the team that avoided a goal. Either way, since the ball is turned over,
players run back.

Players run back: every time there's a turnover for any reason (steal, goal etc.) players
have to run back to their assigned locations.

## Exhaustion

Every time players are involved in a challenge, they gain an exhaustion token. Every time
players have to run back to their position, they gain exhaustion tokens (see Cleanup below).
As soon as a player has a number of exhaustion tokens that is higher than their defensive
skill, they are considered Exhausted. When a player is exhausted, they risk getting injured
during challenges. During halftime, each player loses 1 (or 2, TBD) exhaustion tokens. In
addition, human players can choose one of their player to lose an extra exhaustion token.

**Exhausted:** When a player is exhausted, after they participate in a challenge they must
roll an exhaustion check. To roll an exhaustion check, roll a d12. If you roll a number that
is higher than the number of exhaustion tokens you are safe! Otherwise, your player is now
injured.

**Injured:** When a player is injured, their team must declare substitution at their next
opportunity if they can, and sub out the injured player (see Substitutions). Until they are
subbed they are disadvantaged: they automatically lose a challenge and have to win a clash
roll when their action beats the opponent player's action.

## Substitutions

Once every halftime, when a team wins possession (either by stealing the ball or after the
other attempts a score), they may a declare substitutions. When a team declare substitution,
they may sub out up to 2 of the players on the field with players on the bench and move
around player assignments on the field (including changing formation, once teams have more
formations available). After the team with possessions chooses how to arrange their team,
the other team may substitute 1 of their player and rearrange their players in formation.
Therefore, normally [a team] can substitute up to twice in each halftime (once when they
declare subs and once when the other team declares it). In addition, normally players who
are subbed out cannot be subbed back in (the exception is when players are injured, and see
below Subbing injured players).

### Subbing injured players

As noted above, when a player is injured their team must declare substitution at their next
legal opportunity if they can (that is, if they have not declared substitution that
halftime). Subbing for an injured player is the only time that a player that was subbed out
earlier in the game can be subbed back in, if and only [if] all the players on the bench
were subbed out during the game. When a player who was previously subbed out is subbed back
in (for an injured player), the human player removes from their card half of their
exhaustion tokens (rounded up) so if they were subbed while exhausted they are no longer
exhausted. An injured player that was subbed out cannot be subbed in under any
circumstances!

## End of Time

As soon as the clock counter reaches 15 space minutes, the period's time is at an end and
the game goes into last possession. During the last possession the play proceeds as normal
until the ball turns over -- when the team with the ball losses possession, the period is
officially at an end. If that is the first period, it is now halftime. During halftime:

- fielded players lose 1 exhaustion token
- one of the fielded players of the coach's choice loses an extra exhaustion token
- The coach can change their team's formation and the players' assignment as they please
- Play resume for the second half with the visitors team in possession of the ball at the
  back of the midfield

At the end of the game, if the game is tied -- it goes into extreme shootout!

### Extreme shootout tie breaking bonanza

First each player secretly arranges their team of six players in any order the wish. Once
the order is set, they can look at it but cannot reorder it. Then the players simultaneously
reveal the top card of their deck. These two players are now involved in a clash, adding
their offensive ability (injured players, if there are any, are disadvantaged and therefore
do not add their offensive ability modifier). The side who wins the clash roll gains a goal.
This process [repeats] for all six players unless one team has already secured the win by
getting ahead by more goals than the other team can score with remaining attempts (for
example, if a team leads 4-1 after five clashes, there is no need to roll a sixth clash). If
dice + modifiers are a draw, no team gains the score.

In case that the six clashes end up in a draw (most commonly 3-3), the process continues one
clash at a time. Each cycle of six clashes is called a 'round' of extreme shootouts.

Each team choose and simultaneously reveals one player who hasn't yet participated in a
clash this round. Once players are revealed, they roll a clash and if either team wins --
they score and win the game!

## Coins

The spreadsheet's `Coins` tab defines a currency. The author has confirmed the exchange
matrix is **not relevant to D12 Ball for now**; the bot only borrows the coin art for the
toss.

Coins come in an amount (1 or 3) and a metal (bronze, silver, gold), and are worth a number
of "Dinkys":

| Coin | Worth in Dinkys |
|---|---|
| 1 Bronze | 1 |
| 3 Bronze | 3 |
| 1 Silver | 6 |
| 3 Silver | 18 |
| 1 Gold | 12 |
| 3 Gold | 36 |

Note that 3 Silver (18) is worth more than 1 Gold (12). The tab also carries a pairwise
exchange matrix consistent with those values.

Every coin has a **fortune** face and a **doom** face, which is what the coin toss reads --
fortune wins the flipper the toss, doom hands it to their opponent, and the winner then
chooses home or visiting. Neither upstream source describes the faces; the toss is confirmed
a real rule under [Author clarifications](#author-clarifications).

The author also plans a generic `/flip` command and, longer term, an RPG system built on
2d12 -- one doom die and one fortune die.

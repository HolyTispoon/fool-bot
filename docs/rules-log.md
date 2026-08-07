# D12 Ball -- rules log

Every change the rules have made, with its date; what is still unanswered; and where each
answer came from. **The rules themselves are in [living-rules.md](living-rules.md)** -- this
file never states a rule, it only records how one got there.

**As of:** 2026-08-07.

## Where the rules come from

| Source | Holds | Reachable how |
|---|---|---|
| [Notion page](https://propheticfools.notion.site/D12-Ball-6c9e1ea7ca61825391e881ec5fbfdca5) | the narrative rules: setup, turn structure, scoring, exhaustion, substitutions, shootout | JS app -- a plain fetch returns an empty shell, so render it in a browser |
| [Google Sheet](https://docs.google.com/spreadsheets/d/1PKPpTseisPmM-tH6PMLbtsrYsZ_zG8smluP5VmHKcMw) | component data: player roles, abilities, maneuver die faces, player-board areas, coins | `.../export?format=csv&gid=<gid>` per tab |
| The author (@HolyTispoon) | everything neither of the above says yet -- a third of the ruleset has only ever existed in his head | ask him |

Both upstream sources are prototypes and move. **Neither is complete, and both are behind the
living rules in places** -- see [Where upstream is behind](#where-upstream-is-behind), which is
what a fresh pull should be diffed against.

The sheet's tabs are `Sheet1` (gid 0, player cards), `basic_abilities` (1822486506),
`Benches` (884760728), `older Field` (1743933596), `maneuvers` (1487033386),
`Coins` (36115124). The code imports `Sheet1`, `basic_abilities` and `maneuvers`.

**Working practice.** Take rules questions to the author rather than inferring them from the
code -- several mechanics exist only in the code, so there a bug and a deliberate decision look
identical. Asking as inline comments on a docs PR has worked far better than asking in chat,
and it leaves the answers versioned. When upstream moves, update
[living-rules.md](living-rules.md) as its own commit and add a dated entry below, so each rules
change stays a reviewable diff.

**Verbatim upstream.** Until 2026-08-07 this repo kept a literal transcription of the Notion
page and the sheet in `docs/d12ball-rules.md`. It was replaced by the living rules; the last
copy is in git at commit `5e05bdd` if a future pull wants to diff against upstream's own words.

---

## Still open

### Is the exhaustion work in PR #9 the intended scope?

The author's answer to "exhaustion accumulates but does nothing" was "yet, it's in my PR"
(PR #9, `claude/import-maneuvers-script`). That PR grants a token to both sides on a tie and
renders them with an emoji, but does **not** add the Exhausted threshold, the injury check, an
injured state, or any use of `back_bench`. Worth confirming that accrual was the intended scope
and the Exhausted / Injured layer is a later piece, rather than assuming it done.

Everything else has been answered. What remains unbuilt is in
[Implementation status](#implementation-status).

---

## Change log

Newest first. Each entry says where the change came from: a pull from the sheet or Notion, or
the author directly.

### 2026-08-07 -- sheet re-pull, and rules handed over directly

The sheet was restructured (`Sheet1` + `maneuvers`, plus a new `basic_abilities` tab) and two
maneuvers changed. The author handed over the rest directly.

**From the sheet:**

- **Role abilities moved to their own `basic_abilities` tab** (gid `1822486506`, one row per
  role). `Sheet1`'s `Ability` column was renamed `Basic` and is now a copy of that tab, so
  either can be imported -- `scripts/import_d12ball_players.py` reads the abilities tab and
  cross-checks the copy. The wording of all six abilities is unchanged. A sibling `Advanced`
  column is reserved for advanced mode's per-team abilities; it is empty, and the importer
  drops it with a notice.
- **Each team now fields one Winger and benches a second Striker**, where it was two Wingers
  and one Striker. Emberdash, Tachyon, Zytheris and Acidel changed role and carry the Striker's
  6/1 skills with it. The standard setup still deals one of each role per zone, so what changed
  is the bench: Defender, Playmaker and **Striker**.
- **Low Pass named its destinations** instead of giving a distance range: only the *nearest*
  teammate each way within 2 spaces is a destination, and a pass to a teammate on the ball's own
  space now moves the passer forward 1. Ball speed +1 as before.
- **High Pass contests only a pass of 3 or more**, and hands the offense the ball speed modifier
  when it does. A 2-space pass is simply received -- declining the scoring opportunity it offers
  now resolves the pass normally, where it used to fall back to the skill test.
- **The other four effects were tightened** without changing what they do; every effect now fits
  the bot's maneuver reference card.

**From the author:**

- **A Low Pass must reach a different player.** Nobody passes to themselves to keep the ball, so
  distance 0 is legal only as a pass to a *second* player sharing the ball's space. This
  superseded the earlier reading, under which distance 0 meant the ball stayed with the passer.
- **A Low Pass with no legal destination sends the ball a space forward, loose, and still raises
  its speed by 1** -- settling what had been an open question. Deliberately kept out of the
  sheet as too rare to spend card space on.
- **The own-goal roll costs the rolling player 1 exhaust token**, win or lose, on top of whatever
  the maneuver already charged. It is not a skill test, so it owes no injury check.
- **The maneuver that takes the clock to 15 never ends the period, even when it is itself a
  turnover** -- superseding the previous reading. Last possession is the possession that *starts*
  at 15, so that maneuver resolves in full and hands last possession to whoever it gave the ball
  to.
- **Halftime's substitutions are not a declaration** and do not spend the side's once-a-half one.
  Each side gets a declaring team's allowance independently, with no answering substitution.
- **A tie at full time goes to the extreme shootout in tournament mode only.** Every game is now
  set up as league (a tie stands) or tournament (a tie goes to the shootout). Upstream knows only
  the tournament reading.

### 2026-08-06 -- author, scoping the loose ball and halftime

- **The team that last had possession answers a loose ball first, and alone**, rather than both
  coaches being asked together -- the ball is theirs to lose, and asking both at once means the
  second coach answers the first's pick rather than the position.
- **Sending nobody is always allowed**, and is a move rather than a way out of the prompt, so a
  side with exactly one candidate is still asked.
- **The out-of-bounds placement happens after the run back**, not before -- placed first, the run
  back pulls that player straight back off the ball and leaves it loose again.
- **A High Pass's contest is not a loose ball.** The two run the same roll and mean opposite
  things: the receiver is holding the ball and must keep it, and a defence with nobody on the
  landing space may decline to send anyone, in which case there is no test at all.
- **Only a turnover runs anyone back.** A resolution that leaves possession where it was runs
  nobody back and charges nobody, however far out of position it left them.
- **Halftime's repositioning is free placement to any space on the board**, not just a player's
  own zone -- the only unrestricted placement in the game. The visiting side must finish with a
  player on the kickoff space, since they kick off.

### 2026-08-05 -- sheet re-pull after a playtest, plus author

**From the sheet** (`Sheet1` + `maneuvers`):

- **Low Pass** dropped its fixed 1-space distance for "a teammate 0-2 spaces away" -- only to a
  space a teammate already occupies, so a Low Pass itself never triggered a loose ball. (Revised
  again two days later; see above.)
- **High Pass** replaced its fixed 2 spaces with a 2-3 choice, and only an exact 2 could set up a
  scoring opportunity, and only as a choice. The old requirement that the pass overshoot the
  field was dropped.
- **Fullback's ability** changed from "+1 space on any pass" to "can pass up to 4 with a high
  pass; when resolving block deflect, ball goes back 2 spaces" -- it no longer touches Low Pass,
  the High Pass bonus became the player's choice, and Block Deflect gained a second effect.
- **Defender's ability** was reworded with no change in meaning.
- **Steal Intercept** gained a trailing "after turnover", confirming in the primary text what the
  author had already clarified.

**From the author:**

- **A Winger's Low Pass sets up a scoring opportunity from wherever the pass lands**, not just
  near the goal -- the ability's text did not change, but its meaning was settled.
- **After a swap, the declaring team places meeples anywhere within their new zones**, any number
  of times, free. Where both zones are already full (a 6-board, or board 7's goal zones), the two
  meeples simply trade places.
- **No role or player is tied to a space or zone**, except by the run back returning each meeple
  to its card's zone.
- **A goal's conceding team must move a meeple onto the kickoff space** to restart, at the usual
  run-back cost, once everyone else is settled -- nothing otherwise guarantees anyone is standing
  there.
- **A turnover during last possession ends the period immediately** -- no run back, and no
  resolution of what the causing maneuver still owed.

### 2026-08-04 (later the same day) -- sheet, Time column

**Block Deflect**'s Time went from "2 space minutes" to "1 space minute", matching its own fixed
1-space effect. An in-between pull briefly saw Low Pass's and Steal Intercept's Time values
swapped; the author was mid-edit and fixed it, so that state never landed here.

### 2026-08-04 -- sheet reword (commit 527a772)

Both `Sheet1` and `maneuvers` were reworded:

- **The six role abilities.** Fullback's was restated in terms of pass distance rather than the
  own-goal roll; Defender's and Striker's old wording (flagged as mistakes) is gone; Midfielder's
  and Playmaker's swapped which maneuver they name; Winger's changed only punctuation.
- **Low Pass and High Pass each dropped their distance range for a fixed number** (1 space and 2
  spaces). Both were superseded the following day.
- **Block Deflect no longer risks an own goal.** Its overshoot now sets up a scoring opportunity
  for the defense instead, the way a High Pass overshoot did for the offense.
- **Pressure gained the own-goal trigger** -- so the own-goal risk moved from Block Deflect to
  Pressure.

### 2026-08-04 -- author, scoping substitutions

- **One player of each role is a property of the standard setup, not a standing rule.** A
  substitution may leave a role unfielded, which it has to be able to do: every bench is a
  Playmaker, a Defender and a Striker.
- **Cards change zones freely and rearranging costs no exhaustion** -- the only meeple movement
  in the game that does not pay per space. **Basic mode allows 2-2-2 only**, so a rearrangement
  must leave two per zone. 4-1-1 and 2-1-3 belong to advanced mode and fit no current board.
- **Every turnover opens a substitution window**, not only a steal or a score attempt.
- **The window opens before the run back.**
- **The bench and the back bench are two separate pools.** Anyone subbed out goes to the back
  bench; a team subs from the bench while it has anyone; the back bench is drawn from only when
  the bench is empty and the sub is for an injured player; injured players never return.
- **A player returning from the back bench just loses half their tokens, rounded up** -- they are
  Exhausted or not according to what remains.

### 2026-08-04 -- author, reviewing PR #29 (own goal / run back)

- **The own-goal roll is an advantage, not a disadvantage:** 2d12, take the higher, add offensive
  skill, 7+ avoids.
- **An own goal takes priority over the Defender's Pressure steal.** When a won Pressure would
  trigger both, the own goal resolves and the steal does not also happen.
- **A steal exempts the stealing player from running back**; everyone else displaced still runs
  back.
- **The run back also separates same-zone teammates stacked on one space**, when another space in
  that zone is open.
- **Picking a challenger is only a real choice when nobody is already there.** A defender standing
  on the ball's exact space is the challenger automatically -- no prompt, no walk-in, no token.
- **The loose-ball check runs after every maneuver resolves**, not just after a pass lands on an
  empty space, and a contested pick charges each contestant for the distance they travelled.

### 2026-08-03 -- author

**An injured player removes all exhaustion tokens immediately** and is no longer Exhausted.
Injured players cannot gain more tokens and make no further injury checks.

### 2026-08-02 -- sheet, plus author

- **Steal Intercept**'s effect became "Turnover. Defender and ball move back 1 space. Manipulate
  ball speed up to defensive skill", where it previously said only "Ball moves back 1 space" and
  left the interceptor's own meeple in place.
- **The fallback happens after the turnover, in the new possessing side's direction** (author).
  Read literally against the old side's direction, "back" would send the ball toward the new
  team's attacking goal -- the opposite of what is intended.
- **Every turnover resets the ball's speed to 1** (author). Upstream describes speed changing
  during four maneuvers and never says what a change of possession does to it. Steal Intercept's
  manipulate-speed choice is relative to that reset, so the result always lands within defensive
  skill of 1.
- **The loose-ball rule was specified** (author): its four cases, and distance-travelled
  exhaustion for anyone who moves to contest or recover the ball -- upstream's own text says a
  flat 1 token.

### 2026-08-01 -- Notion re-pull, plus author

The author pushed most of his PR #10 answers into Notion. Changed upstream:

- The score-attempt example says "space 4", not "zone 4", and the threshold reads "equal or
  higher than the defense" -- the self-contradictory "a higher number that is equal or higher" is
  gone.
- Both rows of the Score/Miss table were rewritten; the restart after a goal is explicitly
  board-size dependent, and "conceding team" on a miss became "team that avoided conceding a
  goal".
- "Determine players" now says the challenger comes from the same **zone**, spells out the walk-in
  and exhaust cost, and adds the no-challenger case.
- The long-standing "the defender chooses an offensive maneuver" typo is fixed.
- **Own goal** was expanded from one line into a full rule defining *disadvantage*.
- A new **Setting a scoring opportunity** section was added.
- "exhaustion token" began drifting to "exhaust token".

**From the author, scoping shoot to score:**

- **Exactly two dice are rolled in a score attempt**, one per human. The defence adds the
  defensive skills of every meeple between ball and goal; upstream's "each player rolls a d12"
  reads as one roll per defender and does not work that way.
- **A plain score attempt costs no exhaustion at all**, and never triggers an injury check.
- **A shot off a set-up costs the shooter 1 token, after the roll**, and a Striker's +3 applies to
  any scoring attempt off a set-up.
- **Run back is 1 token per space travelled**, the coach picks each player's space within their
  zone, and the one-per-space limit that leaves is **per team** -- opposing meeples still share a
  space.

### 2026-07-31 -- sheet, plus the first round of author answers (PR #10)

**From the sheet:** Low Pass gained "forward **or backward**"; Block Deflect gained "Ball speed
decreases by 1".

**From the author:**

- **Board sizes are 6, 7 and 9. 7 is the intended default; 6 is a variant.** On a 3-space zone
  the standard 2-2-2 setup deliberately leaves one space empty.
- **Kickoff depends on board size** -- 7 and 9 start from the middle of the board, 6 from the
  midfield space closer to the kicking team's goal -- and **the same rule governs every restart**,
  after a goal and at the second half, not just the opening kickoff.
- **The coin toss and the winner's choice of home or visiting is a real rule**, not a bot
  convenience; upstream still says home is randomly assigned. The trade is deliberate: home kicks
  off, visitors receive at halftime.
- **"Clash roll" is renamed "skill test".**
- **Ignore "back" and "front"** -- they belong to an abandoned variant where each zone was two
  cards. The zone/space confusion elsewhere upstream is human error, not a distinction.
- **Space notation:** the engine's single absolute left-to-right index, with possession tracked
  separately, is what to standardise on.
- **Halftime recovery is 1 token**, not "1 (or 2, TBD)".
- **The injury check belongs to skill tests only.**
- **The ball-speed modifier applies to Steal Intercept only** (High Pass's contest was added to
  that list on 2026-08-07).

### 2026-07-25 -- first copied into the repo

---

## Where upstream is behind

What the Notion page and the sheet still say, against what the living rules say. This is the
list to diff a fresh pull against: a difference already here is old news, anything else is new.

| Upstream still says | The living rules say |
|---|---|
| A fixed 12-card board, 6 field cards, two spaces per zone, and a 'back'/'front' half to each zone | Board sizes 6, 7 and 9; zones of 2-3 spaces; no back/front |
| Home is randomly assigned | A coin toss, and the winner chooses home or visiting |
| "Place the ball ... on the space 3 of the home team" | The kickoff space, by board size |
| Cleanup restarts "from the middle (back of the midfield)" | The same kickoff space rule, for every restart |
| "Clash" / "clash roll" | Skill test |
| A score attempt's "each player rolls a d12" | Exactly two dice, one per coach; the defence sums intervening meeples |
| Nothing about what a score attempt costs | Nothing for a plain attempt; 1 token to a shooter off a set-up, after the roll |
| The own goal is triggered by a deflected pass, and rolled at a **disadvantage** | Triggered by Pressure's overshoot only, rolled at an **advantage**, and costs 1 token |
| Setting a scoring opportunity describes only the old fixed-2 High Pass overshoot | Three set-ups (High Pass of 2, a Winger's Low Pass, a Block Deflect overshoot), each a choice |
| A turnover says nothing about ball speed | Every turnover resets it to 1 |
| A loose ball's contestant "gains 1 exhaustion" | 1 token per space travelled |
| Nothing about the loose-ball check at all, beyond a pass landing on an empty space | A general check after every maneuver, with four cases |
| Nothing about which space a player runs back to, or what it costs | The coach picks, one per team per space, 1 token per space |
| Halftime recovery of "1 (or 2, TBD)" | 1 |
| Halftime lets the coach change assignments "as they please" | Free placement to any space on the board, and the visiting side must cover the kickoff space |
| Substitutions: "if and only if all the players on the bench were subbed out" | Two pools -- bench, then back bench for an injured sub only |
| "So if they were subbed while exhausted they are no longer exhausted" | Half the tokens, rounded up; Exhausted follows from what remains |
| A tie at full time goes to the extreme shootout | Tournament mode only; a league game ends tied |
| "For now, we need one player of each role on the field" | A property of the standard setup, not a standing rule |
| Nothing about a Low Pass with no legal destination | The ball goes a space forward, loose, speed still +1 |

---

## Answered, so nothing gets re-asked

A short index. Every answer is in [living-rules.md](living-rules.md); the dated entry above says
where it came from.

**Written into Notion, and now upstream's own text:** the score threshold wording; "conceding
team" on a miss; "the defender chooses a defensive maneuver"; "space 4" in the score example;
the post-goal restart position; the challenger coming from the zone and paying per space; the
no-challenger case; what *disadvantage* means; what a scoring opportunity is.

**Board and setup:** board sizes 6/7/9 with 7 the default, and a 3-space zone leaving a space
empty; the kickoff space per board size, governing every restart; the coin toss and side choice
as a real rule; the bot's space notation as the one to keep.

**Score attempts:** two dice total; no exhaustion for a plain attempt and no injury check;
"score to shoot" is an ordinary score attempt; the set-up token is taken after the roll; a
Striker's +3 applies to any shot off a set-up.

**Maneuvers and the ball:** the ball-speed modifier's scope (Steal Intercept to the defense, a
long High Pass to the offense, a score attempt to the attacker, and nothing else); every turnover
resetting speed to 1; Steal Intercept's fallback happening after the turnover in the new
possessor's direction; a backward Low Pass raising speed like any other; a Low Pass reaching only
the nearest teammate each way, needing a different player, and its no-destination case; what a
pass across a shared space buys; only a 3+ High Pass being contested.

**Loose ball:** the one-team case taking possession with no test; the out-of-bounds case and its
placement, after the run back; declining always being allowed, including for a High Pass's
defence; the side that last had possession answering first and alone.

**Run back:** 1 token per space; the coach picking the space; one player per space, per team;
same-zone teammates being separated; a steal exempting the stealer; only a turnover running
anyone back.

**Substitutions:** no requirement to keep one of each role; cards changing zones freely; 2-2-2
only in basic mode; rearranging costing nothing; every turnover opening a window; substituting
before the run back; the two pools; a returning player only losing tokens; halftime's window not
being a declaration.

**Own goal:** the trigger moving to Pressure; the advantage roll; priority over the Defender's
steal; the 1-token cost.

**Time:** the maneuver that reaches 15 never ending the period; a turnover during last possession
ending it immediately.

**Out of scope:** the coins' exchange matrix is not relevant to D12 Ball for now ("Dinky" is the
currency unit, and the Dinky AI is named after it); the 72-card "Foolish" deck belongs to another
game; Dinky AI stays a dice-roller.

---

## Decisions recorded

From the author, for `foolbot.py`'s generic commands:

- **Delete** `/place`, `/move`, `/board`.
- **Keep** `/newdeck` and `/draw` -- the 72-card deck belongs to another game he wants to develop
  further. Possibly move to their own file.
- **Keep** `/roll` as a generic dice roller.
- **Add** `/flip` -- pick any of the six coins, get a fortune/doom result. The denomination is
  purely cosmetic.
- Longer term: devices for his other games, including an RPG on a 2d12 system of one doom die and
  one fortune die.

---

## Implementation status

### Built

- **The six role abilities**, in line with the current table.
- **The own-goal trigger on Pressure**, with the advantage roll, its exhaust token, priority over
  the Defender's steal, and Block Deflect's overshoot setting up a scoring opportunity for the
  defense instead.
- **Score attempts.** Two dice, defence summing every meeple between ball and goal, ball-speed
  modifier on the attacker, no exhaustion either side, and the goal applied to the scoreboard.
  The clock and the restart are still announced as text rather than applied.
- **Loose ball**, all four cases, including the ask-one-side-at-a-time order and declining.
- **The High Pass contest**, distinct from a loose ball, with the ball-speed modifier to the
  offense.
- **Substitutions**, end to end: the window on every turnover, before the run back, gated on the
  once-a-half declaration; the declare-then-reply pairing; the two pools; a returning player
  keeping half their tokens; free rearrangement implemented as exchanging two players. Dinky
  substitutes only to get an injured player off, and never rearranges.
- **Halftime**, end to end: recovery, the coach's extra token, each side's independent
  substitution window, and free repositioning gated on the visiting side covering the kickoff
  space.

### Specified but not built

- **The run back.** Fully specified -- 1 token per space, the coach picks within the zone, one
  player per space per team, steal exemption, stacked teammates separated. Nothing enforces it
  yet; the score-attempt cleanup only asks for it in words. `move_ball` refuses a space with no
  meeple, so the post-goal and post-miss restarts are gated on this.
- **Kickoff on a 6-board.** `MatchState.standard` uses `space_index=min(1, len(midfield) - 1)`
  for every board size. On 7 and 9 that is the middle of the board and correct; on a 6-board it
  is the midfield space *further* from the kicking team's goal, so the ball starts a space too far
  forward -- that case wants index 0. Since the same rule governs the restart after a goal and at
  the second half, this wants one shared helper rather than a literal per call site.
- **An unchallenged maneuver should succeed, not stall.** With no defender in the ball's zone,
  `eligible_challengers()` returns empty and the cog replies "The defending team has no player in
  the ball's zone to challenge" and stops. It should automatically succeed for the offense.

### Blocked or deferred

- **The extreme shootout** is specified but not built, and is reachable only in **tournament
  mode** -- which setup refuses until it exists. A league-mode game ends tied instead.
- **Advanced mode** -- per-team abilities (the sheet's empty `Advanced` column) and formations
  other than 2-2-2 -- is unspecified. Setup refuses it.

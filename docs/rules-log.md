# D12 Ball -- rules log

Every change the rules have made, with its date; what is still unanswered; and where each
answer came from. **The rules themselves are in [living-rules.md](living-rules.md)** -- this
file never states a rule, it only records how one got there.

**As of:** 2026-08-09.

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

### 2026-08-09 -- author, a shot may only be taken from within shooting range

- **A score attempt now needs the ball in the far part of the field.** It used to be
  available from wherever the ball was, which made a shot from a team's own goal zone a legal
  (if hopeless) turn. A team that has not carried the ball past the middle of the field now
  has only a maneuver to make.
- **The boundary is the middle of the board, not a zone boundary.** So a team's range is the
  far part of midfield plus the goal zone it attacks, and on boards 7 and 9 -- the odd-sized
  ones -- the middle space is in nobody's range. The author's call: no shot may be taken from
  it. That space is also the kickoff space, which means no restart ever begins in range.
- **It is called shooting range, not a half**, the author's call on the wording. The region
  is not literally half the field on the standard 7-space board -- three spaces of seven --
  so calling it one misread the rule, and "zone" was already taken by the three board zones.
- **Set-ups are bound by it too**, also the author's call. A scoring opportunity sends a
  player into an ordinary score attempt, so what it buys is the shot *out of turn*, not a
  shot from anywhere: a High Pass of 2 or a Winger's Low Pass landing short of range sets
  nothing up and resolves as the pass it was. A Block Deflect that overshoots is unaffected
  in practice -- the ball has reached the space closest to the offense's own goal, which is
  always deep in the deflecting team's range.
- **Board 6 has no neutral space**, its six spaces splitting three and three, and its kickoff
  space sits behind the kicking team's own range.

### 2026-08-08 (later again) -- author, the three basic-mode shapes are 2-2-2, 2-3-1 and 1-3-2

- **4-1-1 and 2-1-3 are out; 2-3-1 and 1-3-2 replace them.** Basic mode still offers exactly
  three shapes, still read from a coach's own goal forward, and 2-2-2 is still where every
  game kicks off. Only which two shapes join it has changed, so nothing about how a coach
  moves between them, or when, is affected.
- **The new pair is a midfield pair.** Both put three cards in midfield, which is what makes
  them different from each other only at the ends: 2-3-1 keeps the back two and pushes one
  forward player back, 1-3-2 keeps the front two and pulls one defender up. 4-1-1's four in a
  goal zone has no counterpart in the new set.
- **Stacking is now board-dependent, where it used to be unconditional.** 4-1-1 and 2-1-3
  overfilled a zone on every board. Three in midfield fits board 7 and board 9 exactly, and
  only overfills board 6's two-space midfield. The coverage rule is unchanged and still
  earns its keep -- see "Occupancy" in the living rules -- but on the default board the new
  shapes never stack, so it is board 6 that exercises it.
- **An uncontested maneuver now succeeds instead of stalling.** This was already the rule --
  "if the defending team has nobody in the ball's zone, there is no challenger and the
  maneuver automatically succeeds for the offense" -- and the only thing the author added is
  that the offense still *picks* which maneuver succeeds, rather than being handed a generic
  success. It had been listed under "Specified but not built"; it is now built.

### 2026-08-08 (later still) -- author, a new play resets to the coach's arrangement, and injuries compel nothing

- **A turnover is now either a steal or a new play, and only a new play opens a substitution
  window.** This narrows 2026-08-04's "every turnover opens a window", which had made the
  window a routine part of open play: a steal came with a pause to substitute in, which is not
  what taking the ball off someone should buy.
- **Steals, which open nothing:** a won Steal Intercept, a Defender's Pressure steal, a loose
  ball won by the side that did not have it (standing on it, sent for it unopposed, or won on
  the skill test), and a lost long High Pass contest. The rule the author gave is that a loose
  ball picked up by the opposing team is a steal, and the High Pass contest follows it -- both
  are the other team taking a live ball.
- **New plays, which open one:** a goal, an own goal, a missed attempt, and a ball out of
  bounds. The common thread is that the ball went dead and is being brought back into play,
  which is also why out of bounds parts company with the other three loose-ball cases.
- **A Block Deflect that overshoots is neither.** Possession turns over and the shot follows
  immediately; the shot is a goal or a miss, so the new play -- and the window -- comes from
  the shot. The deflect's own turnover opens nothing, which is what it already did.
- **The run back is now the steal's half of the rule, and a new play resets instead.** A new
  play puts every fielded meeple on both sides back on the space its coach last *assigned* it
  -- at setup, at their last substitution window, or at halftime -- **free of exhaustion**,
  with nothing for a coach to choose. A steal keeps the run back exactly as it was: the
  stealer stays put, everyone else out of their zone goes back to a space in it that leaves
  none uncovered, at a token a space.
- **This is what makes the window meaningful.** The arrangement is the shape a coach set, and
  a substitution window (or halftime, or setup) is the only place one gets set. Open play
  drags meeples out of it; a new play hands it back. A run back does *not* update it -- the
  scramble a steal forces is not a shape anyone chose, so the next new play undoes it.
- **The reset comes before the window**, reversing the old "window first, then the run back".
  The reason for that order was that whoever came on inherited the outgoing player's position
  and so paid their run-back distance; with the reset costing nothing there is no distance to
  pay, and going the other way is strictly better -- a coach who declares rearranges from
  their own formation rather than from wherever open play scattered them, and a coach who
  passes has already had everything passing gives them.
- **Two placements still cost.** The kickoff space after a goal, and picking up an
  out-of-bounds ball, come after the reset at the usual token a space: nothing guarantees a
  coach's arrangement puts anybody on the space in question.
- **An injured player no longer has to be substituted at all**, dropping the rule outright
  rather than letting it fall foul of the change above. The two go together: with windows now
  only at new plays, "declare at your next opportunity" could have stranded a team on a
  compulsory swap a long way from the moment of the injury. Leaving an injured player on,
  disadvantaged, is now simply a choice a coach may make, and the once-a-half declaration is
  the only gate on a window. The bot names an injured player in the window's heading as a
  nudge, and Dinky still subs one off when it can, but nothing is compelled.

### 2026-08-08 (later the same day) -- author, formations in basic mode

- **4-1-1 and 2-1-3 join 2-2-2 in basic mode**, for every team. They read from a coach's own
  goal forward, so 4-1-1 packs the defence and 2-1-3 the attack, and each fields the same six
  cards -- one of each role, with the same three left on the bench. Advanced mode keeps its
  per-team abilities and no longer owes the game its formations.
- **Setup does not offer them: every game kicks off in 2-2-2**, dealt as the standard setup,
  and a formation is changed only by rearranging in a substitution window. A shape is a move
  a coach makes during a game, not part of arriving at one.
- **A rearrangement may change formation.** The substitution window (and halftime, which runs
  the same window) can move a team into any of the three. It was previously restricted to
  swaps, which cannot change a shape. Which card goes where is the coach's; the formation
  fixes only how many go in each zone.
- **Halftime's free placement answers to the coverage rule** -- settling the question the
  earlier entry opened. Halftime frees the *zone* a meeple may go to, not the space: a coach
  still may not leave a space of a zone they stand in empty in order to stack elsewhere in it.
- **The passer picks the receiver when a Low Pass lands on more than one teammate.** "A pass
  to a *second* player sharing the ball's space" named exactly one player while a space held
  at most one of a team's meeples; a stacking formation makes two or three ordinary. The pick
  decides who a Winger's set-up offers the shot to, so it is a real choice and belongs to the
  coach rather than to whoever the occupant list starts with.

### 2026-08-08 -- author, correcting run-back occupancy

- **The run back spreads a team out; it does not cap a space at one player.** The living rules
  had it as "at most one of its own players on a space once players have run back", which is
  backwards: what a coach owes is **coverage**. Every space of a zone they have players in must
  be occupied as far as their players stretch, and anything left over stacks.
- **The surplus stacks wherever the coach likes.** With more players in a zone than it has
  spaces, only "no space left empty" is required -- four players into a two-space zone may
  finish 3+1 as readily as 2+2. No cap per space, no even spread.
- **Nothing changes under 2-2-2**, which is why the wrong wording survived: two players never
  outnumber a zone's 2-3 spaces, so "at most one per space" and "cover every space you can"
  pick out the same placements. It only starts to matter with the advanced-mode formations --
  4-1-1, 2-1-3 -- which is what prompted the correction. `MatchState.run_back_player` and
  `open_spaces_in_zone` enforce the one-per-space reading and are therefore still correct for
  every formation the code can produce; they will need revisiting with the first formation
  that isn't 2-2-2. (Which was the same day: see the entry above, where those formations moved
  into basic mode and the code took the coverage rule.)
- Setup's meeple placement now points at the same occupancy rule instead of restating
  one-per-team-per-space, again with no change under 2-2-2.

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
  (Superseded on 2026-08-08: all three are basic mode, and a zone holding more players than it
  has spaces is exactly what the coverage rule is for.)
- **Every turnover opens a substitution window**, not only a steal or a score attempt.
  (Superseded on 2026-08-08: only a new play does -- a goal, an own goal, a missed attempt or
  a ball out of bounds. A steal opens none.)
- **The window opens before the run back.** (Superseded on 2026-08-08: a new play resets both
  sides to their coaches' arrangement first, and the window comes after that.)
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
| Substitutions "when they win possession", with no split between kinds of turnover | Only a new play (goal, own goal, missed attempt, out of bounds) opens a window; a steal opens none |
| A loose ball's contestant "gains 1 exhaustion" | 1 token per space travelled |
| Nothing about the loose-ball check at all, beyond a pass landing on an empty space | A general check after every maneuver, with four cases |
| Nothing about which space a player runs back to, or what it costs | After a steal the coach picks, covering every space of the zone their players can fill and stacking the surplus, 1 token per space |
| Nothing about a restart putting players back where the coach had them | A new play resets both sides to the arrangement their coaches last set, free of exhaustion |
| Halftime recovery of "1 (or 2, TBD)" | 1 |
| Halftime lets the coach change assignments "as they please" | Free placement to any space on the board, and the visiting side must cover the kickoff space |
| Substitutions: "if and only if all the players on the bench were subbed out" | Two pools -- bench, then back bench for an injured sub only |
| "So if they were subbed while exhausted they are no longer exhausted" | Half the tokens, rounded up; Exhausted follows from what remains |
| A tie at full time goes to the extreme shootout | Tournament mode only; a league game ends tied |
| "For now, we need one player of each role on the field" | A property of the standard setup, not a standing rule |
| Nothing about formations, and a fixed two cards per zone | Games kick off 2-2-2; rearranging can move a team into 2-3-1 or 1-3-2 |
| A pass to the ball's own space names one player | The passer picks, when more than one teammate is standing there |
| Nothing about a Low Pass with no legal destination | The ball goes a space forward, loose, speed still +1 |
| A score attempt from wherever the ball is | Only from within shooting range, set-ups included |

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
the nearest teammate each way, needing a different player, its no-destination case, and the
passer picking the receiver where the destination holds more than one teammate; what a
pass across a shared space buys; only a 3+ High Pass being contested.

**Loose ball:** the one-team case taking possession with no test; the out-of-bounds case and its
placement, after the run back; declining always being allowed, including for a High Pass's
defence; the side that last had possession answering first and alone.

**Run back:** 1 token per space; the coach picking the space; covering every space of the zone
rather than capping a space at one player, per team; the surplus stacking freely once every
space is covered; same-zone teammates being separated; a steal exempting the stealer; only a
turnover running anyone back.

**Substitutions:** no requirement to keep one of each role; cards changing zones freely;
rearranging as the only way to change formation, and all three shapes available to it;
rearranging costing nothing; a new play opening a window and a steal opening none; substituting
after the new-play reset; the two pools; a returning player only losing tokens; halftime's
window not being a declaration; nothing ever compelling a declaration, an injured player
included.

**The arrangement:** what sets one (setup, a substitution window, halftime) and what does not
(a run back); a new play restoring it for both sides, free of exhaustion and with nothing to
choose; the kickoff-space and out-of-bounds placements still costing, after the reset.

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
- **Substitutions**, end to end: the window on a new play (and not on a steal), before the run
  back, gated on the once-a-half declaration and nothing else -- passing is always on offer;
  the declare-then-reply pairing; the two pools; a returning player keeping half their tokens;
  free rearrangement implemented as exchanging two players. Dinky substitutes only to get an
  injured player off, and never rearranges.
- **Halftime**, end to end: recovery, the coach's extra token, each side's independent
  substitution window, and free repositioning gated on the visiting side covering the kickoff
  space.
- **The run back**, end to end: 1 token per space, the coach picking within the zone under the
  coverage rule, the steal exemption, and stacked teammates separated while a space is free.
  Forced placements are applied silently; only a real choice is put to a coach.
- **Formations**, end to end: 2-2-2 at kickoff, and any substitution window (halftime
  included) able to move a team into 2-3-1 or 1-3-2 with the cards of the coach's choosing.
- **The Low Pass receiver**, where the destination space holds more than one teammate.
- **The unchallenged maneuver.** With no defender in the ball's zone the offense picks a
  maneuver on its own and it resolves as an outright win, with no reveal and no skill test.

### Specified but not built

Nothing. What is left unbuilt is blocked on something, and is in the next section.

### Blocked or deferred

- **The extreme shootout** is specified but not built, and is reachable only in **tournament
  mode** -- which setup refuses until it exists. A league-mode game ends tied instead.
- **Advanced mode** -- per-team abilities (the sheet's empty `Advanced` column) -- is
  unspecified. Setup refuses it. Formations left it for basic mode on 2026-08-08.

# D12 Ball -- rules log

Every change the rules have made, with its date; what is still unanswered; and where each
answer came from. **The rules themselves are in [living-rules.md](living-rules.md)** -- this
file never states a rule, it only records how one got there.

**As of:** 2026-08-16.

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

### 2026-08-16 (newest) -- author, a contest is answered by the nearest players, not by the zone

*From the author: a coach sending someone after a contested ball may send "a player from any
zone -- but only one of the closest players in front of or behind the space where the ball is
contested", with the coach choosing freely where two are tied. Extended in the same message to
the out-of-bounds and ceded-ball pickups, and to a new standing rule that every arrangement
covers its kickoff space.*

- **The zone was the wrong measure and distance is the right one.** Every one of these rules
  already charged a token a space, so distance was what the coach was paying in; the zone was
  a second, unrelated gate on top of it, and it produced the reading nobody wants -- a defender
  two spaces away barred from a challenge while one four spaces away in the same zone was
  offered it. Zone now decides where a player *lives* (the arrangement, the run back) and
  nothing about what they may be sent to do.
- **Two candidates, not the whole field**, which is what stops this becoming the out-of-bounds
  pickup's "anyone, from anywhere". The nearest in each direction along the field is a real
  choice -- forward costs position, back costs the cover behind the ball -- where a list of six
  is a distance sum a coach reads off the board. A tie is the coach's, since two players
  equidistant on the same side differ only in who they are.
- **[Sending a player](living-rules.md#sending-a-player) is stated once and linked four times.**
  The maneuver challenge, the loose ball, the long High Pass contest and the required pickup
  were four wordings of one act, and had drifted: three said "in the zone" and the fourth said
  "any field player from anywhere". A single definition is what stops the next rule that sends
  somebody inventing a fifth pool.
- **Two branches all but disappear, and neither is deleted.** "Nobody in the zone to challenge"
  and "neither side has a player in the zone" were reachable states; with distance as the
  measure, a side with any fielded meeple at all has a candidate. So an unchallenged maneuver
  and an out-of-bounds ball are now reached **only by a coach declining**, which is the more
  interesting way to reach either. The no-candidate branches stay because a side can be left
  with nobody fielded near a ball only by having nobody fielded at all, and a rule that reads
  as if that cannot happen is a rule with a crash in it.
- **The walk-in is no longer bounded by geometry.** A challenge could cost at most the width of
  a zone; it can now cost the width of the board, which on board 9 is eight tokens and past
  every player's defensive skill. That is the price of the change and it is deliberate: the
  2026-08-12 decline exists precisely so a coach can refuse to pay it, and it now has something
  worth refusing.
- **The out-of-bounds and ceded pickups are new plays and are stated as such.** Out of bounds
  already was one; a cede reached the same place by a different road (both coaches' windows
  restore their own arrangement, so both sides stand where they mean to by the time the ball is
  picked up), and saying so makes the two the same rule instead of two coincidences. What
  changes for both is the pool: the gaining side sends one of the nearest two rather than
  anyone on the field, and sends nobody at all when the reset already left somebody on the ball.
- **Every arrangement covers its own kickoff space.** Previously only the side kicking off the
  coming period had to, and only at setup and halftime. It is now a property of an arrangement
  wherever one is set, which is what lets a goal restart without the conceding side dropping
  somebody back and paying for it -- the reset puts a player on the kickoff space by
  construction. On board 6 the two sides have different kickoff spaces, so each covers its own.
  - **The standard deal and all five formations already satisfy it**, since midfield packs from
    a side's own end and every shape puts at least two cards there. Only free space positioning
    can break it, so the rule costs a coach nothing until they deliberately empty the space.
  - **The post-goal kickoff fill survives as a fallback, not as a rule.** A game saved before
    this landed can hold an arrangement that leaves the space empty, and both developers run
    the bot against their own saves.
- **Dinky sends the nearest of the options** in all four, which was already its policy for the
  challenge and the pickup and was not for the loose ball, where it took the higher skill. With
  two candidates a skill sort is a token-for-a-point trade Dinky has no way to price, and the
  cheap one is the one that keeps it in the game.

### 2026-08-15 -- author, an avoided own goal is a new play too

*From the author: after an own goal is attempted and avoided, that should be a new play, the
same as one that is conceded -- and it should end last possession exactly as any other new play
does. Asked in the same message about the parallel case, the author confirmed a scoring attempt
won off a Block Deflect that overshoots near the goal already behaves this way.*

- **Avoiding an own goal is now a stoppage, not a continuation.** `run_own_goal_roll`'s safe
  branch used to fall straight into `finish_maneuver_resolution` and let the same player carry
  on; it now calls `begin_run_back(turnover_occurred=True, new_play=True)`, the same call the
  conceded branch makes. Both sides reset to their saved arrangement, ball speed resets to 1
  (set explicitly on this branch, since nothing upstream of it touches speed the way
  `restart_after_goal` does for a conceded one), and the side that kept the ball is the one that
  may declare.
- **This is the one new-play entry where possession doesn't change.** Every other row in the
  turnover table is also a change of possession; an avoided own goal keeps the ball with the
  side that was just defending it. `begin_run_back`'s `turnover_occurred`/`new_play` flags don't
  require a possession change to fire the reset -- they only gate whether the ball is treated as
  dead and both sides reset, which this is now made to do even without one.
- **It ends last possession by the same mechanism as every other turnover.** `begin_run_back`'s
  own check (turnover under last possession ends the period before any reset is attempted) fires
  first, so an own goal avoided under last possession skips the reset and declaration window
  entirely, exactly as last possession says a turnover under it should.
- **A scoring attempt won off an overshot Block Deflect needed no code change.** It already
  resolves through the same `ScoreAttemptView` any other shot does, which unconditionally calls
  `begin_run_back(new_play=True, turnover_occurred=True)` on a goal or a miss -- so it already
  ended last possession correctly. The author's statement confirms the existing behavior rather
  than changing it.

### 2026-08-15 -- author, the clock runs past 15 and the second half starts at 16

*From the author: the clock keeps counting once last possession has begun, and the second half
starts at 16 whatever the first half ran to. Asked where the second half's last possession
falls, the author chose 30 rather than 31 -- fifteen numbered minutes to match the first half's
00-15, not fifteen minutes of play.*

- **"The clock stops at 15" and "last possession is live" were one fact and are now two.** The
  clock stopping was how last possession was recorded: reaching 15 both set the flag and froze
  the number, so a last possession lasting four turns read 15 for all of them. Only the flag
  ends the period now, on the first turnover under it; the clock is charged for every turn as
  usual and a period genuinely can end at 19.
- **Each period has its own last minute**: 15 in the first half and 30 in the second. This is
  the one number the change adds -- the rule is still "at the period's last minute, use last
  possession", asked of a clock that no longer resets between halves.
- **The second half starts at 16 regardless**, which is the whole reason the running clock does
  not simply carry on from where the first half stopped. A first half that ran to 19 is still
  followed by a second half at 16, so **minutes 16 and up occur twice in a game**: once in the
  first half's last possession and once in the second half proper. That collision is
  deliberate -- the alternative was a second half starting wherever the first one happened to
  stop, which makes no two games comparable and puts the halftime whistle at a different number
  every time.
- **30, not 31.** Read as spans, the two halves are 00-15 and 16-30, which is fifteen numbers
  each and what a printed clock track is drawn from. Read as minutes of play, the second half
  is a tick shorter than the first, because a second half kicking off at 16 has already spent
  the minute a first half kicking off at 00 has not. The author took the first reading.
- **The clock has no upper bound at all now.** Nothing caps how long a last possession runs, so
  neither does the clock. What used to be a range check on the scoreboard (00 to 15, or the
  saved game would not load) is now a floor alone.
- **The printed jumbotron's clock track is redrawn for it**, 00-30 in rows of eight with both
  last minutes marked, and the two halves' bands separated. The overrun has no cells: a token
  past the last minute is a period playing out its last possession, which the board says in
  words rather than in squares.

### 2026-08-15 -- author, a shootout test owes no injury checks

*From the author: remove injury tests during extreme shootouts.*

- **This reverses the second half of the 2026-08-10 ruling below**, which settled that a
  shootout test "does not cost exhaustion tokens, but does involve injury checks for exhausted
  players". The first half stands: a test still costs no exhaustion, because it is not one of
  the ways to gain a token. What goes is the check.
- **The reading it replaces was the ordinary rule applied straight.** "Only skill tests cause
  checks" plus "a shootout test is a skill test" gives checks, which is how it was written and
  why the entry below called it the author's ruling rather than a shortcut. It is now an
  exception, stated in both places the rule is: under [Injury check](living-rules.md#injury-check)
  and in the shootout's own section.
- **What it changes in play is a round that can no longer take somebody out of the round.**
  An injury landing mid-shootout withheld that player's skill in a later pair, so a side could
  arrive at its fifth shooter worse off than it ordered them in. Exhaustion carried in from
  full time still costs a player their skill if they were *already* injured when the shootout
  began -- that is the injured-players rule and this does not touch it.
- **Nothing else about the queue moves.** `begin_injury_tests` is still what every other
  contest hands its tests to; the shootout simply no longer calls it, and goes straight to the
  next test. The `shootout_test` resume kind is still *read* so that a game saved between a
  roll and its tests finishes the way it started, and nothing writes it any more -- the same
  way `tie_mode` and `player_board` were retired.

### 2026-08-12 -- author, a passer never receives their own High Pass

*From the author: "an overshot high pass sets up a scoring opportunity even if the ball travels
0 spaces but the player who passes cannot score off their own set up"; and, asked whether a
throw that moves the ball nowhere should therefore be free, "high pass cost should also be
minimum 1".*

- **The 0-space overshoot is confirmed, and it is the half of this that was already right.**
  2026-08-10 settled that "clamped short is clamped short" -- a High Pass thrown from the final
  space overshoots like any other and sets a scoring opportunity up on the space the clamp left
  the ball on, which is the space it started on. Nothing about that moves.
- **What moves is who takes the shot.** That entry read the shooter as "a player from the
  passing team standing where the ball ended", and from the final space the passer is one of
  them -- so the bot has been offering a coach a shot at a disadvantage in exchange for
  throwing the ball to themselves. The passer is now excluded: the set-up goes to a teammate
  sharing that space, and to nobody if there is none.
- **The exclusion can only ever bite on a 0-space pass.** A High Pass moves the ball and not
  the handler, so the only way the passer is standing on the ball when it lands is that it
  never went anywhere. Reading it as a rule about every High Pass rather than about that one
  case is deliberate: it is the same sentence the Low Pass has always had ("the pass must reach
  a different player"), and stating it once means a later maneuver that moves a handler cannot
  reopen the hole quietly.
- **With nobody else on the space the passer keeps the ball.** Not a loose ball -- the offense
  is standing on it -- and not a contest either, since there is no receiver to fight for what
  they were already holding. The maneuver resolves having achieved nothing, which is the
  coach's own lookout.
- **A High Pass costs a minute at the least**, which is the second half of the same answer.
  Its time cost was "Distance" with no minimum, so the throw the first half of this entry
  creates -- the ball up off the last space and back down at the passer's feet -- would have
  been free, and a maneuver that costs no clock is a maneuver a coach can take all afternoon.
  It now reads "Distance, min. 1", exactly as Low Pass has for the same shape of move (its
  shared-space pass, which also moves the ball nowhere). **The minimum only ever applies to
  that one throw**: every distance a coach is offered is at least 2, so nothing short of the
  clamp can come in under it.
- **Upstream never had the case.** The sheet's own time column reads "distance traveled (2-4
  space minutes)", which says a High Pass is worth 2 to 4 and does not contemplate 0 -- a
  clamp at the end of the field is a thing the board does, not a distance anybody chooses. So
  this is a gap being filled rather than upstream being contradicted, and `maneuvers.json`
  needs no edit.

### 2026-08-12 -- author, board 9 gains 3-2-1 and 1-2-3

*From the author: "for 9 space board, include formations: 3-2-1 and 1-2-3".*

- **Two shapes, and the first that are not played on every board.** They put three cards in a
  goal zone, which only board 9 has three spaces for. The three existing shapes stay open to
  every board.
- **This is not "a shape must fit the board one card a space", and must not be turned into
  one.** 2-3-1 and 1-3-2 overfill a six-space board's midfield and are played there anyway,
  stacking -- the whole reason the stacking machinery exists. Which boards a shape is played
  on is the author's call and is written down per shape (`board_sizes` in `basic_rules.json`),
  not derived from the geometry.
- **Neither shape stacks.** Board 9's zones are three spaces deep and neither puts more than
  three cards in one, so nothing about the surplus rules moves. Both cover the kickoff space
  from either side: two cards in a three-space midfield stand on the two spaces nearest their
  own goal, and the middle one is the second of those.
- **2-2-2 stays open to every board** and cannot be restricted, since it is the shape every
  team is dealt whatever board they are dealt onto.

### 2026-08-12 -- author, a challenge that costs exhaustion may be declined

*From the author: "it's no longer mandatory to challenge a maneuver if your player has to run
towards it and gain exhaustion. you can send no one, in which case the other team just gets to
do their maneuver."*

- **The mandatory challenge is now the exception, not the rule.** A defense with somebody in
  the ball's zone may keep them where they are and let the maneuver succeed unchallenged --
  the same outcome as having nobody in the zone at all, which the rules already had a branch
  for.
- **A defender already standing on the ball still challenges, and is the only one who does.**
  The line the author drew is exhaustion: that defender pays nothing to challenge, so there is
  nothing to weigh and nothing to decline. Everyone else pays 1 token per space to walk in,
  and paying it is now a choice.
- **This makes the maneuver challenge the same shape as the long-pass contest**, which has
  read "a defender already there contests automatically; otherwise defense may send a zone
  player, paying 1 token per space, or decline" all along. The 2026-08-11 pass had corrected
  the maneuver's wording from "may" to "must" to match the old document; that correction was
  right about what the rules then said and is now superseded by the author.
- **Nothing about the uncontested maneuver itself changed.** No challenger still means no
  secret pick from the defense, no reveal, no skill test, and no disadvantage for an injured
  attacker -- there is no opponent to be disadvantaged against.

### 2026-08-12 -- author, board 9's deal spreads the goal zones and clumps midfield

*From the author: "for boards that are size 9, the starting set up should spread out the
defender and attacks so that home team defender is in H3 and their striker is in V3," and
then "midfield should be clumped toward the defensive goal so home team PM is in M2 and
their midfielder in M1."*

- **A goal zone's two cards now stand on its two end spaces**, rather than both packing
  against that coach's own edge and leaving the far space empty. Board 9's zones are three
  deep, so this is the only board it shows on: on 6 and 7 the goal zones are two deep and a
  pair fills them either way, which is why nothing about those boards moves.
- **The two sides stay mirror images**, so the change reads the same from both ends: home
  deals Fullback H1 / Defender H3 and Winger V1 / Striker V3, and the visitors Fullback V3 /
  Defender V1 and Winger H3 / Striker H1. A Striker and the Fullback marking them share the
  goal-line space, which is legal -- coverage is checked per team.
- **Midfield clumps toward each side's own goal instead**, confirmed by the author in the
  same exchange: home Midfielder M1 and Playmaker M2, the visitors M3 and M2. So the spread
  is a rule about the goal zones, not about zones in general -- and the reason is the kickoff
  space, which sits in midfield and which the kicking side has to have somebody standing on.
  Spreading two cards over a three-space midfield would empty the middle and hold the coach
  in the setup window until they moved somebody back onto it.
- **A shape that leaves one card in a zone still puts it on that coach's own end**, since
  there is no pair to spread. That is 2-3-1's lone attacker and 1-3-2's lone defender,
  unchanged.

### 2026-08-11 -- author, a defender off the ball is worth half

*From the author: "When shooting to score, defense players that share space with the ball
provide their full defensive skill value. All the other players between the ball and the goal
share half of the defensive value (rounded up)." Asked whether the halving is per player or
over the group's total, the author confirmed per player.*

- **Standing on the ball is now worth more than standing in front of it.** The defence used to
  add every intervening meeple's whole defensive skill, so a wall four deep was worth as much
  wherever it stood; now only the meeple contesting the shooter's own space is worth its face,
  and the rest are worth half, rounded up.
- **Each defender halves their own skill.** Two 5s in the way add 3 + 3 = 6, not 5. The two
  readings agree whenever at most one defender rounds up, which is most positions -- so this
  is written down rather than left to be re-derived from a board where it happened not to
  matter.
- **Rounded up, so a defensive skill of 1 never rounds away.** Every card in the way is worth
  at least 1, which is what keeps a Striker between the ball and the goal from being worth
  nothing at all.
- **The shot's own image had to change with it**, because a defence of "6 + 3 + 1" says
  nothing about which term was halved or whose it was. Each defender's portrait now carries
  the value they contribute -- a solid badge on the ball, an outlined one and the skill it was
  halved from beyond it -- under a label naming each band.

### 2026-08-11 -- editing pass, the living rules consolidated

*No rule changed here.* [living-rules.md](living-rules.md) was rewritten for length -- 1153
lines to about 360 -- folding the standalone sections into eight top-level ones and replacing
prose with tables wherever the prose was only listing cases. Every mechanic was checked against
the code on the way through. Recorded because the section names moved, and a later pull from
upstream will be read against headings that no longer exist:

| Was | Now |
| --- | --- |
| Setting up a game | Setup |
| Components › The field › Shooting range | Field, teams, and terms › Field, direction, and shooting range |
| Components › The field › The kickoff space | folded into the same section |
| Maneuver | Maneuvers |
| Ball speed / Loose ball / Scoring opportunities / Own goal | subsections of Ball speed, loose balls, and set-ups |
| Turnovers and running back › Steals and new plays | Turnovers, resets, and running back (the table at its head) |
| The clock, halftime and full time | Clock, halftime, and full time |

Two things the pass settled rather than carried over, both places the old document disagreed
with itself:

- **A Winger's Low Pass set-up is range-gated like any other.** The Low Pass section said the
  ability had "no position requirement of any kind" while Scoring opportunities said a set-up
  is offered only where the shot is legal. The second is the rule and the code
  (`set_up_shot_candidates`); the Low Pass section now says "if in range".
- **Re-picking the formation a side is already in is no longer described as a no-op.** It
  re-deals, which discards any zone assignment and space positioning the coach has done since.

Two corrections and three clarifications came out of reviewing the pass, all restoring what
the old document said:

- **The defense must challenge** when it has anyone in the ball's zone -- the compression had
  it as "may", which reads across from the loose ball, where declining really is always legal.
- **Ceding needs the declaration in hand**, not just a side out of range. Both conditions are
  back in the turn sequence and in Ceding the ball.
- **Block Deflect turns nothing over** except the clamped-with-a-defender-on-the-landing-space
  case. The compression had "possession flips and speed resets" reading as unconditional.
- **Last possession belongs to whoever holds the ball** once the action that reached 15 has
  resolved, which is not always a side that just gained it.
- **An uncontested maneuver escapes the injured player's disadvantage**, alongside the
  both-injured case it was already recorded with (2026-08-09).

Four more the compression dropped, restored after review:

- **A side that positions nothing keeps the arrangement it had.** Only a coach who actually
  moves somebody sets a new one, so the scramble a half ends in never becomes a side's shape
  by default. The bot reaches this by putting a side back on its arrangement as the window
  opens, which is presentation; the rule is the outcome.
- **The injured player's withheld skill is only the loose ball and the long High Pass.** The
  compression left it next to the forced maneuver test, which reads as though that test were
  withheld too. It is not -- an injured player made to roll for their own maneuver adds their
  skill in full, and a score attempt is untouched. Recorded because this was read backwards
  once before.
- **A won Pressure names two different carriers**, on opposite teams: ordinarily the handler,
  own-goal roll survived included, and the Defender where their ability also stole it.
- **Only a turnover moves anyone.** A resolution that leaves possession where it was runs
  nobody back, resets nobody and charges nobody, so displacement persists until a turnover --
  which is where a scramble at halftime comes from in the first place.

### 2026-08-10 -- author, a team out of shooting range may cede the ball to coach

*From the author: "During offensive choice, if the team is not in shooting range - it has an
option to cede possession to call for a substitution. That takes up their 'once per halftime'
allotment." Then, asked what that does to the ball, the clock and the other coach: the ball
stays "same place where it was ceded"; the rearrangement is exhaustion-free; "the other coach
gets to sub"; ball speed resets to 1 and there is no time cost; under last possession it ends
the game; and a side with both benches spent is still offered it, that state being "very
rare". Then, asked what settles a ceded ball nobody is standing on: "the team that gains
possession has to send a player to the space where the ball was ceded."*

- **A third choice on the turn**, offered exactly where the score attempt is not: out of
  [shooting range](living-rules.md#field-direction-and-shooting-range), and only while the side still holds its
  once-a-half declaration. The two reads are the same one, which is why the turn prompt can
  explain either missing button in a sentence.
- **It is a turnover with none of a turnover's machinery.** The ball does not move, ball speed
  resets to 1, no time passes, and nobody runs back -- each coach's window opens on their own
  arrangement, free of exhaustion, which is what a Coaching Choice does anyway. So it is a
  third kind of turnover beside the steal and the new play, and the first that neither runs
  players back nor restarts play.
- **It is charged like a declaration and answered like one**, the reply costing the answering
  side's own declaration nothing. The only difference is that neither coach is *asked*: the
  side ceding said so by ceding, and the side receiving has been handed the ball and the
  window together.
- **A ball nobody is standing on is picked up**, from anywhere on the field at a token a
  space, once both windows have closed. The receiving side's arrangement covers their zones,
  not wherever open play left the ball, so this will be the common case -- and it is the same
  step an out-of-bounds ball already asks for. It is a **requirement, not an offer**: the side
  gaining possession sends somebody, and cannot decline and leave the ball lying there.
- **It is not a loose ball.** The other reading was to let the general loose-ball check answer
  it, which would have made the ceded ball a contest the ceding side could win back -- and,
  with one of their own meeples still standing on it, win back uncontested, having bought a
  Coaching Choice with nothing. The author's answer settles it the other way: ceding is a
  concession, not a gamble.
- **Under last possession it ends the period**, with no window on either side: the first
  turnover under last possession ends it whatever the turnover was.
- **A side with nobody to bring on may still cede.** The window is the whole Coaching Choice,
  and hiding the button for a state that needs all three substitutes to have come off injured
  would mislead far more often than it helped.

### 2026-08-10 (latest) -- author, an empty bench is the whole of what opens the back bench

*From the author, correcting the two-pool rule as it had stood since 2026-08-04, when asked
what could leave a side with nobody to bring on: "It's not true that the back bench only open
for injured players. Rather, as a general matter for substitutions at any window: if there are
any players on the bench, you can only sub by bringing one of them in. If there are no players
on the bench, you can sub for someone on the back bench. Injured players can never come back
on to the field."*

- **The back bench opens on an empty bench and nothing else.** It used to also require that the
  player going off was injured, which meant a side with three swaps behind them and a healthy
  six had no substitution left in the game. Who is going off never mattered.
- **Injury bites on the player coming *on*, not on the swap.** An injured player can never
  return, whichever pool they are sitting in; that is the only thing that takes anybody out of
  a pool.
- **So a side runs out only when both benches are spent**: three substitutions to drain the
  bench, and every one of the three who came off went off injured. That is the case the window
  before the shootout skips, and it is now the only case in the game where a coach has nobody
  to bring on.
- `MatchState.substitution_pool` no longer takes the outgoing player. The answer is the same
  for all six, so a caller passing one was asking a question the rules do not ask.

### 2026-08-10 (also) -- author, a coaching window between full time and the shootout

*From the author: "open a coaching window after fulltime and before extreme shootout, allowing
1 sub", and then the two things that request did not settle. With no kickoff to key the order
on -- home go first at setup and the visitors at halftime, both because they restart play --
the **home coach goes first**. And the window offers the **substitution alone** rather than
the usual four actions.*

- **A level score at full time now opens a Coaching Choice before the shootout**, one to each
  coach independently, home first. It reverses the "nobody comes on for it and nobody is
  substituted" line the shootout section had carried since it was written earlier the same
  day: a side that finished the second half with a spent or injured player gets one chance to
  take them off before the shooting starts.
- **One substitution, and it is the window's own allowance.** There is no half left for it to
  be drawn from, so it is counted inside the window the way halftime's two are. A side that
  spends everything it is given now substitutes seven times in a game rather than six.
- **The substitution alone.** A shootout is played by who is on the field and by nothing about
  where they stand, so a formation change, a zone assignment or a space positioning here would
  move meeples that never play again. This is the first Coaching Choice that is not the same
  four actions.
- **It neither opens on the coach's arrangement nor sets one.** Every other window puts the
  side back on the spaces its coach last set, and records where they finish. Here nothing is
  ever played from a position again: restoring would rearrange the last board of the game for
  no reason, and recording would overwrite an arrangement nothing will read.
- **Everything about who may come on is unchanged.** The one swap comes off the bench, or off
  the back bench only when the bench is empty and the player going off is injured. A
  substitute returning from the back bench still loses half their tokens -- which, at a whistle
  that recovers nothing, is the only exhaustion in the game that still moves. (Superseded
  hours later, in the entry above: the injured-swap requirement was never the rule.)

### 2026-08-10 (second latest) -- author, every tie goes to the extreme shootout

*From the author, who asked for league mode to be removed and the shootout built, and then
answered the four things the shootout section did not say: the six who shoot are "the six on
the field at full time"; a shootout test "does not cost exhaustion tokens, but does involve
injury checks for exhausted players"; shootout goals are "added to the match score"; and in
sudden death, once all six have gone, eligibility resets and each pick is free. Then, asked
whether the whistle recovers anything the way halftime does: "noone recovers exhaustion at
full time". Separately: "the term 'clash' is an old reference", to be replaced with "skill
test" throughout.*

- **League mode is gone, and with it the tie-mode setting.** Every game is now settled: a
  level score at full time goes to the extreme shootout, full stop. Setup no longer asks, and
  the `tie_mode` field is off the game record -- a saved game still carrying the key is
  loaded without it rather than skipped.
- **The shootout is played by the six on the field at the whistle**, in the state the second
  period left them. No substitution before it and nobody off the bench, so an injured player
  shoots -- at the disadvantage injury already carries in a contest, adding no skill modifier
  and rolling the bare d12.
- **A shootout skill test costs no exhaustion but still owes injury checks.** It is not one of
  the ways to gain a token, so nothing is charged; an Exhausted player taking part in one
  still rolls a check when it resolves, which is the ordinary rule for a skill test read
  straight. An injury landing in one round withholds that player's skill in a later one.
- **Full time recovers nothing**, unlike halftime, which takes a token off every fielded
  player and a second off one of them. A side goes to the shootout holding everything the
  second half left it with, so players who finished over their defensive skill are still
  Exhausted and owe a check on every test they take part in. This is what makes the two
  answers above bite: with no tokens charged and no recovery either, who is Exhausted in a
  shootout was settled before the whistle, and the only thing that can change it is an injury.
- **Shootout goals go on the scoreboard.** A game level at 2:2 and settled 4-3 is a 6:5 win.
  The shootout's own tally is kept alongside it, because that is what decides when there is no
  point rolling on -- and because 6:5 says nothing about how the game was won.
- **Sudden death resets eligibility and chooses freely.** The order set before the first round
  governs that round alone. Every test after it is a fresh secret pick from whoever has not
  gone this round, and when all six have gone the round ends and a new one starts with
  everybody eligible again.
- **A tied shootout skill test is not re-rolled.** It scores for nobody and the shootout moves
  on -- the one place in the game a tied skill test is left tied. Already in the rules, and
  worth naming next to the ordinary skill test's re-roll.
- **"Clash" is retired everywhere.** It was renamed to "skill test" on 2026-08-07 but survived
  in the shootout section, which was the last text written under the old term.

### 2026-08-10 (earlier) -- author, a High Pass that overshoots sets up a shot it has to fight for

*From the author, given directly and then refined twice in the same conversation: "if a high
pass overshoots the goal - whether the coach chose 2 or 3 or 4 - it sets up a scoring
opportunity in the space closest to the goal with the speed modifier as a negative"; then that
the distance choice "should be moot" and so "should not be offered" from a position 0 or 1
spaces off the end, where the overshoot "offers a choice between a scoring attempt with a
negative speed ball modifier and a high pass contest with a negative ball speed modifier to keep
the ball"; then that "a fullback should not be offered a 4 space when that would overshoot, and
no player should be offered 3 spaces when 2 is possible and 3 would overshoot".*

- **An overshoot sets up a scoring opportunity at any distance.** Until now only an exact 2
  could, and only by landing on a teammate; a 3 or a 4 that ran out of field went straight to
  the long-pass contest. The shooter is a player from the passing team standing where the ball
  ended, and the space is the one the clamp put it on -- the space closest to the goal.
- **The ball speed modifier is subtracted rather than added**, on the shot and on the contest
  alike. This is the first thing in the game that reverses the modifier's sign; everything else
  either adds it or ignores it. It is why the modifier now has a single home rather than being
  halved afresh at each site that pays it.
- **The shot and the contest are one choice, not an offer and a fallback.** Turning down the
  shot lands in the contest, at the same disadvantage. There is no third branch that settles the
  ball quietly.
- **A distance that runs off the field is not offered at all.** A longer pass landing where a
  shorter one already would is that pass at a disadvantage -- negative modifier, contest owed --
  so offering it is offering a strictly worse button. Three spaces from the end a Fullback
  chooses 2 or 3; two spaces from the end, 2 is the whole menu.
- **With the ball 0 or 1 spaces from the end there is no menu.** Every distance is the same
  pass, so the prompt is skipped rather than answered and the pass resolves as an overshoot
  directly. This is now the *only* way an overshoot happens, which is what collapsed the earlier
  reading that a declined overshoot of 2 might be an ordinary catch: a 2 can only overshoot from
  a position where no distance was ever asked for.
- **A pass that cannot move the ball at all is still an overshoot**, confirmed: "clamped short
  is clamped short". A coach whose ball is already on the last space throws a High Pass for a
  shot from where they stand, with the modifier against them. Same test Block Deflect already
  used for its own overshoot.
- **An overshoot with nobody from the passing team on the landing space sets nothing up** and
  is a loose ball as before. Nothing was said about this either way; there is no shooter, so
  there is nothing else it could be.

### 2026-08-10 (later still) -- author, a Coaching Choice opens on the coach's own arrangement

*From the author, on what a coach should be looking at while they coach: the half-field the
bot puts in front of them "should show the positioning that the coach last settled - not the
positions that players last ran back to after a turnover".*

- **Every Coaching Choice now begins by putting the side back on the arrangement its coach
  last set**, free of exhaustion -- the same restore a new play already does, and resting on
  the same rule that a run back never overwrites that arrangement.
- **Only halftime is actually changed by this.** A new play resets both sides *before* it
  offers the window, so the restore finds nothing to do; setup runs on a fresh deal. Halftime
  had no reset at all, so a coach was rearranging out of wherever the first half happened to
  stop -- which is exactly the scramble the arrangement exists to undo.
- **The second half now starts from the shape a coach chose**, since where each side finishes
  its halftime window is its arrangement for the half, and it now finishes from its own shape
  rather than from a run back.
- Upstream says nothing either way about positions at halftime; this is the author's, given
  directly.

### 2026-08-10 (later the same day) -- author, the player board is called the team board

*A rename, not a rule. Nothing about what the board holds or how it is used changes.*

- **"Player board" becomes "team board" everywhere.** The living rules were already saying
  both: the Terms table described a player card's position as showing its zone "on the team
  board" while the section defining that board was headed "Player boards". Team board is the
  right one -- the board belongs to a coach's whole side, and "player board" reads as the
  board belonging to one player, which is the player card.
- **The heading `### Player boards` is now `### Team boards`.** Nothing linked to
  `#player-boards`, so no anchor breaks; `/d12ball rules_search team board` finds it under the
  new name.
- **Upstream still says player board**, so far as the sheet's component data shows -- recorded
  in "Where upstream is behind" below. Worth confirming against the Notion page on the next
  pull, since this rename was made here rather than upstream.

### 2026-08-10 -- documentation only, three sub-rules of The field given headings

*No rule changes here. This is structure, and the parts of it that are a judgement call are
asked as inline comments on the pull request rather than settled.*

- **Shooting range, Occupancy and the kickoff space are now `####` headings** under
  Components › The field, where they had been bold run-in paragraphs. They were already the
  targets of links -- `#shooting-range` had an explicit `<a id="shooting-range"></a>` above
  it -- so the links worked, but a hand-written anchor is not a heading and so is invisible
  to everything that reads the document by its headings: the Contents list, and
  `/d12ball rules_search`, which slugs headings and nothing else.
- **All three had to move together.** A heading runs until the next one at its level or
  above, so promoting Shooting range alone would have swallowed Occupancy and the kickoff
  space into its section. Either all three are headings or none is.
- **Four links now point at the sub-rule rather than the section containing it**:
  `[occupancy](#the-field)` in three places and `[kickoff space](#components)` in one. Both
  were aimed wide because there was nothing narrower to aim at.
- **`#substitutions` is gone.** It was a second hand-written anchor, sitting immediately
  above `## Coaching Choice` and named for something the document has no heading called; its
  one use, in Steals and new plays, now points at `#coaching-choice`. The substitution rules
  proper are under Coaching Choice › Who may come on, which is the other candidate target --
  see the pull request.
- **Every one of the document's 94 internal links now resolves to a real heading.** Both
  hand-written anchors are removed, so there is nothing left that a heading-based reader
  cannot see.

### 2026-08-09 (ball carrier, 3 of 3) -- author, the ball's holder does not run back

*Answering the question the entry below raised, and generalising the run-back exemption in
the process.*

- **The exemption is the ball, not the steal.** It had named two resolutions -- Steal
  Intercept and a Defender's Pressure steal. The author's answer is that the **ball handler**
  does not run back, whoever they are and however they came to be holding it. So the winner
  of a loose ball or a long High Pass is exempt too, which is what the entry below left
  inconsistent.
- **The two rules are now one fact read from either end.** The ball's holder keeps it into
  the next turn, and keeping it is why they stay put. `begin_run_back` reads the exemption off
  `ball_carrier_id` instead of taking a `stays_player_id` argument, so a resolution that names
  a carrier cannot forget to name the exempt player as well -- which is exactly how the old
  gap arose.
- **A new play exempts nobody**, since nobody carries a dead ball, and its reset moves both
  sides regardless. Worth stating because a goal scored off a High Pass set-up leaves a
  receiver recorded as holding a ball that is already on its way back to the kickoff space.
- **Nothing else changes about the run back**: the rate is still a token a space, the
  coverage requirement is unchanged, and where a stack has to be separated the exempt player
  is still the one who stays.

### 2026-08-09 (ball carrier, 2 of 3) -- author, a contest winner carries the ball

*Answering the question the entry below left open, and extending it to the loose ball in the
same breath.*

- **Whoever wins a contest is the ball handler.** The author's answer: the receiver of a High
  Pass who wins the contest, the challenger who wins it instead, and the winner of a loose
  ball. So a contest names a carrier the same way a pass does -- it was the last resolution
  that could still be read as leaving the ball to a space rather than to a person, and it
  does not.
- **An unopposed recovery counts.** Only one side sending anybody is still how that player
  came to be holding it, so the branch that skips the roll names a carrier too.
- **What is left free is now only the dead ball**: a new play and its reset, the kickoff, the
  two placements a restart owes, and a Block Deflect, which sends the ball to a space rather
  than to anyone.
- **This exposed an inconsistency in the run back.** Only a steal exempted a player from
  running back, and the exemption named Steal Intercept and a Defender's Pressure steal -- so
  a contest winner assigned to another zone was run back off the ball they had just won. Left
  as it was at the time, and answered by the entry above.

### 2026-08-09 (ball carrier, 1 of 3) -- author, the ball is carried by a player

*Given as three cases; the general rule behind them, and the two edges it reaches, were
confirmed in the same exchange.*

- **The ball belongs to a player, not to a space.** The author's framing: "the ball is in
  possession of a specific player." Where a resolution leaves it with somebody in particular,
  that player takes the next turn -- so a coach who dribbles forward can no longer start the
  next turn with a different player who happens to share the zone. Possession has always been
  tracked per *team*; this is the first rule that tracks it per *player*.
- **The three cases as given** were a won Dribble Advance, a won Steal Intercept, and losing
  to Pressure. All three are the ones where the ball travels attached to a person.
- **Pass receivers carry too**, confirmed when asked, on the reading that a pass is aimed at
  somebody and the passer already names them out of a stack. So a completed Low Pass and a
  received 2-space High Pass both name a carrier. That is what makes it one rule -- "whoever
  the ball was left with" -- rather than three exceptions to remember.
- **A Defender who steals on a won Pressure carries it**, confirmed when asked. They are
  already the player the run back exempts, on the grounds that they are the one holding it.
- **An own goal survived still carries.** Pressure that overshoots and then passes its roll
  leaves the handler where they were, still holding the ball; nothing about the roll changes
  who has it. A conceded own goal is a new play and clears the carry with everything else.
- **A contested ball is nobody's.** A loose ball, however it is won, and the long High Pass
  contest both end with the ball fought for rather than given, so the coach chooses off the
  ball's space as before. Block Deflect likewise names nobody -- it sends the ball back to a
  space, not to a player.
- **A carry lasts exactly one turn**, set by the resolution that ends a turn and spent by the
  one that follows. A new play, a period restart and a kickoff all clear it.
- **What is fixed is who acts, not what they do.** A carrier chooses freely between a shot and
  a maneuver, subject to shooting range like anyone else.

### 2026-08-09 (later still) -- author, the Coaching Choice

*Given as a specification for the substitution interface, which is being rebuilt; most of it
turned out to be rules rather than interface, so it is recorded here.*

- **The substitution window, halftime and setup are now one thing, the Coaching Choice.** They
  had drifted into three flows offering overlapping subsets of the same four actions --
  formation, substitution, zone assignment, space positioning. They are now the same four
  everywhere, and the occasions differ only in how many substitutions they allow and who goes
  first. The author's framing: a coach should not have to learn three menus to do one job.
- **Setup now offers one, which is a new rule.** Both teams are still dealt the standard 2-2-2
  and both are still identical in basic mode, but a coach may now change any of it before
  kickoff instead of waiting for their first window. Nothing kicks off in a shape nobody chose.
- **Substitutions at setup are unlimited, and a player taken off goes to the *bench*, not the
  back bench** -- the single exception to "the bench only ever drains". The game has not
  started, so nobody has been used up and there is nothing for the back bench to record. This
  also keeps setup from being a trap: a coach experimenting with their line-up before kickoff
  would otherwise permanently retire whoever they took off.
- **The 2-and-1 asymmetry is gone.** The declaring side had two substitutions and the
  answering side one. Both now draw on a flat **2 per half**, tracked per side across the
  whole half rather than per window. The declaration itself is unchanged and still once a
  half, so the counter and the gate now do different jobs: a side that spent both
  substitutions answering someone else's declaration can still declare later in the half, and
  gets the rearrangement without the swaps.
- **Halftime keeps a limit of 2, as its own allowance.** It had been "a declaring team's
  allowance"; the author's call is that it stays two rather than going unlimited like setup,
  and that it is not drawn from either half. So a side can substitute six times in a game --
  two in each half, two at halftime.
- **Halftime's any-zone repositioning is dropped.** It was the one place a meeple could be put
  outside its own assigned zone, which meant a card in one zone and its meeple in another --
  a state nothing else in the game produces and the run back exists to undo. The Coaching
  Choice reaches every arrangement it was there for, by changing formation and swapping zone
  assignments, and reaches them with the cards and the meeples agreeing. **The visitors still
  have to finish halftime with a player on the kickoff space.**
- **The visiting coach goes first at halftime**, where the code had been running home first.
  The rule the author gave is halftime-specific; setup's order (home first) is inferred from
  it, on the reading that the side kicking off coaches first, and is worth confirming.
- **A zone-assignment swap now moves the meeples too.** Exchanging two cards' zones used to
  leave both meeples standing where they were, displaced, for the coach to place afterwards
  or the next run back to collect. It now trades their spaces along with their zones. That is
  what made the old "place your meeples" step necessary, and dropping it is what lets the
  Coaching Choice guarantee no meeple ever stands outside its own zone.
- **Changing formation now re-deals the side automatically**, by defensive skill, highest
  first, from the coach's own goal forward -- rather than asking the coach to fill each zone
  from a list of six. Within a zone, placement runs from the space nearest their own goal
  outward, and the surplus stacks on the middle space of a three-space zone or the
  centre-nearer space of a two-space one. **Board 6's midfield is the one zone whose two
  spaces are equally near the middle**; the author's tie-break is the space nearer that
  coach's own goal, matching how `setup_space_order` already deals outward from a side's own
  end. Ties on defensive skill cannot arise between the six standard roles, whose defences are
  1 to 6, but the code breaks them at random for safety.
- **Space positioning swaps rather than refusing.** Moving a meeple onto an occupied space
  used to be governed by the coverage rule, which on a packed zone left a coach with nowhere
  legal to go and a separate "trade places" fallback to find. The rule is now local: if the
  target is occupied and the mover is the only one of their team on the space they leave, the
  two trade. **Where the target holds more than one teammate, the coach picks which one comes
  back** -- the author's call, rather than taking the first. Coverage is preserved by
  construction under this rule, so every space of a zone can simply be offered.

### 2026-08-09 (later the same day) -- author, the injured player's disadvantage spelled out

*Two rounds of clarification the same day, folded into one entry: the two maneuver clauses
first, then the edge cases and what the disadvantage does to a roll.*

- **No rule changed here; the wording did.** "They automatically lose a challenge, and must win
  a skill test even when their maneuver beats their opponent's outright" has stood since the
  rules were first copied in on 2026-07-25, and had never been built. Implementing it turned up
  a reading on which the two clauses collide -- section 4 calls the skill test a tie rolls a
  *challenge*, so "automatically lose a challenge" could be read as swallowing the forced test
  the second clause creates, leaving that clause with nothing to do. The author's answer is
  that they are two separate moments, and the paragraph now says so directly rather than
  leaving it to be inferred.
- **A tie loses.** When an injured player's maneuver ties their opponent's, they lose it
  outright and the opponent resolves their own effect. Nothing is rolled.
- **A win has to be rolled for.** When their maneuver beats the opponent's outright, the two
  roll a skill test instead, and the injured player has to win it for their maneuver to stick.
  Losing it hands the effect to the opponent's maneuver, which lost the ranking -- that is what
  the clause leaves behind, and it is now stated rather than implied.
- **The forced test is an ordinary skill test.** A tied total is re-rolled, as usual, until it
  is decided; each re-roll charges its token to whoever can still take one.
- **The automatic loss costs no token**, which follows rather than being decided: the token is
  what a player pays for entering the test, and no test is entered. Worth knowing it is a
  derivation if the author ever prices the auto-loss differently.
- **Both participants injured is neither of them disadvantaged**, confirmed by the author: the
  tie is an ordinary tie and a decisive maneuver an ordinary win. Read literally the wording
  above says each of them loses the tie, which is why this is now stated rather than left to
  be worked out.
- **An unchallenged maneuver still succeeds outright**, injured or not, also confirmed: with
  no defender in the ball's zone there is nobody to tie with and no test they can be made to
  roll. The unchallenged maneuver postdates the disadvantage, so this had been an assumption.
- **In a contest an injured player adds no skill modifier** -- keeping a long High Pass, or
  contesting a loose ball. Their offensive or defensive skill stays off the roll entirely and
  they roll the bare d12. This is what the extreme shootout's "adds nothing" had always meant;
  that wording is gone because taken at its word it also stripped the ball speed modifier a
  High Pass receiver gets for keeping what the pass delivered.
- **It is the skill and nothing else, in a contest and nowhere else.** Every other modifier
  still applies, role abilities included. Outside a contest nothing is touched: a maneuver's
  skill test and a score attempt are rolled as normal, so a Midfielder keeps their +3 on a Low
  Pass and a Striker keeps theirs off a set-up -- the Striker confirmed by the author
  directly. The disadvantage in a maneuver is already the two clauses above, and it is not
  compounded by a third.
  - **"Ability modifier" was the wrong name for it and cost a round trip.** It first went in
    as the loss of a *role's bonus* -- the Midfielder's +3 -- which is a different quantity
    and, in the code, a different line. The rules and the code both say "skill modifier" now.

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
  (Superseded on 2026-08-10: an empty bench is the whole of what opens the back bench. Who is
  going off has nothing to do with it.)
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
| "Player board" (the sheet's component data; the Notion wording is unconfirmed) | Team board |
| A fixed 12-card board, 6 field cards, two spaces per zone, and a 'back'/'front' half to each zone | Board sizes 6, 7 and 9; zones of 2-3 spaces; no back/front |
| Home is randomly assigned | A coin toss, and the winner chooses home or visiting |
| "Place the ball ... on the space 3 of the home team" | The kickoff space, by board size |
| Cleanup restarts "from the middle (back of the midfield)" | The same kickoff space rule, for every restart |
| "Clash" / "clash roll" | Skill test |
| A score attempt's "each player rolls a d12" | Exactly two dice, one per coach; the defence sums intervening meeples |
| Every meeple in the way adds its whole defensive skill | Full on the ball's own space, half rounded up beyond it |
| Nothing about what a score attempt costs | Nothing for a plain attempt; 1 token to a shooter off a set-up, after the roll |
| The own goal is triggered by a deflected pass, and rolled at a **disadvantage** | Triggered by Pressure's overshoot only, rolled at an **advantage**, and costs 1 token |
| Setting a scoring opportunity describes only the old fixed-2 High Pass overshoot | Four set-ups (High Pass of 2, a High Pass that overshoots, a Winger's Low Pass, a Block Deflect overshoot), each a choice |
| The ball speed modifier is always added | An overshot High Pass subtracts it, on the shot it sets up and on the contest behind that shot |
| A High Pass is a free choice of 2 or 3 (or 4) | Only distances that fit on the field are offered, and none is offered at all with the ball 0 or 1 spaces from the end |
| A turnover says nothing about ball speed | Every turnover resets it to 1 |
| Substitutions "when they win possession", with no split between kinds of turnover | Only a new play (goal, own goal, missed attempt, out of bounds) opens a window; a steal opens none |
| Nothing about giving the ball up on purpose | A side out of shooting range may cede it to coach, spending their once-a-half declaration; both coaches then get a window |
| The defense must challenge a maneuver whenever it has anyone in the ball's zone | Only a defender already on the ball must; anyone who would have to walk in may be kept back, and the maneuver goes unchallenged |
| A challenger, and a loose ball's contestant, come from the ball's zone | Zone does not come into it: a coach sends the nearest player in front of the space or the nearest behind it, from anywhere on the field |
| An out-of-bounds pickup is not described at all | The same nearest-two choice, made after the reset and only when nobody of that side is already on the ball |
| Nothing about the kickoff space beyond where it is | Every arrangement covers its own side's kickoff space, so a restart moves nobody |
| A loose ball's contestant "gains 1 exhaustion" | 1 token per space travelled |
| Nothing about the loose-ball check at all, beyond a pass landing on an empty space | A general check after every maneuver, with four cases |
| Nothing about which space a player runs back to, or what it costs | After a steal the coach picks, covering every space of the zone their players can fill and stacking the surplus, 1 token per space |
| Nothing about a restart putting players back where the coach had them | A new play resets both sides to the arrangement their coaches last set, free of exhaustion |
| Halftime recovery of "1 (or 2, TBD)" | 1 |
| Halftime lets the coach change assignments "as they please" | A Coaching Choice, the same four actions as any other, with the visiting coach going first and having to cover the kickoff space |
| Nothing about a coach changing anything before kickoff | Setup offers a Coaching Choice, with unlimited substitutions and players taken off going back to the bench |
| Substitutions "up to 2", with no period attached | 2 per side per half, plus 2 more of halftime's own allowance, plus 1 before the shootout |
| Substitutions: "if and only if all the players on the bench were subbed out" | The same condition, now that the injured-swap requirement is gone -- plus injured players never returning |
| "So if they were subbed while exhausted they are no longer exhausted" | Half the tokens, rounded up; Exhausted follows from what remains |
| The shootout says nothing about who shoots, what it costs, or what its goals do | The six on the field when it starts, after a one-substitution window; no exhaustion and no injury checks; goals go on the scoreboard |
| Nothing about coaching between full time and the shootout | A Coaching Choice each, home first, offering one substitution and nothing else |
| A level round "continues one clash at a time" with no end to a round | Eligibility resets when all six have gone, and every sudden-death pick is free |
| "For now, we need one player of each role on the field" | A property of the standard setup, not a standing rule |
| Nothing about formations, and a fixed two cards per zone | Games kick off 2-2-2; rearranging can move a team into 2-3-1 or 1-3-2, and into 3-2-1 or 1-2-3 on the nine-space board |
| A pass to the ball's own space names one player | The passer picks, when more than one teammate is standing there |
| Nothing about a Low Pass with no legal destination | The ball goes a space forward, loose, speed still +1 |
| A score attempt from wherever the ball is | Only from within shooting range, set-ups included |
| Possession is a team's, and any player on the ball's space may act | The ball is carried by a player, who takes the next turn; the coach only chooses when it came free |
| Nothing about anyone being exempt from running back | The player holding the ball does not run back, however they came to be holding it |
| Two 15-minute periods, each clocked 0 to 15 | One running clock: 00-15 in the first half, 16-30 in the second, and it keeps counting past a period's last minute for as long as last possession runs |

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

**Coaching Choice:** the same four actions at setup, a new-play window and halftime; setup
offering one at all, with unlimited substitutions and outgoing players going back to the bench;
2 substitutions per side per half with no declaring/answering asymmetry, and halftime's own 2 on
top; the visitors coaching first at halftime; no requirement to keep one of each role; a formation
change re-dealing by defensive skill; a zone swap moving the meeples too; space positioning
swapping onto an occupied space, and the coach picking who comes back; halftime no longer freeing
the zone; a new play opening a window and a steal opening none; coaching after the new-play reset;
the two pools; a returning player only losing tokens; halftime's window not being a declaration;
nothing ever compelling a declaration, an injured player included.

**The arrangement:** what sets one (any Coaching Choice) and what does not (a run back); a new
play restoring it for both sides, free of exhaustion and with nothing to choose; the
kickoff-space and out-of-bounds placements still costing, after the reset.

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
- **Ceding the ball**, end to end: the third button on the turn out of shooting range, behind
  a confirmation that names what it costs; the ball left where it stands at speed 1 with no
  time cost; a window for each coach, charged as a declaration and answered as one; the
  receiving side sending somebody to pick a ball up that nobody is standing on; and the period
  ending instead under last possession.
- **The Coaching Choice**, end to end, and the same four actions at all four board occasions:
  formation, substitution, zone assignment, space positioning, on one message a coach edits
  their way through. Setup offers one to each coach before kickoff (home first, unlimited
  substitutions, outgoing players back to the bench); a new play offers one to the side taking
  the ball, gated on the once-a-half declaration, with a reply for the other coach if they take
  it and 2 substitutions a side for the half; a ceded ball opens the same window for both
  coaches on the same allowance, asking neither; halftime offers one to each coach
  independently (visitors first) with its own 2. A formation change re-deals the side by defensive skill.
  Dinky substitutes only to get an injured player off, never rearranges, and covers the kickoff
  space itself when it is the side kicking off.
- **Halftime**, end to end: recovery, the coach's extra token, and each side's Coaching Choice,
  gated on the visiting side covering the kickoff space.
- **The run back**, end to end: 1 token per space, the coach picking within the zone under the
  coverage rule, the steal exemption, and stacked teammates separated while a space is free.
  Forced placements are applied silently; only a real choice is put to a coach.
- **Formations**, end to end: every team dealt 2-2-2, and any Coaching Choice -- setup
  included -- able to move a team into 2-3-1 or 1-3-2, re-dealing the six by defensive skill
  and placing every meeple, with the stack space settled per zone.
- **The Low Pass receiver**, where the destination space holds more than one teammate.
- **The unchallenged maneuver.** With no defender in the ball's zone the offense picks a
  maneuver on its own and it resolves as an outright win, with no reveal and no skill test.
- **The injured player's maneuver disadvantage:** a tie against exactly one injured
  participant is their automatic loss, rolling nothing, and a decisive maneuver owed to an
  injured player is downgraded to a skill test they have to win. Specified since the rules
  were first vendored on 2026-07-25 and built on 2026-08-09; the readings it rests on are in
  [Still open](#still-open).
- **The extreme shootout**, end to end: a secret order a side at a time, the reveal, the
  skill test with its injury checks, the "cannot be caught" stop, and sudden death with a
  fresh pick each test. It is the only thing that settles a level game now that league mode
  is gone.

### Specified but not built

Nothing. What is left unbuilt is blocked on something, and is in the next section.

### Blocked or deferred

- **Advanced mode** -- per-team abilities (the sheet's empty `Advanced` column) -- is
  unspecified. Setup refuses it. Formations left it for basic mode on 2026-08-08.
  It also holds up the **back of a printed player card**, which is that player's
  advanced version (the author, 2026-08-12): the printed cards are one-sided until
  the column is filled, and filling it is what unblocks them.

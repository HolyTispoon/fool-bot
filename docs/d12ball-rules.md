# D12 Ball -- rules

**Retrieved:** 2026-08-04 (first copied 2026-07-25)

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

### Changelog

**2026-08-05.** Post-playtest revision, re-pulled from both the `Sheet1` and `maneuvers`
tabs:

- **Low Pass** dropped its fixed 1-space distance entirely. It now reads "Ball moves to a
  teammates 0-2 spaces away" -- the ball can go up to 2 spaces either direction, but only to
  a space a teammate already occupies (distance 0, staying with the same player, counts).
  Landing on an empty or opponent-held space is no longer possible, so a Low Pass itself
  never triggers a loose ball.
- **High Pass** replaced its fixed 2-space distance with a 2-3 space choice: "Ball moves
  forward 2-3 spaces. May set up a scoring opportunity if it moved 2, else reciving player
  must win a skill test to keep posession (as with loose ball)." [sic] Only an exact 2-space
  pass can set up a scoring opportunity, and even then it's a choice, not automatic --
  declining it, or having gone 3, sends it to the same skill-test contest a loose ball uses.
  Unlike the old fixed-2 High Pass, this no longer requires the pass to overshoot the field;
  it still requires a teammate to be standing on the landing space, same as a Winger's Low
  Pass below. See [Setting a scoring opportunity](#setting-a-scoring-opportunity).
- **Fullback's ability** changed from a flat "+1 space on any pass, low or high" to "Can pass
  up to 4 with a high pass. When resolving block deflect, ball goes back 2 spaces." The bonus
  no longer touches Low Pass at all; High Pass's bonus is now the player's choice of a 4th
  space rather than automatic; and Block Deflect gained a second effect it didn't have
  before. See the [role/ability table](#player-cards).
- **Defender's ability** wording changed ("When resolving Pressure, steals the ball." to
  "Steals the ball when resolving Pressure.") with no change in meaning.
- **Winger's ability** ("Can set up a scoring opportunity with a low pass") is unchanged in
  the sheet, but the author clarified directly (see
  [Author clarifications](#author-clarifications)) that it works from wherever the Low Pass
  lands, not just the last space near the goal: a Winger's Low Pass always offers the choice
  to send the receiving player straight into an ordinary score attempt.
- **Steal Intercept's** effect gained a trailing "after turnover" ("Manipulate ball speed up
  to defensive skill after turnover."), confirming in the primary text what was already
  covered under [Author clarifications](#author-clarifications).

**2026-08-04 (later same day).** Re-pulled the `maneuvers` tab again, Time column only.
Net change: **Block Deflect**'s Time went from "2 space minutes" to "1 space minute",
matching its own Effect column's fixed "1 space" instead of overstating it.

An in-between pull briefly saw Low Pass's and Steal Intercept's Time values swap
("distance traveled (1-2 space minutes)" and "1 space minute" trading places) -- the
author was mid-edit on the sheet and fixed it before this was committed, so that state
never landed here. The settled reading, confirmed by the author: **Low Pass**'s Time
staying "distance traveled (1-2 space minutes)" despite its Effect's fixed "1 space" is
correct, not a leftover -- the Fullback ability extends *any* pass, low or high, by 1
space, so the actual distance travelled still varies. Same reasoning as High Pass's
unchanged "distance traveled (2-3 space minutes)" below. **Steal Intercept**'s Time is a
plain fixed "1 space minute", matching its Effect -- Steal Intercept has no equivalent
distance-extending ability.

**2026-08-04.** Commit 527a772 ("updated abilities and maneuvers") reworded both the
`Sheet1` and `maneuvers` tabs:

- The six role abilities. Fullback's is now stated in terms of pass distance rather than the
  own-goal roll, Defender's and Striker's old wording (flagged as mistakes) is gone,
  Midfielder's and Playmaker's swapped which maneuver they name, and Winger's changed only
  its punctuation. See the [role/ability table](#player-cards).
- Three maneuver effects. **Low Pass** and **High Pass** each dropped their distance range
  for a fixed number (Low Pass "1-2 spaces" to "1 space", High Pass "2-3 spaces" to "2
  spaces") -- the Time column's ranges are unchanged, so they no longer describe the same
  thing the Effect column does. **Block Deflect** no longer risks an own goal at all; it now
  reads "sets up scoring opportunity" for the defense instead, the same way a High Pass
  overshoot does for the offense. **Pressure** gained "If reaches offense's goal, triggers
  own goal" -- so the own-goal trigger has moved from Block Deflect to Pressure. See the
  [Actions display](#actions-display) table and [Own goal](#own-goal).

**2026-08-02.** The `maneuvers` tab changed: **Steal Intercept**'s effect now reads "Turnover.
**Defender** and ball move back 1 space. Manipulate ball speed up to defensive skill." -- it
previously said only "Ball moves back 1 space", with the interceptor's own meeple left in
place. This confirms the author's clarification below; the clarification bullet is kept
because the sheet still doesn't spell out that the fallback happens *after* the turnover, in
the new possessing side's direction.

**2026-08-01.** The author pushed most of his PR #10 answers into Notion. Changed upstream:

- The score-attempt example says "space 4", not "zone 4", and the threshold now reads "if
  the attacker rolls a number that is equal or higher than the defense" -- the
  self-contradictory "a higher number that is equal or higher" is gone.
- Both rows of the Score/Miss table were rewritten. The restart after a goal is now
  explicitly board-size dependent, and the "conceding team" wording on a miss is replaced
  by "team that avoided conceding a goal".
- "Determine players" now says the challenger comes from the same **zone**, spells out the
  walk-in and exhaust cost, and adds the no-challenger case.
- "The attacker chooses an offensive maneuver while the defender chooses a **defensive**
  maneuver" -- the long-standing offensive/offensive typo is fixed.
- **Own goal** is expanded from one line into a full rule that defines *disadvantage*.
- A new **Setting a scoring opportunity** section was added.
- "exhaustion token" is drifting to "exhaust token" throughout.

Still stale upstream: the setup section's 12-cards / 6-field-cards / two-spaces-per-zone
model and its back/front paragraph, "Place the ball ... on the space 3 of the home team",
the Cleanup section's "restarts from the middle (back of the midfield)", the "1 (or 2, TBD)"
halftime recovery, and "Clash" for what is now called a skill test. Those are covered under
[Author clarifications](#author-clarifications).

**2026-07-31.** Two action effects changed: **Low Pass** gained "forward **or backward**",
**Block Deflect** gained "Ball speed decreases by 1." The spreadsheet data in this file was
added at this point, having been unreachable when the file was first written.

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
[PR #10](https://github.com/HolyTispoon/fool-bot/pull/10) on 2026-07-31 and 2026-08-01,
plus answers he gave directly while the shoot-to-score work was being scoped, 2026-08-01,
while substitutions were being scoped, 2026-08-04, while reviewing
[PR #29](https://github.com/HolyTispoon/fool-bot/pull/29)'s own-goal/run-back rework,
2026-08-04, while reporting a substitution-flow crash, 2026-08-05, while scoping halftime
resolution, 2026-08-06, and as a rules change handed over directly, 2026-08-07.
**These are rules, and where they conflict with the transcription below, these win** -- the
transcription is a faithful copy of a page that is behind in places. They are kept in their
own section so it stays obvious which text came from upstream and which came from the
author directly.

Answers he has since written into Notion are **not** repeated here -- they now live in the
transcription itself. What remains below is what upstream still does not say.

### Terminology and notation

- **"Clash roll" is renamed "skill test".** Not yet implemented. Upstream still says clash.
- **Ignore "back" and "front".** They belong to an older variant. The Notion page was
  written when each zone was two cards; that "proved too confusing" and was abandoned. The
  setup section still describes that older model.
- On space notation: "use it the way the bot currently uses it with one clear notation" --
  i.e. the engine's single absolute left-to-right index, with possession tracked separately,
  is the notation to standardise on. `H1`/`H2` was floated but the bot's scheme wins.
- The zone/space confusion elsewhere in the Notion text is "human error", not a distinction.

### Board and setup

- **Board sizes are 6, 7 and 9. 7 is the intended default; 6 is now a variant.** The setup
  section still describes a fixed 12-card, 6-space field.
- On a 3-space zone the standard 2-2-2 setup deliberately leaves one space empty.
- **Kickoff depends on board size:** boards **7 and 9** start from the **middle of the
  board**; board **6** starts from the midfield space **closer to the kicking team's goal**.
- **The same rule governs every restart** -- after a goal and at the start of the second
  half, not just the opening kickoff. The Score row of the Score/Miss table now says this;
  the setup section and the Cleanup section still say "back of the midfield".

### Coin toss

- The coin toss and the winner's choice of home or visiting is a **real rule**, not a bot
  convenience. Upstream still says home is randomly assigned.
- The trade it creates is deliberate: home kicks off, visitors receive at halftime, so
  picking visitor buys the second-half restart.

### Score attempts

- **Exactly two dice are rolled.** Each *human* rolls one d12. The attacking side adds only
  the shooting player's offensive skill (plus the ball-speed modifier); the defending side
  adds the defensive skills of **all** its meeples standing between the ball and the goal.
  The Notion wording still implies one roll per defender; it does not work that way.
- **A plain score attempt costs no exhaustion at all** -- not the shooter, not the defenders
  in the way. Only a shot taken off a set-up gains a token, and only the shooter gains it,
  after the roll. The rules grant a token to players "involved in a challenge" and the score
  attempt section calls itself a challenge, but that wording does not reach this roll.

### Maneuvers

- The ball-speed modifier applies to **Steal Intercept only**.
- **Steal Intercept's fallback happens after the turnover, and moves both the
  interceptor and the ball.** The `maneuvers` tab now says "Defender and ball move back
  1 space" (previously just "Ball moves back 1 space"), confirming the interceptor's own
  meeple moves too -- see [Changelog](#changelog), 2026-08-02. The sheet still doesn't
  say so explicitly, but the fallback is relative to the *new* possessing side's
  direction, applied after the turnover: possession flips first, then the intercepting
  player's meeple and the ball each fall back 1 space toward the new possessing team's
  *own* goal (not the old possessing team's goal). Read literally against the old side's
  direction, "back" would send the ball toward the new team's attacking goal instead --
  the opposite of what's intended.
- **Low Pass (post-2026-08-05 revision) has no fixed distance or direction anymore.** "Ball
  moves to a teammates 0-2 spaces away" means: pick any space 0, 1, or 2 spaces from the
  ball, in either direction, that a teammate already occupies -- there is no other
  destination a Low Pass can land on. Ball speed increases by 1 regardless of which distance
  is picked. It no longer risks an own goal on reaching the passing team's own goal
  -- see [Own goal trigger](#own-goal-trigger) below; that trigger moved to Pressure only.
  Because the destination must already have a teammate on it, a Low Pass itself can never
  produce a loose ball or an overshoot.
- **A Low Pass must reach a different player -- nobody passes to themselves to keep the
  ball** (2026-08-07, superseding the reading recorded here before, which took distance 0 to
  mean the ball stays with the same player). Distance 0 is still legal, but only as a pass to
  a *second* player of the same side standing on the ball's own space, which is uncommon but
  allowed (it is what [running back](#running-back)'s one-per-space rule exists to unpick).
  A ball handler with no teammate within two spaces has therefore won a Low Pass with nowhere
  to play it.

  > **Open:** what a Low Pass with no legal destination should do is not settled -- see
  > [rules-open-questions.md](rules-open-questions.md). The bot currently holds the ball
  > where it is, leaves its speed alone, and lets the clock take its usual space minute.
- **High Pass (post-2026-08-05 revision) is a 2-3 space choice (2-4 for a Fullback), and only
  an exact 2 can ever offer a scoring opportunity -- unlike the old fixed-2 High Pass, this no
  longer requires the pass to overshoot the field.** It still requires a teammate to be
  standing on the landing space, exactly like a Winger's Low Pass below: a 2-space pass that
  lands on an empty or opponent-held space skips the choice and goes straight to the mandatory
  skill test. Declining the choice, or having gone 3 (or 4), always sends the ball to the same
  skill-test contest a loose ball uses to decide who keeps it -- see
  [Setting a scoring opportunity](#setting-a-scoring-opportunity) and
  [Actions display](#actions-display). This applies **even when a teammate is already standing
  on the space the pass landed on** -- unlike every other maneuver, a High Pass's landing
  space having a teammate on it does not exempt it from the contest; it only ever avoids the
  contest by taking (and winning) the scoring-opportunity shot instead. Distances of 3 or 4
  never offer the scoring-opportunity choice, whether or not they happen to overshoot.
- **A Winger's Low Pass ability needs no overshoot or last-space requirement either, the same
  as High Pass's own set-up above -- but it needs even less.** Confirmed by the author:
  whenever a Winger completes a Low Pass (any distance, including 0), the offense may choose
  to send the receiving player straight into an ordinary score attempt from wherever the ball
  landed -- treated as a set-up (exhaust token taken after the roll, no restriction on the
  shooter's position). Declining resolves the Low Pass normally. Unlike High Pass's set-up,
  this doesn't even need a teammate to be standing anywhere in particular -- the receiving
  player already is the one taking the shot, by construction of how a Low Pass picks its
  destination. A Block Deflect's set-up is the one that still requires the ball to overshoot
  onto the space nearest the goal (see the next bullet).
- **A Fullback's Block Deflect bonus (ball goes back 2 spaces instead of 1) changes the
  overshoot threshold too.** A Fullback's deflect only sets up a defensive scoring
  opportunity when the full 2-space deflect is what overshoots the field, the same
  "clamped short of the requested distance" test every other maneuver's overshoot uses --
  it is not tied to the un-boosted 1-space case.
- **Defender role ability, "Steals the ball when wins a maneuver with Pressure":** Pressure's
  normal effect still happens -- player and ball go back one space, the defender moves one
  forward -- **and** possession flips in addition. **Unless that same roll concedes an own
  goal**, in which case the own goal takes priority and the steal doesn't also happen -- see
  [Own goal trigger](#own-goal-trigger) below.
- **A High Pass's skill test is not a loose ball.** The two run the same contest and mean
  opposite things. A High Pass has been caught: the receiver is standing on the ball's space
  holding it, and must win a skill test against a defender on that same space -- or, where
  the defence has nobody there, against whoever that coach sends in from the zone, at the
  usual distance-traveled exhaustion. Winning keeps possession and changes nothing else;
  only losing is a turnover. A loose ball is the ball lying where the possessing side has
  nobody, with possession genuinely up for grabs. A pass that lands in a space with no
  player from the team that had possession -- High Pass, Block Deflect, or anything else --
  is a loose ball and follows the rules below instead.
- **Loose ball is a general check after every maneuver resolves, not just a pass landing
  on an empty space.** Once a maneuver settles, check whether the ball's space has a
  player from the team that has possession. If it doesn't, that triggers a loose ball,
  resolved one of four ways:
  - **Only an opposing player is on that exact space:** they win the ball outright -- an
    immediate, uncontested turnover. No skill test and no movement, since that player
    was already standing there.
  - **The space is empty, but both teams have a player in the same zone:** each coach
    picks one of their players in that zone to contest it. Both move to the ball's
    space and gain exhaustion tokens **equal to the number of spaces traveled**, then
    run a skill test: the team that last held possession uses offensive skill, the
    other team uses defensive skill. Both players remain in the space regardless of who
    wins; the winner of the test gains possession.

    > Superseded -- upstream's own text (not yet re-pulled) says this player "gains 1
    > exhaustion", a flat token rather than one per space traveled. Confirmed by the
    > author: it's distance-traveled, the same rate the one-team recovery below and a
    > maneuver's walked-in challenger both use.
  - **The space is empty and only one team has a player in that zone:** that team gains
    possession without a skill test. The coach picks which of their players in that
    zone makes the recovery; that player moves to the ball's space and gains
    exhaustion tokens equal to the number of spaces traveled. If that's the team that
    didn't have possession, it's a turnover: players run back, and ball speed resets to
    1.
  - **"Out of bounds": neither team has a player in that zone, or neither coach sends
    one.** The team that last had possession loses it -- a turnover, ball speed resets to
    1. All displaced players run back, and the team that just gained possession must get
    one of their fielded players (from anywhere on the field, not just that zone) onto
    the ball's space -- the coach picks who, and the bot charges the same
    distance-traveled exhaustion as the one-team case above.
- **The team that last had possession answers first, and alone.** Where both coaches have
  someone to send, they are asked one at a time rather than together, starting with the
  side losing the ball: the ball is theirs to lose, and asking both at once means whoever
  answers second is answering the first's pick rather than the position.
- **Sending nobody is always allowed.** A coach with a player in the zone may leave them
  where they are -- that is what "may choose one of their players" means, and it is a move,
  not a way out of the prompt. Declining costs nothing and moves nobody. If the side that
  last had possession declines and the other side sends someone, that side takes the ball
  (a turnover). If both decline, or one declines and the other had nobody to send, the ball
  is out of bounds and resolves as above. This applies to a High Pass's contest too: a
  defence with nobody on the landing space may decline to send anyone from the zone, and
  the receiver then keeps the ball with no skill test.

  Because declining is always on the table, a side with exactly one candidate is still
  asked rather than having that player sent automatically -- with one player there are
  still two outcomes to choose between.

### Own goal trigger

- **The trigger moved from Block Deflect to Pressure**, matching the `maneuvers` tab's
  2026-08-04 reword -- see [Changelog](#changelog) and the transcription's
  [Own goal](#own-goal) section. Block Deflect's own overshoot now sets up a scoring
  opportunity for the defense instead, and a backward Low Pass no longer risks one either.
- **The roll is now an advantage, not a disadvantage:** roll 2d12 and take the **higher**
  result, then add the offensive skill as before, needing 7+ to avoid conceding. Upstream's
  own-goal paragraph still describes the old disadvantage roll (lower of the two).
- **An own goal takes priority over the Defender's Pressure-steal ability.** When a won
  Pressure would trigger both -- the ball reaching the defense's own goal, and the Defender
  stealing it -- the own goal resolves and ends the point; the steal doesn't also happen.
- **The player rolling to avoid the own goal gains 1 exhaust token** (2026-08-07). The
  attempt costs the token whether or not it succeeds -- it is charged for making the roll,
  not for the result -- and it is charged on top of whatever the maneuver that triggered
  the risk already cost. Upstream's [Own goal](#own-goal) section says nothing about a
  cost; like every other exhaustion gain, it can push the player over their defensive skill
  and make them Exhausted (see [Exhaustion](#exhaustion) above), but it is not a skill test
  and so owes no injury check.

### Ball speed on a turnover

- **Every turnover resets the ball's speed to 1.** Neither [Turnover](#turnover) nor the
  transcription's own "Ball's speed" section says this -- upstream only describes speed
  changing during Low Pass, Dribble Advance, Block Deflect, and Steal Intercept, never what
  happens to it when possession changes hands. This applies to every turnover, not just
  Steal Intercept's: a score attempt (scored or missed), a lost loose ball, and Pressure's
  Defender-ability steal all reset it too, along with the second-half kickoff.
- **Steal Intercept's manipulate-speed choice is relative to that reset, not to the speed
  before the steal.** The turnover happens, speed drops to 1, and only then does the
  defender manipulate it up or down by their defensive skill -- so the result always lands
  within defensive skill of 1.

### Exhaustion

- Halftime recovery is **1** token. Upstream still says "1 (or 2, TBD)".
- **The injury check belongs to skill tests only.** Taking part in a score attempt never
  triggers one, however exhausted the players involved are.
- **Exhausted is judged when a skill test resolves, against every token the player holds by
  then** -- including the ones the test itself charged: the token each participant pays to
  enter it, and one more each for every tie that sent it back to be rolled again. A player
  the test pushed over their own defensive skill is exhausted for that same test, and rolls
  its injury check. There is no snapshot of who was exhausted going in.
- **An injured player removes all exhaustion tokens immediately and is no longer
  exhausted.** Injured players cannot gain more exhaustion tokens and do not make further
  injury checks.
- **At halftime, "the coach can change... the players' assignment as they please" means free
  placement to any space on the board, not just a player's own currently-assigned zone.**
  Confirmed by the author: unlike an ordinary run back or a substitution's rearrangement
  (both still zone-locked), halftime's repositioning step can move any fielded meeple to any
  open space, in any zone, at no exhaustion cost. The one constraint carried over from
  kickoff itself: the visiting side must finish with a player standing on the second-half
  kickoff space, since they're the ones who kick off.

### Running back

- **A turnover is the only thing that runs anyone back.** Cleanup's "every time there's a
  turnover for any reason (steal, goal etc.)" is the whole of it: a resolution that leaves
  possession where it was runs nobody back and charges nobody, however far out of position
  the maneuver left them. A receiver who wins their High Pass skill test, and a loose ball
  the possessing side recovers, both keep the ball and so both skip it. Whoever is displaced
  stays displaced until a turnover does come.
- Run-back exhaustion is **one token per space traveled** -- the same rate a challenger pays
  walking in to a maneuver.
- The coach **chooses** which space in the assigned zone each player runs back to, so long as
  there is at most one player per space once the run back is done. Where a zone has more
  spaces than players assigned to it that is a real choice; where the counts match it is
  forced.
- That one-per-space limit is **per team.** Opposing meeples still share a space, the way they
  do at setup, so it only ever constrains a team against its own players.
- **A steal exempts the stealing player from running back.** On a turnover created by a steal
  (Steal Intercept, or the Defender's Pressure-ability steal), everyone else displaced by the
  turnover still runs back as normal; only the player who won the steal stays where they
  ended up.
- **Running back also spreads out same-zone teammates who ended up sharing a space, not
  just players outside their zone.** Confirmed by the author: if two of a team's own
  zone-native players are doubled up on one space (from ordinary maneuver movement, e.g.
  Pressure or Dribble Advance landing one player on a teammate) while another space in that
  zone is open, one of them has to move to it -- the same "at most one player per space"
  goal the bullet above already applies to players outside their zone. If the zone's spaces
  are all already spoken for, the double-up stands; nobody is moved somewhere that doesn't
  help. A player exempted from running back by a steal is preferred as the one who stays
  put in this case too.
- **No role or player is ever tied to a space or zone, except by the run back itself.**
  Outside of initial setup, nothing constrains where a player's card can sit -- any role can
  be assigned anywhere by a substitution's rearrangement (see Substitutions below). The only
  standing constraint is the run back's own: once players have run back, each meeple must be
  in the zone its player card is currently assigned to.
- **A goal's conceding team must move a meeple onto the kickoff space to start the restart.**
  Nothing already guarantees one of their midfield-zone players ends up standing on the exact
  kickoff space (board sizes 7/9's true middle, or 6's midfield space nearer their own goal)
  -- open play can easily leave both midfield cards elsewhere in the zone. Whoever is nearest
  drops back onto it at the usual one-token-per-space run-back cost, the same as any other
  run-back placement, once every other displaced player is settled.
- **A turnover that happens while last possession is already in force ends the period
  immediately** -- no run back, and no resolution of whatever maneuver caused the turnover
  (e.g. Steal Intercept's own fallback, or its post-run-back ball-speed choice). Play
  proceeds straight to halftime (or full time) resolution. This only applies once last
  possession has already been declared by an earlier play -- see the next bullet for the
  play that declares it.
- **The maneuver that takes the clock to 15 never ends the period, even when it is itself
  a turnover** (2026-08-07, superseding what this section said before). Last possession is
  the possession that *starts* at 15, so whichever side comes out of that maneuver holding
  the ball gets to play it out, and the period ends when *they* lose it. A steal, a goal or
  a missed shot that brings the clock up to 15 therefore resolves in full -- run back
  included -- and hands last possession to the side it gave the ball to.

### Substitutions

- **One player of each role is a property of the standard setup, not a standing rule.** It is
  what basic mode's automatic setup deals out; advanced mode will allow teams to set up other
  ways. Nothing requires a team to keep one of each role on the field afterwards, so a
  substitution may leave a role unfielded -- which it has to be able to do, given every bench
  is a playmaker, a winger and a defender and so could never replace a striker, fullback or
  midfielder in kind.
- **A declaring team's cards may change zones freely, and rearranging costs no exhaustion.**
  It is the one way a meeple moves in this game without paying a token per space.
- **Basic mode allows the 2-2-2 formation only.** A rearrangement may therefore move cards
  between zones but must leave two in each. 4-1-1 and 2-1-3 were floated and are advanced
  mode's, once it exists -- neither fits the boards in the ruleset, where the largest zone is
  three spaces and a team may put at most one player on a space.
- **Every turnover opens a substitution window**, not only a steal or a score attempt. The
  parenthetical upstream is illustrative, not a list.
- **Halftime's substitutions are not a declaration** (2026-08-07). Neither side is asked
  whether to declare -- halftime just gives each of them their changes to make, in line with
  "the coach can change their team's formation and the players' assignment as they please"
  ([End of Time](#end-of-time)) -- and using that window does **not** spend the side's
  once-a-half declaration, so both teams still hold theirs for the second half's open play.
  The allowance within the window is a declaring team's: up to two swaps and a rearrangement,
  each side independently, with no answering substitution for the other team.
- **The window opens before the run back.** The declaring team substitutes and rearranges
  first; the run back then places whoever ended up on the field.
- **The bench and the back bench are two separate pools**, which is what upstream's "if and
  only if all the players on the bench were subbed out" is reaching for:
  - Anyone subbed out goes to the **back bench**, injured or not. The bench only ever drains.
  - While anyone is on the bench, a team may sub in **only** from the bench.
  - The back bench may be drawn from **only** when the bench is empty **and** the team is
    subbing for an injured player.
  - **Injured players go to the back bench and can never be subbed in**, whatever the bench
    looks like.

  So "players who are subbed out cannot be subbed back in" needs no separate bookkeeping --
  it follows from which pool a team is allowed to draw from.
- **A player returning from the back bench just loses the tokens:** half their exhaustion,
  rounded up. Exhausted is then whatever the remaining count says it is, so a player with
  enough tokens returns still exhausted. Upstream's "so if they were subbed while exhausted
  they are no longer exhausted" does not hold in general -- 10 tokens on a defensive skill of
  1 leaves 5.
- **After swapping two players' zone assignments, the declaring team is free to place meeples
  anywhere within their (now current) assigned zones**, not pinned to the exact space the
  other swapped player vacated. "Swap two positions" now only reassigns which zone each
  card belongs to; the meeples themselves stay put until placed, via a follow-up screen that
  offers every field player (not just the two just swapped), any number of times, before the
  coach is done. Costs no exhaustion, same as the swap itself.
  - A 6-board's zones (and board 7's goal zones) are exactly full under the standard 2-2-2 --
    after a swap, neither new zone has an open space to step into until the other player
    vacates it, and neither can vacate first. The follow-up screen falls back to trading two
    meeples' positions directly in that case, which needs no intermediate open space.

### Ties and league vs tournament mode

- **A tie at full time is only sent to the extreme shootout in tournament mode** (2026-08-07,
  new). Every game is now set up as one of two:
  - **League mode:** the game is allowed to end in a tie, and a level score at full time is
    the final result.
  - **Tournament mode:** a level score at full time goes to the
    [extreme shootout](#extreme-shootout-tie-breaking-bonanza).

  Upstream's [End of Time](#end-of-time) section knows only the tournament reading ("if the
  game is tied -- it goes into extreme shootout!"), which is now the tournament-mode case
  rather than the only one. The choice is made in setup alongside game mode and board size.
  Tournament mode is offered but refused for now, the same way advanced mode is, until the
  extreme shootout is implemented.

### Coins

The `Coins` exchange matrix is **not relevant to D12 Ball for now**. "Dinky" is the currency
unit and the Dinky AI is named after it; more and different AI opponents are planned.

The planned `/flip` command should offer **all six coins**, and the denomination is purely
cosmetic in that context.

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
2026-08-05:

| Role | Off | Def | Ability |
|---|---|---|---|
| Fullback | 1 | 6 | Can pass up to 4 with a high pass. When resolving block deflect, ball goes back 2 spaces. |
| Defender | 2 | 5 | Steals the ball when resolving Pressure. |
| Midfielder | 3 | 4 | Gain +3 for skill tests when attempting low pass or pressure. |
| Playmaker | 4 | 3 | May advance 2 spaces when resolving Dribble advance. |
| Winger | 5 | 2 | Can set up a scoring opportunity with a low pass. |
| Striker | 6 | 1 | Gain +3 for scoring attempts off a set up. |

> **`d12ball/data/players.json` and `cogs/d12ball.py` both match this table**, as of the
> post-playtest revision in this commit (see the [Changelog](#changelog), 2026-08-05).
> Fullback's ability changed shape rather than just its wording -- see
> [Author clarifications](#author-clarifications) for how the High Pass choice and the
> Block Deflect bonus are implemented. Winger's ability *text* didn't change, but its
> implementation did; see the same section.

The `+3` abilities are modifiers on the skill test (the roll formerly called a clash). All
six ability slots have code behind them; see the callout above for which ones match the
current wording.

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
example, if the home team playmaker 4/3 attempting to score from space 4 of the home team,
they have to roll a challenge vs. visitors players in visitor spaces 1-3, in the picture
above: 2/5, 5/2, 1/6. To roll a challenge, each player rolls a d12. The attacking player
adds their offensive skill modifier (+4 in this case) as well as the Ball's Speed modifier
(see below, Ball's speed), while all defending players add their defensive skill (5+2+6 in
this case). If the attacker rolls a number that is equal or higher than the defense, they
score! Otherwise it's a missed attempt.

> **Still ambiguous upstream:** "each player rolls a d12" reads as one roll per defender.
> Only **two** dice are rolled in total, one per human. The defender rolls once and adds
> the defensive skills of every meeple between the ball and the goal. See
> [Author clarifications](#author-clarifications).

Time advance: a scoring attempt advances the time by 1 space minute for each space the ball
has traveled through (including the one from which it originates). In the example above the
scoring attempt will advance time by 3 space minutes.

| | Time | Cleanup |
|---|---|---|
| Score | Spaces the ball traveled | Score tracker up 1; turnover; conceding team gains ball in the middle of the midfield or back side of it (in case of board size 6) |
| Miss | Spaces the ball traveled | Turnover; team that avoided conceding a goal starts from space closest to their goal |

### Maneuver

When the attacking player doesn't wish to attempt a score (which should be most of the
time), they maneuver which goes through the following steps.

**Determine players.** The player with possession picks a player to attempt a maneuver,
which has to be a player in the same space the ball (there would often be only one option).
Then, the player must pick a player in the same zone to challenge the attacker. If they pick
a player that isn't in the same space as the attacker that is handling the ball, that player
then moves to the appropriate space and gains an exhaust token for every space they had to
move. They move that token to the space with the ball and the player that had to meet the
challenge gains an Exhaust token for each space they had to travel. in the rare case that
there is no player in the zone, there is no challenger and the offense's maneuver
automatically succeeds.

> The third sentence repeats the second -- an editing leftover from the rewrite, not two
> separate costs. A challenger walked in from elsewhere in the zone pays one exhaust token
> per space, once.

> **Confirmed by the author: picking a challenger is only a real choice when nobody's
> already there.** If a defender is already standing in the ball's exact space (not just
> the zone), they're the challenger automatically -- no prompt, no walk-in, no exhaust
> token. The "pick a player in the same zone" choice only comes up when that isn't the
> case, same as today for the rare no-challenger-in-the-zone case above. The one-player-
> per-space limit (see [Running back](#running-back)) means at most one defender can ever
> be standing there, so this is never itself a choice between two.

**Select a maneuver.** Both players now use their dice to secretly select an action for
their fielded player to attempt, using their six sided action-selection die. The attacker
chooses an offensive maneuver while the defender chooses a defensive maneuver. After both
players have picked their action, they simultaneously reveal their choice and play proceeds
to resolution.

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

> **Missing:** this doesn't say what happens to the ball's speed -- see
> [Author clarifications](#author-clarifications). Every turnover resets it to 1.

### Actions display

3 offense actions, 3 defense actions. Rank and die values are from the spreadsheet's
`maneuvers` tab; each maneuver occupies two faces of the six-sided action-selection die.
Two actions of the same rank tie, which is what sends a maneuver to a clash roll.

| Action | Side | Rank | Die | Defeats | Effect | Time |
|---|---|---|---|---|---|---|
| Low Pass | offense | 1 | 1-2 | Pressure | Ball moves to a teammates 0-2 spaces away. Ball speed increases 1. | distance traveled (1-2 space minutes) |
| Dribble Advance | offense | 2 | 3-4 | Block Deflect | Player and ball move forward 1 space. Manipulate ball speed up to player's offensive skill. | 1 space minute |
| High Pass | offense | 3 | 5-6 | Steal Intercept | Ball moves forward 2-3 spaces. May set up a scoring opportunity if it moved 2, else reciving player must win a skill test to keep posession (as with loose ball). | distance traveled (2-4 space minutes) |
| Block Deflect | defense | 1 | 1-2 | High Pass | Ball moves back 1 space. If reaches offense's goal, sets up scoring opportunity. Ball speed decreases by 1. | 1 space minute |
| Steal Intercept | defense | 2 | 3-4 | Low Pass | Turnover. Defender and ball move back 1 space. Manipulate ball speed up to defensive skill after turnover. | 1 space minute |
| Pressure | defense | 3 | 5-6 | Dribble Advance | Player and ball go back 1 space. Defender moves 1 forward. If reaches offense's goal, triggers own goal. | 1 space minute |

> **Typos preserved as written:** "reciving", "posession" (High Pass's effect) -- see
> [About this transcription](#about-this-transcription).

> **Low Pass and High Pass's Effect text names a number range, not a single distance** --
> both are now a player choice (see [Author clarifications](#author-clarifications)), so the
> Time column's own range tracks that choice rather than a Fullback bonus varying a fixed
> number, the reasoning the pre-2026-08-05 version of this callout gave. **Low Pass's Time
> stayed "distance traveled (1-2 space minutes)" and does not cover its new 0 case** -- a
> distance-0 Low Pass (to a teammate sharing the ball's space; the pass may not be played to
> the passer, see [Author clarifications](#author-clarifications)) still costs the usual
> minimum 1 space minute, per [Cleanup](#cleanup)'s "time always advances at least 1 space
> minute", so the Time column is one entry short rather than wrong. **High Pass's Time column covers its
> Fullback maximum** ("2-4 space minutes" for a 2-4 space choice), unlike Low Pass's, which
> was never revised to mention a Fullback bonus (the ability no longer grants Low Pass one at
> all -- see the [role/ability table](#player-cards)).

> **Steal Intercept still ambiguous** -- see [Author clarifications](#author-clarifications).
> "Defender and ball move back 1 space" doesn't say *when* relative to the turnover, or in
> which direction. Both moves happen after possession flips, relative to the new
> possessing team's direction -- i.e. back toward that team's own goal, not the old
> possessing team's. Nor does "Manipulate ball speed up to defensive skill" say relative to
> what base -- the turnover has already reset speed to 1 by that point, so the manipulation
> is relative to 1, not to whatever the speed was before the steal.

### Own goal

When a team is in risk of scoring an own goal (because a low or high pass was deflected)
they need to roll to see if they can avoid an own goal. The player involved in the maneuver
adds their offense skill to a d12 roll that is rolled at a disadvantage, meaning that you
roll two dice and take the lower result. After you pick the lower result, and add the
offensive skill of the player, you need a result of 7 and above to avoid an own goal.

> **Superseded** -- see [Own goal trigger](#own-goal-trigger) under
> [Author clarifications](#author-clarifications). Upstream hasn't caught up on any of this:
> the trigger above is no longer "a low or high pass was deflected" (the `maneuvers` tab now
> ties it to a won **Pressure** instead, and Block Deflect's own overshoot sets up a scoring
> opportunity for the defense rather than risking an own goal), and the roll itself is now an
> **advantage** (take the higher of two dice), not the disadvantage described above. This
> section previously also noted a Fullback exemption from the disadvantage roll -- that
> described the role's *old* ability, replaced by the pass-distance bonus in the
> [role/ability table](#player-cards), so Fullbacks roll this like everyone else now.

> Clarified by the author beyond this text: there is no "goal space" -- the field only has
> spaces. The risk is triggered by **overshoot**, the same requirement
> [Setting a scoring opportunity](#setting-a-scoring-opportunity) uses: a deflection that
> would push the ball past the space closest to the team's own goal, not merely landing on
> that space.

### Setting a scoring opportunity

When a player succeeds in a high pass and the ball has enough movement to reach beyond the
last space of the field, and there is at least one player from the offensive team in the
last space closest to the opponent's goal, that sets up a scoring opportunity. The human
player may choose one of the players in the zone near the goal to gain an exhaust token and
do a 'score to shoot' roll to see if they can score a goal.

> Clarified by the author beyond this text, for the **original fixed-2 High Pass**: the
> overshoot was **required** (landing exactly on the last space did not set one up), so the
> shooter had to be **in the last space** -- "in the zone near the goal" above should read
> "in the space near the goal". Both of those are specific to that overshoot mechanic; see
> the 2026-08-05 revision below for how High Pass's set-up works now. Regardless of any of
> that, the 'score to shoot' roll is an **ordinary score attempt**, the exhaust token is
> taken **after** the roll, and a striker's `+3` applies to any scoring attempt off a set-up.

> **Not yet in this section, per the [Changelog](#changelog), 2026-08-04:** a Block Deflect
> overshoot sets up a scoring opportunity too -- for the defense, since Block Deflect is the
> defense's own maneuver. Upstream describes only the High Pass case above. Block Deflect
> still keeps the overshoot-and-last-space mechanic High Pass had before the 2026-08-05
> revision below.

> **Post-2026-08-05 revision, per the [Changelog](#changelog):** neither a High Pass's nor a
> Winger's Low Pass's set-up is automatic anymore -- both are now offered as a choice the
> offense can decline. A **High Pass** only ever offers the choice on an exact 2-space pass,
> and it drops the overshoot-onto-the-last-space mechanic described above entirely: whoever
> from the offense is standing on the landing space (wherever the 2 spaces reach) is the
> shooter. A 2-space pass landing on an empty or opponent-held space has nobody to offer the
> choice to, so it skips straight to the mandatory skill-test contest everything else in this
> paragraph eventually reaches too -- declining the offered choice, or having gone 3 (or 4,
> for a Fullback), sends the ball to that same contest (see
> [Actions display](#actions-display)), whether or not a teammate is standing where it
> landed. A **Winger's Low Pass** goes further still: the author confirmed (see
> [Author clarifications](#author-clarifications)) it needs no landing-space requirement at
> all -- the receiving player already is wherever the Low Pass sends them, by construction of
> how its destination is picked, so the choice is always on offer; declining just resolves
> the Low Pass as normal.

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

Every time players are involved in a challenge, they gain an exhaust token. Every time
players have to run back to their position, they gain exhaustion tokens (see Cleanup below).
As soon as a player has a number of exhaust tokens that is higher than their defensive
skill, they are considered Exhausted. When a player is exhausted, they risk getting injured
during challenges. During halftime, each player loses 1 (or 2, TBD) exhaust tokens. In
addition, human players can choose one of their player to lose an extra exhaustion token.

**Exhausted:** When a player is exhausted, after they participate in a challenge they must
roll an injury check. To roll an exhaustion check, roll a d12. If you roll a number that is
higher than the number of exhaustion tokens you are safe! Otherwise, your player is now
injured.

> **Halftime recovery is 1** -- the "(or 2, TBD)" is settled. The check is named twice here
> ("injury check", then "exhaustion check") mid-rename; they are the same roll.

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

> **The count above is open play's only** -- the changes each side makes at halftime itself
> (see [End of Time](#end-of-time)) are not a declaration and don't spend the once-a-halftime
> one described here. See
> [Substitutions](#substitutions) under [Author clarifications](#author-clarifications).

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

> **Superseded** -- see [Ties and league vs tournament mode](#ties-and-league-vs-tournament-mode)
> under [Author clarifications](#author-clarifications). This is the **tournament mode**
> rule; a league-mode game is allowed to end in a tie and stops here.

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

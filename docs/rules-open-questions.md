# D12 Ball -- rules questions

**As of:** 2026-07-31, against `main` at `8fad2b3` plus open PR #9
(`claude/import-maneuvers-script`).
**Companion to:** [d12ball-rules.md](d12ball-rules.md).

Questions that cannot be answered from either upstream source and need the author. The
author answered most of the first round reviewing
[PR #10](https://github.com/HolyTispoon/fool-bot/pull/10) on 2026-07-31; those answers are
now rules and live in the
"[Author clarifications](d12ball-rules.md#author-clarifications)" section of the rules file
rather than here.

---

## 1. Answered -- now in the rules file

Kept as a short index so a question is not re-asked. Detail is in
[d12ball-rules.md](d12ball-rules.md#author-clarifications).

| Question | Answer |
|---|---|
| Board sizes 6/7/9 -- intended? | Yes. 7 is the default, 6 is a variant. |
| 3-space zone leaves a space empty under 2-2-2? | Intended. |
| Do "back"/"front" rules change on a 3-space zone? | Ignore back/front -- an abandoned variant. Spaces will be renotated `H1`, `H2`, ... |
| Is the coin toss and side choice a real rule? | Real rule, and the trade it creates is deliberate. |
| Kickoff space | Depends on board size: middle of the board on 7 and 9; on 6, the midfield space nearer the kicking team's goal. |
| Who rolls in a score attempt? | Two dice total, one per human. Defence adds every intervening meeple's defensive skill. |
| Score threshold | Attacker total **>=** defence total scores. |
| What is "disadvantage"? | Roll two d12, take the lower. Fullbacks exempt on own-goal rolls. |
| Must the challenger be on the ball's exact space? | No -- any player in the ball's zone. Current bot behaviour is correct. |
| What if no defender is in the ball's zone? | No challenger; the offence's maneuver automatically succeeds. |
| Ball-speed modifier scope | Steal Intercept only. |
| Backward low pass | Speed still increases; reaching your own goal does trigger an own-goal attempt. |
| What is a "scoring opportunity"? | Defined in full -- see the rules file. |
| Striker's `+3` | Applies to all scoring attempts off a set-up, not just from a high pass. |
| Coins and Dinkys | Exchange matrix not relevant to D12 Ball for now. Dinky is the currency; the Dinky AI is named for it. More AIs planned. |
| Is the Dinky AI meant to become a real opponent? | No -- it stays a dice-roller. Other AI opponents may come later. |
| Is the 72-card "Foolish" deck a D12 Ball component? | No -- another game. |
| Keep or retire `foolbot.py`'s generic commands? | See section 4. |

---

## 2. Still open from the first round

The author did not reach these.

### 2.1 "Conceding team" in the Score/Miss table

Reads as "the team defending that attempt" in both rows -- on a Score they restart at their
space 3, on a Miss they take the ball at their space 1 -- but on a miss nobody concedes
anything. Confirm the reading, or renotate along with the `H1`/`H2` change.

### 2.2 Halftime exhaustion recovery is 1 or 2

Upstream still says "1 (or 2, TBD)". Needed before halftime can be implemented.

### 2.3 "The attacker chooses an offensive action while the defender chooses an offensive action"

The second "offensive" should be "defensive". Almost certainly the same class of human error
as the zone/space slips, and the spreadsheet types each maneuver Offense or Defense, so
nothing is blocked -- but worth fixing at source.

---

## 3. New questions raised by the answers

### 3.1 Does the post-goal restart also move with board size?

The kickoff answer covers the **start of the game**. The same position is reused after a
goal ("conceding team gains ball in their space 3, back of the midfield") and at the start
of the second half. Do those follow the same size-dependent rule -- middle of the board on
7 and 9, nearer space on 6 -- or does only the opening kickoff change?

This matters because it is the difference between one constant and three call sites.

### 3.2 What is the new space notation, exactly?

`H1`, `H2`, ... was mentioned but not spelled out. On a 7- or 9-space board, does each team
still number from its own end (so home `H1` is the visitors' last space), and is there a
visitor-side prefix? The engine currently uses one absolute left-to-right index with
possession stored separately, which sidesteps the question -- but the bot's user-facing
text will need the real notation.

### 3.3 Scoring opportunity: "last space" or "zone"?

The definition uses both. The trigger requires "at least one player from the offensive team
in the **last space** closest to the opponent's goal", but the choice is "one of the players
in the **zone** near the goal". So can a player standing in the goal zone but not on the
last space take the shot, provided someone else is on the last space?

Also:

- Is the "score to shoot" roll the ordinary score attempt (d12 + offensive skill +
  ball-speed modifier vs. the defence total), or its own roll?
- Does the exhaust token land before or after that roll -- i.e. can the exhaustion tip the
  player over the Exhausted threshold in time to matter for this roll?
- "Enough movement to reach beyond the last space of the field" -- is the overshoot required,
  or does landing exactly on the last space also set up an opportunity?

### 3.4 Defender's new ability: "Steals the ball when wins a maneuver with Pressure"

Pressure normally moves player and ball back one space and the defender forward one, with no
turnover. When a Defender wins with Pressure, does the ball's normal Pressure movement still
happen and possession additionally flips, or does the steal replace the movement?

If possession flips, does the ball-speed manipulation that Steal Intercept grants come with
it?

### 3.5 What should `/flip` offer?

All six coins (1 and 3, in bronze/silver/gold), or only the 3-gold the toss uses? Does the
coin's denomination affect anything, or is it purely cosmetic?

---

## 4. Decisions recorded (not questions)

From the author, for `foolbot.py`'s generic commands:

- **Delete** `/place`, `/move`, `/board`.
- **Keep** `/newdeck` and `/draw` -- the 72-card deck belongs to another game he wants to
  develop further. Possibly move to their own file.
- **Keep** `/roll` as a generic dice roller.
- **Add** `/flip` -- pick a coin, get a fortune/doom result.
- Longer term: devices for his other games, including an RPG using a 2d12 system of one doom
  die and one fortune die.

---

## 5. Implementation gaps

Confirmed as "not built yet" rather than built wrong.

- **Skill tests** (the roll formerly called a clash) and the six **role abilities** -- "not
  yet but we're getting there".
- **Exhaustion.** PR #9 grants and displays tokens on ties, but there is still no Exhausted
  threshold (tokens > defensive skill), no exhaustion check roll, no injured state, and
  nothing uses the `back_bench` the spreadsheet reserves for injured players.
- **Substitution policy** -- the swap works; none of the rules around it are enforced.
- **Score attempts** -- "Shoot to score" still answers "not implemented yet". Now unblocked:
  two dice, defence sums intervening meeples, `>=` scores.
- **Not started:** clock advance, turnover, players-run-back, halftime, last possession, the
  extreme shootout. Maneuver effects are still applied by hand.

### Three code items the answers turn into concrete work

**An unchallenged maneuver should succeed, not stall.** When no defender is in the ball's
zone, `eligible_challengers()` returns empty and the cog replies "The defending team has no
player in the ball's zone to challenge" and stops, so the turn cannot proceed. The author's
answer is that this case has no challenger and the offence's maneuver **automatically
succeeds**. Note this is simpler than the Notion rule it replaces -- nobody is walked in from
another zone and no exhaustion is paid.

**Kickoff is wrong on a 6-board.** `MatchState.standard` uses
`space_index=min(1, len(midfield) - 1)` for every board size. On 7 and 9 that is index 1,
which is the middle of the board -- correct. On a 6-board the midfield has two spaces and
index 1 is the one *further* from the kicking team's goal, so the ball starts one space too
far forward. Home attacks from low indices, so the 6-board case wants index 0.

**Stale player data.** `d12ball/data/players.json` predates two ability changes in the
spreadsheet -- the Defender's (a confirmed mistake in the old data) and the Striker's. A
re-import picks both up; the importer already skips the `Backside` rows the sheet has since
gained. The author also mentioned he may restructure where abilities live in the sheet, so
this may be worth doing after that.

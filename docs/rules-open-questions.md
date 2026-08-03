# D12 Ball -- rules questions

**As of:** 2026-08-01, against `main` at `0f61f26`.
**Companion to:** [d12ball-rules.md](d12ball-rules.md).

Questions that cannot be answered from either upstream source and need the author. Two
rounds of answers came from his review of
[PR #10](https://github.com/HolyTispoon/fool-bot/pull/10) on 2026-07-31 and 2026-08-01, and a
third came directly while shoot to score was being scoped.

**Almost everything is now answered.** Most answers went into Notion directly and are in the
transcription; the rest are under
"[Author clarifications](d12ball-rules.md#author-clarifications)". This file is now mostly a
work list.

---

## 1. Still open

### 1.1 Is the exhaustion work in PR #9 the intended scope?

The author's answer to "exhaustion accumulates but does nothing" was "yet, it's in my PR"
(PR #9, `claude/import-maneuvers-script`).

That PR grants an exhaust token to both sides on a tie and renders them with an emoji, but
it does **not** add the Exhausted threshold (tokens > defensive skill), the injury check
roll, an injured state, or any use of the `back_bench` the spreadsheet reserves for injured
players. Worth confirming that accrual is the intended scope of that PR and the Exhausted /
Injured layer is a later piece, rather than it being assumed done.

### 1.2 Where do role abilities live in the spreadsheet?

The author mentioned wanting to "update the spreadsheet so the ability are found somewhere
else matching the roles" -- currently the ability is repeated on every player row and the
importer asserts all players of a role agree. Worth knowing before re-importing, since a
restructure would change the importer.

---

## 2. Answered

A short index so nothing is re-asked. Detail is in the rules file.

### Written into Notion, now in the transcription

| Question | Where it landed |
|---|---|
| Score threshold ("higher number that is equal or higher") | Fixed upstream: "a number that is equal or higher". |
| "Conceding team" in the Miss row | Rewritten upstream: "team that avoided conceding a goal starts from space closest to their goal". |
| "The defender chooses an offensive action" | Fixed upstream: "the defender chooses a defensive maneuver". |
| "zone 4" in the score-attempt example | Fixed upstream to "space 4". |
| Post-goal restart position | Score row now reads "middle of the midfield or back side of it (in case of board size 6)". |
| Must the challenger be on the ball's exact space? | Rewritten upstream: same **zone**, walk-in costs one exhaust token per space. |
| No defender in the zone | Added upstream: no challenger, offence's maneuver automatically succeeds. |
| What is "disadvantage"? | Own-goal rule expanded upstream to define it: roll two dice, take the lower, then add offensive skill, need 7+. |
| What is a "scoring opportunity"? | New "Setting a scoring opportunity" section upstream. |

### Answered on the PR, not yet upstream

| Question | Answer |
|---|---|
| Board sizes 6/7/9, and 3-space zones leaving a space empty | Yes to both; 7 is the default, 6 a variant. |
| Kickoff space | Middle of the board on 7 and 9; nearer midfield space on 6. Governs every restart, not just the opening. |
| Is the coin toss and side choice real? | Real rule; the trade it creates is deliberate. |
| Space notation | Use the bot's existing scheme -- one clear notation. `H1`/`H2` was floated and dropped. |
| Who rolls in a score attempt? | Two dice total, one per human; defence sums intervening meeples. |
| Ball-speed modifier scope | Steal Intercept only. |
| Backward low pass | Speed still increases; can trigger an own-goal attempt. |
| Halftime exhaustion recovery | 1. |
| Scoring opportunity: last space or zone? | Last space. The upstream sentence should read "in the space near the goal". |
| Is "score to shoot" its own roll? | No -- an ordinary score attempt. |
| Exhaust token before or after the roll? | After. |
| Is the overshoot required? | Yes. |
| Striker's `+3` | All scoring attempts off a set-up, not just from a high pass. |
| Defender's Pressure-steal | Pressure's normal movement still happens **and** possession flips in addition. |
| `/flip` scope | All six coins; denomination purely cosmetic. |
| Coins and Dinkys | Exchange matrix not relevant to D12 Ball for now. More AIs planned. |
| Dinky AI ambitions | Stays a dice-roller. |
| The 72-card "Foolish" deck | Belongs to another game. |
| `foolbot.py`'s generic commands | See section 3. |

### Answered while scoping shoot to score

| Question | Answer |
|---|---|
| Does a score attempt cost exhaust tokens, and to whom? | No -- a plain attempt costs nothing. Only a shot off a set-up does, and only the shooter. |
| Does an exhausted participant in a score attempt roll an injury check? | No. Injury checks happen after a skill test only. |
| Run back: which space in the zone, and how many tokens? | One token per space traveled. The coach picks the space, at most one player per space afterwards. |
| Is that one-per-space limit per team? | Yes. Opposing meeples still share a space. |

### Answered while scoping the loose-ball rule

| Question | Answer |
|---|---|
| Loose ball, only one side has a zone-mate | That side gains possession without a skill test; the coach picks who recovers it, distance-traveled exhaustion (not the flat 1 a contested skill test costs). |
| Loose ball, neither side has a zone-mate ("out of bounds") | The side that last had possession loses it -- a turnover, so it's run-back for everyone, and the new possessor must place one of their fielded players (from anywhere, not just that zone) on the ball's space, same distance-traveled exhaustion. |

---

## 3. Decisions recorded

From the author, for `foolbot.py`'s generic commands:

- **Delete** `/place`, `/move`, `/board`.
- **Keep** `/newdeck` and `/draw` -- the 72-card deck belongs to another game he wants to
  develop further. Possibly move to their own file.
- **Keep** `/roll` as a generic dice roller.
- **Add** `/flip` -- pick any of the six coins, get a fortune/doom result. Denomination is
  cosmetic.
- Longer term: devices for his other games, including an RPG using a 2d12 system of one doom
  die and one fortune die.

---

## 4. Work the answers unblock

### Code fixes with a confirmed rule behind them

**Kickoff is wrong on a 6-board.** `MatchState.standard` uses
`space_index=min(1, len(midfield) - 1)` for every board size. On 7 and 9 that is index 1 --
the middle of the board, correct. On a 6-board the midfield has two spaces and index 1 is
the one *further* from the kicking team's goal, so the ball starts one space too far
forward. Home attacks from low indices, so the 6-board case wants index 0.

Since the same rule governs the restart after a goal and at the second half, this wants to
be one shared helper rather than a literal at each call site.

**An unchallenged maneuver should succeed, not stall.** When no defender is in the ball's
zone, `eligible_challengers()` returns empty and the cog replies "The defending team has no
player in the ball's zone to challenge" and stops. The maneuver should automatically
succeed for the offence.

**Stale player data.** `d12ball/data/players.json` predates two ability changes in the
spreadsheet -- the Defender's (a confirmed mistake in the old data) and the Striker's. A
re-import picks both up, and the importer already skips the `Backside` rows the sheet has
since gained. Gated on 1.2 if the sheet is about to be restructured.

### Built

- **Score attempts.** "Shoot to score" now rolls: two dice, defence sums the skills of every
  meeple between ball and goal, attacker total `>=` defence total scores, ball-speed modifier
  on the attacker, and no exhaustion either side. A goal **applies** to the scoreboard -- a
  bare increment with no threshold behind it. The rest of the cleanup is **announced as text,
  not applied**: the clock, the restart and the run back are hand applied, the same way
  maneuver effects are. The run back below and the clock in "Still unspecified enough to
  block" are what stand between this and an automatic cleanup.

### Newly specified, not yet built

- **Own goals.** Trigger (a deflected low or high pass), roll (2d12 take lower, add
  offensive skill, need 7+), and the fullback exemption are all specified.
- **Players run back.** Fully specified now: one exhaust token per space traveled, the coach
  picks each player's space within their assigned zone, at most one player per space
  afterwards, counted per team. Wants a per-turnover placement step, and `move_ball` refuses a
  space with no meeple, so the post-goal and post-miss restarts are gated on this. **Nothing
  enforces any of this yet** -- the score-attempt cleanup only asks the players for it in
  words.
- **Scoring opportunities.** Overshoot required, shooter must be in the last space, ordinary
  score attempt, exhaust token after the roll.
- The six **role abilities** -- the `+3` modifiers apply to the skill test. (The skill test
  itself, the roll formerly called a clash, is built.)

### Still unspecified enough to block

- Clock advance, turnover, halftime, last possession, and the extreme shootout are described
  upstream but not built. Maneuver effects and score-attempt cleanup are applied by hand.
- Substitution policy -- the swap works; none of the rules around it are enforced.

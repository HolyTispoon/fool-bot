# The clock, the goal log and the event log

Design notes for fool-bot; the map is [CLAUDE.md](../../CLAUDE.md), the rules are [living-rules.md](../living-rules.md).

## The running clock

One clock over both periods -- 00-15 in the first half, 16-30 in the second --
and it **does not stop**. See "Clock, halftime, and full time" in the living
rules, and the 2026-08-15 entry in the rules log for the author's reasoning.
`MatchState.advance_time` is the whole of it.

- **"The clock has reached the last minute" and "last possession is live" are
  two facts.** They were one while the clock stopped at 15: reaching it both
  raised the flag and froze the number, so a last possession lasting four turns
  read 15 for all of them. The flag alone ends the period now, on the first
  turnover under it, and every turn of a last possession is charged as usual --
  so a first half genuinely ends at 19. `advance_time` still returns True only
  on the call that *raises* the flag, which is what stops the announcement going
  out twice.
- **A period's last minute is `ScoreboardState.last_minute`**, over
  `period_last_minute`. It is the one number the running clock adds: 15 and 30,
  read off the period rather than written at each site. Nothing may go back to
  comparing against a literal 15.
- **The second half starts at `SECOND_HALF_START_MINUTE` regardless**, set in
  `end_period` at the whistle rather than at the kickoff -- halftime is played
  with the second half's number already on the scoreboard. That is what makes
  **minutes 16 and up occur twice in a game**, once in the first half's last
  possession and once in the second half proper, which is why the goal log
  records a goal's period as well as its minute.
- **The clock has no ceiling, and `ScoreboardState.__post_init__` no longer
  pretends otherwise.** Its range check was the clamp restated; a floor is all
  that is left, or a game saved at 19 would not reload. `MAX_DEBUG_CLOCK` in the
  cog is not a rule either -- it is what two digits hold, since everything that
  prints the clock prints it `{:02d}`.
- **A game already in its second half when this landed keeps the clock it had**,
  so a side sitting on 3 gets a long half. Nothing migrates it: the alternative
  is rewriting a live game's clock on load, and both developers run the bot
  against their own saves.
- **The printed jumbotron is drawn from the same two numbers.** `CLOCK_MINUTES`
  and `HALFTIME_MINUTE` in `d12ball/boards.py` are `period_last_minute` calls,
  so a period settled upstream reaches the print by re-rendering. Eight columns
  is what puts halftime at the end of a row, which is what lets the two halves
  be drawn as bands; the second half's last row is a cell short, and that spare
  slot carries the note about the overrun -- **the minutes past 15 and 30 have
  no cells**, because nothing bounds how many there are.

## The goal log

Every goal of the game, in the order it was scored: who put it in, who it
counted for, and the minute. `MatchState.goals` is the field --
a list of `GoalRecord` -- and `MatchState.record_goal` is the only thing that
writes to it. The scoreboard is a running total and cannot be read backwards,
which is the whole reason this exists.

- **The three ways to score all log, in the call that credits them.**
  `award_goal`, `concede_own_goal` and `award_shootout_goal` each take the
  player now, and each calls `record_goal` itself. Nothing else may call
  `record_goal`: a scoreboard and a log that disagree is exactly the bug a
  separate "and also log it" step produces. A new way to score has to say who
  scored it, the same way it has to decide steal-or-new-play.
- **An own goal is stored as two facts and printed as one line.** `side` is who
  it counted for and `player_id` is the defender who failed the roll, so it is
  listed in the *other* team's column marked **(OG)** -- the one line of a
  scoresheet where the name and the heading disagree, which is what an own goal
  is. The scorer's name deliberately carries no team emoji anywhere in the log,
  or that line would contradict the heading over it.
- **The period is stored beside the minute and is not decoration.** The clock
  [runs past a period's last minute](#the-running-clock) and the second half
  starts at 16, so a first half can reach 17 and so can the second.
  `GoalRecord.in_first_half_overrun` is the ambiguous case and is exactly the
  condition **(FH)** states, so the marker cannot drift from what it means. The
  second half needs no marker of its own: it overruns as readily, but with the
  first half's overrun always marked, an unmarked number can only be read one
  way.
- **The stamp is the clock as the ball crosses the line**, taken before the
  action's own cost is charged -- a shot's clock cost is spent later, in
  `finish_maneuver_resolution`, so recording it after would report the minute
  play restarted.
- **A shootout goal is logged and flagged.** It is a goal and goes on the
  scoreboard like any other, but it has no minute and no run of play, so
  `build_goal_log` lists those apart rather than stamping six goals with
  whatever the clock stopped on. Same reason `shootout_goals` is a tally of its
  own.
- **It is persisted, and a game older than the field keeps loading.**
  `from_dict` defaults it to empty, so a game already under way logs the goals
  it has left and finishes with a part scoresheet -- which `build_goal_log`
  says outright, by counting itself against the scoreboard rather than trusting
  the two agree.
- **The log goes out at the end, the minute goes out at the time.** Each goal's
  own announcement carries `format_goal_time`, and the full listing is added to
  `announce_game_over`'s content by its two callers -- not inside it, which is
  handed a string and holds no match.

## The event log, and the statistics read off it

`MatchState.events` is everything that happened in a match, in the order it
happened, and `d12ball/stats.py` folds it into every number `/d12ball stats`
reports. It exists for the reason [the goal log](#the-goal-log) does, one step
further on: a match holds the **current position**, so who is injured is
readable and what injured them is not, and how many tokens a player is carrying
is readable and what charged them is not. Neither is reconstructable after the
fact.

- **`MatchState.record_event` is the only writer**, exactly as `record_goal` is
  for the goal log, and for the same reason: a second way in is a second thing
  that can disagree about what a match did.
- **The list's order is the whole of its structure.** There is no turn counter
  and no possession counter, deliberately -- an event belongs to the last
  `turn_action` before it (`events_this_turn`), and a possession is a run of
  consecutive `turn_action`s by one side (`stats.possessions`). Both are exact
  reads of the order, where a stored counter is a second thing that can
  disagree with it, and would have to be cleared, bumped and persisted in step
  with a flow that has enough of those already.
- **It is not state.** Nothing in the game asks it a question and a match with
  an empty log plays identically -- which is what lets a game saved before the
  field load and simply report nothing. Don't make a rule read it.
- **Anything that records has to save in the same breath.** An effect that ends
  in a prompt hands the turn to a click that reloads the match out of the save
  file, so an event written and not persisted is one the next interaction never
  sees. That is not hypothetical: `record_maneuver` landed without a `persist`
  of its own and beat 1 of the tutorial vanished from the log, because
  `resolve_dribble_advance` saves the *game record* without rewriting the match
  (correctly -- nothing on the match had changed until the event did).
- **Where each kind is written**, all of them single funnels every path already
  bottoms out in:

  | kind | recorded by | why there |
  | --- | --- | --- |
  | `turn_action` | `D12Ball.record_turn_action`, from the three buttons on `PlayerActionView` and from `play_ai_turn` | after each one's own stale-view guard -- a refused click is not a turn |
  | `maneuver` | `begin_effect_resolution` | every maneuver in the game reaches it exactly once, decisive, unchallenged or through the skill test. Since the front half of Phase 4 of [model-discord-split.md](../model-discord-split.md) it is also where the reveal `resolve_maneuver_step` worded is posted, above the effect -- which changes nothing about the log, and is named here so the funnel is not read as having moved |
  | `skill_test` | `SkillTestView.roll` | before either branch, so a tie that re-rolls is in the record as well as the roll that settles it |
  | `shot` | `ScoreAttemptView.roll` | before `settle_score_attempt`, which awards the goal |
  | `own_goal_roll` | `run_own_goal_roll` | both outcomes: the rate needs the attempts as well as the concessions |
  | `injury_test` | `run_injury_test` | both outcomes, same reason -- `mark_injured` deliberately logs nothing, or a failed test would be in twice |
  | `goal` | `MatchState.record_goal` | beside the `GoalRecord`, which has no way to say *where in the run of play* |

- **Exhaustion is attributed, not logged.** `MatchState.add_exhaustion` adds to
  the open turn's own event rather than writing one apiece: a game makes around
  a hundred of those calls, and what a statistic asks is what a maneuver cost,
  never in what order the tokens were handed out. Every path that charges
  bottoms out there -- `RulesEngine.apply_exhaustion`, the run back's own charge,
  and the AI's -- which is why the attribution is at the model and not at those
  three. A charge between turns (a halftime recovery) belongs to no turn and is
  simply not attributed.
- **How a maneuver was won is read off the log, not off the match.** The
  obvious test -- ask `settled_maneuver_winner` whether the cards decided it --
  is wrong by a hair: the injury tests run between the roll and the effect, so
  a skill test whose loser went down injured would come back reading as a win
  on the cards. A `skill_test` event in the turn means the dice settled it,
  full stop, and the log cannot move under it that way.
- **`abandoned` on `D12BallGame` splits the two ways a game reaches
  `FINISHED`.** Nothing in the flow needs them apart -- neither is coming back
  -- but a scoreboard read off a game nobody finished is a win nobody earned,
  so `abandon()` sets it and `collect_overview` counts such a game without
  counting its result. It defaults False, so a game saved before the field
  counts as played out, which is what almost all of them are.

### What the statistics are, and what they are not

- **An uncontested maneuver is in no rate.** It always wins, so counting it
  would report the defense's decision to send nobody as the offense card's own
  success -- `ManeuverRecord.contested` is `CONTESTED_DECISIONS` and the
  unchallenged plays are reported in a column of their own.
- **A goal belongs to the possession, not the turn.** A pass that works pays
  off on the shot it set up a turn or two later, so `collect_maneuvers` credits
  a possession's goals to every maneuver played in it. That over-credits by
  design: the log cannot say which of three maneuvers mattered most, and
  crediting only the last would report the High Pass as the only card that ever
  scores.
- **`exh` and `inj` on a maneuver's row are the turn's, not the card's.** A
  turn charges both sides, and the log does not say which of the two a token
  belonged to. Splitting it further would be inventing an attribution the data
  does not carry, which is why the table says so under itself.
- **A rate with no denominator is `None`, drawn as a dash.** "0%" for a card
  played once unchallenged would say it always loses, which is the opposite of
  what happened.
- **A game with no events is not a game with no statistics -- it is a game the
  bot was not counting yet**, and every report says how many of those it is
  standing on. Same reason `build_goal_log` counts itself against the
  scoreboard rather than trusting the two agree.
- **Scoped to the guild, always, with no option to widen it.** `self.games` is
  every game on every server the bot is in; one server's players have no
  business reading another's, and a cross-server total is a disclosure nobody
  consented to.
- **A report goes in a thread of its own, not an ephemeral message.**
  `CommandsMixin.open_stats_thread` starts a parent-message-less public thread
  off the game channel and posts the heading and every table there, then points
  the caller at it ephemerally -- so the channel gets nothing but the thread,
  the report survives a restart, and both coaches (not just whoever ran the
  command) can read it. `share:true` posts straight into the channel instead,
  and a command run inside a thread already, or one that cannot open a thread
  for want of the Create Public Threads permission, falls back to followups.
  The thread is also a rate-limit bucket of its own, the same reason
  `rules_full` uses one.
- **The tables are sized to 58 characters** and live in `d12ball/stats.py`
  rather than the cog, for the reason `d12ball/formatting.py` exists -- they
  are words about match data with no Discord in them. A Discord code block
  scrolls rather than wraps, so a row wider than a phone's message column is
  one a coach has to drag sideways to read. Adding a column means taking one
  out. Rows are in the catalog's own rank order rather than by frequency: a
  table whose rows move between two runs cannot be compared with the one a
  coach read last week.

### Where the statistics are tested

Split three ways, because a recorder that fires on the wrong object -- or
before a save that never happens -- is invisible to a unit test:

- `tests/test_d12ball_stats.py` checks the **reading**, over events built by
  hand. That is deliberate: the fold needs fixtures a real game would take
  fifty turns to reach.
- `TutorialPlaythroughTests` checks the **writing**, against
  `tutorial.BEATS` rather than a copy of it -- five real turns through the real
  cog is what caught the missing `persist`.
- `EveryMatchupResolvesTests` checks the writing across **all thirty-six
  pairings**, on three boards and both control paths, which is the coverage a
  log written at seven funnels needs.

### What is deliberately not counted yet

A loose ball's own contest logs no event of its own -- injuries and exhaustion
out of one still reach the log through the turn they happened in, but who
contested and who won does not. It is the one contest in the game that is not
a maneuver, and nothing in the author's questions asked for it. Adding it is a
`record_event` beside `LooseBallSkillTestView.roll` and a column, not a
redesign.

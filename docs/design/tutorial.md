# The tutorial

Design notes for fool-bot; the map is [CLAUDE.md](../../CLAUDE.md), the rules are [living-rules.md](../living-rules.md).

## The tutorial

`/d12ball create_game tutorial:true` is an ordinary solo game against
Dinky whose first five turns are scripted. `d12ball/tutorial.py` holds
the whole script -- the beats and the questions the cog asks of it --
and the cog reads it behind `if game.in_tutorial` in a handful of
places.

**Every lesson is a real turn, and the five of them are one continuous
play.** Each beat is played from wherever the previous beat's turn left
the ball. It did not start that way: the first version re-dealt both
sides before every beat, which made each lesson self-contained and the
story nonsense -- a coach drove Dinky backwards with a Pressure and
then found the ball back in midfield with nothing to explain it.
**Nothing may move a meeple between beats.** If a beat needs a
different position, the fix is to change the script so the play arrives
there.

Two things follow from lessons being real turns:

- **Nothing in `pending_turn_view` changes and `/d12ball resume` needs
  no branch of its own.** A beat leaves the match in states the game
  already knows how to resume. What a restart loses is a lesson's
  *text*, which is already in the channel above the prompt it
  explained.
- **The clock and the score carry over**, so the real game starts
  around minute 7 of the first half with the coach a goal up. That is
  the author's call and it is why nothing resets the scoreboard at the
  handover.

### The opening is the standard deal

The script **places nothing**. Both sides are dealt the standard
**2-2-2**, exactly as every game deals them, and `MatchState.standard`
records that as `assigned_positions` itself -- which is load-bearing,
because the tutorial skips setup coaching and the goal at the end is a
new play that restores the arrangement.

A hand-written opening was tried and dropped. It put the coach in 2-3-1
and Dinky in 1-3-2 to buy a thinner defensive lane for the final shot,
which meant a tutorial teaching the game from two shapes no game ever
kicks off in. **A beat that wants a different position has to play its
way there.** What the deal gives the script for free is exactly what it
needs:

- the coach's **playmaker on M2** with the ball, one space short of
  shooting range, so Shoot is not offered until beat 1's dribble earns
  it -- and beat 2's lesson is written on it appearing;
- **Dinky's playmaker on the same space**, so the opening maneuver has
  an automatic challenger and beat 1 needs no walk-in to explain yet;
- the coach's **striker on V2**, which is where beat 5's 2-space High
  Pass lands and is inside shooting range;
- **Dinky's fullback on V2 with them**, which is what prices the final
  shot -- a defender on the ball adds their whole defensive skill.

`TutorialOpeningTests` asserts each of those against the deal rather
than against a table, since all of them are claims the lesson text
makes and `basic_rules.json` could quietly change any of them.

### Determinism: rails and dice

A chained script only works if every step lands where the next beat
expects.

- **The rails cover every choice that moves the ball or prices the
  shot**: the turn action, the card, the dribble distance, the ball
  speed, the pass distance, the set-up shot, whether a loose ball
  may be waved through, and whether a maneuver challenge may be.
  `TutorialBeat.choices` is the table, and a rail reaches a view **on
  the prompt's options** since step 6 of docs/architecture-migration.md
  -- `railed`, `live`, `decline_railed`, built by `d12ball.prompts`
  through `tutorial.resolve_choice` over `tutorial.beat_for_game` --
  so a view greys a button off the same reading the driver refuses off
  (`_rail`), and asks the tutorial nothing itself.
  `D12Ball.tutorial_railed_option` was the one question the views used
  to ask, and went with the change.
  - **A rail names a value, except when it cannot.** The ball speed a
    steal may set is capped by the stealer's own defensive skill, and
    who does the stealing is not something the script fixes -- so
    `CHOICE_MAX` means "the highest offered" and `resolve_choice` takes
    the option list rather than a single value. That is also why the
    speed targets are collected (`RulesEngine.speed_targets`) before
    the rail is resolved.
  - **A rail matching nothing on offer is no rail**, rather than a
    prompt with every button dead. The script and the flow can only
    disagree by mistake, and a coach with nothing to press is a worse
    failure than a lesson that did not land.
- **Rails build the button disabled, never absent.** A lesson about the
  three cards in your hand cannot be taught by hiding two of them, and
  a coach should see that Shoot and Time out exist and read why neither is
  theirs yet. Each railed view re-checks in its callback: an earlier
  beat's prompt is still in the channel, and the maneuver menus are
  restored message-agnostically after a restart.
- **What is left free is left free on purpose** -- a run-back space,
  and which of two equally-near players the coach sends to challenge in
  beat 3. Both are legal moves with no wrong answer whose outcome no
  later beat reads. `TutorialPlaythroughTests.FREE_CHOICES` is that
  list, and the suite fails on anything else showing two live buttons,
  so a rail going missing shows up as a failure rather than as a story
  that drifts.
  - **Beat 2's loose ball dropped out of that list on 2026-08-24.**
    Dinky's own midfielder is already standing on M3 where the beaten
    Deflect lands, so under the occupancy rule (see
    [Where the ball comes to rest](loose-balls.md#where-the-ball-comes-to-rest)) the
    coach, who has nobody there, is never put on the clock at all --
    `LooseBallChoiceView` no longer appears in this script. That also
    removed the automatic challenger it used to leave standing on the
    ball for beat 3's Pressure, which is why beat 3 now rails a
    maneuver-challenge send instead.
  - **Beat 1's ball speed choice joined it on 2026-08-24.** It used to
    be pinned at no change with no word said about it, which taught
    nothing and read as an arbitrary restriction -- a coach's first
    look at the mechanic was a menu where every button but one was
    grey. `TutorialBeat.speed_note` is what a beat says about the
    choice it is about to leave free, posted with the same timing as
    `maneuver_note` -- right in front of the menu it explains, not
    with the lesson two messages up -- and only beat 1 has one to say,
    since beat 4 rails its own speed choice and explains why inline.
    The choice costs nothing to leave open: the turnover in beat 2
    resets ball speed regardless, so nothing picked here reaches a
    later beat.
- **Some dice are scripted** (`TutorialBeat.rolls`, read through
  `D12Ball.tutorial_dice`). Beat 2 is a tie the coach has to **lose**,
  or the ball never comes free and beats 3 and 4 have nothing to defend
  against. There is no loose-ball roll to rig behind it any more --
  Dinky's own midfielder already stands where the beaten Deflect lands,
  so they simply keep it, uncontested. Injury checks pass for the whole
  opening (`BLANKET_ROLLS`) --
  a card going down injured is a mechanic the script never introduces,
  lands on whichever player the dice pick, and would leave every beat
  after it planning around a board it did not expect. The check still
  runs and the coach still watches it.
- **The score attempt is deliberately not scripted.** It is the one
  roll that decides something the coach wants, and the play is built so
  it is a heavy favourite rather than a certainty: the striker's
  **d12+11** against the fullback's **d12+6**, which is **85.4%**,
  measured at 87% over 200 playthroughs. A tutorial that cannot lose
  its last shot is not teaching the game.
  - **So a test that plays the script may not assert the ball went
    in.** One did, and failed about one run in seven on `main` -- for
    exactly the reason the shot is left open, which is why it read as
    a flake rather than as the test asking for something the design
    refuses to promise. A test that needs the goal pins the dice
    (`random.randint` to 6, the position doing the rest); a test that
    only needs the *statistics* to be right reads the outcome off the
    match and checks the fold agrees with it. See "The playthrough
    test".
  - **Beat 4's speed rail is worth a whole point of that margin**, and
    is the reason the lesson explains it rather than just greying the
    buttons. A turnover resets ball speed, so beat 1's speed choice is
    thrown away and only the one set *after* beat 4's steal survives to
    the shot -- half of it, rounded down, is added to the attempt.

### The five beats

Each is one turn, and the position it starts from is the one the
previous turn produced -- these are outcomes, not settings:

| # | Coach plays | Dinky plays | Result |
| --- | --- | --- | --- |
| 1 | Dribble Advance | Deflect | Decisive win, the Playmaker's own 2 spaces: M2 → V1 |
| 2 | Low Pass | Deflect | Rank 1 both: a tie, a skill test the coach loses, the ball knocked to M3 -- right onto Dinky's own midfielder, who keeps it uncontested |
| 3 | Pressure | Dribble Advance | The coach sends a challenger to M3, then defends and wins: Dinky driven back to V1 |
| 4 | Steal Intercept | Low Pass | Turnover, the ball back to M3, the run back, and the speed crank |
| 5 | High Pass | Steal Intercept | 2 spaces onto the striker on V2 -- a scoring opportunity, a set-up shot, and a goal |

### The coach always plays home

The standard deal gives home the ball, so a coach who wins the toss is
railed onto Home (`HomeAwaySelectionView`) and Dinky takes the visitors
when Dinky wins it (`CoinFlipView.flip_coin`, overriding
`DinkyAI.choose_home_or_visiting` at the call site -- it takes no
arguments, so it cannot know which game is asking).

### The three fields, and the counter

`tutorial`, `tutorial_step` and `tutorial_staged` live on
`D12BallGame`, not on `MatchState`: a tutorial is a property of the
*game* the way `test_game` and `ai_opponent` are, and the rails are
read by views that hold a game id and may not have loaded a match yet.
A save written before them defaults them; nothing migrates.

- **`in_tutorial` is the one question every rail asks**, and it is
  `tutorial and tutorial_step is not None`. Clearing the step is the
  whole of turning the rails off, which is all `/d12ball skip_tutorial`
  does; `tutorial` stays True so the record and the channel name still
  say what the game was created as. The command is open to the coach
  being taught **or a game helper**: it was the coach alone, on the
  reasoning that a tutorial is one human against Dinky and nobody
  else's business, which is right about who it matters to and wrong
  about who is standing next to them -- whoever turned the tutorial on
  in the lobby is the one they will ask to turn it off. See
  [Who may act on a game](permissions.md#who-may-act-on-a-game).
- **`stage_tutorial_beat` gates the top of `send_turn_prompt`**, which
  is called once a turn -- so the advance is what counts the beats. It
  **moves nothing**; it posts the lesson (or `HANDOVER`, once the
  script has run out) behind a Continue button and holds the rest of
  `send_turn_prompt` -- an AI turn or the ordinary action prompt --
  until it is pressed; see "Reading the notes" below.
  `tutorial_staged` keeps the count honest: `/d12ball offensive_choice`
  and `/d12ball resume force:true` also send a turn prompt without a
  turn having been played.
- **It is ahead of the AI branch** in `send_turn_prompt`, because beat
  3 is a turn the coach *defends* and its lesson has to be posted
  before Dinky moves -- Dinky's own move is part of what the Continue
  click releases.
- **Setup coaching is skipped**, and the script arms at the kickoff --
  so teams, the toss and home-or-visiting are played exactly as an
  ordinary game plays them.

### Reading the notes: the Continue gate

Two narration messages posted back to back with nothing for the coach
to click between them is exactly what gets scrolled past in a busy
Discord channel -- and the same is true when a note is immediately
followed by an *interactive* prompt, since the newest message with
live buttons is what draws the eye, not the note sitting above it.
Since 2026-08-25 every tutorial note that has something following it
is held behind a **Continue** button instead: `WELCOME` before beat
1's lesson, every beat's `lesson` before whatever the turn does next,
every beat's `maneuver_note` before the maneuver menu, beat 1's
`speed_note` before the speed prompt, `HANDOVER` before the first
un-railed turn prompt, and `COACHING_NOTE` before this coach's first
Coaching Choice menu.

- **The gate is a prompt** (`PromptKind.TUTORIAL_CONTINUE`), since the
  last increment of the model/Discord split, and
  `d12ball/flow/gates.py` is the whole of it. `hold_behind_note(game,
  note, then)` writes which note is up and the `FollowOn` the click
  should run onto `D12BallGame.tutorial_gate`, and ends the step on
  the gate prompt with the note as its `ask` -- the step's own lines,
  where it had any, go *above* the note in the same message, so a
  coach reads the event, then the lesson, then (after the click) the
  question. `continue_step` is the click: take the note down and run
  `then`, or, where `then` is `None`, whatever question the position
  already asks. That second shape is the common one, and it is why the
  maneuver pick's and the speed choice's asks in `pending_prompt` are
  the live wording rather than a bare "Choose:" -- after the note the
  game shows what it is waiting on, and it has to be the same question
  the note was in front of. The note's text is the model's too
  (`tutorial.note_text`), because it is narration.
- **Every gate is raised from inside the step it gates.**
  `turn.begin_turn` stages the beat and holds `LESSON` (or, past the
  last beat, `HANDOVER`) in front of `START_TURN`; `MANEUVER` is held
  by the maneuver-action offer, `SPEED` by the speed-choice offer,
  `WELCOME` by the setup coaching's close, and `COACHING` by
  `begin_substitution_window` on this coach's first window
  (`tutorial_coaching_explained` keeps it to one, and is set *before*
  the gate so the continuation cannot raise it again). **A gate's
  continuation must not raise the same gate again**, which is why the
  turn prompt is two steps: `SEND_TURN_PROMPT` may gate, `START_TURN`
  is what runs after.
- **Restart-safe now, as the price of being a prompt.** The gate used
  to be `D12Ball.post_tutorial_note` with the continuation in a closure
  on a `TutorialContinueView` that was never registered, so a restart
  left a dead button and `/d12ball resume` re-drove the position
  *underneath* the note -- which put up the thing the note explains
  without the note. The record on the game is what a restart reads:
  `pending_prompt` answers `TUTORIAL_CONTINUE` ahead of everything,
  `GameService.resume` re-posts the note first, and `skip_tutorial`
  spends a held gate the way the click would. The `then` survives as a
  `FollowOn.to_dict()`, and the golden's every press is the proof it
  comes back the same.
- **`COACHING` is gated too, since 2026-08-27**, and for the reason the
  others are: an ungated note sitting directly above an interactive
  menu is exactly the case the Continue gate exists for. It was left
  ungated at first because the branch chain was hairy and the note
  fires once, late, outside the five scripted beats; the step shape
  made the tail no worse to reason about.

### The Coaching Choice, which the script cannot schedule

There is no beat for it and there cannot be one: a new play offers the
window to the side **restarting** play, which after the coach's goal is
Dinky -- and an AI window never formally declares, so no reply comes
back the coach's way either. `COACHING_NOTE` is a one-off explainer
fired from `begin_substitution_window` at the first window this coach
is ever offered, whenever the game gets round to it. It therefore reads
`game.tutorial` rather than `in_tutorial`, and usually lands a few
turns after the script has finished. `tutorial_coaching_explained`
keeps it to one, and `skip_tutorial` sets that flag so a coach who
opted out is not taught anyway.

### The playthrough test

`tests/test_d12ball_tutorial.py` plays the whole script through the
**real cog** with Discord mocked, pressing whichever button the rails
leave enabled. It is the only thing that can catch what this design is
most fragile to: a change to a maneuver's effect, the run back or the
loose-ball rule putting the story out of joint without breaking
anything else in the suite. It asserts that **no side is ever
re-dealt** (`MatchState.deploy_side` is called zero times), that
staging a beat moves nothing, that only the two intended choices ever
leave two buttons live, that possession changes hands the three
scripted times, and that the whole thing arrives at a goal on minute 7
-- that last one with the dice pinned, since the shot itself is not
scripted (see "Determinism: rails and dice").

**Only the test that is about the goal pins them.** Everything else
plays the real dice, which is what makes the suite an actual
playthrough rather than one fixed transcript -- and is why
`test_the_scripted_shot_reaches_the_statistics` asserts the shot
statistics against `len(match.goals)` rather than against 1. The goal
log is a separate record from the `shot` event that fold counts, so
the two agreeing is a real claim whichever way the shot went, and the
miss is the run that would otherwise fail.

**The lesson text is not asserted anywhere.** It is prose, it will be
revised, and a test quoting it would only ever break on a reword. What
is asserted is every claim it makes that the data could contradict --
which maneuver beats which, that the deal starts out of shooting range,
that the striker is on the space the last pass lands on, that exactly
one Dinky card is standing there.

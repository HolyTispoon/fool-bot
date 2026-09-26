# The game service and the presenter

The second and third parts of [ARCHITECTURE.md](../../ARCHITECTURE.md),
as they are built: `GameService` in `gamesaves/d12ball/service.py`,
and `D12Ball.present` in `cogs/d12ball/core.py`. This note is the
reasoning behind their shape; the map in CLAUDE.md says where they
are. What it replaced is recorded in
[model-discord-split.md](model-discord-split.md), whose "`driver.py`"
and "last increment" sections describe the cog's own loop
(`dispatch_step_result` running `driver.advance` itself, three
dispatchers, `SafeView.answer` and `dispatch_answer`) -- read those
as history.

## One door, one save

`GameService.apply_action(game_id, action)` is the one way a click
changes a game. It loads the match from the record, calls
`driver.answer`, runs everything the answer starts through
`driver.advance`, writes the match **once**, and hands back a
`GameResult`. A `Refusal` comes back as a result with `refusal` set
and nothing written. Four more entry points cover what is not a
click: `begin` opens the pre-kickoff window once setup has settled
the sides; `run_step` runs a `FollowOnStep` by name; `resume` runs
the step the bot itself owes, or hands back the prompt, and says in
words what it was waiting on; `reset_turn` is the recovery command's
`force`, throwing a turn away and re-asking the offense, refused
where the position is not a turn (`RulesEngine.turn_reset_refusal`).
All five reduce to `run`, which is the loop and the save.

**The save moved out of the views and out of the dispatcher.** Before
this, `cog.persist(` was spelled 28 times in the views and 16 times in
the cog, with three different reasons: the dispatcher's one save per
run, the four load-bearing early saves on the rolls (a failed dice
upload must not let the next click roll again), and the branches that
"never reached a dispatcher" (a tie, a hub edit, an Overdrive
declaration). The service saves before it returns, which is before
the view has rendered anything, so every one of those reasons is met
by the same line. The bare `save_games` calls that write the game
record alone -- a message id, a status -- stay where they are, and
`GameService.save` is the same call for a caller that holds the
service. The admin commands that move a meeple or set the clock write
through `service.persist`.

## The result is groups, not strings

ARCHITECTURE.md sketches `public_messages: tuple[str, ...]`. The
result here is richer, on purpose. Discord posts pictures of the
position in the middle of a run -- a loose ball is announced by
showing where it is, the tail of a maneuver shows the settled board,
a new play's board is pinned -- and *where* those go is pinned by the
four goldens, byte for byte. A flat list would lose the order a
coach reads. So `GameResult` carries:

- `answer`, the answer's own lines, kept apart because a Discord
  prompt is *replaced* by its answer (an edit, one request);
- `groups`, every closed narration group and every stop, in order,
  each a `Narration` tagged with the step that said it and, where the
  frontend stopped to draw, carrying the position as
  `MatchState.to_dict()` at that moment;
- `narration`, what the run was still carrying, which opens the
  prompt;
- `prompt`, `board_changed` (since the last drawn group), `detail`
  (a roll's numbers), and `match`, the position after the call.

The prompt carries its `options` -- what may be chosen, a dataclass
per kind, attached by `driver.advance` to the step's own `next` and
by `pending` to the chain's reading, so the two agree (step 6 of
docs/architecture-migration.md; see
[model-discord-split.md](model-discord-split.md)). A web page renders
the same groups, draws the same boards from the same dicts and builds
its controls from the same options. Nothing in it is Discord's.

## Batching is still the frontend's

Principle 8 in CLAUDE.md did not move. `Batching` is the frontend's
answer to three questions, handed to the service once at
construction: which steps' lines are a message of their own
(`own_message`), where the loop must stop for a picture
(`stop_after`), and what to do at a stop (`at_stop`: draw it, post
the lines plainly, or carry them on). `DiscordBatching` in
`cogs/d12ball/core.py` is those three answers for Discord -- the sets
that used to be `DRIVER_STOPS`, `DRIVER_OWN_MESSAGE` and
`FOLLOW_ONS_THAT_SPEAK_THE_LINES`, and the branches that used to be
`stop_draws_the_board` and `post_stop`. The service never reads a
step's name to decide anything; it asks the `Batching` it was given.

**`carry_from` is the fourth batching decision, and it is per
call.** A step takes the lines said before it as its `lead_in` and
*composes* them into its own text -- the Low Pass's line and the
clock's, one paragraph -- so the presenter cannot join them
afterwards; they have to go into the run. `apply_action(...,
carry_from=k)` hands back the first `k` of the answer's lines and
carries the rest. `None` keeps them all (the view replaces the prompt
with them), `0` carries them all (the distance menus, whose answer
opens the step's message), `1` posts the first and carries the rest
(the rolls, whose verdict follows the dice). A callable is asked with
the `Answered` where the split depends on what came back: the injury
die that was not rolled, the Mind Pull that landed, the turn action
that walked a challenger in. This is the old `lines_posted` flag and
the `narration[1:]` re-slicing in the views, made one parameter.

## The AI answers here

Step 7 of [../architecture-migration.md](../architecture-migration.md).
The AI is a client of the service like a coach, not a branch inside
a step: when `run`'s loop ends on a prompt, it asks
`driver.ai_action` whether the question is the AI's --
`d12ball.prompts.asked_sides` is the one reading of whose question a
prompt is, the third reader over the chain beside `pending_prompt`
and `owed_step` -- and if it is, puts the strategy's `Action` through
`driver.answer` exactly as a click goes, then carries on. A roll is
nobody's question, so the loop stops there and the AI never rolls
(CLAUDE.md, "Nothing rolls dice on its own"). A strategy whose answer
is refused is a bug and raises: the prompt offered what it offered,
and `AIStrategy.choose` read the offer. `MAX_AI_ANSWERS` is the guard
against a strategy that answers without moving the position, since
this is one process for every game at once. `resume` runs a saved AI
prompt on the same way ("the AI's choice"); a save waiting on one is
a run that never finished, and the startup sweep re-arms nothing for
it.

**An AI answer is batched by the frontend**, because the coach's
was. `Batching.carry_answer(action, answered)` is `carry_from` for
the answers nobody clicked, and `DiscordBatching`'s `AI_ANSWER_CARRY`
mirrors what each kind's view passes -- the distance menus' answers
open the effect's message (0), a declined offer's first line stands
alone (1), everything else is kept. The result carries the outcome
as two more group tags: `Narration.prompt`, the lines the run was
carrying into a question the AI answered before anybody saw it --
what a coach's prompt message would have opened with, without the
question -- and `Narration.action`, the answer's own kept lines, with
`detail` beside them where the answer had a picture's numbers. The
presenter posts each the way the kind's view posts a coach's
(`D12Ball.post_ai_answer`): a hub note is never a message, the
shootout's first block is the coach's own secret, the maneuver pick
and the halftime token go a message per block.

**One exception, for the cascade.** Where an answer carries whole,
it is a continuation of what led to the question rather than an
event of its own, and the group the loop had just closed after the
step that asked -- if it was that step's, and not a picture -- is
taken back and carried in front of it. The run back closes a message
before each question it puts; the AI's placement belongs in that
message, composed by `CONTINUE_RUN_BACK` like the forced placements
around it, and that is how an AI side's run back is still one
message and one board refresh ([rate-limits.md](rate-limits.md)). It
is the service undoing one `own_message` close, on the frontend's
say-so, and it is confined to `_answer_for_ai`.

## Setup and the lobby are service methods, not prompt kinds

Step 8 of [../architecture-migration.md](../architecture-migration.md),
decision 6 of [../web-app.md](../web-app.md). Nothing before the
kickoff is a turn: no `MatchState` exists until the sides are settled,
so there is no `PendingPrompt` to answer and no `driver` to run. What
there is, is a record -- `D12BallGame` -- and a dozen changes to it
that each have a rule: who may take the second seat, what a tutorial
pins, which team the other side's pick rules out, who may choose home
or visiting. ARCHITECTURE.md says lobby operations "can use small
service methods" and "do not need to pass through the turn driver",
and that is the shape: `next_game_number`, `create_game`,
`discard_game`, `lobby_join`, `lobby_observe`, `lobby_leave`,
`configure`, `start_lobby`, `reopen_lobby`, `pick_team`, `flip_coin`
and `choose_home_or_visiting`, each load, one change, save once,
return the record. A web room adds two, `take_seat` and `vacate_seat`,
the same shape over the record's seat moves; they are the room's and
not the lobby's, open before kickoff and during the game, and never
move the other seat ([web-app.md](web-app.md), "Rooms, seats and who
holds them").

**The rules are the record's, and it refuses with `RuleRefusal`.**
Each service method is a thin door over a method of the same name on
`D12BallGame` (`configure` over `configure`, `start_lobby` over
`start_lobby`, ...), which is where the sentence lives: "This lobby is
full", "That team is no longer available", "The tutorial is played on
a 7-space board". The service lets the exception through and writes
nothing, so a frontend's `except RuleRefusal` is the whole of its
error handling, and a web app validates a lobby click exactly as the
bot does. `RuleRefusal` moved to `d12ball/game.py` for this -- the
record is the leaf of the model and `components.py` imports from it
-- and is still imported from `components` everywhere else. The
record's older mutators (`resolve_coin_toss`,
`choose_home_or_visiting`, `start_game`, `finish_game`, `abandon`)
raise it now too. A value the record cannot read -- a board size of
8, a setting nobody offers -- is a bug in the frontend and a bare
`ValueError`, per step 6.

**The service constructs nothing random** (decision 7). The coin is
`RulesEngine.flip_coin`, and the AI's team is
`AIStrategy.choose_team(pool)` over `D12BallGame.ai_team_pool` -- the
same `excluded_teams` reading the picker greys out by and `pick_team`
refuses against, so Dinky cannot land on the one matchup a coach may
not pick. `flip_coin` is the one method with a branch: in a solo game
the AI won, it takes the AI's side for it (visiting in a tutorial,
whose script is written for a coach with the ball at kickoff;
`choose_home_or_visiting` otherwise) and deals the match, so the
coach's next question is `begin`'s window and not one the AI has
already answered.

**A table asks the record, never works it out.** A frontend that
draws setup -- the Discord views, the web app's table (step 3 of
[../web-app-next.md](../web-app-next.md)) -- reads what it may offer
off the record, each reading the one its door refuses by:
`open_settings` (the settings `configure` will consider in this state),
`teams_open_to(n)` (the teams a picker offers, `excluded_teams`
behind it), `coin_is_owed` and `home_choice_owed_by`. The Discord team
picker and the web table both grey by `teams_open_to`, so a pairing
greyed on one is greyed on the other.

**The rematch is a service method too**: `rematch(game_id)` is a
finished game's next record -- the same two seats (the AI where it
sat), the same settings, remembered on the finished game as
`rematch_game_id` so a second ask returns it -- saved once. A web
room's opens in its lobby (`in_lobby=True`), so an empty seat is
filled before the sides settle. The Discord rematch still opens its
channel first and its record through `open_new_game`, which is where
the channel id comes from; moving it onto `rematch` is a change to the
cog for another day, not a rule either side decides differently.

**What stays the frontend's** is what it always was: the channel and
its permissions, the message and its id, whose account clicked.
`open_new_game` and `open_lobby` make the channel, then the record
through `create_game` with the ids the record now carries as
optional (decision 3, the step's first commit), then post the message
and write its id through `save`; a message that could not be posted
is `discard_game`, and a lobby whose team picker could not be posted
is `reopen_lobby`. A game helper's team pick is told which side it is
for by `D12BallGame.team_pick_lands_on`, but *that* it is a helper's
is the view's to know. Two record-only writes remain in the setup
views -- the message id after the coin's choice message goes up, and
after the lobby's team picker -- and both are `GameService.save`, so
`cogs/d12ball_views` binds `save_games` nowhere.

**`configure` is one method for every setting**, keyed by the word a
button carries (`GAME_SETTINGS`), taking the enum or its wire string.
The lobby and the setup settings block each offer a subset -- the
Test game and Tutorial toggles and the name are the lobby's, the AI
row an open solo game's -- and the record refuses the rest by its
state, never by which screen asked. One consequence the author
should know: a tutorial created by `/d12ball create_game` used to
reach the setup screen with live mode and board buttons, and could be
put on a nine-space board its script is not written for; the pin is
the record's now and holds for the whole of setup.

## The presenter saves nothing

`D12Ball.present(interaction, game, result)` is the whole of the
Discord side of a run: write the persistent board once if it moved,
post each group as the messages its step earns (`post_group`), draw
each picture from the snapshot the service took, and put up the
prompt through `render_prompt`. It replaces `dispatch_step_result`'s
loop, `post_stop`, `stop_draws_the_board`, `post_narration_group`,
`post_then_dispatch`, `post_blocks_then_dispatch` and `run_step`.
`dispatch_step_result` survives as `run` + `present_result` for the
bot's own steps (a gate skipped, the tests' `run_step`), and
`apply_action` on the cog is the service's with the result rendered
(see [testing.md](testing.md) for how a test's stub on the cog is
reached: the routing rides on the cog's `service`).

**The result is rendered at the door, once.** The service's sentences
carry tokens -- `{team:purple}`, `{coach:1}` and their kind, step 9 of
[../architecture-migration.md](../architecture-migration.md) -- and
`D12Ball.rendered(game, result)` draws every one of them for Discord
at the two doors the cog takes a result from the service through
(`apply_action` for a click, `present_result` for everything the bot
runs itself -- a step, begin, resume, reset), before a view or
`present` reads it. Nothing below
that reads a token; a web frontend renders the same result its own
way. See "Tokens" in [model-discord-split.md](model-discord-split.md).

The board write is the one piece of arithmetic left: a drawn group
writes the persistent message from its own render (render once,
upload twice), so the plain write is owed only for what moved after
the last picture, and it goes in front of the first thing posted
after it. `PROMPTS_DRAWN_LATER` still holds off the write in front of
a question whose answer draws the board a moment later.
`render_match_png`, `post_new_play_board` and `announce_board_update`
take the position to draw, so a snapshot renders from the dict the
service handed back rather than from the save.

## Recovery is the service's, off the one reading

`resume_pending_prompt` was a second reading of "what is this match
waiting on", in the cog, with nine flags in its own order and a cog
routine per branch. Steps 1 to 4 of the migration moved it whole into
`GameService.resume`; step 5 removed it. **The reading is
`d12ball.prompts.owed_step`'s now**: one chain in `d12ball/prompts.py`
(`pending`) answers either a `PendingPrompt` -- somebody is asked --
or a `FollowOn` -- the bot owes the next step -- and `pending_prompt`
and `owed_step` are the two readers over it, exactly one of which
answers for any position. `resume` runs what the second hands back
through `run`, or hands back what the first does; `driver.answer`
refuses an action while the second answers (`STEP_OWED`), which is
what closed finding 1 of [../web-app.md](../web-app.md): a turn
action used to be applied on top of a half-run run back, because the
chain answered `PLAYER_ACTION` for the states where nobody was asked.
Those fallbacks are gone, and so is the `PlayerActionView` the
startup sweep used to re-arm over one of them -- the sweep skips a
game the bot owes a step on and logs it, because a click there is
refused and `/d12ball resume` is what runs it.

The six steps a resume can name that nothing else named --
`ADVANCE_SETUP_STAGE`, `ADVANCE_HALFTIME_STAGE`,
`ADVANCE_FULL_TIME_STAGE`, `ADVANCE_SHOOTOUT`, `FINISH_TIME_OUT`,
`BEGIN_BALL_RECOVERY` (step 5 added a seventh, `RUN_AI_COACHING_WINDOW`,
and step 7 took it out again: an AI side's window is a prompt it
answers) -- are `FollowOnStep` members
with a row in `MODEL_STEPS`. Each is still called inline by the step
that ordinarily reaches it; the member is the door a resume comes back
in through, and the closed enum is why nothing can reach one by
spelling its name. The three the chain already named --
`CONTINUE_RUN_BACK`, `RESOLVE_LOOSE_BALL`, `BEGIN_EFFECT_RESOLUTION`
-- are what the old fallbacks now resolve to. `OWED_STEP_NAMES` in
the service is the wording `/d12ball resume` reports each as.

What "owed" means, branch by branch, is what the flow decides at that
point without asking anybody: a stage set with no window open (the
advance opens it); a pickup nobody need make;
a run back with only forced placements left; a loose ball both sides
have answered; a won card with nothing to ask. The stage fixtures in
`tests/prompt_fixtures.py` open their window now, because the hub
answer had always refused a window that was not open (`_window_is`)
-- the old `COACHING_HUB` reading for a bare stage was a prompt whose
every answer was a stale click, which is the shape an owed step has.

A restart still re-arms one message per game; `resume` re-posts
through `render_prompt`, so a resumed prompt gets its picture (the
field strip, the hand, the coach's half-field) where the old bare
re-post did not. An open Coaching Choice comes back with the "picking
this up" note above the allowance, worded by the engine.
`tests/test_d12ball_game_service_resume.py` resumes every fixture in
the shared table with no cog imported -- an asked position comes back
as its prompt with nothing written, an owed one is run to a question
with one save -- and `tests/test_d12ball_recovery.py` is the Discord
half over the same table.

**The challenge image is keyed on the group.** `Narration.arguments`
carries the stopped or closed step's own kwargs, so `post_group` draws
the walk-in's image of the `challenger_id` the step named rather than
of whoever `match.challenger_id` happens to hold by the time the
group is rendered.

## What a test does now

`tests/cog_steps.py` holds the ninety-odd cog wrappers the tests
drove a step through, as free functions over the cog. `run_step` and
`dispatch` are the two shapes; the rest reduce to them.
`arm_cog_stub_routing` wraps the cog's `service` property, so the
`GameService.run` every entry point reduces to runs with a test's cog
stubs routed into the driver's table. `suppressed_cog_saves`
patches `gamesaves.d12ball.service.save_games`, which is where every
click's save is.

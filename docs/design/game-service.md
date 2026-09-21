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
and nothing written. Three more entry points cover what is not a
click: `begin` opens the pre-kickoff window once setup has settled
the sides; `run_step` runs a `FollowOnStep` by name (the recovery
command re-posting the turn); `resume` runs the step the bot itself
owes, or hands back the prompt, and says in words what it was waiting
on. All four reduce to `run`, which is the loop and the save.

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
three goldens, byte for byte. A flat list would lose the order a
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

A web page renders the same groups and draws the same boards from
the same dicts. Nothing in it is Discord's.

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

## The presenter saves nothing

`D12Ball.present(interaction, game, result)` is the whole of the
Discord side of a run: write the persistent board once if it moved,
post each group as the messages its step earns (`post_group`), draw
each picture from the snapshot the service took, and put up the
prompt through `render_prompt`. It replaces `dispatch_step_result`'s
loop, `post_stop`, `stop_draws_the_board`, `post_narration_group`,
`post_then_dispatch`, `post_blocks_then_dispatch` and `run_step`.
`dispatch_step_result` survives as `run` + `present` for the bot's
own steps (a gate skipped, the tests' `run_step`), and `apply_action`
on the cog is the service's, kept as a method so a test's stub on the
cog is reached (see [testing.md](testing.md)).

The board write is the one piece of arithmetic left: a drawn group
writes the persistent message from its own render (render once,
upload twice), so the plain write is owed only for what moved after
the last picture, and it goes in front of the first thing posted
after it. `PROMPTS_DRAWN_LATER` still holds off the write in front of
a question whose answer draws the board a moment later.
`render_match_png`, `post_new_play_board` and `announce_board_update`
take the position to draw, so a snapshot renders from the dict the
service handed back rather than from the save.

## Recovery is the service's ladder

`resume_pending_prompt` was a second reading of "what is this match
waiting on", in the cog, with nine flags in its own order and a cog
routine per branch. It is `GameService.resume` now, the same order,
each branch a flow function run through `run` -- which is the first
step toward proposal 1 of [../web-app.md](../web-app.md), the model
answering "nobody is asked; run this" itself. A restart still re-arms
one message per game; `resume` re-posts through `render_prompt`, so
a resumed prompt gets its picture (the field strip, the hand, the
coach's half-field) where the old bare re-post did not. An open
Coaching Choice comes back with the "picking this up" note above the
allowance, worded by the engine.

## What a test does now

`tests/cog_steps.py` holds the ninety-odd cog wrappers the tests
drove a step through, as free functions over the cog. `run_step` and
`dispatch` are the two shapes; the rest reduce to them.
`arm_cog_stub_routing` wraps `dispatch_step_result` and
`apply_action` on the cog, so a stub a test puts on the cog is
reached by the driver inside the service. `suppressed_cog_saves`
patches `gamesaves.d12ball.service.save_games`, which is where every
click's save is.

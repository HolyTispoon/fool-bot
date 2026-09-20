# Discord's rate limits

Design notes for fool-bot; the map is [CLAUDE.md](../../CLAUDE.md), the rules are [living-rules.md](../living-rules.md).

## Discord's rate limits

The bot was getting rate limited mid-game, and the cause was not one call
site: it was that a single click fanned out into ten or twenty requests into
one channel with nothing between them. **The fix for that is always fewer
requests, never slower ones.** discord.py already sleeps and retries on a 429
(the `We are being rate limited... Retrying in N seconds` line is its, at
WARNING, so it is console-only and never reaches #logs); adding our own
pacing on top would only make a turn take ten seconds and still spend the
same budget. So:

**The gate itself lives in `cogs/d12ball_boards.py`.** Everything below
describes `BoardRefresher` and the `BoardRefreshState` it keeps per game.
They were seven attributes and six methods on the cog, touched by nothing
but each other, which made the one piece of this bot with measured timing
invariants read as ordinary cog surface among 223 methods.

- **The seven were parallel dicts keyed by game id, and are now one
  object.** Every method reached into several of them for the same game in
  the same breath, so the invariant that had to hold was that all seven
  agreed about one game -- written down nowhere, and kept by hand at each
  of the eleven sites that wrote them. Each field of the dataclass carries
  its dict's "missing" as its default, so nothing had to learn a new
  absent-value.
- **`state()` starts an entry and `states.get` does not.** A caller about
  to write asks the first; a caller only reading asks the second, so that
  asking after a finished game does not quietly file a new entry for it.
- **`D12Ball` keeps a thin forwarding method for each of the six**, so the
  fifty-odd call sites did not move in the change that extracted this. They
  are the identical call on `self.boards` and carry no reasoning of their
  own; the reasoning is on the method each forwards to.

- **Read a 429 by looking the ids up, not by reasoning about them.** All the
  warning gives you is a method and a URL, and the only thing in it that names
  the game is the channel and message id. Three batches of these were read by
  inferring which message that must have been, and the inference that the
  board's id sits a few seconds after its channel's is wrong -- **the board
  message is not the message `create_game` sends.** The coin flip re-points
  `game.message_id` at the home/visiting choice message it posts (in
  `CoinFlipView`, `cogs/d12ball_views.py`), because that is the message the
  buttons and every later board have to live on. Setup is a play-by-Discord
  affair that can take hours, so the board's snowflake can trail its channel's
  by any amount at all, and the first message in the channel keeps the setup
  text for the rest of the game. So `D12Ball.__init__` logs one INFO line per
  unfinished game naming its channel, board message and prompt message, and a
  warning is attributed by grepping the startup block for the id rather than by
  reasoning about it.
- **Batch what the bot does on its own, and only interrupt for a person.** A
  cascade of automatic steps is one message and one board refresh at the end
  of it, not one of each per step -- see `continue_run_back`. Nobody reads the
  intermediate boards; the one worth looking at is the one where everything
  has finished moving.
- **There are two dispatchers, and which one a step gets is a batching
  decision.** `D12Ball.dispatch_step_result` hands a step's narration to
  whatever comes next as its `lead_in`, so a cascade of the bot's own steps
  is one message. `D12Ball.post_then_dispatch` posts it as a message of its
  own and carries nothing forward. The second is for the handful of lines
  that are an *event* rather than a preamble -- where the ball came down,
  that a new play has started, that everybody is running back -- and a coach
  reads the channel expecting those to be their own beat. It is a method on
  the cog rather than a flag on `StepResult` because principle 8 puts
  batching on this side of the seam: the model says what was said and in
  what order, and nothing more. Getting it wrong is cheap to catch and
  invisible by inspection, which is what the two goldens are for -- the
  advanced one caught three merged pairs the hour it existed.
- **A step says the board moved; the frontend decides what that costs.**
  `StepResult.board_changed` is a fact about the position -- the ball moved,
  a meeple moved -- and `dispatch_step_result` turns it into *at most* one
  write of the persistent board message. At most, because some of the steps
  it hands off to draw the board themselves: `begin_loose_ball` announces the
  position with the board under it, since the ball is lying somewhere nothing
  in the channel has named. Drawing it again in front of that is the same
  bytes twice for one click, so `FOLLOW_ONS_THAT_DRAW_THE_BOARD` in
  `cogs/d12ball/core.py` names the follow-ons it is skipped for.
  - **The answer is the step's, not the calling card's.** Eight sites reach
    `begin_loose_ball`, and they were lifted a rank at a time and then, in
    Phase 4, the rest at once -- the step itself is
    `d12ball/flow/arrivals.py`'s now. Keying the suppression to the step
    means each caller inherits it rather than deciding it again, which is
    how the two paths that opted out of `restrict_to_occupants` survived,
    one floor up in this same flow.
  - **`OFFER_SETUP_PASS_PUSH_BACK` is in the set one step removed**, because
    all three of its branches end in `begin_loose_ball`: the fallback where
    no distance fits, Dinky's maximum, and the coach's own answer. The board
    reaches the channel a beat later rather than in front of a question whose
    answer moves the ball again.
  - **It lives in the cog on purpose.** This is a five-in-five economy, and
    rate limits are the frontend's -- principle 8 in CLAUDE.md. A web app
    reading the same `StepResult` has no such bucket and should redraw every
    time. Putting the suppression in the step would have shipped this
    channel's arithmetic to every frontend that ever reads it.
- **Render the board once per state, not once per upload.** `render_match_png`
  returns bytes and `match_file_from_png` wraps them, because uploading a
  `discord.File` consumes the stream inside it. The end of a maneuver puts the
  same board in two places (the persistent message and the snapshot under the
  result) and so does `announce_board_update`; both draw it once and upload it
  twice. `refresh_match_image` takes a `png=` for exactly this, and so does
  `post_new_play_board`.
- **Only new-play boards are pinned, and `post_new_play_board` is the only
  thing that pins.** A pin is a request of its own *and* a "pinned a message"
  system post in the channel, so `pin_board_message` has exactly one caller and
  every pinned board is a snapshot of its own -- the kickoff included, which
  used to be the odd one out. It was the persistent message, pinned in place by
  a `D12Ball.pin_board` that no longer exists; see "The first board of a game"
  under "Working on the board image" in [board-image.md](board-image.md) for why that changed. Pinning every board a
  turn puts out would roughly double the channel's traffic and fill the 50-pin
  cap inside a game.
  At the cap the pin fails with error 30003 and the helper unpins the oldest
  board *it* pinned -- read off `channel.pins(oldest_first=True)` and matched
  by the `d12ball-pbd` filename -- so a pin somebody else put there is never
  displaced, and a channel with no board to roll off simply leaves the new one
  unpinned. Every failure is swallowed: a missing pin is worth less than the
  turn it would take down with it.
- **The full-image link is paid once a burst, not once a board.** Editing the
  message uploads a new attachment, which invalidates the old one, so the
  "View full image" link has to be re-cut in a second edit -- the URL does not
  exist until the upload lands. That is two edits a board, and a turn's worth
  of boards is more than the bucket has. So every write strips the now-dead
  link in the edit it was already paying for and records the URL in
  `link_owed`, and a later pass with nothing new to draw puts a live one back.
  The board is linkless for a window or two rather than dead-linked for it.
  - **The link may not ride along with the upload that killed it**, and that
    pair is what the fifth batch of 429s was. `BoardRefresher.write` used to
    relink in the same pass, so a settling write sent its second PATCH about a
    third of a second after its first had landed -- inside the window that
    first request opened. The log is six refusals evenly 11.8 seconds apart
    (one interval, plus the retry each cost), every one carrying a
    `retry_after` that was the remainder of a window a board upload had just
    opened, for as long as the two coaches kept clicking. **A 429 reaching the
    log at all means a limit the headers did not advertise**: discord.py
    pre-emptively waits out any bucket Discord tells it about, so the gate can
    only be beaten from inside its own window. Every pass is one request now --
    the board if one was asked for, otherwise the link the last one owes --
    which is what makes the interval the whole of the spacing.
  - **`relink` says which of the two a pass may spend its request on**, not
    whether it pays for both. An interim write (the immediate one,
    `relink=False`) leaves the link to the trailing pass; a trailing pass
    (`relink=True`) draws the board if it has a new one and settles the link if
    it does not.
  - **The settling pass is owed as soon as a link is stripped**, so
    `refresh_match_image` schedules one after an immediate write whenever
    something is in `link_owed` -- not only when a second refresh asks.
    Without it a quiet board would keep the link that write took off. The same
    fact keeps the trailing task looping: `schedule` returns only once nothing
    is wanted **and** nothing is owed, since the link is the one piece of work
    no call site will ever come back and ask for.
  - **A settling write with nothing new to draw still pays the link**, from the
    URL it was handed rather than by re-fetching the message: one edit, and the
    common case, since the last step of a click usually moves nothing. That is
    `BoardRefresher.settle_link`, and it spends no request when nothing
    is owed. It always clears `link_owed`, which is what stops the loop above
    spinning on a link it cannot place.
  - Before the home/visiting choice the message is still the setup prompt: its
    buttons are live, it has no link to go stale, and its view is left alone.
    **And it is a different message from the one the channel opens with** --
    `CoinFlipView` re-points `game.message_id` at the home/visiting choice
    message, so a board write never touches the "Start playing in this channel"
    post again. Only the *content* is left alone from then on: a refresh edits
    attachments and the view, so the persistent message reads as setup text with
    a board under it for the whole game.
- **Channel message edits are one bucket, and it is the one that runs out.**
  Every 429 in two logged sessions of play was a `PATCH` on
  `/channels/{id}/messages/{id}`. **`message_id` is not one of Discord's major
  rate-limit parameters**, so every edit to every message in a game's channel
  shares a single bucket of roughly five requests in five seconds -- editing a
  different message buys nothing. Check `discord.http.Route` before assuming
  otherwise; this was got wrong twice.
  - Only edits reached *through the channel* land there.
    `interaction.response.edit_message` is the interaction-callback route and
    `followup.send(...).edit()` is the webhook route, so neither competes.
    `channel.get_partial_message(...).edit()` does, and after the second round
    of 429s **the board message is the only thing that does it** -- every
    request in that bucket, all game, is a write to one message.
  - **Nothing else may be edited through the channel without a reason.**
    `close_maneuver_prompt` used to re-edit the maneuver prompt on each pick
    with a freshly built `ManeuverActionPromptView`. Nothing about that message
    changes when a side picks -- it names who it is waiting on, and the view is
    built from the game id alone -- so it was a request out of this bucket,
    once a maneuver, immediately before the resolution's own board refresh, for
    nothing. It now only deletes, once both sides have picked, and a delete is
    a route of its own. Who has picked is announced in its own message.
    **That is now a rule about the prompt and not only an economy**: the
    buttons are public (see [The maneuver prompt](maneuver-prompt.md#the-maneuver-prompt)), so an
    edit greying a picked side's row would tell the other coach they had
    answered.
  - **A board refresh spends exactly one of the five, and so does every
    pass**, so `refresh_match_image` is rate-gated per game: the first goes out
    at once and any that arrive within `BOARD_REFRESH_INTERVAL` collapse into
    **one** trailing refresh rather than queueing. A pass that spends two is
    a pass the interval cannot space -- see the full-image link above.
  - **`BOARD_REFRESH_INTERVAL` must stay above Discord's five-second window**,
    or two refreshes fall inside one window. At three seconds a turn spent
    exactly five and was still earning 429s -- measured. Six leaves a turn at
    three requests over three passes: the immediate board, the settling board,
    and the link that one owes. Adding a call site is free; shortening the
    interval is not.
  - A trailing refresh **draws when it runs**, never from a `png=` handed to it
    earlier -- the board it was offered is stale by the time it fires, and
    re-drawing is exactly what lets one pending refresh stand in for every
    request behind it.
  - **Only one write per game is ever in the air**, held by
    `locks`. A write is not instant: drawing a 2200px board and
    uploading it is most of a second, more on a bad connection, so an upload
    slower than the window let the trailing pass start alongside the immediate
    write and put two PATCHes on one message in the same instant. That is the
    one thing an interval cannot space out, and it is what a pair of 429s
    logged in the same second was.
  - **The interval runs from when a write lands, not from when it was sent**,
    and that is the whole of what makes it an interval. Timed from the send it
    measures nothing: the board is nearly a megabyte of PNG, so the request
    itself is seconds long on an ordinary connection -- and twenty-odd when
    discord.py is sleeping off a 429 *inside* the single await this code makes
    (it sleeps the `retry_after` and retries, up to five times). For all of
    that time the window read as having been open for ages, so the moment the
    lock freed, the queued write went out on its heels -- into the bucket that
    had just been refusing the one before it. Measured: **6 microseconds**
    after a throttled write landed, and **0.7 milliseconds** after a merely
    slow one. So a burst of warnings is not evidence of a burst of clicks: the
    third batch is four retries of one request, and the gate fed it.
    - **The lock stopped two writes being *concurrent*; only this stops them
      being *consecutive*,** which is the same feedback loop one step along.
      Both are needed, and neither is a shorter interval.
    - **A trailing pass's `delay` is when to look, not when to write.** It is
      queued behind a write that is still going and its sleep runs *alongside*
      that write, so by the time it holds the lock its wait is already spent.
      What the interval is still owed is settled under the lock, by
      `BoardRefresher.wait_out_interval`. It is the only place the bot
      sleeps before a request, and it is not the pacing ruled out below:
      nobody is waiting on
      a board that has not been drawn yet.
    - **The stamp goes in a `finally`.** A write that raised still spent its
      place in the bucket, and a window left open by the failure is one more
      request into a channel that is already unhappy.
  - **A refused write backs the game's window off, doubling per refusal in a
    row to `BOARD_REFRESH_BACKOFF_CEILING`, until one lands.** Every other
    lever here decides how many writes a turn asks for; this is the only one
    that says what to do when the answer turns out to be too many anyway --
    and without it there is no answer at all. A refused write deliberately
    does not record its digest, so the next refresh redraws the same board and
    asks again at the next window, and the next, for as long as the game goes
    on. **The fourth batch of warnings is that loop**: 61 refused uploads on
    one message, one request about every six seconds, every one of them
    refused, across three quarters of an hour and a restart in the middle.
    Nothing in the gate could have ended it.
    - **The budget in this section is a guess at somebody else's arithmetic,
      and that batch is the evidence it is wrong.** No five-in-five-seconds
      bucket refuses one request every six seconds for ninety seconds
      straight. Whatever the real rule is -- a window longer than the
      `retry_after` implies, a sub-limit the headers do not describe, a
      limiter that counts refusals -- the bot cannot read it, so it has to be
      able to *recover* from being wrong rather than only to avoid it.
      `discord.http` at DEBUG is what would settle it: it names the
      sub-ratelimit case outright, and `FOOLBOT_LOG_LEVEL=DEBUG` is enough to
      see it (console only -- the mirror's threshold is separate).
    - **One logical write is up to five requests, and that is not ours to
      change.** discord.py sleeps the `retry_after` and retries five times
      inside the single await this code makes, so a write that is being
      refused puts five uploads into the channel before the bot hears about
      it. `Client(max_ratelimit_timeout=...)` is the only dial and it is
      clamped to a 30-second floor, well above the ~5s these come back with,
      so it never fires. What the bot can decide is when to ask next.
    - **Only a 429 backs off.** A 404 or a dropped connection is a one-off and
      the next window is the right time to try again; a refusal is precisely
      the case where the next window is what is too soon. One write landing
      clears the count outright rather than stepping back down, because what
      the backoff was waiting for has happened.
    - **It is announced at WARNING**, which is most of the point: a run of
      `discord.http` 429s names a channel and a message and nothing else, and
      this is the line that ties one to a game without anybody having to look
      an id up. Console-only, like every other WARNING here.
  - **A write in flight does not stand in for a request that arrives during
    it.** The board it is putting up was drawn before that request, so the want
    is recorded in `wanted` and a pass that finds the flag set
    again when it lands waits out another interval and goes round once more.
    Counting the *task* instead dropped the request on the floor -- it was still
    in `tasks`, so nothing rescheduled, and the board kept a state
    the click had already moved past until somebody clicked again. Anything
    added to the gate has to keep the discard *before* the write, or the same
    hole reopens.
  - **A board identical to the one already up is not written at all.** The
    render is deterministic, so `BoardRefresher.write` keeps a digest of what
    it last uploaded and skips the upload when the new bytes match (a settling
    write still owes its link). Plenty of steps refresh without moving anything
    visible -- picking a receiver, choosing a maneuver -- and those were
    costing two of five for nothing. The
    digest is recorded only after the upload lands, so a rejected edit does
    not convince the next refresh its work is done, and it is in memory only:
    after a restart the first refresh always writes, because nothing records
    what is actually on the message.
  - It is a task, so `cog_unload` cancels it: a reload builds a new cog with
    its own games, and a task holding the old one would write from state
    nothing else can see.
  - **Fewer requests is not the same as slower requests, and this is the
    difference.** Nothing here sleeps before a call anyone is waiting on. The
    gate drops redundant work; the turn does not get slower for it.
    `BoardRefresher.wait_out_interval` is the one sleep before a request,
    and it is on the right side of that line: the board it is holding back has not been
    drawn yet, and every write it delays is one it is about to make
    unnecessary. A coach waits on prompts and on the messages a turn posts,
    and none of those go through this gate.
- **A followup after the click's own answer reads as a reply to it, and that
  is not what most of them are.** `interaction.followup.send` posts through
  the interaction's own webhook, and Discord's client shows that message
  quoting whatever the interaction answered before it -- right for the one
  message that genuinely *is* this click's answer, and a "replying to ..."
  strip of clutter above everything a cascade goes on to post once that
  answer has already been given. `send_new_prompt` in `cogs/d12ball_helpers.py`
  is the fix: it answers the interaction while it still has an answer to
  give, and falls back to a plain, unreferenced `channel.send` once it
  doesn't -- the same `is_done()` read `send_error_fallback` already makes,
  for the opposite reason (that one always answers ephemerally and only
  picks the route; this one changes the message itself, since a channel post
  can't be ephemeral). Every "new prompt or announcement" send that fires
  mid-cascade goes through it now -- `cogs/d12ball/turnovers.py`,
  `cogs/d12ball/effects.py`, `cogs/d12ball/presentation.py`,
  `cogs/d12ball/core.py`, `cogs/d12ball/periods.py`, and the non-ephemeral
  sends in `cogs/d12ball_views/turn.py`, `loose_ball.py`, `rolls.py`,
  `setup.py` and `shootout.py`: the Coaching Choice window opening or being
  reposted, the run-back and out-of-bounds-pickup announcements, the AI's
  own coaching summary, `resume_pending_prompt`'s fallback, every maneuver
  effect's own narration and follow-on prompt, the maneuver-pick and
  skill-test and score-attempt results, the coin toss and home/visiting
  choice, halftime, full time, and the whole extreme shootout -- since by
  the time any of them fires the interaction has already been acknowledged
  earlier in the same cascade (`drop_turn_prompt`'s own docstring says as
  much: "The caller must have acknowledged the interaction already"). An
  ephemeral reply (an error, a refusal, a coach's own pick coming back to
  them) is untouched and stays on `followup.send` -- ephemeral can only
  ever go out over the interaction, so there is no route for
  `send_new_prompt` to fall back to. What is deliberately not converted is
  `cogs/d12ball/slash_commands.py` and `cogs/debug.py`: a slash command's
  own followups are the direct answer to that command's interaction rather
  than a cascade riding on someone else's click, and Discord does not tie a
  slash-command followup to an origin message the way it ties a component
  interaction's -- there is no "replying to ..." strip for those to grow in
  the first place. This is the funnel to route a new mid-cascade send
  through when one turns up somewhere else, not a one-off worth repeating
  by hand.
- **Renders belong in a worker thread.** Everything that draws goes through
  `asyncio.to_thread`; Pillow is pure CPU and blocking the loop stalls the
  rate-limit sleeps and the gateway heartbeat along with everything else. The
  one exception is the maneuver reference image, built once in `D12Ball.__init__`
  before the bot is serving anything.
- **The command tree syncs only when it changed.** `setup_hook` runs on every
  process start, and registering global commands is heavily rate limited, so a
  day of testing used to re-upload an identical command list dozens of times.
  `command_tree_fingerprint` hashes the exact payload `tree.sync()` would send
  (not the command names -- an edited description is precisely the change that
  otherwise never arrives) and `botstate` remembers it. It is recorded only
  after a sync succeeds. When the fingerprint cannot be built at all the gate
  syncs, which is what it always did; `FOOLBOT_COMMAND_SYNC=always` forces it
  when Discord's copy has drifted some other way.
- **The application emoji are fetched once per startup.** `fetch_application_emojis`
  makes the call and the loaders (coins, conditions, teams, the d12) read the
  same answer. Two paths re-fetch so an upload takes without a restart, each at
  its own natural moment: `ensure_coin_emojis` on a coin toss (throttled to
  `EMOJI_REFETCH_INTERVAL` -- an application with none uploaded came up short on
  every toss, one HTTP request per flip), and `/d12ball setup_hub` for the d12.
- **Deleting a channel is the tightest limit there is** -- two per ten minutes
  -- so `/debug reset_channels` is slow by nature and backs off between
  retries (`CHANNEL_DELETE_RETRY_DELAYS`). What reaches that loop is not an
  ordinary 429, which discord.py handles; it is a failure discord.py gave up
  on, or a Cloudflare ban, and hammering either is how a rate limit becomes a
  ban. A long reset also outlives its 15-minute interaction token, so the
  summary it could not deliver goes to the console.

`data/bot_state.json` is where the two "already done this" facts live -- the
build already announced and the command tree already synced. It is untracked
runtime state like the saved games, and local to each machine, so two
developers deploying the same commit each announce it and each sync their own
tree.

One more `.env` variable, alongside the logging ones above:

| Variable | Default | What it does |
| --- | --- | --- |
| `FOOLBOT_COMMAND_SYNC` | off | `always` registers the commands even when the tree is unchanged |
| `FOOLBOT_D12BALL_ARCHIVE_EXPORT_DIR` | unset | Where `/debug export_archived_games` writes a game before deleting its channel; unset, that command refuses outright — see "Freeing up the PBD Archive" in [channels-and-archive.md](channels-and-archive.md) |

# fool-bot

A Discord bot for playing and testing Prophetic Fool prototypes. The active
prototype is **D12 Ball**, a board game whose state is rendered to a PNG and
posted into a Discord channel.

## Running it

```bash
pip install -r requirements.txt     # needs a .env with DISCORD_TOKEN
python3 foolbot.py
```

```bash
python3 -m unittest discover -s tests
```

## Where things live

| Path | What it is |
| --- | --- |
| `foolbot.py` | Bot entry point; generic deck/dice commands. Loads the cogs. |
| `botstate.py` | The little the bot remembers between runs, in `data/bot_state.json` |
| `botlog/` | Console logging setup, and the #logs channel mirror — see below |
| `cogs/d12ball.py` | All D12 Ball slash commands and Discord interaction flow |
| `cogs/d12ball_helpers.py` | Constants and free functions shared by the cog and its views — emoji lookups, player/team formatting, channel naming |
| `cogs/d12ball_views.py` | The `discord.ui.View` classes, one per prompt a player can be shown |
| `cogs/debug.py` | Maintenance commands, including the PBD channel-and-count reset |
| `d12ball/components.py` | Game state model — `MatchState`, `BoardState`, `TeamSetup`, `PlayerCatalog` |
| `d12ball/game.py` | `D12BallGame` (per-channel game record), `Team`, `GameMode`, `Formation` |
| `d12ball/render.py` | Board image rendering (Pillow) |
| `d12ball/data/` | `players.json`, `basic_rules.json` |
| `d12ball/images/` | Card art and emoji |
| `d12ball/fonts/` | Bundled DejaVu — see "Fonts" below |
| `gamesaves/d12ball/storage.py` | Persistence to `data/d12ball_games.json` |
| `scripts/` | CLI tools used repeatedly (not one-off scratch work) |
| `docs/` | The game rules, and how they got that way -- see below |

## The rules

**Read [docs/living-rules.md](docs/living-rules.md) before changing anything that models the
game.** It is the whole ruleset as it currently stands and the single thing to check a
mechanic against: it states each rule once, settled, with no history and no upstream
wording to reconcile.

The rules themselves live in two upstream places, neither complete on its own, plus a third
body that has only ever existed in the author's head:

- a [Notion page](https://propheticfools.notion.site/D12-Ball-6c9e1ea7ca61825391e881ec5fbfdca5)
  for the narrative rules. It is a JS app, so a plain fetch returns an empty shell -- render
  it in a browser to read it.
- a [Google Sheet](https://docs.google.com/spreadsheets/d/1PKPpTseisPmM-tH6PMLbtsrYsZ_zG8smluP5VmHKcMw)
  for component data. The share URL is not fetchable but `export?format=csv&gid=<gid>` is,
  which is how `scripts/import_d12ball_players.py` works.

**Every ability is imported twice**, in full and abbreviated -- `ability` and `ability_short` on
each role profile in `players.json`, from the `basic_abilities` sheet's own two columns. Text
that shows an ability on its own (the roster, the rules listing) uses the sentence;
anything captioning a portrait with it uses `RoleProfile.short_ability`, which falls back to
the sentence when there is no short form. **Don't shorten an ability in code.** Which half of a
two-part ability survives is a rules judgement, so the author makes it upstream and the import
carries it. Two quirks of that sheet are handled in the script and covered by
`tests/test_d12ball_player_import.py`: the column is spelled `Abbreivated` and stored with a
trailing space, and an abbreviation beginning `+3` is typed with a leading backtick so the
spreadsheet doesn't read it as a formula.

[docs/rules-log.md](docs/rules-log.md) is the other half: every rules change with its date and
where it came from, what is still unanswered, and what the answers unblock. Two parts of it
earn their keep when upstream moves:

- **Where upstream is behind** lists every point at which the living rules already differ from
  Notion or the sheet, so a fresh pull can tell old news from a real change.
- The **change log** is the running record. The rules are a live prototype and move: when they
  do, update the living rules and add a dated entry as its own commit, so each rules change
  stays a reviewable diff.

**Take rules questions to the author rather than inferring them from the code** -- several
mechanics exist only in the code, so there a bug and a deliberate decision look identical.
Asking as inline comments on a docs PR has worked far better than asking in chat, and it
leaves the answers versioned.

## Formations and occupancy

Basic mode has three shapes -- **2-2-2, 2-3-1 and 1-3-2**, read from a coach's
own goal forward, six cards either way. **Every team is dealt 2-2-2**, and a
coach changes shape only in a [Coaching Choice](#the-coaching-choice) -- of
which setup is now one, so a game need not kick off in the shape it was dealt.

**Stacking is board-dependent.** Three in midfield fits board 7 and board 9 one
card a space; only board 6, whose midfield has two spaces, makes 2-3-1 or 1-3-2
overfill a zone. So the occupancy machinery below is exercised on board 6 and
by `/coach`, not by the default board -- render a sample at `--board-size 6` to
see a stack.

- **The shapes live in two places on purpose.** `Formation` in `d12ball/game.py`
  names the three; the counts are in `basic_rules.json`, with the rest of the
  ruleset data. `load_basic_ruleset` checks the two agree, so neither can drift
  alone.
- **Occupancy is a coverage rule, not a limit** -- see "Occupancy" in the living
  rules. `MatchState.placement_spaces_in_zone` is the whole of it: a team's
  uncovered spaces in a zone, or every space once its other meeples cover them
  all. It discounts the meeple being moved, since the space it is leaving is
  about to be uncovered. **The run back is now its only caller.** A Coaching
  Choice satisfies coverage by construction instead of by checking (see
  `position_meeple`), which is why it can offer every space of a zone.
  `open_spaces_in_zone` still means "spaces this team has not covered" and is
  the input to `crowded_players`.
- **A formation change re-deals the whole side, and nothing else does.**
  `D12Ball.formation_placement` orders the six by defensive skill and
  `formation_space_order` gives each a space, working outward from the coach's
  own end; `MatchState.deploy_side` puts cards and meeples down together, so
  nothing partial ever reaches the match. A coach who wants a particular card
  somewhere particular moves it afterwards. This replaced an assignment keyed
  by *area* (`own_goal` / `midfield` / `opponent_goal`) that a coach filled one
  select at a time -- `zone_for_area` and `SETUP_AREAS` survive from it, and are
  still how a shape is read from a coach's own end.
- **Board 6's midfield is the only zone whose stack space is a judgement call.**
  A surplus goes on the middle space of a three-space zone, or the
  centre-nearer space of a two-space one -- except there, where the two spaces
  straddle the centre. `formation_stack_space` breaks that tie toward the
  coach's own goal, which is the author's call and the only stack the three
  basic shapes can produce.
- **A Low Pass into a stack asks who receives it.** Several teammates on one
  space is ordinary under a stacking shape, and the receiver is what a Winger's
  set-up hands the shot to, so `low_pass_receivers` lists them and
  `LowPassReceiverView` puts the choice to the passer. `low_pass_candidates`
  still names one player per destination -- that is a button label, not the
  receiver.

## The Coaching Choice

Setup, a new play's substitution window and halftime are **one flow offering
the same four actions** -- formation, substitution, zone assignment, space
positioning. See "Coaching Choice" in the living rules. They were three flows
offering overlapping subsets of those four; a coach should not have to learn
three menus to do one job.

- **`CoachingOccasion` carries every difference between the three**, as
  properties rather than as flags at the call sites: the substitution
  allowance, whether the declare-or-pass offer is put at all (and charged), and
  whether a player taken off is retired to the back bench. Anything that
  differs by occasion belongs on that enum, not in an `if` in the cog.
- **Three substitution budgets, not one.** Setup is unlimited, so
  `substitutions_remaining()` returns **None** there -- callers have to tell
  that apart from a limit of zero, which is what `may_substitute()` and
  `substitution_allowance_label` are for. A new play's come out of
  `half_substitutions_used`, per side, cleared at halftime; halftime's two are
  counted inside the window and charged to neither half. So a side can
  substitute six times in a game.
- **The declaration and the counter are separate gates.**
  `may_declare_coaching` is once a half and decides whether a side is *offered*
  a new play's window at all; the counter decides how many swaps they get in
  it. A side that spent both answering someone else's declaration can still
  declare later and get the rearrangement without the swaps.
- **The whole flow lives on one message.** Every step is an
  `interaction.response.edit_message`, and nothing in it ever sends another.
  That is the interaction-callback route, so unlike the board refresh it does
  not compete for the five-in-five bucket -- see "Discord's rate limits". It
  used to be a message per step, and a coach making two substitutions and a
  rearrangement put eight into the channel plus a board refresh apiece. One
  message also cannot go stale: every older prompt used to keep a live view, so
  a coach could scroll up and click a menu from three steps ago.
- **`CoachingView.show(..., moved=)` decides whether the image is re-sent.**
  Passing no `attachments` leaves the one already on the message alone, so only
  a step that actually moved something re-uploads. Opening a submenu does not.
- **A part-made pick lives on the view**, so a restart comes back to the hub.
  That costs almost nothing now: every action is one or two clicks, and a
  formation change is atomic.
- **Setup and halftime each have their own stage sequence** (`SETUP_STAGES`,
  `HALFTIME_STAGES`), and `finish_substitution_window` routes back into
  whichever is running instead of offering the other side a response. Both run
  **the side kicking off first** -- home at setup, the visitors at halftime.
- **The kickoff space is the only thing that can hold a coach in the flow.**
  `coaching_finish_refusal` refuses Done until the side kicking off the coming
  period has somebody on it. An AI has no menu to be held in, so
  `cover_kickoff_space` does the same job at the end of its window.
- **`LEGACY_HALFTIME_STAGES` is not dead weight.** Halftime used to run
  substitutions and any-zone repositioning as two stages a side; a game saved
  in either resumes at that side's hub. `from_dict` reads the old
  `pending_substitution_*` keys for the same reason. Both developers run the
  bot from their own tree against their own saves, so a half-finished game
  outlives the change that renamed things.

## The maneuver with nobody to challenge it

A maneuver normally needs two players. When the defending team has nobody in
the ball's zone there is no challenger, and the maneuver the offense picks
succeeds outright -- see "Maneuver" in the living rules. `MatchState`'s
`maneuver_uncontested` is the whole of it.

- **It stands in for `challenger_id` everywhere that flag means "a maneuver is
  under way".** `challenger_id` is what tells `validate()` that the handler is
  allowed to be off the ball mid-effect, and what tells `on_ready` which
  prompt to restore. An uncontested maneuver has no challenger and never will
  have a `defense_maneuver`, so both of those checks read
  `maneuver_uncontested` as well.
- **It is persisted, unlike `new_play`.** Nothing else in a saved state can
  tell "the defense has not picked yet" from "the defense is never going to
  pick", and a restart between the offense's pick and its effect has to know
  which. `reset_maneuver` clears it, along with everything else the turn set.
- **`maneuver_selections_complete` is the only "are we ready to resolve"
  test.** Two call sites used to check `offense_maneuver and defense_maneuver`
  directly and would have hung the turn; anything new should ask the property.
- **Both entry points go through the same branch** --
  `PlayerActionView.choose_action` for a human and `play_ai_turn` for the AI
  -- and both then use the ordinary maneuver prompt, so a coach reads the menu
  they always read. What is skipped is the challenger pick, the matchup image
  (it draws two players against each other), the reveal, and the skill test.

## Who wins a maneuver

**`D12Ball.settled_maneuver_winner` is the only answer to that**, and it
returns the winning maneuver's name or `None` when a skill test still has to
decide. Three call sites ask it and none of them may go back to reading
`maneuver_catalog.resolve()` on its own -- see "Injured players" in the living
rules for why the ranking is no longer the whole story.

- **Injury moves wins in both directions.** A decisive maneuver owed to an
  injured player is downgraded to a skill test they have to win, and a tie
  against exactly one injured participant is their automatic loss with nothing
  rolled. So the ranking alone both over- and under-reports a winner, which is
  why one predicate rather than a check at each site.
- **Two of the three callers are restarts.** `on_ready` uses it to decide
  whether the pending prompt is a `SkillTestView`, and `build_effect_choice_view`
  to decide whether an effect is pending at all. Both used to ask whether the
  ranking was a tie, which after a restart would have offered a skill test
  nobody owed, or an effect choice for a test that had not been rolled.
- **`resolve_maneuver` branches on it, and on `outcome` only for wording.**
  There are four ways a maneuver lands and each reads differently, but which
  one is a *win* is not decided there.
- **An uncontested maneuver wins whatever the offense picked, injured or
  not** -- no opponent to be disadvantaged against, no challenge to lose. Same
  for a tie where *both* participants are injured: it is an ordinary tie,
  because the disadvantage is measured against a healthy opponent. Both cases
  postdate the disadvantage rule and both are the author's, confirmed
  2026-08-09.
- **Injury separately withholds the skill modifier in a *contest*** -- a
  different thing this predicate has nothing to do with. It changes totals, not
  winners, and lives in `LooseBallSkillTestView.roll`, which covers both the
  loose ball and the long High Pass. An injured contestant rolls the bare d12:
  their offensive or defensive skill is left off, and **only** that. Ball speed
  and role abilities still apply, and a maneuver's skill test and a score
  attempt are untouched -- so the Midfielder's +3 and the Striker's +3 are both
  paid to an injured player. This was got backwards once, as the loss of a
  role's bonus; the name for it is "skill modifier".

## Where a shot may be taken from

A team may only shoot from within **shooting range** -- see "Score attempt" and
"Shooting range" in the living rules. `MatchState.can_attempt_score` is the
whole rule, over `BoardState.is_in_shooting_range`.

- **Shooting range is not a zone**, and is deliberately not called a half
  either. It is measured from the middle of the board and cuts across midfield,
  so it is the far part of midfield plus the goal zone a team attacks -- three
  spaces of seven on the standard board, which is why "half" was the wrong word
  for it. On an odd-sized board (7 and 9) the middle space is in *nobody's*
  range, which is why the geometry compares doubled indices against the last
  index rather than dividing. That space is also the kickoff space, so no
  restart ever begins in range.
- **A set-up's shot obeys it too.** A scoring opportunity sends a player into an
  ordinary score attempt, so what it buys is the shot out of turn, not a shot
  from anywhere. `set_up_shot_candidates` is `scoring_opportunity_candidates`
  plus the range check, and the two are separate because only some callers are
  asking about a shot -- a long High Pass asks the latter to find the receiver
  who has to contest for the ball, which has nothing to do with where the goal
  is.
- **A 2-space High Pass that lands short of range is still received.** The range
  rule takes away the shot, not the catch. The set-up branch and the long-pass
  contest are the same landing space asked two different questions, so a pass of
  2 that is refused a set-up has to resolve as an ordinary pass rather than fall
  through to a contest it has never had to win.
- **A Block Deflect that overshoots is the one set-up the rule cannot bite.** It
  puts the ball on the space closest to the offense's own goal, always deep in
  the deflecting team's range, so it asks `scoring_opportunity_candidates`
  directly -- a branch that can never be taken reads as if it could.
- **Nothing gates `begin_score_attempt` itself.** The rule is enforced where the
  shot is *chosen*: `PlayerActionView` omits the button (and `build_turn_prompt`
  says why), `choose_action` refuses a stale click, `DinkyAI` only ever shoots
  from the scoring space, and the set-ups ask `set_up_shot_candidates`.
- **The board image draws where range begins**, in `draw_shooting_range_edges`
  -- one dash column on board 6, two on 7 and 9 bracketing the space in nobody's
  range. The rule is positional and the board is where both coaches read
  position.

## Turnovers: steals and new plays

Every turnover resets the ball's speed and puts players back in position, but
*how* differs, and only one of the two opens a
[Coaching Choice](#the-coaching-choice).
`begin_run_back`'s `new_play` flag is the whole distinction -- see "Steals and
new plays" in the living rules for which is which.

- **A steal runs back; a new play resets.** A steal keeps the old behaviour --
  the stealer stays, everyone else displaced picks a space in their zone at a
  token a space. A new play calls `announce_new_play_reset`, which puts *both*
  sides back on the arrangement their coaches set, free of exhaustion, and
  then offers the window. That leaves nobody displaced, so the run back that
  follows finds nothing to do and falls through to whatever the restart still
  owes.
- **`new_play` is the exception, not the rule.** It defaults False, so a new
  path that turns the ball over is a steal unless it says otherwise. Exactly
  three call sites pass it: the score attempt (goal or miss), the conceded own
  goal, and the out-of-bounds loose ball. Anything that adds a way for
  possession to change has to decide which it is -- did the ball go dead, or
  did the other team take it off them?
- **It is deliberately not persisted**, unlike the `pending_run_back_*`
  fields. It is consumed inside `begin_run_back`, and by the time anything is
  saved the state already records which branch was taken: a window open, or a
  run back pending. A restart resumes from that, never from the flag.
- **A Block Deflect that overshoots is neither.** It flips possession and goes
  straight to the shot without calling `begin_run_back` at all; the goal or
  miss that follows is the new play.
- **A new play posts its board and pins it**, via `post_new_play_board` inside
  `announce_new_play_reset`. The reset is the arrangement the play starts from
  and the one point in a restart where nothing is still moving, so it is the
  board worth keeping -- what the restart still owes (a kickoff fill, an
  out-of-bounds pickup) lands on the persistent message afterwards. The other
  two pinned boards are the kickoff (the persistent message itself, pinned in
  `TeamSelectionView`) and the second-half restart in `finish_halftime`.
  Nothing else pins; see "Discord's rate limits".
- **`continue_run_back` is one loop, not a recursion, and it batches.** Every
  placement it makes without asking anyone -- the forced ones, the AI's
  choices, the drop back that fills an empty kickoff -- goes into a list, and
  that list is posted as a single message with a single board refresh when the
  cascade reaches a coach's choice or runs out. It used to send a message and
  re-upload the board per player, which after a steal that scatters a six-card
  side is a dozen-odd requests into one channel with nothing between them --
  see "Discord's rate limits". Anything added to the cascade should append to
  `notes` and `continue`, not send. `MAX_RUN_BACK_PASSES` bounds it: as a
  recursion the interpreter did that, and a loop that will not settle would
  hang the event loop for every game at once.

### The arrangement

`MatchState.assigned_positions` is `player_id -> [zone, space]`, persisted
with the rest of the match, and it is what a new play restores.

- **Only a deliberate placement sets it**, via `set_assigned_positions`: the
  standard deal, and the close of any [Coaching Choice](#the-coaching-choice) a
  side actually took up. A run back must never write to it -- the scramble a
  steal forces is not a shape a coach chose, and the whole point is that the
  next new play undoes it.
- **A player with no entry is left where they stand.** That is how a game
  saved before this field existed keeps working: `restore_assigned_positions`
  moves nobody, the ordinary run back still finds them displaced, and the
  side's next window sets a real arrangement.
- **Restoring never charges exhaustion**, so it goes through
  `board.place_meeple` rather than `run_back_player`, and it skips the
  occupancy check on purpose -- the end state is a whole arrangement that was
  valid when it was saved, even though restoring it one meeple at a time
  passes through states that are not.
- **The two placements a restart owes still cost**: the post-goal kickoff fill
  and the out-of-bounds pickup run after the reset, at the usual rate, because
  nothing guarantees a coach's arrangement covers the space in question.

## Logging and the #logs channel

**Use `logging`, not `print`.** Every module gets its own logger
(`LOGGER = logging.getLogger(__name__)`) and `botlog.configure_logging()`
in `foolbot.py` sets the root logger up once, before anything logs. That is
also why `bot.run` is called with `log_handler=None`: discord.py otherwise
configures its own logger inside `run`, and with a root handler already
attached every library line would print twice.

Records at ERROR and above are mirrored into a Discord channel, so a crash
shows up in the server instead of only on the console of whoever is hosting
the bot. The bot finds or creates a channel called `#logs` on startup, posts
the record with its traceback in a code fence, and posts a one-line notice
naming the build it is running whenever that build changes.

Everything is optional and lives in `.env` next to `DISCORD_TOKEN`:

| Variable | Default | What it does |
| --- | --- | --- |
| `FOOLBOT_LOG_LEVEL` | `INFO` | Console threshold |
| `FOOLBOT_LOG_CHANNEL_LEVEL` | `ERROR` | Discord threshold; `off` disables the mirror |
| `FOOLBOT_LOG_CHANNEL_ID` | — | Mirror into exactly this channel |
| `FOOLBOT_LOG_CHANNEL_NAME` | `logs` | Channel to find or create, when no id is set |
| `FOOLBOT_LOG_GUILD_ID` | first server | Which server hosts the channel |
| `FOOLBOT_DEPLOY_NOTICE` | on | `off` stops the "now running this build" notice |
| `FOOLBOT_HOST_NAME` | machine name | What the deploy notice calls this host |

Three things to know before changing any of it:

- **The level you log at decides who sees it.** ERROR reaches the server;
  WARNING and INFO are console-only. So an error means "someone needs to
  fix this", not "something unexpected happened" — a missing application
  emoji is an INFO, a game whose channel the bot is not allowed to move is
  an ERROR. The test is whether anyone can act on it: a finished game whose
  channel was deleted, or whose server the bot has left, is an INFO however
  much it looks like a failure, because there is nothing to fix and the
  startup sweep would repeat it on every reconnect.
- **The sink must never log its own failures.** A failed send that logged
  would hand itself the record it just failed to send. `botlog/handler.py`
  prints those to stderr, deliberately.
- **The build notice is keyed on the commit sha**, remembered in the
  untracked `data/bot_state.json`. `on_ready` fires again on every gateway
  reconnect and either of us restarts the bot constantly while testing;
  keying on the commit is what keeps that from being a stream of identical
  "restarted" posts. It reads HEAD out of the checkout with `git log`, so
  the notice is only as accurate as the deployed tree — and degrades to
  saying nothing at all if git is not on PATH.
- **The notices are one stream per machine, not one per repository.** That
  state file is local, so when we both deploy into the same `#logs` the
  posts interleave: the same commit gets announced once by each host, and
  neither stream is the repository's history. Each notice names its host so
  they can be told apart. Don't read the channel as a changelog.
- **A merge is listed only when it resolved a conflict.** A clean merge
  repeats commits the notice already lists, so it is dropped and its pull
  request named in the heading instead; a conflict resolution exists in the
  merge commit and nowhere else, so dropping it would drop work. The test
  for which is an empty combined diff — `--name-only` and `--stat` both
  report a clean merge of two branches that touched one file as if it
  carried changes, so `merges_with_content` reads the patch.

The channel is created with whatever permissions the server's defaults give
it. Tracebacks name game ids, channel names and command arguments, so lock
the channel down server-side if that matters.

## Discord's rate limits

The bot was getting rate limited mid-game, and the cause was not one call
site: it was that a single click fanned out into ten or twenty requests into
one channel with nothing between them. **The fix for that is always fewer
requests, never slower ones.** discord.py already sleeps and retries on a 429
(the `We are being rate limited... Retrying in N seconds` line is its, at
WARNING, so it is console-only and never reaches #logs); adding our own
pacing on top would only make a turn take ten seconds and still spend the
same budget. So:

- **Batch what the bot does on its own, and only interrupt for a person.** A
  cascade of automatic steps is one message and one board refresh at the end
  of it, not one of each per step -- see `continue_run_back`. Nobody reads the
  intermediate boards; the one worth looking at is the one where everything
  has finished moving.
- **Render the board once per state, not once per upload.** `render_match_png`
  returns bytes and `match_file_from_png` wraps them, because uploading a
  `discord.File` consumes the stream inside it. The end of a maneuver puts the
  same board in two places (the persistent message and the snapshot under the
  result) and so does `announce_board_update`; both draw it once and upload it
  twice. `refresh_match_image` takes a `png=` for exactly this, and so does
  `post_new_play_board`.
- **Only new-play boards are pinned.** A pin is a request of its own *and* a
  "pinned a message" system post in the channel, so `pin_board_message` is
  called from three places and no more: the kickoff board, the second-half
  board, and `post_new_play_board`. Pinning every board a turn puts out would
  roughly double the channel's traffic and fill the 50-pin cap inside a game.
  At the cap the pin fails with error 30003 and the helper unpins the oldest
  board *it* pinned -- read off `channel.pins(oldest_first=True)` and matched
  by the `d12ball-pbd` filename -- so a pin somebody else put there is never
  displaced, and a channel with no board to roll off simply leaves the new one
  unpinned. Every failure is swallowed: a missing pin is worth less than the
  turn it would take down with it.
- **A board refresh is two requests, and that is unavoidable.** Editing the
  message uploads a new attachment, which invalidates the old one, so the
  "View full image" link has to be re-cut in a second edit -- the URL does not
  exist until the upload lands. Budget for two, and prefer not refreshing at
  all over refreshing twice.
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
    `channel.get_partial_message(...).edit()` does, and there are two of
    those: the board refresh and `refresh_maneuver_prompt`.
  - **A board refresh spends two of the five** (the attachment, then the link
    button), so `refresh_match_image` is rate-gated per game: the first goes
    out at once and any that arrive within `BOARD_REFRESH_INTERVAL` collapse
    into **one** trailing refresh rather than queueing.
  - **`BOARD_REFRESH_INTERVAL` must stay above Discord's five-second window**,
    or two refreshes fall inside one window and, with the prompt edit that
    shares the bucket, a single turn spends exactly five -- measured, and
    exactly what was still earning 429s at three seconds. Six leaves the turn
    at three. Adding a call site is free; shortening the interval is not.
  - A trailing refresh **draws when it runs**, never from a `png=` handed to it
    earlier -- the board it was offered is stale by the time it fires, and
    re-drawing is exactly what lets one pending refresh stand in for every
    request behind it.
  - **A board identical to the one already up is not written at all.** The
    render is deterministic, so `write_board_message` keeps a digest of what
    it last uploaded and skips both edits when the new bytes match. Plenty of
    steps refresh without moving anything visible -- picking a receiver,
    choosing a maneuver -- and those were costing two of five for nothing. The
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
  makes the call and the three loaders read the same answer. `ensure_coin_emojis`
  still retries so an upload takes effect without a restart, but no more often
  than `EMOJI_REFETCH_INTERVAL` -- an application with none of them uploaded
  comes up short on every toss, and the retry was an HTTP request per flip.
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

## Working on the board image

The board image is the bot's main output, so look at it. Don't rely on the
test suite to tell you a rendering change is right — it only asserts the
output is a PNG of the expected dimensions.

```bash
python3 scripts/render_sample.py --home purple --visiting teal --out board.png
python3 scripts/render_sample.py --home-formation 2-3-1 --board-size 6  # stacked meeples
python3 scripts/render_sample.py --coaching home       # a coach's own half
python3 scripts/render_sample.py --list-games
python3 scripts/render_sample.py --game <game_id>      # reproduce a real board
```

`--game` renders a real saved game from your own `data/d12ball_games.json`,
which is how to reproduce a board someone reported a problem with rather than
guessing at the state. Saved games are local to each machine, so a fresh clone
lists none until the bot has been run.

**There are two board images, and they are drawn to different widths.**
`render_match_image` is the 2200px one everybody sees;
`render_coaching_image` is the 1280px half-field a
[Coaching Choice](#the-coaching-choice) keeps up, and the two do not share a
layout. The coaching image carries one row of meeples instead of two, so at the
match image's width it arrives in Discord as an unreadable sliver -- but its
width still has to fit a stack, and board 6's two-space midfield under 2-3-1 is
the widest case there is. **It is deliberately not mirrored for the visiting
coach**: the zones keep their real names and the spaces their real numbers, so
V1 is the same space on both images and on the board the coaches are looking
at.

### Fonts

Fonts are bundled in `d12ball/fonts/` and loaded by absolute path. **Do not go
back to looking them up by bare filename.** `ImageFont.truetype("Arial.ttf")`
searches the host's font directories, and the same typeface is filed under a
different name on macOS, Windows and Linux, so no list of bare names works
everywhere. When every name misses, Pillow's `load_default()` returns a face
pinned to size 10 that ignores the requested size, and every label on the
board silently collapses to tiny text. That was a real bug; the tests in
`D12BallFontTests` exist to keep it from coming back.

`render.py` builds its font objects at **import time**, so a running bot keeps
whatever it resolved at startup. Restart after any render change.

## Game channels

Every game gets its own private channel, named by `build_game_channel_name` in
`cogs/d12ball_helpers.py`: `d12ball-pbd<number>`, then the game's name if
`/d12ball create_game` was given one (`game_name`, carried on the game record
and reused by the rematch button), or the two sides otherwise —
`d12ball-pbd12-the-cup-final`, `d12ball-pbd12-username-vs-dinky-ai`.

- **The number stays immediately after the `d12ball-pbd` prefix.** It is the
  only part read back off a channel, by `CHANNEL_NAME_PATTERN`, and the suffix
  in that pattern is optional so channels created before names existed still
  match. Anything that changes the shape of the name has to keep both true.
- **Names are slugged, not passed through.** Discord lowercases a channel name
  and rewrites spaces itself, so `slugify_channel_part` does it first and the
  saved name matches what the server shows. Punctuation is dropped, letters
  outside ASCII are kept (they are legal, and a wholly non-Latin display name
  would otherwise slug to nothing), and the whole name is cut to Discord's
  100-character limit without ending on a dash.
- **Archiving moves the channel between categories and never renames it**, so
  a game's channel keeps the name it was created with for the rest of its life.
  Nothing renames a channel when a player's display name changes.

## Gotchas

- **`data/d12ball_games.json` is runtime state and is deliberately untracked.**
  The bot rewrites it on every game action. It used to be committed, which
  meant it showed as modified more or less permanently and was a standing
  source of merge conflicts. Don't re-add it. Each developer's saved games are
  local to their own machine, and `data/` is created at startup if missing.
- **Startup drops finished games whose channel was deleted.** The archiving
  sweep in `on_ready` prunes a finished game when Discord answers its channel
  lookup with a 404, because there is nothing left to archive and the record
  would report the same failure on every reconnect. Two edges are deliberate:
  a game whose *guild* is missing is only skipped, since a Discord outage
  looks identical and the games would be gone for good; and only the channel
  lookup counts, so a 404 from the category or the move is an error and keeps
  the game. Deleting a channel by hand now also deletes the game record, and
  since `get_next_game_number` is `max + 1` over the guild's saved games,
  pruning the newest ones lets a PBD number be handed out twice.
- **Meeple name labels are sized per space, not once for the board.**
  `fit_meeple_labels` in `render.py` picks the largest size whose names all fit
  the space's width and whose lines fit between the tokens and the edge of the
  space, and `shorten_to_width` truncates anything still too wide. That replaced
  a fixed `FONT_MEEPLE` and a fixed 23px line offset, which overflowed the space
  borders whenever two meeples shared a space -- unavoidable once a formation
  can put four of a team's meeples on one.
- **The "View full image" button dies after 24 hours, by design.** Discord
  signs attachment URLs and stops honouring a signature a day after issuing it,
  so the link baked into a board or maneuver-reference message goes dead once
  the message sits untouched that long. The next board update re-cuts it. This
  is an accepted trade for a one-tap link; the alternative was a callback
  button that fetches a fresh URL on click at the cost of an extra tap. See
  `add_full_image_button` in `cogs/d12ball.py`.

## Collaboration

Two people develop on this repo in parallel, on different machines and
different operating systems.

- **Never force-push a branch that has been pushed.** The other developer may
  have it checked out and be testing against it.
- Feature branches are short-lived and land on `main` via a pull request. Don't
  set up long-lived tracking branches for code that is only being tested.
- To test someone else's branch without creating a local branch:
  ```bash
  git fetch origin <branch>
  git checkout --detach FETCH_HEAD
  # ... test ...
  git checkout main
  ```
- Assume either developer may be running the bot from the working tree at any
  time. Stop the bot before switching branches, and restart it after.

## Notes for Claude

- **Keep this file current with the code.** When a change alters the
  architecture or the structure — a new module or cog, a responsibility moving
  between them, a new persisted field on a game record, a change to how
  channels are named or state is stored, a new environment variable — update
  the relevant section here in the same commit, unless it already says so.
  Add the reasoning, not just the fact: this file exists to explain the
  decisions the code cannot. Leave it alone for ordinary changes that fit the
  structure already described.
- **Don't commit one-off diagnostic scripts.** If something is scaffolding for
  a single investigation, hand it over as a file instead. `scripts/` is for
  tools worth running more than once.
- **Verify git and environment behaviour before asserting it.** This repo has
  enough quirks (a tracked file that is rewritten at runtime, fonts resolved
  at import) that reasoning from first principles produces confident wrong
  answers. Reproducing takes a minute and is usually decisive.
- The two developers run on different operating systems. Before concluding
  "it works here but not there", establish what actually differs between the
  hosts rather than assuming a deployment or staleness problem.

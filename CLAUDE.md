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
| `d12ball/cards.py` | The six maneuvers as cards — the printed face and the hand the bot shows |
| `d12ball/boards.py` | The field, jumbotron and team boards, print-ready for the tabletop game |
| `d12ball/rules_doc.py` | Reads `docs/living-rules.md` for the two rules commands |
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

### Serving the rules in Discord

`/d12ball rules_full` posts the living rules in a thread and `/d12ball rules_search`
posts one section of them. Both read `docs/living-rules.md` itself, through
`d12ball/rules_doc.py` -- **there is no second copy of the rules text in the bot**, so a
rules change reaches the commands in the commit that makes it, and cannot be half-applied.

- **The parse is cached against the file's timestamp**, so an edited ruleset is served
  without restarting the bot -- the opposite of the fonts, which are resolved at import
  (see "Fonts"). It is re-read on every autocomplete keystroke otherwise.
- **A section carries its subsections.** Asking about "Maneuver" means the four steps as
  well, so `RulesSection.text` is the whole subtree; `label` is the heading path
  (`Maneuver › 3. Who wins`) and `slug` is GitHub's own anchor, which is what the
  document's internal links already use.
- **The autocomplete searches the body as well as the headings**, because a coach knows
  the rule and not what it is filed under -- "scissors" has to find "3. Who wins". Headings
  match first, then bodies, deepest first, since the subsection is the more specific answer
  to the same question.
- **A coach can submit text that was never offered**, so `best_match` is what the command
  asks rather than `find`. It answers when the words can only mean one thing: they name a
  heading, or every section mentioning them is on one branch -- a subsection and the parents
  carrying its text, which are the same rule read at different depths. Anything wider comes
  back as a list of headings, because it is a choice and not an answer.
- **Discord renders neither anchors nor tables.** `[text](#anchor)` shows as its raw
  brackets, so `for_discord` drops the syntax and keeps the words; tables are left alone,
  because the alternative is restating the rules in a second form and that is exactly what
  this avoids.
- **`chunk_for_discord` breaks at blank lines and starts a message at every `##`.** A chunk
  boundary is a visible seam in the channel, and a heading is where a seam belongs; a table
  split down the middle renders as neither a table nor prose.
- **The full rules are around forty messages, which is why they go in a thread.** A thread
  has its own channel id, so those sends are a rate-limit bucket of their own rather than
  the game channel's -- see "Discord's rate limits". Run inside a thread already, the
  command posts there instead, since threads do not nest.

## Formations and occupancy

Basic mode has five shapes -- **2-2-2, 2-3-1 and 1-3-2** on every board, plus
**3-2-1 and 1-2-3** on the nine-space board -- read from a coach's own goal
forward, six cards either way. **Every team is dealt 2-2-2**, and a coach
changes shape only in a [Coaching Choice](#the-coaching-choice) -- of which
setup is now one, so a game need not kick off in the shape it was dealt.

**Which board plays which shape is data, not geometry.** `board_sizes` on a
shape in `basic_rules.json` lists the boards it may be picked on, and leaving
it out means every board. It is not "a shape that would stack is refused":
2-3-1 and 1-3-2 overfill board 6's midfield and are played there anyway. 3-2-1
and 1-2-3 need a goal zone three deep, and being board 9's alone is the
author's call (2026-08-12 in the rules log). `BasicRuleset.formations_for_board`
is the only reading of it -- `D12Ball.available_formations` for a match, which
is what the Formation menu builds from and what `current_formation` names a
side's shape out of -- and `BasicRuleset.formation_shape` is the matching
refusal, so a shape offered in one place cannot be refused in another.
**A formation is named by its counts**, which `load_basic_ruleset` checks; that
is what lets the printed team board list the names and nothing else.

**Stacking is board-dependent.** Three in midfield fits board 7 and board 9 one
card a space; only board 6, whose midfield has two spaces, makes 2-3-1 or 1-3-2
overfill a zone. Board 9's two shapes stack nowhere -- its zones are three
spaces deep and neither puts more than three cards in one. So the occupancy
machinery below is exercised on board 6 and by `/coach`, not by the default
board -- render a sample at `--board-size 6` to see a stack.

**The deal spreads a goal zone's pair and packs midfield**, which is
`setup_space_order` and only ever visible on board 9 -- the one board whose
zones are deeper than 2-2-2 fills them. A goal zone's two cards take its two
end spaces and midfield clumps toward that side's own goal, so home deals H1,
H3, M1, M2, V1, V3 (see "Setup" in the living rules, and the 2026-08-12 entry
in the rules log). The clumped half is not an oversight: the kickoff space is
in midfield and the side kicking off has to be standing on one, so spreading
two cards over a three-space midfield would empty the middle and hold the coach
in the setup window (`coaching_finish_refusal`). That is why the function takes
the zone. **This is the standard deal only**; a formation change re-deals through
`formation_space_order`, which packs and then stacks.

- **The shapes live in two places on purpose.** `Formation` in `d12ball/game.py`
  names them; the counts and the boards they are played on are in
  `basic_rules.json`, with the rest of the ruleset data. `load_basic_ruleset`
  checks the two agree, so neither can drift alone.
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

A fourth occasion joined them: the window between full time and the
[extreme shootout](#the-extreme-shootout). It is the same flow, with **one
substitution and none of the other three actions** -- a shootout is played by
who is on the field and by nothing about where they stand, so formation, zone
assignment and space positioning would move meeples that never play again.

A fifth is [a ceded ball](#ceding-the-ball), which is a new play's window in
everything but how it was bought.

- **`CoachingOccasion` carries every difference between the five**, as
  properties rather than as flags at the call sites: the substitution
  allowance, whether the declare-or-pass offer is put at all, whether the
  declaration is charged, whether a player taken off is retired to the back
  bench, and whether the three positional actions are offered at all. Anything
  that differs by occasion belongs on that enum, not in an `if` in the cog.
- **`spends_declaration` and `asks_declaration` are two facts, not one.** They
  agreed for the first four occasions and part company at `CEDED`, which is
  charged the once-a-half without ever being offered -- the button that gave
  the ball up *was* the declaration. `open_coaching_window` reads the second
  (open declared, however that came about) and `declare_coaching` the first
  (charge, unless this is a reply), which is why an occasion given for free
  and one paid for in advance can share the same code path.
- **`offers_positioning` governs the arrangement as well as the menu**, which
  is one fact read at both ends: a window with no positioning in it neither
  opens on the coach's arrangement (`begin_substitution_window` skips the
  restore) nor records one (`finish_substitution_window` skips
  `set_assigned_positions`). Restoring at full time would rearrange the last
  board of the game, and recording would overwrite an arrangement nothing will
  ever read. `CoachingHubView` simply does not build the three buttons, rather
  than building them disabled -- there is nothing a coach could do to enable
  them.
- **Four substitution budgets, not one.** Setup is unlimited, so
  `substitutions_remaining()` returns **None** there -- callers have to tell
  that apart from a limit of zero, which is what `may_substitute()` and
  `substitution_allowance_label` are for. Open play's -- a new play's or a
  ceded ball's, which draw on the same pot -- come out of
  `half_substitutions_used`, per side, cleared at halftime; halftime's two and
  full time's one are counted inside the window and charged to neither half.
  So a side can substitute seven times in a game.
- **Who may come on is one question, not six.** `MatchState.substitution_pool`
  takes a side and nothing else: the bench while anyone is sitting on it, the
  back bench once it has drained, minus anyone injured. It used to take the
  outgoing player, because the back bench was thought to open only for an
  injured swap -- **it does not**, and that reading left a side with three
  swaps behind them and a healthy six unable to substitute at all. See
  "Who may come on" in the living rules, and the 2026-08-10 correction in the
  rules log. Don't reintroduce the parameter: the answer is the same for all
  six, and a caller passing one is asking a question the rules do not ask.
  - The one state with nobody to bring on is **both benches spent**: three
    substitutions to drain the bench, and every one of the three who came off
    injured, since injury is the only thing that takes a card out of a pool.
    That is what the full-time window skips on and what disables the hub's
    Substitution button.
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
- **What the coach *did*, though, lives on the match**, because the one message
  is also the thing that destroys it: each step's note is written over by the
  next, so "so-and-so comes on for so-and-so" is gone by the time the coach
  clicks Done. `pending_coaching_formation` (the shape at the open) and
  `pending_coaching_swaps` are what survive it, and `coaching_summary` reads
  them into the message the window closes with. Both are persisted, so a window
  resumed after a restart still closes with what was done before it, and both
  are cleared by `close_coaching_window` -- so the summary has to be built
  *before* the window is closed.
  - **Only the shape and the swaps.** Zone assignment and space positioning are
    on the board, and the board goes up the moment coaching ends. Reporting the
    shape as a change (`2-2-2 → 2-3-1`) rather than as a state is why the
    opening shape is recorded at all: a coach who changes shape and changes back
    did nothing.
- **A window opens on the arrangement its coach last settled**, restored by
  `begin_substitution_window` before anything else -- never on the scramble a
  run back left. A new play resets both sides before offering the window and
  setup runs on a fresh deal, so this only ever moves anybody at halftime, and
  the board refresh it asks for is conditional on having moved somebody. It is
  the guarantee for every occasion rather than a halftime step because the
  half-field a coach works from should show their own shape whatever brought
  them there. `repost_coaching_prompt` deliberately does *not* restore: that is
  a resume, and the window's own moves have already happened.
- **Setup, halftime and full time each have their own stage sequence**
  (`SETUP_STAGES`, `HALFTIME_STAGES`, `FULL_TIME_STAGES`), and
  `finish_substitution_window` routes back into whichever is running instead of
  offering the other side a response. The first two run **the side kicking off
  first** -- home at setup, the visitors at halftime. Nobody kicks anything off
  at full time, so home going first there is the author's call and not the
  position's.
- **A full-time window with nothing in it is skipped, silently.** Its only
  action is the substitution, so a side with an empty `substitution_pool` would
  get a Done button with extra steps. Halftime's extra-token stage skips the
  same way for the same reason. Every other occasion has three more actions to
  fall back on, so none of them skips. It is a genuinely rare state -- see
  "Who may come on is one question, not six" above.
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

A maneuver normally needs two players. When the defense has no challenger the
maneuver the offense picks succeeds outright -- see "Maneuvers" in the living
rules. `MatchState`'s `maneuver_uncontested` is the whole of it.

**There are two ways to have no challenger and they are deliberately one
state.** The defense has nobody in the ball's zone, or it has somebody and
**sends nobody**: walking in costs 1 token per space, and since 2026-08-12
paying it is a choice. `begin_uncontested_maneuver` is the only way in either
way, so nothing downstream has to know which happened.

- **Exhaustion is where the line is drawn**, which is why the choice is not
  offered to everybody. A defender already standing on the ball pays nothing
  to challenge, so there is nothing to weigh and nothing to refuse: they
  challenge automatically, as they always did. `automatic_challengers` is that
  reading -- it is what the two offense branches use to skip the prompt and
  what `begin_uncontested_maneuver` refuses on -- and `may_decline_challenge`
  is the same fact from the defense's end, asked by `ManeuverChallengeView`
  before it builds the Send nobody button. The view is normally only built
  where the choice is real; a restart can re-attach it to a prompt saved
  before a defender walked onto the ball, which is the state that check is for.
- **Which way it happened is read off the zone, never stored.** Anybody still
  eligible to challenge means the defense was offered the challenge and passed,
  since a defense with nobody there is never asked. `announce_uncontested_maneuver`
  and the "no defensive maneuver to pick" reply both word themselves from that,
  so nothing has to be persisted to word a message after a restart.
- **Dinky never declines.** `choose_challenger` still returns a player, so in a
  solo game keeping somebody back is the human's option alone -- the same call
  as never ceding and never leaving a loose ball uncontested.
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
- **Three entry points go through the same branch** --
  `PlayerActionView.choose_action` for a human offense, `play_ai_turn` for the
  AI, and `ManeuverChallengeView.decline` for a defense that sends nobody --
  and all of them then use the ordinary maneuver prompt, so a coach reads the
  menu they always read. What is skipped is the challenger pick, the matchup
  image (it draws two players against each other), the reveal, and the skill
  test. A decline moves nobody and charges nobody, so it is also the one of
  the three that asks for no board refresh.

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

## Every roll is a coach's

**Nothing rolls dice on its own.** A skill test, a score attempt, a loose ball,
an own goal and an injury test all wait behind a button, and any coach in the
game may press it -- one roll by one player is still their roll to throw, and
letting either side press it is what keeps a solo game moving when the risk is
the AI's. The two that were not always like this were the one-sided ones: the
own goal and the injury test had no opposing roll to wait for, so the bot rolled
them itself and posted the answer.

Both are now places a turn can **stop**, and that is the whole cost of it:

- **What the roll was going to do next has to outlive the wait.** An own goal
  carries `pending_own_goal_distance`, the clock cost of the maneuver that
  risked it, which the roll spends whichever way it goes. Injury tests carry
  `pending_injury_resume`, which is the contest's continuation -- a maneuver's
  skill test resumes into its winner's effect, a loose ball (or the long High
  Pass borrowing its machinery) into its run back, with the two arguments that
  run back needs, and a shootout skill test into the next one. Neither is
  derivable after the fact: `settled_maneuver_winner`
  answers None while a test is owed, and the contest that knew the distance has
  already cleared itself. Both are persisted, and `reset_maneuver` clears them
  with everything else the turn set.
- **`pending_injury_tests` is a queue, and `continue_injury_tests` is its only
  exit.** A contest can owe two tests; they are asked one at a time and the
  continuation fires when the last one is answered. A test that turns out not to
  be owed -- the player is already injured -- leaves by the same door rather
  than returning, so this can never be where a turn stops for good. **Nothing is
  written when nothing is owed**: `begin_injury_tests` goes straight to the
  continuation, which is the common case and the one that has to stay free.
- **Both are checked ahead of everything else in `pending_turn_view`**, because
  both interrupt a turn whose own state is still set underneath them -- a skill
  test comes back with its challenger and both maneuvers in place, an own goal
  with the Pressure that risked it still live, and either would otherwise be
  answered by the maneuver branches.
- **The player is in the injury button's custom_id as well as in the queue**, so
  a coach who scrolls back to the first of two prompts cannot roll the second
  player's test with it.

## The extreme shootout

**Every game is settled.** A level score at full time opens the shootout -- see
"Extreme shootout" in the living rules -- and there is no setting for it: league
mode and the `tie_mode` field went with it, so `end_period` branches on the
score alone. A saved game still carrying `tie_mode` loads without it rather than
being skipped, which is what the retired-field filter in
`gamesaves/d12ball/storage.py` is for; nothing writes the key any more, so it
dies out on its own.

- **A level score opens a Coaching Choice first, not the shootout.**
  `end_period` hands off to `begin_full_time_coaching`, one substitution to
  each coach, and `finish_full_time_coaching` is the only caller of
  `begin_shootout` -- so **the six who shoot are the six on the field when the
  shooting starts**, which is after that window and not at the whistle.
  `pending_full_time_stage` and `pending_shootout` are therefore never both
  set, and `pending_turn_view` reads the first ahead of everything a turn
  leaves behind, exactly as it does for setup and halftime.

- **`D12Ball.advance_shootout` is the only reading of "what is this shootout
  waiting on?"**, and `pending_turn_view` answers the same three questions in
  the same order. Two of the four steps are the bot's own -- the reveal, and
  setting the next test up -- so a restart between them has no button anywhere,
  which is why `resume_pending_prompt` hands a shootout back to
  `advance_shootout` rather than posting a view. Same shape as the run back and
  the halftime sequence, and the same reason.
- **The first round records no shooter.** `shootout_shooter` reads it off the
  coach's order and the count of who has been out, so the reveal has no state of
  its own to lose. Sudden death has no order to read, so there it is exactly
  what the coach picked -- and that is the only case
  `shootout_shooters_complete` can be false in.
- **The roll retires its own shooters**, in the same save as the goal
  (`finish_shootout_test`). That is what stops a restart between the roll and the
  injury tests re-rolling a test already paid for, and it is why
  `continue_shootout` may not call it again: round 1 derives its shooter, so a
  second call would quietly retire the next pair as well.
- **A part-built order lives on the match, not on the view.** Both menus are
  ephemeral for the same reason the maneuver pick is -- neither coach may see the
  other's -- so a restart cannot re-attach to them and
  `restore_shootout_menus` re-registers them message-agnostically, exactly as
  `restore_maneuver_menus` does. A view rebuilt that way starts empty, so a coach
  who had ordered five would come back to none if the order lived there.
- **`shootout_winner` is the whole of "is it over?"**, both rounds in one
  predicate: in round 1 a lead bigger than the tests still to come (which it
  counts by asking who is left, hence the retirement above), and in sudden death
  any lead at all, since that round started level by construction.
- **A shootout goal is a goal**, so `award_shootout_goal` writes the scoreboard
  *and* a separate tally. The tally is not the score: it is what the "cannot be
  caught" stop counts and what `shootout_score_line` reads for the summary,
  because 6:5 says nothing about how the game was won.
- **`shootout_heading` is only ever a question.** It names the test about to be
  rolled, and by the time a result is posted the shooters have been retired and
  that number has moved on -- so a result carries `shootout_running_score`
  instead.
- **"Your Order" is on the roll prompt**, not on the order prompt, because the
  order prompt is deleted the moment both sides have set theirs and the roll
  prompt is what a coach is looking at for the rest of the shootout. A coach may
  look at their own order whenever they like -- they just may not reorder it --
  so it answers ephemerally, and in sudden death, which has no order, it lists
  who they have left this round.
- **A shootout test costs no exhaustion and still owes injury checks**, which is
  the author's ruling and not a shortcut: it is not one of the ways to gain a
  token, but an Exhausted participant rolls a check like any other skill test.
  It goes through `begin_injury_tests` with a resume of its own, so the queue is
  the same one every contest uses.

## Where a shot may be taken from

A team may only shoot from within **shooting range** -- see "Score attempt" and
"Field, direction, and shooting range" in the living rules.
`MatchState.can_attempt_score` is the
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
- **An overshoot is the set-up the rule cannot bite**, whichever maneuver made
  it. A Block Deflect's puts the ball on the space closest to the offense's own
  goal and a High Pass's on the space closest to the goal they attack; both are
  as deep into the shooting team's range as the field goes. So both ask
  `scoring_opportunity_candidates` directly rather than `set_up_shot_candidates`
  -- a branch that can never be taken reads as if it could.
- **Nothing gates `begin_score_attempt` itself.** The rule is enforced where the
  shot is *chosen*: `PlayerActionView` omits the button (and `build_turn_prompt`
  says why), `choose_action` refuses a stale click, `DinkyAI` only ever shoots
  from the scoring space, and the set-ups ask `set_up_shot_candidates`.
- **The board image draws where range begins**, in `draw_shooting_range_edges`
  -- one dash column on board 6, two on 7 and 9 bracketing the space in nobody's
  range. The rule is positional and the board is where both coaches read
  position.

## What a shot is up against

A defender sharing the ball's space adds their whole defensive skill; a
defender anywhere else between the ball and the goal adds half of it,
rounded up -- see "Score attempt" in the living rules.
`ShotDefender.value` in `d12ball/components.py` is the whole rule.

- **The halving is per player, not over the group's total.** Two 5s in
  the way add 3 + 3 = 6, where halving their sum would give 5. The two
  readings agree whenever at most one defender rounds up, which is most
  positions -- so a change here can pass a playtest and still be wrong.
  It is the author's, confirmed 2026-08-11.
- **`MatchState.defenders_between_ball_and_goal` pairs each defender
  with whether they are on the ball**, because it is the only thing that
  knows: it walks the spaces from the ball outward, and by the time a
  caller has the skill in hand the position is gone.
  `D12Ball.intervening_defenders` turns that into `ShotDefender`s, and
  the roll and the image both read `.value` -- **neither may go back to
  summing `defense`.**
- **The image says which half is which.** A defence of "6 + 3 + 1" names
  no term, so each defender's portrait carries the value they
  contribute: a solid badge on the ball, an outlined one and the skill
  it was halved from beyond it, under a label per band. It rides on two
  optional fields of `ChallengeSide` (`contribution` and `halved`), so
  the maneuver challenge -- which shares `render_matchup` -- is drawn
  exactly as it was.
- **`halved` cannot be inferred from the two numbers.** A defensive
  skill of 1 halves to 1, and drawing that as a full value would say the
  defender is on the ball when they are not.

## A High Pass that runs out of field

An overshot High Pass offers a shot **or** a contest for the ball, and pays the
ball speed modifier against both -- see "High Pass" and "Ball speed" in the
living rules. `MatchState.pending_high_pass_overshoot` is the flag and
`MatchState.ball_speed_modifier` is the only place the sign is decided.

- **A coach is only offered a distance that fits on the field.**
  `MatchState.high_pass_distances` drops any that would clamp, because a longer
  pass landing where a shorter one already would is that pass at a
  disadvantage -- negative modifier, contest owed. `D12Ball.high_pass_distance_options`
  wraps it with the handler's own maximum (the Fullback's 4), and is the single
  home three things read: the menu `HighPassChoiceView` builds, what the AI
  picks from, and `choose`'s refusal of a click on a menu the ball has moved out
  from under. Those buttons carry no message id, so an older prompt in the
  channel does dispatch.
- **An overshoot is therefore only ever the no-menu case.** When even the
  shortest pass runs out of field -- the ball 0 or 1 spaces from the end --
  `resolve_high_pass` skips the prompt and applies the minimum distance
  directly, because 2, 3 and 4 are the same pass. `high_pass_distance_is_moot`
  is that test; it agrees with "`high_pass_distances` is empty" and exists
  because the moot check should not have to know the handler's role.
  **This is what makes `contest_on_decline` unconditional for an overshoot**: a
  chosen 2 can only overshoot from a position where no distance was offered, so
  the "a pass of 2 is received, full stop" rule and this one never meet.
- **`ball_speed_modifier` is the whole of the sign, and three sites ask it**:
  the score attempt's roll, the image that composes it, and the long-pass
  contest in `LooseBallSkillTestView.roll`. Each used to halve `ball.speed`
  itself. The fourth site is deliberately left alone -- the modifier a *defense*
  adds to a maneuver skill test it won with Steal Intercept, which is settled
  before any pass is thrown and is not the offense's to lose.
- **Every detail string is `:+d`**, because a modifier that can be negative can
  no longer be printed under a hardcoded `+`.
- **The flag is set only when a set-up is actually offered**, in
  `offer_overshoot_set_up`. An overshoot with nobody from the offense on the
  landing space has no shooter, falls through to the ordinary loose-ball paths,
  and would carry an inert flag for the rest of the turn if it were set earlier.
- **It is persisted**, unlike the overshoot test itself, which is a local read of
  `relative_flat_index` against the requested distance the way Block Deflect
  reads its own. Both things the flag governs outlive the effect that sets it: a
  score attempt is a view a restart re-attaches, and the contest is rolled a
  click later. `reset_maneuver` clears it with the rest of the turn.
- **The shot and the contest are two halves of one choice.** Declining an
  overshoot lands in the long-pass contest, still with the modifier against it;
  nothing about an overshoot settles the ball quietly.
  `begin_high_pass_contest` is that contest, reached both from the ordinary
  3-or-4 path and from `decline_scoring_attempt(contest=True)`.
- **`contest_on_decline` rides on the view, not on the match.** By the time the
  decline arrives, an overshot pass and an ordinary 2-space one have left the
  match in the same state, and `SetUpAttemptChoiceView` was already the one view
  a restart cannot reconstruct -- so this adds nothing new to that gap. It also
  relabels the decline button, because "resolve as a normal pass" would be a lie
  there.

## Loose balls and the board

A loose ball is announced **with the board under it and the space named**, and
those two are one decision: the ball is lying somewhere nothing else in the
channel has named, and the question that immediately follows -- who to send
after it -- is a question about how far away everybody is.

- **`begin_loose_ball` posts through `announce_board_update`**, which is why
  that helper is no longer only for manual corrections. The snapshot is drawn
  once and the persistent message is brought in line from the same bytes, so it
  costs the render everything else costs; the callers that used to refresh
  immediately before it (the receiverless Low Pass) no longer do, or the same
  board would be written twice. See "Discord's rate limits".
- **A High Pass is not a loose ball, here as everywhere else.** It borrows the
  same contest, but the ball is on a receiver both coaches watched catch it, so
  that branch sends its headline plainly and pays no upload. `is_high_pass` is
  the test, the same one `contest_noun` reads.
- **The pick prompt names the space as well**, because it outlives the message
  that announced it: `/d12ball resume` puts that prompt back up on its own, and
  a restart re-arms it wherever it has scrolled to.
- The uncontested turnover -- the ball landing on a space only the *other* side
  occupies -- goes out the same way. "So-and-so is already there" cannot be read
  without knowing where there is.
- `ball_location_line` and `ball_space_label` in `cogs/d12ball_helpers.py` are
  the wording, over `space_label`. The line spells the zone out beside the code
  because "M2" alone means nothing to anyone not already looking at the board.

## The ball carrier

Possession is a team's, but the ball is a *player's*: a resolution that
leaves it with somebody in particular makes them the **ball carrier**, and
they take their side's next turn instead of the coach picking again off the
ball's space -- see "The ball carrier" in the living rules.
`MatchState.ball_carrier_id` is the field and
`MatchState.turn_handler_candidates` is the whole of the rule.

- **Every place that offers a handler asks `turn_handler_candidates`**, never
  `eligible_ball_handlers` -- `send_turn_prompt`, `BallHandlerSelectionView`,
  `DinkyAI.choose_ball_handler`, and `select_ball_handler`'s own validation.
  `eligible_ball_handlers` still means "everyone of this team on the ball" and
  is what the loose-ball check and the kickoff fill ask, which is a different
  question and must not be narrowed.
- **`reset_maneuver` deliberately does not clear it.** It runs *between* the
  effect that sets the carrier and the prompt that spends it, so clearing it
  there drops every carry -- and `/d12ball offensive_choice` calls it to start
  a turn fresh, which would make that command a way to hand the ball to
  somebody else. It is consumed by `select_ball_handler` and cleared by
  `clear_ball_carrier`.
- **A stale carrier is harmless by construction.** `turn_handler_candidates`
  falls back to the full list whenever the named player is not among them, so
  a value surviving a period restart, or missing from a game saved before the
  field existed, narrows nothing. Correctness does not rest on having found
  every place to clear it.
- **The setting sites are the effects, not one dispatcher.** Nine of them:
  `apply_dribble_advance`, `resolve_steal_intercept`, `resolve_pressure`
  (twice -- the handler, then the Defender's steal over the top of it),
  `apply_low_pass`, the two High Pass branches where a pass of 2 is received,
  the two unopposed branches of `resolve_loose_ball`, and
  `LooseBallSkillTestView.roll`. There is no single "who has the ball now" to
  derive it from after the fact, which is why each says so itself. A new
  maneuver has to decide, the same way it decides steal-or-new-play.
- **Pressure sets it before the overshoot branch returns.** An own goal
  survived is still a handler who was pressured and kept the ball; a conceded
  one is a new play and gets cleared with everything else.
- **A contest names its winner**, so `begin_loose_ball` clears the carry when
  the ball comes free and the resolution sets it again to whoever won -- on
  the roll, or unopposed. That covers the long High Pass, which routes through
  the same machinery. The out-of-bounds branch is the exception: nobody
  contested it, so it stays clear and the pickup is an ordinary placement.
  Block Deflect sets nothing either -- it sends the ball to a space rather
  than to a player.
- **The run-back exemption is the carry, read from the other end.**
  `begin_run_back` sets `pending_run_back_stays_player_id` from
  `ball_carrier_id` rather than taking it as an argument -- the player holding
  the ball does not run back, whoever they are, because running them back
  would move them off the ball and charge them for it. It used to be a
  `stays_player_id` argument that only the two steals passed, which left a
  loose-ball or High Pass winner being run back off the ball they had just
  won. Deriving it is what stops a new resolution naming a carrier and
  forgetting the exemption; **don't reintroduce the parameter.**
- **A new play exempts nobody**, so `begin_run_back` clears the carry before
  reading it. A goal scored off a High Pass set-up still has the receiver
  recorded as carrying, and they are not -- the ball is on its way back to the
  kickoff space. `announce_new_play_reset` clears it too; that one is for the
  reset, this one is for the exemption two lines below it.
- **The carry travels with the exemption**, in `inherit_run_back_exemption`
  (a substitution) and `swap_meeple_positions` (a meeple trade). Both belong
  to the space rather than the player, since both exist because that meeple is
  standing on the ball. `swap_field_positions` deliberately moves neither: it
  exchanges zone assignments and leaves both meeples where they are.
- **`build_turn_prompt` is told, not asked.** `select_ball_handler` has
  already consumed the field by the time the prompt is built, so `carrying=`
  is passed by the one caller that still knows -- worth the parameter, because
  a coach who is not offered a choice should be told why.

## Turnovers: steals and new plays

Every turnover resets the ball's speed and puts players back in position, but
*how* differs, and only one of the two opens a
[Coaching Choice](#the-coaching-choice).
`begin_run_back`'s `new_play` flag is the whole distinction -- see "Steals and
new plays" in the living rules for which is which. (A third kind,
[ceding](#ceding-the-ball), goes nowhere near `begin_run_back`: nothing was
contested and nothing went dead, so nobody runs back and nothing restarts.)

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
- **A coach's run-back prompt carries the board, and prices every space it
  offers.** "Where does this player run back to" is a question about where
  everybody is standing and how far each space is -- the same reasoning as
  [a loose ball](#loose-balls-and-the-board), and the persistent board has
  scrolled away up the channel by the time a turn has resolved. So the prompt
  is sent with a snapshot of its own, from the render the persistent message is
  settled with (one draw, two uploads), and `RunBackChoiceView`'s buttons read
  `M2 (4 spaces)` -- a run back costs a token a space, so the distance *is* the
  price and the two spaces of a zone are rarely the same offer.
  `MatchState.run_back_distance` is the one reading of it, asked by the labels
  and spent by `run_back_player`, so what a button promises and what the coach
  is charged cannot drift; `travel_space_label` is the wording, shared by the
  buttons and by `describe_run_back_options` beside them.
  - **The board goes when the question does.** The click edits the prompt into
    its answer, and `attachments=[]` takes the snapshot with it -- it shows the
    player still displaced, so leaving it under the result would put a stale
    position in the channel for the rest of the game. The board they moved to
    is the persistent message's, refreshed a line later.
  - The full-image link is added with the view handed over, or the edit that
    adds it drops the buttons the prompt exists for -- see
    `add_full_image_button`. That edit is the webhook route, not the channel's;
    see "Discord's rate limits".

### The arrangement

`MatchState.assigned_positions` is `player_id -> [zone, space]`, persisted
with the rest of the match, and it is what a new play restores -- and what any
[Coaching Choice](#the-coaching-choice) opens on, which is the same restore
read from the other end.

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

## Ceding the ball

A side out of [shooting range](#where-a-shot-may-be-taken-from) may hand the
ball over rather than play it, to buy a
[Coaching Choice](#the-coaching-choice) -- see "Ceding the ball" in the living
rules. It is the third kind of turnover, and the only one that neither runs
players back nor restarts play: the ball stays where it was given up, at speed
1, and no time passes.

- **`MatchState.may_cede_possession` is the whole of when it is offered**, and
  it is `can_attempt_score` read from the other end plus the once-a-half
  declaration. So one sentence in `build_turn_prompt` explains both missing
  buttons, and `PlayerActionView` never builds the shot and the cede together.
  It is deliberately **not** conditional on having anyone to bring on: the
  window is the whole Coaching Choice, and the state with nobody to bring on
  needs all three substitutes to have come off injured.
- **The confirm replaces the turn prompt rather than posting under it.**
  Ceding is the one turn action that hands the opponent the ball, and it sits
  one button along from Maneuver, so `CedeConfirmView` puts the cost in front
  of the coach first. Both ends are `interaction.response.edit_message`, so it
  costs nothing out of the channel's edit bucket (see "Discord's rate limits"),
  and Back restores the prompt **verbatim** from a string the view carries --
  `build_turn_prompt` can no longer tell whether the handler was carrying the
  ball, so rebuilding it would quietly lose that line.
- **`pending_cede` is persisted, and it means "a cede's windows are still
  running".** The whole of a cede happens either side of two Coaching Choices,
  and `cede_possession` resets the turn before the first one opens -- so by the
  time the second closes, nothing else in the match says how it got there and
  `finish_substitution_window` would fall through to a run back nobody owes. It
  is checked in `pending_turn_view` ahead of the "no ball handler yet" branch
  for exactly the reason setup and halftime are, and `finish_cede` clears it
  before dispatching so the state that follows speaks for itself.
- **A cede is charged as a declaration and answered as one.** The reply is the
  same occasion (`finish_substitution_window` passes the occasion through
  rather than defaulting to `NEW_PLAY`), and neither coach is asked -- see
  `asks_declaration` under "The Coaching Choice".
- **The tail is the out-of-bounds pickup, not the loose-ball check.** The
  receiving side's arrangement covers their zones, not wherever open play left
  the ball, so usually nobody is standing on it; `finish_cede` sends them to
  fetch it at the usual token a space. Routing it through
  `check_for_loose_ball` instead would let the side that ceded contest the ball
  back -- and, with one of their meeples still on it, take it back
  uncontested, having bought a window for nothing. The author settled this on
  2026-08-10: "the team that gains possession has to send a player to the space
  where the ball was ceded." So `finish_cede` must keep deciding this itself --
  falling through to `finish_maneuver_resolution` with nobody on the ball would
  hand it to the loose-ball check, which is the reading that was rejected.
- **The clock cost rides on `pending_run_back_distance`, set to 0.** That field
  is what every tail step reads back for the clock, and the pickup spans a
  restart, so a cede has to say 0 there rather than pass it down a call chain.
  `finish_maneuver_resolution` prints "No time has passed" for it, because
  "Time has advanced 0" reads as a bug.
- **Under last possession it ends the period**, in `begin_cede` and before any
  window opens, clearing `pending_cede` on the way out so the flag does not
  follow the game into the second half.
- **Dinky never cedes.** `DinkyAI.choose_action` still answers shoot or
  maneuver, so in a solo game the option is the human's alone. Nothing about
  the flow assumes that -- an AI *receiving* a ceded ball runs its reply window
  through `run_ai_substitution_window` like any other -- it is just that giving
  the ball away is a judgement call and Dinky makes none.

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
  under "Working on the board image" for why that changed. Pinning every board a
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
  of boards is more than the bucket has. So `write_board_message` takes
  `relink`: an **interim** write (the immediate one, `relink=False`) strips the
  now-dead link in the edit it was already paying for and records the URL in
  `board_link_owed`, and the **settling** write (the trailing refresh) puts a
  live one back. The board is linkless for `BOARD_REFRESH_INTERVAL` rather than
  dead-linked for it.
  - **The settling pass is owed as soon as a link is stripped**, so
    `refresh_match_image` schedules one after an immediate write whenever
    something is in `board_link_owed` -- not only when a second refresh asks.
    Without it a quiet board would keep the link the interim write took off.
  - **A settling write with nothing new to draw still pays the link**, from the
    URL it was handed rather than by re-fetching the message: one edit, and the
    common case, since the last step of a click usually moves nothing. That is
    `settle_board_link`, and it spends no request when nothing is owed.
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
    `close_maneuver_prompt` used to re-edit the "Choose Your Maneuver" prompt
    on each pick with a freshly built `ManeuverActionPromptView`. Nothing about
    that message changes when a side picks -- it names who it is waiting on,
    both sides share the one button, and the view is built from the game id
    alone -- so it was a request out of this bucket, once a maneuver,
    immediately before the resolution's own board refresh, for nothing. It now
    only deletes, once both sides have picked, and a delete is a route of its
    own. Who has picked is announced in its own message.
  - **A board refresh spends one of the five**, two when it is the settling
    one, so `refresh_match_image` is rate-gated per game: the first goes out at
    once and any that arrive within `BOARD_REFRESH_INTERVAL` collapse into
    **one** trailing refresh rather than queueing.
  - **`BOARD_REFRESH_INTERVAL` must stay above Discord's five-second window**,
    or two refreshes fall inside one window. At three seconds a turn spent
    exactly five and was still earning 429s -- measured. Six leaves a turn at
    three requests: one interim board, then the settling board and its link.
    Adding a call site is free; shortening the interval is not.
  - A trailing refresh **draws when it runs**, never from a `png=` handed to it
    earlier -- the board it was offered is stale by the time it fires, and
    re-drawing is exactly what lets one pending refresh stand in for every
    request behind it.
  - **Only one write per game is ever in the air**, held by
    `board_refresh_locks`. A write is not instant: drawing a 2200px board and
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
      `wait_out_board_interval`. It is the only place the bot sleeps before a
      request, and it is not the pacing ruled out below: nobody is waiting on
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
    is recorded in `board_refresh_wanted` and a pass that finds the flag set
    again when it lands waits out another interval and goes round once more.
    Counting the *task* instead dropped the request on the floor -- it was still
    in `board_refresh_tasks`, so nothing rescheduled, and the board kept a state
    the click had already moved past until somebody clicked again. Anything
    added to the gate has to keep the discard *before* the write, or the same
    hole reopens.
  - **A board identical to the one already up is not written at all.** The
    render is deterministic, so `write_board_message` keeps a digest of what
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
    `wait_out_board_interval` is the one sleep before a request, and it is on
    the right side of that line: the board it is holding back has not been
    drawn yet, and every write it delays is one it is about to make
    unnecessary. A coach waits on prompts and on the messages a turn posts,
    and none of those go through this gate.
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

**The first board of a game goes up when setup coaching ends**, not when the
match is created. `finish_setup_coaching` posts it; the coin toss and the
home/visiting choice leave the persistent message imageless, and an AI setup
window skips its own refresh while `pending_setup_stage` is set. Nothing has
been played before that point, so a board posted earlier shows a deal neither
coach has finished with and is redrawn twice over before anyone acts on it --
the one worth looking at is the line-up the game kicks off from.

**And it goes up through `post_new_play_board`, like every other new play's.**
A kickoff *is* a new play, so its board is its own message under the coaching
that produced it, pinned like the rest. It used to attach the board to the
persistent message instead, which put it in the right order but the wrong
place: Discord leaves an edited message where it was, so a board finished after
two coaching windows appeared above them, at the top of the channel, with the
timestamp of the home/visiting choice. Both developers read that as the change
never having landed. The persistent message still gets the same render in the
same breath -- `post_new_play_board` refreshes it from the `png=` it already
drew -- so this costs one message and one pin per *game*, not per turn.

**There are two board images, and they are drawn to different widths.**
`render_match_image` is the 2200px one everybody sees;
`render_coaching_image` is the 1280px half-field a
[Coaching Choice](#the-coaching-choice) keeps up, and the two do not share a
layout. The coaching image carries one row of meeples instead of two, so at the
match image's width it arrives in Discord as an unreadable sliver. **It is
deliberately not mirrored for the visiting coach**: the zones keep their real
names and the spaces their real numbers, so V1 is the same space on both images
and on the board the coaches are looking at.

Two things set its width, and both are three cards wide. A zone's **assigned
cards** are drawn under that zone, and midfield holds three under 2-3-1 and
1-3-2 (a goal zone does under board 9's 3-2-1 and 1-2-3, which is the same
three); a space has to fit a **stack**, which is board 6's two-space midfield
under those same shapes. `D12BallComponentTests` checks both, because the
suite cannot see the image and an overflow here is silent.

**The cards and the two benches are on it for a reason.** Exhaustion counts and
the Exhausted and Injured badges are drawn nowhere else, and which pool a
player is in is the whole of who may come on -- so without them the flow would
be asking a coach to remember numbers off a board they cannot see while the
menu is up.

**The ball token hangs off the possessing side's meeples, except when they have
none there.** `ball_token_x` is the whole of the placement: normally it tucks
against that side's group on the open end of the row, which keeps it next to
whoever is holding it however many of them share the space. An empty group
reports the whole space as its bounds, so anchoring to its edge drew the ball a
radius *outside* the space, under the next space's tokens -- which meant
[a loose ball](#loose-balls-and-the-board), the one position whose whole
question is where the ball is lying, was the one thing the board did not show.
With nobody of that side there it is centred in the space instead. The suite
cannot see the image, so `D12BallComponentTests` asserts the placement rule
rather than the pixels.

### The matchup image

`render_matchup` draws a contest about to happen, and one layout serves two:
the maneuver challenge (one against one) and the score attempt (one against a
wall of defenders). See "What a shot is up against" for the badges only the
second one carries.

**Its width is content, not a canvas.** Each side is a group as wide as it
needs to be, held between `CHALLENGE_MIN_GROUP_WIDTH` and
`CHALLENGE_MAX_GROUP_WIDTH`, and the image is the two plus `CHALLENGE_GUTTER`.
Discord scales the whole thing down to the message's width, so every pixel of
empty black is spent making the writing smaller — which is what a 300px
minimum was doing on a maneuver challenge, where both groups are a two-word
name and a skill line. The minimum is now little more than the portrait it
sits under, and it is a floor for a group *carrying an ability*: a wall of
defenders has none, and packs to its own content.

- **The sum overrides the maximum.** A total broken over two lines with the
  number stranded on the second is unreadable however narrow it makes the
  image, so `group_width` floors on it. The maximum caps the *names*, which
  can wrap.
- **A matchup has its own fonts** (`FONT_CHALLENGE_TITLE`, `_BODY`,
  `_ABILITY`, `_TOTAL`) rather than borrowing `FONT_SMALL` and
  `FONT_DICE_TOTAL`, which size the board and the dice and are not on this
  image at all. The heading is the one line nobody needs to read — it names a
  picture a coach is already looking at — so it is set *below* the body, and
  the room that frees goes to the names, skills and abilities. Changing a size
  here changes the width: the text is what the groups are measured from.
- **Look at it.** The suite checks it is a PNG and nothing about how it reads.
  There is no sample script for this one; render a `ChallengeSide` pair
  through `render_maneuver_challenge` and `render_score_attempt` (three
  defenders, one of them halved, is the widest case) and open the result.

### The maneuver cards

`d12ball/cards.py` draws the six maneuvers as cards. They exist because a
selection d6 makes a coach hold the rules in their head: the die says "3-4" and
the coach has to remember that is Dribble Advance if they have the ball and
Steal Intercept if they do not, what it beats, and which role changes it.

**One layout serves two things, on purpose.** `render_maneuver_card` is the
print-ready face for the tabletop game -- 2.5 x 3.5in at 300dpi, plus one
shared back -- and `render_maneuver_hand` puts a side's three side by side,
which is what the bot shows a coach who has clicked "Choose Your Maneuver".
A coach who has played at the table and a coach playing by Discord should be
reading the same card, so neither gets a design of its own.

```bash
python3 scripts/render_maneuver_cards.py --out cards/ --sheet  # print-sheet.png
python3 scripts/render_maneuver_cards.py --bleed   # 1/8in for a print shop
python3 scripts/render_maneuver_cards.py --hands   # what the bot sends
```

- **The hand replaced a paragraph per maneuver.** `build_maneuver_choice_text`
  listed each maneuver's effect and matchups next to the buttons; every word of
  it is on a card and in the same place on each one, so a coach now compares
  three cards instead of reading three sentences. It went with the change --
  don't reintroduce it alongside the image.
- **The hand is a side's three cards *and the shared back*, which replaced a
  button.** `ManeuverActionSelectView` carried a "Maneuver Reference" button
  that posted the defeat cycle as a second ephemeral message -- a click, a
  round trip and an upload to see the one thing a coach needs *while* they are
  choosing. The back carries that same cycle, it is public information either
  coach may look at whenever they like, and at the table it is face up on the
  deck in front of them. So `render_maneuver_hand` draws it as the fourth card
  and the button is gone; `/d12ball maneuver_reference` still posts the
  hexagon for anyone who wants it in the channel, which is why
  `build_maneuver_reference_file` is still there.
- **Both hands are drawn once in `D12Ball.__init__`**, like the maneuver
  reference image and for the same two reasons: startup is the one place a
  render can block the loop harmlessly, and the alternative is drawing three
  cards on every click of a button pressed several times a turn. Nothing about
  a card depends on the match, so they cannot go stale.
  `build_maneuver_hand_file` re-wraps the bytes per send, because uploading a
  `discord.File` consumes the stream inside it.
- **The hand is drawn at a third of the print card's width.** Discord scales an
  inline image down whatever it is sent, so the extra pixels would only be
  payload -- and this send is ephemeral, once per coach per maneuver. The
  abilities are small print at that size, which is what the full-image link on
  the message is for. That link is the webhook route, not the channel's edit
  bucket; see "Discord's rate limits".

- **Nothing on a face is written in the script.** The effect, the time cost and
  the beats/ties/loses row come from `maneuvers.json` through
  `load_maneuver_catalog` and `ManeuverCatalog.relationships`; the abilities
  come from `players.json`. So a card cannot claim a rule the bot does not
  play, and an import is carried onto the cards by re-running this rather than
  by editing them.
- **Which roles a card lists is mostly matched, not tabulated.** A role is on
  the card when its ability sentence names that maneuver, which is why the
  Fullback is on both High Pass and Block Deflect, carrying its whole sentence
  to each. The sentence is never cut down here -- see "Every ability is
  imported twice". A new ability that mentions a maneuver reaches its card
  without anything in the script being touched.
  - **Two things the match cannot find are listed explicitly**, and both are
    the author's call rather than an oversight in the data. `EXTRA_ROLES` puts
    the **Striker** on High Pass: its +3 is for scoring off a set-up, one step
    removed from the maneuver, and three maneuvers can produce a set-up -- a
    High Pass is much the most common way, so it goes there and nowhere else.
    `EXTRA_NOTES` gives **Steal Intercept** the ball speed modifier its
    defender adds to the skill test, which decides the maneuver and which no
    role ability names, so its card would otherwise be the only blank one.
  - **Neither can live in `maneuvers.json`**: `scripts/import_d12ball_maneuvers.py`
    rewrites that file whole from the sheet, so a field added to it survives
    until the next import and no longer.
- **The strip diagram is what a card can say that a die face cannot**, so it
  carries the geometry and the effect text carries the wording. It is the
  standard seven-space board with the ball on the third space, which is the
  only position from which every maneuver fits: a High Pass of 4 lands on the
  last space and a Fullback's Block Deflect of 2 on the first.
  - **A dashed arc is a role's variant and a solid one is the ordinary move.**
    That is the only thing the dashes mean, which is why Low Pass's backward
    option is solid -- it is a choice any passer has, not an ability.
  - **A move's offset is along the offense's attacking direction, never
    "forward" or "back".** Those two words mean opposite things to the two
    sides and are what got Pressure and Steal Intercept drawn mirrored:
    a challenger's forward is toward the goal *they* attack, so Pressure moves
    the handler and the challenger onto the **same** space (which is how a
    Defender's won Pressure can steal at all); and a steal's back is toward the
    new possessor's own goal, which is the goal the offense was attacking, so
    the ball travels the way the offense was going. Both are verified against
    `move_player_relative` rather than reasoned about -- run it and read the
    flat indices before redrawing an arrow.
  - **Distances are labelled under the space they land on.** High Pass throws
    three arcs out of one space, and labelling those at their peaks stacked
    three captions on top of each other. A caption's font is sized to the gap
    to the next caption on its row, and ability variants get a second row.
- **The offense red and defense green are the maneuver reference image's**, so
  a coach reading a card and a coach reading the bot's hexagon are looking at
  the same two colours.
- **A card is white, and the colour is its edge and its header.** It used to
  be a saturated frame edge to edge on a cream face, with a near-black back --
  which is a page of ink per sheet of nine and the first thing a home printer
  runs out of. The face and the back are now `CARD_FACE` white, the maneuver's
  colour is a `EDGE_WIDTH` outline, and `BACK_COLOR` is white with a grey
  edge. **`FACE_COLOR` is still the boards' cream** and is deliberately not
  the cards': a board is one sheet a game, where cards are printed by the
  page.
- **The rounded outline is the cut line.** With the face and the sheet both
  white there is nothing else to say where a card ends, which is why the
  corner radius is drawn rather than implied and why `FRAME` is small enough
  that the outline is the card's own edge.
- **One back for all six.** A coach holding both sets must not show which side
  of the ball they are reading. It carries the defeat cycle, which is public
  and which every coach may look at anyway.
  - **The cycle draws both relations: a solid arrow to what a maneuver beats,
    a dashed line to what it ties with.** The ties were left to the caption
    ("same rank ties"), which made them the one thing on the card a coach had
    to work out rather than look up -- and a tie is the branch that costs a
    skill test and a token each. `tie_pairs` asks `ManeuverCatalog.resolve`
    rather than pairing equal ranks or joining opposite nodes: on six
    maneuvers the ties happen to be the hexagon's three diagonals, but that
    is a property of a six-node cycle, so a seventh would move the lines
    without moving what they mean.
- **`print_sheet` is an exact grid, because splitters cut by dividing.**
  Every cell is one card plus `SHEET_MARGIN` on all four sides, the sheet is
  `SHEET_COLUMNS` cells wide and whole rows deep, and a short last row is
  padded with spare backs. So dividing the image into quarters across gives a
  card dead centre in each piece. The old `contact_sheet` put a gutter
  between the cards *and* around the outside, which made a quarter of its
  width a card plus a quarter of a gutter -- every cut but the first came out
  off-centre. `D12BallManeuverTests` divides a rendered sheet and checks the
  pieces, since nothing else would notice.
- **The header's corner names the mode, not the die faces.** It printed
  "die 1-2" while the cards and the selection die had to coexist; it now reads
  "BASIC MANEUVER", which is what will still mean something once a second set
  of maneuvers exists.
- `cards/` is generated output and is gitignored, like `board.png`.

### The printed boards

`d12ball/boards.py` draws the three boards the tabletop game is played on --
the **field board**, the **jumbotron board** and a coach's **team board** --
print-ready at 300dpi, A3 landscape.

```bash
python3 scripts/render_boards.py --out print/          # every field size
python3 scripts/render_boards.py --teams --bleed --pdf
python3 scripts/render_boards.py --board-size 9        # just the one field
```

- **They follow `cards.py`, not `render.py`.** The palette is the maneuver
  cards' -- dark ink on a light face -- because a print goes on paper and the
  bot's dark board is the wrong thing to hand a printer. The zone tints are the
  bot's three hues lightened, so a coach reads one board as the other.
  Everything is measured in inches, with the same 1/8in bleed the cards carry.
  The boards keep `FACE_COLOR`'s cream where the cards went white: a board is
  one sheet a game.
- **The clock and the score are the jumbotron's, not the field's.** They were
  bands under the field, where sixteen minutes across a sheet that was already
  carrying the field left a cell an inch wide -- too small to stand a token in,
  which is the only thing those cells are for. On their own board the clock is
  two rows of eight (`CLOCK_COLUMNS`) and both tracks clear `MIN_TOKEN_INCHES`;
  `cell_inches` is that measurement, reported by the CLI and asserted by
  `D12BallJumbotronTests`. The field board got the whole of that space back,
  which is what makes a space tall enough for two sides' meeples --
  `FieldGeometry.space_inches`, asserted the same way. It is the split the bot's
  own board already makes: a jumbotron is the state of the match, the field is
  the position.
- **No die value is printed anywhere.** Maneuvers are chosen with the cards, so
  the two selection d6s are off the team board and the head coach cell lists
  the six maneuvers by rank (O1, D2) instead of by face. The **ruleset still
  defines those dice** -- `basic_rules.json`, `TeamBoardDefinition`, and the
  living rules' own component list -- so this is a divergence and not a
  deletion: `draw_die_slot` reads `team_die` alone and says why, and a test
  greps the module for `offense_die`/`die_values` because the data is still
  right there to pick up again by accident. **If the selection die is retired
  upstream, that is a rules change and wants its own commit** -- living rules,
  a dated rules-log entry, and then the data.
- **A3 landscape, all three, and that is a constraint rather than a
  preference.** Five of the team board's six cells have to hold a 3.5in card:
  two rows of them plus a header and a footer is 11.3 inches, which is most of
  an A3's shorter side and more than a tabloid's. So the head coach is a cell
  of the grid rather than a band across the top, the formation table is a
  footer strip rather than a panel, and **`card_slot_inches` is what says
  whether a print can be laid cards on** -- the CLI prints it, and a smaller
  sheet scales the whole board down rather than overflowing its areas.
  `D12BallTeamBoardTests` asserts it, because a band added above the areas
  takes them under a card silently: it renders fine and prints useless.
- **A panel that has to fit divides what it is given.** The head coach cell
  sizes its three maneuver rows from the height left under the die rather than
  from a fixed measurement, because three rows that fit one sheet run off the
  bottom of another -- and that overflow is the one thing on these boards a
  reader would take for a bug rather than a layout that scaled.
- **Nothing on any board is written in the module.** The layouts, the
  formations, the standard deal and the coach's die come from
  `basic_rules.json`, the six maneuvers from `maneuvers.json`, and the roster
  from `players.json` -- so a printed board cannot claim a rule the bot does
  not play, and an import reaches the boards by re-running the script.
- **The geometry a board asserts is read off the same code the bot enforces.**
  `shooting_range_bands` walks `BoardState.is_in_shooting_range` a space at a
  time and `kickoff_marks` reads `kickoff_space_index`, rather than either
  restating where the middle of the board is. That is what puts two kickoff
  marks on board 6 (its midfield has no middle, so each side kicks off from
  the space nearer its own goal) and one on 7 and 9, and what leaves the
  bracket under the field agreeing with the living rules' own table.
- **Every field size is rendered by default.** A print run wants the 6-, 7- and
  9-space boards; `--board-size` narrows it to one. The sizes come from
  `rules.board_layouts`, so a fourth layout added upstream is printed without
  the script being touched.
- **Zones keep their real names on the team board.** A coach's own goal is the
  home goal for one of them and the visitors goal for the other, and one
  design is printed for both, so the areas read HOME GOAL / MIDFIELD /
  VISITORS GOAL exactly as the field and the coaching image do. Only the
  formation strip is relative, and it says so. `--teams` colours a board per
  team and changes nothing else.
- **The formation strip lists the shapes and nothing else, and groups the ones
  only some boards play.** One team board is printed for every field size, so
  3-2-1 and 1-2-3 are on it under "9-SPACE BOARD ONLY" rather than left off --
  read from `board_sizes` rather than from a size written into the module. The
  `(2 / 3 / 1)` that used to follow each name restated the same three digits
  (a shape is named by its counts, which the ruleset loader checks) and five
  shapes with it no longer fit the strip. `draw_formation_strip` measures
  itself and shrinks to fit, because a sixth shape added upstream lands there
  without anybody measuring.
- **The clock and score tracks are printed aids, not components the rules
  name.** What they count is a rule -- fifteen space-minutes, a clock that
  stops there, a score a shootout can add six to -- but nothing upstream says
  a board carries a track, so don't read them as one.
- **`Sheet` measures in thousandths of the sheet's width** and does not
  supersample, unlike `cards.Pen`: a board is tens of megapixels at 300dpi,
  where a card is under one, and a stepped edge that small does not survive
  the print. Its canvas is allocated on first use, which is what lets
  `card_slot_inches` and `cell_inches` ask how a layout comes out without
  drawing it.
- `print/` is generated output and is gitignored, like `cards/`.

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

## Recovering a stuck game

A restart re-arms exactly **one** message per game — the one recorded in
`turn_message_id` — so a game can come back with no working button anywhere in
its channel. `/d12ball resume` puts the question back up and
`/d12ball abandon_game` ends the ones nobody is going to finish. Both are open
to either player in the game, or to anyone with `manage_channels`
(`may_administer_game`).

**The ephemeral views in the game are the three secret picks**, and they are
ephemeral for one reason: a coach must not see the other side's choice before
the reveal, and it is the only thing Discord offers that hides it.
`ManeuverActionSelectView` is the maneuver pick; `ShootoutOrderSelectView` and
`ShootoutPickSelectView` are the shootout's shooting order and its sudden-death
shooter. Everywhere else `ephemeral=True` carries an error reply with no buttons
on it. Those three are also the only views a restart cannot re-attach to their
message: the bot never holds a durable handle to an ephemeral message, so there
is no id to give `add_view`.

`restore_maneuver_menus` is the way round it, and `restore_shootout_menus` does
the identical thing for the other two. `add_view` **without** a
message_id lands the view under a `None` key, and discord.py's
`ViewStore.dispatch_view` looks a click up by `(message_id, custom_id)` and then
falls back to `(None, custom_id)` — so the menu a coach already has open starts
answering again after a restart. It is safe because the custom_ids already carry
the game and the side (`d12ball:maneuver_pick:<game>:<side>:<maneuver>`), and
because a message_id match wins over the fallback, so the next menu the game
opens is dispatched to its own view as usual. The registration outlives the
maneuver, which costs nothing: `pick` re-reads the match and answers "a maneuver
has already been chosen for that side." The fallback is asserted against
discord.py's own store in `tests/test_d12ball_recovery.py`, because the whole
thing rests on it surviving a library upgrade. Failing all that, the public
"Choose Your Maneuver" button *is* restored normally, and clicking it opens a
fresh menu.

Three more ways a restart strands a game, none of them about ephemerality:

- The prompt was **deleted** before the restart. `close_maneuver_prompt` drops
  the maneuver prompt once both sides have picked and clears `turn_message_id`
  with it, and `close_shootout_prompt` does the same for the shootout's order
  and shooter prompts. There is then nothing to re-arm.
- The process died **before the prompt it was about to send was recorded**.
- The process died **in the middle of a cascade whose next step was the bot's
  own**. This is the one that strands a game hardest: `continue_run_back`, the
  setup sequence, the halftime sequence, the full-time one and the shootout are
  driven from a live interaction, so there is no button anywhere and nothing
  will ever pick the state back up.

Two things follow from that:

- **`pending_turn_view` is the only reading of "what is this match waiting
  on?"** Startup re-attaches the view it returns to the message the prompt is
  already on; `resume_pending_prompt` posts the same one on a fresh message. A
  second copy of that branch chain is how a resume comes to offer a different
  prompt from the one a restart restores. Its ordering carries real decisions —
  setup, halftime, the window before the shootout and a
  [ceded ball](#ceding-the-ball) are checked ahead of "no ball handler yet"
  because all four leave `active_player_id` None, and a maneuver is recognised
  by `challenger_id` rather than `pending_action`, which `choose_challenger`
  clears.
- **A state whose next step is the bot's is handed back to the routine that
  drives it**, not re-asked: `continue_run_back`, `begin_ball_recovery`,
  `advance_setup_stage`, `advance_halftime_stage`, `advance_full_time_stage`,
  `run_ai_substitution_window`, `advance_shootout`, `finish_cede`. That is the
  whole difference between resume's two callers, and the reason `pending_turn_view` returns a
  view rather than posting it.

- **An open Coaching Choice is re-posted, never re-opened.**
  `repost_coaching_prompt` exists because `begin_substitution_window` calls
  `open_coaching_window`, which resets the substitution counter — resuming
  through it would hand a coach back the swaps they had already spent. It is
  checked ahead of the setup, halftime and full-time stages for the same
  reason: all three run their coaching through that one window.
- **`resume force:true` clears the turn**, via `reset_maneuver` and
  `close_coaching_window`, and asks the offense to choose again. It refuses
  during setup, halftime, a [ceded ball](#ceding-the-ball) and the shootout --
  the window before it included: those are real positions in the game rather
  than a turn gone wrong, and clearing them would drop a coach's window -- or
  both coaches' shooting orders -- on the floor. A cede has a second reason:
  the ball has already changed hands, so the prompt a cleared turn puts up
  would be asking the receiving side to act with nobody on the ball.
  `offensive_choice` refuses in all the same states for the same reasons.
- **`/d12ball offensive_choice`'s refusals all point at resume.** "A score
  attempt is already in progress" was the symptom that started this:
  `pending_action` stays `"shoot"` for the whole post-goal sequence, since only
  `reset_maneuver` at the end of the turn clears it, so a restart during the new
  play's coaching window leaves it set with the window still open. The third
  refusal is a roll a coach still owes (see "Every roll is a coach's"), which
  `pending_action` says nothing about -- `choose_challenger` cleared it when the
  maneuver that led there began. The fourth is a cede, which leaves
  `pending_action` clear for the same kind of reason: the turn was reset before
  either window opened.
- **Abandoning archives, it does not delete.** The channel is the record of what
  happened, deleting one is the tightest rate limit Discord has, and keeping the
  saved game is what stops the PBD number being handed out twice (see the
  pruning note under Gotchas). `abandon_and_archive_game` moves the channel
  first because that is the only step that can fail — a half-ended game is worse
  than one still stuck — then clears `message_id` and `turn_message_id`, since
  startup restores views off those two and reads nothing about status.
  `D12BallGame.abandon()` accepts a game still in setup, which `finish_game`
  refuses; a game gets stuck before kickoff as easily as after it.

**A bot run out of a git worktree keeps its own saved games.** `PROJECT_ROOT` in
`gamesaves/d12ball/storage.py` is resolved from that file's own path, so
`<checkout>/data/d12ball_games.json` is per checkout. Restarting "with updates"
from a different tree loads a different set of games, which looks exactly like a
game breaking on restart and is not something `/d12ball resume` can help with.
Check which tree the bot is actually running from before treating a missing game
as a bug.

## Gotchas

- **The team board is saved as `team_board` and read under either name.** It
  was called a player board until 2026-08-10 — `TeamBoardState`, `team_board`
  on `TeamSetup`, and the key in `basic_rules.json` and in every saved match.
  `TeamSetup.from_dict` falls back to `player_board`, because a game saved
  before the rename outlives it: both developers run the bot from their own
  tree against their own saves, and there were real games under the old key
  when it changed. Nothing writes the old name, so it dies out on its own —
  don't add a migration, and don't drop the fallback until you know no
  half-finished game predates the rename.
- **`data/d12ball_games.json` is runtime state and is deliberately untracked.**
  The bot rewrites it on every game action. It used to be committed, which
  meant it showed as modified more or less permanently and was a standing
  source of merge conflicts. Don't re-add it. Each developer's saved games are
  local to their own machine, and `data/` is created at startup if missing.
  `data/d12ball_games.tmp` — the file `save_games` writes and then renames over
  the JSON — had been committed by accident and was doing exactly the same
  thing. Both are ignored now; neither belongs in a commit.
- **`save_games` never raises, and a save failure never fails the turn.**
  It is called from around a hundred and fifty places, most of them part-way
  through resolving a turn, so a raise lands in whichever callback is running
  and `SafeView.on_error` tells the coach the click went wrong — after the
  maneuver has been announced and the board redrawn, so clicking again applies
  the turn twice. The live game is the one in memory; the file is what a
  restart reads. So an `OSError` is caught, logged, and swallowed. This is not
  hypothetical: one developer's checkout is on a mounted Google Drive letter,
  and when the mount went away mid-game every save raised `FileNotFoundError`
  from `mkdir` walking the path up to a drive root that no longer existed.
  `botstate.write_key` does the same for the same reason — silently, since it
  is on the startup path and its whole job is to keep #logs quiet.
  - **Only the first failure of a run reaches #logs.** The condition is one
    thing wrong repeated once or twice a click, and someone has to go and
    remount the drive; the ones behind it are console-only, and so is the
    line that says saving is working again. See "The level you log at decides
    who sees it".
  - **A file this run could not read is never written over** (`_load_unreadable`).
    The other half of the same mount going away is the bot *starting* while it
    is gone: `load_games` comes back empty, and once the mount returns the
    first save would replace every saved game with the one played since.
    Saving is blocked until the process is restarted, which is what wants
    doing anyway. "There is no file yet" is not that case, so a fresh clone
    saves normally.
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
  the message sits untouched that long. The next board update re-cuts it --
  a few seconds after the board itself, during which the persistent message
  carries no link at all; see "Discord's rate limits" for why. This
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

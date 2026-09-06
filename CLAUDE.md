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
| `discord_emoji_cache.py` | The cache-with-cooldown shape shared by every cog's application-emoji lookup (`cogs/coins.py`, `cogs/d12ball.py`) -- not what each cog loads, only the retry timing |
| `botlog/` | Console logging setup, and the #logs channel mirror — see below |
| `cogs/d12ball/` | All D12 Ball slash commands and the Discord interaction flow. One class of 217 methods over 10,087 lines is what this package replaced, split along the section banners the file already carried: `core` (lifecycle, lookups, `persist`, the spine of a turn, `pending_turn_view`), `effects` (one banner per maneuver), `turnovers` (run back, cede, out-of-bounds pickup), `periods` (clock, halftime, shootout), `presentation` (prompts, images, channels, the AI turn, the tutorial's narration) and `slash_commands` (every command, the three subgroups, the startup sweep). `__init__.py` assembles `D12Ball` from the six mixins and re-exports what the module exposed, so `from cogs.d12ball import D12Ball` is unchanged. |
| `cogs/d12ball_helpers.py` | Constants and free functions shared by the cog and its views — emoji lookups, player/team formatting, channel naming. Re-imports and re-exports everything `d12ball/formatting.py` holds, so an existing `from cogs.d12ball_helpers import space_label` keeps working; what stayed here needs an emoji dict or discord.py itself. |
| `cogs/d12ball_views/` | The `discord.ui.View` classes, one per prompt a player can be shown -- forty-nine of them, split into ten modules along the clusters they already fell into (`base`, `setup`, `turn`, `rolls`, `runback`, `effects`, `coaching`, `halftime`, `loose_ball`, `shootout`). `__init__.py` re-exports every name the single file held, so `from cogs.d12ball_views import X` is unchanged for every X and no call site moved -- the arrangement `cogs/d12ball_helpers.py` has with `d12ball/formatting.py`. `base` holds `SafeView` (whose `load_match`/`require_match` are the shared "get the game and its match, or bail" lookup nearly every view opens with, and whose `is_game_participant` is the shared "is this one of the two coaches" check a roll button answers to) plus the two contest-rendering helpers; it imports from no sibling, which is what keeps the package a DAG. |
| `cogs/d12ball_boards.py` | The write gate on a game's persistent board message. `BoardRefreshState` is one game's -- when a write landed, the pass waiting to write again, the board already on the message, the link owed for it, the lock, the wants arriving mid-write, the refusals -- and `BoardRefresher` holds one per game and the six methods that read it. Those were seven parallel dicts keyed by game id on the cog, agreeing about a game only by hand at each of the eleven sites that wrote them. `D12Ball` keeps a thin forwarding method for each of the six, so no call site moved -- see "Discord's rate limits". |
| `cogs/debug.py` | Maintenance commands, including the PBD channel-and-count reset |
| `d12ball/components.py` | Game state model — `MatchState`, `BoardState`, `TeamSetup`, `PlayerCatalog` |
| `d12ball/engine.py` | `RulesEngine` — the cog's decisions and candidate lists that never touch Discord, over a fixed player catalog/ruleset/maneuver catalog/AI strategies. `D12Ball.engine` is the one instance a cog builds; every call site reads `self.engine.foo(...)` (or `self.cog.engine.foo(...)` from a view) instead of `self.foo(...)`. Includes prompt-text and matchup-data builders (`build_turn_prompt`, `challenge_side`, ...) that are presentation but need nothing beyond the match and the catalogs -- no emoji dict, no cog. |
| `d12ball/formatting.py` | Plain-text formatting over match/game/zone data with no Discord dependency -- space codes, team-side labels, player names. `cogs/d12ball_helpers.py` re-exports all of it; `d12ball/engine.py` imports it directly for the prompt/matchup builders above. |
| `d12ball/game.py` | `D12BallGame` (per-channel game record), `Team`, `GameMode`, `Formation` |
| `d12ball/render.py` | Board image rendering (Pillow) |
| `d12ball/cards.py` | The twelve maneuvers as cards — the printed face, the one shared back, and the hand the bot shows |
| `d12ball/player_cards.py` | The roster as cards, print-only, over `cards.py`'s print machinery |
| `d12ball/boards.py` | The field, jumbotron and team boards, print-ready for the tabletop game |
| `d12ball/rules_doc.py` | Reads `docs/living-rules.md` for the two rules commands |
| `d12ball/stats.py` | Every statistic `/d12ball stats` reports, as a fold over `MatchState.events`, plus the plain-text tables it renders. No Discord and no game flow: a statistic is a reading of what happened, and a reading that could change what happens is a bug waiting to be written -- see "The event log" below |
| `d12ball/tutorial.py` | The scripted opening a tutorial game plays -- the five beats as data, and the rails -- see below |
| `d12ball/data/` | `players.json`, `basic_rules.json`, `maneuvers.json` |
| `d12ball/images/` | Card art and emoji |
| `d12ball/fonts/` | Bundled DejaVu — see "Fonts" below |
| `gamesaves/d12ball/storage.py` | Persistence to `data/d12ball_games.json` |
| `gamesaves/d12ball/archive_export.py` | Writing one finished game's export (record, final board, channel transcript) to disk for `/debug export_archived_games` -- see "Freeing up the PBD Archive" below |
| `scripts/` | CLI tools used repeatedly (not one-off scratch work) |
| `tests/roster.py` | Naming a player in a test by role -- see "The test suite" |
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
  **Don't guess a gid -- run the import script, or read its `DEFAULT_SOURCE`.** The workbook
  keeps its old tabs: `gid=0` is the pre-reshuffle player table, still there and still
  answering, with nine-of-one-species rosters and the retired `{colour}_{name}` ids. Fetching
  it by hand and reading it as current is a mistake that has been made; the live tab is
  "Player Cards" (`gid=6660238`), and the scripts already point at the right ones.

**Every ability is imported twice**, in full and abbreviated -- `ability` and `ability_short` on
each role profile in `players.json`, from the `basic_abilities` sheet's own two columns. Text
that shows an ability on its own (the roster, the rules listing) uses the sentence;
anything captioning a portrait with it uses `RoleProfile.short_ability`, which falls back to
the sentence when there is no short form. **Don't shorten an ability in code.** Which half of a
two-part ability survives is a rules judgement, so the author makes it upstream and the import
carries it. Two quirks of that sheet are handled in the script and covered by
`tests/test_d12ball_player_import.py`: the column is spelled `Abbreivated` and stored with a
trailing space, and a cell beginning `+3` may be typed with a leading backtick so the
spreadsheet doesn't read it as a formula.

**The escape is on sentences as well as abbreviations, and not predictably.** It was stripped
from the abbreviated column alone -- which is where the `+3`s were first noticed -- and the
Striker's *sentence* starts `+3` too, so it shipped in `players.json` as
`` "`+3 for scoring off a set up." `` and printed with the backtick on the maneuver card, the
roster and the rules listing. Whether a given cell carries the guard is the spreadsheet's
business: the Midfielder's sentence also starts `+3` and is stored without one. So
`strip_formula_escape` is applied to **every** ability column, and
`test_no_shipped_ability_carries_a_formula_escape` asks the shipped catalog rather than the
importer -- the importer was only half wrong, so every test about it passed.

[docs/rules-log.md](docs/rules-log.md) is the other half: every rules change with its date and
where it came from, what is still unanswered, and what the answers unblock. Two parts of it
earn their keep when upstream moves:

- **Where upstream is behind** lists every point at which the living rules already differ from
  Notion or the sheet, so a fresh pull can tell old news from a real change.
- The **change log** is the running record. The rules are a live prototype and move: when they
  do, update the living rules and add a dated entry as its own commit, so each rules change
  stays a reviewable diff.

[docs/advanced-maneuver-matrix.md](docs/advanced-maneuver-matrix.md) is a third document and a
different kind of thing: the **worksheet advanced mode was built from**, cut back to what is
still open. It was a table of every advanced maneuver against every maneuver it could meet,
with each assumption named and each undecided cell marked; the author answered, the six cards
went into the living rules on 2026-08-19, and **the answered parts were deleted rather than
kept in parallel** -- which is what happens to a worksheet, and the reason a settled rule has
exactly one home. **Nothing left in it is a rule.** What it still holds is the player
abilities that have no data yet, one cell that may be inert, two judgement calls the build
made, and the map of where advanced mode touches the code. Don't read it as a specification,
and don't implement from it.

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
in midfield and **every** arrangement has to cover its own side's (2026-08-16,
and before that only the side kicking off), so spreading two cards over a
three-space midfield would empty the middle and hold the coach in the window
(`coaching_finish_refusal`). That is why the function takes the zone. Packing
from a side's own end is what makes the deal and all five formations satisfy
that rule for free. **This is the standard deal only**; a formation change re-deals through
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
  what gates `crowded_candidates` -- see "Who runs back" below.
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
- **The kickoff space is the only thing that can hold a coach in the flow, and
  since 2026-08-16 it holds every coach in every window.**
  `coaching_finish_refusal` refuses Done until *this* side has somebody on
  *their own* kickoff space -- `MatchState.kickoff_space_for`, read off the
  rule rather than off the ball, since an arrangement is set in windows where
  the ball is elsewhere. It used to ask only the side kicking off the coming
  period, and only at setup and halftime; it is now a property of an
  arrangement, which is what lets a goal restart without the conceding side
  dropping somebody back and paying for it. Full time is exempt because it
  positions nobody (`offers_positioning`). An AI has no menu to be held in, so
  `cover_kickoff_space` does the same job at the end of its window.
  - **The standard deal and all five formations already satisfy it** -- a
    midfield packed from a side's own end always reaches that side's kickoff
    space, on every board -- so this costs a coach nothing until they use
    space positioning to empty it deliberately. Board 6 is the only board
    where the two sides cover *different* spaces.
  - **`pending_kickoff_fill` survives as a fallback, not as a rule.** A game
    saved before this landed can hold an arrangement that leaves the space
    empty, and both developers run the bot against their own saves.
- **`LEGACY_HALFTIME_STAGES` is not dead weight.** Halftime used to run
  substitutions and any-zone repositioning as two stages a side; a game saved
  in either resumes at that side's hub. `from_dict` reads the old
  `pending_substitution_*` keys for the same reason. Both developers run the
  bot from their own tree against their own saves, so a half-finished game
  outlives the change that renamed things.

## Sending a player

Three rules ask a coach to send somebody to the ball's space, and since
2026-08-16 they ask it the same way: **the nearest player either side of the
space, from any zone**. `MatchState.contest_candidates` is the whole of it --
see "Sending a player" in the living rules -- and the three are the maneuver
challenge (`eligible_challengers`), the loose ball (`loose_ball_candidates`),
and the pickup after an out-of-bounds ball, a ceded ball, a missed shot or an
avoided own goal (`begin_ball_recovery`, `recover_out_of_bounds_ball`). It was
four until 2026-08-18: the long High Pass contest **is** the loose ball now
rather than borrowing it -- see
[Loose balls and the board](#loose-balls-and-the-board).

- **Distance is the measure, and it always was -- the zone was a second gate
  on top of it.** Every one of these charges a token a space, so a defender
  two spaces away was being refused a challenge a defender four spaces away in
  the same zone was offered. Zone now decides where a player *lives* -- the
  arrangement, the run back, `position_meeple` -- and nothing about what they
  may be sent to do. `fielded_players_in_zone` is gone; don't bring it back.
- **Two candidates, and a tie is every player tied.** Two players the same
  distance off on the same side differ only in who they are, which is the
  coach's call, so the function returns them all rather than picking. It
  iterates `field_players` rather than the board or a set, because the buttons
  a coach is offered have to come back in the same order twice.
- **Anyone already on the space is a candidate at distance 0**, and is never
  actually sent: `automatic_challengers` filters them out of the pool (and
  would have nothing to filter otherwise), the High Pass contest forces them,
  and `eligible_ball_handlers` catches them before a pickup is asked for at
  all.
- **A challenge narrows to them, and this is the one place the wider pool is
  not the offer.** `MatchState.challenge_candidates` is
  `automatic_challengers() or eligible_challengers()`: a defender standing on
  the ball challenges, so **nobody may be walked in past them** (the author,
  2026-08-17). It is what the view builds from, what `choose_challenger`
  validates against and what `DinkyAI` picks out of, so the three cannot
  disagree about who is on offer. The other three rules keep the whole pool --
  a contest and a pickup have somebody on the space or they have nothing to
  ask.
- **Two branches are now guards rather than states.** An empty candidate list
  means a side with no meeples on the board, which `validate()` rejects -- so
  "nobody in the zone to challenge" and "neither side has anyone to send" are
  unreachable from a game that loads, and an unchallenged maneuver and an
  out-of-bounds ball are reached by declining and by nothing else. The
  branches stay: without them the flow builds a prompt with no buttons on it.
- **The walk-in is no longer bounded by geometry** -- up to eight spaces on
  board 9, which is past every player's defensive skill. That is the point of
  the decline, and it is why `DinkyAI` sends the *nearest* candidate in all
  four rather than the best. `choose_loose_ball_player` took the higher skill
  until this landed and now takes distance first; it needs the match to know
  one, which is why it grew a parameter.
- **A missed shot and an avoided own goal joined the pickup on 2026-08-24.**
  Both restart the ball on a space with no coverage guarantee -- unlike a
  goal, whose kickoff space every arrangement is required to cover -- so
  before this they fell through to `finish_maneuver_resolution`'s generic
  loose-ball check at the tail of the reset, which would have let the *other*
  side contest a position they never earned. `ScoreAttemptView.roll`'s missed
  branch and `run_own_goal_roll`'s avoided branch now both set
  `pending_ball_recovery = True` the moment the restart is decided -- the
  same pattern `apply_setup_pass_out` already used for an out-of-bounds
  Setup Pass -- so `begin_ball_recovery` asks the restarting side once the
  reset has settled, and asks nobody at all when the reset already covers the
  space, which the standard deal and every formation usually do.

## The maneuver with nobody to challenge it

A maneuver normally needs two players. When the defense has no challenger the
maneuver the offense picks succeeds outright -- see "Maneuvers" in the living
rules. `MatchState`'s `maneuver_uncontested` is the whole of it.

**Sending nobody is the way in, and since 2026-08-16 it is the only one.**
Walking in costs 1 token per space, and since 2026-08-12 paying it is a
choice. There used to be a second way -- the defense with nobody in the
ball's zone -- and the two were deliberately one state; the zone is no longer
the measure (see [Sending a player](#sending-a-player)), so a side with a
meeple anywhere on the board has somebody to send, and a side with none is a
match `validate()` refuses. The no-candidate branches are still there as
guards. `begin_uncontested_maneuver` is the only way in either way, so
nothing downstream has to know which happened.

- **Exhaustion is where the line is drawn**, which is why the choice is not
  offered to everybody. A defender already standing on the ball pays nothing
  to challenge, so there is nothing to weigh and nothing to refuse: they
  challenge, as they always did. `automatic_challengers` is that reading -- it
  is what `begin_uncontested_maneuver` refuses on -- and `may_decline_challenge`
  is the same fact from the defense's end, asked by `ManeuverChallengeView`
  before it builds the Send nobody button and by the prompt before it words
  one.
  - **Skipping the prompt is a count, not a flag.** `choose_action` applies the
    challenge unasked only when there is exactly **one** of them. Two is the
    defending coach's pick (the author, 2026-08-17), because a challenge is
    settled on defensive skill and the two differ only in who they are -- so
    the view is now built in a state where declining is refused, which used to
    happen only after a restart re-attached it to a stale prompt. That check
    still earns its keep for the same reason it did before.
    - **Both routes into a challenge read the count, and one of them used to
      read it as a flag.** `play_ai_turn` -- the AI on offense, so a *human*
      defending -- took `on_ball_space[0]` and sent it, picking for the coach
      off placement order in the one game where nobody else could. It asks the
      same `len(...) == 1` now. A rule about how many candidates there are has
      to be asked wherever candidates are counted, not only where it was
      written down first.
    - **The two prompts word themselves out of `challenger_prompt_ask`**, in
      `d12ball/formatting.py`: two defenders on the ball cannot be held back,
      so a prompt offering "or send nobody" offers what
      `ManeuverChallengeView` does not build. The AI's route said it
      regardless, which is what having the sentence twice buys you.
- **Which way it happened is read off the candidates, never stored.** Anybody
  still eligible to challenge means the defense was offered the challenge and
  passed, since a defense with nobody to send is never asked.
  `announce_uncontested_maneuver` and the "no defensive maneuver to pick" reply
  both word themselves from that, so nothing has to be persisted to word a
  message after a restart. Both branches survive the 2026-08-16 change even
  though one of them is now practically unreachable -- the wording asks the
  state rather than knowing the answer.
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

## The maneuver prompt

Both sides pick their maneuver off **one public message carrying both rows of
buttons**, and the click is answered ephemerally.
`ManeuverActionPromptView` is the whole of it.

It used to be two steps: a public prompt with a single "Choose Your Maneuver"
button that opened an ephemeral menu of the clicking coach's own cards. That
extra click existed because **an ephemeral message must answer that coach's own
interaction**, and only one of the two coaches is ever holding a live one when a
maneuver begins -- whoever picked Maneuver, or whoever picked the challenger.
The other had nothing for the bot to reply to.

**The cards were never the secret.** The twelve of them and the defeat cycle are
public information either coach may ask for at any time --
`/d12ball maneuver_reference` posts the hexagon to the whole channel. What has
to stay hidden is the **pick**, and that is hidden by the reply being ephemeral
rather than by the menu being private: Discord tells nobody else who pressed
what, and the prompt is never edited to say (see `close_maneuver_prompt`). So a
coach reading this message cannot tell whether the other side has clicked. The
extra click bought a round trip and nothing else.

- **`RulesEngine.maneuver_pick_sides` is the only answer to whose buttons get
  built**, and it is every side of this maneuver a *person* still picks for.
  Two things take a side off it, and both are settled before the prompt exists:
  an unchallenged maneuver has no defense to pick for, and **Dinky's pick is
  written into the match before the prompt is built** -- so a solo game's
  prompt is one hand and one row. It is read off persisted state alone, which
  is what lets a restart rebuild the identical view.
  - **It answers the mention line as well as the buttons.**
    `begin_maneuver_action_selection` builds `waiting_on` out of the same list:
    a coach named above the prompt and given no row to press would stall a game
    and nothing would catch it.
- **A side that has already picked keeps its buttons.** The message is
  deliberately never edited -- that is [the tightest rate-limit bucket in the
  game](#discords-rate-limits) -- so the buttons a restored view dispatches have
  to match the buttons sitting on the message. Taking a picked side's row away
  would leave those clicks answered by nothing. `pick` refuses the second click
  instead.
  - **Not greying them either**, for the same reason and one more: an edit that
    disabled a row would tell the other coach that side had answered. The "X
    has picked their maneuver" message says that already, deliberately and in
    its own message.
- **Authorization is checked before "already picked".** The other coach's row
  is sitting on the same message, so answering a click on it with "that side has
  already chosen" would say whether they had.
- **Each side gets its own rows and its own colour** -- offense red, defense
  green, the cards' and the reference hexagon's own two colours, so a coach
  finds their row without reading the labels. `even_button_rows` splits a hand
  into as few rows as Discord allows and then evenly across them: six advanced
  cards chunked at the five-per-row limit would read five and one. An advanced
  contested prompt is exactly five rows -- two a side plus the reference -- which
  is Discord's ceiling and worth knowing before adding a seventh card.
  - **The wording above the prompt names the colour by looking it up**, in
    `MANEUVER_ROW_COLOURS`, rather than by knowing which side a lone row
    belongs to. A one-row prompt is the *defense's* whenever Dinky has the
    ball, and `maneuver_prompt_wording` said "the red row" either way -- which
    sent a solo coach on defense looking for buttons that were not theirs. One
    table for the two names, so the sentence cannot come to disagree with the
    `danger`/`success` styles the buttons are built with.
- **The restart story got simpler, not more complicated.** The prompt is on a
  real message recorded in `turn_message_id`, so `on_ready` re-attaches it
  through `pending_turn_view` like any other view. The message-agnostic
  `add_view` registration the ephemeral menu needed (`restore_maneuver_menus`)
  is gone; [the shootout's two menus](#the-extreme-shootout) still need it and
  still have it.
- **The uploads halve.** One public hand image and one public field strip,
  against a hand and a field to each of two coaches. See
  [The maneuver cards](#the-maneuver-cards).

## A maneuver's identity is not its printed name

`match.offense_maneuver` and `defense_maneuver` hold a **key** --
`low_pass`, `double_team` -- and never a display name.
`maneuver_key` in `d12ball/components.py` is the slug, and every
dispatch table, button custom_id and comparison in the cog and the
views is keyed on it.

It used to be the name. That made a rename upstream a code change and
put a display string in every saved game, and the author renamed the
basic D2 card from "Steal Intercept" to "Steal" on 2026-08-18 -- which
under names would have silently broken a dozen comparisons, five
tutorial rails and every game saved mid-turn.

- **`legacy_maneuver_key` translates a game saved before the keys.**
  Almost every name slugs straight to its key, so only the one that
  does not is written down. Same tolerant shape as `player_board` and
  `tie_mode`: nothing writes a name any more, so it dies out on its
  own. Don't add a migration pass, and don't drop it until no
  half-finished game can predate the change.
- **`RulesEngine.maneuver_name` is the only way back to a name**, and
  it is only ever for wording. A caller that has a key and wants to
  print it asks; a caller that wants to *decide* something compares
  keys.
- **Relations are by rank.** `ManeuverDefinition.defeats_rank`
  replaced `defeats`, because since advanced mode each rank carries
  two cards -- the basic one and its counterpart -- and **rank alone
  decides** who wins (the author, 2026-08-18). Naming one of the two
  would be naming half a relation. `ManeuverCatalog.counterpart` is
  the pairing, looked up by rank rather than tabulated.
- **The importer resolves the sheet's `Defeats` name into that rank**,
  so the cycle is still data rather than something written into the
  code. It carries one alias -- the sheet renamed the row without
  rewriting its own four references to it -- which can be dropped once
  upstream catches up.

## Advanced maneuvers

Six more cards, one per basic card's rank, turned on by
`GameMode.ADVANCED`. See "Advanced maneuvers" in the living rules;
what is left open is in
[docs/advanced-maneuver-matrix.md](docs/advanced-maneuver-matrix.md).

**`RulesEngine.maneuver_tiers` is the only answer to who holds what**,
and the buttons, the hand image and the click that answers all read
it. Two things narrow it, and both are rules: a basic game is the
basic three, and **an unchallenged maneuver is always basic** (the
author) -- which is answerable at the moment a hand is drawn because
all three routes into the unopposed branch settle it before the
offense is prompted. That also makes declining a challenge a defensive
weapon rather than only a saving.

- **`advanced_effects_apply` is the whole of the outright rule**, and
  it is one condition: **the cards decided, not the dice.** A matchup
  the cards decided carries the winner's benefit and the loser's cost;
  a matchup the cards **tied** carries neither, and `resolving_maneuver`
  substitutes the basic counterpart so the skill test's winner
  resolves that instead. The two injury cases fall out of the same
  reading rather than being exceptions to it: an automatic loss of a
  tie carries nothing (it *was* a tie), and a skill test forced by the
  disadvantage still carries them (it was not) -- the author,
  2026-08-19. **Nothing is persisted for this**; it is read off the
  two stored keys, so a restart mid-effect answers the same way.
- **Each benefit is its basic counterpart parameterised, not a second
  function.** `apply_deflection`, `apply_steal`, `apply_pressure` and
  `apply_low_pass` each take a key and serve both cards on their rank.
  A change to what a deflection *is* reaches Clear for free, which is
  the point -- the two differ by a distance and a speed drop and
  nothing else.
- **Every cost bites inside the winning maneuver's own resolution**,
  which is why there is no cost dispatcher. `advanced_cost` names the
  card that was beaten and the winner's handler asks it: Clear's 2
  exhaustion and Double Team's shove are charged by the card that beat
  them, Intercept's uncontested reception is a branch of the High
  Pass, and Dribble Burst's is the first exception to "every turnover
  resets ball speed to 1". A generic "and then pay the cost" step
  would have to know where inside each effect it belonged, which is
  the thing the handler already knows.
- **`pending_effect_continuation` is what lets an effect reach past
  its own maneuver**, as `{"kind": ...}` -- the same shape
  `pending_injury_resume` uses and for the same reason. Two need it:
  Setup Pass sets the ball's speed and *then* picks the pass out, and a
  beaten Skilled Pass hands the defense an unopposed Low Pass once the
  steal has settled. A speed choice had always been the *last* human
  step of an effect, leading straight into
  `finish_maneuver_resolution`; `continue_effect` is the branch.
  - **The record is cleared by whatever applies the step, not by the
    dispatch.** A continuation is one more prompt and a coach may take
    hours over it, so between dispatching and the click that answers,
    this field is the only thing on the match saying what is owed --
    which is why `build_effect_choice_view` reads it *first*, ahead of
    the winner. Clearing it at dispatch (which is what `finish_cede`
    does with `pending_cede`, for a flow with no prompt left in it)
    would leave a restart in that window putting the speed choice back
    up and letting a coach answer it twice.
  - An unrecognised kind falls through to the ordinary end of a
    maneuver rather than stranding the turn -- and *that* branch does
    clear it, or the next speed choice in the game would find it still
    set.
- **`pending_double_team` is the two defenders, not a flag.** A won
  Double Team leaves both challenging the next maneuver, each adding
  their defensive skill, and what the following turn needs is *who* --
  a flag would leave it re-deriving "the nearest teammate" off a board
  that has moved since. `announce_new_play_reset` clears it, which is
  the one thing the card says ends it; `reset_maneuver` deliberately
  does not, since that runs at the end of the turn that set it.
- **"The teammate closest to where the play started" is read before
  anything moves**, by both the benefit and the cost. A moment later
  the handler has been shoved back two and the ball with them, and the
  nearest defender to *that* space can be somebody else. The cost's
  caller reads it before the pass moves the ball and passes it in,
  which is why `pay_double_team_cost` takes a partner rather than
  looking one up.
- **A Setup Pass is gated on the field, not on the roster** (the
  author, 2026-08-25). `RulesEngine.setup_pass_distances` offers 1 and
  3 -- and a Fullback's 4 -- whenever the space they land on is on the
  board, and **0 alone still needs a teammate**, since it means one
  sharing the passer's own space and a passer never receives their own
  pass. It used to offer only distances that reached somebody, which
  read the card as a set-up that either happens or does not and left a
  passer with nobody ahead of them unable to play it at all.
  - **A pass landing on nobody settles where it lands**, exactly as a
    Deflect's does: `apply_setup_pass` hands it to `begin_loose_ball`,
    which since 2026-08-26 settles every arrival by what is standing
    there -- see [Where the ball comes to rest](#where-the-ball-comes-to-rest).
    It pays `SETUP_PASS_CLOCK_COST` there, the card's flat 2 minutes,
    however far the ball actually travelled.
  - **That leaves one position a Setup Pass goes out from, and it is
    still a fourth `new_play=True` call site.** The card cannot
    overshoot, so `apply_setup_pass_out` is reached only where nothing
    is on the menu at all: the passer on the very last space of the
    field -- the one place even 1 space runs off the end -- with no
    teammate beside them. The other three call sites are the score
    attempt, a conceded own goal and the out-of-bounds loose ball.
  - **Dinky answers the distance through `choose_high_pass_distance`**,
    which is the same question now that a bad pass costs the ball: the
    longest that reaches a teammate, otherwise the longest available.
    A second policy would only be the same one written twice.
- **A role ability is inherited by rank, and what carries is the rule
  rather than the number.** Each sentence in `players.json` was written
  against one card and states a number, so read literally three of them
  are nonsense on their advanced counterpart: a Fullback's "ball goes
  back 2" is a *reduction* on a 3-space Clear, its "high pass up to 4"
  is a fourth number against a card offering 0/1/3, and a Playmaker's
  "may advance 2" was no bonus at all on a run to the end of the field.
  The author settled all three on 2026-08-19 -- **the Fullback's
  ability is +1 distance** (High Pass 3->4, Deflect 1->2, Clear
  3->4, Setup Pass gains a 4), and **the Playmaker's is one exhaustion
  token off a Dribble Burst**, which is the only ability that reads
  differently on the two cards of a rank. The Midfielder's +3 and the
  rank-D2 ball speed modifier were already uniform and needed no
  ruling.
  - **The Playmaker's stayed on the cost when the burst was bounded**
    (the author, 2026-08-26). The 2026-08-19 reading turned on there
    being no distance left to add to; a run of up to 4 has one, and the
    ability is still a token off rather than a fifth space. So the
    distances a Playmaker is offered are everybody's, and the discount
    comes out of the total in `apply_dribble_burst` -- named once
    beside the run rather than subtracted from each button's price.
  - **A Fullback's extra space is distance, not speed.** A Block
    Deflect of 2 has always cost 1 speed, so a Clear of 4 still costs
    3. `apply_deflection` keeps `speed_drop` as the card's own number
    rather than deriving it from the distance -- written the other way
    it read correctly until the Fullback was let near a Clear.
  - **The three cannot be matched out of the ability sentences and
    cannot live in `maneuvers.json`**, which the sheet import rewrites
    whole. They are `EXTRA_NOTES` entries in `d12ball/cards.py`, which
    say what the ability does *on the card it is on* -- the same escape
    hatch Steal's ball speed modifier uses, and for the same reason.
- **Dinky rolls its rank as it always has and picks the tier at
  random.** That is not a policy and is not meant to be one: an
  advanced card carries a cost as well as a benefit, and weighing the
  two is judgement, which Dinky makes none of. The alternative was
  Dinky never playing an advanced card, which leaves half of advanced
  mode unreachable in a solo game.
- **`EveryMatchupResolvesTests` is the guard worth keeping.** It walks
  all thirty-six pairings on all three boards through the real
  `resolve_maneuver`, for two coaches and against Dinky, and asserts
  almost nothing about what happens. Twelve cards reached from four
  directions apiece is a lot of branches nobody would think to build a
  fixture for; it caught two real bugs the day it was written.

## Who wins a maneuver

**`D12Ball.settled_maneuver_winner` is the only answer to that**, and it
returns the winning maneuver's **key** or `None` when a skill test still has to
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
  | `maneuver` | `begin_effect_resolution` | every maneuver in the game reaches it exactly once, decisive, unchallenged or through the skill test |
  | `skill_test` | `SkillTestView.roll` | before either branch, so a tie that re-rolls is in the record as well as the roll that settles it |
  | `shot` | `ScoreAttemptView.roll` | before `settle_score_attempt`, which awards the goal |
  | `own_goal_roll` | `run_own_goal_roll` | both outcomes: the rate needs the attempts as well as the concessions |
  | `injury_test` | `run_injury_test` | both outcomes, same reason -- `mark_injured` deliberately logs nothing, or a failed test would be in twice |
  | `goal` | `MatchState.record_goal` | beside the `GoalRecord`, which has no way to say *where in the run of play* |

- **Exhaustion is attributed, not logged.** `MatchState.add_exhaustion` adds to
  the open turn's own event rather than writing one apiece: a game makes around
  a hundred of those calls, and what a statistic asks is what a maneuver cost,
  never in what order the tokens were handed out. Every path that charges
  bottoms out there -- the cog's `apply_exhaustion`, the run back's own charge,
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
  ephemeral -- neither coach may see the other's -- so a restart cannot
  re-attach to them and `restore_shootout_menus` re-registers them
  message-agnostically. A view rebuilt that way starts empty, so a coach who had
  ordered five would come back to none if the order lived there. **These are the
  last two views that need that**: the maneuver pick used to be a third and went
  public on 2026-08-25 (see [The maneuver prompt](#the-maneuver-prompt)), so an
  order that could be shown publicly would take the trick out of the codebase
  altogether. It cannot -- an order is a real secret, where a hand of cards
  never was.
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
- **A shootout test costs no exhaustion and owes no injury checks either**
  (2026-08-15), which is the author's ruling and not a shortcut -- the rule for
  every other skill test read straight would give checks, so the living rules
  state the exception in both places. It is not one of the ways to gain a token,
  and an Exhausted shooter carries that into the shootout and out again
  unchanged. `finish_shootout_test` goes straight to `continue_shootout` rather
  than through `begin_injury_tests`.
  - **The `shootout_test` resume kind is still read and never written.**
    `dispatch_injury_resume` keeps the branch so a game saved between that roll
    and its tests finishes the way it started; nothing writes it any more, so it
    dies out on its own -- the same retirement `tie_mode` and `player_board`
    got. Don't drop it until no half-finished game can predate the change.

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
  from anywhere. Only the 2-space High Pass's set-up still checks it --
  `can_attempt_score` over `high_pass_receiver_candidates`, in `apply_high_pass`
  -- because it is the only set-up whose landing space can be short of range.
  There used to be a `set_up_shot_candidates` wrapping the two, which never had
  a second caller.
- **A 2-space High Pass that lands short of range is still received.** The range
  rule takes away the shot, not the catch. The set-up branch and the long-pass
  contest are the same landing space asked two different questions, so a pass of
  2 that is refused a set-up has to resolve as an ordinary pass rather than fall
  through to a contest it has never had to win.
- **An overshoot is the set-up the rule cannot bite**, whichever maneuver made
  it. A Deflect's puts the ball on the space closest to the offense's own
  goal and a High Pass's on the space closest to the goal they attack; both are
  as deep into the shooting team's range as the field goes. So neither puts a
  range check over its candidates -- a branch that can never be taken reads as
  if it could.
- **Nothing gates `begin_score_attempt` itself.** The rule is enforced where the
  shot is *chosen*: `PlayerActionView` omits the button (and `build_turn_prompt`
  says why), `choose_action` refuses a stale click, `DinkyAI` only ever shoots
  from the scoring space, and the 2-space High Pass's set-up asks
  `can_attempt_score`.
- **The board image draws where range begins**, in `draw_shooting_range_band`
  -- a labelled bracket under the field, one for each side's range and (on
  board 7 and 9) a third over the space in nobody's. It used to be a dashed
  line drawn straight through the spaces, which marked the same edge but said
  nothing about what it meant; the labelled bracket is the same marking
  `boards.py`'s printed field board already carried (`draw_shooting_ranges`),
  so the two now agree by construction rather than by two separate drawings
  of the same rule. `shooting_range_bands` reads `is_in_shooting_range` a
  space at a time, the same reading the print board's own version makes, so
  neither can drift from the rule the bot enforces. The rule is positional and
  the board is where both coaches read position.

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

- **A passer never receives their own pass**, which is the whole of
  `D12Ball.high_pass_receiver_candidates` -- `scoring_opportunity_candidates`
  less `active_player_id`. It is asked by all three High Pass branches (the
  overshoot's set-up, the ordinary 2-space one, and the long-pass contest behind
  both), because they have to agree on who the pass reached and the occupant
  list is in no particular order. It can **only bite on a pass clamped to 0
  spaces**: a High Pass moves the ball and not the handler, so nowhere else is
  the passer still standing on it when it lands. Stating it as a rule about
  every High Pass rather than about that one case is deliberate -- see the
  2026-08-12 entry in the rules log.
  - **That is the one overshoot that can set nothing up while the offense is
    still on the ball, and since 2026-08-24 it is not a free ride either.** It
    is neither loose (the passer is standing there) nor a contest (there is no
    receiver to fight for what they never let go of) -- but with nowhere left
    to throw it and nobody to throw it to, `apply_high_pass_out` sends it out
    exactly as `apply_setup_pass_out` already did, rather than letting
    `finish_maneuver_resolution` hand it straight back to the passer. The
    branch is read off `actual_distance == 0`, not `receiver_candidates`
    alone -- an ordinary loose ball landing on a genuinely empty space
    elsewhere on the field still goes through `finish_maneuver_resolution` as
    before. It is also why that function words a 0-space result rather than
    reporting "the ball moves 0 spaces forward", which no coach saw until this
    rule.
  - **It still costs High Pass's own 2 minutes**, which is why `apply_high_pass`
    carries a `distance_moved` apart from the `actual_distance` the result
    reports. Every maneuver's clock cost is flat and distance-independent
    (2026-08-16) -- 1 for everything but High Pass, 2 for it -- so this is no
    longer a minimum bailing out a clamped throw; it is the same cost every
    High Pass pays, whatever it moved. **Every clock argument out of that
    function is the first**; only the wording reads the second.
- **A coach is only offered a distance that fits on the field.**
  `MatchState.high_pass_distances` drops any that would clamp, because a longer
  pass landing where a shorter one already would is that pass at a
  disadvantage -- negative modifier, contest owed. `D12Ball.high_pass_distance_options`
  wraps it with the handler's own maximum (the Fullback's 4), and is the single
  home three things read: the menu `HighPassChoiceView` builds, what the AI
  picks from, and `choose`'s refusal of a click on a menu the ball has moved out
  from under. Those buttons carry no message id, so an older prompt in the
  channel does dispatch.
- **Dinky throws to the furthest teammate it can reach, not simply the
  furthest** (2026-08-18). `MatchState.high_pass_receivers_at` is the
  lookahead -- the before-the-throw twin of `high_pass_receiver_candidates`,
  excluding the passer for the same reason -- and
  `DinkyAI.choose_high_pass_distance` falls back to the longest available only
  when no distance reaches anybody. It is not a rules change; it is that the AI's
  own maximizing was working against it, and
  [where the ball comes to rest](#where-the-ball-comes-to-rest) sharpened the
  cost: a pass landing where the offense has nobody gives the ball up, so
  throwing as far as possible was giving it away as often as possible.
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
  `relative_flat_index` against the requested distance the way Deflect
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
after it -- is a question about how far away everybody is. Who a coach may
send is [Sending a player](#sending-a-player), the same pool a challenge and a
pickup use.

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
- **The headline is read off the position, not off what made the ball
  loose.** `build_loose_ball_headline` words an empty space and an occupied one
  differently, because they are different questions to the two coaches, and
  since 2026-08-18 both are loose. A caller passing its own `headline=` is
  saying the wording would be a lie, which is the High Pass's case and nobody
  else's.
- `ball_location_line` and `ball_space_label` in `cogs/d12ball_helpers.py` are
  the wording, over `space_label`. The line spells the zone out beside the code
  because "M2" alone means nothing to anyone not already looking at the board.

## Where the ball comes to rest

**What is standing on the space the ball lands on decides how it is won, and
only an empty space is a *loose ball*** -- the author, 2026-08-26. See "Where
the ball comes to rest" in the living rules. Three positions:

| On the landing space | What happens |
| --- | --- |
| Nobody | **Loose.** Each side may send a player after it, or send nobody. |
| One side only | **Theirs**, uncontested. No roll, and the other side is never offered a send. |
| Both sides | A **contest** between the players already there. Nobody else may be sent. |

That corrects the 2026-08-18 ruling, which made *loose* a fact about the ball
("nobody is in possession") rather than about the space, and so let a side walk
somebody in against a space the other side already held. Half of it was already
built: `restrict_to_occupants` landed on 2026-08-24 as Deflect/Clear's own
narrowing and **is** the rule above -- what was wrong is that it was a flag, so
the two paths that did not pass it kept the old behaviour.

- **The rule is unconditional and the flag is gone.** `D12Ball.begin_loose_ball`
  reads both sides' `loose_ball_occupants` and, when exactly one is empty, calls
  `match.decline_loose_ball` on it *before* `auto_resolve_loose_ball_picks`
  runs -- so that side is never put on the clock, `LooseBallChoiceView` is never
  built for them, and the occupying side resolves through the existing "sole
  occupant auto-contests, several -- coach picks" / "one side only, takes
  without a test" machinery with nobody left to contest against. Don't
  reintroduce a parameter for this: a call site that could opt out is exactly
  how the two wrong paths survived 2026-08-24.
- **A High Pass is the one exemption, and `is_high_pass` is already its flag.**
  The ball is high in the air, which gives players time to run at it, so a
  landing space holding only one side may still be contested by the other. That
  is a property of the pass and not of the space, which is why it rides on the
  same flag that carries the ball speed modifier rather than getting one of its
  own. Read **symmetrically** -- the author states it as the defense running at
  the passer's own teammates, and the justification is about the ball, so the
  mirror case is contestable too.
- **Each side's contestant is whoever of theirs is standing on the ball, and
  otherwise a player they may send.** `MatchState.loose_ball_occupants` is the
  first half and `MatchState.contest_candidates` the second;
  `RulesEngine.loose_ball_candidates` is `occupants or candidates` -- one of two
  pools and never a mixture, exactly the shape `challenge_candidates` has, and
  for the same reason. The second half is now only ever reached on an empty
  space or a High Pass.
- **The word is a rule, not decoration.** `contest_noun` answers three ways --
  "high pass", "loose ball", "ball" -- and `build_loose_ball_headline` the same
  three. The message the author caught called every arrival a loose ball *and*
  offered a send the occupancy rule had already taken away; both halves were
  wrong, and only in the case a coach was most likely to meet. "ball" rather
  than "contest" is what the sentences around it need: a coach "contests the
  ball", never "contests the contest". See
  [What a message says](#what-a-message-says) for the wording rules the same
  correction produced.
  - **Every message on the path asks for it, the result and the resume
    included.** `settle_loose_ball_winner` announced "wins the loose ball!"
    whatever had happened, so the sentence a coach read *after* watching two
    players roll for a space they were both standing on denied what they had
    just seen; `pending_turn_view`'s two loose-ball prompts said it too, in
    front of a coach about to act on the position. The noun is read with the
    rest of the position, before the fields the result clears.
- **`pending_loose_ball_on_empty_space` is persisted, and cannot be derived.**
  By the time a roll or a result is worded the contestants have been walked onto
  the space, so the position that decides the word is gone --
  `MatchState.begin_loose_ball` reads it at the one moment it exists. Same
  reason `pending_loose_ball_is_high_pass` is stored. A game saved before the
  field defaults to True, which is what every arrival was called before this.
- **The machinery keeps its `loose_ball_*` names.** Three positions share one
  flow, and renaming it would rename a persisted field and every custom_id
  already sitting in a channel. What a coach reads is what the correction was
  about.
- **A side with somebody on the ball may not withhold them**
  (`may_decline_loose_ball`), the same reading `may_decline_challenge` makes:
  declining is a refusal to pay a walk-in's exhaustion and they have no
  walk-in to pay for. `LooseBallChoiceView` does not build the Send nobody
  button rather than disabling it, and `decline` re-checks for a stale click.
  **That is also what keeps out of bounds an empty space's outcome alone.**
- **Skipping the prompt is a count, not a flag**, exactly as with the
  challenge. `auto_resolve_loose_ball_picks` puts up a **lone** player on the
  ball unasked -- there is nothing to ask -- and leaves two to the coach
  (2026-08-18, the same call as the maneuver challenge's).
  `build_loose_ball_prompt` words that case differently, because the question
  is which of them rather than whether to send anybody.
- **The passer is struck out of the offense's pool in a High Pass contest**,
  in `loose_ball_occupants` and nowhere else, so the pool, the decline and the
  auto-pick cannot disagree about who is standing there. It can only bite on a
  pass clamped to 0 spaces, which never reaches a contest -- stated anyway, for
  the reason `high_pass_receiver_candidates` states it.
- **A Deflect calls `begin_loose_ball` directly** rather than going
  through `finish_maneuver_resolution`. It knocks the ball out of possession
  whoever is standing there, so `check_for_loose_ball`'s question -- does the
  possessing team have somebody on the ball -- has an answer that does not
  matter. It also stops refreshing the board first, since `begin_loose_ball`
  posts one.
- **`check_for_loose_ball` has one detour now, not two.** Its guard still
  earns its keep: the maneuvers that leave the ball with a named player are not
  loose, and that is what it asks. What changed on 2026-08-26 is what happens
  *after* the detour -- a ball landing where only the defense stands is theirs,
  where between 2026-08-18 and then the offense could walk somebody in.

## What a message says

Three rules the author gave on 2026-08-27, after reading a turn back out of
a channel. They are about every message the bot posts, not only the ones that
produced them.

- **Say what the position is, never what it is not.** A ball coming down where
  one side is standing was announced "**Not loose.** ... so the ball is simply
  theirs" -- a sentence fragment that defines the position by the two it is
  not, in front of a coach who has to act on it. It reads "The ball comes down
  to a space where {team} has a player, so they get the ball." The other two
  arrivals were reworded with it; see
  [Where the ball comes to rest](#where-the-ball-comes-to-rest).
- **Don't answer a question nobody asked.** That same message closed with
  "nobody may be sent after it", and the contest's with "and nobody else may
  be sent" -- both denying an offer neither message had made. A coach reading
  a result is not owed a list of what the rules did not do.
- **A move that costs nothing says nothing.** `describe_exhaustion_gain`
  returns `""` for a charge of zero, where it used to say "was already there --
  no exhaustion cost", and "free of exhaustion" is gone from the new-play
  reset, the halftime restore and Double Team's second defender. Every move
  that *does* cost a token says so in that same line, so silence already
  carries the fact -- and "free" left a coach to work out what was free about
  it. **Callers join on the parts that are there** (`"\n".join(filter(None,
  ...))`) rather than interpolating, or the empty string shows as a blank line.

The subject is spelled out for a related reason: "It comes down on an empty
space" followed a sentence about a maneuver, so the pronoun read as the
maneuver. Nothing in a result message should have to be resolved backwards
through the message above it.

## The ball carrier

Possession is a team's, but the ball is a *player's*: a resolution that
leaves it with somebody in particular makes them the **ball carrier**, and
they take their side's next turn instead of the coach picking again off the
ball's space -- see "Choosing the handler" in the living rules.
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
  Deflect sets nothing either -- it makes a loose ball, and the contest
  names the carrier.
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
- **A Deflect that overshoots is neither.** It flips possession and goes
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
- **Who runs back is two questions, and `next_run_back_step` is the only
  reading of both.** It answers with a side and a list: one name means the
  player is settled and only the space is open, several means a stack has to
  send somebody and *the coach picks which* (2026-08-17). Those who must return
  -- `run_back_displaced`, everyone outside their own zone -- are answered
  before any stack, because a player coming home covers a space and a zone with
  nothing uncovered has no stack to break up. `run_back_movers` is the two
  together, asked only to find out whether a run back has anything to do at all.
  - **`crowded_candidates` offers the whole stack rather than picking out of
    it.** It used to keep whichever player the space's occupant list started
    with -- placement order, so arbitrary -- and hand the rest to the run back
    with nobody asked. One of them moves per pass and the cascade asks again,
    so a zone with two uncovered spaces is two questions rather than one
    silent pair of placements. The ball's holder is never a candidate, which
    is the run-back exemption read from the other end: a pair holding the ball
    between them is one candidate and no question.
  - **`apply_forced_run_backs` leaves an undecided stack out of its
    arithmetic** instead of zipping it into a space. A zone's displaced players
    may still be forced around it, and settling them can take the zone's last
    open space -- which dissolves the stack and saves the coach the question.
  - **The two questions share one message.** `RunBackPlayerChoiceView` asks
    which player and *edits itself into* `RunBackChoiceView` to ask which
    space, so the board uploaded for the first is the board the second is read
    off. That edit is the interaction-callback route, so it costs nothing out
    of the channel's bucket -- but it replaces the view wholesale, which is why
    the full-image link has to be rebuilt onto the new one by hand.
  - Neither pick is persisted. A restart reads the question back off the
    position through `build_run_back_view`, so a coach who had already answered
    the first is asked it again -- the same as a part-made Coaching Choice.
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
1, costing its flat space minute like any other maneuver even though nothing
travelled (2026-08-16).

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
- **A cede is a new play in everything but how it was bought**, and it arrives
  there without a reset of its own: both coaches take a window, and a window
  opens on its own coach's arrangement, so by the time `finish_cede` runs both
  sides are standing where a new play's reset would have put them. Don't add a
  `restore_assigned_positions` to make it look like one -- it would be a no-op
  over an arrangement the windows have already recorded.
- **The tail is the out-of-bounds pickup, not the loose-ball check.** The
  receiving side's arrangement covers their zones, not wherever open play left
  the ball, so usually nobody is standing on it; `finish_cede` sends them to
  fetch it at the usual token a space -- the nearest player either side of it,
  since 2026-08-16 (see [Sending a player](#sending-a-player)). Routing it
  through
  `check_for_loose_ball` instead would let the side that ceded contest the ball
  back -- and, with one of their meeples still on it, take it back
  uncontested, having bought a window for nothing. The author settled this on
  2026-08-10: "the team that gains possession has to send a player to the space
  where the ball was ceded." So `finish_cede` must keep deciding this itself --
  falling through to `finish_maneuver_resolution` with nobody on the ball would
  hand it to the loose-ball check, which is the reading that was rejected.
- **The clock cost rides on `pending_run_back_distance`, left at 1.** That
  field is what every tail step reads back for the clock, and the pickup spans
  a restart, so a cede has to say so there rather than pass it down a call
  chain. Ceding costs its flat space minute like any other maneuver
  (2026-08-16) despite nothing travelling -- `cede_possession` sets the field
  explicitly rather than leaning on the 1 `reset_maneuver` already leaves,
  so the value reads as a deliberate fact and not a coincidence.
- **Under last possession it ends the period**, in `begin_cede` and before any
  window opens, clearing `pending_cede` on the way out so the flag does not
  follow the game into the second half. That branch bypasses `finish_cede`
  entirely, so it charges the minute itself with `match.advance_time(1)`
  before handing off to `end_period` -- every turn of last possession is
  charged as usual, and this turnover is no exception.
- **Dinky never cedes.** `DinkyAI.choose_action` still answers shoot or
  maneuver, so in a solo game the option is the human's alone. Nothing about
  the flow assumes that -- an AI *receiving* a ceded ball runs its reply window
  through `run_ai_substitution_window` like any other -- it is just that giving
  the ball away is a judgement call and Dinky makes none.

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
  `TutorialBeat.choices` is the table and
  `D12Ball.tutorial_railed_option` is the one question the views ask,
  so a view adds a rail with one call rather than a branch.
  - **A rail names a value, except when it cannot.** The ball speed a
    steal may set is capped by the stealer's own defensive skill, and
    who does the stealing is not something the script fixes -- so
    `CHOICE_MAX` means "the highest offered" and `resolve_choice` takes
    the option list rather than a single value. That is also why
    `SpeedDeltaChoiceView` collects its targets before building any
    button.
  - **A rail matching nothing on offer is no rail**, rather than a
    prompt with every button dead. The script and the flow can only
    disagree by mistake, and a coach with nothing to press is a worse
    failure than a lesson that did not land.
- **Rails build the button disabled, never absent.** A lesson about the
  three cards in your hand cannot be taught by hiding two of them, and
  a coach should see that Shoot and Cede exist and read why neither is
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
    [Where the ball comes to rest](#where-the-ball-comes-to-rest)) the
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
  say what the game was created as.
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

- **`D12Ball.post_tutorial_note`** is the whole of it: post the note
  with a `TutorialContinueView`, and call `then` -- the continuation
  that was going to run right after it -- only when that view's one
  button is pressed. `then` receives the *click's* interaction, not
  the one the note was posted with, since everything after the click
  has to answer with that.
- **`stage_tutorial_beat` takes `then` as an optional parameter**
  rather than always gating, so the staging tests -- which call it
  directly and check only which note came out -- see the old, ungated
  behaviour when they leave it out. `send_turn_prompt` is the one real
  caller that supplies it, wrapping everything it used to do inline
  (the AI branch, the ball-handler selection, the ordinary prompt) in
  a nested `continue_turn_prompt`.
  `begin_maneuver_action_selection` and `offer_speed_choice` follow
  the identical shape for their own notes: the prompt-building code
  moves into a nested function, and `maneuver_note`/`speed_note`
  decide whether it runs straight away or waits on a click.
- **Not restart-safe, on purpose.** `TutorialContinueView` is never
  registered with `bot.add_view`, so a restart while one is up leaves
  it dead -- the same tradeoff the rest of the tutorial already makes
  for a lesson's own text (see the module docstring in
  `d12ball/tutorial.py`). The game itself is untouched; a coach whose
  Continue button stopped answering falls back to `/d12ball resume`
  for whatever it was gating, same as any other stuck prompt.
- **`COACHING_NOTE` is gated too, since 2026-08-27.** The tail of
  `begin_substitution_window` -- the arrangement restore, the AI window,
  and the human coach's menu -- moves into a nested `open_the_window`,
  and `post_tutorial_coaching_note` hands that to `post_tutorial_note`
  as the continuation (returning True to tell the caller it has taken
  over), the same shape as `offer_speed_choice`. It was left ungated at
  first on the grounds that the branch chain was hairy and the note
  fires once, late, outside the five scripted beats -- but an ungated
  note sitting directly above an interactive menu is exactly the case
  the Continue gate exists for, and the split (`coaching_window_note`
  was already extracted) makes the tail no worse to reason about.

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

## Why the cog is mixins

`cogs/d12ball/` is six mixin classes assembled into one `D12Ball` in
`__init__.py`, and the choice of mixins over collaborator objects is the whole
design.

- **These methods co-operate through the cog's own state and call each other by
  the hundred.** `self.foo(...)` has to keep working across every seam, and a
  mixin is the only split where it does, untouched. Turning those calls into
  explicit dependencies on collaborator objects is a far larger change and a
  different one -- don't start it by halves.
- **The seams are the author's, not invented.** The single file carried sixteen
  `# -- Low Pass ---` banners, and the split follows them. Each mixin is a
  contiguous run of the old file, so the moves are readable as moves.
- **The mixin order carries no resolution.** It is the order the file read in.
  No method is defined by two mixins, and `test_no_method_is_defined_by_two_mixins`
  in `tests/test_d12ball_package_shape.py` is what keeps that true -- a name in
  two of them means one is dead code, chosen by the MRO rather than by anybody.
- **`commands.GroupCog` comes last**, so the mixins sit ahead of it in the MRO.
  discord.py collects commands by walking the whole MRO (`CogMeta.__new__`), so
  a command or subgroup defined on a mixin registers exactly as one on the cog
  would -- verified against the assembled class, which has the same 221 methods
  and the same 17 app commands as the single file did.
- **The command module is `slash_commands.py`, not `commands.py`.** A submodule
  binds its own name into the package namespace, so `commands.py` would shadow
  `discord.ext.commands` in the very file that reads `commands.GroupCog`.
- **`pending_turn_view` moved whole, into `core`.** It is a flat, ordered
  dispatch chain whose ordering is load-bearing and mostly comments explaining
  why each branch sits where it does -- see "Recovering a stuck game". A second
  copy of that chain is the failure mode; splitting it is how you get one.

## Logging and the #logs channel

**Use `logging`, not `print`.** Every module gets its own logger
(`LOGGER = logging.getLogger(__name__)`) and `botlog.configure_logging()`
in `foolbot.py` sets the root logger up once, before anything logs. That is
also why `bot.run` is called with `log_handler=None`: discord.py otherwise
configures its own logger inside `run`, and with a root handler already
attached every library line would print twice.

Records at ERROR and above are mirrored into a Discord channel, so a crash
shows up in the server instead of only on the console of whoever is hosting
the bot. A bot told to post (`FOOLBOT_LOG_MIRROR=on` — see below; the
default is console only) finds or creates a channel called `#logs` on
startup, posts the record with its traceback in a code fence, and posts a
one-line notice naming the build it is running whenever that build changes.

Everything is optional and lives in `.env` next to `DISCORD_TOKEN`:

| Variable | Default | What it does |
| --- | --- | --- |
| `FOOLBOT_LOG_MIRROR` | off | `on` lets this bot post to the channel at all |
| `FOOLBOT_LOG_LEVEL` | `INFO` | Console threshold |
| `FOOLBOT_LOG_CHANNEL_LEVEL` | `ERROR` | Discord threshold; `off` disables the mirror |
| `FOOLBOT_LOG_CHANNEL_ID` | — | Mirror into exactly this channel |
| `FOOLBOT_LOG_CHANNEL_NAME` | `logs` | Channel to find or create, when no id is set |
| `FOOLBOT_LOG_GUILD_ID` | first server | Which server hosts the channel |
| `FOOLBOT_DEPLOY_NOTICE` | on | `off` stops the "now running this build" notice |
| `FOOLBOT_HOST_NAME` | machine name | What the deploy notice calls this host |

Things to know before changing any of it:

- **Posting to the channel is opt-in, per bot.** `FOOLBOT_LOG_MIRROR`
  is off unless a checkout's own `.env` sets it, and nothing reaches
  `#logs` without it — neither an error nor a deploy notice. The same
  repository is run by more than one bot: the real one on its host, and
  a test bot on a developer's machine out of a clone or a worktree of
  the same code. Both used to bind the channel and both posted, so it
  carried a test bot's tracebacks beside the ones somebody could act
  on. `.env` is untracked and per checkout, so a clone starts silent —
  which is the right way round: a real bot gone quiet after a redeploy
  is one line in a file its host already needs, where a test bot
  posting is noise in the one channel that is supposed to be
  actionable, and nobody running it has any reason to notice.
  `mirror_enabled()` in `botlog/channel.py` is the switch, read in
  exactly two places (`install_mirror` and `announce_startup`, the two
  entry points that reach the channel) rather than inside
  `ensure_log_channel`, so a bot that is not posting attaches no sink,
  lowers no log level and shells out to no git.
  An unrecognised value is **off**, unlike `FOOLBOT_LOG_CHANNEL_LEVEL`,
  which falls back to `ERROR`: the level's failure mode should be
  saying too much, and this one's should be saying nothing.
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
  state file is local, so when two opted-in hosts deploy into the same
  `#logs` the posts interleave: the same commit gets announced once by each,
  and neither stream is the repository's history. Each notice names its host
  so they can be told apart. Don't read the channel as a changelog — and
  don't read a host's absence from it as that host being behind, since a
  checkout without `FOOLBOT_LOG_MIRROR` announces nothing at all.
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
    buttons are public (see [The maneuver prompt](#the-maneuver-prompt)), so an
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
| `FOOLBOT_D12BALL_ARCHIVE_EXPORT_DIR` | unset | Where `/debug export_archived_games` writes a game before deleting its channel; unset, that command refuses outright — see "Freeing up the PBD Archive" |

## Working on the board image

The board image is the bot's main output, so look at it. Don't rely on the
test suite to tell you a rendering change is right — it only asserts the
output is a PNG of the expected dimensions.

```bash
python3 scripts/render_sample.py --home purple --visiting teal --out board.png
python3 scripts/render_sample.py --home-formation 2-3-1 --board-size 6  # stacked meeples
python3 scripts/render_sample.py --coaching home       # a coach's own half
python3 scripts/render_sample.py --field               # the field on its own
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

**The last board of a game rides on the result, and is the one board that is
not pinned.** `announce_game_over` posts it under the whistle (or under the
shootout that settled it) for the reason a loose ball's board is posted with
its announcement: by full time the persistent message has scrolled hours up
the channel, and the final position is exactly the thing nobody should have to
go looking for. It is the usual render-once-upload-twice -- the persistent
message is settled from the same bytes, which is why neither `end_period` nor
`continue_shootout` refreshes it themselves any more. Pinning stays the new
play's alone: a pin here would be the one at the very bottom of a channel
nobody is playing in again.

**There are three board images. Two are drawn, and the third is cut out of
one of them.** `render_match_image` is the 2200px one everybody sees;
`render_coaching_image` is the 1280px half-field a
[Coaching Choice](#the-coaching-choice) keeps up, and those two do not share a
layout. The coaching image carries one row of meeples instead of two, so at the
match image's width it arrives in Discord as an unreadable sliver. **It is
deliberately not mirrored for the visiting coach**: the zones keep their real
names and the spaces their real numbers, so V1 is the same space on both images
and on the board the coaches are looking at.

**`render_field_image` is the third, and it is a crop rather than a third
layout.** The field alone -- both sides' meeples, the ball, the space codes and
the shooting range edges, with no title, jumbotron, assignment cards, team
boards or benches -- for the message under a coach's maneuver cards (see "The
maneuver cards"). It draws the match image's canvas, calls the same
`draw_board`, and cuts the board's rectangle plus `FIELD_MARGIN` out of it, so
it is made of the same pixels as the board both coaches are reading and cannot
drift from it: a change to a space, a meeple or the ball token reaches it
without being made twice. It is the one board image that is **not** upscaled --
`OUTPUT_SCALE` is there so a 2200px board holds up when a client blows it up,
and a strip a third of that height is shown at its own size or smaller.

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

`d12ball/cards.py` draws the twelve maneuvers as cards. They exist because the
selection d6 they replaced made a coach hold the rules in their head: the die
said "3-4" and the coach had to remember that was Dribble Advance if they had
the ball and Steal Intercept if they did not, what it beat, and which role
changed it. The cards won outright on 2026-08-17 -- the die is off the rules
altogether now.

**One layout serves two things, on purpose.** `render_maneuver_card` is the
print-ready face for the tabletop game -- 2.5 x 3.5in at 300dpi, plus one
shared back -- and `render_maneuver_hands` puts every hand in play side by
side, which is what rides on the maneuver prompt. A coach who has played at the
table and a coach playing by Discord should be reading the same card, so neither
gets a design of its own.

```bash
python3 scripts/render_maneuver_cards.py --out cards/ --sheet  # print-sheet.png
python3 scripts/render_maneuver_cards.py --bleed   # 1/8in for a print shop
python3 scripts/render_maneuver_cards.py --hands   # every prompt image the bot sends
```

- **The hand replaced a paragraph per maneuver.** `build_maneuver_choice_text`
  listed each maneuver's effect and matchups next to the buttons; every word of
  it is on a card and in the same place on each one, so a coach now compares
  three cards instead of reading three sentences. It went with the change --
  don't reintroduce it alongside the image.
- **The hand is a side's three cards *and the shared back*, and the "Maneuver
  Reference" button is back beside them.** The back carries the defeat cycle,
  it is public information either coach may look at whenever they like, and at
  the table it is face up on the deck in front of them -- so
  `render_maneuver_hands` draws it as the last card. That was taken as reason
  enough to drop the button, and it was not: the back is one card among four at
  a third of print size, where the hexagon is the picture a coach actually
  reads a matchup off. `ManeuverActionPromptView.show_reference` posts it
  ephemerally, so the cost is a click and an upload only when somebody wants
  one. Both it and `/d12ball maneuver_reference`, which posts the same image to
  the channel, go through `build_maneuver_reference_file`.
  - **Ephemeral for the pick's reason, not its own.** The hexagon hides
    nothing -- answering in the channel would just tell the other side that
    this coach is still choosing.
  - **One button for a prompt holding both sides.** Its custom_id carries the
    game and no side, since the hexagon is the same picture for either coach.
- **Every hand is drawn once in `D12Ball.__init__`**, like the maneuver
  reference image and for the same two reasons: startup is the one place a
  render can block the loop harmlessly, and the alternative is drawing up to
  thirteen cards on every maneuver. Nothing about a card depends on the match,
  so they cannot go stale. `build_maneuver_hand_file` re-wraps the bytes per
  send, because uploading a `discord.File` consumes the stream inside it.
  - **Six images, not four**, keyed by the sides on the prompt *and* by the
    tiers they may play -- offense alone, defense alone, or both, against the
    basic three or all six of an advanced game. Which sides is
    `RulesEngine.maneuver_pick_sides` and which tiers is
    `RulesEngine.maneuver_tiers`, the same two questions the buttons under the
    image ask. **The reference hexagon is keyed by tier the same way** (see
    below): a hand's own `tiers` says which back it needs,
    `MANEUVER_TIER_ADVANCED` in it or not, so a hand and its back agree without
    a second question being asked.
  - **Both hands on one image, not one per side.** Discord lays two attachments
    on a message out side by side, which would halve the width of both. Nothing
    is given away: the twelve cards and the defeat cycle are public information
    either coach may ask for at any time. Where the back is drawn it rides on
    the last side's block rather than starting a row of its own, or it would be
    a row one card wide and the image would arrive as a tall ribbon.
  - **Each side's block is captioned -- "OFFENSE HAND" / "DEFENSE HAND", in that
    side's own colour** (`HAND_HEADINGS`, `OFFENSE_COLOR`/`DEFENSE_COLOR`). The
    two rows sitting one above the other read as one grid of cards otherwise,
    and a coach has to find *their* row before reading a label. `lay_out_hand`
    takes a `headings` list parallel to `blocks` and reserves a band above each
    captioned block's first row; a block with no heading (the lone card back,
    which has fewer headings than blocks because it shares the last side's
    block) reserves nothing. The player's name and team are deliberately *not*
    on the image -- the mention line right above the prompt already names both
    coaches, and putting names on the cards would make the hand depend on the
    match, which is exactly what the `__init__`-time render avoids.
  - **A basic contested prompt drops the back** (the author). Both basic hands
    together *are* the whole game -- all six cards, each carrying its own
    beats/ties/loses row -- so the hexagon is the same six relations drawn a
    second time, for the width of a card. Every other case still earns it: one
    hand (an unchallenged maneuver, or a solo game against Dinky) shows half the
    cycle, and an advanced prompt's back is the two-tier hexagon, which is what
    says the twelve cards resolve as six ranks rather than as two unrelated
    cycles. It also leaves basic's two hands as two clean rows of three instead
    of a ragged four and three. The "Maneuver Reference" button is still there
    for anyone who wants the hexagon, which is why dropping it costs nothing.
  - **Seven cards do not fit one row.** Discord scales an inline image to the
    message's width, so a row of seven arrives at about 75px a card against
    131px for a row of four. `HAND_MAX_COLUMNS` is 4, and anything past it
    wraps -- which keeps every card the width a coach already reads.
- **The hand is drawn at a third of the print card's width.** Discord scales an
  inline image down whatever it is sent, so the extra pixels would only be
  payload -- and this send is once per maneuver, not once per coach. The
  abilities are small print at that size, which is what the full-image link on
  the message is for. That link is the webhook route, not the channel's edit
  bucket; see "Discord's rate limits".
- **The field goes under the hands**, drawn by `render_field_image` and sent by
  `D12Ball.post_field_image`. What a maneuver would do depends on where
  everybody is standing, and the persistent board has usually scrolled up the
  channel by the time a turn resolves.
  - **A message of its own, not a second attachment on the prompt.** Discord
    lays two images on one message out side by side, which would show a field
    the width of the whole board at half the width of a phone. It also keeps
    the prompt's link pointing at the cards -- `build_full_image_button` reads
    the *first* attachment, and "View full image" under a hand means the hand.
    Both sends are the webhook route, so neither competes with the board for
    the channel's edit bucket.
  - **It is rendered per maneuver, unlike the hand**, because it is the position
    and so is different every time. It carries a full-image link of its own for
    a stronger version of the hand's reason: a field is the whole width of the
    board in a strip a fifth as tall, which is the smallest thing the bot sends
    inline.
  - **Losing it must not lose the pick**, which is already up and clickable by
    then, so the send is wrapped the way `add_full_image_button`'s is.
  - **The High Pass distance prompt carries it too**, and is the one place it
    is an attachment on the prompt rather than a message of its own. Choosing
    2, 3 or 4 is the same question the cards are read against -- how far is the
    end of the field from here -- and there is no second image on that message
    for Discord to lay it out beside. Riding on the prompt is what lets
    `HighPassChoiceView.choose` take it away with `attachments=[]` in the edit
    that answers the question, so a strip showing the ball where it was
    *before* the pass does not outlive the pass. See "A High Pass that runs out
    of field".

- **Nothing on a face is written in the script.** The effect, the time cost and
  the beats/ties/loses row come from `maneuvers.json` through
  `load_maneuver_catalog` and `cards.matchup_rank_groups`; the abilities come
  from `players.json`. So a card cannot claim a rule the bot does not play, and
  an import is carried onto the cards by re-running this rather than by
  editing them.
  - **Each column names the rank it faces, not one maneuver.** Every column
    used to narrow to the card's own tier -- naming only the basic opponent on
    a basic card and only the advanced one on its counterpart -- on the
    reasoning that rank decides and each rank carries one card per tier, so
    the second name was the same relation read twice. That reads backwards on
    an advanced card: naming only its own tier's opponent makes the twelve
    maneuvers look like two cycles with no relation between them, which is
    exactly wrong when a tie on the cards resolves as the basic pair (see
    `tie_note` below). `matchup_rank_groups` names the rank instead --
    `O2`/`D1`/etc, coloured the opposing side's colour -- with **both** tiers'
    names under it, basic in ink and advanced in its own colour. This is true
    of a basic card as well as an advanced one: what a basic card beats is
    still a rank, and that rank still has an advanced card on it once
    advanced mode is in play.
  - **The row's own height is measured, not a fixed constant.** It used to be
    sized for a name long enough to wrap to two lines, which left every card
    whose names were shorter than that -- almost all of them -- a band of
    blank space under its own column. `matchup_content_height` counts the
    actual wrapped lines at the row's own name size (22, large enough that
    every maneuver name in the game still fits one line in a column this
    wide) and `render_maneuver_card` sizes the row to that, the same way it
    already sizes the abilities band to `laid_out_abilities`' measured
    height. The room either measurement frees goes to the effect band
    between them.
- **Which roles a card lists is mostly matched, not tabulated.** A role is on
  the card when its ability sentence names that maneuver, which is why the
  Fullback is on both High Pass and Deflect, carrying its whole sentence
  to each. The sentence is never cut down here -- see "Every ability is
  imported twice". A new ability that mentions a maneuver reaches its card
  without anything in the script being touched.
  - **The match is on whole words, not substrings.** It was a substring while
    every maneuver name was two words; the author renamed the basic D2 card to
    "Steal" on 2026-08-18, and "steal" is inside "Steals the ball when
    resolving Pressure" -- so the Defender's ability, which is Pressure's,
    silently appeared on Steal's card as well.
  - **No role ability names an advanced maneuver**, and that is the data being
    honest rather than a gap: the sheet's `Advanced` ability column is empty
    for all thirty-six. What an advanced card carries instead is the one thing
    settled about how it resolves -- `tie_note`, which says a tie resolves it
    as the basic card on its rank with no advanced effect, and that a skill
    test forced by injury still carries them. The counterpart it names is
    looked up by rank rather than written down.
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
  - **`EXTRA_NOTES` is keyed by rank in practice**: the ball speed modifier is
    on Steal *and* Intercept, since the sheet lists it against both rows and it
    is what decides that rank's skill test either way.
- **The strip diagram is what a card can say that a die face cannot**, so it
  carries the geometry and the effect text carries the wording. A basic card is
  drawn on the standard seven-space board with the ball on the third space,
  which is the only position from which every basic maneuver fits: a High Pass
  of 4 lands on the last space and a Fullback's Deflect of 2 on the
  first. **An advanced card is drawn on the nine-space board** with the ball on
  the fourth, because Clear drives the ball back 3 and Dribble Burst runs it 4
  forward -- 4 either way once a Fullback is near a Clear, which the seven-space
  strip has no room for. `STRIP_GEOMETRY` is the pair, per tier, and the nine-space board is a
  real board rather than a strip invented to fit.
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
  the same two colours. **An advanced card is a distinct shade, not a tint of
  the basic one** -- a darker red/green rather than a lighter or darker version
  of the same hue, since a basic and its advanced counterpart sit side by side
  in the reference image and back to back in the print run, and two cards that
  read as the same colour under different lighting is exactly what a coach
  must not confuse.
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
- **The back is keyed by tier -- `render_maneuver_card_back(catalog, bleed,
  tier=...)`.** `MANEUVER_TIER_ADVANCED` (the default) is one back for all
  twelve: a coach holding both sets in advanced mode must not show which side
  of the ball -- or which tier -- they are reading, and the offense there
  holds six. `MANEUVER_TIER_BASIC` draws six nodes with one name apiece
  instead: a basic-mode coach's hand is never anything but the three basic
  cards, so there is no tier to hide, and a name with no counterpart stacked
  under it reads larger in the same circle. `render_maneuver_hands` picks
  between them off its own `tiers` argument -- `MANEUVER_TIER_ADVANCED` in it
  or not -- so a hand and the back riding along with it can't disagree about
  which a coach is holding.
  - **A node is a rank**, and in advanced mode carries the two cards on it,
    basic name over advanced, split by a hairline. Rank alone decides who
    beats whom, so the hexagon is six nodes however many cards there are -- a
    second back was never available, and two cycles laid on top of each other
    is not a hexagon.
  - **The rank itself (O1, D2, ...) sits outside the circle, straight above
    or below the node** -- whichever side faces away from the ellipse's own
    centre -- in the node's own green/red. A node already carries two names;
    putting the rank inside it as well would be a fifth line in a circle
    sized for four. Outside it, the badge is what tells a coach the two
    tiers resolve by rank rather than as twelve maneuvers with no relation
    between them -- the same reason `render_maneuver_reference_image`
    carries one now (see below). **It used to sit out along the spoke from
    the ellipse's centre through the node instead**, which for the four
    off-axis nodes pushed it toward the card's corners -- close enough to
    the edge that the label's own width ran past it. Vertical is the
    direction every node has clear room in, since the hexagon already
    clears the header above and the caption below. The two caption lines at
    the foot of the card were pushed lower to clear the D1 badge below the
    bottom node, which still sits on this same vertical line.
  - **One size for all six nodes, and it is the tightest of them.** With one
    name to a node the tightest fit was a single long word and capping there
    shrank every other node for nothing; with both tiers on a node all six are
    four lines of much the same length, so the tightest is a real constraint.
    `CYCLE_LABEL_MARGIN` went from 8 to 24 for the same reason: the outer two
    of four lines sit where the circle curves away hardest, and at 8 the
    longest cleared the chord by under two pixels a side.
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
- **The header's corner names the tier, not the die faces.** It printed
  "die 1-2" while the cards and the selection die had to coexist, then "BASIC
  MANEUVER" while there was only one set; it now reads the card's own tier,
  and is **the one thing on a card that tells the two sets apart** -- the back
  cannot, and must not.
- **The effect text's size is searched, not set.** The effects run from Block
  Deflect's twenty words to Double Team's seventy against a band that is
  whatever the strip, the matchups and the abilities leave behind. A fixed size
  fitted the short cards and ran Double Team's paragraph straight over three
  bands at once, silently, because nothing measured what it had been given.
- `cards/` is generated output and is gitignored, like `board.png`.

### The player cards

`d12ball/player_cards.py` draws the roster as cards -- one a player, poker
size at 300dpi, the same as a maneuver's and out of the same `Pen`, palette
and `print_sheet`.

```bash
python3 scripts/render_player_cards.py --out cards/players --sheet
python3 scripts/render_player_cards.py --team orange --bleed
```

- **It follows the bot's own card, not a design of its own.** Name, the two
  skills in `CARD_OFFENSE_COLOR` and `CARD_DEFENSE_COLOR`, the role, the
  portrait, inside the team's colour -- `build_player_card` in `render.py` is
  what a coach playing by Discord is looking at, and a coach at the table
  should be reading the same card. `ROLE_INITIALS` is shared for the same
  reason: the two letters in the badge are the two letters on the meeple's
  card in the channel.
- **What the print adds is the ability, and it is the full sentence.** The
  bot has the roster and the rules commands a click away; a card on a table is
  the whole of what its coach has, so the sentence goes under the portrait.
  Never `ability_short` -- see "Every ability is imported twice" --
  and `D12BallPlayerCardTests` greps the module to keep it that way.
- **The ability is measured before anything is drawn, and the portrait takes
  what is left.** Its length is the one thing on the card the layout does not
  choose, so the header and stats are pinned to the top, the ability band to
  the bottom, and the picture gets the middle. That is silent when it goes
  wrong -- a longer ability squeezes the portrait rather than overflowing --
  which is why the suite asserts a floor on the slot rather than only that a
  card renders.
- **A portrait prints at about 190dpi and that is deliberate.** The art is the
  bot's own, around 400px, and there is no larger source, so `PORTRAIT_MAX_SCALE`
  lets it up to 1.6x and no further: kept to its native size it would print
  smaller on a 2.5in card than the bot draws it on a phone.
- **A portrait in `d12ball/images/player_images/` is a cut-out, and new art has
  to be one.** These are JPEG paintings on a white studio background, and a
  cut-out that leaves any of it behind shows twice over: as a pale box behind
  the player on the dark images (`render_matchup`, and anywhere a portrait is
  posted on its own), and as a faint checkerboard on the printed card, because
  the background is not flat white but the JPEG's 8x8 blocks.
  `scripts/recut_player_portraits.py` is the cut, and the roster was put
  through it on 2026-08-12: background goes wherever it is light and
  *colourless*, which is what keeps the white jersey numbers and the white net
  a goalkeeper stands in -- paint carries a tint, a studio wall does not.
  Reaching the edge of the image is not the test, since most of what was left
  behind is walled in: between a tentacle and an arm, or in the holes of a net.
  - **It is a dry run unless told otherwise** -- `--in-place`, or `--out` to
    look first -- because what it overwrites is tracked art. It repeats itself
    until a pass clears nothing, so what comes out does not depend on how often
    it has been run; a pass drops pixels as it scans, which the pixels it has
    already passed never saw. `D12BallPortraitRecutTests` asserts every tracked
    portrait is already settled, which is the check a new painting fails.
  - **Look at a new portrait on black, not on white.** White is exactly the
    background that hides this. The printed card is white, which is why the
    fault survived the cards being looked at, and the dark matchup image is
    what showed how much of it was still there.
- **`Pen.paste` resizes straight to the supersampled canvas.** The
  supersampling is there because Pillow does not antialias the shapes the cards
  are drawn out of; a photograph put through it would be resampled twice for
  nothing.
- **A team sheet is three across**, not the maneuvers' four: a team is nine
  players, and nine poker cards in a 3x3 come out at about 8 x 11 inches --
  a page. Print it at 100% on A4, or borderless on letter, or the cards come
  off the printer undersized.
- **The back is the player's advanced version, and it is the one thing here
  waiting on the rules.** Not a shared back like a maneuver's: player cards are
  dealt face up and sit on the field and team boards all game, so there is
  nothing to hide -- the other side of the card is the same player in advanced
  mode. Advanced mode is unspecified and the sheet's `Advanced` ability column
  is empty for all thirty-six, so `render_player_card` draws a face and the
  script prints one-sided; see "Blocked or deferred" in the rules log. What
  that costs when the column fills is the ability band read from the advanced
  ability, a side marker in the header, and a duplex-mirrored back sheet --
  the front is already the whole of the rest of the card.

### The printed boards

`d12ball/boards.py` draws the three boards the tabletop game is played on --
the **field board**, the **jumbotron board** and a coach's **team board** --
print-ready at 300dpi. **Tabloid (11 x 17) is the default now**, not A3 --
the field board portrait, the other two landscape; see `PAPERS` and
`DEFAULT_PAPER` for why tabloid rather than A3 is the one a home or copy-shop
printer actually stocks.

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
  rows of eight (`CLOCK_COLUMNS`), two a half, and every track clears
  `MIN_TOKEN_INCHES`;
  `cell_inches` is that measurement, reported by the CLI and asserted by
  `D12BallJumbotronTests`. The field board got the whole of that space back,
  which is what makes a space tall enough for two sides' meeples --
  `FieldGeometry.space_inches`, asserted the same way. It is the split the bot's
  own board already makes: a jumbotron is the state of the match, the field is
  the position.
- **The three token supplies are on the jumbotron for the neighbouring
  reason.** `TOKEN_SUPPLIES` is the exhaustion stock and the two markers it
  turns players into, as silos rather than as a tally: a player's own tokens are
  stacked on their card, which is where the bot draws them, so what had nowhere
  printed to live was the pile they come out of.
  - **A silo is `SILO_INCHES` and carries no words at all** -- a token wide,
    half again as tall, with the token's own art printed at the bottom as the
    base of the stack. It is a place to stand pieces rather than a cell to
    read, and a caption would be naming a piece the coach is holding a copy of.
    Being a fixed measurement rather than a share of the panel is the point: a
    piece does not get bigger because the sheet did. It is still capped by the
    room under the label, so a smaller paper shrinks it instead of running it
    off the panel, and `cell_inches` measures it against `MIN_TOKEN_INCHES`
    like the tracks.
  - **The art is `render.py`'s own token PNGs**, so a coach at the table and a
    coach reading a line of text in Discord see one icon -- see
    `scripts/render_condition_tokens.py`, which draws them, and note that the
    loaders in `render.py` thumbnail to 26px and cache there, which is why
    `load_token_art` opens the file itself. A missing file leaves the silo
    empty rather than failing the board.
- **No die value is printed anywhere, and since 2026-08-17 that is the rule
  rather than a divergence from it.** Maneuvers are chosen with the cards, so
  the two selection d6s are off the team board and the head coach cell lists
  the maneuvers by rank (O1, D2) instead of by face -- **a row is a rank with
  both its cards on it**, the basic name in ink and its advanced counterpart
  under it in grey. Three rows a column however many cards exist: listing them
  per card would print two O1s with nothing saying they are the same rank, in a
  panel sized for three. The author retired
  them from the rules outright, so the living rules no longer mention them
  either -- see the dated entry in the rules log.
  **The data and the code have not caught up.** `basic_rules.json` still
  defines `head_coach_dice`, `TeamBoardDefinition` still holds them,
  `maneuvers.json` still carries `die_values`, `ManeuverCatalog.offense_for_die`
  / `defense_for_die` still map a face to a maneuver, and `DinkyAI` still picks
  its maneuver by rolling a d6 through them. None of it reaches a coach, so
  retiring it is a code change and not a rules one -- but the sheet still has
  the column, so an import will keep writing it until the author drops it
  upstream. `draw_die_slot` reads `team_die` alone and says why, and a test
  greps the module for `offense_die`/`die_values` because the data is still
  right there to pick up again by accident.
- **The team board is landscape and holds two panels, not one.** Dropping the
  three zone areas onto the field board (see "The zone-assignment rows" below)
  left a single row -- the bench, the back bench and the head coach -- short
  enough that a match's two coaches share one sheet, cut in half, rather than
  each wanting a whole one: `render_team_board` draws the same panel twice,
  stacked over the sheet's own short side. **Landscape, not portrait**, and
  deliberately the opposite of the field board: stacking over the *short* side
  (11in) leaves every column a real card's width of room over the long side
  (17in), where stacking over the long side would leave the row only the short
  side to divide three ways -- not enough for a fanned poker card, measured.
  `card_slot_inches` is what says whether a panel holds a real card -- the CLI
  prints it, and `TeamBoardGeometry` sizes the header and the footer in fixed
  inches rather than as a share of the panel, which is what a header this much
  shorter than the design it came from needed: a title sized to the *sheet's*
  width came out taller than a header a third its old height, the day this
  landed. `D12BallTeamBoardTests` asserts a panel's slot clears a real card at
  A3 and at tabloid alike now -- both hold real cards, which is new: the three
  zone areas were what cost tabloid the 0.7in it used to come up short by.
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
- **Zones keep their real names on the field board's own assignment rows**,
  not the team board any more -- see "The zone-assignment rows". A coach's own
  goal is the home goal for one of them and the visitors goal for the other,
  and the field board is read by both, so the areas read HOME ZONE / MIDFIELD
  / VISITORS ZONE exactly as the bot's coaching image does -- HOME THIRD /
  VISITORS THIRD on the 9-space board, the only one where the three areas
  (H/M/V) are all equal (see "The field" in the living rules, and the
  2026-08-24 entry in the rules log; not to be confused with `FONT_GOAL_ZONE`,
  which labels the actual goal beyond the edge of the board). The team board's
  own formation strip is relative, and it says so. `--teams` colours a board
  per team and changes nothing else.
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

### End zones

`draw_end_zone` gives each goal its own zone, American-football style, beyond
H1 and beyond the board's last V space -- not squeezed into either one's own
space, because both are already full of meeples under the standard deal (see
"Formations and occupancy"). It is drawn in the margin between the board and
the canvas edge, so `GOAL_ZONE_WIDTH` is whatever that margin leaves once
`GOAL_ZONE_EDGE_MARGIN` (to the canvas edge) and `GOAL_ZONE_GAP` (to the
board's own outline) are taken out -- there is no spare canvas to grow it
into without widening the board itself.

- **"GOAL" runs the zone's length in the defending team's own color** --
  the home team's to the left of H1, the visitors' to the right of the
  board's last V space -- rotated 90°, the way a real end zone's lettering
  reads sideways on a field running left to right. Letters are spaced apart
  by `GOAL_ZONE_LETTER_SPACING`, on top of the font's own advance, because a
  four-letter word at a font size that fits the zone's width reads as a
  small cluster rather than something that fills a tall zone.
- **The visitors' end zone is rotated a further 180°** (`angle=270` on
  `draw_end_zone`, the author's call) from the home end zone's -- a real
  field's two ends face opposite directions rather than both reading the
  same way. The coordinate math for where the "O" (and the ball standing in
  for it) lands after rotation was verified empirically against Pillow's
  actual `rotate(90)`/`rotate(270)` output, not derived on paper -- a sign
  error here is silent, not a crash.
- **A blank d12 stands in for the "O" itself**, not a separate emblem placed
  over the whole word: the letter is left undrawn and its slot remembered,
  so the ball can be centered exactly there once the word is rotated. It is
  fully opaque and sized to the letter it replaces (`ball_radius`, computed
  from the "O"'s own advance and the word's cell height) rather than a fixed
  constant, so it cannot end up visibly smaller than the letters around it.
  The "12" on it is rotated the same angle as the word, so it reads in the
  same orientation rather than sideways against it.
- **The jumbotron and both team boards now span the field's full width,
  end zones included** (`FIELD_FAR_LEFT`/`FIELD_FAR_RIGHT`, `JUMBOTRON_LEFT`/
  `JUMBOTRON_RIGHT`), rather than stopping at the board's own edge and
  leaving the end zones looking like they belong to nobody.
- **`BENCH`/`BACK BENCH` position off the team name's own measured width**,
  not a fixed offset -- a species team's name (`Fire Demons`, `Telekinetics`)
  is wider than a color team's and was landing underneath "BENCH" rather
  than beside it. `TEAM_BOARD_BENCH_MIN_X`/`TEAM_BOARD_BACK_BENCH_MIN_X` are
  what a short name already left in place, so nothing shifts for the common
  case.
- **The printed field board carries its own end zones now**, `draw_field_end_zones`
  in `boards.py` -- the print counterpart of `draw_end_zone`, not a second
  drawing of the same pixels: it is a different rendering stack (`Sheet`
  rather than a raw canvas) at a different resolution (300dpi rather than the
  bot's fixed 2200px), so the geometry and the font-fit are worked out fresh
  rather than shared. `FieldGeometry` narrows the strip itself to
  `strip_left`/`strip_right`, reserving `end_zone_width` plus a gap on each
  side for it; `left`/`right` stay the full content width for the header, the
  direction arrows and the shooting-range bracket, which read the wide pair
  same as the bot's own jumbotron and team boards span its end zones. **It is
  drawn in ink, not a team's colour** -- the field board is a template for the
  tabletop game with no match to read a team from, unlike the bot's own board,
  which always has one.
  - **`end_zone_width` is a tight fit, not a generous one**, and tighter still
    since the field board went portrait to make room for the zone-assignment
    rows (below): the strip now divides an 11in width instead of a 17in one,
    so every inch an end zone takes is an inch a space cannot have. Don't grow
    it without checking `test_a_space_is_big_enough_to_stand_meeples_on`, whose
    width floor is 1.0in now, not the 1.5in a landscape sheet could promise.

### The zone-assignment rows

A card row for each zone -- HOME ZONE, MIDFIELD, VISITORS ZONE (HOME THIRD /
VISITORS THIRD on the 9-space board) -- above the strip for the visiting
coach and below it for home, on the field board itself
rather than on the team board, which used to carry them. `draw_zone_assignment_rows`
and `draw_zone_assignment_cell` in `boards.py` draw them; `FieldGeometry`'s
`visiting_zone_top`/`_bottom` and `home_zone_top`/`_bottom` are where.

- **That is the whole reason the field board is portrait (11 x 17) rather than
  landscape.** A zone row needs a real 3.5in card's worth of height, twice
  over (once for each coach), which the sheet's 17in length holds without
  crowding the strip; the strip's own spaces pay for it instead, coming out
  under an inch wide on the 9-space board rather than the 1.5in two meeples
  side by side would ask for on a landscape sheet. The author's own call,
  made knowing that cost -- see `FieldGeometry`'s own docstring.
- **The visiting row is rotated 180 degrees cell by cell, not the row
  reordered.** The two coaches sit on opposite sides of the table, so a row
  that reads upright to home reads upside down to visiting -- rotating each
  cell the other 180 degrees turns it upright *for them* without touching
  which column is which: HOME ZONE (or THIRD) is still the leftmost cell in
  both rows, directly under and over the strip's own Home column, so a coach
  reading either row left to right reads the same zone order the strip does.
  `draw_zone_assignment_cell` draws the whole cell upright on its own small
  canvas and rotates the finished picture when it is the visiting row, rather
  than working out where flipped text and flipped dashes land by hand.
- **The dashed guides inside a row are a visual cue, not a slot count.** This
  is a staging area a coach fans any number of cards across before assigning
  them to numbered spaces, not a fixed set of areas the way the strip's own
  spaces are -- `CARDS_PER_AREA` (three) is borrowed from the team board's own
  areas for the guide only, and nothing here enforces it.
- **The caption is dropped rather than shrunk past legibility.** "cards
  assigned to this zone" fits next to MIDFIELD's own width; HOME ZONE/THIRD
  and VISITORS ZONE/THIRD are narrower, and `draw_zone_assignment_cell` measures whether
  it fits before drawing it rather than shrinking the font until it does --
  a caption nobody can read is a worse failure than one left off.
- **The header was rebuilt to stack rather than sit side by side**, in the
  same change: `draw_field_header`'s title on the left and its note on the
  right used to overlap in the middle on anything narrower than the old
  landscape sheet, which the portrait sheet always is. Both are wrapped to
  the sheet's own content width and stacked in one left-aligned column now,
  which cannot overlap regardless of paper size or how long the wording runs.

### Fonts

Fonts are bundled in `d12ball/fonts/` and loaded by absolute path. **Do not go
back to looking them up by bare filename.** `ImageFont.truetype("Arial.ttf")`
searches the host's font directories, and the same typeface is filed under a
different name on macOS, Windows and Linux, so no list of bare names works
everywhere. When every name misses, Pillow's `load_default()` returns a face
pinned to size 10 that ignores the requested size, and every label on the
board silently collapses to tiny text. That was a real bug; the tests in
`D12BallFontTests` exist to keep it from coming back.

**A second family, Racing Sans One, is bundled the same way** for the goal
zone's own "GOAL" lettering (`load_goal_zone_font`) -- an uppercase, slightly
slanted display face, picked over several others tried in the same slot
(DejaVu Bold read as too plain, Anton's condensed width didn't leave room to
also space the letters out, Bungee read as too blocky) for the author's own
taste, over the same bundled-path-first fallback chain and falling back to
DejaVu Bold rather than Pillow's built-in face. Its OFL license is
`RacingSansOne-OFL.txt` in the same directory, alongside the DejaVu one.

`render.py` builds its font objects at **import time**, so a running bot keeps
whatever it resolved at startup. Restart after any render change.

## Team colors

**Eight teams along two axes, since the 2026-08-17 reshuffle.** The
original four **color** teams (Orange, Teal, Purple, Slime) went from a
fixed nine-player roster each to a mixed one -- 3 of their own species
plus 2 of each other -- and the four **species** teams that mix was
drawn from (Fire Demons, Cyborgs, Telekinetics, Oozes) became rosters of
their own: the pre-reshuffle grouping, unchanged in membership, just
under a new `Team` key. A coach may now field a player under either of
two identities. `Team` in `d12ball/game.py` holds all eight, and
`TEAM_PAIRS` (plus the `paired_team()` helper next to it) is the one
source of truth for which color and which species share a hex --
`TEAM_COLORS[Team.FIRE_DEMONS] = TEAM_COLORS[Team.ORANGE]`, and so on,
because Orange *was* Fire Demons' own color before the reshuffle mixed
its roster. `COLOR_TEAMS`/`SPECIES_TEAMS` are the two four-tuples, for
anything that needs the axis rather than the pairing (the team picker's
two button rows, mostly).

Each team's color is still one hex value, defined once as `TEAM_COLORS`
in `d12ball/render.py`, and every place a team's color is drawn -- card
borders, the skill numbers and name on a card, board tokens, the matchup
image's `team_color`, and the coaching image -- reads that dict rather
than carrying a hex value of its own. **No new hexes were added for the
species teams** -- `TEAM_COLORS` fills them in from `TEAM_PAIRS` after
the four color entries, so there is still exactly one hex per color
anywhere in the code.

| Team | Hex |
| --- | --- |
| Orange | `#FFA500` |
| Teal | `#008080` |
| Purple | `#9e4dff` |
| Slime | `#66FF00` |
| Fire Demons | same as Orange |
| Cyborgs | same as Teal |
| Telekinetics | same as Purple |
| Oozes | same as Slime |

- **A team's name for display is `team_display_name(team)`, in
  `d12ball/game.py`, never `team.value.title()`.** `str.title()` doesn't
  turn an underscore into a space -- `"fire_demons".title()` is
  `"Fire_Demons"` -- which was a real, live bug the moment a team's
  value carried one. Every call site that used to write `.value.title()`
  on a `Team` now calls this instead. It lives next to `Team` itself
  rather than in a cog module, because `d12ball/components.py` needs it
  too and cogs import from `d12ball`, never the other way around.
- **A player's team is no longer the player's to carry.**
  `PlayerDefinition` in `d12ball/components.py` has no `team` field --
  dual roster membership is the whole reason for this change, and a
  player belonging to two rosters at once cannot coherently have one
  intrinsic team. `players.json` is a flat `"players"` table (36
  entries: name, role, species, stat_overrides, keyed by id) plus a
  `"teams"` table (8 entries, `{"player_ids": [9 ids]}`) that resolves
  ids into it -- so a dual-membership player's record is written once,
  not twice. `load_player_catalog` builds every `TeamDefinition` from
  the same shared `PlayerDefinition` objects, and `TeamDefinition`'s
  existing "exactly 9 unique players" check is unchanged, holding
  independently for every one of the eight rosters.
  - **`MatchState.team_for_player(player_id)`** is the one answer to
    "which of this player's two rosters is *this match* fielding them
    as" -- checked against `field_players` plus both benches, the same
    roster-membership test used elsewhere in the match logic. Every
    display call site that used to read `player.team` calls this
    instead (`format_role_bracket` and its ~90 callers, the matchup/
    score-attempt `challenge_side` builder, the injury-die render, the
    board's card borders and meeple tokens) -- most already had a
    `match` or `setup` in scope, so this was mechanical at nearly every
    site. Two real bugs surfaced doing this sweep, both silently
    assuming a card's own `.team` always matched whichever side it was
    on, which stopped being true the moment dual membership existed:
    `d12ball/render.py`'s space-occupant stack grouping and
    `cogs/d12ball.py`'s `/ref` command side-detection. Both now check
    board/roster membership directly instead.
  - **A message names a player through `D12Ball.player_label`**, which
    is `format_role_bracket` with the two arguments that never vary
    already filled in: the emoji dict is the cog's, and the team is
    always `match.team_for_player`, since the definition cannot answer
    it. Ninety-odd sites spelled all three out, which put the same
    forty characters of lookup in front of every player's name in the
    codebase and was the whole of why two files carried eighty-odd
    lines past 100 columns. `player_id_label` is the same thing for a
    caller holding a card id rather than a definition.
    `format_role_bracket` itself is still right for a caller with a
    `TeamSetup` rather than a match, which already knows the side.
    Not to be confused with `CoachingView.player_button_label`, which
    is the name on a *button*: the position instead of the team emoji
    (every card in that flow is the clicking coach's own), cut to
    Discord's 80-character limit.
- **A player's id is `{slug(name)}_{role}`, not team-prefixed.**
  `hellguard_fullback`, globally unique, because a player's own color
  team is no longer part of their identity -- it can't be, when they
  have two. The old scheme was `{old_color}_{slug(name)}`
  (`orange_hellguard`); see the legacy-migration Gotcha below for what
  that means for a game saved under it.
- **A team may not play its own pair, and the reason is the color.**
  `TEAM_COLORS` gives Fire Demons Orange's own `#FFA500`, so that one
  match would draw both sides' cards, meeples and tokens in the same
  color -- and the board is where a coach reads which meeples are
  theirs. `TeamSelectionView.excluded_teams` (`cogs/d12ball_views.py`)
  drops a chosen team's `paired_team()` from the other side's options,
  the same way it already dropped the team itself, and the AI's random
  pick is filtered the same way -- nobody is holding Dinky's buttons,
  so that pool is the only check a solo game has.
  - **It is not a rule about shared rosters, and must not be rewritten
    as one.** Every other color/species matchup shares players too --
    a color team is 3 of its own species plus **2 of each other**, so
    it overlaps all four species teams and the pairing is only the
    largest of the four. Those matchups are offered and are meant to
    be: the shared players are fielded twice, once a side. See "One
    player, both sides" below.
  - **Enforced at the picker, not in `MatchState` or `D12Ball`.** Every
    path that creates a match reads
    `game.player_1_team`/`player_2_team`, and those are only ever set
    through the picker. Don't add a second enforcement point in the
    data layer: two places checking the same rule is how they drift
    apart. What holds the one place up is
    `test_every_matchup_the_picker_offers_builds_a_match`
    (`tests/test_d12ball_coin_toss.py`), which walks every pair the
    picker will offer and builds the match the coin flip is about to
    build.

- **The team-picking step is now its own screen, not shared with game
  settings.** Eight teams need two rows a side (a color row and a
  species row) where four needed one, which leaves nothing for the
  mode/board-size/AI-opponent buttons that used to share the view.
  Settings moved to their own step -- costing nothing new, since
  `CoinFlipView` already carried them alongside the flip button with
  rows to spare. A normal game's two sides still share one screen,
  whichever human clicks picks their own side; a **test game** (one
  person playing both sides) used to show both sides' rows at once and
  now prompts Player 1 then Player 2 in turn on the same message, each
  getting the full two-row budget rather than splitting it.
- **The `team_*.png` application emoji (`d12ball/images/emoji/`) are a
  second copy of the same colors, and the only one that has to be.**
  They are uploaded to Discord's Developer Portal separately (see
  `TEAM_EMOJI_NAMES` in `cogs/d12ball_helpers.py`) and shown next to a
  coach's name in chat, so they cannot read `TEAM_COLORS` at request
  time the way a rendered board can. A color change here means
  recoloring the matching PNGs, or the ring-and-letter emoji a coach
  sees stops agreeing with the color the board draws them in. The four
  species emoji share their paired color's ring for the same reason the
  boards do, so their letters were picked to stay distinct from all
  eight teams' initials: **F**ire Demons, **C**yborgs, **K** for
  Telekinetics (Teal already has T), **Z** for Oozes (Orange already has
  O). `TEAM_EMOJI_FALLBACKS` gives each a themed unicode emoji (🔥🤖🔮🫧)
  distinct from the four plain colored circles, so the bot reads
  correctly before the four new PNGs are uploaded -- which, like the
  original four, is a manual Developer Portal step nothing here can do.
- **Changing a team's color is `TEAM_COLORS` plus its emoji, and nothing
  else.** No other module should hold a team's hex value of its own --
  that duplication is exactly what let the two drift apart before. A
  species team's color is inherited through `TEAM_PAIRS`, so changing a
  color team's hex moves its species team's color with it for free;
  there is nothing to keep in sync by hand.

## One player, both sides

A player belongs to two rosters -- their color team and their species
team -- so **any color side meets any species side holding 2 or 3 of the
same people**. Those are played as two cards: the same person, in two
kits, exhausted, injured, substituted and sent about independently, and
free to challenge each other. Only the [paired teams](#team-colors) are
refused a fixture, and that is about the color they share, not the
players.

Everything in a match is keyed by a **card id**. It is the catalog
player's own id for the home copy and `duplicate_card_id` -- that id
plus `DUPLICATE_CARD_SUFFIX` -- for the visiting one, both in
`d12ball/components.py`. `catalog_player_id` maps a card id back, and
is a pure function of the string rather than a lookup on the match, so
anything holding a card id can resolve it.

- **Distinct ids are what make the two copies separate players of the
  game**, and that is the whole reason for the scheme. The board, both
  benches, the exhaustion counts, `injured`, the injury queue,
  `assigned_positions`, the shootout orders and every button's
  custom_id go on saying "this player" with one string, exactly as they
  did at four teams. The alternative was making all of them carry a
  side as well.
- **One suffix level is enough and always will be.** Two rosters can
  share a player and a match has two sides, so a third copy has nowhere
  to come from. `TeamDefinition`'s "9 unique players" check holds the
  other half of that up.
- **The visiting side is the one that carries the suffix**, applied in
  `create_standard_setup` through its `duplicate_ids`, which
  `MatchState.standard` fills from `PlayerCatalog.shared_player_ids`.
  Two teams on one axis share nobody, so it is empty for every match
  before the reshuffle and most of them since -- a home side's ids are
  always the catalog's.
- **`PlayerCatalog.player_by_id` hands back a definition carrying the
  card's own id**, not the catalog's. This is load-bearing: some ninety
  call sites resolve a card id to a `PlayerDefinition` and then read the
  id back off it to ask `match.team_for_player(player.player_id)` which
  side the card is on, and a definition answering with the catalog id
  would name the home copy every time -- wrong emoji, wrong color, on
  every message about that player. `player_index` in `d12ball/render.py`
  aliases both forms the same way, since the renderer indexes that dict
  in a dozen places.
  - The two copies are the same person, so they draw the same name,
    role, skills and portrait. **What tells them apart is the team
    color**, which is read off the match -- which is also why the
    paired teams cannot meet.
- **Anything walking a *roster* and asking the match about each player
  has to come through `TeamSetup.card_id_for`**, since a roster is the
  catalog's and a match is keyed by card. `/ref`'s roster listing is the
  one caller today; it was reading meeple positions under catalog ids,
  which for a duplicated visiting side finds the home copy's meeple or
  nothing at all.
- **`tests/roster.py` translates too.** `fielded` and `benched` name a
  player by role off the catalog on purpose -- see "The test suite" --
  so they are exactly the helpers that have to know which id this match
  holds that player under on that side.
- **The way to be sure this is transparent is to force it.** Making
  `MatchState.standard` suffix a visiting side's *whole* roster and
  running the suite puts a duplicate card through every flow the tests
  cover -- maneuvers, run backs, coaching windows, shootouts, saves,
  renders -- rather than only through the ones that thought to build an
  overlapping match. It passed clean when this landed, and it is a
  two-line patch worth re-running after anything that touches ids.

## Player species

A player's species and their team are two different things as of the
2026-08-17 roster reshuffle, where each color team became 3 of its own
associated species plus 2 of each other. `PlayerDefinition.species` in
`d12ball/components.py` carries it, read off a `Species` column by
`scripts/import_d12ball_players.py` the same way `Role` is --
lowercased and validated against a closed set (`EXPECTED_SPECIES`).
`SPECIES_TEAM` in the same script maps each species to its own team key
(`fire_demon -> fire_demons`), the way `Team` already named a color-team
row; add a species to both `EXPECTED_SPECIES` and `SPECIES_TEAM` (and a
color pairing to `TEAM_PAIRS`) together if a fifth is ever themed in --
there is no fifth color to pair it with today.

- **It is optional on load, unlike `role`.** A `players.json` written
  before the column existed still loads -- `load_player_catalog` reads
  it with `.get("species", "")` -- because the file is regenerated
  wholesale by re-running the import rather than migrated in place, and
  nothing forces both developers to have re-imported before pulling a
  commit that reads a new field. An empty species is not a fourth kind
  of species; it means the data predates the column.
- **It is no longer flavor data on its own -- it is what a species
  team's roster is drawn from**, and what the legacy-migration Gotcha
  below reconstructs a pre-reshuffle id from. Nothing about basic-mode
  rules reads it; it decides roster membership, not a mechanic.

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
- **Four things archive a channel, and only one of them is a person asking.**
  The startup sweep in `on_ready` files away every finished game it can reach,
  `start_rematch` files the old game away on its way out, `/d12ball
  abandon_game` files away a game nobody is going to finish, and the
  **Archive button** beside Rematch on the full-time message is the pair who
  are not playing again saying so. That button is why the sweep is no longer
  the only way a finished game reaches the archive without someone abandoning
  a game that had already ended. Its gate is `may_administer_game` -- either
  player, or anyone with `manage_channels` -- deliberately wider than the
  rematch's players-only gate, since filing a channel away commits nobody to
  playing anything.
  - **A view rebuilt straight after a move must be *told* it was archived.**
    `RematchView` takes an `archived` override for exactly this:
    discord.py's `TextChannel.edit` returns a **new** channel object and
    leaves the cached one alone, so `bot.get_channel(...).category` is only
    corrected when the `GUILD_CHANNEL_UPDATE` event lands. Both of
    `refresh_buttons`' callers rebuild in the same breath as the move, so
    reading the state back off the cache drew the button live again. Don't
    replace the override with a cache read -- the tests in
    `tests/test_d12ball_full_time.py` hold the cache at the pre-move category
    on purpose, which is what the live client does for that moment.
    `game_channel_is_archived` is still the right question everywhere else
    (the first post, and the startup re-arm), and answers False for a channel
    it cannot see: the move is idempotent, so a button offered needlessly
    costs a no-op where one withheld leaves a pair with no way to archive.

## Freeing up the PBD Archive

A category holds at most 50 channels, and PBD Archive only ever grows --
nothing un-archives a game -- so a long-lived server eventually hits
`400 Bad Request ... Maximum number of channels in category reached (50)`
the moment the next game tries to archive. `/debug export_archived_games`
is the way out: write everything a finished game and its channel know to
local disk, then delete the channel, which is the only thing that actually
frees a slot in the category.

- **Exported, not merely archived.** Archiving moves a channel and keeps it
  forever, on the theory that the channel *is* the record -- see "Game
  channels" above. Freeing a category slot needs the channel gone, so this
  command is a deliberate exception to "abandoning archives, it does not
  delete" (see "Recovering a stuck game" below): it deletes on purpose, and
  only after writing the record down somewhere else first.
- **The export has to land before the channel dies, never after.**
  `gamesaves/d12ball/archive_export.write_game_export` is called and
  checked for success before `channel.delete()` is even attempted; an
  `OSError` there leaves that game's channel and save record completely
  untouched; a game moves on to `save_games` only once its channel is
  actually gone. Losing a channel Discord will never give back over a
  write that could be retried is the one failure mode this whole feature
  exists to avoid.
- **Four files a game, mirroring what a coach could have looked up while
  the channel was alive**: `game.json` is the exact record `save_games`
  already writes for it (`game.to_dict()`, so it carries the whole
  `MatchState` too); `board.png` is the final position, rendered the same
  way `render_match_png` always has -- best-effort, since a game abandoned
  before it ever had match state has no board to draw, and a render
  failure there costs the picture and nothing else; `transcript.jsonl` is
  every message the channel ever held, oldest first, one JSON object a
  line; `attachments/` is every file any of those messages carried,
  downloaded there and then rather than left as a URL. Discord's
  attachment links are signed and expire (see "The 'View full image'
  button dies after 24 hours" under Gotchas) -- a transcript that only
  recorded the URL would go quietly unreadable long before anyone opened
  the export.
- **No Google Drive API call exists anywhere in this bot.** "Export to
  Google Drive" means `FOOLBOT_D12BALL_ARCHIVE_EXPORT_DIR` points at a
  folder Google Drive is already syncing -- on the live host, a folder
  inside the mounted `K:\` letter the whole checkout already runs from
  (see "Two of those machines"). `archive_export_dir()` reads it the same
  opt-in-by-`.env` way `FOOLBOT_LOG_MIRROR` does: unset means the command
  refuses outright rather than deleting anybody's channels with nowhere to
  put what it took from them, which is also what keeps a fresh clone or a
  developer's own test checkout from ever running this by accident.
- **A manual command that clears the whole category, oldest game first.**
  `limit` is 1 to 50, defaulting to 50, because **50 is what fills the
  category** -- a command whose entire purpose is making room in a full
  one should be able to empty it in a single run. Oldest `game_number`
  first, because any archived channel freed makes the same room and there
  is no other reason to prefer one over another.
  - **It was capped at 20, defaulting to 5, on a misreading of the delete
    limit.** Deleting a channel is two per ten minutes and **per
    channel**: `channel_id` is one of the four major rate-limit
    parameters (`discord.http.Route.major_parameters`), so fifty
    different channels are fifty separate buckets, not one queue two
    deep. Only a repeat against the *same* channel is rationed, which is
    what `CHANNEL_DELETE_RETRY_DELAYS` is for. This is the mirror of the
    board-edit bucket, where `message_id` is **not** major and so every
    message in a channel shares one -- the same table read for two
    different ids, which is why "check `discord.http.Route`" is the
    standing instruction rather than "remember which".
  - **What a full run does cost is time**, and it is unbounded by
    anything here: a channel's whole history plus every attachment in it,
    fifty times over, where a single board is close to a megabyte. It
    outlives the fifteen-minute interaction token, which is why the
    summary already falls back to the console -- and why
    `write_game_export` logs a line per game, so a long run is legible
    while it is still running.
- **Gated to Administrator, narrower than `/debug reset_channels`'s
  `manage_channels`.** Both delete channels, but this one also downloads
  and holds a copy of everything the channel ever said before it does --
  more is riding on trusting whoever is allowed to run it, so it gets the
  narrower default. Either gate is only Discord's *default*; a server can
  widen or narrow it per-role in Integrations settings.
  - **A permission gate belongs on the `debug` group, not on a
    subcommand, and a subcommand that wants a narrower one has to check
    it in its own body.** Discord carries
    `default_member_permissions` and `dm_permission`/`contexts` on a
    top-level command only, and discord.py's `Command.to_dict` fills
    those keys in `if self.parent is None` -- so
    `@app_commands.default_permissions(...)` and
    `@app_commands.guild_only()` on a `@debug.command` set the
    attributes, read correctly from Python, and are left out of the
    payload entirely. Both of these commands shipped that way for two
    releases and were runnable by every member of the server. The group
    now carries `manage_channels` for the pair, and
    `export_archived_games` re-checks `guild_permissions.administrator`
    itself. `test_the_permission_gate_rides_on_the_group` reads the
    payload rather than the attribute, which is the only way to see it.
  - **The Administrator check is the one refusal ahead of `confirm`.**
    Somebody who may not run this command should be told that and
    nothing else -- not walked through what it would have done, and not
    handed the export path. Every *operational* refusal still comes
    after confirm.
- **A dead interaction diagnoses itself, in `defer_or_report`.** Both
  commands here acknowledge through it rather than calling
  `interaction.response.defer` directly. Discord discards an
  interaction nothing has acknowledged within three seconds, and the
  defer is then a 404 (10062, "Unknown interaction") raised out of the
  command's **first line** -- which reads as a bug in the command and
  cannot be one, since nothing of ours has run yet. Deferring earlier
  cannot fix it; the defer is the thing that fails. Only two states
  put a dead token there, and they want opposite fixes: the bot took
  over three seconds to reach that line, or **a second process is
  signed in on the same token** and answered first. The interaction's
  own age tells them apart -- Discord stamps the id with its creation
  time, so `utcnow() - snowflake_time(interaction.id)` is exactly how
  long it waited -- so the ERROR that reaches #logs carries the number
  and says which reading it supports. Nothing runs afterwards: a
  refusal sent on a dead token is a second traceback for one cause.
- **An unexpected exception reports back, through
  `Debug.cog_app_command_error`.** Both commands here defer first, so
  without it a crash below the defer leaves the caller watching an
  ephemeral spinner that never resolves while the traceback goes only to
  the console and #logs -- which are on the machine hosting the bot,
  not in front of whoever pressed the button. Unlike the coach-facing
  `D12Ball.cog_app_command_error`, this one **names the exception**: the
  audience is whoever is allowed to delete channels, the reason is the
  whole of what they need, and there is no `/d12ball resume` to point
  them at.
- **`confirm` is checked before anything else that can refuse**, including
  whether an export directory is even configured. Typing the command wrong
  should be told exactly that, not some unrelated reason it wouldn't have
  worked anyway.
  - **The refusal names the field and stops.** It used to restate the whole
    operation -- how many games, out of where, to which directory, and that
    the channels would not survive it -- which is a briefing, delivered to
    somebody who has just been told their command did not run. What they
    need is which field was wrong. The warning belongs on `confirm`'s own
    description, where it is read *before* the command is sent rather than
    after it has failed. That is also what stops the message having to cope
    with an export directory it was never given.
- **Only channels the bot can already see are candidates.** The category
  is re-checked at call time the same way `/debug reset_channels` checks
  it -- a channel matching `CHANNEL_NAME_PATTERN`, currently sitting in
  PBD Archive, whose `channel_id` names a saved game with
  `GameStatus.FINISHED` -- so a game whose channel already vanished (the
  case the `on_ready` sweep already prunes, see "Startup drops finished
  games whose channel was deleted" under Gotchas) is left for that sweep
  rather than picked up here with nothing left to export.
- **The pure write and the Discord fetching are two different modules on
  purpose.** `gamesaves/d12ball/archive_export.py` knows nothing about
  `discord` -- it takes plain bytes and dicts and writes them down,
  raising `OSError` outright rather than swallowing it the way
  `save_games` does, because this caller has to know the write actually
  landed before it does something `save_games` never has to contend with:
  an action Discord cannot undo. `cogs/debug.py` does every bit of
  fetching (the channel, its history, each attachment's bytes) and only
  hands this module data once it has all of it for one game.

## The game-creation hub and the lobby

The friendly front door to a new game, alongside `/d12ball create_game` (which
stays, for anyone who prefers the command; the lobby now covers everything it
does bar naming specific opponents up front). Two pieces:

- **The hub** is one locked channel per server carrying a single persistent
  message with a **D12 Ball** button (`NewGameHubView`, in
  `cogs/d12ball_views/lobby.py`). An admin registers it by running
  `/d12ball setup_hub` **in the channel** -- the command sets
  `@everyone send_messages=False` (keeping the bot's own send), posts or edits
  the message, and records `{channel_id, message_id}` per guild in
  `data/d12ball_hubs.json` via `gamesaves/d12ball/hub.py`. Re-runnable to move
  the hub or repair a deleted message. The button's custom_id names no game and
  no guild (the interaction carries the guild, and there is no lobby yet), which
  leaves room for the planned role-self-assign buttons on the same message.
  `build_hub_message` is a welcome plus one titled block per game -- name,
  button, and **the game's own description, which is the author's copy and kept
  verbatim** (D12 Ball's came back in review as the one to use). The **only image
  that ever accompanies "D12 Ball"** is a
  d12 -- the `d12dice` application emoji, uploaded through the Developer Portal;
  `load_d12_emoji` resolves it to a `<:d12dice:id>` string (or `None`, degrading
  to no emoji everywhere), loaded in `cog_load` onto `self.d12_emoji` and
  **re-fetched by `/d12ball setup_hub`** so a fresh upload takes without a
  restart. It rides the hub button, `build_hub_message(...)`, and the lobby
  heading. Never a 🎲/🏈/🎮 -- a d6, a gridiron or a video-game pad, none of
  which this is.
  `data/d12ball_hubs.json` is untracked runtime state like the saved games, and
  local to each machine -- the message lives in Discord, this is only a pointer.

- **The lobby** is an ordinary `SETUP` game with `in_lobby=True` on the record
  (`d12ball/game.py`). `D12Ball.open_lobby` creates its channel through the
  existing `create_private_game_channel` (named `d12ball-pbdN-lobby`), builds
  the game with `player_2_id`/`ai_opponent` **both None**, and posts a
  `LobbyView` -- Join / Observe / Leave / Start Game, the Test game and Tutorial
  toggles, a **Name** button (opening `LobbyNameModal`, the one text field in
  the flow), and the mode / board-size / opponent settings. **Nothing may read
  `is_solo_game` off a lobby**: a two-human game also starts with `player_2_id`
  None, and who the opponent is (a second human, Dinky, the creator on both
  sides, or the tutorial's Dinky) is only settled when Start Game is pressed.
  - **The lobby channel is visible to the whole server**
    (`lobby_channel_overwrites` -- `@everyone` view+send), so anyone can look in
    and decide to join or observe. `lobby_start` swaps that for
    `game_channel_lockdown_overwrites` (`@everyone` no view; the two players full;
    every `observer_id` read-only), in the **same `channel.edit`** as the rename,
    so it is one request and best-effort. Observer overwrites are keyed by
    `discord.Object(id=..., type=Member)` -- `TextChannel.edit(overwrites=...)`
    accepts them and an observer may not be in the member cache.
  - **Join** fills `player_2_id` (and clears any AI pick, and drops the user
    from `observer_ids`). **Observe** appends to `game.observer_ids` -- a list
    field, `field(default_factory=list)`, persisted; a player may not observe.
    **Leave** removes you from whichever list you are on.
  - **A lobby is never abandoned just because it emptied out.** The creator
    leaving with a Player 2 present promotes them; the creator leaving alone is
    **refused** -- the lobby stays up for them to invite someone or start solo.
    `abandon_and_archive_game` is only reached through `/d12ball abandon_game`
    now.
  - **Test game** and **Tutorial** are mutually exclusive with each other and
    with a second human -- each is a different answer to "who takes the other
    side". Test game toggles `game.test_game` (one person both sides); while a
    lobby carries it `player_2_id` is still None, so
    `D12BallGame.__post_init__`'s "same user for both sides" check is **relaxed
    while `in_lobby`** and holds again once `lobby_start` sets
    `player_2_id = player_1_id`. Tutorial toggles `game.tutorial` and **pins
    Basic mode on a 7-space board against Dinky** -- the only shape
    `d12ball/tutorial.py`'s script is written for -- greying the mode and board
    rows; `tutorial_step` stays None and the kickoff arms it, exactly as the
    `create_game` path does.
  - **Name** sets `game.game_name` through a modal (players only). It decides
    only the channel name at Start -- `game_name` beats the test/tutorial/
    players-derived name.
  - **Start Game** (`lobby_start`, any player) finalises the record, does the
    **one-time best-effort** `channel.edit` (rename + lockdown -- the deliberate
    exception to "Archiving ... never renames it" under "Game channels"), then
    `post_game_setup_message`, the same `TeamSelectionView` the rest of setup
    drives (test games included -- Player 1 then Player 2 in turn).
    `game.message_id` is re-pointed at it, as `CoinFlipView` does for the
    home/visiting message.

- **`restore_saved_views` re-arms both.** A hub message per stored guild
  (`NewGameHubView`), and `LobbyView` on an `in_lobby` game's `message_id`
  ahead of the team-picker branch -- without that a lobby would come back as
  the team picker. `LobbyNameModal` is opened fresh per click and needs no
  persistence.

## Recovering a stuck game

A restart re-arms exactly **one** message per game — the one recorded in
`turn_message_id` — so a game can come back with no working button anywhere in
its channel. `/d12ball resume` puts the question back up and
`/d12ball abandon_game` ends the ones nobody is going to finish. Both are open
to either player in the game, or to anyone with `manage_channels`
(`may_administer_game`).

**So that is what a crash tells the coach to do.** The two catch-alls for an
unexpected exception -- `SafeView.on_error` for a click and
`cog_app_command_error` for a command -- share `ERROR_RECOVERY_ADVICE` in
`cogs/d12ball_helpers.py`: try again, then `/d12ball resume`, then the person
running the bot. They used to stop at the first of those, which is advice for
a dropped connection and for nothing else -- a bug in the flow is reached
identically on every click, and the turn it stranded is the thing resume
exists to put back. **The retry stays first, and is not hedged.** A coach
whose click failed cannot be told which kind of failure they have hit, the
transient one does clear on a second press, and a message opening by ruling
that out is both discouraging and, often enough, wrong. The traceback is in
`#logs` and on the host's console and nowhere a coach can see, so the last
step is the only way a bug resume cannot fix ever gets reported.

**The ephemeral views in the game are the shootout's two secret picks**, and
they are ephemeral for one reason: a coach must not see the other side's choice
before the reveal, and it is the only thing Discord offers that hides it.
`ShootoutOrderSelectView` is the shooting order and `ShootoutPickSelectView` the
sudden-death shooter. Everywhere else `ephemeral=True` carries a reply with no
buttons on it — an error, or a coach's own maneuver pick coming back to them.
Those two are also the only views a restart cannot re-attach to their message:
the bot never holds a durable handle to an ephemeral message, so there is no id
to give `add_view`.

**The maneuver pick used to be a third, and is not any more** — see
[The maneuver prompt](#the-maneuver-prompt). Its cards were never the secret;
the *pick* was, and an ephemeral reply to a public button hides that just as
well.

`restore_shootout_menus` is the way round it for the two that are left.
`add_view` **without** a message_id lands the view under a `None` key, and
discord.py's `ViewStore.dispatch_view` looks a click up by
`(message_id, custom_id)` and then falls back to `(None, custom_id)` — so the
menu a coach already has open starts answering again after a restart. It is safe
because the custom_ids already carry the game and the side, and because a
message_id match wins over the fallback, so the next menu the game opens is
dispatched to its own view as usual. The registration outlives the shootout,
which costs nothing: a stale click is answered rather than acted on. The
fallback is asserted against discord.py's own store in
`ShootoutMenuRestoreTests` (`tests/test_d12ball_shootout.py`), because the whole
thing rests on it surviving a library upgrade.

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

- **A new field on `MatchState` goes in `MATCH_SAVED_FIELDS`, and the
  suite fails until it does.** That table in `d12ball/components.py` is
  a field's key, what a save older than it comes back as, and its
  copies in either direction; `to_dict` and `from_dict` both walk it,
  so the two cannot gain a field the other does not know about. It
  replaced 44 fields written out three times over — once on the
  dataclass and once in each half of the save — where landing in two
  of the three is invisible while the bot is up (the live game is the
  one in memory) and shows only as state quietly missing after a
  restart.
  - **`MATCH_EXPLICIT_FIELDS` is the other half of the guard, not a
    dumping ground.** It names the eighteen `to_dict`/`from_dict`
    still handle themselves, each because it says something a table
    cannot: the board and the two setups rebuild objects, the maneuver
    keys go through `legacy_maneuver_key`, `exhaustion` and
    `exhausted` are both filtered against `injured`, and the five
    coaching fields carry their `pending_substitution_*` fallbacks.
    `MatchStateSerializationTests` walks `dataclasses.fields` and
    fails on anything in neither place, so a forgotten field is a red
    suite rather than a bug in a game.
  - **`default` and `factory` are split the way `dataclasses.field`
    splits them.** A shared `[]` handed to every game that predates a
    field is the same bug here as anywhere else, and there is a test
    for it.
  - **The wire format is not the table's to change.** Every fallback
    in it exists because a half-finished game outlives the commit that
    added the field — see the rest of this section — so adding an
    entry is free and changing a key is not.
- **The team board is saved as `team_board` and read under either name.** It
  was called a player board until 2026-08-10 — `TeamBoardState`, `team_board`
  on `TeamSetup`, and the key in `basic_rules.json` and in every saved match.
  `TeamSetup.from_dict` falls back to `player_board`, because a game saved
  before the rename outlives it: both developers run the bot from their own
  tree against their own saves, and there were real games under the old key
  when it changed. Nothing writes the old name, so it dies out on its own —
  don't add a migration, and don't drop the fallback until you know no
  half-finished game predates the rename.
- **A game saved before the 2026-08-17 eight-team reshuffle is migrated
  on load, the same tolerant way.** Its players are named by the old
  `{color}_{slug(name)}` id and its two sides by the old color alone --
  both stopped matching the reshuffled catalog outright, which is what
  turned `/d12ball resume` into `ValueError('The setup does not match
  the team roster.')` on a real in-progress game.
  `gamesaves.d12ball.storage.migrate_legacy_game_data` fixes it inside
  `load_games`, before a `D12BallGame` is even constructed: it walks
  the whole saved dict once, replacing any string that is a
  reconstructed legacy id (built from the *current* catalog -- a
  player's species names the color they used to be fielded under
  exclusively, so nothing here is a hardcoded table of 36 pairs) with
  the player's new id, then remaps a legacy color's Team value to its
  **paired species team**, not the color itself -- that species roster
  is the one whose membership the old save actually matches, since the
  reshuffled color of the same name now holds different players. A
  game already in the new shape is left untouched, detected by whether
  the walk actually found a legacy id rather than by trusting a team
  value's name -- "orange" is a legal `Team` both before and after the
  reshuffle, just for a different roster. Don't add a migration for
  this a second time, and don't drop it until no half-finished game
  can predate the reshuffle.
  - **A rename is the one thing the reconstruction cannot derive, so
    `LEGACY_RENAMED_NAMES` writes those down.** A legacy id carries the
    name the player had when the game was saved; everything else about
    it is still derivable from the catalog, which is why that table is
    three entries and not thirty-six. Three orange players were renamed
    in 36250a9 on 2026-08-17 -- a day before the reshuffle and
    separately from it -- so a game older than *that* commit was
    already failing `TeamSetup.validate`, and the reshuffle migration
    shipped mapping six of its nine ids and leaving three. Add to the
    table whenever a player is renamed.
  - **A migration that fires and cannot finish is worse than one that
    does not fire**, which is what that half-mapped side was: the save
    still fails to load and the traceback names nobody.
    `_unmapped_legacy_ids` is the answer -- anything still shaped like
    `{legacy color}_{name}` after the remap goes to #logs at ERROR,
    naming the game and the ids, because the leftovers *are* the
    diagnosis and somebody has to add the entry. It reads the match
    state alone, since that is the only part of a save holding player
    ids and a game's own name could carry anything.
- **`data/d12ball_games.json` is runtime state and is deliberately untracked.**
  The bot rewrites it on every game action. It used to be committed, which
  meant it showed as modified more or less permanently and was a standing
  source of merge conflicts. Don't re-add it. Each developer's saved games are
  local to their own machine, and `data/` is created at startup if missing.
  `data/d12ball_games.tmp` — the file `save_games` writes and then renames over
  the JSON — had been committed by accident and was doing exactly the same
  thing. Both are ignored now; neither belongs in a commit.
- **Saving a match is `D12Ball.persist(game, match)`, not two lines.**
  Writing the match onto its record and saving it is one step, and it
  appeared as `game.match_state = match.to_dict()` followed by
  `save_games(...)` at 111 sites. Separating the halves fails silently:
  a `save_games` with no `to_dict` above it writes whatever the record
  was already carrying, so the file keeps a state the game has moved
  past and nothing shows it until a restart reads it back.
  `save_games` on its own is still right for the forty-odd callers
  saving the *game* record alone — a message id, a tutorial flag, the
  finished status — which have no match to write. `send_turn_prompt`
  is the one deliberate exception, batching its `to_dict` with
  `turn_message_id` into a single later save.
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
- **A bundled file's name is case-sensitive on one developer's machine and not
  on the other's.** `d12ball/images/emoji/exhaust.png` was tracked as
  `Exhaust.png` against a lowercase path in `render.py`: it opened on macOS,
  missed on Linux, and every icon loader swallows the `OSError` and returns
  None so the render can go on -- so the board simply came out with no
  exhaustion token, on one host only, for as long as nobody looked. CI caught
  it because CI is Linux. `Path.exists()` is not the check, since it answers
  True on the wrong case; the test in `D12BallFontTests` compares each declared
  path against its directory's own listing, which fails on both. Same reasoning
  as the fonts one section above -- a graceful fallback is what makes a missing
  file quiet.

## The test suite

**A patch target naming a module is a patch on that module's own binding.**
This bit both package splits, and bit the cog's hardest: 192 patches of
`cogs.d12ball.save_games` against six mixins that all save.
`cogs/d12ball_views` was one module, so
`mock.patch("cogs.d12ball_views.save_games")` covered every view in the game;
it is a package now, and `from ... import save_games` binds the name into
each submodule, so the same patch reaches none of them. It fails *silently*
-- the patch applies to the package, the test passes, and the real save
writes `data/d12ball_games.json`, because not one of those forty-odd patches
was ever bound with `as` or asserted on. `tests/save_patches.py` is the one
answer for all of them (`suppressed_view_saves`, `suppressed_cog_saves` and
`suppressed_full_image_links`, each patching every submodule that names
the thing), and `tests/test_d12ball_package_shape.py` fails if a submodule
starts saving and is not named there.

- **Naming the right module is not the whole of it, because most views do
  not save through their own binding.** `suppressed_view_saves` covers the
  three view submodules that call `save_games` themselves; every other view
  saves through `self.cog.persist`, which is `cogs.d12ball.core`'s binding
  and needs `suppressed_cog_saves`. A test that wraps only the first is the
  same silent failure one step along -- it reads as suppressed, and the cog
  writes underneath it. Nineteen call sites on `main` were doing exactly
  that, across six files, and the suite was green for all of them. **A view
  usually needs both helpers**, not the one that matches its package.
- **A forgotten suppression now fails the test that forgot it.**
  `save_patches.guard_stray_saves` replaces `save_games` in all ten modules
  that bind it with a stand-in that raises, and importing `save_patches`
  arms it -- which covers the whole run, because `unittest discover` imports
  every test module before it runs any test, so the nine that exercise the
  cog without importing `save_patches` are guarded too. It arms the
  *modules'* bindings and never `gamesaves.d12ball.storage` itself, which is
  what leaves `test_game_storage.py` -- the one place that means to reach a
  disk, through a `GAMES_FILE` pointed at a tempdir -- working untouched.
  `mock.patch` restores what it replaced, so a suppression helper puts the
  guard back on its way out.
  - **`SAVING_MODULES` is armed, and `cogs/debug.py` is why it is a third
    list.** `/debug reset_channels` saves too, and belongs to neither
    package, so the two lists the suppression helpers use would never have
    named it. `StraySaveGuardTests` walks `cogs/` and fails if any module
    binds `save_games` without being named -- the guard can only see a
    binding the list knows about.
- **The way to be sure is still to make the real function raise and run the
  suite.** Replacing `gamesaves.d12ball.storage.save_games` with a recorder
  before the tests import anything lists every call site that reaches it,
  which is the only thing that found the nineteen. The list should now be
  twelve, all of them `test_game_storage.py` testing storage on purpose.
  That is the check worth repeating after anything that moves a view -- and
  the cheaper version of it is that a full run must not create `data/` at
  all.
- **`cogs.d12ball_views.random` and `.discord` were never the views'.** Both
  named the global module through the views' namespace, so those patches
  were always global; they say `random.` and `discord.` now, which is what
  they always did.


**A recorder is tested where a real game is already being played.** The event
log behind the statistics is written at seven separate funnels, and a recorder
that fires on the wrong object -- or before a save that never happens -- passes
every unit test and loses the event. So `tests/test_d12ball_stats.py` covers
the fold and the two suites that already play real games cover the writing:
`TutorialPlaythroughTests` (five scripted turns through the real cog) and
`EveryMatchupResolvesTests` (all thirty-six pairings). See "Where the
statistics are tested".

**A test names a player by their role, not by their name.** The roster is data
the author revises, and a revision is not a code change: 36250a9 renamed five
orange players and broke the suite on `main`, independently of the branch it
landed on, because tests had picked their fixtures by id. Almost none of them
were about *who* the player was -- they wanted a fielded card, or a fullback,
or three of a side to drain the bench with. `tests/roster.py` is how they ask
for that: `fielded(match, PlayerRole.STRIKER)`, `benched(...)`,
`field_players(match)[:3]`, and `roles(ids)` for a test asserting what a deal
fielded rather than who.

- **Every team is dealt the same six roles and benches the same three**, so
  those answer for any team, and a side is named by its `TeamSide` rather than
  by which colour is playing it. The side defaults to home.
- **The standard deal's own tests assert roles against
  `BasicRuleset.standard_setup` itself**, since the deal *is* by role
  (`default_formation_deal`) -- a list of six names was a snapshot of the data
  rather than a reading of the rule, which is why it broke.
- **A test genuinely about a particular player keeps naming them**: the roster
  listing, `test_d12ball_player_import`, and the portrait-art check, which is
  the one that *should* fail when a rename lands without the matching image.
  Everything else should be answerable after a rename without being touched.
- **A team's colour comes from `TEAM_COLORS`** for the same reason -- a test
  carrying `"#f28c28"` under the label `"Orange"` had been wrong since the
  palette moved and nothing noticed, because it was only ever passed to a
  renderer as a string. See "Team colors".
- **A test asserting a label the bot builds out of a name puts the name in
  by lookup**, rather than baking the whole string. The High Pass distance
  buttons (`test_d12ball_high_pass.py`) read
  `f"3 spaces (V2-{striker} [SK])"` off `display_name(fielded(...))`: the
  wording, the space code and the role initials are what is under test, and
  the card standing there is not.
- **A tie broken on roster order is read off the roster, never written down.**
  `test_dinky_breaks_a_role_tie_on_bench_order` asks the bench which of the
  two tied roles it lists first, because the rule is "bench order decides" --
  naming the winner is asserting today's ordering of the data.
- **Synthetic fixtures carry names that are obviously off the roster** --
  `Defender A`, `Shooter`, in `test_d12ball_shot_defence.py` and the dice
  captions in `test_d12ball_components.py`. They are built in the test file
  and never looked up, so a real name there cannot break; it just reads as a
  roster reference and sends the next rename chasing it.
- **`grep` the roster against `tests/` to check, and mutate the data to be
  sure.** Both were done when this landed: no player id or display name
  appears anywhere in `tests/`, and the suite was re-run against a renamed
  id, a renamed player, a reordered roster and a cross-team reshuffle. What
  a reshuffle *cannot* survive is a team losing one of the six standard-setup
  roles or its ninth player -- `load_player_catalog` and
  `default_formation_deal` refuse the data outright, which is the rules
  talking and not the suite.

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

**Two of those machines are the same person's, and only one of them is the
real bot.** The Windows PC serves the live bot out of
`K:\My Drive\Prophetic Fools Games\Discord Bots\fool-bot`; the Mac is that
person's development checkout. So:

- **A traceback from a `K:\` path is the live bot, and a fix on the Mac has not
  reached it.** A change is not deployed until that checkout has pulled and the
  bot has been restarted there -- see "Fonts" and `render.py`'s import-time
  loading for why a restart is not optional.
- **They are two checkouts, so everything that is per checkout is separate**:
  `.env` (which is what decides whether a bot posts to `#logs` at all),
  `data/d12ball_games.json`, and `data/bot_state.json`. The Mac's saved games
  are not the live bot's, so `scripts/render_sample.py --game` cannot reproduce
  a board from a game played on the server.
- **The `K:\` drive is a mounted Google Drive letter**, which is the checkout
  the swallowed-save handling under Gotchas was written for -- when the mount
  goes away mid-game every `save_games` raises.

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

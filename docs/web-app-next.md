# The web app: what is next

**This is a worksheet, not a specification.** The web app shipped with
step 10 of [architecture-migration.md](architecture-migration.md) and
its settled design is [design/web-app.md](design/web-app.md). This
file is what comes after: where the app stands on 2026-09-25, the
three decisions the author has to take before some of the work can
start, the steps in the order they pay off, and one prompt per step
written to be handed to a Claude Code session as it is. Strike a step
when it lands and move what it settled into `docs/design/web-app.md`.
**Nothing in it is a rule.**

## Where it stands, 2026-09-25

What exists (`webapp/`, four Python files and one page):

- A coach opens a link the bot hands them with `/d12ball web_link`,
  sees the board, the score, the narration and the prompt, and answers
  every kind of prompt but `GAME_OVER` through the same
  `GameService.apply_action` a Discord click goes through.
- A spectator with no key sees everything but answers nothing, and a
  side's secrets (the other hand, an unrevealed shootout order) are
  left out of what they are sent.
- A turn taken on Discord reaches the page through
  `GameService.listeners`.
- Four tests hold it to the architecture: nothing under `webapp/`
  imports `cogs` or `discord`; every control of every prompt fixture
  is accepted by the driver; every result is JSON; answers are
  serialised per game.

What it does not do, in the order it hurts:

1. **Discord does not see a turn taken on the web.** The page listens
   to the service; the cog does not. A coach who answers on the web
   leaves the channel's board and prompt stale for the coach on
   Discord, whose next click is refused as a stale one with nothing
   said about why. Until this is closed, a game is playable on the web
   only when *both* coaches are on the web, or one is the AI.
2. **It draws one picture, the board.** The dice, the ignition die,
   the Mind Pull and injury dice, the hand of cards, the field strip
   under the distance prompts, the shot image and the coaching
   half-field are all `D12Ball.render_prompt`'s and the roll views'.
   `GameResult.detail` is on the wire and nothing in `webapp/` reads it.
3. **It cannot open a game.** No lobby, no team pick, no coin, no
   kickoff, no rematch. The service has every method for it
   (`create_game`, the lobby moves, `configure`, `pick_team`,
   `flip_coin`, `choose_home_or_visiting`, `begin`); the routes and
   the page do not.
4. **The journal lives in memory.** A restart is a page with a board,
   a prompt and no history.
5. **The page is a wireframe.** One column, no layout for a phone,
   nothing that tells a coach it is their turn while they are on
   another tab.
6. **Two things the migration's second read left open** (see "Read
   again after step 10" in architecture-migration.md): the web app
   inherits `DiscordBatching` through the cog's service, which
   principle 8 says it should not, and the `to_dict` wire tree has one
   consumer, the tests, because `present.py` builds its payload off
   the dataclasses directly.
7. **It cannot run without the bot.** `foolbot.py` calls `bot.run`
   unconditionally and the server starts in `cog_load`. That is
   decision 5 of [web-app.md](web-app.md) working as intended, not a
   gap, and the last section says when it stops being one.

## A second repository?

**No.** The web app is a frontend over the model in this repository,
and it has to run in the bot's process: `gamesaves/d12ball/storage.py`
rewrites the whole save file on every call and reads it once at
startup, so a second process would overwrite the first's file with a
stale copy of every game (finding 13, decision 5). A separate
repository would need a separate process, a published `d12ball`
package to import, and a shared store with a row per game to make the
two processes safe, and decision 5 defers exactly that until the web
app has to outlive a bot restart. Nothing on this list needs it. Keep
`webapp/` here, keep it importing nothing from `cogs/`, and keep
`tests/test_web_purity.py` as the fence. The day a separate deployment
is wanted is the last step below, and it is a change to the
persistence layer before it is a change to the web app.

## Three decisions to take first

Each is the author's, and two of the steps cannot start until it is
taken. Take them as inline comments on the PR that adds this file.

1. **Who is a web coach?** `D12BallGame.player_1_id` and
   `player_2_id` are Discord account ids, and every authorisation
   predicate reads them. A game opened *on the web* has no account
   behind either seat. Three shapes, from smallest to largest:
   - **(a) A web game is always opened in a channel.** The web app
     plays and rematches games that exist; `/d12ball web_link` stays
     the only way in. No identity work at all. Step 5 below does only
     its first half under this.
   - **(b) A web seat is a name and a derived id.** `create_game`
     takes a negative synthetic id per seat (the record is unchanged
     in shape; `player_1_id` is still an `int`), the key for that seat
     is derived the same way, and the page that opens a game shows its
     creator both links. The startup sweep and the hub ignore a game
     with no `guild_id` already.
   - **(c) Accounts.** A login of any kind. Nothing on this list needs
     it; do not start here.
   The recommendation is (a) now and (b) when the first playtester
   asks to play without Discord, because (b) is a change to who a
   coach is, which is a rules-adjacent question, and (a) costs
   nothing.
2. **Does Discord mirror a web turn, and how much of it?** Step 2
   assumes yes: the cog listens to the service and presents a web
   result in the game's channel the way it presents its own, one
   message per group and one board refresh, through `D12Ball.present`
   and the board gate. The alternative, a stale-prompt notice and a
   board refresh only, is fewer requests but leaves the channel with
   no transcript of half the game. The recommendation is the full
   mirror, since the channel is the record the author reads a game
   back out of.
3. **The wire tree.** Either `_state` answers with `result.to_dict()`
   and `present.py` reads the dicts, or the `to_dict` tree on the
   option shapes goes and `tests/test_wire_shapes.py` with it. Step 7
   does whichever is chosen. The recommendation is to keep the tree
   and make the page read it: a wire format with a consumer is one
   that gets kept right.

## The steps

In the order they pay off. Each is one branch off an up-to-date
`main`, one PR against the template, the suite green, the four web
tests and the six safety-net tests untouched unless the step says
why. None changes the save format. None adds a rule to `webapp/`.

| # | Step | Needs decision | Size |
| --- | --- | --- | --- |
| 1 | Run it for real, and write down how | none | a day, no code |
| 2 | Discord sees a web turn | 2 | small |
| 3 | The dice on the page | none | medium |
| 4 | The prompt's pictures | none | medium |
| 5 | Setup, kickoff and the rematch on the web | 1 | large |
| 6 | The page as a thing to play on | none | medium |
| 7 | The web app's own batching, and the wire tree | 3 | small |
| 8 | The tests the survey found missing, and retiring the worksheets | none | small |
| -- | Later: outliving a restart | its own review | not now |

### 1. Run it for real, and write down how

**Why first.** Nothing below is worth building until two people have
played a game through the page, because that is what tells you which
of the gaps above is the one that actually stops play. The design doc
has the four environment variables; nobody has written down how the
live bot on the Windows checkout is reached from a browser that is
not on its network.

**What it is.** Set `FOOLBOT_WEB_PORT`, `FOOLBOT_WEB_SECRET` (so links
survive a restart) and `FOOLBOT_WEB_URL` on the live checkout, put
the port behind something that terminates TLS and gives it a public
name, open a game in a channel, hand out both links, play it through
with one coach on the page and one on Discord, and note where it
broke. The key is in the query string of the link, so the link must
only ever travel over HTTPS, which is the tunnel's job.

**Which tunnel.** This is hosting, not code, and I have not verified
which fits the author's network; the candidates are a Cloudflare
Tunnel, Tailscale Funnel or ngrok, all of which give a Windows host a
public HTTPS name without opening a port on the router. Pick the one
whose account the author already has.

**Done when** `docs/design/collaboration.md` has a "Reaching the web
app" section with the exact variables and the tunnel command, and the
findings from the playtest are the top of this file.

**Prompt.**

```text
Read CLAUDE.md, docs/design/web-app.md ("Running it") and
docs/design/collaboration.md. We are deploying the D12 Ball web app
on the live bot for the first time. Do not change any Python.

1. Write a "Reaching the web app" section into
   docs/design/collaboration.md: the four FOOLBOT_WEB_* variables and
   what each is for, why FOOLBOT_WEB_SECRET must be set on the live
   checkout (links die with the process otherwise), why the link must
   only travel over HTTPS (the key is in the query string), and the
   exact steps to expose the port through <TUNNEL> on the Windows
   host, including the command and where FOOLBOT_WEB_URL comes from.
   Say what you could not verify from here.
2. Add a "Playtest checklist" to docs/web-app-next.md under step 1:
   open a game in a channel, /d12ball web_link for each coach, one
   coach on the page and one on Discord, play to a goal, a loose ball,
   a coaching window and the end, and for each note whether the page
   and the channel agreed about whose turn it was and what happened.
3. Open a PR against the template. It is docs only; say so under
   Testing.
```

### 2. Discord sees a web turn

**Why second.** Gap 1 above. Until the channel shows what a web coach
did, a mixed game is not playable, and mixed games are how the page
gets tested at all while there is one page and one channel.

**What it is.** The cog appends a listener to its service the way
`WebApp.watch` does, and a result the cog did not produce itself is
presented in the game's channel: one message per narration group, the
board refreshed once through `BoardRefresher`, and the next prompt put
up with `send_new_prompt` so its view is live for the Discord coach.
The cog already presents a result with no interaction behind it (the
startup sweep and `/d12ball resume` post into a channel by id); the
listener reuses that path rather than growing a second presenter.

**What it must not do.** Present a result twice: a click the cog
itself made reaches the listener too, so the listener has to know
which results are its own. The smallest reading is a flag the cog
sets around its own `apply_action` calls (the lock is already held
there), or a listener that is registered on the web app's service
only once step 7 gives it one. Pick the first now; step 7 replaces
it. And the rate limits hold: a web result is one message per group
and one board refresh, never one per line.

**Done when** a coach on the page takes a turn and the channel shows
the narration, the board and the next prompt, with the request count
per result written in the PR body; and a test in
`tests/test_web_app.py` or a new `tests/test_web_mirror.py` drives an
action through the web route and asserts the cog presented it once,
with the same stubs `tests/cog_steps.py` uses.

**Prompt.**

```text
Read CLAUDE.md, docs/design/web-app.md, docs/design/game-service.md,
docs/design/rate-limits.md and docs/design/recovery.md. Branch off an
up-to-date main.

Problem: a turn taken on the web app never reaches the Discord
channel. webapp/server.py's WebApp.watch appends a listener to
GameService.listeners, so a page sees a Discord click; nothing in
cogs/ listens, so a Discord coach sees nothing of a web click and
their next press is refused as stale.

Make the cog a listener. In cogs/d12ball/core.py, register one
listener on self.service when the web app starts (start_web_app) and
remove it in cog_unload. For a result the cog did not produce itself,
present it in the game's channel through D12Ball.present, the one
presenter: one message per narration group, one board refresh through
BoardRefresher at the end, the next prompt put up with
send_new_prompt. Find how the startup sweep and /d12ball resume
present into a channel with no interaction and reuse that path; do
not write a second presenter. The listener is sync (the service is),
so schedule the async presentation on the loop under the game's lock
(gamelocks.GameLocks), the same lock the web route holds.

The cog's own clicks reach the listener too. Mark them: a set of game
ids the cog is currently applying for, added around its own
apply_action/run/resume calls, and the listener skips a result for a
game in it. Say in a comment that step 7 of docs/web-app-next.md
replaces this with a service of the web app's own.

Rate limits: count the requests one web result costs in the channel
and put the number in the PR body. It must be no more than what the
same result costs when a Discord coach makes it.

Tests: one that drives an action through the web route
(tests/test_web_app.py has the HTTP harness) with a cog attached and
asserts present ran once with that result; one that a Discord click
does not present twice. Suppress saves through tests/save_patches.py.
The three cog goldens must not change.

Update docs/design/web-app.md ("What a page is handed" grows a
paragraph on the mirror) in the same commit. PR against the template.
```

### 3. The dice on the page

**Why third.** The rolls are the drama of the game and the page shows
a sentence where Discord shows a picture. Everything needed is already
on the wire: `GameResult.detail` and `Narration.detail` carry the five
roll dataclasses (`ContestDice`, `ShotDice`, `OwnGoalRoll`,
`MindPullRoll`, `InjuryRoll`, with `IgnitedRoll` inside them), and the
renderers are `render.py`'s with no Discord in them.

**What it is.** The journal keeps a result's `detail` on the entry
that carried it; `Entry.to_dict` says an entry has a picture; a new
route `GET /api/game/{id}/detail/{entry}.png` renders it in a worker
thread with the same Pillow functions the roll views call
(`render_skill_test_dice`, `render_volatile_die`,
`render_mind_pull_die`, `render_own_goal_dice`,
`render_injury_test_die`), cached like the boards. The page puts the
picture between the same two lines Discord does.

**Why Pillow and not HTML dice.** One picture, two frontends, and the
design doc's own reason: the model's voice is one, and so is its
picture of a roll. Drawing dice in CSS would be a second rendering to
keep right, and the ignition die and the blaze are not trivial to
redraw. HTML dice are a step 6 refinement if the PNGs prove slow on a
phone, measured, not assumed.

**The one thing in the way.** `render_contest_dice` in
`cogs/d12ball_views/base.py` builds the tuple `render_skill_test_dice`
takes from a `ContestDice` plus the catalog, and `challenge_side` in
`cogs/d12ball/presentation.py` builds a `ChallengeSide` for the shot
and challenge images. Both are a rendering brief over the model's
values, and the web app may not import them. Move each to `render.py`
(or a new `d12ball/dice_brief.py` if `render.py` should not know
`ContestDice`), make the cog call the moved function, and verify the
move by SHA-256 on the dice images, per board-image.md.

**Done when** every roll kind on the page shows the picture Discord
shows, the cog's images are byte-identical before and after the move
(hashes in the PR body), and `tests/test_web_app.py` renders one of
each detail through the route.

**Prompt.**

```text
Read CLAUDE.md, docs/design/web-app.md, docs/design/board-image.md
and docs/design/model-discord-split.md. Branch off an up-to-date main.

Goal: the web page shows the dice. GameResult.detail and
Narration.detail already carry the five roll dataclasses (ContestDice
and ShotDice in d12ball/flow/rolls.py, OwnGoalRoll in flow/effects.py,
MindPullRoll in flow/arrivals.py, InjuryRoll in flow/injuries.py, with
IgnitedRoll from engine.py inside them); nothing in webapp/ reads
them.

1. Move the rendering briefs out of cogs/. render_contest_dice in
   cogs/d12ball_views/base.py turns a ContestDice into the tuple list
   render.render_skill_test_dice takes; challenge_side in
   cogs/d12ball/presentation.py builds a render.ChallengeSide. Both
   read only the model and the catalog. Move them below render.py
   (into render.py, or d12ball/dice_brief.py if render.py should not
   import from flow/), leave a one-line forwarder in the cog or
   re-point every caller, and verify by SHA-256 that every dice image
   and the shot and challenge images the cog produces are
   byte-identical before and after. Put the hashes in the PR body.
   This is its own commit.
2. In webapp/server.py, keep each result's detail on the journal
   Entry that carried it (the answer's own detail, and each group's).
   Entry.to_dict says whether the entry has a picture. Add
   GET /api/game/{game_id}/detail/{entry_id}.png that renders it with
   the same render.py function the matching roll view calls, in
   asyncio.to_thread, cached the way the boards are (BOARD_CACHE).
   Pick the renderer by the detail's shape (the `shape` its to_dict
   writes), never by the prompt kind.
3. In webapp/static/app.js, draw the picture between the lines the
   way the cog does: find where each roll view places the image
   relative to the narration and match it.
4. Tests: in tests/test_web_app.py, for one fixture per detail shape,
   apply the roll through the route and GET the detail PNG; assert a
   PNG of the size the renderer produces. tests/test_web_purity.py
   must still pass, so nothing under webapp/ imports cogs.

Update docs/design/web-app.md: "The pictures, and the voice" gains
the dice, and "What it does not do yet" loses them. PR against the
template; the board-image checklist line applies to the move.
```

### 4. The prompt's pictures

**Why fourth.** After the dice, what the page lacks is what a coach
looks at while choosing: the field strip under the seven distance
prompts, the hand of cards on the maneuver pick, the shot image on a
score attempt, the coach's half-field on the hub, and the challenge
image on the walk-in. Each is keyed on the `PromptKind` in
`D12Ball.render_prompt` (`FIELD_PROMPT_KINDS`, the coaching kinds) and
drawn by `render_field_image`, `cards.render_maneuver_hands`,
`render_score_attempt`, `render_coaching_image` and
`render_maneuver_challenge`, none of which import Discord.

**What it is.** `_state`'s prompt gains a `picture` URL, keyed on the
kind the same way `render_prompt` keys it, served by
`GET /api/game/{id}/prompt.png?v=...`, rendered read-only in a worker
thread. The hand is this viewer's own (the page already sends only the
viewer's row; the picture is the same rule), and the coaching
half-field is the asked side's. The challenge image rides on the
`AUTO_RESOLVE_CHALLENGER` group's `arguments` (`challenger_id`), the
way the cog keys it, so it is an entry picture like the dice, not a
prompt picture.

**What it must not do.** Decide which picture from the match. The kind
is the key, as it is in the cog; a page that looked at
`match.challenger_id` to decide would be the second reading finding 14
of web-app.md warned about.

**Done when** each of the five pictures shows on the page for its
kind, and a test walks the fixtures for those kinds through the route.

**Prompt.**

```text
Read CLAUDE.md, docs/design/web-app.md, docs/design/maneuver-prompt.md,
docs/design/cards.md and docs/design/model-discord-split.md
("one picture per kind"). Branch off an up-to-date main. This step
assumes step 3 of docs/web-app-next.md has landed (challenge_side and
the dice brief live below render.py).

Goal: the page shows the picture a prompt rides on, keyed on the
PromptKind exactly as D12Ball.render_prompt keys it
(cogs/d12ball/core.py, FIELD_PROMPT_KINDS and the coaching kinds).

1. In webapp/server.py, _state's prompt gains "picture": a URL or
   null, decided by a table from PromptKind to a renderer in
   webapp/present.py (the web half of render_prompt):
   - the seven FIELD_PROMPT_KINDS: render.render_field_image;
   - MANEUVER_ACTION: cards.render_maneuver_hands with this viewer's
     hand only, off the prompt's options (the rows the page already
     sends), never off the match;
   - SCORE_ATTEMPT: render.render_score_attempt, sides built by the
     moved challenge_side;
   - COACHING_HUB and COACHING_OFFER: render.render_coaching_image for
     the asked side, titled with engine.coaching_title.
   Serve it at GET /api/game/{game_id}/prompt.png?key=...&v=<board
   version>, rendered in asyncio.to_thread and cached with the boards.
   A spectator gets the field strip and the half-field and never a
   hand.
2. The challenge image is an entry picture, not a prompt picture: the
   group tagged AUTO_RESOLVE_CHALLENGER carries challenger_id in
   Narration.arguments (see docs/web-app.md, "Small things"). Keep it
   on the journal Entry beside the dice detail from step 3 and serve
   it through the same detail route.
3. app.js draws the picture above the controls, and the challenge
   image inside its entry.
4. Tests: for one fixture per kind above, GET the picture and assert
   a PNG of the renderer's size; assert a spectator's MANEUVER_ACTION
   picture is null. Nothing under webapp/ imports cogs.

Update docs/design/web-app.md ("What it does not do yet" loses the
pictures; "The pictures, and the voice" says how they are keyed). PR
against the template.
```

### 5. Setup, kickoff and the rematch on the web

**Why fifth, and why after decision 1.** The service has every method
(`create_game`, `lobby_join`/`observe`/`leave`, `configure`,
`start_lobby`, `pick_team`, `flip_coin`, `choose_home_or_visiting`,
`begin`), each a thin door over a rule on `D12BallGame` that refuses
with `RuleRefusal`, and `tests/test_game_service_setup.py` walks the
whole path with no channel. What is missing is routes and a page.
What is undecided is who sits in a seat a browser opened, which is
decision 1.

**Two halves.** The first needs no decision: a game opened in a
channel, played on the page from the team pick onward, and the
rematch a finished game offers (`GAME_OVER` is the one kind
`present.py` has no builder for, because its answer opens a new
game). The second is web-native creation under decision 1(b), and it
is its own PR.

**What it is, first half.** Routes over the setup methods,
`POST /api/game/{id}/setup/{move}`, each: authenticate the viewer,
call the service method, map `RuleRefusal` to a 409 with its sentence,
answer with the state. `_state` before kickoff gains a `setup` panel:
the settings, the seats, whose pick it is, the coin, home or visiting,
and the Begin button that calls `begin`. The page draws the panel
where the prompt goes. For the rematch, `present.py` gains a
`GAME_OVER` builder whose one control calls the rematch route, which
does what `RematchView` does through the service and returns the new
game's id and this coach's link for it.

**What it must not do.** Repeat a lobby rule. The record refuses; the
route shows the refusal. A page that greys a team because it worked
out the pairing exclusions itself is the failure mode; `excluded_teams`
is the record's and the page asks for the list.

**Done when** a game opened with `/d12ball create_game` can be picked, tossed, seated and begun from the page by
either coach, a finished game can be rematched from the page, and
`tests/test_web_app.py` walks the setup path over HTTP the way
`test_game_service_setup.py` walks it over the service.

**Prompt, first half.**

```text
Read CLAUDE.md, docs/design/web-app.md, docs/design/game-service.md
("setup and the lobby"), docs/design/hub-and-lobby.md and
docs/design/coaching-choice.md. Read tests/test_game_service_setup.py
end to end: it is the path this step puts on the web. Branch off an
up-to-date main.

Goal: a game opened in a Discord channel can be set up, kicked off
and, when finished, rematched from the web page. Web-native game
creation is NOT this step (decision 1 in docs/web-app-next.md).

1. Routes in webapp/server.py, one per service setup method the page
   needs: pick_team, flip_coin, choose_home_or_visiting, configure,
   begin. Shape: POST /api/game/{game_id}/setup/{move} with a JSON
   body of the method's arguments; authenticate with the key; call
   the service method under the game's lock; catch RuleRefusal and
   answer 409 with its sentence in "refusal"; otherwise answer the
   state. Build Team and HomeChoice from the wire in the route the way
   Action.from_dict builds a PromptKind (d12ball/wire.py's reason).
2. _state before kickoff gains "setup": the settings (GAME_SETTINGS
   and their current values), both seats (name, team or null), which
   teams this viewer may pick (ask the record; do not compute the
   pairing exclusions here), whether the coin is tossable and by whom,
   whether home/visiting is owed and by whom, and whether begin is
   available. Every one of those is a question the record or the
   service answers; if one is not yet exposed, add the method to
   D12BallGame or GameService and have the cog's setup views read it
   too.
3. present.py gains the GAME_OVER builder: one control, "Rematch",
   posting to POST /api/game/{game_id}/rematch, which does what
   cogs/d12ball_views/setup.py's RematchView does through the service
   and answers with the new game id and this viewer's link for it
   (webapp/keys.link_for). Remove the GAME_OVER exemption from
   tests/test_web_app.py.
4. The page: a setup panel in the prompt's place before kickoff,
   drawn from "setup" and nothing else; a rematch button after.
5. Tests: over HTTP, both coaches pick, one tosses, the winner
   chooses, begin opens the pre-kickoff Coaching Choice; a refused
   pick (excluded pairing) is a 409 carrying the record's sentence and
   changes nothing; a spectator is 403 on every setup route; a
   rematch produces a new game the page can open. Suppress saves.

Docs: docs/design/web-app.md "What it does not do yet" loses "It does
not create games" and gains a sentence on what it still does not do
(open one from nothing). PR against the template.
```

**Prompt, second half (only after decision 1(b)).**

```text
Read CLAUDE.md, docs/design/web-app.md, docs/design/game-service.md,
docs/design/permissions.md and docs/design/gotchas.md ("to_dict/
from_dict"). Branch off an up-to-date main. Decision 1(b) of
docs/web-app-next.md has been taken: a web seat is a name and a
derived id.

Goal: a game can be opened from the web page with no channel.

1. Identity. GameService.create_game already takes guild_id and
   channel_id as None. Add webapp/seats.py: a synthetic negative id
   per web seat derived from the game id and the seat number (never
   colliding with a Discord snowflake, which is positive), and the
   key for that seat from keys.key_for as today. The save format does
   not change: player_1_id stays an int. Check every predicate that
   reads player ids (game_participant_ids, may_act_for, the startup
   sweep's guild filter, the hub) and confirm a negative id and a
   None guild_id fall through them the way a game they do not know
   about should; write the list in the PR body.
2. POST /api/games creates a game (mode, modules, board size, AI
   opponent or a second seat) through create_game and answers both
   links; the creator's page shows the second link to hand to their
   opponent. A game with no second name gets the AI, as create_game
   already does.
3. The index page becomes the front door: open a game, or paste a
   link.
4. Tests: create over HTTP, both seats play the first turn; a
   Discord-opened game is unaffected; test_web_purity still passes.

Docs: docs/design/web-app.md gains "Who is a web coach" with the
derivation and why the record did not change. PR against the template.
```

### 6. The page as a thing to play on

**Why sixth.** Everything above makes the page *complete*; this makes
it *usable*, and it should come after, because the layout depends on
what is on it. Three things, and the playtest from step 1 says which
first:

- **Layout.** Two columns on a laptop (board left, prompt and journal
  right), one on a phone with the board scaled to the width and the
  prompt pinned at the bottom; a tap on the board opens it full size.
- **Your turn.** The tab title carries a mark when the prompt is this
  viewer's, and the Notifications API asks once and fires once per
  prompt that is theirs. Nothing here is a rule; `prompt.yours` is
  already on the wire.
- **The journal survives a restart.** Write each game's journal to
  `data/d12ball_web_journal.json` (frontend state, its own file, never
  the save) on each `add`, and read it at start. Bounded by
  `JOURNAL_LENGTH` as it is in memory. The board snapshots on entries
  are saved with them, since that is what a scrolled-back entry draws.

**Done when** a game is playable on a phone without pinching, and a
bot restart mid-game leaves the page with its history.

**Prompt.**

```text
Read CLAUDE.md, docs/design/web-app.md and docs/design/gotchas.md
("data/ is untracked runtime state"). Branch off an up-to-date main.
Do this as three commits, each reviewable alone.

1. Layout. webapp/static/game.html and app.css: two columns from
   900px up (board left; scoreboard, prompt and journal right), one
   column below with the board at full width and the prompt section
   sticky at the bottom; a click on the board opens it at full size
   (a <dialog>, no library). The journal scrolls inside its column
   and new entries scroll into view as they do today. Check it in a
   real browser at 360px and 1280px wide and put screenshots in the
   PR. No framework, no build step, no CDN: the page stays one file
   each of HTML, CSS and JS served by aiohttp.
2. Your turn. In app.js: when state.prompt.yours turns true, prefix
   the document title with a mark and, if the viewer has granted
   Notification permission (ask once, on the first control they
   press, never on load), fire one notification per prompt naming
   the ask. Clear the mark when the prompt changes or is answered.
3. The journal survives a restart. In webapp/server.py, Journal
   writes itself on every add to data/d12ball_web_journal.json (one
   file, keyed by game id, the same JOURNAL_LENGTH bound, entries with
   their board snapshots and details from steps 3 and 4) and reads it
   in WebApp.__init__. A write failure is logged and never fails the
   request, like save_games. A game the journal knows and the service
   does not (deleted) is dropped on load. Tests: a Journal round-trips
   through a temp path; a full test run must not create data/ (see
   tests/save_patches.py for how saves are suppressed and do the same
   for this file).

Update docs/design/web-app.md ("What a page is handed": the journal is
persisted, and why it is still not the save; "What it does not do
yet" loses the in-memory line). PR against the template.
```

### 7. The web app's own batching, and the wire tree

**Why seventh, and after decision 3.** Two loose ends the migration's
second read left on purpose. The batching is a principle: the web app
"shares the cog's service and so inherits `DiscordBatching`, which
principle 8 says it should not". The fix is a second `GameService`
over the same `games` dict and the same save, constructed with the
default `Batching()`, so a run on the web stops where a page wants it
to and not where a Discord message does. Both services announce to
both listeners, which is what makes the step 2 flag go: the cog
listens to the web service and the web app to the cog's, and neither
sees its own results.

**Done when** `WebApp` owns a service of its own, the step 2 flag is
gone, and the page answers with (or `present.py` reads) `to_dict`
per decision 3.

**Prompt.**

```text
Read CLAUDE.md, docs/design/web-app.md, docs/design/game-service.md
("batching stays the frontend's") and the "Read again after step 10"
section of docs/architecture-migration.md. Branch off an up-to-date
main.

1. A service of the web app's own. In cogs/d12ball/core.py's
   start_web_app, construct a second GameService over the same
   self.games dict, the same engine and the same save callable, with
   the default Batching(), and hand it to WebApp. Verify by reading
   GameService.__init__ and storage.py that two services over one
   dict and one save are safe on one event loop (apply_action is
   synchronous; the save is whole-file), and say so in the PR body.
   Cross-wire the listeners: the cog listens to the web service and
   the web app to the cog's. Remove the "applying" set step 2 of
   docs/web-app-next.md added, since a service never announces to
   itself. The step 2 tests must still pass unchanged except for the
   wiring.
2. Decision 3 of docs/web-app-next.md, as taken: <either> _state
   answers with result.to_dict() / prompt.to_dict() and present.py's
   builders read the dicts, so tests/test_wire_shapes.py is testing a
   format with a consumer; <or> the to_dict tree on the option shapes
   goes with its test, and docs/design/web-app.md's "The wire" says
   what remains and why. Its own commit.

Update docs/design/web-app.md ("One process, one service" becomes
"one process, two services, one dict") and the map row in CLAUDE.md
for gamesaves/d12ball/service.py if its wording no longer holds. PR
against the template.
```

### 8. The tests the survey found missing, and retiring the worksheets

**Why last.** None blocks play. The survey on 2026-09-25 found no test
on `POST /resume`, on the `?entry=` board snapshot route, on a
spectator's payload leaving a side's secrets out beyond "no controls",
or on `configured_port`/`start_web_app` wiring; and the two
worksheets, this file's predecessors, are kept only because about a
hundred and thirty code comments cite them by step and finding
number.

**Prompt.**

```text
Read CLAUDE.md and docs/design/testing.md. Branch off an up-to-date
main. Two commits.

1. tests/test_web_app.py grows: POST /resume on a fixture whose
   position owes a step (tests/prompt_fixtures.py's owed cases)
   answers resumed=true and the next prompt, and 403 for a spectator;
   GET board.png?entry=<id> for an entry with a snapshot is a PNG and
   for one without is 404; a spectator's state on the MANEUVER_ACTION
   and shootout fixtures carries no hand and no order for either side
   (assert on the JSON, not on the controls); configured_port reads
   FOOLBOT_WEB_PORT and start_web_app returns None without it.
2. Retire docs/web-app.md and docs/architecture-migration.md per
   "Where this leaves the two worksheets": for every code comment
   that cites either by step or finding number, re-point it at the
   section of docs/design/web-app.md, game-service.md or
   model-discord-split.md that holds what it cites (add the paragraph
   there if none does); then delete the two files and their CLAUDE.md
   rows, and re-point docs/web-app-next.md's own references. Use an
   Explore subagent for the sweep. Nothing else changes; the suite is
   the check. PR against the template.
```

### Later: outliving a restart

Not on the list, and written down so nobody starts it by accident.
The day the web app has to run when the bot is down, or on another
host, `storage.py`'s whole-file save has to become a store with a row
per game that two processes can share, and the lock has to become
one both processes honour. That is a change to persistence reviewed
on its own, with the save format still the contract; the web app is
a client of it, not the reason for its shape. Decision 5 of
[web-app.md](web-app.md) stands until then. A websocket in place of
the poll is in the same drawer: the design doc's reason (a few clicks
a minute, and a re-read is always right) has not changed.

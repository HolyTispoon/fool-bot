# The Codex bot: a second bot from the same repository

**This is a worksheet, not a specification.** It was written on
2026-10-07 from the author's ask -- a second Discord bot, run from this
repository beside fool-bot and modelled on the D12 Ball bot, that plays
Sirlin Games' *Codex: Card-Time Strategy*, starting from the basic game
of Bashing against Finesse, with one slash command to open a lobby and
buttons for nearly everything after it -- against what the repository
already has (the model/Discord split, `GameService`, the driver, the
views, the board gate, the deploy scripts) and against three outside
sources: the Unofficial Manual Rewrite v1.3 of the rulebook, the Codex
Card Database (codexcarddb.com) with its source repository, and the
forum play-by-post spreadsheet. Each step below has a prompt a Claude
Code session is started with. Strike a step when it lands and move what
it settled into `docs/design/codex.md`, the design note step 1 creates.
**Nothing in it is a rule.**

## What was found, and what it settles

### The game, in the terms the code will use

The basic game is the plan's scope: one hero each, the ten neutral
starting cards as both decks, the tower and the surplus as the only
add-ons, no heroes' hall and no tech lab (UMR p. 3). Everything below is
what that game asks of an engine, read from the Unofficial Manual
Rewrite v1.3 (`UMR p. n` is its page) and from the card texts.

- **A player's things.** A base at 20 HP. One hero in the command zone
  -- Troq Bashar for Bashing, River Montoya for Finesse, both neutral,
  both cost 2 (p. 3, 6). A worker card: the first player starts with 4
  workers, the second with 5 (p. 3). A deck of the ten neutral starting
  cards, seven units and three minor spells, the same ten for both
  sides. A hand of five. A codex of 24 cards: two copies of the spec's
  twelve -- three spells, one ultimate, two Tech I, five Tech II and one
  Tech III (p. 3). In the base, three tech-building slots and one add-on
  slot (p. 8, 9). Gold, capped at 20 (p. 5).
- **The five phases** (p. 5). *Ready*: the cards teched last turn go
  face-down into the discard pile; every card readies. *Upkeep*: a gold
  per worker; one summoning rune off each hero; the upkeep effects, in
  the order the active player chooses -- the surplus's draw, Helpful
  Turtle's healing, Star-Crossed Starlet's damage. *Main*: actions in
  any order until the player locks patrollers. *Draw*: the hand is
  discarded face-down and the player draws that many plus two, to a
  maximum of five. *Tech*: two cards out of the codex -- or none, one or
  two once the player has ten workers -- chosen secretly: offered when
  the turn ends, open to change all through the opponent's turn, and
  confirmed by the player at the start of their next turn, so the
  choice overlaps the opponent's turn and the ready phase is where it
  is settled (the author, 2026-10-08). A player may shuffle the discard
  pile into the empty deck once per phase.
- **The actions of the main phase** (p. 6-11). Hire a worker, once a
  turn: a gold and a card from the hand, which is trashed unseen. Summon
  the hero for its cost, at level 1, with arrival fatigue; level it for a
  gold a level, healing it when it reaches a new band; a hero with
  summoning runes cannot be summoned. Play a tech card: its cost, and
  the tech building its level needs -- every tech card in this set is a
  unit. Play a spell: its cost, a hero in play, the spec's hero for a
  spec spell, and for an ultimate the hero at maximum level since the
  turn began. Play an ability action: Harmony's "stop the music",
  River's sideline at level 3, Maestro's granted exhaust. Construct a
  tech building: Tech I for 1 gold at six workers, Tech II for 4 at
  eight, Tech III for 5 at ten, each 5 HP, each finished at the end of
  the turn, each rebuilt for 0 after it is destroyed. Construct an
  add-on: the tower (3 gold, 4 HP) or the surplus (5 gold, 4 HP), one
  slot. Attack. Lock patrollers, which ends the phase. The hero limit
  (p. 6), the spec choice at Tech II (p. 8) and the multicolour
  penalties (p. 4) never arise with one neutral hero a side.
- **Combat** (p. 10-11, 14). An attacker must take the squad leader,
  then any other patroller, then anything with HP. Attacker and defender
  deal their ATK to each other at once, swift strike first; a card with
  damage equal to its HP, or with 0 HP, is destroyed. A destroyed unit
  goes face-down to the discard; a destroyed hero returns to the command
  zone with two summoning runes and one of the opponent's heroes in play
  gains two levels; a destroyed tech building or add-on deals 2 to its
  base. The patrol slots (p. 10): squad leader armor 1, elite +1 ATK,
  scavenger a gold when it dies, technician a card when it dies, lookout
  resist 1. Exhausted cards cannot patrol; cards with arrival fatigue
  can. Armor refreshes at the start of each turn. Flying, anti-air,
  stealth, invisible and unstoppable change who may be attacked and who
  may be ignored (p. 14, 16-18); the tower detects the first stealth or
  invisible attacker on an opponent's turn and any one card on its
  owner's, and deals a combat damage to every attacker it can see (p. 9).
- **Who decides.** The active player makes every decision, including
  the order of effects on cards they do not control (p. 14). In this set
  nothing asks the other player anything during a turn: the flagbearer
  is a constraint, the tower's detection on the defender's behalf is
  automatic, the patrol bonuses pay out by themselves. The one thing a
  player does on the opponent's turn is the tech choice.
- **The game ends** when a base is destroyed (p. 2).

### The thirty-six cards, and what each asks of the engine

Read from the card database's data on 2026-10-07. A unit is `ATK/HP`;
a card's tech level is in brackets; `(T)` marks a targeted effect.

| Group | Card | What it asks |
| --- | --- | --- |
| Starter | Tenderfoot 1/2 [0], Older Brother 2/2 [0] | Nothing: vanilla units (Tenderfoot is a Virtuoso) |
| Starter | Timely Messenger 1/1 [0] | Haste |
| Starter | Brick Thief 2/1 [0] | Arrives-or-attacks: 1 damage to a building (T) and repair 1 on another; resist 1 |
| Starter | Helpful Turtle 1/2 [0] | Healing 1 at upkeep |
| Starter | Granfalloon Flagbearer 2/2 [0] | Flagbearer: the opponent's targeted spells and abilities must take it once |
| Starter | Fruit Ninja 2/2 [0] | Frenzy 1 |
| Starter | Spark (1), Bloom (2), Wither (2) | Minor spells: 1 damage to a patroller (T); a +1/+1 rune on a friendly unit or hero without one (T); a -1/-1 rune on a unit or hero (T), the two runes cancelling |
| Bashing | Wrecking Ball (0), The Boot (3), Intimidate (1) | 2 damage to a building (T); destroy a tech 0 or I unit (T); -4 ATK this turn, floor 0 (T) |
| Bashing | Final Smash (6, ultimate) | Three mandatory targets in sequence: destroy a tech 0 unit, return a tech I unit to its owner's hand, gain control of a tech II unit; "do as much as you can"; the flagbearer rule per part |
| Bashing | Iron Man 3/4 [I], Regular-sized Rhinoceros 5/6 [II] | Nothing: vanilla units |
| Bashing | Revolver Ocelot 3/3 [I] | Sparkshot: 1 damage to an adjacent patroller |
| Bashing | Hired Stomper 4/3 [II] | Arrives: 3 damage to a unit (T), mandatory, own units and itself included |
| Bashing | Sneaky Pig 3/3 [II] | Haste; arrives with stealth until end of turn |
| Bashing | Eggship 4/3 [II] | Flying |
| Bashing | Harvest Reaper 6/5 [II] | Overpower: the excess over a patroller goes to one other legal defender |
| Bashing | Trojan Duck 8/9 [III] | Obliterate 2 before combat, then a new defender if the first is gone; arrives-or-attacks: 4 damage to a building (T) |
| Finesse | Harmony (2, ongoing) | Channeling; whenever its owner plays a spell, a 0/1 Dancer token, limit 3, never from Harmony itself; "sacrifice Harmony → stop the music" flips Dancers into 2/1 unstoppable Angry Dancers; losing the hero sacrifices it without flipping |
| Finesse | Discord (2) | -2/-1 to all the opponent's tech 0 and I units until end of turn; 0 HP kills |
| Finesse | Two Step (2, ongoing) | Channeling; two of the owner's units (T) partnered, +2/+2 each while both are held; sacrificed when one leaves or changes hands |
| Finesse | Appel Stomp (1, ultimate) | Sideline a patroller (T), draw a card, then a choice: put Appel Stomp on top of the deck |
| Finesse | Nimble Fencer 2/3 [I] | Your Virtuosos have haste, itself included |
| Finesse | Star-Crossed Starlet 3/2 [I] | Upkeep: 1 damage to herself; +1 ATK per damage on her |
| Finesse | Grounded Guide 4/4 [II] | Your other units +1 ATK, your Virtuosos +2/+1 instead; stacks |
| Finesse | Maestro 3/5 [II] | Your Virtuosos cost 0 and gain "exhaust → 2 damage to a building (T)"; the exhaust needs the Virtuoso held since the turn began, or haste |
| Finesse | Backstabber 3/3 [II] | Invisible: untargetable and unattackable to an opponent without a detector, and sneaks; attackable while patrolling |
| Finesse | Cloud Sprite 3/2 [II] | Flying |
| Finesse | Leaping Lizard 3/5 [II] | Anti-air |
| Finesse | Blademaster 7/5 [III] | Your units and heroes have swift strike while it is in play; it is a Virtuoso, so Maestro makes it free |
| Hero | Troq Bashar 2/3, 3/4 at 5, 4/5 at 8 | At 5: attacks deal 1 damage to the defender's controller's base; at 8: readiness |
| Hero | River Montoya 2/3, 2/4 at 3, 3/4 at 5 | At 3: exhaust → sideline a tech 0 or I patroller (T); at 5: your tech 0 units cost 1 less, floor 0 |
| Tokens | Dancer 0/1, Angry Dancer 2/1 | A token is trashed when it leaves play; the flip keeps runes and damage |
| Add-ons | Tower 4 HP, Surplus 4 HP | Detection once a turn and 1 combat damage to visible attackers; a card at upkeep |

Only four cards have no text at all -- Tenderfoot, Older Brother, Iron
Man and the Rhinoceros -- so there is no "vanilla deck" to start from.
What there is instead is a vanilla *engine*: one that plays every card
for its cost and its numbers, ignores its text, and says so. The steps
start there (step 2), with the cards whose text is still ignored listed
in one table the suite pins, and the table empties by step 6. Nothing is
ever ignored silently.

**The mechanics, grouped the way the steps take them.**

- *Economy and cards* (step 2): gold with its cap; workers and the
  once-a-turn hire; the draw rule and the once-a-phase reshuffle; the
  hand, the discard, the codex and the secret tech choice; the hero's
  summon, levels, bands, healing at a band and the max-level-since-the-
  turn-began condition for ultimates; summoning runes and the levels a
  kill grants; tech buildings, their worker requirements, finishing at
  end of turn, rebuilding for 0 and the 2 damage a destroyed one deals;
  the add-on slot.
- *The board* (step 2): the play zone, the patrol zone's five slots and
  their bonuses, arrival fatigue, exhaust and ready, damage, the two
  runes cancelling, the end-of-turn cleanup, the three attack
  priorities, simultaneous damage, what each kind of card does when it
  dies, the base at 0.
- *The keywords* (step 5): flying and anti-air, stealth, invisible and
  unstoppable with the tower's detection, swift strike, sparkshot's
  adjacency, overpower's excess, obliterate before combat, readiness,
  armor refreshing, frenzy, healing, resist, haste.
- *The effects* (step 6): arrives and attacks triggers; targeting, the
  flagbearer and resist's cost; damage, destruction, runes and debuffs
  for a turn; return to hand and gain control; sideline; the ongoing
  spells with their attachments and channeling; tokens with a limit and
  the flip; granted static abilities (Grounded Guide, Nimble Fencer,
  Blademaster, Maestro) that come and go with the card granting them;
  cost reductions with a floor of 0; the upkeep effects and their
  ordering; the "do as much as you can" rule; the tower's own detection
  on its owner's turn.

### Hidden information, which D12 Ball never had

D12 Ball's whole position is on one public board; the only secret it
ever keeps is a shootout order. Codex is a hidden-information game.

- **The hand** is its owner's alone. **The deck's order** is nobody's.
  **The discard pile** is face-down, so its owner knows it and the
  opponent knows its size. **The tech choice** is secret until the
  cards are drawn and played. **A hired worker's card** is trashed
  unseen. **The codex's size** is public, as a binder on the table is;
  **which cards are still in it** is its owner's, since the teched
  cards are never shown (p. 5, "fog of war").
- So the public channel gets the board and the narration -- a card
  played is a card revealed -- and each player gets their hand, their
  discard and their tech choice privately. On Discord that is the
  ephemeral interaction response: in the channel, seen by the one who
  clicked, gone when they dismiss it, never stored by the bot. Because
  an ephemeral message disappears -- dismissed, or lost with the
  client's session -- the one public message carries the buttons that
  summon it again: **My hand**, one button that answers by who
  clicked it -- for the active player the control panel, the cards in
  their hand pictured with the actions under them; for the other
  player their hand pictured and nothing to press -- the other
  player's **Tech**, and either player's **Codex** -- their own
  codex pictured, through a menu that shows everything, or one tech
  level, or (in the full game) one spec, since a codex is too many
  cards for one picture (the author, 2026-10-08). The bot's #logs mirror
  and any state it prints must never carry a hand or an unanswered
  tech choice; the event log holds card identities and stays in the
  save, since this bot writes no export (the author, 2026-10-07).
- **The tech choice is a second thing a match waits on**, owed by the
  player whose turn just ended while the other player acts. D12 Ball's
  `pending` is one reading with one answer; Codex keeps the one reading
  for the active player's prompt and carries the tech choice as a
  *standing* prompt beside it, answerable any time until its owner's
  next ready phase, which blocks until it is answered (UMR p. 5: "You
  don't need to finish choosing cards until your next turn begins").

### What the three outside sources give

- **The rulebook** (`Codex_UMR_v13w.pdf`, 24 pages, at
  https://gitlab.com/omniraptorr/codex-rules/-/raw/main/Codex_UMR_v13w.pdf?inline=true):
  the rules, a glossary of every keyword, and a card FAQ (pp. 19-22) --
  Dean Ray Johnson's compilation of Sirlin Games' manual and Chris
  Franka's rulings document, under fair use. The author prefers it to
  the official rulebooks (https://sirlingames.com/rulebooks), with which
  it should agree on every matter (2026-10-08). Its rules become code.
  The PDF is committed at `docs/codex/Codex_UMR_v13w.pdf` (the author,
  2026-10-08: "make sure it's in the repo"), so a step reads it from the
  tree and every `UMR p. n` is checkable offline; every card is read against
  it as well as the database.
- **The card database** (`codexcarddb.com`, source at
  `github.com/rgdelato/codex-cards-gatsby`): every card's text, type,
  cost, stats and tech level, each hero's three bands, and Sirlin's
  dated rulings, as JSON under `raw_data/` -- `neutral.json` (the
  starters, Bashing, Finesse, the tokens, the buildings), one file per
  colour, `heroes.json`, `maps.json`, `rulings.json` (a `General` group
  of keyword rulings and a group per colour). On 2026-10-07 that is 310
  printed cards and 20 heroes across twenty specs, 26 rulings on the
  basic set's 36 cards and some sixty on the keywords they use. **The
  rulings are official rules of the game**, Sirlin's own, collected
  there with their dates, and the plan treats them as such: where the
  rulebook's text and a ruling differ, the ruling governs, and every
  ruling on a card in play is implemented and pinned by a test (the
  author, 2026-10-08). A card's page is `/card/<slug>`, the slug
  lowercase with underscores, and its picture is at
  `codexcards-assets.surge.sh/images/<sirlins_filename>`, 330 by 450,
  for every card and hero; the tokens, the workers and the buildings
  have no picture there. The data carries the glyphs as Unicode (`⤵`
  exhaust, `◎` target, `①` a gold), which the import turns into tokens.
  The repository's `LICENSE` is the Gatsby template's MIT; the card
  texts, the rulings and the art are Sirlin Games'.
- **The spreadsheet** ("Newest Codex Forum Game Template"): one
  player's bookkeeping for a play-by-forum game. A `State` tab -- hand,
  deck, discard, the tech choice, workers, the five patrol slots, the
  board, the turn's actions with their gold, base and building HP, a
  gold float -- with Apps Script buttons for *Peek*, *Discard/Draw*,
  *Draw 1 Card*, *Start Game* and *Save Tech Choice*; a `Post template`
  tab that renders the public state as a forum post with the hand and
  the tech choice behind spoilers; and a `List of Cards` tab of every
  spec's twelve and every colour's ten. It enforces no rule. What it
  settles is where the automation pays: the draw rule, the reshuffle,
  the gold arithmetic and the secrecy, and exactly which numbers a
  spectator needs on the public board -- the patrol slots by name, what
  is in play, the buildings with their HP, hand, deck and discard
  *counts*, gold and workers. The board image below shows the same list.
- **The Screentop table** (`screentop.gg/@GRAG/Codex`): two players,
  thirty to sixty minutes, the components and no automation. Its
  module's spec is public through one GraphQL query to
  `api.screentop.gg`, and with it the URL of every sheet it was built
  from: the seven colour card sheets at 375 by 525 a card, the hero
  sheet, the three card backs (card, hero, token), the token and map
  cards, the playmat, the chits. That is where the bot's emoji came
  from and where the token faces and the card backs come from (decision
  6); the table itself was not opened for this plan, and its layout
  settles nothing the rulebook's playmat diagram (p. 3) does not.

### What the repository gives, and what it does not

The D12 Ball bot is four parts (ARCHITECTURE.md): the model, the
service, the Discord frontend, and a web frontend the Codex bot does not
need yet. Each has a shape worth copying and a few leaves worth sharing.

| D12 Ball | Codex | Shared, copied, or new |
| --- | --- | --- |
| `foolbot.py` (`GameBot`, the command-sync gate) | `gamebot.py`, then `codexbot.py` | The bot class and its sync gate are generic once they take the extensions to load, the state file and the name of the sync variable; `foolbot.py` keeps its names and `codexbot.py` is twenty lines over the same class |
| `botlog/` | the same package | Shared once it takes a variable prefix (`FOOLBOT_LOG_*` today: mirror, level, channel level, channel id, channel name, guild id, the deploy notice, the host name), the state file the deploy notice reads, and the bot's name for that notice, which today does not say which bot restarted |
| `botstate.py`, `discord_emoji_cache.py`, `gamelocks.py` | the same modules | Shared as they are: `read_key`/`write_key` already take `state_file`, `ensure_cached_emojis` and `GameLocks` know no game |
| `d12ball/components.py` (`MatchState`, `MATCH_SAVED_FIELDS`) | `codex/components.py` | Copied shape: the saved-fields table with fallbacks from the first commit |
| `d12ball/game.py` (`D12BallGame`, `RuleRefusal`, lobby rules) | `codex/game.py` (`CodexGame`) | Copied shape: a record whose lobby rules refuse with `RuleRefusal`; the refusal cites a rulebook page or a card instead of a Law |
| `d12ball/engine.py` (`RulesEngine`, `rng`) | `codex/engine.py` | Copied shape: every question the frontend may ask, one `random.Random` |
| `d12ball/prompts.py` (`PromptKind`, `PendingPrompt`, `Action`, `pending`, `OPTIONS`) | `codex/prompts.py` | Copied shape, plus `standing_prompts` for the tech choice |
| `d12ball/flow/` (`StepResult`, `FollowOn`, `MODEL_STEPS`, `driver.advance`/`answer`/`apply`) | `codex/flow/` | Copied shape; the steps are a turn's phases and actions instead of a maneuver's |
| `d12ball/special_abilities.py`, `has_special_ability` | `codex/keywords.py`, `codex/effects.py` | Copied idea: one table tying a catalog id to a rule, with the sheet sentence it was built from -- here the card's text and Sirlin's ruling |
| `d12ball/data/` and the import scripts | `codex/data/` and `scripts/import_codex_cards.py` | Copied rule: regenerated whole, never edited by hand |
| `d12ball/tokens.py`, `DiscordTokens` | `codex/tokens.py`, `CodexTokens` | Copied shape: the model marks, the cog draws, nothing in the model holds an emoji |
| `d12ball/render.py` and `d12ball/fonts/` | `codex/render.py` | New drawing over the shared fonts and the imported card art: the cards' own pictures as the board's tiles and the hand's picture in the panel; drawn tiles only for the base and the buildings |
| `d12ball/wire.py` | `codex/wire.py` | Copied: `jsonable` and `to_dict`, one-way, so a web or Godot client later costs nothing here |
| `gamesaves/d12ball/service.py` (`GameService`, `GameResult`, `Narration`, `Batching`) | `gamesaves/codex/service.py` | Copied shape: one door, one save, the result a frontend renders |
| `gamesaves/d12ball/storage.py` | `gamesaves/codex/storage.py` | Copied: `load_games`/`save_games` over `data/codex_games.json`, never raising |
| `cogs/d12ball/` (six mixins), `present`, `render_prompt`, `view_for_prompt` | `cogs/codex/` | Copied shape: the one presenter over a result, the one mapping from kind to view and to picture |
| `cogs/d12ball_views/` (`SafeView.apply`, `may_act_for`) | `cogs/codex_views/` | Copied shape: a view builds from `options` and answers through the service; the gates read `is True` |
| `cogs/d12ball_boards.py` (`BoardRefresher`) | the same class | Shared once two things it reaches for are parameters -- the view it keeps on the board message (D12 Ball's home-or-visitors view) and the predicate that says the full-image link may go up -- and once it can set the message's text beside its picture, which D12 Ball leaves alone; everything else in it is a message and a bucket |
| `cogs/d12ball_helpers.py` | `cogs/game_auth.py` (new, shared) and `cogs/codex_helpers.py` | The authorisation predicates (`game_participant_ids`, `is_game_helper`, `may_act_for_coach`, `may_act_in_game`, `HelperConfirmationRequired`) read only the seat ids and are shared by moving them to a module of their own that `d12ball_helpers` re-exports; `send_new_prompt` the same way; the naming and the token resolver are copied shapes |
| the hub and `LobbyView` | `LobbyView` in the calling channel, and a line on fool-bot's hub | Copied idea, no hub message of its own: a button is delivered only to the application that posted its message, so a button on D12 Ball's hub could not reach the Codex bot, but a command mention on it can (decision 10); the lobby lives where `/codex lobby` is called |
| `tests/` | `tests/` | Flat, with no `__init__.py`, so helpers are imported by bare name: Codex's helpers carry a `codex_` prefix (`codex_positions`, `codex_flow_stubs`), and the stray-save guard in `tests/save_patches.py`, which walks all of `cogs/` and `gamesaves/`, lists the Codex modules that bind `save_games` |
| `scripts/update_main_bot.ps1`, `run_web_app.ps1`, `deploy.ps1` | `scripts/run_codex_bot.ps1`, a slot in `deploy.ps1` | Copied from the web app's runner: no pull, no install, its own pid and logs |
| `tests/test_model_purity.py`, the goldens, `tests/test_driver_full_game.py`, `tests/save_patches.py` | the same, for `codex/` | Copied ratchets; a game-staging helper by card slug instead of `tests/roster.py`'s by-role |

What the repository does not give: anything for hidden information
(every D12 Ball prompt is public), anything for a many-actions turn (a
D12 Ball turn is a few prompts and a roll; a Codex turn is a dozen
clicks by one player), any emoji for a second application (application
emoji belong to one application and are uploaded by hand in the
Developer Portal; there is no upload code), and the application
itself, which the author created on 2026-10-07 -- one, with no test
application beside it (2026-10-08).

## The decisions

These are the ones the plan is built on. Each is the recommendation and
its reason; the author overrules any of them by saying so on the PR,
and the step's prompt is rewritten rather than argued with.

0. **A second bot, with its own token, from this repository, modelled
   on the D12 Ball bot, the basic game first, a slash command for the
   lobby and buttons after it** (the author, 2026-10-07). Everything
   below is under this.

1. **Its own process, its own token, its own files; nothing shared with
   fool-bot at runtime.** `codexbot.py` beside `foolbot.py`, reading
   `CODEX_DISCORD_TOKEN` from the same `.env`; its games in
   `data/codex_games.json`, its bot state in `data/codex_bot_state.json`,
   its own pid and log files; one application in the Developer Portal,
   the live one, and no test application beside it (the author,
   2026-10-08) -- so one Codex bot runs at a time, and a session
   testing from the Mac stops the live host's first, or runs before the
   live host runs one at all. One bot per token is already the rule ([collaboration.md](design/collaboration.md)):
   `update_main_bot.ps1` matches `foolbot\.py`, so it neither stops nor
   counts the Codex bot, the way the web app "is not a foolbot to it"
   (so the entry point's name must not contain `foolbot.py`);
   `data/bot_state.json`'s two keys -- the command tree's fingerprint
   and the deploy notice's sha -- would otherwise be written by both,
   and each bot would re-sync its commands on every start. The Codex
   bot asks for no privileged intent: it is slash commands and buttons,
   so `Intents.default()` without message content, and one less switch
   in the Portal. **What it costs:** a second runner script, a second
   slot in `deploy.ps1`, a second line in Task Scheduler, two
   processes to restart after a pull, and the emoji uploaded again to
   the second application. A Codex cog inside fool-bot's process was
   the author's to choose and was not chosen; it would also have put
   one game's rate-limit buckets and one game's crashes under the
   other's.

2. **Share the leaves, copy the shapes, and look back once.** What is
   already game-agnostic is imported as it is or made so with a
   parameter: `gamelocks.py`, `discord_emoji_cache.py` and
   `botstate.py` as they are; `botlog/` once it takes a variable
   prefix, a state file and the bot's name; the `GameBot` class and its
   command-sync gate out of `foolbot.py` once they take the extensions,
   the state file and the sync variable; the authorisation predicates
   and `send_new_prompt` out of `cogs/d12ball_helpers.py` into a module
   both bots import; `BoardRefresher` once the view it keeps on the
   board message and the full-image-link predicate are parameters.
   Each of those is a move with D12 Ball's tests untouched, done in the
   step that first needs it. What is a *shape* -- `GameService` and
   `GameResult`, `pending` and `PendingPrompt` and `Action`,
   `StepResult` and `FollowOn` and the driver loop, `SafeView`, the
   storage module -- is copied into `codex/`, `gamesaves/codex/` and
   `cogs/codex*`, keeping the names, so whoever can read one bot can
   read the other; its D12 Ball types are in its imports and
   annotations, and only running a second game shows which of them are
   the shape and which the game. Step 8 is that look. **What it
   costs:** duplicated code for a few weeks, and the step that removes
   it.

3. **The model/Discord split holds for Codex from its first commit.**
   `codex/` imports no `discord`, defines no `async def`, and imports
   Pillow only in `codex/render.py`; `codex/flow/driver.py` runs every
   step and answers every action; the cog asks and renders. The ratchet
   in `tests/test_model_purity.py` covers the two new packages. A whole
   game is played through the driver with no frontend imported (step 2)
   before any Discord code is written (step 3). It is what made the web
   app possible for D12 Ball, Codex has more state to get wrong, and a
   Codex AI or web client later inherits it for nothing.

4. **Hidden information goes through ephemeral interaction responses in
   the game channel, never DMs.** An ephemeral response is in the
   channel, seen by the one who clicked, gone when dismissed, and stored
   nowhere, so nothing the bot keeps can leak it; no DM permission is
   asked for; and a restart loses nothing because the state is the
   service's -- a public **My hand** button rebuilds the view. The active
   player's whole main phase is driven from **one ephemeral panel edited
   in place** by each click (a component interaction may edit the message
   it sits on), so the public channel carries one message per turn --
   the board, the turn's lines and the game's buttons (decision 5) --
   and nothing else, and an observer sees what a spectator at the
   table sees -- and, once the turn is over, a summary of it, which the
   author asked for on 2026-10-07. The panel pictures the cards in the
   player's hand (the author, 2026-10-08), so playing from it is
   looking at the cards, not at their names. **What it costs:** an
   ephemeral message dies with the client session and cannot be found
   again by the bot, so every entry point -- **My hand** on the turn
   message, `/codex hand`, `/codex resume` -- creates a fresh one rather
   than editing an old one; and hidden zones have to be kept out of
   every log line and the
   #logs mirror, which is a hard rule the design note states. **The
   fallback**, if the author prefers D12 Ball's shape of public prompts:
   the same views posted publicly with the hand select ephemeral; it is
   a change to `present`, not to the model.

5. **One public message per turn, carrying the board as a rendered
   image and the turn's lines as its text, edited after every action
   through the write gate.** An image, not an embed (the author,
   2026-10-07). When a turn begins the cog posts the turn's message:
   its text "Turn 7 -- perrytom (Bashing)" and the lines the turn has
   said so far, its attachment the board `codex/render.py` draws with
   Pillow in `asyncio.to_thread`. **The board is the game's own art,
   drawn element by element** (the author, 2026-10-08: card art
   wherever possible, the pieces from screentop.gg, and no playmat --
   step 3 laid the position on the module's mat, and the author's
   review of the design canvas,
   https://claude.ai/artifact/2gJhY3oDWjVNvweAW1XY7f, replaced it with
   a panel built from parts, so that less of the picture is anything
   but cards and nothing is drawn for a place the position does not
   use). Each side is a **panel**: cards at 200 by 273 (the art at
   61%) in square cells of 273, so that a card turned on its side lies
   at full size too (the author, 2026-10-08) -- five columns in the
   basic game, seven in the standard one, the count the game's and
   fixed when it starts so the picture's width holds from turn to turn
   (the author, 2026-10-08); a column of buildings on
   the left, the mat's left edge kept -- the add-on slot, Tech III, II
   and I as the module's tiles, greyed until built, the house chit on
   one under construction or destroyed, and the base with a heart drawn
   over its tile carrying the HP it has now; the patrol zone across the
   top of the grid on the mat's blue, its five slots the mat's own
   pictures cut from the playmat with their bonuses printed under them,
   a patroller's card covering its slot; the command zone as a rounded
   plate per hero, the hero's card lying on it in full with its
   summoning-rune chit while off the field and the plate empty while
   the hero is on it; the field after the plates in the same rows --
   the heroes first with their level chits, then the units, each with
   its damage and rune chits, an ARRIVED tag the turn it came, and on
   its side at full size with the exhaust glyph when exhausted
   -- rows added as the position needs, so the panel's height follows
   it; and a nameplate along the outer edge with the player, the spec
   and hero, and GOLD, WORKERS, HAND, DECK, DISCARD and CODEX as a word
   and a count each, the active player's carrying a gold rule and
   "<Hero>'s turn <n>". Nothing of the playmat is drawn but the five
   patrol cuts; the draw, discard and workers are counts, since a box
   printed for a pile says nothing a number does not. The two panels
   are **stacked**, the default -- the table seen from the active
   player's side, their panel below and the other player's above it,
   turned round whole to face them so the two patrol zones meet, its
   nameplate alone kept the right way up (the author, 2026-10-08) --
   or **side by side**, neither turned, and a
   button on the turn message swaps the game
   between the two (the author, 2026-10-08); the layout is the game's,
   kept on the record, so everyone sees the same picture. Nothing is
   drawn that a piece or a card already shows, the base's HP apart.
   What the canvas left open on 2026-10-08 -- whether the ground is
   flat or the mat's leather -- step 7's PR asks. After every action the
   message is edited with the new lines and the re-rendered board; when
   the turn
   ends it is edited a last time and stands, so the channel's history
   reads as one picture per turn with the actions that led to it -- the
   shape of the forum post the spreadsheet generates, which is where
   the author has played. The new turn's message is pinned and the old
   one unpinned, the rollover D12 Ball's `post_new_play_board` already
   does, so the pin is always the current position. **Why not an
   embed**, since the author asked what the difference is: an embed is
   Discord's structured text card -- a colour stripe, a title, up to 25
   named fields of 1024 characters, a footer -- so it costs nothing to
   build, edits instantly, can be copied, searched and read aloud, and
   is crisp on a phone; but it has no geometry: five patrol slots with
   tiles in them, an exhausted card turned sideways, two halves facing
   each other are beyond it, and its inline columns stack on a phone. An
   image has the geometry and reads at a glance; every edit is a render
   in a thread and an upload of the whole picture, its text is small on
   a phone, and only an eye can test it. The author chose the image, and
   nothing in the bot is an embed. **Rate limits:** exactly one message
   per channel is edited -- the current turn's -- as in D12 Ball,
   through the same gate, which coalesces a burst of clicks into one
   trailing edit and now sets the message's text beside its picture; a
   cascade of the bot's own steps is one edit; there is no other public
   message per action. **What it costs:** a render and an upload per
   edit, which the gate's interval already paces, and a renderer to
   write and look at.

6. **The cards are data imported from the database's repository, never
   typed.** `scripts/import_codex_cards.py` fetches the ten `raw_data`
   files from `rgdelato/codex-cards-gatsby` at a commit pinned in the
   script, turns the glyphs into tokens, and writes `codex/data/cards.json`,
   `heroes.json` and `rulings.json` whole -- the rule `d12ball/data/`
   already lives under: regenerated whole, never edited by hand, the
   import the only way. A card is keyed by its slug (`trojan_duck`) and
   never held or compared by name; the catalog is the way back to a
   name. All 310 cards and 20 heroes come in at once, so a later spec is
   code, not data. **The art comes in with them** (the author,
   2026-10-08: "definitely use card art wherever possible", and the
   board art from screentop.gg): the same import fetches each card's
   and hero's picture by its `sirlins_filename` from the database's
   image host into `codex/images/cards/<slug>.jpg`, 330 by 450, and
   from the Screentop module's public sheets, into `codex/images/board/`,
   the playmat, the building and add-on tiles, the spec cards, the
   patrol-slot icons, the damage, level and time-rune chits, the token
   faces (Dancer, Angry Dancer, Mercenary) and the three card backs --
   each sheet's URL read from the module's spec and each cell's index
   pinned in the script after one look. Nothing is redrawn that the
   module or a card already shows. `/codex card` answers with the
   card's picture, its text and its rulings, and links the database's
   page. **What it costs:** the texts, the rulings and the art are
   Sirlin Games' words and pictures, reproduced in a public repository
   as the fan database and the Screentop module reproduce them. The
   author took that on 2026-10-07 (question 1); the alternatives
   weighed and set aside were the facts alone in the tree with the
   prose fetched per checkout, the bot speaking only in its own words
   with the rulings as cited paraphrases, and a private home for the
   prose.

7. **A card's rules are code keyed by its slug: keywords as a closed
   table, unique text as one handler per card, and every ruling a
   test.** `codex/keywords.py` holds the keyword table the engine's
   combat and targeting questions read; `codex/effects.py` the handlers
   for arrives, attacks, upkeep, static and ability text, each beside
   the sentence it was built from, and `UNIMPLEMENTED`, the set of slugs
   the engine still plays for their numbers alone, which a test pins
   step by step until it is empty. Each of Sirlin's rulings on the set's
   cards and keywords is an official rule and is treated as one (the
   author, 2026-10-08): implemented, and pinned by a test named for the
   card with the ruling as its docstring; where the rulebook's text and
   a ruling differ, the ruling governs, and a rules question is answered
   from the rulings before it is taken to the author. It is how
   `SPECIAL_ABILITIES` and `has_special_ability` work for D12 Ball, and
   it is what keeps a bug and a decision apart when the author is not
   the designer.

8. **The tech choice is a standing prompt beside `pending`, open to
   change until the ready phase confirms it.** `pending` stays one
   reading with one answer, the active player's; `standing_prompts(match)`
   lists what the other player may answer meanwhile -- in this set only
   `TECH_CHOICE`, offered ephemerally when their turn ends and
   answerable again from the **Tech** button for as long as the
   opponent's turn lasts, each answer replacing the last -- and
   `driver.answer` takes an action for either. The owner's next turn
   opens on `TECH_CONFIRM`, the pending prompt that shows them their
   picks -- or the picker, if they never chose -- with **Confirm** and
   **Change**; the ready phase runs only once it is answered, and the
   confirmed cards go face-down to the discard then (the author,
   2026-10-08). One chain, two readers, because a second copy of "what
   is this match waiting on" is the failure mode CLAUDE.md names.
   (In a test game nothing stands: each side's tech is chosen in its
   own ready phase -- the author, 2026-10-09;
   [codex.md](design/codex.md), "The standing prompt".)

9. **Every draw the game makes is `engine.rng`.** The shuffle, the
   opening hand and the first player are the only randomness in the
   basic game; tests seed it; nothing under `codex/` imports `random`.

10. **The lobby is the one slash command a game needs; everything after
    it is a button.** `/codex lobby` posts the lobby in the channel it
    is called in, with the two heroes as seats (**Play Bashing**, **Play
    Finesse**), **Leave**, and **Start** for either seated player once
    both seats are taken. Start creates `codex-<n>` under a **Codex
    Games** category, shuffles, deals, picks the first player at random
    (UMR p. 3) with the rule's 4 and 5 workers, and posts the first
    turn's message, which carries the game's buttons: **My hand** for
    either seated player -- the control panel when the active player
    presses it, the hand alone when the other does: one button,
    different answers by who clicked (the author, 2026-10-08) --
    **Tech** for the other player, **Codex**, **Swap view** and
    **Concede** for either. The slash commands kept beside it: `hand`, `board`,
    `card`, `rules`, `games`, `concede`, `resume`, and the admin
    `abandon` and `reset_channels`. **The hub.**
    The author would have fool-bot's hub carry a button that starts a
    Codex lobby (2026-10-07). Discord delivers a component's
    interaction only to the application that posted the message, and
    has no way for one application to run another's command, so a
    button on fool-bot's hub cannot reach the Codex bot. The nearest
    thing Discord allows is a **command mention**: `</codex lobby:ID>`
    in a message renders as a clickable chip that puts `/codex lobby`
    into the clicker's composer, one keypress from sending, for any
    application's command whose id is known. So fool-bot's hub message
    gains a Codex line with that mention, and the Codex bot writes its
    top-level command ids to `data/codex_command_ids.json` after each
    sync for fool-bot to read when it renders the hub -- one shared,
    read-only file across the line, as the statistics' read of the web
    games is for D12 Ball -- falling back to the command's name in plain
    text when the file is absent. A hub message of the Codex bot's own
    is not built: it would need its own permission overwrite in the
    locked hub channel and a second message to keep, for a chip that
    does the same thing.

11. **Undo, with its infrastructure in the model's first commit** (the
    author, 2026-10-07: "definitely need an undo"). Two undos are built
    in these steps: **to the start of this turn**, the active player's
    own, with nobody's consent asked; and **to the start of the
    previous turn**, which unwinds the opponent's turn as well, so the
    opponent confirms it with a button of their own, or a helper does.
    What makes both cheap, and a finer one possible later, is laid down
    in step 2: the match keeps a **snapshot of the position at every
    turn start**, bounded to the last three, and a **journal of the
    turn's actions**, each with the random outcomes it consumed (a
    reshuffle's order), so that any point in a turn is a snapshot plus
    a replay of the journal up to it, and the replay reproduces the
    position byte for byte -- a test says so. `driver.apply` is the one
    door, so it is where the journal is written; `begin_turn` is where
    the snapshot is taken. Because a replay reuses the recorded
    outcomes, an undo past a draw deals the same cards again: undo
    cannot be used to redraw. Hidden information is in the save
    already, so a snapshot exposes nothing new. The finer undo -- to
    any action of a turn -- is a view and a service method over the
    same journal; it was built on 2026-10-10 as the author decided it:
    points between actions only, a card off a deck's top closing the
    points before it while the start of the turn stays open, and
    nothing into the previous turn (docs/design/codex.md, "The undos").
    **What it costs:** two saved fields from the first commit, a
    shuffle that can take a recorded order back, and every frontend
    surface -- the panel, the turn message, the board -- re-rendering
    from the position after an undo rather than from what it last
    showed. The panel still guards against the misclick structurally:
    the defender is asked after the attacker, a card's cost is shown
    before it is chosen, and **Lock patrol** and **Save tech** stand
    alone in their row.

12. **The rules reference is the imported rulings and a link.**
    `/codex rules <keyword>` answers from the `General` rulings; `/codex
    card <name>` shows a card's text and its rulings; both link the
    database. The bot serves no rulebook text and `docs/living-rules.md`
    is not touched: nothing in the bot wants a second copy of Codex's
    rules. The rulebook's PDF is in the tree (`docs/codex/`) for the
    developers to read, not for the bot to quote (the author,
    2026-10-08). The bot words its refusals itself
    ("Iron Man can't attack: it arrived this turn"), citing the rulebook
    page the way D12 Ball cites a Law.

13. **No AI opponent in these steps.** Two humans. The shape exists
    (`AIStrategy.choose` over `PendingPrompt.options`) and a random
    legal player would help the tests; it is on the list of what is not
    here.

## Questions for the author

Each step's PR carries a `## Questions to the author` section; these
are the ones known before any step starts. A step whose prompt needs the
answer says what it builds until it has one.

1. ~~**Card text and rulings bundled as data in this repository** -- the
   fan database reproduces them openly, and a bot cannot play without
   the text. Built as yes. If no, the import stays and the data moves
   out of the tree into `data/` on each checkout, fetched at startup.~~
   Answered by the author on 2026-10-07: yes, everything goes in the
   tree -- the texts and the rulings beside the facts, as decision 6
   has it.
2. ~~**A rendered board image, or Discord embeds?**~~ Answered by the
   author on 2026-10-07: an image, not an embed. Decision 5 has the
   difference between the two and the shape that follows -- one
   message per turn, the board as its picture and the turn's lines as
   its text.
3. ~~**No undo at all?** Built as none. The alternative worth having is
   a helper's "back to the start of this main phase" when nothing
   hidden has been revealed since.~~ Answered by the author on
   2026-10-07: definitely an undo -- to the start of this turn and to
   the start of the previous turn in these steps, and the infrastructure
   for a finer one from the first commit (decision 11).
4. ~~**One ephemeral panel for the active player, or public prompts as
   D12 Ball posts them?** Built as the panel.~~ Answered by the author
   on 2026-10-07: the panel is fine, with a public message edited after
   each action that stands as the turn's summary once it is over
   (decisions 4 and 5).
5. ~~**A hub message per guild, as D12 Ball has, or the lobby where the
   command is called?**~~ Answered by the author on 2026-10-07: the
   lobby starts from `/codex lobby`, and fool-bot's hub points at it
   the one way Discord allows across applications, a command mention
   (decision 10). The wording of that hub line is the author's, asked
   for on step 3's PR.
6. ~~**Which channel mirrors the Codex bot's errors?**~~ Answered by
   the author on 2026-10-07: the same #logs channel. `botlog` reads
   `CODEX_LOG_*` for this bot, falling back to the `FOOLBOT_LOG_*`
   values when a `CODEX_` one is unset, and every notice it posts names
   the bot ("**Codex bot restarted**"), so one channel carries both.
7. ~~**Does the Codex bot carry `/roll`, the coins or the Tethys
   deck?** Built as no.~~ Answered by the author on 2026-10-08: no;
   one bot, one game; those stay fool-bot's.
8. ~~**May anyone in the server read a game's channel?** Built as
   yes.~~ Answered by the author on 2026-10-08: yes, as D12 Ball's
   channels are; the hands are ephemeral, so a watcher sees the table
   and nothing more.
9. ~~**Which specs after Bashing and Finesse?**~~ Answered by the
   author on 2026-10-08: all six colours, two at a time -- red and
   green first, then purple and black, then white and blue. The data
   for all twenty specs comes in at step 1; the colours are steps 10 to
   13, after the basic game.

## The steps

In the order they pay off. Each is one branch off an up-to-date `main`,
one PR against the template, the suite green, the six D12 Ball
safety-net tests untouched unless the step says why. None changes
D12 Ball's save format or any file under `d12ball/`, `gamesaves/d12ball/`
or `cogs/d12ball*` except where a step names one. Every step ends on a
**stop**: the thing the author looks at before the next step is worth
starting.

| # | Step | Size | Stop |
| --- | --- | --- | --- |
| ~~1~~ | ~~The second bot stands up, and knows the cards~~ -- landed; what it settled is in docs/design/codex.md, "Its own process, its own token" and "The cards are data" | medium | `/codex card trojan duck` answers in the test server, and both bots run on the live host after one `deploy.cmd` |
| ~~2~~ | ~~A whole game through the driver, with no frontend~~ -- landed; what it settled is in docs/design/codex.md, "The model, before a line of Discord" | large | a test plays Bashing against Finesse to a destroyed base with nothing from `cogs/` or `discord` imported |
| ~~3~~ | ~~The lobby, the channel and the board~~ -- landed; what it settled is in docs/design/codex.md, "The service and its file", "The lobby and the channel", "Who may act, shared", "The board on Discord" and "Hidden information on Discord" | medium | two people reach the opening position on Discord: a channel, a board, a hand each that the other cannot see |
| ~~4~~ | ~~The turn on Discord, and the two undos~~ -- landed; what it settled is in docs/design/codex.md, "The turn on Discord" | large | two people finish a game on the vanilla engine; a bot restart mid-turn resumes from **My hand**; an undo to the start of the turn puts the board, the turn message and the panel back |
| ~~5~~ | ~~The keywords~~ -- landed; what it settled is in docs/design/codex.md, "The keywords" and "Which choices an attack asks, and which it does not" | medium | Eggship flies over a patrolling Leaping Lizard and takes its damage; every keyword ruling of the set is a test |
| ~~6~~ | ~~Triggers, spells and the ongoing spells~~ -- landed; what it settled is in docs/design/codex.md, "Targeting and the effects" | large | every card of the set does what it says; `UNIMPLEMENTED` is empty |
| ~~7~~ | ~~The board drawn element by element~~ -- landed; what it settled is in docs/design/codex.md, "The board on Discord" and "The cards are data" | medium | a mid-game board on the test server is the canvas's stacked board: cards at 200 by 273, the far side turned to face the near one, nothing of the mat but its five patrol slots |
| ~~8~~ | ~~Finishing a game: concede, abandon, rematch, the golden~~ -- landed; what it settled is in docs/design/codex.md, "The end of a game" and "The golden" | small | a finished game ends cleanly, offers a rematch and is moved aside; a seeded whole game is pinned byte for byte |
| ~~9~~ | ~~The look back: what turned out identical moves to one home~~ -- landed; what it settled is in docs/design/codex.md, "What the two games share" | small | nothing copied in steps 1 to 8 remains byte-identical in two places |
| ~~10~~ | ~~The standard game's rules, over the red and green data~~ -- landed; what it settled is in docs/design/codex.md, "The standard game" and "The vanilla engine and `UNIMPLEMENTED`" | large | three heroes a side, a spec chosen at Tech II, the heroes' hall and the tech lab built, a red team against a green one with every card still played for its numbers |
| ~~11~~ | ~~Red and green: every card does what it says~~ -- landed; what it settled is in docs/design/codex.md, "Red and green" | large | `UNIMPLEMENTED` empty again; Calamandra against Jaina, the Core Set's own first game |
| ~~12~~ | ~~Purple and black~~ -- landed; what it settled is in docs/design/codex.md, "Purple and black" | large | the same for the Vortoss Conclave and the Blackhand Scourge |
| ~~13~~ | ~~White and blue~~ -- landed; what it settled is in docs/design/codex.md, "White and blue" | large | the same for the Whitestar Order and the Flagstone Dominion; every printed card plays |
| -- | Later, and not now | -- | |

### Claiming a step

The series does not exist yet: **step 1's prompt adds it** -- one entry
in `SERIES` in `scripts/claim_web_step.py`
(`"codex": ("docs/codex-bot.md", "codex-step", "Codex step")`), plus
the `--series` help string and the module docstring, which both list the
series by hand. From then on
`python3 scripts/claim_web_step.py --series codex <n>` claims a step the
way the other series are claimed: an empty commit on `codex-step-<n>`
pushed create-only, refused if the row is struck on `origin/main`, the
branch exists, or an open PR is titled `Codex step <n>:`. A step lands by
striking its row above (`| ~~n~~ | ~~title~~ -- landed; what it settled is
in docs/design/codex.md | ... |`).

**The cloud routine** (the author, 2026-10-08): `trig_01FZvSJE78cUuHfbbNN97QPa`,
"fool-bot: start the next Codex step", runs on Claude Opus 5.5 and fires
on every pull request closed in this repository, with a run every eight
hours as a fallback. Each run works through its gates -- the worksheet
on `main`, the first unstruck row with a prompt written, nobody's claim
on it and no `Codex step` PR open, the suite green on `main` -- then
claims the step (by hand for step 1, since step 1 adds the series),
runs the preamble and the step's prompt, strikes the row, and opens a
PR titled `Codex step <n>: ...`. Most fires find nothing to do and exit
in a minute. **Every PR it opens carries two sections for the author**
besides the template's: `## Questions to the author` (`None.` when
empty) and `## For the author`, in two parts -- what to do on the live
host after merging (`deploy.cmd`, every new `.env` variable by name,
every emoji to upload to the Codex application, any Discord-side
setup; "Nothing to do on the live host" when that is true) and what can
be tested in the server now, command by command, with what should
happen and what is not expected to work yet. A step whose section has no
prompt stops the routine with a report, never a guess -- none since
2026-10-09, when steps 10 to 13 were written, and the rule stands for
a step added later. A PR it opened that is closed without
merging is a rejected step: it does not open it again, and a human
claims the step to redo it.

## Preamble

Every step's prompt begins with this block. A session given a step reads
it first, then the step's own prompt below.

```text
You are working in the fool-bot repository on the Codex bot planned in
docs/codex-bot.md: a second Discord bot, run from this repository as its
own process with its own token, modelled on the D12 Ball bot, playing
Sirlin Games' Codex -- the basic game, Bashing against Finesse. Read
that worksheet first (the section "The game, in the terms the code will
use" is the rules you implement; the card table is the scope), then the
design note docs/design/codex.md if it exists, then
docs/design/model-discord-split.md and docs/design/game-service.md (the
shape you are copying). Read the rest of docs/design/ only where a step
names a file.

Start on a fresh branch off an up-to-date main (the claim script has
made it: git fetch && git checkout codex-step-<n>), in a worktree of
your own if another session may be using the checkout. Never work on
main.

Hard rules for every step:
- codex/ and gamesaves/codex/ import no discord, define no async def,
  and import Pillow only in codex/render.py. The purity ratchet
  enforces it; do not loosen the ratchet.
- A rule is a question the model answers and the cog asks. Nothing in
  cogs/codex* decides a rule, computes a candidate list, a cost, a legal
  defender or a draw count; a view builds its controls from
  PendingPrompt.options and nothing else, and the driver refuses what
  the options do not offer, with RuleRefusal, never a bare ValueError.
- Cards are keyed by slug and never by display name. Card data comes
  from scripts/import_codex_cards.py and nothing edits codex/data/ by
  hand. A card whose text the engine does not yet honour is in
  codex.effects.UNIMPLEMENTED, and the test that pins that set changes
  in the same commit as the engine.
- Nothing that is hidden -- a hand, a deck's order, a discard pile's
  contents, an unanswered tech choice, a hired worker's card -- is
  written into a public message, a log line or the #logs mirror. Say
  in the PR where you checked.
- A ruling is a rule. Sirlin's rulings in codex/data/rulings.json are
  official rules of the game: the engine does what a ruling says, a
  test pins it with the ruling as its docstring, and where the
  rulebook's text and a ruling differ the ruling governs. A rules
  question is answered from the rulings first and taken to the author
  only when they are silent.
- Read every card you implement against the card database AND the
  rulebook -- its rules, its glossary and its Card FAQ (pp. 19-22) --
  not the database alone. The rulebook to read is the Unofficial
  Manual Rewrite v1.3, which the author prefers, committed at
  `docs/codex/Codex_UMR_v13w.pdf` (also at
  https://gitlab.com/omniraptorr/codex-rules/-/raw/main/Codex_UMR_v13w.pdf?inline=true)
  and cited as "UMR p. n". The official rulebooks are at
  https://sirlingames.com/rulebooks; the two should agree on every
  matter, and a disagreement is a question for the author. Neither is
  committed to this repository: fetch it, read it, cite its pages.
- Card art wherever a card exists: the board's tiles, the panel's hand
  and /codex card show the cards' own pictures from codex/images/cards/;
  nothing is redrawn that a card already shows, and drawn tiles are
  for the base and the buildings alone.
- Every draw the game makes is engine.rng. A test seeds it.
- Rate limits: the fix is always fewer requests, never slower ones.
  One message per channel is edited, the current turn's -- the board
  with the turn's lines -- through the gate; the active player's panel
  is ephemeral and edited through its own interactions; a cascade of
  the bot's own steps is one edit and nothing more. Nothing is an
  embed. Read docs/design/rate-limits.md before adding any send, edit
  or pin.
- Nothing under d12ball/, gamesaves/d12ball/ or cogs/d12ball* changes
  unless the step names the file and says why. The D12 Ball save
  format, docs/living-rules.md and the six D12 Ball safety-net tests
  are not touched.
- Nothing rendered is tested for how it looks: render it
  (scripts/render_codex_sample.py once step 3 adds it) and look, and
  put the picture in the PR.
- tests/ is flat and its helpers are imported by bare name, so every
  Codex test helper is named codex_<thing>.py, and every Codex module
  that binds save_games is listed in tests/save_patches.py's tables
  (the stray-save guard walks all of cogs/ and gamesaves/).
- A leaf that both bots use is moved, not copied: the move names the
  D12 Ball file it touches, the D12 Ball tests pass unchanged, and
  d12ball's module keeps re-exporting the old name.
- Run python3 -m unittest discover -s tests before the PR; a full run
  must not create data/. The PR is against the template, carries a
  "## Questions to the author" section ("None." when empty) and a
  "## For the author" section in two parts -- what to do on the live
  host after merging (deploy.cmd; every new .env variable by name and
  what goes in it; every emoji PNG to upload to the Codex application
  in the Developer Portal, by name; any Discord-side setup; or
  "Nothing to do on the live host") and what can be tested in the
  server now, command by command, each with what should happen, and
  one line on what is not expected to work yet -- and strikes this
  step's row in docs/codex-bot.md. When the step settles something the
  worksheet only proposed, write it into docs/design/codex.md with the
  reasoning, and add a row to CLAUDE.md's tables only for a new module
  or a new hard rule.
```

### 1. The second bot stands up, and knows the cards

**Landed** (2026-10-08, by the cloud routine): the bot, the card data,
`/codex card` and `/codex rules`, the runner and the design note --
[design/codex.md](design/codex.md), "Its own process, its own token",
"The cards are data", "The reference commands" and "Running it". **The
art followed** on the `codex-art` branch: neither image host was
reachable from the session that ran the step, so the author ran
`scripts/import_codex_cards.py` on the Mac on 2026-10-08, and a session
pinned the Screentop sheets' cells from what that committed ("The cards
are data" says what is where).

The first thing anybody sees: a bot that answers `/codex card` with a
card's text and Sirlin's rulings. It is also everything the later steps
stand on that is not the game -- the entry point, the token, the deploy
slot, the data import and the design note -- so that step 2 is only the
model and step 3 only the frontend.

```text
Step 1 of docs/codex-bot.md. Nothing has landed before it. Also read
docs/design/collaboration.md ("One bot per token" and "Running the web
app"), docs/design/logging.md and docs/design/rules-and-data.md (the
import-script rule, which the card data inherits).

Four commits, in this order.

1. The claim series. scripts/claim_web_step.py gains
   "codex": ("docs/codex-bot.md", "codex-step", "Codex step") in SERIES,
   and the --series help string and the module docstring list it. Then
   claim this step with it (python3 scripts/claim_web_step.py --series
   codex 1) and continue on codex-step-1.

2. The card data. scripts/import_codex_cards.py fetches, from
   https://raw.githubusercontent.com/rgdelato/codex-cards-gatsby/<sha>/raw_data/,
   the files neutral.json, red.json, green.json, blue.json, black.json,
   white.json, purple.json, heroes.json, maps.json and rulings.json,
   with <sha> a commit pinned in the script (today's head of master;
   record it in a module constant and in a "source" header of every
   generated file). --offline <dir> reads the same files from a local
   checkout. It writes codex/data/cards.json (every non-hero record,
   tokens and buildings included, with a kind field: card, token,
   building, worker), codex/data/heroes.json and codex/data/rulings.json,
   whole, sorted by slug. The slug is the database's card URL slug:
   lowercase, spaces to underscores, punctuation dropped, as
   codexcarddb.com/card/<slug> spells it; two records with one name
   (the token faces) collapse to one. The glyphs in the texts become
   tokens the way d12ball/tokens.py writes them: ⤵ to {exhaust}, ◎ to
   {target}, ① ② ... to {gold:n}, → to {arrow}; the rules_text_1..3 lines
   become a list; a hero's three bands become a list of {min_level, atk,
   hp, text}. Nothing else is reworded. Regenerated whole, never edited
   by hand -- say so in the file header as d12ball/data/ does.

   The art, in the same run (decision 6): every card's and hero's
   picture from http://codexcards-assets.surge.sh/images/<sirlins_filename>
   into codex/images/cards/<slug>.jpg (330 by 450; the records without a
   sirlins_filename -- tokens, workers, buildings -- have none there);
   and from the Screentop module @GRAG/Codex, whose spec one GraphQL
   query to https://api.screentop.gg/ returns
   ({ user(name:"GRAG"){ game(name:"Codex"){ revision(name:"main"){ spec
   } } } }, with every sheet's URL under spec.assets.entries), into
   codex/images/board/: the playmat whole; from the "Mini Cards" sheet
   (10 by 4) the Base, Tech I, II and III tiles, the four add-on cards,
   the five patrol-slot icons and the twenty spec cards; the "Card
   Backs" sheet's three backs; the Dancer, Angry Dancer and Mercenary
   faces from the "Token and Map Cards" sheet; the "Damage", "Levels",
   "Time Runes" and "Chits" sheets cut into their cells. Each cell's
   index is pinned in the script after one look at the sheet, with the
   sheet's name beside it, so a re-import is deterministic; --no-images
   skips the lot. The images are committed like the data: regenerated
   by the script, never edited by hand.

   codex/cards.py reads them: Card and Hero dataclasses, and CardCatalog
   with by_slug, by_spec(spec), starting_deck(color) (the ten, in the
   data's order), codex_for(spec) (two copies of each of the twelve),
   hero_for(spec), token(slug), building(slug), and name(slug) -- the
   one way back from a slug to a name. codex/formatting.py: card_label
   ("Trojan Duck (7) 8/9"), the plain-text rendering of a text line's
   tokens, and nothing that touches Discord. codex/rulings.py:
   rulings_for(slug) and keyword_rulings(keyword) over the General
   group, each ruling as (author, date, text).

   tests/test_codex_cards.py: the data loads; every slug is unique; the
   36 cards of the basic set and the two heroes are present with the
   costs, stats and tech levels the worksheet's table gives; every
   ruling names a slug in the catalog or a General keyword; no text
   still contains ⤵ ◎ or a circled digit; starting_deck("neutral") is
   ten cards and codex_for("bashing") is twenty-four; every card and
   hero of the basic set has its picture under codex/images/cards/ at
   330 by 450, and codex/images/board/ holds the playmat, the three
   backs, the three token faces and the tiles the board draws.

3. The bot. gamebot.py is new: GameBot(commands.Bot) moved out of
   foolbot.py and made to take what foolbot.py hard-codes -- the
   extensions to load, the state file the command-tree fingerprint is
   kept in, the name of the variable that forces a sync, and whether
   the message-content intent is wanted -- with foolbot.py passing
   today's values (cogs.coins, cogs.d12ball, cogs.tethysdeck,
   cogs.debug; data/bot_state.json; FOOLBOT_COMMAND_SYNC; yes) and
   keeping every module-level name tests/test_command_sync.py patches,
   so that test passes unchanged. botlog takes a variable prefix, the
   state file its deploy notice reads (deploy_notice binds
   botstate.STATE_FILE at import today and announce_startup has no
   parameter for it -- give both one) and the bot's name, which the
   deploy notice and the gateway-recovery notice then say; foolbot.py
   passes "FOOLBOT", the default file and "fool-bot", and
   tests/test_botlog.py passes unchanged. codexbot.py is then twenty
   lines: load_dotenv, botlog with prefix "CODEX" (each CODEX_LOG_*
   variable falling back to its FOOLBOT_LOG_* value when unset, so one
   .env serves both bots), data/codex_bot_state.json,
   CODEX_COMMAND_SYNC, the token from CODEX_DISCORD_TOKEN,
   Intents.default() with no message content, and cogs.codex alone --
   no /roll, no coins, no Tethys deck, no d12ball.
   tests/test_web_purity.py's list of entry points that import no
   webapp gains codexbot.py.

   cogs/codex/ is a package whose __init__.py assembles
   Codex(commands.GroupCog, group_name="codex", group_description="Play
   Codex -- one game per channel.") -- the description passed
   explicitly and under 100 characters, or tree.sync() fails inside
   setup_hook -- from one mixin for now, cogs/codex/reference.py:
   /codex card <name> with autocomplete over the catalog, answering
   with the card's picture attached and, as plain text under it, the
   name and type line, cost, ATK/HP or the three bands, the text with
   its tokens rendered, the rulings with author and date, and a link to
   http://codexcarddb.com/card/<slug> -- no embed, as nothing in this
   bot is -- and /codex rules <keyword> with autocomplete over the
   General group, answering with the keyword's rulings as the official
   rules they are.
   cogs/codex_helpers.py holds CodexTokens, the resolver from token to
   emoji or word, and nothing else yet. In this step every token
   renders as a word: application emoji belong to one application and
   are uploaded by hand in the Developer Portal (there is no upload
   code), so draw the PNGs the resolver will want -- gold, exhaust,
   target, the two heroes -- into codex/images/emoji/ with a script
   under scripts/, list them for the author in the PR, and let the
   resolver pick each up by name once it is uploaded, the way
   cogs/d12ball_helpers.py's loaders fall back. One is there already:
   codex/images/emoji/codex.png, the medallion from the back of every
   card -- the gold ring, the six gems and the pyramid -- cut from the
   Screentop module's "Card Backs" sheet (@GRAG/Codex; the module's
   spec, with every asset's URL, is public through a GraphQL query to
   api.screentop.gg) on 2026-10-07, 128 px with transparent
   surroundings, the bot's own mark -- the {codex} token the lobby and
   the turn message open with; the author uploads it to the application
   by hand like the rest. Every token is rendered
   at the cog's door, never in the model.

   scripts/run_codex_bot.ps1 and run_codex_bot.cmd, modelled line for
   line on run_web_app.ps1: no pull and no install; stops every
   codexbot\.py run by this checkout's venv python plus whatever
   data/codexbot.pid names, refuses to start if any survive, starts
   hidden with data/codexbot.stdout.log and .stderr.log, fails if the
   process has exited after four seconds. deploy.ps1 calls it after
   update_main_bot.ps1 and before run_tunnel.ps1, with the one-line
   reason in its comment. .gitignore lists the new data files by name.
   requirements.txt does not change.

4. The documents. docs/design/codex.md is created with the standard
   header line and these sections: what the bot is and what it plays;
   "Its own process, its own token" (decision 1 of the worksheet, with
   the matcher argument); "The cards are data" (decision 6, the pinned
   commit, the slug, the glyph tokens, where the copyright question
   stands); "Running it" (the Mac command, the K:\ runner, the one Developer
   Portal application, and why there is no test one). CLAUDE.md: its first
   paragraph says the repository runs two bots and names this one; "##
   Running it" gains python3 codexbot.py; "Where things live" gains rows
   for codexbot.py, codex/, cogs/codex/, cogs/codex_helpers.py,
   scripts/import_codex_cards.py and scripts/run_codex_bot.ps1; "Read
   this before touching" gains one row pointing at codex.md; the
   deploying row names run_codex_bot.ps1 and CODEX_DISCORD_TOKEN.
   docs/design/collaboration.md gains the second bot under its deploy
   section: what is shared (the checkout, the venv, data/), what is
   separate (every file it writes, its restart), and that the
   author creates its applications.

Verify by hand and say so in the PR: python3 codexbot.py starts with
the application's token -- the one token there is, so nothing else
runs the Codex bot meanwhile -- and answers /codex card trojan duck and
/codex rules overpower in the server; python3 foolbot.py still starts and
/d12ball still syncs; on the live host deploy.cmd leaves both bots
running (the author does this one; the PR says it is owed).

Done when: the suite is green with the new tests, both bots run from
one checkout, and the design note and the map say so. Under Questions
to the author: question 1 of the worksheet (the bundled texts), and the
channel for the Codex bot's #logs mirror.

Stop: the author asks the test server for a card and reads Sirlin's
ruling under it.
```

### 2. A whole game through the driver, with no frontend

**Landed.** The model is whole and a seeded game plays to a destroyed
base through `driver.apply` with no frontend imported. What it settled
-- the prompt kinds, the standing tech choice, the snapshots and the
journal, the vanilla engine and `UNIMPLEMENTED`, the saved fields, what
the narration may say, the by-slug test helper -- is in
docs/design/codex.md, "The model, before a line of Discord".

The model, whole, before a line of Discord: the state, the record, the
engine's questions, the prompts, the turn's flow and the driver, with
the vanilla engine of decision 7 -- every card for its numbers, every
text in `UNIMPLEMENTED`. The test that plays a game to the end with
nothing from `cogs/` imported is the deliverable; it is what step 3
renders and what every later step keeps green.

```text
Step 2 of docs/codex-bot.md. Step 1 has landed. Also read
d12ball/prompts.py, d12ball/flow/result.py and d12ball/flow/driver.py
(the shapes you copy, read whole), d12ball/components.py
(MATCH_SAVED_FIELDS and validate) and docs/design/gotchas.md (why the
fallbacks stay). Three commits: the state and the record; the engine,
prompts and flow; the tests.

1. codex/components.py. MatchState: two PlayerState in seat order,
   first (who went first), active (whose turn), turn (the number),
   phase (ready, upkeep, main, patrol, draw, tech), the winner, the
   events list, and next_instance_id. PlayerState: base_hp, gold,
   workers, hired_this_turn, hero (HeroState: zone command or play,
   level, damage, summoning_runes, arrived_this_turn, exhausted,
   max_level_since_turn_began), hand (slugs), deck (slugs, top last),
   discard (slugs), codex (a dict slug to count), tech_choice (None, or
   the slugs picked and not yet discarded), tech_owed (bool),
   tech_confirmed (bool, set by TECH_CONFIRM and cleared when the picks
   reach the discard), buildings
   (tech1, tech2, tech3: each hp, under_construction, destroyed), add_on
   (slug, hp, under_construction, or None), play (a list of
   CardInstance), reshuffled_this_phase. CardInstance: id, slug,
   owner, controller, damage, plus_runes, minus_runes, exhausted,
   arrived_this_turn, patrol_slot (None or one of the five), modifiers
   (a list of {kind, amount, until} for this-turn effects, empty until
   step 6), attached (ids, empty until step 6), flipped (False until
   step 6). On the match, for decision 11: turn_snapshots (the last
   three turn-start positions as dicts, oldest first) and journal (the
   actions applied since the turn began, each with the random outcomes
   it consumed). MATCH_SAVED_FIELDS carries every field with a fallback
   from this first commit; to_dict/from_dict round-trip; validate checks the
   position against itself (ids unique, slugs in the catalog, a
   patroller per slot, counts non-negative). The save file is
   data/codex_games.json and the format is the contract from now on.

   codex/game.py: CodexGame -- game_id and game_number; guild_id,
   channel_id, message_id and turn_message_id all optional; player_1_id
   and player_2_id with their names, observer_ids and test_game spelt
   exactly as D12BallGame spells them, so the authorisation predicates
   step 3 shares read either record; player_specs (seat number to
   spec); status (lobby, playing, finished, abandoned); match_state
   (None until Start) -- with the lobby rules as methods that refuse
   with RuleRefusal: take_seat(user, spec), leave(user), may_start(),
   start(engine). RuleRefusal is codex/'s own, with a `cite` field (a
   rulebook page like "UMR p. 6" or a card slug) where d12ball's has
   law.

2. codex/engine.py. RulesEngine(catalog) with rng, the questions, no
   Discord: new_match(seats, first) (shuffle, deal five each, 4 and 5
   workers); legal_actions(match) for the active player, as data: hire
   (bool and why not), hero (summon with cost, or level with the most
   levels affordable), playable (slug, effective cost, and why a card
   in hand is not: tech building missing, gold, no hero for a spell),
   buildings (which of tech1/tech2/tech3/tower/surplus may be built,
   with cost and the worker requirement), attackers (instance ids and
   the hero, ready and not fatigued), end_main; legal_defenders(match,
   attacker) (the three priorities, UMR p. 10, so the squad leader
   alone while there is one, then any patroller, then anything with
   HP, the base included); patrol_candidates(match); draw_count(n)
   (n+2, max 5); tech_bounds(player) (exactly 2, or 0 to 2 at ten
   workers); hero_band(hero) and hero_stats; effective_cost(player,
   slug) (the printed cost until step 6); is_vanilla(slug) reads
   effects.UNIMPLEMENTED.

   codex/prompts.py: PromptKind -- MAIN_ACTION, CHOOSE_DEFENDER,
   PATROL, TECH_CHOICE, TECH_CONFIRM, GAME_OVER (TARGET, UPKEEP_ORDER
   and the combat choices come in steps 5 and 6) -- PendingPrompt,
   Action, OPTIONS with one dataclass per kind built from the engine's
   answers (MainActionOptions, DefenderOptions, PatrolOptions with the
   candidates and the five slots, TechOptions with the codex's slugs,
   their counts, the bounds and the picks made so far, TechConfirmOptions
   with the picks and the two answers confirm and change,
   GameOverOptions), pending(engine, game, match) returning the active
   player's PendingPrompt or the FollowOn owed, and
   standing_prompts(engine, match) returning the TECH_CHOICE the other
   player may still answer -- answerable again and again until their
   turn begins, each answer replacing the picks (decision 8).
   asked_player on a prompt: the active player for every kind but
   TECH_CHOICE, whose asked player is its owner. A turn begins on
   TECH_CONFIRM (or on TECH_CHOICE as the pending prompt, when nothing
   was picked), and begin_turn runs only once the picks are confirmed;
   the confirmed cards go to the discard in the ready phase.

   codex/flow/: result.py (StepResult, FollowOn, FollowOnStep,
   Headline, copied), turn.py (begin_turn: ready -- the tech choice
   into the discard, everything readies, armor and
   max_level_since_turn_began recorded -- then upkeep: gold per worker
   to the cap, a summoning rune off the hero; end_main; draw_phase: the
   hand to the discard face-down, draw_count drawn with the
   once-a-phase reshuffle; begin_tech: tech_owed set, the turn passes),
   actions.py (hire_worker, summon_hero, level_hero(n), play_card for
   a unit or a spell -- a spell in this step is paid, discarded and
   does nothing, since it is in UNIMPLEMENTED -- construct, lock_patrol
   with the slot assignment), combat.py (declare_attack(attacker,
   defender): exhaust, the elite's +1, armor, simultaneous damage,
   deaths -- a unit to the owner's discard with the scavenger's gold or
   the technician's card to its controller, the hero to the command
   zone with two summoning runes and two levels to the opponent's hero
   in play, a building's 2 to the base, the construction rune lost --
   and the base at 0 ending the game), driver.py (MODEL_STEPS covering
   FollowOnStep exactly; advance; answer taking the pending prompt's
   action or a standing prompt's; apply, which also writes the
   journal). codex/history.py, for decision 11: snapshot(match), called
   by begin_turn, which also empties the journal and keeps only the
   last three snapshots; record(match, action, outcomes), called by
   driver.apply with the random outcomes the step consumed, which a
   StepResult carries back in a `drawn` field (a reshuffle's order);
   replay(engine, game, snapshot, actions), rebuilding a position from
   a snapshot and a prefix of the journal; undo_targets(match), and
   undo_to_turn_start(match) and undo_to_previous_turn(match) over
   them. engine.shuffle(cards, recorded=None) draws from rng or takes a
   recorded order back, and it is the only shuffle. Each step changes
   the match
   and returns what happened, in the model's voice with tokens
   ({player:1}, {card:iron_man}, {gold:3}, {hero:troq_bashar}), and
   sends and saves nothing.

   codex/effects.py: UNIMPLEMENTED, a frozenset of every slug in the
   basic set whose text the engine does not honour -- today every card
   with text, the two heroes' bands included -- and nothing else yet.
   codex/keywords.py: the keyword table read off the card texts
   (keyword, X) per slug, present and inert. codex/tokens.py: the six
   builders and render(text, resolve), copied from d12ball/tokens.py
   with Codex's names. codex/wire.py: jsonable and to_dict on the
   result and prompt types, copied.

3. Tests. tests/test_codex_model_purity.py (or the two packages added
   to tests/test_model_purity.py's lists -- whichever keeps that file
   honest; say which): codex/ and gamesaves/codex/ import no discord,
   define no async def, and the game imports without Pillow.
   tests/test_codex_driver_full_game.py: a seeded game of Bashing
   against Finesse through driver.apply alone, under a policy that hires
   when it can, plays the cheapest playable unit, builds the next tech
   building when it can, summons and levels the hero, attacks with
   everything that has a legal defender and patrols everything ready;
   asserts the game ends with a base destroyed within a bounded number
   of turns, that every position round-trips through to_dict/from_dict
   and validate, and that no module from cogs/ or discord is in
   sys.modules at the end. tests/test_codex_rules.py: the draw table
   (0 to 3 discarded against 2 to 5 drawn), the once-a-phase reshuffle,
   the gold cap, hire once a turn and the tucked card gone, hero band
   stats and the heal at a new band, summoning runes and the kill's two
   levels, each tech building's cost and worker requirement and its
   completion at end of turn, the rebuild for 0, the 2 damage of a
   destroyed building, the three attack priorities, each patrol slot's
   bonus, the squad leader's armor refreshing. tests/test_codex_prompts.py:
   a fixture per PromptKind and per owed step, asserting exactly one of
   pending_prompt and owed_step answers, and that standing_prompts
   carries the tech choice across the opponent's turn and that
   begin_turn refuses to run while it is owed.
   tests/test_codex_driver_actions.py: driver.ANSWERS covers PromptKind
   exactly and MODEL_STEPS covers FollowOnStep exactly, as
   tests/test_d12ball_driver_actions.py and the package-shape test keep
   true for D12 Ball. tests/test_codex_history.py: after a seeded turn
   of several actions with a reshuffle inside its draw, replaying the
   journal from the turn-start snapshot reproduces to_dict byte for
   byte; undo to the start of this turn and to the start of the
   previous turn restore the exact earlier dicts and the prompts that
   go with them; the journal is empty after begin_turn and the
   snapshots are bounded to three. tests/test_codex_effects.py:
   UNIMPLEMENTED equals the exact set this step leaves (list it), so a
   card can only leave it with a handler. tests/codex_positions.py: the
   helper that stages a position by slug -- put(match, player, slug,
   patrol=..., damage=...) -- because Codex's cards are fixed data, not
   a roster the author revises, so naming by slug is right here where
   D12 Ball names by role; say so in its docstring.

Nothing in this step imports discord, renders anything, or saves to
disk. Record in docs/design/codex.md: the prompt kinds and what each
asks, the standing prompt (decision 8), the snapshots and the journal
(decision 11), the vanilla engine and UNIMPLEMENTED, the saved-fields
table, and the by-slug test helper.

Done when: the full-game test passes, UNIMPLEMENTED is pinned, and the
purity ratchet covers the new packages.

Stop: a transcript of the seeded game, printed by the test with -v,
read by the author for its wording.
```

### 3. The lobby, the channel and the board

**Landed.** Two seats in a `/codex lobby`, Start, and the opening
position in a channel of its own: the first turn's message pinned with
the board, the turn's lines and **My hand**, **Codex** and **Swap view**,
each hand shown to its owner alone. What it settled -- the service and
its file, the lobby and the channel, the shared authorisation module,
the board's layout and what it shows, the two `BoardRefresher`
parameters and the three beside them, the ephemeral shape as tried --
is in docs/design/codex.md, from "The service and its file" to "Hidden
information on Discord". `cogs/codex_boards.py` was not needed: the
Codex cog builds the shared `BoardRefresher` with its own parameters.

The frontend up to the opening position: the service and its file, the
lobby from `/codex lobby`, the channel, the board image and the table
message with **My hand** -- the first time hidden information is shown
on Discord, so the first time the ephemeral shape is tried.

```text
Step 3 of docs/codex-bot.md. Steps 1 and 2 have landed. Also read
gamesaves/d12ball/service.py and storage.py (copied whole),
cogs/d12ball/core.py (present, render_prompt, view_for_prompt,
DiscordBatching), cogs/d12ball_views/base.py (SafeView),
cogs/d12ball_boards.py (BoardRefresher), docs/design/rate-limits.md,
docs/design/permissions.md, docs/design/hub-and-lobby.md (what a lobby
is) and docs/design/board-image.md (fonts, the to_thread rule). Three
commits: the service and storage; the cog, views and lobby; the board.

1. gamesaves/codex/storage.py: load_games(path=None) and
   save_games(games, path=None) over data/codex_games.json, the
   temp-file write, the two per-file failure flags, never raising, with
   CodexGame as the record and no legacy migration (copied).
   gamesaves/codex/service.py: GameService(engine, games,
   batching=Batching(), save=None) as D12 Ball's is built, with
   create_game, next_game_number, take_seat, leave, start, abandon
   (each a thin door over the record's rule, saving once),
   apply_action, run, resume and persist, each
   load-apply-save-once-return, and listeners for a later web client;
   GameResult (the groups of narration with their snapshots,
   board_changed, the prompt, the standing prompts, the refusal),
   Narration, Batching (copied; the AI carry is left out).
   gamelocks.GameLocks is imported, not copied, and held by the cog as
   D12 Ball's is. tests/save_patches.py's SAVING_SERVICE_MODULES gains
   gamesaves.codex.service and SAVING_COG_MODULES the Codex cog modules
   that bind save_games, so suppressed_cog_saves reaches them and the
   stray-save guard, which walks all of cogs/ and gamesaves/, passes;
   a full run must not create data/.

2. cogs/codex/ grows mixins the way cogs/d12ball/ has them -- core
   (lifecycle, lookups, the service property, DiscordBatching, present,
   render_prompt, view_for_prompt), lobby (the /codex lobby command and
   what Start does), presentation (the board, channels), slash_commands
   (/codex games, /codex board, /codex hand, /codex resume -- resume
   re-posts the table and the board) -- assembled in __init__.py with
   commands.GroupCog last; tests/test_codex_package_shape.py carries
   the four ratchets tests/test_d12ball_package_shape.py carries: no
   method defined by two mixins, the views package a DAG that
   re-exports every name, every command and parameter description
   present and under 100 characters, MODEL_STEPS covering FollowOnStep.
   cogs/game_auth.py is new and shared: game_participant_ids,
   is_game_helper, may_act_for_coach, may_act_in_game,
   HELPER_CONFIRMED_EXTRA, helper_click_confirmed,
   HelperConfirmationRequired and send_new_prompt moved out of
   cogs/d12ball_helpers.py, which re-exports every one so nothing else
   under cogs/d12ball* changes; the D12 Ball tests pass unchanged, and
   the predicates read a CodexGame because step 2 gave it the same
   seat fields. cogs/codex_helpers.py imports them and adds its own:
   channel_name(game) = "codex-<n>-<p1>-vs-<p2>", capped at 100
   characters, with its own CHANNEL_NAME_PATTERN; the categories
   "Codex Games" and "Codex Archive" -- not PBD's, whose names
   /debug's reset and the pin rollover match and whose fifty-channel
   cap is D12 Ball's; BOARD_IMAGE_FILENAME_PREFIX = "codex-" so the pin
   rollover knows its own boards; CodexTokens grows {player:n},
   {card:slug}, {gold:n}, {hero:slug}. cogs/codex_views/base.py: SafeView with
   load_match, require_match, the gates and apply -- the one call a
   click makes, through the service -- and answer; imports no sibling.
   cogs/codex_views/lobby.py: LobbyView with Play Bashing, Play
   Finesse, Leave and Start, persistent (timeout None, fixed custom_ids
   carrying the game id), re-armed on startup by a sweep over open
   lobbies. cogs/codex_views/turn_message.py: TurnMessageView, the
   buttons the current turn's public message carries, persistent and
   re-armed on startup from turn_message_id: My hand (ephemeral to the
   clicker: their hand pictured by render_hand, their discard pile's
   contents as text; a non-seated clicker is told the table is not
   theirs), Codex (ephemeral to the clicker, their own codex pictured
   by render_codex with each card's remaining count, under a select
   that chooses the view -- Everything, Tech I, Tech II, Tech III,
   Spells, and in the standard game one of the player's specs -- the
   picture re-rendered in place on each choice; the author,
   2026-10-08: "a lot of cards", so a menu rather than one picture),
   Swap view (either seated player: flips the game's board between
   stacked and side by side -- board_layout on the record, through
   service.set_board_layout, saved as a record change -- and sends the
   board through the gate; the label names the layout it would switch
   to) and, from step 4, My hand answering the active player with the
   control panel instead, and Tech for the other, and from step 7
   Concede. The turn's last edit drops the
   view, so only the current turn's message has buttons. What a
   codex still holds is the engine's answer (codex_remaining(match,
   player), grouped by the view's filter); the view computes nothing.

   /codex lobby posts the lobby in the channel it is called in; Start
   (either seated player, once both seats are taken) runs
   service.start: the record goes to playing, engine.new_match deals,
   the channel codex-<n> is created under a "Codex" category (created
   if missing) with the permissions D12 Ball's channels get, the first
   turn's message -- the opening board as its picture, "Turn 1 -- <the
   first player>" and the lines begin_turn says for them as its text --
   is posted and pinned with its TurnMessageView, and the lobby
   message edited once to say where the game is. fool-bot's hub message
   (build_hub_message in cogs/d12ball_helpers.py, the author's own
   text) gains one Codex line, worded by the author on this PR,
   carrying the command mention </codex lobby:ID> when
   data/codex_command_ids.json names the id and the command's name in
   plain text otherwise; codexbot.py writes that file after each
   command sync. It is the one file read across the line, and fool-bot
   only reads it. No hub message; the
   /codex lobby row in the worksheet's decision 10 is the reason.

3. codex/render.py and cogs/codex_boards.py. The board is the game's
   own art (decision 5): each side is the Screentop playmat from
   codex/images/board/, the two mats stacked -- seen from the active
   player's side, the other player's mat above theirs and turned to
   face them (the author, 2026-10-08) -- or side by side as the game's
   board_layout says, with the position laid on each where the mat has
   a place for
   it --
   the hero as its card in the first hero slot while it is in the
   command zone, its summoning runes as a chit on it, and on the field
   with the units once summoned (the author, 2026-10-08); the
   patrollers as their cards in the five labelled slots;
   the Base, Tech I, II and III tiles and the add-on card from the
   module's sheet in their places, each with its damage chits and a
   mark while under construction, the unbuilt ones faint; the draw pile
   as the card back with its count, the discard as its count, the
   workers as a count on the workers area; the play zone's cards --
   the hero with its level chit, then the units --
   as their cards across the mat's open middle, each with its damage
   and rune chits, turned sideways when exhausted and marked when it
   arrived this turn; the player's name, gold, hand and codex counts in
   a strip along the mat's top. Roboto Slab from d12ball/fonts/ by
   absolute path for every number and name (the fonts are shared;
   d12ball/fonts/ is not moved). Rendered in asyncio.to_thread. The
   same module renders render_hand(cards, playable, costs): the hand's
   cards as their own pictures in a row, numbered, greyed where not
   playable, each with its cost after reductions -- the picture the
   panel and My hand attach -- and render_codex(cards, counts): a grid
   of the codex's cards as their own pictures, each with a badge of
   how many remain, a card with none left shown faint, sized so that
   Everything -- twelve cards in the basic game, thirty-six in the
   standard one -- stays under Discord's upload limit and readable.
   render_board(match, layout) draws both layouts.
   scripts/render_codex_sample.py renders the opening position in
   both, a hand and a codex view, and --game <id> a saved one; look at
   the images and put them in the PR.
   cogs/d12ball_boards.py's BoardRefresher takes, as parameters, the
   two things it reaches into D12 Ball for today: the view it keeps on
   the board message (HomeAwaySelectionView, once
   home_and_visiting_selected) and the predicate for when the
   full-image link may go up; D12 Ball passes both, its log text names
   the game from the cog, and its tests pass unchanged. The Codex cog
   instantiates the same class with TurnMessageView as the view it
   keeps on the message and a predicate that is always true, and its
   boards come through cog.render_match_png and
   cog.match_file_from_png as D12 Ball's do, since the refresher looks
   those up on the cog at call time; a third parameter, the message's
   text, lets the write set the turn's lines beside the picture (D12
   Ball passes none), and an edit whose picture and text are both
   unchanged is skipped. refresh_match_image is the one forwarder.

Tests: tests/test_codex_game_service_setup.py (every lobby move through
the service, the refusals, one save per call); tests/test_codex_cog_lobby.py
driving the cog with the fakes tests/cog_steps.py uses, from /codex
lobby to the opening board, asserting the sends and that the hand
response is ephemeral and is the clicker's; tests/test_codex_render.py
asserts a picture of the expected size for the opening position (each
WebP: the board since 2026-10-08, the hand and codex since 2026-10-09)
and nothing about its look. On startup the cog re-arms the persistent views the
way CoreMixin.restore_saved_views does -- every open lobby's LobbyView,
every playing game's TableView -- and logs ERROR for a game that owes
a step with nothing to re-arm. Record in docs/design/codex.md: the
ephemeral shape (decision 4) as tried, the board's layout and what it
shows, the channel and the categories, the shared authorisation
module, and the two BoardRefresher parameters.

Done when: two people, each with a test account, reach the opening
position: the channel, the first turn's message pinned with its
buttons, a hand each pictured for its owner and unseen by the other.

Stop: the opening board, in the PR and in the test server, looked at.
```

### 4. The turn on Discord, and the two undos

**Landed** (2026-10-08): docs/design/codex.md, "The turn on Discord",
says what it settled -- the panel, one ephemeral message edited by its
own interactions; the patrol lock as two menus, since five slot menus
and a Lock row are six rows; the tech choice from the Lock's follow-up
and **Tech**; the turn message's rollover through `draw_after`, and the
gate writing only the current one; the requests per click; the two
undos and who may take each; and the resume path.

The whole of a turn, on the vanilla engine, driven from the active
player's ephemeral panel: the turn message that is the turn's running
summary, the actions, the attack with its defender, the patrol lock,
the automatic draw, the tech choice during the opponent's turn, the two
undos, and the resume path. After this step two people can finish a
game.

```text
Step 4 of docs/codex-bot.md. Steps 1 to 3 have landed. Also read
docs/design/maneuver-prompt.md (why a prompt is never edited, and what
this step does differently and why), docs/design/recovery.md and
docs/design/rate-limits.md again. Four commits: the turn message and
the gate; the panel and the actions; patrol, draw and the tech choice;
the undos and resume.

1. The turn message. When a turn begins the cog posts the turn's
   message: its text "Turn <n> -- <player> (<spec>)", a mention of
   whose turn it is, and the lines the owed steps said at the turn's
   start (the gold gained, the hero's rune, the teched cards to the
   discard), the model's lines with their tokens rendered at the door;
   its attachment the board; its buttons TurnMessageView's -- My hand
   for either seated player, answering the active player with the
   control panel and the other with their hand alone (one button,
   different answers by who clicked: the author, 2026-10-08), Tech,
   which only the other player may press, Codex and Swap view for
   either, and Concede from step 7. It is
   pinned and the previous turn's message unpinned, the rollover
   post_new_play_board does for D12 Ball. After every action it is
   edited, through the gate, with the new lines and the re-rendered
   board; when the turn ends it is edited a last time with the patrol
   locked and the draw's count and without its buttons, and it stands. The channel's history is then one picture per turn with the
   actions that led to it. The text stays under Discord's 2000
   characters: past that, the earliest lines fold into "and n more",
   since the board carries the position. A cascade of the bot's own
   steps -- deaths, a building's 2 to the base, the game's end -- is
   one edit. There is no other public message per action, and no embed
   anywhere.

2. cogs/codex_views/turn.py: TurnPanelView, the control panel, built
   from MainActionOptions and nothing else. Its picture is
   render_hand's -- the cards in the hand as their own pictures,
   numbered, greyed where not playable now, each with its cost after
   reductions -- re-rendered with every edit of the panel, so the
   player plays from the cards and not from their names (the author,
   2026-10-08). Its controls: a row of buttons for Hire worker
   (disabled with its reason as the label when the engine says why
   not), Summon hero or Level up (a select of how many levels, from the
   affordable count), Undo (commit 4) and End main phase; a select Play
   a card listing each playable card by its number in the picture, its
   name and its cost, and omitting the rest; a select Build listing
   what may be built with its cost; a select Attack with listing ready
   attackers. Each click
   answers through SafeView.apply; the result's lines go to the turn
   message, the board goes through the gate, and the panel is edited
   in place (interaction.response.edit_message) with the new options.
   A click by anybody but the active player is refused ephemerally.
   CHOOSE_DEFENDER renders as a select of DefenderOptions -- each legal
   defender labelled with why it is legal ("squad leader", "patroller",
   "no patrol") -- in the same panel, with Cancel back to
   the actions. The panel is the view for MAIN_ACTION and
   CHOOSE_DEFENDER in view_for_prompt; render_prompt gives neither a
   picture. My hand on the turn message creates the panel afresh for the
   active player (ephemeral), and so does /codex resume for them; the
   cog never looks for an old panel.

3. cogs/codex_views/patrol.py: PatrolView for PATROL -- five selects,
   one per slot, each listing the candidates not yet placed, a Clear,
   and Lock patrol alone in its row; locking answers with the
   assignment, and the driver runs the owed steps: draw_phase (the
   count is public, the cards are not: the turn message says "draws
   four"), begin_tech (the tech choice is now owed), and the opponent's
   turn opening on TECH_CONFIRM -- or on TECH_CHOICE, if they never
   picked -- so the chain stops there, the new turn message says the
   turn waits on them to confirm their tech, and begin_turn runs when
   they have. cogs/codex_views/tech.py: TechChoiceView for TECH_CHOICE
   -- its picture render_codex's with the picks marked, under an
   ephemeral multi-select of the codex's cards with their remaining
   counts and the picks so far, min and max from TechOptions, Save
   tech alone in its row -- sent as an ephemeral follow-up to the
   Lock click, and reachable all through the opponent's turn from Tech
   on the turn message, by its owner only, to tech or to change their
   mind, each save replacing the last; and TechConfirmView for
   TECH_CONFIRM -- the picks pictured by render_hand, Confirm and
   Change, Change reopening the picker -- shown to the player when
   their turn would begin, from My hand or as the follow-up to the
   opponent's Lock when they are present, and the ready phase runs on
   Confirm (the author, 2026-10-08). The choice is never shown or
   counted publicly beyond "has teched".

4. The undos and resume. Undo on the panel opens two choices. To the
   start of my turn is the active player's alone:
   service.undo_to_turn_start restores the turn's snapshot through
   codex/history.py, the turn message is edited back to its first
   lines plus "undone to the start of the turn", the board goes through
   the gate, and the panel re-renders from the new prompt. To the start
   of the previous turn unwinds the opponent's turn too, so it posts a
   public confirmation the opponent answers with a button of their own
   (a manage_channels helper may confirm instead, through
   HelperConfirmationRequired); on confirmation
   service.undo_to_previous_turn restores the older snapshot, the
   previous turn's message is edited back to its first lines plus
   "undone to the start of the turn" with the restored board and
   pinned again, the current turn's message is deleted (the one
   deletion in the flow), and that turn's player gets a fresh panel. The cog decides nothing about what a snapshot holds or
   which undos exist: history.undo_targets(match) says, and the Undo
   choices are built from it. GAME_OVER renders as a public line naming
   the winner and the final board, with a Rematch button for step 7
   left out for now. tests/test_codex_cog_turn.py drives a whole turn
   through the cog with the fakes: each panel edit is an edit of the
   ephemeral message, not a channel send; the public requests per
   action are one edit of the turn message and at most one of the board
   through the gate; the hand never appears in a public send or edit;
   the tech choice is answerable while the other player's panel is
   open; a stale panel's click is refused with the driver's words; an
   undo to the start of the turn leaves the turn message, the board and
   the panel showing the restored position; the previous-turn undo
   waits for the opponent's button. tests/test_codex_resume.py: a match
   saved mid-turn resumes to the same prompt from My hand and from /codex
   resume.

Record in docs/design/codex.md: the panel (one ephemeral message edited
by its own interactions, and why that is not a channel edit), the turn
message and the two-message gate, the request count per click and its
bucket, the two undos and who may take each, and the resume path.
Measure the requests per click with the fakes and write the number in
the PR.

Done when: two people finish a game on the vanilla engine; a bot
restart mid-turn resumes from My hand; both undos work; the tests
above pass.

Stop: a whole game played by the author and the other developer on the
test server, with the request counts in the PR and one undo taken.
```

### 5. The keywords

**Landed.** The keyword table is what the engine reads, the three
choices an attack asks are prompts of their own, and every `General`
ruling on the set's keywords is a test -- 53 of them in
`tests/test_codex_keywords.py`, each named for its ruling with the
ruling as its docstring. What it settled is in
[design/codex.md](design/codex.md), "The keywords" and "Which choices an
attack asks, and which it does not".

The combat keywords the set uses, as the closed table of decision 7,
each with Sirlin's rulings as tests. After this step every unit whose
text is only a keyword leaves `UNIMPLEMENTED`, and the tower is
buildable.

```text
Step 5 of docs/codex-bot.md. Steps 1 to 4 have landed. The rules are
the worksheet's "Combat" paragraph and the keyword table; the rulings
are codex/data/rulings.json's General group for these keywords (read
them all before writing any). Two commits: the engine; the prompts and
views the choices need.

1. codex/keywords.py becomes the table the engine reads:
   has_keyword(instance_or_hero, keyword, match) answering from the
   card's printed keywords, the patrol slot's grants (the lookout's
   resist 1) and, from step 6, granted abilities. codex/flow/combat.py
   grows: flying and anti-air (legal_defenders: a ground attacker
   cannot take a flying card and must ignore flying patrollers; a flyer
   may ignore ground patrollers but not flying ones; a flyer attacking
   past anti-air patrollers takes each one's ATK as combat damage; a
   ground card without anti-air deals no damage to a flyer); stealth,
   invisible and unstoppable (the attacker may ignore patrollers;
   invisible is also unattackable and untargetable to an opponent
   without a detector, except while patrolling); the tower (on the
   opponent's turn it detects the first stealth or invisible attacker
   of the turn, which then may not sneak; on its owner's turn a DETECT
   action in MainActionOptions names one card to detect for the turn;
   it deals 1 combat damage to every attacker it can see, simultaneous
   with combat, swift strike included); swift strike (its damage first;
   a card destroyed by it deals none; two swift strikers simultaneous);
   sparkshot (1 damage to a patroller in an adjacent slot, a choice
   when both neighbours are filled, across no empty slot, flyers
   included); overpower (the excess over the defender's remaining HP to
   one other defender the attacker could have attacked, patrollers
   first, a choice when more than one); obliterate 2 (the defending
   player's two lowest-tech units destroyed before combat, the
   attacker's choice on ties, and a new defender if the first is gone);
   readiness (no exhaust on attack, one attack a turn); armor (the
   squad leader's 1, refreshed at the start of each turn, damage
   prevented still dealt); frenzy (+X ATK on its controller's turn);
   healing X (at upkeep, each friendly unit and hero); resist X (an
   opponent pays X gold to target it -- the engine's part now, the
   targeting in step 6); haste (no arrival fatigue). Timely Messenger,
   Helpful Turtle, Fruit Ninja, Revolver Ocelot, Eggship, Harvest
   Reaper, Backstabber, Cloud Sprite, Leaping Lizard and the tower
   leave UNIMPLEMENTED; Sneaky Pig, Blademaster, Nimble Fencer,
   Granfalloon Flagbearer and the heroes' bands stay until step 6.

2. codex/prompts.py gains the combat choices as kinds -- SPARKSHOT_TARGET,
   OVERPOWER_TARGET, OBLITERATE_CHOICE -- each with options listing
   what may be chosen and why, asked only when there is a choice (one
   adjacent patroller is no question), and DETECT inside
   MainActionOptions. cogs/codex_views/turn.py renders each as a select
   in the panel. The engine's attack preview -- what will happen if this
   attacker takes this defender, as lines -- is not built; the player
   reads the board.

Tests: tests/test_codex_keywords.py, one test per General ruling for
these keywords, named test_<keyword>_<n> with the ruling as the
docstring, staged with tests/codex_positions.py; the worksheet's stop
scenario (Eggship attacks past a patrolling Leaping Lizard, takes 3,
deals its 4 to the base) explicitly; a flyer attacking a flying squad
leader; the tower detecting the first stealth attacker and not the
second; overpower's excess forced onto another patroller before a
building; obliterate taking the squad leader and the attacker choosing
again. tests/test_codex_effects.py's pinned set shrinks to the names
above.

Record in docs/design/codex.md: the keyword table, what stacks and what
does not (UMR p. 16), and which choices are asked and which are not.

Done when: the tests pass and the full-game test still ends a game.

Stop: the Eggship over the Leaping Lizard, on the test server, with the
tower's damage line in the channel.
```

### 6. Triggers, spells and the ongoing spells

**Landed.** Every card of the basic set plays its text and
`UNIMPLEMENTED` is empty; docs/design/codex.md, "Targeting and the
effects", says how -- the effect stack and the one reading of what a part
may target, resist and the flagbearer, the abilities, the attacks
triggers inside an attack, `settle`, the grants and costs, the tokens,
channeling and Two Step, and the upkeep's order -- and "The saved fields"
what it added to the save.

Everything with text that is not a keyword: the thirteen spells, the
arrives and attacks triggers, the heroes' bands, the granted abilities,
the ongoing spells with their tokens and partners, the upkeep effects
and their order. After this step the basic game is the basic game.

```text
Step 6 of docs/codex-bot.md. Steps 1 to 5 have landed. The rules are
the worksheet's card table and the card rulings in
codex/data/rulings.json for the 36 cards (read every one before
writing any). Four commits: targeting and the simple spells; triggers
and the heroes; the static grants and costs; the ongoing spells, the
tokens and the upkeep.

1. Targeting. codex/prompts.py gains TARGET with TargetOptions: the
   legal targets for the effect being resolved, each with the resist
   cost it would charge and whether the flagbearer rule forces it, and
   the effect's name; a multi-part effect (Final Smash) asks TARGET
   once per part in order, choosing as it resolves, with the
   flagbearer checked per part against what this cast has already
   taken. The resist cost is paid when the target is chosen; a player
   who cannot pay it cannot choose it, and is then not forced to a
   flagbearer with resist. "Do as much as you can": a part with no
   legal target is skipped and the spell still plays if any part can
   resolve. Your own invisible cards are targetable. codex/effects.py
   gains the handlers: Spark, Bloom (only a friendly unit or hero
   without a +1/+1 rune), Wither (the runes cancel; 0 HP kills through
   armor), Wrecking Ball, The Boot (a tech 0 or I unit; dies, so the
   patrol slot pays), Intimidate (-4 ATK this turn, floor 0), Discord
   (every opposing tech 0 and I unit, -2/-1 until end of turn, 0 HP
   kills), Final Smash (the three parts: destroy, return to its owner's
   hand, gain control -- the controller changes, the owner does not).
   A spell needs a hero in play, a spec spell its spec's hero, an
   ultimate the hero at max level since the turn began; the engine's
   playable list says which is missing. End-of-turn cleanup removes
   every this-turn modifier.

2. Triggers and the heroes. Arrives and attacks: Brick Thief (1 to a
   building, repair 1 on another, an undamaged own building a legal
   choice that does nothing), Hired Stomper (3 to a unit, mandatory,
   itself a legal target), Trojan Duck (4 to a building, arrives or
   attacks, after obliterate and before combat), Sneaky Pig (stealth
   until end of turn on arrival). An attacks trigger resolves after the
   defender is chosen and before damage; if it destroys the defender,
   the attacker chooses again (CHOOSE_DEFENDER again). Troq at 5:
   attacks deal 1 to the base of the defender's controller, the base
   itself included; Troq at 8: readiness. River at 3: an ability action
   "exhaust: sideline a tech 0 or I patroller" in MainActionOptions'
   abilities, refused while she is fatigued; River at 5: tech 0 units
   cost 1 less, floor 0. A hero's band abilities are read off the
   bands' texts through the same table as a card's.

3. Grants and costs. Static abilities granted by a card in play, in
   effect exactly while that card is in play under its controller:
   Nimble Fencer (your Virtuosos have haste, itself included),
   Blademaster (your units and heroes have swift strike), Grounded
   Guide (your other units +1 ATK; your Virtuosos +2/+1 instead;
   stacking per Guide), Maestro (your Virtuosos cost 0; each gains
   "exhaust: 2 damage to a building (target)", usable only by a
   Virtuoso held since the turn began or with haste). effective_cost
   applies River's and Maestro's reductions with a floor of 0.
   Granfalloon Flagbearer joins the targeting rule of commit 1.

4. The ongoing spells, the tokens and the upkeep. Harmony: in play,
   channeling (sacrificed the moment its owner controls no Finesse
   hero, without the flip); whenever its owner plays a spell -- not
   Harmony itself -- a 0/1 Dancer token, limit 3 across all Dancers;
   "Sacrifice Harmony: stop the music" as an ability action flipping
   every Dancer into a 2/1 unstoppable Angry Dancer, runes and damage
   kept. Two Step: two of the owner's units as partners, chosen as two
   TARGET parts, +2/+2 each while both are held, sacrificed when either
   leaves play or changes controller; a unit already partnered is not a
   legal target. Appel Stomp: sideline a patroller, draw a card, then a
   yes/no prompt (APPEL_STOMP_TOP) to put it on top of the deck instead
   of the discard. Tokens are trashed when they leave play and never
   enter a hand, deck or discard. Star-Crossed Starlet: 1 damage to
   herself at upkeep, +1 ATK per damage. Helpful Turtle's healing and
   the surplus's draw at upkeep; UPKEEP_ORDER asked only when the order
   matters -- Turtle and Starlet both in play -- with the active player
   choosing. Surplus leaves UNIMPLEMENTED with the rest; the set is now
   empty and tests/test_codex_effects.py asserts it is.

Tests: tests/test_codex_card_rulings.py, one test per card ruling in
rulings.json for the 36 cards, named test_<slug>_<n> with the ruling
as the docstring (26 today; the test file says how many it found so a
re-import that adds one fails loudly); tests/test_codex_spells.py for
each spell's happy path and its refusals (no hero, wrong spec, the
ultimate too soon); the Maestro-and-Nimble-Fencer turn (a Virtuoso
arrives free and exhausts for 2 at once); Harmony across a turn (three
spells, three Dancers, a fourth spell no Dancer; stop the music; the
hero dies and Harmony goes without a flip); Two Step's sacrifice when a
partner is Booted; Final Smash with a flagbearer on the other side.
cogs/codex_views/turn.py renders TARGET, APPEL_STOMP_TOP and
UPKEEP_ORDER as selects and a yes/no in the panel.

Record in docs/design/codex.md: targeting and the flagbearer, grants
and when they end, tokens, channeling, the upkeep order, and that
UNIMPLEMENTED is empty from this step so the table's job is done until
the next spec.

Done when: every card of the set has a handler or a keyword, every
ruling is a test, and the full-game test's policy plays spells too.

Stop: a whole Bashing-against-Finesse game on the test server with the
author on one side, and nothing refused that the rulebook allows.
```

### 7. The board drawn element by element

**Landed.** `codex/render.py` draws each player as a panel from the
module's pieces and the cards' art, and `render_board` composes two,
stacked or side by side; the five patrol slots are cut from the
playmat. What it settled -- the sizes, every state, why the mat went --
is in docs/design/codex.md, "The board on Discord", and the cuts in
"The cards are data".

Decision 5 as the author's review of the design canvas left it on
2026-10-08: the playmat step 3 laid the position on goes, and each side
becomes a panel built from the module's pieces and the cards' own art,
so that less of the picture is anything but cards and nothing is drawn
for a place the position does not use. Step 6 landed before this was
decided, which is why it is step 7 and not part of step 3: everything
step 3 built around the picture -- the turn message, the gate, the
WebP, the scale, the two layouts and the swap, `stacked_seats` -- stays;
what changes is the drawing. The canvas,
https://claude.ai/artifact/2gJhY3oDWjVNvweAW1XY7f, is the sketch this
step draws from: its plan board carries every number below, its states
board every state, its "Stacked, facing" board what the bot posts.

```text
Step 7 of docs/codex-bot.md. Steps 1 to 6 have landed. Also read
docs/design/codex.md, "The board on Discord" and "The cards are data" (the art), and
docs/design/board-image.md. Decision 5 says what the board is; this
step draws it, from the author's design canvas
(https://claude.ai/artifact/2gJhY3oDWjVNvweAW1XY7f -- the plan board
has the sizes, the states board every state). Three commits: the
pieces; the panel; the layouts and the sample.

1. The pieces. scripts/import_codex_cards.py cuts five more pieces,
   from the playmat itself rather than a sheet: the patrol slots as
   the mat prints them, each 200 by 273 at y 38 and x 688, 917, 1143,
   1371 and 1597 (squad_leader, elite, scavenger, technician, lookout),
   and under each its bonus strip, 200 by 41 at y 311, into
   codex/images/board/patrol_slots/<slot>.png and <slot>_bonus.png,
   with the boxes pinned beside BOARD_SHEETS and --cut-only re-cutting
   them. The white-on-blue icons under patrol/ stay. The house chit
   (chits/house.png) is the construction mark (UMR p. 8), and the mark
   on a destroyed building.
2. The panel. codex/render.py draws one player as render_panel(...) at
   the pixels the canvas was drawn at, Roboto Slab for every word and
   number:
   - cards 200 by 273 (the art at 61%) in square cells of 273, a card
     standing centred in its cell and an exhausted one lying in it at
     full size (the author, 2026-10-08: A of the canvas's three ways);
     columns of 273 with 16 between and 20 of padding, so the basic
     panel is 1649 wide and the standard one 2227; five columns in the
     basic game, seven in the standard one (three plates and four cards
     in the first row) -- the count is the game's, fixed when it
     starts, so the picture's width holds from turn to turn (the
     author, 2026-10-08); chits 50 to 62 wide (damage/, levels/,
     time_runes/, chits/plus_rune.png, chits/house.png);
   - a column of buildings on the left, 160 wide, the mat's left edge
     kept, top to bottom: the add-on slot (a dashed outline, or the
     add-on's card at 82 by 114), Tech III, II and I as the module's
     tiles at 160 by 114 -- greyed (grayscale, half opacity) until
     built, in colour once built, the house chit on a top corner while
     under construction, dark with the house chit when destroyed, a
     damage chit on a damaged one -- and the base tile with a heart
     drawn over its printed one carrying the HP it has now (the tile
     prints 20; the heart is drawn because the number changes);
   - the patrol zone across the top of the grid on the mat's blue
     (#244990): the five slot cuts in order, each centred in its
     column, each bonus strip under its slot; a patroller's card covers
     its slot, chits and all, the bonus still under it;
   - the command zone as a rounded plate per hero (one, or three),
     filling its cell: a dark plate (#3a2a1c, a 2-pixel #8a6a3a edge)
     labelled COMMAND ZONE, the hero's card lying on it in full at 184
     by 251 with its time-rune chit while off the field, the plate
     empty while the hero is on the field;
   - the field after the plates in the same rows: the heroes first,
     then the units, each its card -- a level chit top left (a hero), a
     damage chit over the stats, a rune chit top right, an ARRIVED tag
     the turn it came -- and, exhausted, turned on its side at full
     size, lying across its square cell, with the exhaust glyph on the
     cell's top corner; rows of the column count, added as the
     position needs, so the panel's height follows it;
   - a nameplate along the panel's outer edge, 56 tall: the player, the
     spec and hero, then GOLD (the gold emoji's picture), WORKERS, HAND,
     DECK, DISCARD and CODEX as a word and a count each; the active
     player's nameplate carries a gold rule and "<Hero>'s turn <n>" in
     a gold pill.
   Nothing of the playmat is drawn beyond the five cuts; playmat.png
   stays as the reference the layout was taken from. The ground is flat
   (#231a14 on #15100c) unless the author answers the canvas's question
   with the mat's leather, tiled from a plain patch of it.
3. The layouts and the sample. render_board(match, layout) composes
   two panels: stacked, the default -- the active player's below, the
   other player's above it turned round whole so the two patrol zones
   face each other, its nameplate alone kept the right way up
   (stacked_seats as it is), a 36-pixel divider between them reading
   "<Hero>'s turn <n>" -- or side by side, the first player's on the
   left, a vertical divider between, neither turned. The interface,
   BOARD_SCALE, the WebP, the gate and Swap view are untouched; the
   picture's size changes with the position, which the gate already
   allows for. scripts/render_codex_sample.py renders the opening
   position, a mid-game position and every state on the canvas's states
   board, in both layouts; put the pictures in the PR beside the
   canvas's boards they should match.

Record in docs/design/codex.md: rewrite "The board on Discord" to what
is drawn and why the mat went, keeping what stays (the message, the
gate, the WebP, the layouts, the turn's view), and add the five cuts
to "The cards are data" beside the other cuts. No save field changes; a test of how the board looks is
not added (the author's rule for everything printed).

Done when: the board is two panels in either layout at the sizes
above; the suite is green; the sample pictures match the canvas.

Stop: a mid-game board on the test server, stacked, looked at beside
the canvas's "Stacked, facing" board.
```

### 8. Finishing a game: concede, abandon, rematch, the golden

**Landed** (step 8): what it settled -- the concession as the model's
and the service's own door, the finished record, Concede behind a second
click, the helper's abandon, the rematch with Keep heroes, the channel
moved to Codex Archive with nothing exported, the test server's reset,
the startup sweep, the logging audit -- is in docs/design/codex.md,
"The end of a game"; the golden's seed and what it does not cover are
in "The golden".

What a game needs after its last turn, and the safety net under
everything before it. No statistics and no archive export for this bot
(the author, 2026-10-07): a finished game's channel is moved out of the
way and nothing is written from it.

```text
Step 8 of docs/codex-bot.md. Steps 1 to 7 have landed. Also read
docs/design/recovery.md and tests/test_golden_service.py (the golden
you copy). Two commits: the ending; the golden.

1. Concede on the turn message and /codex concede, the clicker's own
   side only, confirmed by a second click; the admin /codex abandon
   (manage_channels) through the service; GAME_OVER's Rematch -- a new
   lobby posted in the finished game's channel with the same two seats,
   the heroes swapped unless both players press Keep heroes, the first
   player drawn again at random. A finished or abandoned game's channel
   is moved to the "Codex Archive" category and left as it is: no
   export is written from it and no statistics are read from it; the
   event log stays in the save. /codex admin reset_channels, for the
   test server, under the gate cogs/debug.py's group has (guild only,
   manage_channels by default): every non-archived Codex channel
   deleted and its game dropped, after a confirmation word. The startup
   sweep re-arms the current turn message's buttons for games still
   playing and nothing else. Nothing hidden is in a message about a game still being
   played: audit every logging call under cogs/codex* and
   gamesaves/codex/ for a hand, a deck, a discard pile or a tech
   choice, and write the finding in the PR.

2. tests/test_codex_golden.py: a seeded whole game through GameService
   with its tokens intact, pinned byte for byte in tests/golden/,
   re-recorded with FOOLBOT_UPDATE_GOLDEN=1 as the D12 Ball goldens
   are, with the rule written in the file that a faithful change to
   rendering leaves it alone while a change to the model's wording
   re-records it and says so in the PR.

Record in docs/design/codex.md: the ending, the rematch, what happens
to a finished channel and why nothing is exported, and the golden's
seed and what it does not cover. CLAUDE.md names the golden in its
tests paragraph.

Done when: a finished game ends cleanly, offers a rematch and is moved
aside; the golden pins a game; the suite is green.

Stop: a game finished on the test server, its rematch opened.
```

### 9. The look back: what turned out identical moves to one home

**Landed.** What was identical moved to `gamekit/` (the model's side:
`jsonable`, the drivers' two shared refusals, the token `Resolver`,
`StopHandling`, `SavedField`, the games file's guarded read and write)
and `botkit/` (Discord's: the channel helpers and the per-game click
lock), both games importing it and re-exporting the old names; every
pair that differs in substance, and why, is in docs/design/codex.md,
"What the two games share". Step 8 was already struck when this step
ran.

Decision 2's second half. With two games running, the generic and the
particular can finally be told apart by diffing them.

```text
Step 9 of docs/codex-bot.md. Steps 1 to 8 have landed. Also read
docs/design/cog-structure.md and docs/design/game-service.md.

Diff, pair by pair, what steps 1 to 8 copied: codex/flow/result.py
against d12ball/flow/result.py, codex/flow/driver.py against
d12ball/flow/driver.py, codex/tokens.py against d12ball/tokens.py,
codex/wire.py against d12ball/wire.py, gamesaves/codex/storage.py and
service.py against gamesaves/d12ball/, cogs/codex_views/base.py against
cogs/d12ball_views/base.py, the channel and category helpers in
cogs/codex_helpers.py against cogs/d12ball_helpers.py
(slugify_channel_part, get_or_create_category, pin_board_message,
add_full_image_button), the two runner scripts, and the test ratchets
(the purity probe, the package-shape checks, the driver-coverage
checks) against their d12ball twins. The leaves steps 1 and 3 already
moved -- gamebot.py, botlog's parameters, cogs/game_auth.py, the
BoardRefresher's two parameters -- are the pattern to follow. Whatever is byte-identical, or differs only by the
game's name, moves to one home -- gamekit/ for what the model side
shares, botkit/ for what the Discord side shares -- with both games
importing it, each move its own commit, the goldens of both games
untouched, and nothing else about either game changed. What differs in
substance stays where it is, and the PR lists each pair with one line
on why it is not shared. Say in the PR how many lines moved.

CLAUDE.md gains a row per new package and loses nothing;
docs/design/codex.md and docs/design/model-discord-split.md say what is
shared and why the rest is not. Strike step 8.

Done when: nothing copied remains byte-identical in two places, both
suites are green, and both bots run.

Stop: the PR's list of pairs, read by the author.
```

### 10 to 13. After the basic game

The author's order, given on 2026-10-08: all six colours, two at a
time -- red and green first, then purple and black, then white and
blue. The standard game's rules come first because a colour is three
heroes, and three heroes a side is the standard game: the hero limit
and the heroes' hall, the spec chosen at Tech II and the tech lab, the
starting deck's colour, the multicolour penalties (UMR p. 4, 6, 8, 9)
-- and the Codex button's menu gains a view per spec of the player's
three, since a seventy-two card codex is three binders (the author,
2026-10-08). **The panel's main phase is rows of buttons, not menus**
(the author, 2026-10-09; docs/design/codex.md, "The panel"), and three
heroes a side do not fit its actions row, which holds one hero's
**Summon** or **Level up** beside Hire, Attack, Undo and End main
phase: step 10 gives the heroes a row of their own -- one button per
hero, Summon or Level up by one level a click -- under the actions
row, so the hand keeps two rows at most (`HAND_ROWS`) and the board's
row stays the last. A choice the standard game adds -- the spec chosen
at Tech II, which hero to summon -- is buttons where it fits a row or
two, a menu only where it cannot.

The four prompts were written on 2026-10-09, once steps 8 and 9 had
landed, from the design note as it stood then and in the shape of
steps 5 and 6. Step 10 builds the standard game's rules over the red
and green data with every card still played for its numbers, so the
standard game is playable before a single red or green effect exists;
step 11 gives red and green their effects and rulings, the way steps 5
and 6 did for the neutral set, and lands on Calamandra against Jaina,
the Core Set's own first game (UMR p. 3) -- a basic game, one hero a
side, on the green and red starting decks, which is why step 10 lets
a basic game seat any landed hero and not only the neutral two; steps
12 and 13 repeat step 11 for the other two pairs, each landing its
colours first and then playing their text. Where a comment in the code
names "step 9" for the standard game, it was written before the board
redraw became step 7 (2026-10-08) and means step 10.

**What the four hold in common.** A colour lands as the basic set did:
its heroes offered in the lobby (`LANDED_COLORS`, which step 10 adds
and each pair's step extends), its cards read by the keyword table and
played for their numbers with every text the engine does not honour in
`UNIMPLEMENTED`, written out and pinned; then the keywords the pair
adds, then the effects, every ruling a test with the ruling as its
docstring, and the set empty at the end of the step. Nothing is ever
ignored silently. The cards, the rulings and the art have been in the
tree since step 1; what each step adds is code. The prompts name the
cards by mechanic rather than one by one where a mechanic is a dozen
cards, and each colour's card table -- `codex/data/cards.json` read by
colour, with the Card FAQ (UMR pp. 19-22) and the glossary (pp. 16-18)
-- is the scope, as the worksheet's table was for the basic set. The
design note's sections are the record of what each step settled; a
step that finds a question the rulings and the FAQ do not answer takes
it to the author on the PR, as the preamble says, and builds the
rulebook's reading until it has an answer.

### 10. The standard game's rules, over the red and green data

**Landed** (2026-10-09, by the cloud routine): the record and the lobby,
the match with three heroes, the buildings and the costs, the board and
the codex, and red and green played for their numbers --
[design/codex.md](design/codex.md), "The standard game", with
`LANDED_COLORS` and the landed set in "The vanilla engine and
`UNIMPLEMENTED`", which is no longer empty and says so.

The standard game is what the rulebook calls the game: three heroes a
side, a codex of seventy-two, all four add-ons (UMR p. 3). Everything
in steps 1 to 9 was written so that it fits -- the seats by spec, the
add-on as data, the hero as a list later, every colour's data and art
imported at step 1, the panel's columns and the codex's views already
reading how many heroes a player has -- and this step is where the
hero becomes a list. It lands red and green as data the vanilla engine
plays for its numbers, so that a standard game can be played at all
(three neutral heroes do not exist), and so that step 11 starts from a
game that runs. A basic game may seat any landed hero from this step
on, because the Core Set's first game is a basic game of Calamandra
against Jaina (p. 3), and because a seat picked from a menu of heroes
makes no distinction the rules do not.

```text
Step 10 of docs/codex-bot.md. Steps 1 to 9 have landed. Also read
docs/design/codex.md whole -- "The lobby and the channel", "The
panel", "The board on Discord", "The saved fields", "The end of a
game" (the rematch's swap) and "What the two games share" are what
this step changes -- and UMR pp. 3-4 and 6-10: three heroes, the
starting deck's colour, the hero limit, the spec chosen at Tech II,
the heroes' hall and the tech lab, the multicolour penalties, which
hero gains a kill's levels; with the General rulings heroes_hall and
tech_lab, which are the rules. Where a comment in the code names
"step 9" for the standard game, it means this step. Five commits: the
record and the lobby; the match with three heroes; the buildings and
the costs; the board and the codex; red and green under the vanilla
engine.

1. The record and the lobby. CodexGame gains mode -- "basic" or
   "standard", saved, "basic" where an older record has none -- and a
   seat holds its heroes rather than one spec: player_specs stays the
   saved key and becomes a list per seat, one spec in a basic game and
   three in a standard one (a hero is its spec's one hero, hero_for,
   so a spec names a hero and nothing is saved twice), and player_decks
   the starting deck's colour per seat, "neutral" where absent. The
   rules, on the record with RuleRefusal (UMR pp. 3-4): a seat's heroes
   are distinct and of colours the bot has landed (cards.LANDED_COLORS
   -- neutral, red and green from this step; a hero of another colour
   is refused as not in this bot yet, with no page to cite); a basic
   game's deck is its hero's colour; a standard game's is one of its
   three heroes' colours, asked where they differ and settled by the
   rule where they do not, the neutral heroes' colour a deck the three
   may take; Start is refused until every seat is complete; a rematch
   swaps the two teams whole (rematch_specs as lists; Keep heroes as it
   is); a test game seats one person on both sides as before. The
   lobby (cogs/codex_views/lobby.py) is rebuilt from the record: its
   first row Basic game / Standard game -- either seated player's, or
   anyone's while nobody sits, the lobby's until Start -- Leave and
   Start; its second a menu of the landed heroes, one pick in a basic
   game and three in a standard one, which seats the clicker with those
   heroes (Play Bashing and Play Finesse go, and with them the cog's
   SPEC_HEROES and its "Bashing against Finesse" line: the catalog
   names the heroes); its third, shown only to a seat whose heroes span
   more than one colour, a button per colour for the deck. A menu
   because twenty heroes do not fit two rows of buttons; the lobby's
   line per seat names its heroes and its deck. Everywhere the cog
   names a side by spec.title() (cogs/codex/ending.py, turns.py,
   cogs/codex_views/turn_message.py) it names it by
   formatting.deck_name(player.specs) instead, and turn_heading is
   unchanged.

2. The match with three heroes. PlayerState.hero becomes heroes, a
   list of HeroState saved under "heroes", an older save's "hero" read
   as a list of one; spec becomes specs, a tuple saved under "specs"
   with "spec" its fallback (the specs property goes); deck_color is
   new, "neutral" in an older save. new_match deals each seat its
   deck's starters (catalog.starting_deck) and a codex of every spec's
   twenty-four (codex_for over specs); the first player's 4 and the
   second's 5 workers, the hand of five and the random first player
   are unchanged. Every hero ref becomes hero:<slug> -- Action's
   arguments gain hero, and summon, level and attack name one -- and
   the golden re-records for it, which the PR says and shows.
   Everything that touched player.hero loops over heroes: the ready
   phase and the armor, one summoning rune off each hero at upkeep
   (UMR p. 5), max_level_since_turn_began per hero, validate,
   patroller, patrol_candidates, attackers, legal_defenders,
   hero_keywords and TEXT's band rows per hero, the snapshots, the
   render. The hero limit (engine.hero_limit, UMR p. 6 and the
   heroes_hall ruling, which is the one reading): one; two with an
   active tech II or an active heroes' hall; three with an active tech
   III, or an active tech II and an active heroes' hall -- active being
   built, finished and not destroyed (tech_building_active) -- and a
   summon past it is refused citing p. 6; a dead hero in the command
   zone does not count against it, so it may be replaced at once, and
   losing a building removes nobody. Spells (UMR p. 7): a spec spell
   needs its spec's hero in play, an ultimate that hero at max level
   since the turn began, as now but per hero; a starting spell any hero
   -- effective_cost adds 1 where the spell's colour is not neutral and
   no hero of its colour is in play ("a hero of the wrong colour"),
   never for a neutral spell -- and the caster is the engine's, a hero
   of the spell's colour where there is one, with nobody asked, since
   nothing in these sets turns on which hero cast a starting spell.
   Channeling stays by spec (settle, unchanged). The kill's two levels
   (UMR p. 10): with one hero in play it gains them, with none nobody
   does, and with more than one the active player is asked --
   LEVEL_GAIN, a new kind, a button per hero in play, asked where the
   kill happened as obliterate's choice is, on MatchState.combat or
   the effect's frame, so the levels are gained before anything after
   the kill resolves. The panel's hero row (TurnPanelView, the
   author's decision above): one button per hero under the actions
   row, "Summon Jaina (2 gold)" or "Level up Jaina (1 gold)", a level
   a click, disabled with its reason (the limit, the runes, the gold,
   the maximum); the actions row keeps Hire worker, Attack..., Undo...
   and End main phase; HAND_ROWS becomes two so the board's row stays
   the last; MainActionOptions.hero becomes heroes, one HeroOption
   each.

3. The buildings and the costs. The add-ons are the data's four
   (engine.ADD_ONS, effects.ADD_ONS, and render's default HP read from
   the catalog): the heroes' hall (UMR p. 9) and the tech lab, which
   carries a spec (AddOnState.spec, None in an older save). In a
   standard game, constructing tech II chooses a spec among the
   player's heroes' (UMR p. 8): the build action carries spec, the
   BuildOption lists the choices, the driver refuses a missing or a
   foreign one citing p. 8, and PlayerState.tech2_spec keeps it,
   unchanged by the building's destruction and its rebuild. A tech II
   or III card is playable only with its spec the tech II's or the
   lab's (why_not_playable says which is missing); a basic game's one
   spec is chosen by the rule and never asked. The tech lab's spec is
   chosen as it is built, from the heroes' specs, where a tech II
   stands; where none does it is built without one and chosen together
   with the tech II's when that is built (the tech_lab ruling); a
   destroyed lab loses its spec, and a rebuilt one may choose another
   (p. 9). The multicolour penalties (UMR pp. 4, 8, 9):
   engine.team_colors(player) is the heroes' colours less neutral, and
   where there are two or more, the first tech building or add-on the
   player constructs costs 1 more -- PlayerState.constructed_once,
   false in an older save, set by any construction, a rebuild for 0
   included -- and the build option shows the cost it will charge. On
   the panel, Build Tech II in a standard game turns the panel into the
   spec choice, a button per spec and Back, the shape Attack... has;
   Build Tech lab the same where a tech II stands, and both rows where
   a lab without a spec waits on the tech II's choice; the hall needs
   nothing. Destroyed, each add-on deals its 2 to the base and a new
   one replaces the one in the slot, as step 2 settled.

4. The board and the codex. render.heroes reads player.heroes, so a
   standard panel is seven columns with three command-zone plates as
   step 7 drew it; the nameplate reads the deck's colour and the
   heroes' names ("Red · Jaina, Zane, Drakk"), turn_colors as it is;
   the add-on slot draws the hall's and the lab's cards from
   buildings/, which the import cut at step 1; the chosen spec card
   (specs/<spec>.png, cut for this) is drawn small on the tech II tile
   once chosen, and on the lab's card for its own. The codex is three
   binders: codex_counts over specs; codex_views' spec views appear as
   the engine already offers them; TechOptions.codex lists every
   spec's cards; the Everything view of seventy-two at CODEX_COLUMNS
   must stay under Discord's upload limit -- measure it and say so in
   the PR, and narrow the view to the specs' three where it does not.
   scripts/render_codex_sample.py renders a standard game's board, hand
   and codex beside the basic game's; put the pictures in the PR.

5. Red and green under the vanilla engine. keywords.keyword_table and
   the set constants in codex.effects read the landed set
   (effects.LANDED_SET: the basic set plus RED and GREEN -- each
   colour's ten starters, its three specs' thirty-six, its three
   heroes and its tokens), so a red or green card whose text is only
   keywords the engine already plays -- Mad Man's haste, Nautical
   Dog's frenzy, Centaur's overpower, Chameleon's stealth, Huntress's
   sparkshot and anti-air, Barkcoat Bear's resist and overpower -- plays
   in full from this step; every other red or green card with text,
   the six heroes' bands and the pair's tokens go into UNIMPLEMENTED,
   written out, and tests/test_codex_effects.py pins the set as exactly
   that and every other landed card handled (its _handled table grows
   with any new static table). A text that opens with a keyword the
   table does not know -- deathtouch, long-range, ephemeral, boost,
   untargetable -- is unimplemented, not half-read: read_keywords takes
   only KEYWORDS. Building cards and upgrades are things in play from
   this step, since Bloodburn, Rich Earth and Verdant Tree are
   starters: a building card has HP, may be attacked once the patrol
   zone allows ("anything with HP", UMR p. 10) and goes to its owner's
   discard when destroyed, dealing nothing to the base (p. 8 speaks of
   tech buildings and add-ons); an upgrade has no HP and cannot be
   attacked (p. 7); neither patrols, both arrive with arrival fatigue,
   and render_panel draws them after the units.

Tests: tests/test_codex_rules.py gains the standard game's rules, each
with its page -- the hero limit at each building and at the hall, a
dead hero replaced at once, a summon refused past the limit, the tech
II's spec kept through a rebuild, the lab's spec and its loss, a tech
II card refused for the wrong spec and allowed for the lab's, the +1
on a multicolour team's first building and never on a team of one
colour and neutral, a starting spell's +1 by the wrong hero and never
for a neutral one, the levels' recipient asked with two heroes in play
and not with one; tests/test_codex_keywords.py pins the heroes_hall
and tech_lab rulings (four); tests/test_codex_game.py the lobby's
rules (a hero of a colour not landed, a fourth hero, a hero twice, a
deck of a colour nobody plays, Start before the seats are complete, a
rematch's swap of teams); tests/codex_positions.py's new_game takes
the teams and the mode -- Bashing against Finesse the default, so no
test changes -- and hero_in_play names the hero where a side has three;
tests/test_codex_driver_full_game.py plays a second game, a standard
one, three red heroes against three green, the policy summoning and
levelling each hero and choosing the first spec offered, to a destroyed
base with every card played for its numbers, and checks nothing hidden
is said; tests/test_codex_cog_lobby.py seats a standard team through
the menu and the deck buttons and starts it; tests/test_codex_cog_turn.py
presses the hero row and the spec choice through the fakes, holding
the request budget. The basic golden is re-recorded for the hero refs
alone, and the PR shows that its diff is only the refs.

scripts/render_codex_emoji.py's FACES gains the six red and green
heroes, a square pinned per hero after one look at the card; the PR's
For the author names the six PNGs to upload to the Codex application.

Record in docs/design/codex.md, a new section "The standard game":
the lobby's picks and why a menu, the record's keys, the saved fields
and their fallbacks, the hero refs and the golden's re-recording, the
hero limit as the ruling words it, the spec at tech II and the lab's,
the multicolour costs and where the surcharge is remembered, the
caster nobody chooses and why, the levels' recipient, building cards
and upgrades in play, what the board draws for all of it; and
LANDED_COLORS beside the landed set in "The vanilla engine and
UNIMPLEMENTED", which is no longer empty and says so.

Done when: a standard game runs through the driver from the lobby to
a destroyed base with three heroes a side; a basic game of Bashing
against Finesse plays as before; the suite is green.

Stop: a standard game on the test server, red against green: three
heroes summoned on one side, its tech II's spec chosen, a heroes' hall
and a tech lab built, every red and green card played for its numbers
and saying so.
```

### 11. Red and green: every card does what it says

**Landed** (2026-10-09, by the cloud routine): the keywords, the costs
and resources, the spells, triggers and abilities, the static grants and
printed overrides, and the upkeep, the end of the turn and the tokens, a
commit each -- `UNIMPLEMENTED` empty again, the fourteen keyword rulings
and the 101 card and hero rulings pinned, `DIVIDE_DAMAGE` and
`MODE_CHOICE` as buttons. What it settled is in docs/design/codex.md,
"Red and green".

The Blood Anarchs and the Moss Sentinels, ninety-two cards, six
heroes, six tokens: everything with text that step 10 played for its
numbers. The pair brings the engine keywords it has not met, two
kinds of choice a spell can ask that nothing neutral asked (damage
divided among targets, one of two modes), control that changes hands
and comes back, a printed value replaced for a turn, a coin, and the
first upkeep and end-of-turn effects that are not the surplus's draw.
It lands on the rulebook's own first game.

```text
Step 11 of docs/codex-bot.md. Steps 1 to 10 have landed. The rules are
the card texts of the red and green sets in codex/data/cards.json --
the two starting decks, Anarchy, Blood and Fire, Balance, Feral and
Growth, the six heroes' bands and the pair's tokens -- their rulings in
rulings.json's Red, Green and Heroes groups, the General rulings on the
keywords below, and the Card FAQ (UMR pp. 19-22): read every one before
writing any, and read each card against the glossary (pp. 16-18) and
UMR p. 15 (play, put into play and summon; legendary; owner and
controller; workers). Also read docs/design/codex.md, "Targeting and
the effects", "The keywords" and "The standard game". Five commits:
the keywords; the costs and the resources; the spells, the triggers
and the abilities; the static grants and the printed overrides; the
upkeep, the end of the turn and the tokens. UNIMPLEMENTED empties as
they land and is empty at the end.

1. The keywords (KEYWORDS, STACKING, the engine's questions):
   deathtouch (Tiny Basilisk, Potent Basilisk: combat damage kills a
   unit or hero through armor and counts as death from combat damage;
   two instances are one), long-range (Doubleshot Archer: the defender
   deals nothing back unless it has it too; anti-air flown over and the
   tower still shoot), ephemeral (Crashbarrow, Shoddy Glider, the
   Sharks of Surprise Attack: dies at the end of any turn), boost X
   (Marauder, Feral Strike, Murkwood Allies: paid as the card is
   played, from the hand alone -- PlayOption carries the boost's cost
   and the play action whether it was boosted, refused where it cannot
   be paid, and never offered where an effect puts the card into play),
   untargetable (Moss Ancient, Potent Basilisk: no part with the target
   symbol may choose it; attackable, and chosen by what does not
   target), armor as the glossary has it -- the squad leader's,
   refreshed each turn as now; Ironbark Treant's +2 while patrolling;
   the temporary armor of Rampant Growth, Dinosize, Stampede and
   Argagarg's band, gone unused at the end of the turn; stacking --
   armor piercing (Ferocity: armor prevents nothing of it, and still
   prevents the next damage), legendary (Galina Glimmer, Guargum;
   UMR p. 15: settle destroys the newest copy, whatever else it is), and
   the conditioned keywords read off the position each time: Predator
   Tiger and Tiny Basilisk against tech 0 units, Stalking Tiger's
   stealth while attacking a unit and its invisibility while a Feral
   hero is held, Gemscout Owl's flying that cannot attack, "can't
   patrol" (Makeshift Rambaster, Land Octopus) and "can't attack"
   (Young Treant), "+X ATK when attacking buildings" (Makeshift
   Rambaster, Steam Tank), and Wandering Mimic's six, read off what is
   in play and never off another Mimic (the FAQ). Rampaging Elephant
   readies the first time it exhausts each turn. Frenzy, sparkshot,
   resist, anti-air, haste, overpower, flying and stealth on the pair's
   cards play as they did from step 10.

2. The costs and the resources. Rich Earth hires for 0 and still tucks
   a card; Gigadon costs 1 less per green unit held, Pirategang
   Commander's Blood units and Guargum's Growth spells cost 0 and need
   no building or hero (effective_cost and why_not_playable; floor 0,
   and Gigadon's cost stays 9 to anything that reads a cost, the FAQ);
   Merfolk Prospector, Galina Glimmer and Gemscout Owl gain gold,
   Pillage and Gunpoint Taxman steal it (the glossary's Steal: as much
   as there is); Rickety Mine flips a coin -- engine.rng, recorded in
   the journal as a shuffle's order is (StepResult.drawn grows a kind),
   so a replay lands the same side; workers are trashed by Marauder's
   boost, Detonate, Predator Tiger and Land Octopus's upkeep (a worker
   lost is a count down, UMR p. 15, and the hire still needs a card); a
   trashed card leaves the game (Detonate, Nature Reclaims,
   Desperation): gone, in no pile and in no count. Desperation's two
   halves -- trash and draw three with an empty hand (the hand is empty
   once it is played, the FAQ), and the hand discarded at the end of
   the main phase -- the second a flag on the player that lock_patrol
   reads and clears.

3. The spells, the triggers and the abilities, through codex.effects
   and codex.flow.resolve as step 6 built them, each a row beside its
   sentence. Damage with a shape: Fire Dart and Flame Arrow choose a
   unit (or a hero) or a building and deal by what was chosen; Scorch,
   Bombaster and Firebat a patroller or a building; Ember Sparks and
   Burning Volley divide theirs -- DIVIDE_DAMAGE, a new kind: the
   targets chosen as TARGET parts, then the split, at least 1 to each
   (the FAQ), a button per target adding a point until the damage is
   placed, with Hotter Fire's +1 on the total and not per target -- and
   the modal spells, Feral Strike and Murkwood Allies, choose one of
   two, or both when boosted: MODE_CHOICE, a new kind, a button per
   mode, asked only where there is a choice. Kidnapping and Ogre
   Recruiter take control (the controller changes, the owner does not,
   as Final Smash's third part does), Kidnapping until the end of the
   turn and back to the last controller then, the kidnapped unit
   readied with haste (the FAQ); Chaos Mirror swaps two printed ATKs
   until the end of the turn and Polymorph: Squirrel makes a unit a 1/1
   Squirrel with no abilities until its caster's next upkeep -- both a
   printed override on the instance, commit 4. Maximum Anarchy,
   Bloodlust (the damage at the end of the turn), Charge, Now, Pillage
   with its Pirate clause, Scorch, Moment's Peace (the caster's units
   cannot patrol and the opponent's cannot attack anything of theirs
   until the caster's next turn: patrol_candidates and legal_defenders
   read it), Circle of Life (sacrifice a green unit, then a green unit
   one tech higher costing 5 or less from the codex into play -- a
   TARGET over the codex, which is the caster's, pictured to them
   alone, and never Gigadon), Feral Strike's two modes (two units from
   the codex to the hand, revealed and so named; up to two units from
   the hand into play with the tech building of their level, the spec
   ignored, the FAQ), Stampede (+3 ATK and +3 armor, the excess to the
   base and never elsewhere, over overpower), Ferocity, Dinosize,
   Rampant Growth, Forest's Favor, Nature Reclaims (never a base, an
   add-on or a tech building), Detonate (any player's worker, or a
   building card). Arrives: Bamstamper Lizzo (3 to a unit, mandatory),
   Artisan Mantis (repair 3), Potent Basilisk (may destroy an upgrade
   or an ongoing spell), Pirategang Commander (three Pirates), Moss
   Ancient (three Squirrels, on arriving and on attacking), the two
   Pandas (arrive exhausted, a Wisp each), Young Treant (a card), Spore
   Shambler (two runes on itself), Fairie Dragon (a feather rune on a
   tech I or II unit, may), Tyrannosaurus Rex (up to two of units,
   upgrades and workers, in any mix), Disguised Monkey (stealth this
   turn), Argagarg's Wisp. Attacks: Doubleshot Archer (3 to that
   player's base), Ogre Recruiter (control of a tech 0 or I unit, after
   the damage, if it survived), Cinderblast Dragon (on arriving and on
   attacking: a non-ultimate Fire spell from the hand or the codex for
   free, no Fire hero needed; on an attack, after the defender and
   before the damage, a new defender if the spell destroyed the first
   and no second spell, the FAQ). Dies: Crash Bomber (by whose turn it
   is), Captured Bugblatter (whenever any unit dies, by whose turn),
   Drakk's band (each opponent's base), Pirategang Commander's granted
   line on its controller's units, Bloodburn's rune (limit 4). Damages:
   Molting Firebird (a building: 1 to every unit and hero of that
   opponent), Predator Tiger (a base: a worker trashed there), Might of
   Leaf and Claw (a growth rune per attacker's combat damage, none for
   0, one for damage armor prevented, the FAQ), Gunpoint Taxman (kills
   a patroller: steal 1), Zane's band (a scavenger or technician Zane
   himself kills, in combat or by his own ability, never by a spell).
   Abilities, as actions with their costs, usable only where the cost
   can be paid in full (UMR p. 8): a gold (Firebat with its exhaust,
   Lobber, Bombaster's sacrifice of itself, Calypso Vystari's "if you
   played a spell this turn", Careless Musketeer's 1 to its own base,
   Verdant Tree's tech buildings finished at once this turn -- two in
   one turn, the FAQ -- Firehouse, readied where its 2 destroyed the
   target and not where an Illusion died of the targeting, the FAQ),
   a rune (Bloodburn's two, Spore Shambler's and Blooming Ancient's
   moved rune, Blooming Elm's three or one), a discard (Calamandra's
   stealth), a sacrifice (Bombaster), the heroes' bands (Jaina's 1 to a
   patrolling unit or building and her 3; Argagarg's +1 ATK and +1
   armor; Calamandra's max: a Tiger from the codex into play, free and
   needing no building; Zane's max: a patroller shoved to an empty
   slot of its own zone and 1 damage to it, the damage alone where no
   slot is empty), Rickety Mine's exhaust, Sanatorium (a gold and its
   exhaust: a card, then up to two tech 0, I or II units from the hand
   into play with haste and ephemeral -- a TARGET over the hand,
   pictured to its owner alone), Merfolk Prospector's exhaust.

4. The static grants and the printed overrides, read off the position
   each time (body_keywords and unit_stats with the match, as step 6
   left them): War Drums (+X where X is its controller's units in play,
   the FAQ), Hotter Fire (+1 to every red spell's and red ability's
   damage, stacking per copy, never combat damage), Behind the Ferns
   (stealth to the caster's units of 3 ATK or less, read as the attack
   is declared and before its bonuses, the FAQ), Master Midori's +1/+1
   to units with no abilities (is_vanilla: a keyword, a granted
   ability and a printed line each count, a rune, damage, a patrol
   slot's bonus and an Illusion's type do not, his rulings) and his
   flying on his own turn, Calamandra's resist 1 to her units, Drakk's
   frenzy to his units and his haste to the first unit that arrives
   from the hand each turn (kept for good once given, and only by an
   arrival from the hand -- a token, a forecast unit and a unit out of
   a Jail do not count, nor does a unit played before he reached max,
   his rulings), Blooming Elm's overpower to units and heroes with a
   +1/+1 rune, Fairie Dragon's feather runes (3/1 with flying, over the
   printed values and under the runes, while any Fairie Dragon is held
   by anyone, the FAQ), Spirit of the Panda's +2/+2 with its granted
   attacks trigger (the gold to the attached unit's controller, the
   healing to the spell's), Might of Leaf and Claw's +5/+5 from five
   growth runes, Pirategang Commander's and Guargum's free plays.
   Where two grants read each other --
   Behind the Ferns gives stealth to a unit of 3 ATK or less, and
   Midori's +1/+1 goes only to a unit with no abilities -- the Card FAQ
   settles it by which came first: each card in play and each band a
   hero has reached carries the order it came to be (one sequence on
   the match, a saved field), and unit_stats applies the grants in that
   order; a test holds the FAQ's two examples, the Tiger Cub and the
   Iron Man, both ways round. The printed override
   (CardInstance.printed, None in an older save): Chaos Mirror's ATK and
   Polymorph's 1/1 Squirrel with no abilities replace what the card
   prints until their end, keep its runes, damage and attachments over
   them, and are what a copy reads (the glossary's Copy): the Mirror
   Illusions of step 13 copy the printed card, and these are the two
   exceptions the glossary names.

5. The upkeep, the end of the turn and the tokens. Upkeep effects of
   the pair: Land Octopus (two workers or itself: a choice), Galina
   Glimmer's gold (rounded down, herself counted), Gemscout Owl's gold,
   Dothram Horselord joining the side with the most total ATK (control
   at upkeep, his own ATK counted on his side, the FAQ), Spirit of the
   Panda's healing; UPKEEP_ORDER is asked only where the order changes
   something -- a sacrifice or a death among the effects due -- and
   pure gains resolve unasked in a fixed order, as the surplus's draw
   did; say in the PR which orders are asked. The end of the turn
   (begin_tech, before the buildings finish, both sides): ephemeral
   dies, Bloodrage Ogre returns to its owner's hand where it neither
   arrived nor attacked this turn (after the draw phase, the FAQ),
   Chameleon Lizzo returns if still in play, Bloodlust's 1 damage,
   Kidnapping's control given back, every this-turn modifier and
   override removed, Moment's Peace held until its caster's next turn.
   The tokens (Pirate, Beast, Frog, Hunter, Squirrel, Wisp; the blue
   Shark is Surprise Attack's) are summoned as the Dancer is, trashed
   when they leave play; Final Showdown's two Hunters are summoned for
   the opponent, who controls them and may not patrol them on the
   caster's turn (the FAQ); Moss Ancient's Squirrels have haste and are
   invisible while it is held and not after.

Tests: tests/test_codex_keywords.py pins the General rulings of
deathtouch, longrange, ephemeral, boost_x, untargetable, limit_x and
channelling -- fourteen today -- named as before, and the ratchet counts
them; tests/test_codex_card_rulings.py every ruling of the Red, Green
and Heroes groups on the pair's cards and heroes (88 and 13 today; the
file says how many it found, so a re-import that adds one fails
loudly); tests/test_codex_spells.py each spell's happy path and its
refusals, the divided damage with and without Hotter Fire, the modal
spells boosted and not, a boost refused when an effect puts the card
into play; tests/test_codex_effects.py asserts UNIMPLEMENTED empty and
every red and green card handled; and the scenarios: the FAQ's Behind
the Ferns and Midori examples, Cinderblast Dragon's spell destroying
the defender, Dothram Horselord changing sides at upkeep, Bloodrage
Ogre's return after the draw, Rickety Mine's coin replayed byte for
byte, Kidnapping's control back at the end of the turn, Stampede's
excess to the base past overpower, a second Galina Glimmer destroyed on
arrival, Final Showdown's Hunters refused the patrol zone on the
caster's turn, Land Octopus's upkeep choice asked and the Owl's gold
not. The new kinds' views: DIVIDE_DAMAGE and MODE_CHOICE are buttons in
the panel; a TARGET over the hand or the codex is pictured as the hand
is, to its owner alone, and tests/test_codex_cog_turn.py holds that
nothing of it reaches the channel. Read every new line of both
full-game transcripts for hidden information: a card fetched from the
codex is named only once it is revealed or in play.

Record in docs/design/codex.md, a section "Red and green" after
"Targeting and the effects": the keywords added and what stacks, the
boost, the printed override and the order of grants, control that
returns, the coin in the journal, the trash, the end-of-turn effects
and their order, the tokens' limits, the two prompt kinds, which
upkeep orders are asked; "The saved fields" gains what this step added
with its fallbacks (printed, the sequence, the end-of-main-phase
discard, the controller to return to, the growth and blood runes).

Done when: every red and green card has a handler or a keyword, every
ruling on them is a test, UNIMPLEMENTED is empty, and both full-game
tests still end a game; the golden is untouched unless a wording
changed, which the PR says and shows.

Stop: Calamandra against Jaina on the test server -- the Core Set's
own first game (UMR p. 3), a basic game on the green and red starting
decks -- with the author on one side, and nothing refused that the
rulebook allows.
```

### 12. Purple and black

**Landed** (2026-10-09, by the cloud routine): every purple and black
card, hero and token does what it says, in six commits; `UNIMPLEMENTED`
is empty, 122 rulings and ten General ones are pinned, and the board
draws the future, time runes, a disabled card and a Graveyard's buried
count. What it settled is in docs/design/codex.md, "Purple and black".

The Vortoss Conclave and the Blackhand Scourge, ninety-two cards,
six heroes, six tokens. Purple is time: runes that count down on a card
in play (fading) or on a card not yet in play (forecast, and with it a
zone the game has not had, the future), a turn taken twice, a hero who
fades, a loan paid at upkeep or the game lost. Black is death: damage
dealt as runes that never heal, a graveyard that buries what dies and
plays it again, the weakest unit sacrificed, a hero back from the
command zone at max level, and the one max-level trigger whose choice
the active player cannot make for the other side (UMR p. 14). The step
lands the two colours for their numbers first, as step 10 landed red
and green, then plays their text.

```text
Step 12 of docs/codex-bot.md. Steps 1 to 11 have landed. The rules are
the card texts of the purple and black sets in codex/data/cards.json
-- the two starting decks, Past, Present and Future, Demonology,
Disease and Necromancy, the six heroes' bands and the pair's tokens --
their rulings in rulings.json's Purple, Black and Heroes groups, the
General rulings on the keywords below, and the Card FAQ (UMR pp.
19-22): read every one before writing any, and read each card against
the glossary (pp. 16-18) and p. 14 (decisions on opponents' turns).
Also read docs/design/codex.md, "The standard game" and "Red and
green". Six commits: the colours landed for their numbers; time, and
the keywords; the forms of death; black's effects; purple's effects;
the upkeep, the extra turn and the tokens. UNIMPLEMENTED holds the
pair after the first commit, pinned, and is empty after the last.

1. The colours landed. LANDED_COLORS gains purple and black, so the
   lobby offers Max Geiger, Prynn Pasternaak, Vir Garbarean, Garth
   Torken, Orpal Gloor and Vandy Anadrose; LANDED_SET gains PURPLE and
   BLACK; every purple or black card whose text is only keywords the
   engine plays (Argonaut's readiness, the Stinger's flying, the
   Horror's deathtouch) plays in full, and every other goes into
   UNIMPLEMENTED, written out and pinned; scripts/render_codex_emoji.py's
   FACES gains the six heroes, and the PR's For the author names the six
   PNGs. A standard game of three purple heroes against three black
   runs through the driver for its numbers before anything below.

2. Time, and the keywords. Time runes (CardInstance.time_runes and
   HeroState.time_runes for Prynn, 0 in an older save; the chits under
   time_runes/ on the board): fading X (Fading Argonaut, Shimmer Ray,
   Yesterday's Golgort, Rememberer, Ebbflow Archon, Vortoss Emblem,
   Prynn) arrives with X and loses one at its controller's upkeep, and
   is sacrificed when its last rune goes by any means (the ruling), a
   fading card with no runes from the start never fading; forecast X
   (Plasmodium, Knight of the Conclave, Reaver, Omegacron, Double Time,
   the Mech) is played from the hand paying its cost and meeting its
   requirements now -- into the future, PlayerState.future, a list of
   instances with their runes, not in play, untargetable and
   unaffected, and jailed by nothing (step 13) -- and arrives at the
   upkeep that removes its last rune, with arrival fatigue and its
   arrives trigger then, needing nothing any more; a forecast spell
   resolves then instead. Time Spiral, Tinkerer and Seer add or remove
   a rune from any player's card, in play or in the future (the FAQ);
   Shimmer Ray discards to add one, in the main phase alone; Omegacron
   sacrifices to lose one while forecasted, the one ability usable on a
   card in the future; Temporal Research counts its caster's runes,
   Vortoss Emblem's among them wherever it is attached. The keywords
   (KEYWORDS, STACKING): indestructible (Hardened Mox, Immortal,
   Gargoyle: exhausted instead of dying, its damage and attachments
   gone and its runes kept; never sacrificed; exhausted for good at 0
   HP from runes; skipped by every "lowest" or "weakest" choice, the
   ruling), disable (Octavian, Ready or Not's second clause: exhausted,
   sidelined if patrolling, and not readied at its next ready phase --
   CardInstance.disabled and HeroState.disabled, false in an older
   save, cleared by the ready phase that skips them), untargetable
   (Chronofixer, Omegacron, the Mech, Nebula's grant), long-range
   (Necromancer), boost (Hooded Executioner), deathtouch (Gorgon, the
   Horror, Wight against heroes), obliterate 2 and 4 (Terras Q,
   Zarramonde) and resist 2 and 3 on them; unstoppable with a
   condition (Pestering Haunt, Cursed Ghoul against runed units, Wight
   against heroes, Shrine's Demons against units); Nullcraft's "can't
   be the target of Buff or Debuff spells" and Battle Suits' Soldiers
   and Mystics read a card's subtype for the first time (Card.subtype,
   which the import carries; Illusion is step 13's); Lord of Shadows'
   "your black units are invisible" reads a card's colour.

3. The forms of death. Damage dealt as -1/-1 runes (Orpal's first
   band, Poisonblade Rogue's attacks, Plague Spitter): combat damage
   that leaves runes instead of damage, permanent, kills at 0 HP, and
   still counts as combat damage for anything that asks (Brave Knight
   in step 13, Jandra now; Orpal's ruling); Blackhand Dozer's floor
   (damage its controller deals, from any source and on any turn,
   cannot take an opposing base below 6, a tech building's 2 included,
   the FAQ). The Graveyard (a starting building): its controller's
   non-token units are buried in it as they die -- a list on the
   building's instance, out of play and out of the discard, runes and
   effects gone -- and a buried unit is played from it through its
   exhaust, paid and meeting its requirements, with its arrives
   trigger; four buried sacrifice it and discard them; it changes hands
   with the building and its tech II and III units are playable only
   with the matching spec (the FAQ). The weakest unit (the glossary:
   lowest tech, then least ATK, the chooser deciding a tie -- the
   active player, since the chooser is whoever resolves it) for
   Sacrifice the Weak and Hooded Executioner's boost, skipping what
   cannot be sacrificed or destroyed (Pestering Haunt, an indestructible
   unit, Gilded Glaxx with gold); Death Rites (a this-turn trigger on
   the caster: an opponent's lowest-tech unit per death); Doom Grasp
   (sacrifice a unit, then destroy a tech 0, I or II unit or hero);
   Spreading Plague; Death and Decay; Shadow Blade (3 to a patroller,
   and a random discard if it dies of it -- an Illusion's controller
   discards too, the FAQ); Soul Stone (attach; +1/+1; where the unit
   would die, its damage is removed and every Soul Stone on it
   sacrificed instead, no death effect; with Two Lives in step 13, the
   crumbling rune first). A random discard (Thieving Imp, Cursed Crow,
   Shadow Blade) is engine.rng recorded in the journal, and the card
   is a count to the narration, never a name. Sacrifice as a cost
   (Bombaster's shape): Lich's Bargain's worker, Doom Grasp's unit,
   Orpal's non-Demon, Garth's Skeleton, Banefire Golem's unit at
   upkeep, Omegacron's.

4. Black's effects, through the tables and the resolve loop. Arrives:
   Thieving Imp (a random discard), Plague Lab (a -1/-1 rune on every
   opposing unit), Plague Lord (on arriving and on attacking: a rune on
   each opposing unit and hero), Cursed Ghoul (a rune on a unit),
   Skeleton Javelineer (a javelin rune), Zarramonde (played from the
   hand alone: a unit, hero, worker, upgrade or ongoing spell
   destroyed), Terras Q (four Warlocks summoned for an opponent, who
   controls them; Terras Q may not attack or patrol while any of those
   four is in play -- the tokens remember the Terras Q that made them,
   so a second copy or a trashed-and-returned one is held by its own
   four alone, the FAQ). Attacks: Bone Collector (a Skeleton),
   Poisonblade Rogue (armor piercing and runes for damage this turn).
   Dies: Jandra (from combat damage, deathtouch and rune damage
   included: every non-Demon unit of hers), Blackhand Dozer (the active
   player destroys one of its controller's lowest-tech units -- asked
   of the active player whichever side the Dozer was on, UMR p. 14),
   Gorgon (a card), Corpse Catapult (a corpse rune per death of its
   controller's units), Necromancer (a Skeleton per non-token death of
   its controller's). Damages: Cursed Crow (a base: a random discard,
   not for a building's 2, the FAQ). Spells: Deteriorate, Sickness (one
   or two), Summon Skeletons, Dark Pact (2 to a base, two cards drawn
   by its owner), Carrion Curse (look at an opponent's hand -- pictured
   to the caster alone, never to the channel -- and choose up to two
   non-unit cards of it, which they discard: a TARGET over the
   opponent's hand), Nether Drain (two levels from one hero to another,
   either side's, floors and ceilings kept; the drained hero may not
   level this turn; a max-level trigger reached on the opponent's turn
   does not resolve where it asks a choice, p. 14), Lich's Bargain (a
   worker, 4 to the caster's base, three tokens), Metamorphosis (every
   unit sacrificed; each non-Demon hero to max, a Demon until it leaves
   play, two +1/+1 runes, readiness, invisible), Death Rites, Doom
   Grasp, Shadow Blade, Spreading Plague, Death and Decay. Abilities:
   Garth's Skeleton (once per turn), his Skeleton for a card, his max
   (a tech I or II unit costing 5 or less from the discard pile into
   play, the discard pictured to him alone, its tech building and spec
   needed, no gold), Orpal's rune for a non-Demon (once per turn) and
   his max (the first time a unit with a -1/-1 rune dies each turn, the
   active player puts a rune on two units friendly to it), Vandy's
   fetch (a Demonology spell from the codex to the hand, revealed and
   named) and her max (+2/+2 to one friendly and one opposing tech 0 or
   I unit, mandatory as far as it goes, both dying at her controller's
   next upkeep whether she is there or not; reached on the opponent's
   turn, it does not resolve, p. 14 -- the engine's one reading of a
   trigger that needs a decision on the wrong turn, which Nether Drain
   and Blackhand Resurrector can cause), Gargoyle's gold (once per
   turn: until its controller's next upkeep, not indestructible, flying,
   +3 ATK, may attack and patrol), Corpse Catapult's 6 to a building,
   Crypt Crawler's gold (a flier loses flying this turn), Plague Lab's
   duplication (a gold and its exhaust: for any number of cards with
   runes, another rune of a kind already there -- a TARGET repeated,
   each pick a card and, where it has runes of two kinds, which; never
   a card in the future), Skeletal Lord's five Skeletons (exhausted by
   the Lord, so arrival fatigue is no bar, the FAQ: a unit from the
   hand into play, no requirements), Blackhand Resurrector (its exhaust
   and sacrifice: a hero that died this game summoned from the command
   zone at max level, summoning runes or none, its max-level trigger
   resolved; at level 1 under Chronofixer). Static: Abomination (-1/-1
   to every other unit, both sides, stacking), Twilight Baron (its
   controller plays no tech II or III units while it is held; those
   already in play and the future unaffected), Voidblocker (whoever
   attacks it exhausts another of their ready units or heroes -- a
   choice at declare_attacker, or nothing where there is none, the
   FAQ), Shrine of Forbidden Knowledge (a card more at the draw phase
   and a hand of six, two of them seven; Demons unstoppable by units),
   Skeletal Lord's +1/+1 to Skeletons, Skeletal Archery's long-range
   and anti-air to Skeletons, Lord of Shadows (itself included),
   Pestering Haunt's ceiling of 1 ATK, Wight.

5. Purple's effects. Max Geiger: sparkshot; discard for a card; his
   max: a friendly unit trashed and returned fresh, under the same
   controller, with arrival fatigue (his rulings). Prynn: fading 4 and
   a rune per attack; dies from fading -- by the upkeep's removal
   alone -- and every opponent skips their next draw phase, keeping
   their hand; her max: two runes for a unit trashed, every unit she
   trashed returned fresh to its last controller when she leaves play
   (a list on her); at two runes she may use it and dies at once, not
   from fading (her rulings). Vir: look at the top card of the deck
   (pictured to him alone), exchange it with a card from the hand, play
   it paying and meeting its requirements -- nothing on an empty deck,
   no reshuffle; his max: a Mech in the future with forecast 2.
   Spells: Forgotten Fighter, Undo and Stewardess's return to the
   owner's hand; Origin Story (a hero to its command zone without
   dying -- no death effect, its levels and runes gone, and no
   summoning rune placed, the author, 2026-10-09 -- so its owner may
   summon it again on their next turn); Assimilate (control of an upgrade, an ongoing spell or a
   building card, never a base, an add-on or a tech building; a
   channeling spell taken is discarded at once); Temporal Distortion (a
   tech I or II unit of the caster's to its owner's hand, then a unit
   of that level costing no more from the codex into play, requirements
   ignored; nothing where the unit cannot leave play); Ready or Not;
   Rewind (an ultimate castable whatever the turn Prynn maxed, every
   tech 0, I and II unit to its owner's hand, no death effects);
   Research & Development (five cards, the one reshuffle); Promise of
   Payment (the next card played this turn costs 0 -- the discount
   taken by the next card alone, never a hire, a building or an ability
   -- and its printed cost is owed at the caster's next upkeep after
   the upkeep's other effects, or the game is lost: GAME_OVER's third
   way, MatchState.lost_by_debt or its like, and nothing owed where no
   card followed, the FAQ); Now, Unphase (invisible until the caster's
   next upkeep), Temporal Research, Time Spiral, Double Time (a forecast
   spell: an extra turn after this one when it resolves, two copies two
   turns -- MatchState.extra_turns, the turn passing to the same
   player with every phase, and the tech choice standing through it as
   through any turn). Units: Hive (five Stingers on arriving; a gold
   re-summons one, five per Hive; the Stingers sacrificed with it,
   which the active player chooses between two Hives), Ebbflow Archon
   (-1/-1 per rune; a rune for a unit to its owner's hand or a hero to
   its command zone), Gilded Glaxx (while its controller has gold it
   is not sacrificed and leaves play only by combat damage, and 0 HP
   does not kill it; deathtouch and rune damage do, the FAQ),
   Chronofixer (no opposing hero gains a level by any means), Nebula
   (its controller's other units invisible; a free destroy once per
   turn), Octavian (8 gold: readied, and up to eight units and heroes
   disabled), Omegacron, Reaver (a gold, its exhaust and a discard: two
   workers trashed, or 6 damage to each of up to two units or heroes --
   MODE_CHOICE), Rememberer (fading 3; per rune removed, a unit with
   fading from the discard pile into play with its requirements met --
   the sacrifice and the return at once, the active player ordering
   the sacrifice first to return itself, the FAQ), Second Chances (once
   per turn, a non-token unit leaving play other than by combat damage
   -- sacrificed, bounced, obliterated, killed by a spell -- returns
   fresh to its last controller; several at once, one at random,
   engine.rng, recorded), Sentry (prevents the first spell or ability
   damage to one of its controller's patrollers each turn, sparkshot's
   included, random among several), Shimmer Ray, Slowtime Generator
   (every player's workers yield at most 4 at upkeep), Tricycloid (+1/+1
   per rune; a rune for 1 damage), Void Star (4 gold once per turn: +4
   ATK until the next upkeep), Vortoss Emblem (fading 3; attached to
   any unit, which is a flagbearer; its caster's card), Warp Gate
   Disciple (a gold and its exhaust: a tech I or II unit from the codex
   into play, requirements ignored), Xenostalker (attacks: 1 to up to
   four patrollers without flying), Yesterday's Golgort (a rune per
   building its controller's cards damage), Hardened Mox (trashed the
   moment its controller has a tech II unit, the future included),
   Hyperion (attacks: a card), Knight of the Conclave, Immortal,
   Plasmodium, Seer, Nullcraft. Where a card's rulings speak of Jail or
   Illusions, the rule waits for step 13 and the test is written then.

6. The upkeep, the extra turn and the tokens. Upkeep effects of the
   pair: a time rune off each fading and forecast card, Banefire Golem's
   sacrifice (itself where nothing else, mandatory), Plague Lord's base
   damage per rune (its controller's turn alone, its own base included),
   Shrine's 1, Promise of Payment's debt last, Vandy's doomed pair, Land
   Octopus and the rest as step 11 ordered them; UPKEEP_ORDER as step
   11 left it, asked where the order changes something -- a rune
   removed before Rememberer's or Prynn's, a sacrifice before a death
   -- and the PR says which. The extra turn: begin_tech passes the turn
   to the same player where one is owed, and the turn message, the
   heading and the standing tech prompt follow as for any turn. The
   tokens: Skeleton, Zombie, Horror (deathtouch), Warlock, Stinger
   (flying), Mech (forecast 2, untargetable); the board draws a card in
   the future in the grid after the units, greyed with its rune chit,
   a buried count on the Graveyard's card, and the disabled mark beside
   the exhaust glyph.

Tests: tests/test_codex_keywords.py pins the General rulings of
fading_x, forecast_x and indestructible (ten today); tests/test_codex_card_rulings.py
every ruling of the Purple, Black and Heroes groups on the pair (107
and 15 today, counted by the file); tests/test_codex_spells.py each
spell's happy path and refusals; tests/test_codex_effects.py asserts
the set empty; and the scenarios: Prynn at two runes using her max and
dying not from fading, Rememberer returning itself, two Double Times,
Promise of Payment unpaid and the game lost, Second Chances' random
return replayed byte for byte, Terras Q held by its own Warlocks and
not a copy's, Banefire Golem sacrificing itself, Vandy's max reached
on the opponent's turn and not resolved, Blackhand Dozer's floor
against a tech building's 2, Skeletal Lord exhausting fatigued
Skeletons, Hardened Mox trashed by a forecasted tech II unit, Gilded
Glaxx at 0 HP with gold, Carrion Curse's look reaching the caster alone
(tests/test_codex_cog_turn.py), a forecast unit arriving with its
trigger after its building was destroyed. Read every new line of the
transcripts for hidden information: the top of a deck, a hand looked
at and a discard pile searched are pictured to one player and named to
nobody until a card is played.

Record in docs/design/codex.md, a section "Purple and black" after
"Red and green": time and the future, the forms of death and the
graveyard, the weakest, the decision the active player cannot make,
the extra turn, the debt, the subtypes and the colour as rules, the
saved fields with their fallbacks (time runes, the future, buried,
disabled, the debt, extra turns, the lineage of a token).

Done when: every purple and black card has a handler or a keyword,
every ruling on them is a test, UNIMPLEMENTED is empty, and the
full-game tests still end a game -- a third of them purple against
black.

Stop: the Vortoss Conclave against the Blackhand Scourge on the test
server, the author on one side: a Plasmodium arriving from the future,
a unit played again out of the Graveyard, and nothing refused that the
rulebook allows.
```

### 13. White and blue

**Landed** (2026-10-10, by the cloud routine): every white and blue
card, hero and token does what it says, in six commits, and so every
printed card plays and the lobby offers all twenty heroes;
`UNIMPLEMENTED` is empty for good, the 92 rulings on the pair and the
General rulings of its keywords are pinned, and the ratchets count every
ruling the data holds. What it settled is in docs/design/codex.md,
"White and blue".

The Whitestar Order and the Flagstone Dominion, ninety-two cards, six
heroes, seven tokens. White is the body and the mind: armor that moves,
a hero with two lives, monks who heal and ninjas who hide, an oath,
and cards that look at the other hand. Blue is the law: a jail that
holds the opponent's units, a council that limits their plays, a
silence that strips their heroes, illusions that die when looked at,
copies, a hero who stashes a card at the draw, and the one standing
reveal in the game -- an upgrade under which the opponent plays with
their hand open. After it every printed card plays, and the lobby
offers all twenty heroes.

```text
Step 13 of docs/codex-bot.md. Steps 1 to 12 have landed. The rules are
the card texts of the white and blue sets in codex/data/cards.json --
the two starting decks, Discipline, Ninjutsu and Strength, Law, Peace
and Truth, the six heroes' bands and the pair's tokens -- their rulings
in rulings.json's White, Blue and Heroes groups, the General rulings on
the keywords below, and the Card FAQ (UMR pp. 19-22): read every one
before writing any, and read each card against the glossary (pp.
16-18). Also read docs/design/codex.md, "Hidden information on
Discord", "Red and green" and "Purple and black". Six commits: the
colours landed for their numbers; the keywords and the copies; the
zones and the rules a player is put under; white's effects; blue's
effects; the last of the tables. UNIMPLEMENTED holds the pair after
the first commit, pinned, and is empty for good after the last.

1. The colours landed. LANDED_COLORS is every colour, so the lobby
   offers all twenty heroes -- Garus Rook, Grave Stormborne, Setsuki
   Hiruki, Bigby Hayes, General Onimaru, Sirus Quince the six new --
   and LANDED_SET is every card; what plays for its keywords alone
   plays (Fox Viper, Flying Fox, Glorious Ninja, Vigor Adept,
   Porcupine, Savior Monk, Fuzz Cuddles), the rest is pinned in
   UNIMPLEMENTED; FACES gains the six heroes and the PR names the PNGs.
   The Everything view of a white or blue codex is measured as step
   10's was.

2. The keywords and the copies. Two lives (Rook's max, Justice
   Juggernaut: destroyed, it heals and takes a crumbling rune instead,
   no death effect resolving -- not the technician's card -- and dies
   for real with the rune; sacrificed without one, it takes the rune
   and the sacrifice's effect still happens); stash (Bigby: at the draw
   phase its player may keep one card and draws one less, so the hand
   ends the same size -- STASH, a new kind the owed DRAW_PHASE waits on
   where its player has stash, a button per card to keep and one to
   keep none, pictured as the hand is, to its owner alone); illusion
   (a subtype, not an ability, so Midori's +1/+1 reaches it: an
   Illusion dies the moment a spell or ability of either player
   targets it, before the effect, which does not resolve on it --
   Spectral Aven, Hound, Roc, Tiger and Flagbearer, Reteller of
   Truths, Liberty Gryphon, the Mirror Illusions; Dreamscape makes
   every tech 0, I and II unit one while it is held and Hallucination
   up to two for a turn; Macciatus gives its controller's +1/+1 and
   stops the dying); detector (Eyes of the Chancellor, Versatile
   Style's hero for a turn: a detector sees every hidden card of the
   opponent's, so detected_by reads detectors beside the tower);
   unattackable (Masked Raccoon with a Cute Animal, Liberty Gryphon's
   three with another Illusion); armor piercing (Speed of the Fox);
   stealth and invisible with conditions (Smoker, Hidden Ninja's kept
   past 4 ATK, Fox's Den School's Ninjas and Cute Animals, Flagstone
   Spy, Eyes' grant); long-range while exactly 1 ATK (Bluecoat
   Musketeer); unstoppable with conditions (Rook against a lone
   patroller, Colossus against a base, Traffic Director against a
   building, Patriot Gryphon against small units, Masked Raccoon with
   another Ninja, Justice Juggernaut that cannot patrol, Daigo). Copies
   (the glossary's Copy): Manufactured Truth and Quince's Mirror
   Illusions copy the printed card -- its type, subtype, ATK, HP,
   abilities and tech level, step 11's printed override read first --
   and none of its runes, attachments or modifiers; a copy arrives with
   nothing and resolves no arrival effect; CardInstance.copy_of, None in
   an older save, is what the engine reads the card as while it stands.

3. The zones and the rules a player is put under. Jail (a starting
   building): an opposing unit played from the hand goes to it instead
   of arriving -- a slot on the building's instance -- and the next
   releases the last, which arrives then with its trigger and its
   fatigue; a boost is paid as the unit is played and resolves as it
   leaves; the jailed unit is discarded with the Jail; a forecast unit
   and a summoned one never go there (the ruling). Censorship Council
   (one card from the hand per turn for the opponent, hires aside, an
   effect's put-into-play aside); Reputable Newsman (CHOOSE_NUMBER, a
   new kind at its arrival, a menu of 0 to 20 since twenty-one numbers
   do not fit two rows: no opposing spell or upgrade of that cost while
   it is held); Building Inspector (the opponent's first building each
   turn costs 1 more, a rebuild's 0 becoming 1); Free Speech (silence:
   the opponent's heroes, in play and summoned meanwhile, cast nothing
   and have no ability -- printed, band or granted -- until after that
   opponent's next turn; they still level and heal at a band -- a
   modifier on the PlayerState with its end, false in an older save);
   Moment's Peace was step 11's; Oathkeeper's oath (OATH, a new kind at
   its arrival, two buttons: no card from the hand but a worker's, or
   no draw phase; held while it is in play, an effect's put-into-play
   allowed, the FAQ); Morningstar Pass and Setsuki's first band (a gold
   to attack it or her, charged by declare_attacker and refused
   without it; Setsuki's while she is not patrolling); Lawbringer
   Gryphon's base with flying (may_be_attacked for a base; gone when
   it leaves); Mindparry Monk (no opposing target on its controller's
   units or heroes); Eyes of the Chancellor (the opponent plays with
   their hand revealed: the one standing reveal -- RulesEngine
   .hands_visible_to(seat), read by My hand and /codex hand, which
   picture the other hand under the owner's for the Eyes' controller
   alone, and nowhere else).

4. White's effects. Starters: Aged Sensei's +1 ATK and +1 armor, Fox
   Primus, Fox Viper, Grappling Hook (a patroller to an empty slot of
   its zone, over any between, the FAQ), Morningstar Flagbearer, Safe
   Attacking (+1 armor to the controller's tech 0 and I attackers per
   attack, lost after each, the FAQ), Savior Monk, Sensei's Advice (up
   to two), Smoker (targeted, to its owner's hand before the effect),
   Snapback (an opposing hero to its command zone with two summoning
   runes; another hero of that zone into play, runes or none, theirs
   removed -- the same hero where there is no other). Strength: Ardra's
   Boulder, Bird's Nest (channeling; two Birds, limit 2 across nests;
   lost Birds re-summoned at upkeep to the limit; a second Nest two
   more at once, the FAQ), Colossus, Doubling Barbarbarian (every gain
   of ATK, HP or armor doubled, a +1/+1 rune +2/+2, the squad leader's
   armor 2, temporary bonuses too, the FAQ), Earthquake, Entangling
   Vines (attached to a patrolling unit: sidelined, no attack, no
   patrol), Hero's Monument (untargetable; Daigo Stormborne, an 8/8
   legendary token indestructible, untargetable and unstoppable that
   cannot patrol, trashed with the Monument; heroes +1/+1), Morningstar
   Pass (no damage to the controller's other buildings), Mythmaking,
   Oathkeeper (swift strike, resist 2; 2 gold: every patrolling unit
   sidelined), Rambasa Twin (arrives: may put the other Twin from the
   codex into play; the first Twin to die each turn returns to its
   owner's codex -- a card back into the binder), Thunderclap (up to
   three non-flying units costing 2 or less sidelined, tokens costing
   0), Training Grounds (+1 ATK to heroes; its exhaust levels a hero to
   max), True Power of Storms (two other cards costing 3 revealed and
   discarded from the hand -- named, since revealed -- then 10 damage),
   Whitestar Grappler (4 to a unit; the survivor deals its ATK back;
   sidelined if patrolling). Ninjutsu: Flying Fox, Fox's Den School
   (invisible; a unit made a Ninja for good, the FAQ), Fox's Den
   Students (four Ninjas; the controller's Ninjas haste and stealth
   this turn), Fuzz Cuddles, Glorious Ninja, Hidden Ninja (a card where
   either is a Ninja or the Ninjutsu hero), Inverse Power Ninja (-1/-1
   per other unit or hero of its controller's), Jade Fox (four Ninjas;
   Ninjas flying and swift strike, herself included, not Setsuki),
   Jefferson DeGrey (every token destroyed), Masked Raccoon, Porcupine,
   Shuriken Hail, Speed of the Fox (the Ninjutsu hero: haste,
   readiness, armor piercing, +1 ATK). Discipline: Focus Master (three
   focus runes; one prevents 1 where a friendly unit or hero would take
   exactly lethal damage -- deathtouch's one is lethal, more is not,
   and never for overpower's or Stampede's excess, the FAQ), Martial
   Mastery (discard, two cards, then look at the opponent's hand --
   pictured to the caster alone; not discarded until done), Mindparry
   Monk, Reversal (3 to a patroller, then disabled), Sparring Partner
   (its exhaust for a +1/+1 rune; 2 gold readies it to spar again and
   it may not attack this turn), Versatile Style (MODE_CHOICE of four:
   an upgrade destroyed, a flier disabled, 2 repaired, the Discipline
   hero a detector this turn), Vigor Adept, Young Lightning Dragon (a
   gold for +1 ATK, three times a turn). The heroes: Rook (unstoppable
   past a patrol zone of one; two lives), Grave (sparkshot; readiness;
   at max a sword rune, and his exhaust with it destroys a unit or
   hero -- after an attack, not during, his ruling), Setsuki (the gold
   to attack her; attacks: swift strike this turn; two cards at
   upkeep).

5. Blue's effects. Starters: Arrest, Bluecoat Musketeer, Building
   Inspector, Jail, Lawful Search (a card, then a look at the
   opponent's hand or their discard pile -- MODE_CHOICE, pictured to
   the caster alone), Manufactured Truth (one of the caster's tech 0
   or I units a copy of another until the end of the turn), Porkhand
   Magistrate (a gold and its exhaust: a unit or hero disabled, never
   itself, its controller draws), Reputable Newsman, Spectral Aven,
   Traffic Director. Law: Arresting Constable, Censorship Council,
   Community Service (a look at the opponent's hand or discard pile,
   then a tech I or II unit from it into play under the caster's
   control -- a TARGET over what was looked at), Flagstone Garrison (a
   card per unit played from the hand), Free Speech, General's Hammer,
   Guardian of the Gates (no attack; what it deals combat damage to is
   disabled, armor or not, itself never), Injunction (a tech I or II
   building disabled -- not operational next turn, no tech II built on
   a disabled tech I nor a tech III on a disabled tech II, the FAQ --
   and every unit of that player's at its level, whatever their spec),
   Insurance Agent (an insurance rune tied to the Agent that placed
   it, the Agent's controller gaining the unit's printed cost in gold
   and a card when it dies, sacrificed included, trashed or bounced
   not; two Agents twice; Plague Lab's copy inert; an Illusion dies
   before the rune lands, the FAQ), Judgment Day (the one ultimate
   playable by a max-level Law hero whatever the turn he arrived or
   maxed: every tech 0, I and II unit destroyed), Jurisdiction (a
   non-ultimate spell from the caster's codex, paid and discarded; a
   channeling one discarded at once without its hero), Lawbringer
   Gryphon, Patriot Gryphon (a building destroyed: its ATK to that
   base, beside the 2), Tax Collector (steal 1), Overeager Cadet.
   Peace: Air Hammer (+2 against a damaged building), Boot Camp (a unit
   or a non-Peace hero exhausted with a rune, sidelined; a card), Brave
   Knight (readiness; dying of combat damage -- sparkshot's, overpower's,
   deathtouch's, the tower's and rune damage included -- to its owner's
   hand instead), Debilitator Alpha (-1 ATK to what attacks it as squad
   leader), Drill Sergeant (a rune per unit played from the hand; a
   rune moved), Elite Training (+1 ATK, +1 armor, anti-air and
   sparkshot to up to two until the caster's next upkeep), Flagstone
   Spy (invisible; combat damage to a building: a look at that hand,
   pictured to its controller alone, and a gold stolen), Justice
   Juggernaut, Scribe (a card), The Art of War (the Peace hero
   unstoppable, swift strike, +2 ATK and +2 armor until the next
   upkeep), Onimaru's max (three Soldiers with sparkshot). Truth:
   Dreamscape, Hallucination, Liberty Gryphon, Macciatus, Mind Control
   (an ultimate ongoing spell attached to a tech 0, I or II unit: the
   caster controls it while attached, the owner again when it leaves;
   taken by Assimilate, the unit with it; Kidnapping over it returns
   to the Mind Controller), Reteller of Truths (the first two non-token
   Illusions of its controller's to die each turn, itself included, to
   their owner's hand, their death effects resolved), Spectral
   Flagbearer, Hound, Roc and Tiger, Sirus Quince (a Mirror Illusion on
   arriving and another for 2 gold, limit 2 across Mirrors and what
   they became; his second band: a Mirror becomes a copy of a tech 0, I
   or II unit -- type, tech level and all, still an Illusion, once per
   Mirror per turn -- trashed at the end of the turn; his max: as a
   non-token unit of his controller's arrives, a Mirror may copy it,
   trashed when Quince or the original leaves; Mirrors that copied
   nothing stay when he leaves, his rulings). Bigby: stash, the
   sideline, a card for his exhaust.

6. The last of the tables. tests/test_codex_effects.py asserts
   UNIMPLEMENTED empty over every card in the data, and the file's
   count of the sets is the whole catalog; tests/test_codex_card_rulings.py's
   CARD_RULINGS is every ruling in rulings.json; tests/test_codex_keywords.py's
   tables cover the whole General group, so EveryRulingIsPinnedTests
   counts every ruling the data holds and a re-import that adds one
   fails loudly. Every remaining "lands with step 13" or "the standard
   game" comment in codex/ and cogs/codex* is resolved or deleted, and
   docs/design/codex.md's opening paragraph says the bot plays the
   whole game. CLAUDE.md's row for codex/ loses "the basic game" where
   it says it; nothing else there changes.

Tests: tests/test_codex_keywords.py pins the General rulings of
illusion, stash, arrival_fatigue, detector and flagbearer, whichever
are not yet pinned (ten today); tests/test_codex_card_rulings.py every
ruling of the White, Blue and Heroes groups on the pair (79 and 13
today, counted by the file); tests/test_codex_spells.py each spell's
happy path and refusals; and the scenarios: Bigby's stash ending with
the same hand size as the draw without it, a boosted unit jailed and
released, Quince's copies and his limit of two, Free Speech's silence
through a level-up and a summon, Brave Knight under deathtouch,
Injunction on a tech I with the tech III still buildable, Eyes of the
Chancellor's reveal reaching the Eyes' controller alone and never the
channel (tests/test_codex_cog_turn.py), Oathkeeper's second oath
through a draw phase, Reputable Newsman's number refusing a spell,
Lawbringer Gryphon's base against a ground attacker, Rambasa Twin back
in the codex, Snapback on a hero with summoning runes, Two Lives in the
technician slot, a Spectral Flagbearer forced and dying of it, Mind
Control taken by Assimilate. Read every new line of the transcripts
for hidden information: a hand looked at, a discard pile searched and
a stashed card are pictured to one player and named to nobody.

Record in docs/design/codex.md, a section "White and blue" after
"Purple and black": the illusion and the copy, the jail, the silence,
the oath, the number, the stash, the one standing reveal and how it
reaches one player, the attack that costs gold, the base that flies,
the saved fields with their fallbacks (copy_of, the jail's slot, the
silence, the oath, the number, the crumbling, focus, insurance and
sword runes); and the opening of the note rewritten: the bot plays
Codex whole, every printed card, the basic game and the standard one.

Done when: every printed card has a handler or a keyword, every ruling
in the data is a test, UNIMPLEMENTED is empty and the table has no
next spec to wait for, and the full-game tests still end a game -- one
of them white against blue.

Stop: every printed card plays: the Whitestar Order against the
Flagstone Dominion on the test server, the author on one side, a unit
of theirs jailed and a stash kept, with the lobby offering all twenty
heroes and nothing refused that the rulebook allows.
```

## What is not in these prompts, on purpose

- **The standard game and the six colours, in steps 1 to 9.** They
  are steps 10 to 13, in the order the author gave on 2026-10-08 --
  the standard game's rules first, then red and green, purple and
  black, white and blue -- with prompts written on 2026-10-09, once
  step 9 had landed. Everything in steps 1 to 9 is written so that they fit: the seats by
  spec, the add-on as data, the hero as a list later, every colour's
  data and art imported at step 1. Nothing in steps 1 to 9 builds them.
- **An AI opponent.** Decision 13. The first one worth writing is a
  random legal player for the tests, not an opponent.
- **Maps, free-for-all and two-headed dragon.** Deluxe variants and
  multiplayer; nothing in the state assumes two players except the
  seats, and nothing is built for more.
- **A web page or a Godot client.** `codex/wire.py` exists from step 2
  so that one costs nothing here; no client is written.
- **Statistics and an archive export.** The author, 2026-10-07: not
  for this bot. The event log stays in the save, a finished channel is
  moved to the Codex Archive category, and nothing is written from it
  or read out of it.
- ~~**The finer undo, to any action of a turn.** Its infrastructure --
  the turn-start snapshots and the journal with its recorded random
  outcomes -- is in from step 2, and the two coarse undos are step 4;
  the finer one is a view and a service method over the same journal,
  later.~~ Built on 2026-10-10, outside the steps: docs/design/codex.md,
  "The undos".
- ~~**A cloud routine for the series.** Eight steps; claim by hand.~~
  The author asked for one on 2026-10-08; "Claiming a step" has it.
- **A test of how the board looks.** The author's rule for everything
  rendered: render it and look.
- **Moving fool-bot's `/roll`, the coins or the Tethys deck.** They are
  fool-bot's, and question 7 is built as no.
- **A rulebook of our own.** The bot cites a page; it does not reprint
  one.

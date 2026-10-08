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
  base. The patrol slots (p. 10): squad leader armour 1, elite +1 ATK,
  scavenger a gold when it dies, technician a card when it dies, lookout
  resist 1. Exhausted cards cannot patrol; cards with arrival fatigue
  can. Armour refreshes at the start of each turn. Flying, anti-air,
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
  armour refreshing, frenzy, healing, resist, haste.
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

- **The rulebook** (`Codex_UMR_v13w.pdf`, 24 pages): the rules, a
  glossary of every keyword, and a card FAQ -- Dean Ray Johnson's
  compilation of Sirlin Games' manual and Chris Franka's rulings
  document, under fair use. Its rules become code; its words are not
  ours to bundle. The page numbers above are the only thing the plan
  takes from it verbatim.
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
   Pillow in `asyncio.to_thread`. **The board is the game's own art**
   (the author, 2026-10-08: card art wherever possible, and the board
   art from screentop.gg): each side is the Screentop module's playmat
   -- the hero slots, the five labelled patrol slots with their bonuses
   printed, the add-on slot, the base, the Tech I, II and III places,
   the workers area, the draw and discard piles -- with the game laid
   on it where the mat has a place for it: the hero as its own card
   with its level chit, patrollers in their slots, the built tech
   buildings and add-on as the module's tiles with their damage, the
   draw pile as the card back with its count, the discard and the
   workers as counts, and the play zone's units as the cards' own
   pictures across the mat's open middle, each carrying its damage and
   rune chits, turned sideways when exhausted and marked when it
   arrived this turn; the gold, hand and codex counts in a strip. The
   two mats are **stacked** -- the table seen from the active player's
   side, their mat below and the other player's above it, turned round
   to face them (the author, 2026-10-08) -- or **side by side**, and a
   button on the turn message swaps the game
   between the two (the author, 2026-10-08); the layout is the game's,
   kept on the record, so everyone sees the same picture. Nothing is
   drawn that the module or a card already shows. After every action the
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
    same journal, and it is on the list of what is not built yet.
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
    database. No rulebook text is bundled and `docs/living-rules.md` is
    not touched: Codex's rules are not ours to keep, and nothing in the
    bot wants a second copy of them. The bot words its refusals itself
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
   for all twenty specs comes in at step 1; the colours are steps 9 to
   12, after the basic game.

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
| 5 | The keywords | medium | Eggship flies over a patrolling Leaping Lizard and takes its damage; every keyword ruling of the set is a test |
| 6 | Triggers, spells and the ongoing spells | large | every card of the set does what it says; `UNIMPLEMENTED` is empty |
| 7 | Finishing a game: concede, abandon, rematch, the golden | small | a finished game ends cleanly, offers a rematch and is moved aside; a seeded whole game is pinned byte for byte |
| 8 | The look back: what turned out identical moves to one home | small | nothing copied in steps 1 to 7 remains byte-identical in two places |
| 9 | The standard game's rules, over the red and green data | large | three heroes a side, a spec chosen at Tech II, the heroes' hall and the tech lab built, a red team against a green one with every card still played for its numbers |
| 10 | Red and green: every card does what it says | large | `UNIMPLEMENTED` empty again; Calamandra against Jaina, the Core Set's own first game |
| 11 | Purple and black | large | the same for the Vortoss Conclave and the Blackhand Scourge |
| 12 | White and blue | large | the same for the Whitestar Order and the Flagstone Dominion; every printed card plays |
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
happen and what is not expected to work yet. A step whose section has
no prompt (9 to 12, until the author writes them) stops the routine
with a report, never a guess. A PR it opened that is closed without
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
   into the discard, everything readies, armour and
   max_level_since_turn_began recorded -- then upkeep: gold per worker
   to the cap, a summoning rune off the hero; end_main; draw_phase: the
   hand to the discard face-down, draw_count drawn with the
   once-a-phase reshuffle; begin_tech: tech_owed set, the turn passes),
   actions.py (hire_worker, summon_hero, level_hero(n), play_card for
   a unit or a spell -- a spell in this step is paid, discarded and
   does nothing, since it is in UNIMPLEMENTED -- construct, lock_patrol
   with the slot assignment), combat.py (declare_attack(attacker,
   defender): exhaust, the elite's +1, armour, simultaneous damage,
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
   bonus, the squad leader's armour refreshing. tests/test_codex_prompts.py:
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
   the hero as its card in the first hero slot with its level chit, or
   the slot empty while it is in the command zone, its summoning runes
   as chits; the patrollers as their cards in the five labelled slots;
   the Base, Tech I, II and III tiles and the add-on card from the
   module's sheet in their places, each with its damage chits and a
   mark while under construction, the unbuilt ones faint; the draw pile
   as the card back with its count, the discard as its count, the
   workers as a count on the workers area; the play zone's other units
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
asserts a picture of the expected size for the opening position (the
board WebP since 2026-10-08, the hand and codex PNG) and nothing
about its look. On startup the cog re-arms the persistent views the
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
   "nothing is patrolling") -- in the same panel, with Cancel back to
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
   readiness (no exhaust on attack, one attack a turn); armour (the
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
   armour), Wrecking Ball, The Boot (a tech 0 or I unit; dies, so the
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

### 7. Finishing a game: concede, abandon, rematch, the golden

What a game needs after its last turn, and the safety net under
everything before it. No statistics and no archive export for this bot
(the author, 2026-10-07): a finished game's channel is moved out of the
way and nothing is written from it.

```text
Step 7 of docs/codex-bot.md. Steps 1 to 6 have landed. Also read
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

### 8. The look back: what turned out identical moves to one home

Decision 2's second half. With two games running, the generic and the
particular can finally be told apart by diffing them.

```text
Step 8 of docs/codex-bot.md. Steps 1 to 7 have landed. Also read
docs/design/cog-structure.md and docs/design/game-service.md.

Diff, pair by pair, what steps 1 to 7 copied: codex/flow/result.py
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

### 9 to 12. After the basic game

The author's order, given on 2026-10-08: all six colours, two at a
time -- red and green first, then purple and black, then white and
blue. The standard game's rules come first because a colour is three
heroes, and three heroes a side is the standard game: the hero limit
and the heroes' hall, the spec chosen at Tech II and the tech lab, the
starting deck's colour, the multicolour penalties (UMR p. 4, 6, 8, 9)
-- and the Codex button's menu gains a view per spec of the player's
three, since a seventy-two card codex is three binders (the author,
2026-10-08). Step 9 builds those rules over the red and green data
with every card
still played for its numbers, so the standard game is playable before
a single red or green effect exists; step 10 gives red and green their
effects and rulings, the way steps 5 and 6 did for the neutral set,
and lands on Calamandra against Jaina, the Core Set's own first game
(UMR p. 3); steps 11 and 12 repeat step 10 for the other two pairs.
Their prompts are written when step 8 lands, in the shape of steps 5
and 6, from the design note as it stands then. Nothing in steps 1 to 8
builds any of it, and everything in them is written so that it fits.

## What is not in these prompts, on purpose

- **The standard game and the six colours, in steps 1 to 8.** They
  are steps 9 to 12, in the order the author gave on 2026-10-08 --
  the standard game's rules first, then red and green, purple and
  black, white and blue -- with prompts written when step 8 lands.
  Everything in steps 1 to 8 is written so that they fit: the seats by
  spec, the add-on as data, the hero as a list later, every colour's
  data and art imported at step 1. Nothing in steps 1 to 8 builds them.
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
- **The finer undo, to any action of a turn.** Its infrastructure --
  the turn-start snapshots and the journal with its recorded random
  outcomes -- is in from step 2, and the two coarse undos are step 4;
  the finer one is a view and a service method over the same journal,
  later.
- **A cloud routine for the series.** Eight steps; claim by hand.
- **A test of how the board looks.** The author's rule for everything
  rendered: render it and look.
- **Moving fool-bot's `/roll`, the coins or the Tethys deck.** They are
  fool-bot's, and question 7 is built as no.
- **A rulebook of our own.** The bot cites a page; it does not reprint
  one.

# The Transformers TCG bot: a third bot from the same repository

**This is a worksheet, not a specification.** It was written on
2026-10-14 from the author's ask -- a third Discord bot, run from this
repository beside fool-bot and the Codex bot and modelled on both, that
plays the *Transformers Trading Card Game* (Wizards of the Coast,
2018-2020; continued by its community since) -- against what the
repository already has (two bots over one model/Discord split, the
shared `gamekit/` and `botkit/`, `GameBot` and `botlog`, the board gate,
the deploy scripts) and against the four links the author gave:
transformers.cards' rules page, teletraan1.net's card list, the fandom
wiki's *How to Play (Basic Rules)*, and transformers.cards' public
decks. One of the four turned out to be a database of a different game
(below, "What the four links give"). Each step below has a prompt a
Claude Code session is started with. Strike a step when it lands and
move what it settled into `docs/design/tftcg.md`, the design note step 1
creates. **Nothing in it is a rule.**

## What was found, and what it settles

### The game, in the terms the code will use

The starter set is the plan's scope: the *Bumblebee vs Megatron Starter
Set* (Wave 2S), two teams of two characters and one forty-card battle
deck, which the bot deals to both sides. Everything below is what that
game asks of an engine, read from the rules as transformers.cards
carries them -- *Rules 1.0* (`/rulesbasic`, Wizards' rules sheet in six
numbered sections, cited `R1 §n`) and *Expanded Rules 2.0*
(`/rulesexpanded`, nine numbered sections, cited `ER §n`: the Aequitas
Committee's expansion of Wizards' rules, the same text
transformerstcg.org carries as "Rules") -- from the wiki's basic and
advanced pages, and from the cards.

- **A player's things.** A team of characters, each a card with two
  faces, alt mode and bot mode, each face its own Attack, Defense,
  Health, traits and text; the face up is the character's mode, and
  the game starts in alt mode (R1 §1.3). A battle deck of at least forty
  battle cards -- Actions and Upgrades, no more than three of a name --
  face down, drawn from and flipped from the top. A hand, three cards at
  the start. A scrap pile, face up, where used cards go, which both
  players may look through. A played area, where this turn's Actions
  and a battle's flipped cards lie until the end of the turn. A KO area
  for characters knocked out. Damage counters on characters, kept
  between turns. Each character tapped or untapped; three Upgrade slots
  a character, Weapon, Armor and Utility, one of each, the old one
  scrapped by the new (R1 §1.4; ER §7). Stars on characters, on some
  battle cards and on stratagems, 25 at most a team (R1 §1.1).
- **The five phases** (ER §1). *Start of the turn*: draw a card, then
  the start-of-turn abilities. *Main phase*, in any order, each at most
  once: flip one character to its other mode; play an Action (a Secret
  Action face down); play an Upgrade onto a character; use one untapped
  character's tap ability. On the first turn of the game the first
  player plays nothing from hand; on the second the other player plays
  an Action or an Upgrade, not both (ER §1.2). *Attack*, the turn's
  required one if any character is untapped: choose combatants -- an
  untapped attacker, tapped as it is chosen; a tapped defender, or any
  defender when none is tapped; the abilities of choosing -- then flip
  battle cards -- each side's count locked first (two, plus Bold or
  Tough); the attacker's flips, with any "before flipping" ability such
  as Focus before them, each card's icons applied as it turns, a white
  icon flipping two more once; then the defender's the same way -- then
  attack damage: Attack less Defense, Pierce a floor capped by the
  Attack, the modifiers the attacker's first then the defender's, the
  counters, the KO (ER §1.3). *Post-attack*: after-attack abilities with
  the green swaps among them; an extra attack if one is owed; then the
  turn's rhythm -- the attacking player attacks again while the defender
  has no untapped character and they have one ("attacking out"), and
  when every character on both sides is tapped, all untap (ER §1.4).
  *End of turn*: the end-of-turn abilities, the played area to the scrap
  pile -- the defending player's unrevealed Secret Actions among it,
  face up and without effect -- the until-end-of-turn effects worn off,
  and again until nothing is pending (ER §1.5).
- **The battle icons** (R1 §1.5; ER §1.3.2): orange +1 Attack to the
  attacker; blue +1 Defense to the defender; white, two more flips the
  first time a player flips one in a battle; black, Pierce 1 to the
  attacker until the end of the battle; green, a swap after the attack
  -- a card from hand for the green card flipped. A card carries up to
  three. Hybrid icons (Wave 5 on) count only with the matching trait.
- **The keywords in the set.** Bold X and Tough X, X more flips
  attacking or defending, adding together; Pierce X, at least X damage,
  never more than the Attack, adding together; Plan X, up to X cards
  from hand back on top of the deck in any order, a "may"; Stealth,
  enemies attack other characters if able (ER §6; the site's keyword
  rulings). Focus, Brave and Safeguard are step 5's and no card of the
  set's.
- **Triggered abilities** (ER §3, §4): "When [condition] → [effect]".
  The effect follows the condition at once, or, when the condition is an
  Action or an Upgrade being played, after that card finishes; several
  at once resolve the attacking (active) player's in their order first,
  then the defending player's in theirs; an ability that triggers while
  another resolves goes first; a trigger resolves though its source has
  flipped, left or been KO'd. Actions within Actions (ER §2) and
  Upgrade play (ER §7) follow from it.
- **Shuffling** (ER §5): an empty deck is the scrap pile shuffled, at
  once, at any time -- except the cards an Action or ability scrapped
  earlier in its own resolution, which wait in the scrap pile until it
  is done.
- **Who decides.** The active player makes most decisions. The
  defending player decides what is theirs: the order of their own
  simultaneous triggers and the choices inside them -- Security
  Console's Plan when its character defends -- their Focus, their green
  swap, whether to reveal a Secret Action (optional, by Wizards' ruling
  of 2019), and every "your opponent chooses". So a turn asks both
  seats, the way D12 Ball's defender is asked and Codex's never is.
- **The three post-cancellation changes** (transformers.cards, "New
  Rules"; transformerstcg.org, "Post-Cancellation Rules Changes"): the
  Pierce from black icons ends with the battle, not the turn; an "any
  number" of damage counters moved cannot exceed the receiver's
  remaining Health; two opposing changes to icon colours cancel and the
  icons keep their printed colour. They are rules of the continuing
  game, and the engine's.
- **The game ends** when a player's characters are all KO'd, or a
  card's win condition is met (ER §1.6); face-down Secret Actions are
  revealed then. The first player is random, and the next game switches
  (R1 §1.3).

### The twenty-five cards of the starter set, and what each asks

Read from transformers.cards on 2026-10-14 (the site's deck
`Bumblebee Vs. Megatron Starter Set`, and each card's page). A
character's face is `ATK/DEF/HP`; a battle card's icons are in
brackets; `(T)` marks a choice of target; `×n` is the copies in the
forty.

| Group | Card | What it asks |
| --- | --- | --- |
| Autobots | Bumblebee // Least Likely, Most Dangerous (`C2S01`, 7★): alt 3/2/9 Car, Melee; bot 3/1/9 Melee | Bold 1 in bot mode; nothing in alt |
| Autobots | Windblade // Defender of Truth (`C2S04`, 5★): alt 2/2/8 Plane, Ranged; bot 2/1/8 Ranged | When you flip to bot mode → Pierce 2 until end of turn: a flip trigger and a modifier for the turn |
| Decepticons | Megatron // Cybertronian Tyrant (`C2S02`, 7★): alt 2/2/10 Tank, Ranged; bot 3/1/10 Ranged | Bold 1 in alt mode; in bot mode, when you upgrade this → +1 Attack until end of turn: a trigger on an Upgrade being put |
| Decepticons | Starscream // Decepticon Lieutenant (`C2S03`, 5★): alt 3/1/7 Plane, Melee; bot 4/0/7 Melee | Tough 1 in bot mode |
| Actions | Pep Talk ×2 [blue] | Draw 2 cards |
| Actions | Equipment Enthusiast ×2 [white] | Draw a card for each of your Upgrades: a count over the battlefield |
| Actions | New Designs ×2 [orange] | You may play an Upgrade: a second Upgrade play, inside an Action, whose put-triggers wait until the Action is done (ER §7) |
| Actions | Strafing Run ×1 [none] | 1 damage to each enemy: no choice |
| Actions | Supercharge ×2 [orange] | One of your characters gets Bold 3 until end of turn (T) |
| Actions | Surprise Attack ×2 [white] | One of your characters gets Pierce 3 until end of turn (T) |
| Actions | Reckless Charge ×2 [orange] | +4 Attack until end of turn (T), and a delayed trigger: at end of turn, 3 damage to it |
| Actions | Rest and Relaxation ×2 [green] | Repair 1 damage from one of your characters (T) |
| Actions | Vaporize ×2 [blue] | Scrap an enemy Upgrade (T) |
| Actions | Inferno Breath ×2 [blue] | A cost -- tap one of your untapped characters with 5★ or more (T) -- then 3 damage to an enemy (T) |
| Actions | Leap of Faith ×1 [white], 1★ | Scrap the top card of your deck, you may play it; then again: a card played from the scrap pile, an Action within an Action (ER §2), an Upgrade play that is not the turn's, and a star card counting toward the limit |
| Weapons | Grenade Launcher ×2 [orange], +4 Attack | After the upgraded character attacks → scrap this: a post-attack trigger |
| Weapons | Primary Laser ×2 [blue], +2 Attack | Nothing: a vanilla Upgrade |
| Weapons | Handheld Blaster ×2 [blue, blue] | Bold 1: a keyword granted while attached |
| Weapons | Backup Beam ×2 [blue, green] | Bold 2 |
| Weapons | Enforcement Batons ×2 [orange, green], +1 Attack | When you put this on a character → scrap an enemy Weapon (T), mandatory while there is one |
| Armor | Armored Plating ×2 [blue], +1 Defense | Nothing: a vanilla Upgrade |
| Armor | Improvised Shield ×2 [orange, orange] | Tough 1 |
| Armor | Sparring Gear ×2 [orange, green] | Tough 2 |
| Utilities | Security Console ×2 [white] | When the upgraded character defends → draw a card, then Plan 1: a trigger of the *defender's*, in the middle of the opponent's attack, with a choice from a hidden hand |
| Utilities | Stealthiness ×2 [orange] | Stealth: a static that changes who may be chosen as the defender |

Two Upgrades have no text, and one Action asks nothing; the rest is
text. As with Codex there is no "vanilla deck" to start from, so the
steps start from a vanilla *engine*: one that plays every card for its
numbers -- a face's three numbers, an Upgrade's bonus, every icon, and
the three battle keywords Bold, Tough and Pierce, which are numbers on
the card -- ignores the rest of its text, and says so, in one table the
suite pins (`UNIMPLEMENTED`) that empties by step 6. Nothing is ignored
silently.

**The mechanics, grouped the way the steps take them.**

- *The turn and the deck* (step 2): the shuffle, the hand of three, the
  draw, the scrap pile and the reshuffle; modes and the one flip; tap
  and untap; the three plays of the main phase and the first two turns'
  restrictions; Upgrades in their slots with their printed bonuses, the
  old one scrapped; the attack -- attacker, defender by the tapped rule,
  the flips with their locked count, the orange, blue, white and black
  icons, Bold, Tough and Pierce, damage, KO; extra attacks and attacking
  out; the untap of all; the end of turn's cleanup; the game's end.
- *The battle's fine print and the keywords* (step 5): Focus, Plan,
  Brave, Stealth and Safeguard; the green swap; white's two more exactly
  once; hybrid icons as data; the ordering of triggers and the pending
  rule; Secret Actions as a shape, since the set has none but Wave 3
  will; the shuffle's exception; the three post-cancellation changes.
- *The effects* (step 6): the triggers -- on a flip, on an Upgrade put,
  when this defends, after this attacks, at end of turn; the costs (a
  tap); the targets, "an enemy", "one of your characters", "an enemy
  Upgrade"; the nested plays (New Designs, Leap of Faith); modifiers
  until end of turn and until end of battle; keywords granted by an
  Upgrade; the statics (Stealth); counts.

### Hidden information, and the questions a defender is asked

Codex settled the hidden hand on Discord: an ephemeral panel for the
active player, pictured, and one public message per turn. This game
keeps that and adds two things.

- **What is hidden, and whose it is.** The hand is its owner's. The
  deck's order is nobody's -- until a Plan, a Focus or a "look at the
  top card" shows it to one player, who then knows it. The scrap pile
  is public both ways, by the rule, so either player may ask to see
  either pile. The KO area, the battlefield, the Upgrades and the
  played area are public, a Secret Action face down in it being its
  owner's. "Look at your opponent's hand" (Disruptive Entrance, Wave 1)
  shows one player the other's hand. The battle's flips are public as
  they happen -- they are the game's dice.
- **The defender is asked in the middle of the attacker's turn.** In
  the starter set alone: the green swap after an attack is each
  player's for their own green flips; Security Console's Plan is the
  defender's, with a card from their hand. Later sets add Focus on
  defense, Secret Action reveals, "your opponent chooses" and the order
  of a defender's own triggers. D12 Ball asks its defender through a
  public prompt with a mention; Codex never asks the other seat
  mid-turn. This bot needs both shapes: the panel for the active player,
  and a public ask for the other seat (decision 8).
- **The flips are the dice.** D12 Ball's rule that nothing rolls on its
  own, every roll waiting behind a button, is a rule about a shared
  moment. Here the randomness was spent at the shuffle, and a flip is
  deterministic once the deck is ordered; what is shared is the moment
  the cards turn, and what sits before it is each player's decisions
  (Focus, a held Secret Action). Decision 9 says where the button is.

### What the four links give -- and the one that is a different game

- **transformers.cards** (Z-R0E's site, the home of the *Allied
  Crossplay* continuation). The rules: *Rules 1.0* (`/rulesbasic`,
  Wizards' sheet, §1.1-1.6), *Expanded Rules 2.0* (`/rulesexpanded`,
  §1-9: the turn, Actions within Actions, triggered abilities and their
  ordering, shuffling, duplicate keywords, Upgrade play, stratagem
  targets, errata), the tournament rules, the three post-cancellation
  rules, Wizards' Wave FAQs, and forty-odd *Rules Roundups* from
  2018-10-11 to 2026 -- Wizards' through 2020, the Aequitas Committee's
  and the site's after -- every ruling tagged to a keyword, a mode, a
  trait, a term or a card (`/rules/keyword/Bold`, `/rule/<id>`). The
  card database: 1,223 cards on 2026-10-14 -- 441 characters, 623
  battle cards, 159 stratagems -- each at `/card/<code>/<slug>` with
  its wave and number, rarity, stars, each face's Attack, Health and
  Defense, its traits and text with the glyphs as pictures (the arrow
  `🠪`, the stat marks, the trait marks, the icons), its battle icons
  (three slots, blank where empty), a thumbnail per face
  (`/images/thumbnails/<code>_<n>.jpg`) and a full picture, the
  rulings tagged to it, and the decks using it; the listings
  (`/cards`, `/characters`, `/battle`, `/stratagems`) carry the same
  facts in one table each. The downloads: every wave as a PDF and as a
  ZIP of card images with bleed. An OCTGN game package on the site's
  own MyGet feed (`https://www.myget.org/F/teletraan`): one package,
  "Transformers TCG Continuation", version `26.09.26.15` of
  2026-09-26, 73 MiB, by Z-R0E, "all cards on Transformers.cards,
  including community sets" -- which, if it is what an OCTGN package is,
  holds every set's `set.xml` with every card's properties and every
  card's picture: the one structured source, not downloaded for this
  plan (step 1 looks). A Tabletop Simulator mod. The decks: public
  (`/decks/public`, hundreds), tournament, and nine pre-constructed
  (`/decks/precon`): the *Bumblebee Vs. Megatron Starter Set*, the
  *Metroplex*, *Devastator*, *Blaster* and *Soundwave* sets, and four
  three-character starters of the site's own -- *Thunderbee*,
  *Battlechargers*, *Timecop*, *Stormtrigger* -- plus the co-operative
  *Unicron Raid*; each deck at `/deck/<id>/<slug>` with its characters,
  its battle cards by type with counts, its stars and sideboard, and
  an export to OCTGN's `.o8d` (`/export?dl=octgn&deck=<id>`), to
  Tabletop Simulator and to PDF. The ban list (`/banned`): nine banned
  cards and seven banned-with-replacements. The site is the author's
  link and the plan's source for cards, rulings, decks and art.
- **The wiki** (transformerstcg.fandom.com): *How to Play (Basic
  Rules)* and *(Advanced Rules)*, rewritten to the current game, with
  the three post-cancellation changes; the teaching text, which adds
  nothing the site lacks, and which points at transformerstcg.org as
  "the maintained rules".
- **teletraan1.net** -- "A Transformers DBG Website" -- is a database
  of the **Transformers Deck-Building Game** (Renegade Game Studios):
  Energon and Power, Robots, Maneuvers, Technology, Allies, Relics,
  Sites and Missions, the *Autobot Core Set* through *Chaos Unleashed*.
  A different game with nothing in common with the TCG but the licence.
  Nothing in this plan reads it; question 2 asks the author whether
  the link was meant.
- **The public decks** are the site's, above: what a deck is in
  practice (25★ with star cards and stratagems, forty-plus cards, a
  sideboard of up to ten in "Standard Play"), and the export that a
  deck import will read.
- **transformerstcg.org**, found through the wiki: a second community
  home (Team Bayformers' successor), with the same rules text under
  "Rules", a glossary of every term with an anchor each, Wizards' FAQs
  and roundups reproduced "under Hasbro's Fan Content Policy", the
  formats (*Full Constructed* over an Allowed/Banned/Replaced list),
  and its own numbered lineage -- *Org Wave 7: Monster Menagerie*
  remastered, *Org Wave 9: War|Void* in beta, *Org Wave 10* announced
  -- which overlaps transformers.cards' Waves 6 to 10 (*World Strike*,
  *Monster Menagerie*, *Waste Lands*, *Ark Exodus*, *CNA Augmentation*,
  *The Six Shadows*) in part. Two continuations, one ruleset. The plan
  takes transformers.cards' card pool and cites its rules pages, and
  question 3 asks the author which pool the bot should know.

### What the repository gives, and what it does not

Two bots stand on the model/Discord split (ARCHITECTURE.md), and the
Codex bot's look back (its step 9) left the shared leaves in `gamekit/`
and `botkit/`. The third bot imports those from its first commit and
copies Codex's shapes rather than D12 Ball's, because Codex is the card
game: a hand, a deck, a panel, a journal.

| D12 Ball / Codex | TF TCG | Shared, copied, or new |
| --- | --- | --- |
| `gamebot.py` (`GameBot`); `foolbot.py`, `codexbot.py` | `tftcgbot.py` | Shared as it is: twenty lines over `GameBot` with the extensions, the state file, the sync variable, no message content, the command-ids file |
| `botlog/` | the same package | Shared as it is: prefix `TFTCG`, name "TF TCG bot", its own state file; `TFTCG_LOG_*` falling back to `FOOLBOT_LOG_*` as `CODEX_LOG_*` does |
| `botstate.py`, `discord_emoji_cache.py`, `gamelocks.py` | the same modules | Shared as they are |
| `gamekit/` (`jsonable`, `MOVED_ON`/`STEP_OWED`, `Resolver`, `StopHandling`, `SavedField`, the games file's read and write) | the same package | Shared as it is -- the Codex look back's result; this bot copies nothing of it |
| `botkit/` (`slugify_channel_part`, `get_or_create_category`, `GameLockedView`) | the same package | Shared as it is |
| `cogs/game_auth.py` (the gates, the helper's confirmation, `send_new_prompt`) | the same module | Shared: the record spells `player_1_id` and `player_2_id` as both others do |
| `cogs/d12ball_boards.py` (`BoardRefresher`) | the same class | Shared: `keep_view`, `links`, `message_of`, `text_for`, `label` are the parameters the Codex bot made it take |
| `codex/components.py` (the `SavedField` tables) | `tftcg/components.py` | Copied shape: `MatchState`, `PlayerState`, and new, `CharacterState` -- a card with two faces, a mode, tapped, damage, three slots -- and `CardInstance` for an Upgrade attached or an Action played |
| `codex/game.py` (`CodexGame`, `RuleRefusal` citing a page) | `tftcg/game.py` (`TFTCGGame`) | Copied shape: the record, with team and deck legality as methods refusing with `RuleRefusal`, citing `R1 §1.1` and `ER §8` |
| `codex/engine.py` (`RulesEngine`, `rng`, the one shuffle) | `tftcg/engine.py` | Copied shape: every question the frontend asks; `rng` for the shuffle and the first player, and every flip and draw comes off the deck the shuffle ordered |
| `codex/prompts.py` (`pending`, `OPTIONS`, `standing_prompts`) | `tftcg/prompts.py` | Copied shape; a prompt's asked seat varies by kind, as D12 Ball's `asked_sides`; no standing prompt in this set |
| `codex/flow/` (the phases as steps, `resolve.py`'s effect stack, `driver.py`) | `tftcg/flow/` | Copied shape: the five phases and the attack's three steps as `FollowOnStep`s; the effect stack's frames are where Actions within Actions and pending triggers live |
| `codex/history.py` (snapshots, the journal, the three undos) | `tftcg/history.py` | Copied, then moved in step 9 where it proves identical; a journal entry records a shuffle's order, and a flip replays from it |
| `codex/effects.py`, `keywords.py`, `UNIMPLEMENTED` | `tftcg/effects.py`, `tftcg/keywords.py` | Copied idea: `EFFECTS` part by part, `TEXT` per card, the keyword table per face, each beside the printed sentence, and the set the suite pins |
| `codex/cards.py`, `scripts/import_codex_cards.py` | `tftcg/cards.py`, `scripts/import_tftcg_cards.py` | Copied rule: regenerated whole, never edited by hand; a card has faces, and a name has printings |
| `codex/tokens.py`, `CodexTokens` | `tftcg/tokens.py`, `TFTCGTokens` | Copied shape: `{icon:orange}`, `{attack}`, `{defense}`, `{health}`, `{tap}`, `{arrow}`, `{trait:car}`, `{faction:autobot}`, `{card:B2046}`, `{player:n}`, `{to:n}`; the cog draws, the model marks |
| `codex/render.py` | `tftcg/render.py` | New drawing over the imported faces: a character as its own face, turned when tapped, its Upgrades under it; the battle strip |
| `codex/wire.py` | `tftcg/wire.py` | Copied |
| `gamesaves/codex/service.py`, `storage.py` | `gamesaves/tftcg/` | Copied shape: one door, one save; `data/tftcg_games.json` |
| `cogs/codex/` (seven mixins), `present`, `render_prompt`, `view_for_prompt` | `cogs/tftcg/` | Copied shape: the one presenter, the one mapping from kind to view and picture, the turn message through the gate, the panel |
| `cogs/codex_views/` (`SafeView.apply`, the panel, `TurnMessageView`) | `cogs/tftcg_views/` | Copied shape; plus the public ask for the other seat, which is D12 Ball's `send_new_prompt` shape over Codex's views |
| `cogs/codex_helpers.py` | `cogs/tftcg_helpers.py` | Copied shape: the resolver, the channel name, the two categories |
| fool-bot's hub line for Codex | a second line | Copied: `</tftcg create_game:ID>` read from `data/tftcg_command_ids.json`, the name in plain text when the file is absent |
| `tests/codex_positions.py`, `tests/test_codex_golden.py`, `tests/codex_cog_fakes.py` | `tests/tftcg_*` | Copied ratchets; a position staged by card code |
| `scripts/run_codex_bot.ps1`, the slot in `deploy.ps1` | `scripts/run_tftcg_bot.ps1`, a third slot | Copied |

What the repository does not give: a card with two faces (every D12
Ball and Codex card has one); a public random draw that is the game's
dice, and its picture (D12 Ball's dice images are the nearest thing);
Upgrades attached in slots, with bonuses and granted keywords (Codex's
`attached` ids for an ongoing spell are a thin precedent); a question
to the seat that is not active in the middle of the other's turn, with
a hidden answer (D12 Ball asks its defender publicly; Codex asks the
other seat nothing but its tech choice); a deck a player brings (D12
Ball's teams and Codex's decks are the game's data; a deck list, its
legality and its import are new); and the application, which the author
creates in the Developer Portal.

## The decisions

These are the ones the plan is built on. Each is the recommendation and
its reason; the author overrules any of them by saying so on the PR,
and the step's prompt is rewritten rather than argued with.

0. **A third bot, with its own token, from this repository, modelled
   on the Codex bot and the D12 Ball bot, playing the Transformers TCG,
   the starter set first, one slash command to open a game and buttons
   after it** (the author, 2026-10-14). Everything below is under this.

1. **Its own process, its own token, its own files; nothing shared
   with the other two at runtime.** `tftcgbot.py` beside `foolbot.py`
   and `codexbot.py`, reading `TFTCG_DISCORD_TOKEN` from the same
   `.env`; its games in `data/tftcg_games.json`, its bot state in
   `data/tftcg_bot_state.json`, its command ids in
   `data/tftcg_command_ids.json`, its own pid and log files;
   `TFTCG_COMMAND_SYNC`; `TFTCG_LOG_*` falling back to `FOOLBOT_LOG_*`;
   `Intents.default()` with no message content. One application in the
   Developer Portal, the live one, and no test application beside it
   unless the author wants one this time (question 9). The entry
   point's name contains neither `foolbot.py` nor `codexbot.py`, so
   neither of the other runners stops it or counts it. **The package
   is `tftcg`, not `transformers`**: `transformers` is the name of a
   widely installed pip package (Hugging Face's), and a package of ours
   by that name would shadow it, or be shadowed by it, in any venv that
   ever has it; `tftcg` is what the community's own sites say. The
   slash group is `/tftcg` for the same reason, short to type, and the
   author may prefer `/transformers` (question 7). **What it costs:** a
   third runner script, a third slot in `deploy.ps1`, a third line in
   Task Scheduler, three processes to restart after a pull, and the
   emoji uploaded again to the third application.

2. **Share what is shared; copy Codex's shapes; look back once more.**
   `gamekit/`, `botkit/`, `gamebot.py`, `botlog/`, `cogs/game_auth.py`
   and `BoardRefresher` are imported from the first commit, with their
   tests untouched; nothing of them is copied. What is a *shape* --
   `GameService` and `GameResult`, `pending` and `PendingPrompt` and
   `Action`, `StepResult` and `FollowOn` and the driver loop, the
   effect stack, `history.py`, `SafeView`, the panel, the turn message,
   the storage module -- is copied from `codex/`, `gamesaves/codex/`
   and `cogs/codex*` into `tftcg/`, `gamesaves/tftcg/` and
   `cogs/tftcg*`, keeping the names. Step 9 is the look back: what
   turns out byte-identical between the Codex bot and this one --
   `history.py` is the likeliest, then the service's classes,
   `SafeView.apply`, the turn message's rollover and the ephemeral
   panel's plumbing, `picture_file` and `kept_pictures` -- moves to
   `gamekit/` or `botkit/` with the Codex tests passing unchanged and
   `codex/`'s module re-exporting the old name, as the first look back
   did. **What it costs:** duplicated code for a few weeks, and the
   step that removes it.

3. **The model/Discord split holds from the first commit.** `tftcg/`
   and `gamesaves/tftcg/` import no `discord`, define no `async def`,
   and import Pillow only in `tftcg/render.py`; `tftcg/flow/driver.py`
   runs every step and answers every action; the cog asks and renders.
   The ratchet in `tests/test_model_purity.py` covers the two new
   packages. A whole game plays through the driver with no frontend
   imported (step 2) before any Discord code is written (step 3).

4. **Hidden information goes through ephemeral interaction responses,
   never DMs; public information that is only large goes the same
   way.** The active player's main phase is driven from one ephemeral
   panel edited in place by each click, which pictures their hand; the
   other player's **My hand** shows their hand alone; a Focus or Plan
   look, a look at the opponent's hand, a Secret Action's own face are
   ephemeral to the one entitled to them. The scrap piles are public by
   the rule, and either player sees either pile ephemerally from a
   **Scrap** button, because a pile of thirty cards is not a message the
   channel wants. Nothing hidden is written to a public message, a log
   line or the #logs mirror; the event log holds card identities and
   stays in the save, since this bot writes no export (as Codex).
   **What it costs:** every entry point creates a fresh ephemeral
   message rather than finding an old one, as Codex's does.

5. **One public message per turn, carrying the board as a rendered
   image and the turn's lines as its text, edited after every action
   through the write gate.** An image, not an embed, as the author
   chose for Codex. When a turn begins the cog posts the turn's message
   -- "**Turn 7** -- @player (Autobots)" and the lines so far, with a
   mention that notifies the new active player -- and edits it after
   every action; when the turn ends it is edited a last time, pinned,
   and stands, the previous one unpinned. **The board is the cards
   themselves, drawn element by element** as Codex's is: each side a
   panel -- its characters in a row as their own faces from
   `tftcg/images/cards/`, the face up being the mode, a tapped one
   turned on its side at full size, damage drawn as chits on it, its
   three Upgrades tucked under it as small cards in the slot's place
   (Weapon left, Armor right, Utility below) with the slot's mark, a
   KO'd one in a greyed row beneath; the played area beside them --
   this turn's Actions face up, a Secret Action as a card back; a
   nameplate along the outer edge with the player, the faction, and
   DECK, HAND and SCRAP as a word and a count each. The two panels
   stacked, the far side turned to face the near one (the author's
   choice for Codex), or side by side under **Swap view**, the layout
   the game's, on the record. **The battle strip** is this game's
   addition: while an attack is in progress, between the two panels,
   the attacker's and the defender's faces with their flipped cards laid
   out in order with the icons that counted, and the arithmetic as the
   headline -- "Megatron attacks Bumblebee: 3 + 2 🟧 = 5 against 2 + 1
   🟦 = 3: 2 damage" -- the picture that goes between the lines, as D12
   Ball's dice do. After every action the message is edited with the
   new lines and the re-rendered board; a cascade of the bot's own
   steps -- the damage, the KO, the post-attack triggers, the untap --
   is one edit. **Rate limits:** one message per channel is edited
   through the gate; the panel is edited through its own interactions;
   the public asks of decision 8 are sends through `send_new_prompt`,
   not edits, and each is edited once, by the click that answers it,
   which is the click's own response and not the channel's bucket.
   **What it costs:** a render and an upload per edit, and a renderer
   to write and look at.

6. **The cards are data imported from transformers.cards, never
   typed.** `scripts/import_tftcg_cards.py` takes its source in this
   order, settled in step 1 by looking: the site's OCTGN package from
   its MyGet feed, pinned by version (`26.09.26.15` today) -- if it
   holds every card's properties and pictures as an OCTGN package does,
   it is the one structured, versioned source; and where it holds less
   than the site's pages (the icons, the rulings, the thumbnails per
   face), the site itself, crawled once -- the four listings for the
   facts, each card's page for its faces, icons, text and rulings --
   at a date pinned in the script and written into every generated
   file's header; `--offline <dir>` reads a saved crawl or package.
   The import writes `tftcg/data/cards.json` (every card: code, name
   and subname, wave and number, rarity, stars, kind -- character,
   battle, stratagem -- and for a character its faces, each with mode,
   Attack, Defense, Health, traits and text; for a battle card its
   type, slot, bonus, icons and text; for a stratagem its target and
   text), `rulings.json` (every ruling with its source, date, tags and
   text), `decks.json` (the nine pre-constructed decks by card code,
   from the site's lists), `banlist.json`, and the art into
   `tftcg/images/cards/<code>_<n>.jpg` (a thumbnail per face) and the
   site's own marks -- the five battle icons, the three stat marks,
   the trait and faction marks -- into `tftcg/images/marks/`. **A card
   is keyed by its code** (`C2S02`, `B2046`, `S508`), the site's own
   and unique per printing, never held or compared by name; `name` is
   the way back. A name has printings -- Handheld Blaster is `B1034` in
   Wave 1 and `B2034` in Wave 2, one card by the rules -- so the
   catalog carries, per code, the `rules_key` its text shares (the
   earliest printing's code where the texts are the same, its own where
   an erratum or a replacement made them differ), and the rules tables
   key on that. The glyphs in the texts become tokens: the arrow `🠪`
   to `{arrow}`, the stat marks to `{attack}`, `{defense}`, `{health}`,
   the icons to `{icon:orange}` and so on, the trait marks to
   `{trait:car}`, the tap glyph to `{tap}`. All 1,223 cards come in at
   once, so a later wave is code, not data. `/tftcg card` answers with
   both faces' pictures, the text and the rulings, and links the site's
   page. **What it costs:** the texts, the rulings and the art are
   Hasbro's and Wizards' words and pictures, and the community's for the
   later waves, reproduced in a public repository as the two community
   sites reproduce them under Hasbro's Fan Content Policy. The author
   took the same question for Codex on 2026-10-07; question 1 asks it
   again for this licence.

7. **A card's rules are code keyed by its rules key: keywords as a
   closed table, text as parts, and every ruling a test.**
   `tftcg/keywords.py` holds the keyword table the engine's battle and
   targeting questions read, per face, with what adds and what does not
   (ER §6); `tftcg/effects.py` holds `EFFECTS` part by part and `TEXT`
   per card -- the trigger, the cost, the parts -- each beside the
   printed sentence, as Codex's does, and `UNIMPLEMENTED`, the set of
   rules keys the engine still plays for their numbers alone, which a
   test pins step by step. The rulings are rules: Wizards' (official,
   2018-2020), the Aequitas Committee's and the site's (the
   continuation's), each on a card or keyword in play implemented and
   pinned by a test named for the card with the ruling as its
   docstring; the three post-cancellation changes among them. Where a
   ruling and the rules text differ, the later governs, and a rules
   question is answered from the rulings before it is taken to the
   author, who is not the designer.

8. **A question to the seat that is not active is a public ask with a
   mention, answered through its own buttons, the hidden part behind
   one of them.** When the pending prompt is the defending player's --
   a green swap, Security Console's Plan, later a Focus, a held Secret
   Action's reveal, a "your opponent chooses" -- the cog sends one
   message through `send_new_prompt`: the question in words, a mention
   of whose it is, and its buttons: the public answers where the choice
   is public (**Pass**, **Reveal**, a character to choose), and
   **Answer** where it is not, which opens an ephemeral view with the
   hand pictured and the choice in it. The click that answers edits the
   ask to its outcome ("perrytom swapped a card for Backup Beam") in
   its own response, so the ask costs the channel one send and the gate
   nothing; the active player's panel meanwhile says whom the turn
   waits on. A `manage_channels` helper may answer for an absent
   player, through the confirmation `game_auth` already has. **Why not
   the panel:** an ephemeral message can only be opened by its owner's
   click, so a question the bot must put to someone who has not
   clicked needs a message they are notified of; a mention in an edit
   notifies nobody. **Why not the turn message:** it is the active
   player's turn's summary, edited through a gate that may lag, and a
   question with a deadline of "now" is not a summary. **What it
   costs:** one message per such question -- a handful a turn at most
   -- and the discipline that the ask carries no hidden information.

9. **The attacker's flips wait behind the attacker's button; the
   defender's wait behind the defender's only while the defender has
   something to decide first.** After the defender is chosen, the panel
   offers **Flip** (and, when the attacker has Focus or a "before you
   flip" choice, that choice first), so the attacking player sees their
   cards turn as a moment of their own, as D12 Ball's coaches press
   Roll. The defender's flips are then owed -- run by the bot in the
   same edit, nobody pressing anything -- unless the defender has a
   decision before them (a Focus, a held Secret Action, a "before
   flipping" trigger with a choice), in which case the ask of decision
   8 carries **Flip** with that decision in front of it. The reason: a
   flip is deterministic once the deck is shuffled, so there is no roll
   to witness, only the decisions before it; a button nobody needs
   blocks a present attacker on an absent defender. The author may
   prefer both flips behind buttons, or neither (question 6); each is a
   change to the prompt's `asked_player` and the owed step, not to the
   rules.

10. **Secret Actions reveal themselves unless held.** The set has none,
    Wave 3 has thirteen, and the shape is step 5's. Playing one offers
    its owner two ways to hold it: **reveal when it can** (the default
    -- the bot reveals it at the first window its condition is met,
    the way nearly every player plays nearly every Secret Action) or
    **ask me** (the owner wants to hold it, as Wizards' 2019 ruling
    allows -- the bot then asks them at *every* reveal window while it
    is down, whether or not the condition is met, refusing a reveal
    whose condition is unmet privately, so that the asking tells the
    opponent nothing). The choice is the owner's and hidden with the
    card. A face-down card's existence is public, as it is on the
    table. **What it costs:** a pause at each window for a held card,
    which its owner chose; and the end-of-turn rule that the defending
    player's unrevealed Secret Actions are scrapped face up without
    effect (ER §1.5), which the bot applies.

11. **The lobby is the one slash command a game needs; everything
    after it is a button.** `/tftcg create_game` opens the game's
    channel under **TF TCG Games** (a thread, or the channel it was
    typed in, where the bot may not make one -- the Codex bot's
    `venue`) and posts the lobby in it: two seats, each choosing a
    team -- in these steps the starter's two, **Autobots** (Bumblebee
    and Windblade, 12★) and **Decepticons** (Megatron and Starscream,
    12★), both dealt the forty; the site's other pre-constructed decks
    and a deck a player brings are step 7's -- **Leave**, and
    **Start** for either seated player once both have chosen. Start
    names the channel `tftcg-<n>-<p1>-vs-<p2>`, puts every character on
    the battlefield in alt mode, shuffles both decks, deals three each,
    picks the first player at random (R1 §1.3) and posts the first
    turn's message, which carries the game's buttons: **My hand**
    (the panel for the active player, the hand for the other),
    **Scrap**, **Deck** (the counts and the KO area in words, for a
    phone), **Undo**, **Swap view**, **Concede**. The slash commands
    beside it: `card`, `rules`, `games`, `board`, `hand`, `resume`,
    `concede`, and the admin `abandon` and `reset_channels`. fool-bot's
    hub gains a third line with the command mention
    `</tftcg create_game:ID>`, read from `data/tftcg_command_ids.json`
    as the Codex line is.

12. **Undo, with its infrastructure in the model's first commit.**
    Codex's: a snapshot of the position at every turn start, bounded to
    the last three, and a journal of the turn's actions with the random
    outcomes each consumed -- here a shuffle's order, so that a flip or
    a draw replays byte for byte -- with `driver.apply` the one door
    where the journal is written. The two coarse undos (to the start of
    this turn, the active player's alone; to the start of the previous
    turn, with the opponent's agreement or a helper's) and the fine
    undo over the journal's points, as Codex built them on 2026-10-10,
    with one rule carried over and sharpened: **anything that shows a
    player a card they could not see before closes the undo points
    before it** -- a draw, a Plan or Focus look, a look at the
    opponent's hand, a revealed top card -- and a flip, which is public,
    does not. **What it costs:** two saved fields from the first commit,
    a shuffle that takes a recorded order back, and every surface
    re-rendering from the position after an undo.

13. **The rules reference is the imported rulings and a citation.**
    `/tftcg rules <term>` answers from the rulings tagged to a keyword,
    a mode, a trait or a term; `/tftcg card <name>` shows a card's faces,
    text and rulings; both link the site. The bot reprints no rules
    text and words its refusals itself ("Starscream can't attack: he is
    tapped"), citing the section the way D12 Ball cites a Law and Codex
    a page (`ER §1.3.1`). The two rules pages and the .org glossary are
    committed as dated markdown under `docs/tftcg/` by the import's
    `--rules`, for the developers to cite offline, never for the bot to
    quote; `docs/living-rules.md` is not touched.

14. **No AI opponent in these steps.** Two humans; the shape exists.

15. **Every draw the game makes is `engine.rng`.** The two shuffles,
    every reshuffle and the first player are the randomness; a flip and
    a draw are the top of an ordered deck; tests seed it; nothing under
    `tftcg/` imports `random`.

## Questions for the author

Each step's PR carries a `## Questions to the author` section; these
are the ones known before any step starts. A step whose prompt needs
the answer says what it builds until it has one.

1. **Card texts, rulings and art bundled in this repository**, as the
   Codex bot's are. Hasbro's and Wizards' words and pictures, and the
   community's for Waves 6 to 10, reproduced as transformers.cards and
   transformerstcg.org reproduce them under Hasbro's Fan Content
   Policy. Built as yes. If no, the import stays and the data lives in
   `data/` on each checkout, fetched by the import rather than
   committed.
2. **teletraan1.net is the Transformers Deck-Building Game's
   database**, not the TCG's. Nothing in this plan reads it. Was the
   link meant for something else -- the deck-building game as a fourth
   bot one day, or a mistaken paste?
3. **Which card pool does the bot know?** transformers.cards' (Wizards'
   Waves 1 to 5 and the Allied Crossplay Waves 6 to 10 and outliers), or
   transformerstcg.org's (the same Wizards' waves and its own Org Waves,
   partly different cards). Built as transformers.cards', the author's
   link, with the site's ban list as data and a game setting that
   applies it or not. Rules text: the two agree on every matter found;
   a disagreement found later is a question.
4. **The starter set's two teams as the first game, each with the whole
   forty** -- Wizards' product gave two players four characters and
   forty battle cards and taught them with a sheet that ignored the
   cards' text; the bot plays the real rules over the same cards.
   Built as that. The alternative is the product's teaching split, two
   characters and twenty cards a side, which no rules text describes.
5. **Secret Actions: revealed when they can, unless held** (decision
   10), or asked about at every window, or at the matching ones only
   with the leak that brings. Built as decision 10; not needed before
   step 5.
6. **The attacker's flips behind a button, the defender's only when
   they have a decision** (decision 9), or both behind buttons as D12
   Ball's rolls, or neither. Built as decision 9.
7. **`/tftcg` or `/transformers`** as the slash group. Built as
   `/tftcg`; a rename is one string.
8. **A deck a player brings: pasted as text, or fetched from a
   transformers.cards deck URL?** The URL is one network fetch at
   import, on a human's command, never in a game flow -- the first
   outbound request any of the bots makes; the paste is the deck page's
   own text copied in. Built as both, in step 7.
9. **The same #logs channel, one application and no test application,
   and the author creates the application** -- as the Codex bot. Built
   as that.
10. **Single games, no sideboard, no best-of-three.** Built as that;
    a sideboard is data the record can hold later.
11. **The board's look is reviewed on step 3's PR** from rendered
    pictures, as the Codex board was on a canvas; what the author
    changes there is written into step 3's design note, and a redraw
    is a step only if the review asks for one.
12. **Combiners, Titan Masters, Battle Masters, Weaponizers, Triple
    Changers, stratagems and the community mechanics** come wave by
    wave after the starter (steps 10 to 15), in the waves' own order.
    Built as that order; the author may want a particular wave sooner.

## The steps

In the order they pay off. Each is one branch off an up-to-date `main`,
one PR against the template, the suite green, the D12 Ball and Codex
safety-net tests untouched unless the step says why. None changes
either other game's save format or any file under `d12ball/`,
`codex/`, `gamesaves/d12ball/`, `gamesaves/codex/`, `cogs/d12ball*` or
`cogs/codex*` except where a step names one. Every step ends on a
**stop**: the thing the author looks at before the next step is worth
starting.

| # | Step | Size | Stop |
| --- | --- | --- | --- |
| 1 | The third bot stands up, and knows the cards | medium | `/tftcg card megatron` answers in the test server with both faces and Wizards' rulings, and all three bots run on the live host after one `deploy.cmd` |
| 2 | A whole game through the driver, with no frontend | large | a test plays the starter's Autobots against its Decepticons to the last KO with nothing from `cogs/` or `discord` imported |
| 3 | The lobby, the channel and the board | medium | two people reach the opening position on Discord: a channel, a board with four characters in alt mode, a hand of three each that the other cannot see |
| 4 | The turn on Discord, and the undos | large | two people finish a game on the vanilla engine; the defender answers a green swap from a public ask; a restart mid-turn resumes from **My hand**; an undo puts everything back |
| 5 | The battle's fine print and the keywords | medium | a white icon flips two more exactly once; Stealthiness turns an attack aside; every keyword ruling on the site's pages is a test; a Secret Action can be played, held, revealed and scrapped unrevealed |
| 6 | Every card of the starter set does what it says | large | `UNIMPLEMENTED` is empty over the twenty-five; Security Console asks the defender mid-attack |
| 7 | The decks: the site's pre-constructed decks, and a deck a player brings | medium | the Thunderbee starter plays the Timecop starter from the lobby; a pasted deck is refused with the rule it breaks |
| 8 | Finishing a game: concede, abandon, rematch, the golden | small | a finished game ends cleanly, offers a rematch with the first player switched, and is moved aside; a seeded whole game is pinned byte for byte |
| 9 | The look back: what the Codex bot and this one share moves to one home | small | nothing copied in steps 1 to 8 remains byte-identical in two places |
| 10 | Wave 1 whole | large | every Wave 1 card plays; the Metroplex deck's deployables with it |
| 11 | Wave 2: Rise of the Combiners | large | Devastator combines |
| 12 | Wave 3: Siege I | large | Battle Masters, Secret Actions in play, the Blaster and Soundwave sets |
| 13 | Wave 4: Siege II | large | Weaponizers and Triple Changers; Trypticon |
| 14 | Wave 5: Titan Masters Attack | large | heads on bodies, stratagems, hybrid icons |
| 15 | Waves 6 to 10, the community's | large, several PRs | Rolling Actions, Stations, the Junkion and Mercenary keywords; every card in the data plays |
| -- | Later, and not now | -- | |

### Claiming a step

The series does not exist yet: **step 1's prompt adds it** -- one entry
in `SERIES` in `scripts/claim_web_step.py`
(`"tftcg": ("docs/tftcg-bot.md", "tftcg-step", "TF TCG step")`), plus
the `--series` help string and the module docstring, which both list
the series by hand. From then on
`python3 scripts/claim_web_step.py --series tftcg <n>` claims a step the
way the other series are claimed: an empty commit on `tftcg-step-<n>`
pushed create-only, refused if the row is struck on `origin/main`, the
branch exists, or an open PR is titled `TF TCG step <n>:`. A step lands
by striking its row above (`| ~~n~~ | ~~title~~ -- landed; what it
settled is in docs/design/tftcg.md | ... |`).

**No cloud routine is created by this plan.** The Codex series got one
at the author's ask on 2026-10-08, modelled on the redesign routine,
and this series can have one the same way -- the same gates (the
worksheet on `main`, the first unstruck row with a fenced prompt,
nobody's claim and no `TF TCG step` PR open, the suite green), the same
two sections on every PR (`## Questions to the author`, `None.` when
empty, and `## For the author` in two parts: what to do on the live
host after merging and what can be tested in the server now). Until
the author asks, a human claims each step.

## Preamble

Every step's prompt begins with this block. A session given a step reads
it first, then the step's own prompt below.

```text
You are working in the fool-bot repository on the Transformers TCG bot
planned in docs/tftcg-bot.md: a third Discord bot, run from this
repository as its own process with its own token, modelled on the
Codex bot and the D12 Ball bot, playing the Transformers Trading Card
Game -- the Bumblebee vs Megatron Starter Set first. Read that
worksheet first (the section "The game, in the terms the code will
use" is the rules you implement; the card table is the scope), then
the design note docs/design/tftcg.md if it exists, then
docs/design/codex.md (the bot whose shapes you copy -- read "Its own
process, its own token", "The model, before a line of Discord",
"Hidden information on Discord", "The turn on Discord", "The undos",
"What the two games share"), then docs/design/model-discord-split.md
and docs/design/game-service.md. Read the rest of docs/design/ only
where a step names a file.

Start on a fresh branch off an up-to-date main (the claim script has
made it: git fetch && git checkout tftcg-step-<n>), in a worktree of
your own if another session may be using the checkout. Never work on
main.

Hard rules for every step:
- tftcg/ and gamesaves/tftcg/ import no discord, define no async def,
  and import Pillow only in tftcg/render.py. The purity ratchet
  enforces it; do not loosen the ratchet.
- A rule is a question the model answers and the cog asks. Nothing in
  cogs/tftcg* decides a rule, computes a legal defender, a flip count,
  an Attack total, a draw or a target list; a view builds its controls
  from PendingPrompt.options and nothing else, and the driver refuses
  what the options do not offer, with RuleRefusal citing a section
  ("ER §1.3.1", "R1 §1.1"), never a bare ValueError.
- Cards are keyed by code and rules by rules key, never by display
  name. Card data comes from scripts/import_tftcg_cards.py and nothing
  edits tftcg/data/ by hand. A card whose text the engine does not yet
  honour is in tftcg.effects.UNIMPLEMENTED, and the test that pins that
  set changes in the same commit as the engine.
- Nothing that is hidden -- a hand, a deck's order, a face-down Secret
  Action's face, a Focus or Plan look, an opponent's hand once looked
  at -- is written into a public message, a log line or the #logs
  mirror. The scrap piles and the KO areas are public. Say in the PR
  where you checked.
- A ruling is a rule. Wizards' rulings and the continuation's in
  tftcg/data/rulings.json are rules of the game: the engine does what a
  ruling says, a test pins it with the ruling as its docstring, and
  where the rules text and a ruling differ the later governs. The three
  post-cancellation changes are rules. A rules question is answered
  from the rulings first and taken to the author only when they are
  silent.
- Read every card you implement against the card's page on
  transformers.cards AND the rules -- Rules 1.0 (/rulesbasic) and
  Expanded Rules 2.0 (/rulesexpanded), committed as dated markdown
  under docs/tftcg/ by step 1 and cited as "R1 §n" and "ER §n" -- not
  the data alone. transformerstcg.org carries the same rules text and
  a glossary; the two should agree, and a disagreement is a question
  for the author.
- Card art wherever a card exists: the board, the panel's hand, the
  battle strip and /tftcg card show the cards' own faces from
  tftcg/images/cards/; nothing is redrawn that a card already shows,
  and drawn tiles are for the chits, the slot marks and the card back.
- Every draw the game makes is engine.rng, and a flip or a draw is the
  top of the deck the shuffle ordered. A test seeds it.
- Rate limits: the fix is always fewer requests, never slower ones.
  One message per channel is edited, the current turn's -- the board
  with the turn's lines -- through the gate; the active player's panel
  is ephemeral and edited through its own interactions; a question to
  the other seat is one send through send_new_prompt, edited once by
  the click that answers it; a cascade of the bot's own steps is one
  edit and nothing more. Nothing is an embed. Read
  docs/design/rate-limits.md before adding any send, edit or pin.
- Nothing under d12ball/, codex/, gamesaves/d12ball/, gamesaves/codex/,
  cogs/d12ball* or cogs/codex* changes unless the step names the file
  and says why. Both other games' save formats, docs/living-rules.md,
  the six D12 Ball safety-net tests and the Codex golden are not
  touched.
- Nothing rendered is tested for how it looks: render it
  (scripts/render_tftcg_sample.py once step 3 adds it) and look, and
  put the picture in the PR.
- tests/ is flat and its helpers are imported by bare name, so every
  TF TCG test helper is named tftcg_<thing>.py, and every TF TCG module
  that binds save_games is listed in tests/save_patches.py's tables
  (the stray-save guard walks all of cogs/ and gamesaves/).
- A leaf that two bots use is moved, not copied: the move names the
  Codex or D12 Ball file it touches, their tests pass unchanged, and
  the old module keeps re-exporting the old name.
- Run python3 -m unittest discover -s tests before the PR; a full run
  must not create data/. The PR is against the template, carries a
  "## Questions to the author" section ("None." when empty) and a
  "## For the author" section in two parts -- what to do on the live
  host after merging (deploy.cmd; every new .env variable by name and
  what goes in it; every emoji PNG to upload to the TF TCG application
  in the Developer Portal, by name; any Discord-side setup; or
  "Nothing to do on the live host") and what can be tested in the
  server now, command by command, each with what should happen, and
  one line on what is not expected to work yet -- and strikes this
  step's row in docs/tftcg-bot.md. When the step settles something the
  worksheet only proposed, write it into docs/design/tftcg.md with the
  reasoning, and add a row to CLAUDE.md's tables only for a new module
  or a new hard rule.
```

### 1. The third bot stands up, and knows the cards

The first thing anybody sees: a bot that answers `/tftcg card` with a
card's two faces and the rulings on it. It is also everything the later
steps stand on that is not the game -- the entry point, the token, the
deploy slot, the data import and the design note -- so that step 2 is
only the model and step 3 only the frontend.

```text
Step 1 of docs/tftcg-bot.md. Nothing has landed before it. Also read
docs/design/collaboration.md ("One bot per token", "Running the web
app", "The Codex bot"), docs/design/logging.md,
docs/design/rules-and-data.md (the import-script rule, which the card
data inherits), scripts/import_codex_cards.py (the shape of an import
that pins a source) and codexbot.py (the twenty lines you copy).

Four commits, in this order.

1. The claim series. scripts/claim_web_step.py gains
   "tftcg": ("docs/tftcg-bot.md", "tftcg-step", "TF TCG step") in
   SERIES, and the --series help string and the module docstring list
   it. Then claim this step with it (python3 scripts/claim_web_step.py
   --series tftcg 1) and continue on tftcg-step-1.

2. The card data. scripts/import_tftcg_cards.py. First look at the
   site's OCTGN package: the MyGet feed https://www.myget.org/F/teletraan
   lists one package (its id a GUID; version 26.09.26.15 on
   2026-10-14, 73 MiB), downloaded from
   /F/teletraan/api/v2/package/<id>/<version> as a NuGet zip. Open it
   and record in the design note what it holds: an OCTGN game package
   carries def/definition.xml and sets/<guid>/set.xml with every card's
   properties, and often the card pictures. If it carries every card's
   code, name, wave, stars, faces with their numbers and text, traits,
   type and slot, icons and pictures, it is the source, pinned by
   version in a module constant; what it lacks -- the rulings, and the
   thumbnails per face if its pictures are not per face -- comes from
   the site. If it carries less than that, the site is the source: the
   four listings (/cards, /characters, /battle, /stratagems -- one
   table each, every card's code in its link, its wave and number,
   rarity, stars, type, the numbers and traits per face, and the text
   with the glyphs as pictures) for the facts, and each card's page
   (/card/<code>/<slug>) for its faces, its battle icons (three slots,
   BattleIcon_<L>.png, X for none), its subname, its thumbnails
   (/images/thumbnails/<code>_<n>.jpg) and its "Relevant Rulings" with
   source, date, tags and link, crawled once with a pause between
   requests, at a date pinned in the script. --offline <dir> reads a
   saved package or crawl; --no-images skips the pictures. Either way
   the source and its version or date go into a "source" header of
   every generated file.

   It writes, whole and sorted by code, with a header saying never to
   edit by hand as d12ball/data/ and codex/data/ do:
   tftcg/data/cards.json -- every card: code, name, subname, wave (its
   code and name), number, rarity, stars, kind (character, battle,
   stratagem), and for a character its faces in order, each with mode
   (alt, bot, alt_1, alt_2, body, head, upgrade, combiner), attack,
   defense, health, traits and text lines; for a battle card its type
   (action, secret_action, rolling_action, upgrade), slot (weapon,
   armor, utility), bonus (attack, defense, health), icons (a list of
   orange, blue, white, green, black, with a trait for a hybrid), and
   text lines; for a stratagem its target and text; and rules_key:
   the code of the earliest printing whose name and text are the same,
   the card's own code where they differ (a reprint with an erratum,
   a replacement). tftcg/data/rulings.json -- every ruling once, with
   source, date, text, and tags (cards by code, keywords, modes,
   traits, terms). tftcg/data/decks.json -- the nine pre-constructed
   decks at /decks/precon by name, with characters and battle cards by
   code and count, read from each deck's page or its o8d export.
   tftcg/data/banlist.json -- the banned cards and the replacements
   from /banned, by code. The glyphs in the texts become tokens the way
   codex/tokens.py writes them: the arrow 🠪 to {arrow}, the three stat
   marks to {attack}, {defense}, {health}, the icon pictures to
   {icon:orange} and the rest, the trait marks to {trait:<slug>}, the
   tap glyph to {tap}. Nothing else is reworded.

   The art, in the same run: every face's thumbnail into
   tftcg/images/cards/<code>_<n>.jpg (record their size in the note;
   if the full pictures are what the board wants, say so and fetch
   those instead, once), and the site's marks -- BattleIcon_O, B, W,
   G, K, X; Card_Attack, Card_Defense, Card_Health; every
   "Trait - <name>.png" -- into tftcg/images/marks/, by their slugs.
   The two rules pages (/rulesbasic, /rulesexpanded) and
   transformerstcg.org/glossary as dated markdown into docs/tftcg/
   under --rules, the section numbers kept, for citation; nothing in
   the bot reads them. The images and the documents are committed like
   the data: regenerated by the script, never edited by hand. Mind
   .gitignore: an unanchored cards/ entry once dropped the Codex art
   silently.

   tftcg/cards.py reads them: Card, Face, BattleCard, Stratagem and
   CardCatalog with by_code, by_name (every printing of a name),
   faces(code), rules_key(code), deck(name) (a pre-constructed deck's
   lists), and name(code) -- the one way back from a code to a name,
   "Megatron // Cybertronian Tyrant" with its subname.
   tftcg/formatting.py: card_label ("Megatron // Cybertronian Tyrant
   (7★)"), face_label ("bot 3/1/10"), the plain-text rendering of a
   text line's tokens, and nothing that touches Discord.
   tftcg/rulings.py: rulings_for(code) over the card's rules key and
   every printing, and rulings_tagged(tag).

   tests/test_tftcg_cards.py: the data loads; every code is unique;
   the four characters and twenty-one battle cards of the starter set
   are present with the stars, faces, numbers, icons, slots and bonuses
   the worksheet's table gives; every ruling's card tag names a code in
   the catalog; no text still contains the arrow glyph or a bare icon
   mark; deck("Bumblebee Vs. Megatron Starter Set") is four characters
   and forty battle cards; every face of the starter set has its
   picture under tftcg/images/cards/, and tftcg/images/marks/ holds
   the five icons, the three stat marks and the traits the starter's
   faces carry; Handheld Blaster's two printings share one rules key.

3. The bot. tftcgbot.py is twenty lines over gamebot.GameBot, as
   codexbot.py is: load_dotenv, botlog.configure_logging with prefix
   "TFTCG", bot name "TF TCG bot" and data/tftcg_bot_state.json, the
   mirror, GameBot(extensions=("cogs.tftcg",),
   state_file=data/tftcg_bot_state.json, sync_variable=
   "TFTCG_COMMAND_SYNC", message_content=False,
   command_ids_file=data/tftcg_command_ids.json), the token from
   TFTCG_DISCORD_TOKEN, --with-fool-bot as the Codex bot has it.
   botlog/settings.env already falls back from <PREFIX>_<name> to
   FOOLBOT_<name>; nothing in botlog changes. tests/test_web_purity.py's
   list of entry points that import no webapp gains tftcgbot.py.

   cogs/tftcg/ is a package whose __init__.py assembles
   TFTCG(commands.GroupCog, group_name="tftcg", group_description=
   "Play the Transformers TCG -- one game per channel.") -- the
   description passed explicitly and under 100 characters -- from one
   mixin for now, cogs/tftcg/reference.py: /tftcg card <name> with
   autocomplete over the catalog by name and subname, answering with
   both faces' pictures attached (one picture for a battle card) and,
   as plain text under them, the name and subname, the wave and
   number, the stars, each face's mode, numbers and traits, the text
   with its tokens rendered, the icons, the rulings with source and
   date, and a link to https://transformers.cards/card/<code>/<slug>
   -- no embed, as nothing in these bots is -- and /tftcg rules <term>
   with autocomplete over the keywords, modes, traits and terms the
   rulings are tagged with, answering with those rulings as the rules
   they are. cogs/tftcg_helpers.py holds TFTCGTokens, the resolver
   from token to emoji or word, the channel name and the two
   categories ("TF TCG Games", "TF TCG Archive"), and nothing else yet.
   In this step every token renders as a word or as the site's own
   glyph where Unicode has one: application emoji belong to one
   application and are uploaded by hand in the Developer Portal, so
   draw the PNGs the resolver will want -- the five icons, the three
   stat marks, tap, the Autobot and Decepticon marks -- at 128 px with
   transparent surroundings into tftcg/images/emoji/ with
   scripts/render_tftcg_emoji.py (modelled on render_codex_emoji.py),
   list them for the author in the PR, and let the resolver pick each
   up by name once it is uploaded, the way cogs/codex_helpers.py's
   does. Every token is rendered at the cog's door, never in the model.

   scripts/run_tftcg_bot.ps1 and run_tftcg_bot.cmd, modelled line for
   line on run_codex_bot.ps1: the pull through pull_checkout.ps1
   (-SkipPull from deploy.ps1), stops every tftcgbot\.py run by this
   checkout's venv python plus whatever data/tftcgbot.pid names,
   refuses to start if any survive, skips with a warning when
   TFTCG_DISCORD_TOKEN is in neither the environment nor .env, starts
   hidden with data/tftcgbot.stdout.log and .stderr.log, fails if the
   process has exited after four seconds. deploy.ps1 calls it after
   run_codex_bot.ps1 and before run_web_app.ps1, with the one-line
   reason in its comment, and -StopOnly stops it in its turn.
   .gitignore lists the new data files by name. requirements.txt does
   not change.

4. The documents. docs/design/tftcg.md is created with the standard
   header line and these sections: what the bot is and what it plays;
   "Its own process, its own token" (decision 1 of the worksheet, the
   package name and why); "The cards are data" (decision 6: which
   source was chosen after looking, the pinned version or date, the
   code and the rules key, the glyph tokens, what the site's pages had
   that the package did not, where the copyright question stands);
   "The reference commands"; "Running it" (the Mac command, the K:\
   runner, the one Developer Portal application). CLAUDE.md: its first
   paragraph says the repository runs three bots and names this one;
   "## Running it" gains python3 tftcgbot.py; "Where things live" gains
   rows for tftcgbot.py, tftcg/, cogs/tftcg/, cogs/tftcg_helpers.py,
   scripts/import_tftcg_cards.py and scripts/run_tftcg_bot.ps1; "Read
   this before touching" gains one row pointing at tftcg.md; the
   deploying row names run_tftcg_bot.ps1 and TFTCG_DISCORD_TOKEN.
   docs/design/collaboration.md gains the third bot under its deploy
   section as the Codex bot is there.

Verify by hand and say so in the PR: python3 tftcgbot.py starts with
the application's token -- the one token there is, so nothing else runs
the TF TCG bot meanwhile -- and answers /tftcg card megatron and /tftcg
rules pierce in the server; python3 foolbot.py and python3 codexbot.py
still start and still sync; on the live host deploy.cmd leaves all
three bots running (the author does this one; the PR says it is owed).

Done when: the suite is green with the new tests, three bots run from
one checkout, and the design note and the map say so. Under Questions
to the author: question 1 of the worksheet (the bundled texts and art)
and question 3 (the card pool).

Stop: the author asks the test server for Megatron and reads both
faces and a ruling of Wizards' under them.
```

### 2. A whole game through the driver, with no frontend

The model, whole, before a line of Discord: the state, the record, the
engine's questions, the prompts, the turn's flow and the driver, with
the vanilla engine of decision 7 -- every card for its numbers, every
other text in `UNIMPLEMENTED`. The test that plays a game to the last
KO with nothing from `cogs/` imported is the deliverable; it is what
step 3 renders and what every later step keeps green.

```text
Step 2 of docs/tftcg-bot.md. Step 1 has landed. Also read
codex/components.py, codex/prompts.py, codex/flow/result.py,
codex/flow/driver.py, codex/flow/resolve.py and codex/history.py (the
shapes you copy, read whole), d12ball/prompts.py's asked_sides (the
one thing you take from D12 Ball: a prompt that names which seat it
asks), and docs/design/gotchas.md (why the fallbacks stay). Three
commits: the state and the record; the engine, prompts and flow; the
tests.

1. tftcg/components.py. MatchState: two PlayerState in seat order,
   first (who went first), active (whose turn), turn (the number),
   phase (start, main, attack, post_attack, end), plays (what the main
   phase has used: flipped, action, upgrade, tap -- booleans), attack
   (None, or AttackState: attacker id, defender id, the locked flip
   counts, each side's flipped codes in order, the attacker's bonus
   Attack and Pierce so far, the defender's bonus Defense, whether each
   side has had its white flips, the stage -- combatants, attacker
   flips, defender flips, damage, post), attacks_left (the extra
   attacks owed), delayed (effects waiting for the end of the turn,
   each with its source and its part), the winner, the events list,
   and next_instance_id. PlayerState: characters (a list of
   CharacterState: id, code, face (the index of the face up), tapped,
   damage, slots -- weapon, armor, utility, each a CardInstance or
   None -- modifiers, a list of {kind, amount, until: turn or battle,
   source}, ko (bool; a KO'd character keeps its id, its face and its
   damage in the KO area), deck (codes, top last), hand (codes), scrap
   (codes, in order), played (a list of CardInstance for this turn's
   Actions, each with face_down for a Secret Action and its hold
   choice -- fields present and inert until step 5), ko_area (ids).
   CardInstance: id, code, owner, controller, and, for an Upgrade,
   the character it is on. On the match, for decision 12:
   turn_snapshots (the last three turn-start positions as dicts,
   oldest first) and journal (the actions applied since the turn
   began, each with the random outcomes it consumed). The SavedField
   tables carry every field with a fallback from this first commit;
   to_dict/from_dict round-trip; validate checks the position against
   itself (ids unique, codes in the catalog, a face index within the
   card's faces, one card in a slot, a character in the KO area not on
   the battlefield, counts non-negative). The save file is
   data/tftcg_games.json and the format is the contract from now on.

   tftcg/game.py: TFTCGGame -- game_id and game_number; guild_id,
   channel_id, message_id and turn_message_id all optional, venue as
   the Codex record has it; player_1_id and player_2_id with their
   names, observer_ids and test_game spelt exactly as the other two
   records spell them, so cogs/game_auth.py reads this one; teams (seat
   number to a team: a name, its characters by code, its deck by code
   and count -- in this step the starter's two, "Autobots" and
   "Decepticons", each with the forty); board_layout; status (lobby,
   playing, finished, abandoned); match_state (None until Start) --
   with the lobby rules as methods that refuse with RuleRefusal:
   take_seat(user, team), leave(user), may_start(), start(engine), and
   the legality of a team as one method, legal_team(team) -- stars at
   most 25 counting star cards and stratagems, forty or more battle
   cards, no more than three of a name, no two characters of one full
   name, no two stratagems on one target -- citing "R1 §1.1" and
   "ER §8", read by step 7's deck import and by nothing yet.
   RuleRefusal is tftcg/'s own, with a `cite` field, as codex/'s has.

2. tftcg/engine.py. RulesEngine(catalog) with rng, the questions, no
   Discord: new_match(teams, first) (shuffle each deck, deal three,
   every character in its first face, untapped); legal_plays(match)
   for the active player in the main phase, as data: flip (which
   characters may flip, and why not -- already flipped this turn, a
   face that cannot be flipped to), actions (each playable Action in
   hand with why not: the first-turn rule, already played), upgrades
   (each Upgrade in hand with the characters it may go on, by slot and
   by its "put on X only"), tap_abilities (none in this set; the shape
   is there), attack (whether the turn's attack may begin: an untapped
   character exists, the main phase's plays are optional), end
   (whether the turn may end: the required attack is done or
   impossible); legal_attackers(match); legal_defenders(match,
   attacker) (the tapped rule; Stealth and Brave are step 5's, the hook
   is here); flip_count(match, side) (two plus Bold or Tough, locked
   when the combatants are chosen); attack_total and defense_total
   over the face's number, the Upgrades' bonuses, the modifiers and the
   icons so far; attack_damage(match) (ER §1.3.3 with Pierce);
   extra_attack_owed(match) (ER §1.4); first_turn_rule(match);
   is_vanilla(rules_key) reads effects.UNIMPLEMENTED.

   tftcg/prompts.py: PromptKind -- MAIN_ACTION, CHOOSE_ATTACKER,
   CHOOSE_DEFENDER, FLIP_CARDS, GREEN_SWAP, TARGET, CHOOSE_FROM_HAND,
   PLAN, ORDER_TRIGGERS, REVEAL_SECRET, GAME_OVER (the last six present
   as kinds with options in this step, asked by nothing until steps 5
   and 6, so that ANSWERS and the view table are complete from the
   first commit) -- PendingPrompt with asked_player, the seat the
   question is put to (the active player for MAIN_ACTION,
   CHOOSE_ATTACKER and CHOOSE_DEFENDER; the flipping player for
   FLIP_CARDS, with may_press, the seats that may press it -- both,
   when the flipping player has nothing to decide, decision 9; the
   swapping player for GREEN_SWAP; whoever the effect says for the
   rest), Action, OPTIONS with one dataclass per kind built from the
   engine's answers (MainActionOptions with the legal plays and their
   reasons, AttackerOptions, DefenderOptions with why each is legal,
   FlipOptions with the count and what may be decided before it,
   GreenSwapOptions with the green cards flipped and the hand,
   TargetOptions, HandOptions, PlanOptions, TriggerOrderOptions,
   RevealOptions, GameOverOptions), pending(engine, game, match)
   returning the PendingPrompt or the FollowOn owed, and
   standing_prompts(engine, match, game) returning an empty list -- the
   reader exists so that the service and the cog have Codex's shape.

   tftcg/flow/: result.py (StepResult, FollowOn, FollowOnStep,
   Headline, copied), turn.py (begin_turn: the draw -- with the
   reshuffle -- and the start-of-turn triggers; begin_attack_phase;
   end_turn: the end-of-turn triggers and the delayed effects, the
   played area and the flipped cards to the scrap pile, the modifiers
   until end of turn removed, again while anything triggers, the turn
   passed), actions.py (flip(character), play_action(card, ...) --
   paid into the played area and, in this step, doing nothing, since
   its text is in UNIMPLEMENTED; play_upgrade(card, character) -- into
   its slot, the old one scrapped, the bonus counted from then on;
   tap_ability(character) refused, none exists), combat.py
   (choose_attacker: tapped; choose_defender; lock_counts; flip_cards
   for a side: cards off the top one at a time with the reshuffle
   where the deck empties, orange, blue and black counted as each card
   turns, white's two more once; resolve_damage: the totals, Pierce,
   the counters, the KO -- the character to the KO area with its
   Upgrades to the scrap pile; post_attack: the green swaps offered
   (step 5 answers them; here the step says nothing and moves on),
   extra attacks, the untap of all, the winner), driver.py
   (MODEL_STEPS covering FollowOnStep exactly; advance; answer; apply,
   which also writes the journal; ANSWERS covering PromptKind exactly),
   resolve.py (the effect stack, copied from codex/flow/resolve.py:
   frames on MatchState.resolving, DOES keyed by a part's does,
   STRUCTURAL -- empty of card effects until step 6, with the frames
   the engine's own steps use for the triggers that are rules: an
   Upgrade put, a KO). tftcg/history.py, for decision 12, copied from
   codex/history.py: snapshot at begin_turn, record in driver.apply
   with the random outcomes the step consumed (a shuffle's order, in
   StepResult.drawn), replay, undo_targets, undo_to_turn_start,
   undo_to_previous_turn, and the fine undo's undo_points and undo_to
   with the rule of decision 12 -- a draw closes the points before it
   (StepResult.drew), a flip does not. engine.shuffle(cards,
   recorded=None) is the only shuffle. Each step changes the match
   and returns what happened, in the model's voice with tokens
   ({player:1}, {card:B2046}, {icon:orange}, {attack}), and sends and
   saves nothing. The Headline of a resolved attack carries the
   arithmetic written out, as D12 Ball's rolls do.

   tftcg/effects.py: UNIMPLEMENTED, a frozenset of every rules key in
   the starter set whose text the engine does not honour -- every card
   with text but Bold, Tough and Pierce, which keywords.py reads from
   this commit -- and EFFECTS, TEXT and COSTS empty. tftcg/keywords.py:
   the keyword table read off every face's and battle card's text
   (keyword, X) per rules key, with Bold, Tough and Pierce live and the
   rest present and inert. tftcg/tokens.py: the builders and
   render(text, resolve), copied from codex/tokens.py with this game's
   KINDS. tftcg/wire.py: jsonable from gamekit and to_dict on the
   result and prompt types, copied.

3. Tests. tests/test_model_purity.py's lists gain tftcg/ and
   gamesaves/tftcg/ (the file is one of the six; say in the PR that
   only its lists changed). tests/test_tftcg_driver_full_game.py: a
   seeded game of the starter's Autobots against its Decepticons
   through driver.apply alone, under a policy that flips a character
   when it may, plays the first playable Action and the first playable
   Upgrade onto the first character that takes it, attacks with the
   first legal attacker at the first legal defender, presses Flip, and
   ends the turn; asserts the game ends with a side KO'd within a
   bounded number of turns, that every position round-trips through
   to_dict/from_dict and validate, that the first player played
   nothing from hand on turn 1 and the second one card on turn 2, and
   that no module from cogs/ or discord is in sys.modules at the end.
   tests/test_tftcg_rules.py: the hand of three; the draw and the
   reshuffle, and the reshuffle during a flip; the three plays once
   each and in any order; the first two turns' restrictions; the flip
   and its face; an Upgrade into its slot and the old one scrapped,
   its bonus in the totals; the tapped rule for defenders and the
   any-defender rule; the flip counts with Bold and Tough, locked at
   the combatants; each icon's effect as the card turns and white's
   two more once a side; Pierce as a floor capped by the Attack (the
   ER §1.3.3 cases); the counters and the KO, the KO'd character's
   Upgrades to the scrap pile; the extra attack and attacking out; the
   untap of all; the end of turn's cleanup; the game's end.
   tests/test_tftcg_prompts.py: a fixture per PromptKind and per owed
   step, asserting exactly one of pending_prompt and owed_step answers,
   and the asked_player and may_press of each.
   tests/test_tftcg_driver_actions.py: driver.ANSWERS covers PromptKind
   exactly and MODEL_STEPS covers FollowOnStep exactly.
   tests/test_tftcg_history.py: after a seeded turn with an attack
   whose flips reshuffled the deck, replaying the journal from the
   turn-start snapshot reproduces to_dict byte for byte; the two coarse
   undos restore the exact earlier dicts and the prompts that go with
   them; a draw closes the fine undo's earlier points and a flip does
   not; the journal is empty after begin_turn and the snapshots are
   bounded to three. tests/test_tftcg_effects.py: UNIMPLEMENTED equals
   the exact set this step leaves (list it), so a card can only leave
   it with a handler. tests/tftcg_positions.py: the helper that stages
   a position by code -- put(match, player, code, face=..., tapped=...,
   damage=..., upgrades=...) -- because the cards are fixed data, not a
   roster the author revises, so naming by code is right here where
   D12 Ball names by role; say so in its docstring.

Nothing in this step imports discord, renders anything, or saves to
disk. Record in docs/design/tftcg.md: the prompt kinds and what each
asks and of whom, the owed steps, the attack as a state on the match,
the snapshots and the journal (decision 12) and which actions close an
undo point, the vanilla engine and UNIMPLEMENTED, the saved-fields
table, and the by-code test helper.

Done when: the full-game test passes, UNIMPLEMENTED is pinned, and the
purity ratchet covers the new packages.

Stop: a transcript of the seeded game, printed by the test with -v,
read by the author for its wording -- every attack's arithmetic in
particular.
```

### 3. The lobby, the channel and the board

Two seats in a `/tftcg create_game`, Start, and the opening position in
a channel of its own: the first turn's message pinned with the board,
the turn's lines and **My hand**, a hand each that the other cannot
see. The board's first drawing is this step's, and its look is reviewed
on this PR (question 11).

```text
Step 3 of docs/tftcg-bot.md. Steps 1 and 2 have landed. Also read
gamesaves/codex/service.py and storage.py (the shapes you copy),
cogs/codex/core.py, lobby.py and presentation.py, cogs/codex_views/base.py
and lobby.py, cogs/codex_helpers.py, cogs/d12ball_boards.py (the gate
and its parameters), docs/design/rate-limits.md, docs/design/
permissions.md, docs/design/hub-and-lobby.md and codex/render.py
(render_panel, compose_board, preload_pictures, bundled_bytes). Four
commits: the service and its file; the lobby and the channel; the
board; the hub line.

1. gamesaves/tftcg/service.py and storage.py, copied from the Codex
   service: GameService(engine, games, batching, save) with announce,
   game, load, persist, save, waiting_on, standing, next_game_number;
   the lobby doors create_game, discard_game, take_seat, leave,
   set_board_layout, start, abandon, drop_games; apply_action, resume,
   run; the undo doors over tftcg/history.py; GameResult with the
   standing prompts and no prompt on the wire, for the same reason the
   Codex result has none: a prompt lists a hand. storage.py over
   gamekit.storage, data/tftcg_games.json, no legacy migration, no
   mkdir on load. tests/save_patches.py's tables list the new modules.
   tests/test_tftcg_game_service_setup.py: the lobby doors over the
   record's rules, a refusal carrying its cite, start dealing three and
   putting every character in alt mode, the one save per door.

2. The lobby and the channel. cogs/tftcg/lobby.py: /tftcg create_game
   opens the game's venue as the Codex bot's does (a channel under
   "TF TCG Games", a thread where the bot may not make one, the channel
   it was typed in where neither; the record's venue) and posts the
   lobby there: LobbyView, persistent -- Play Autobots, Play
   Decepticons (the starter's two teams, each named with its characters
   and stars in the lobby text), Leave, and Start for either seated
   player once both seats are taken; a seat's team is shown on the
   lobby as it is taken; the lobby message is edited by the clicks that
   change it, in their own responses. Start: the channel named
   tftcg-<n>-<p1>-vs-<p2> (CHANNEL_NAME_PATTERN in tftcg_helpers), the
   first player picked by engine.rng, the deal, and the first turn's
   message posted with the board, the turn's heading and lines, and
   TurnMessageView: My hand (the hand pictured, ephemeral, to either
   seated player -- the panel is step 4's, so in this step both get
   the hand alone), Scrap (either scrap pile, ephemeral, to anyone
   in the game), Deck (the counts and the KO areas in words), Swap
   view, and the slots for Undo and Concede that steps 4 and 8 fill.
   The gates are cogs/game_auth.py's, read with is True. The board
   message is the turn message, through BoardRefresher(self,
   keep_view=TurnMessageView, links=always, message_of=turn_message_id,
   text_for=the turn's text, label="TF TCG"), as the Codex bot builds
   it. cogs/tftcg/core.py: lifecycle, the service property, the locks,
   DiscordBatching, render_prompt and view_for_prompt (MAIN_ACTION and
   the rest mapped in step 4; GAME_OVER's line here), restore_saved_views
   re-arming LobbyView and TurnMessageView on start, preload_pictures
   at cog_load off the loop. cogs/tftcg/presentation.py: the board
   render through asyncio.to_thread, the turn message's post, a hand
   sent to its owner alone (render_hand). cogs/tftcg/slash_commands.py:
   /tftcg games, board, hand, resume (the current prompt put up again
   from the one reading, the board brought back down the channel).
   tests/tftcg_cog_fakes.py, copied from tests/codex_cog_fakes.py with
   this bot's routes, and tests/test_tftcg_cog_lobby.py: a lobby to the
   opening position with the fakes, the requests per click counted (the
   lobby's edits in the click's response, one channel send for the
   turn message, one pin), the hand never in a public send or edit.

3. The board. tftcg/render.py, the one module importing Pillow: the
   board as two panels drawn element by element from the imported
   faces and the marks, as codex/render.py draws Codex's (copy its
   scaffolding -- DRAW_SCALE, scaled_card, the chit and tag helpers,
   compose_board's three layouts, the WebP output, bundled_bytes and
   preload_pictures -- and draw this game's elements). A panel: the
   side's characters in a row, each as the face that is up at a size
   that holds four across (the starter's teams are two; a team may be
   five), a tapped one turned on its side at full size in a square
   cell as Codex's exhausted cards are, its damage as chits in its
   corner, its three Upgrades as small cards tucked under it in the
   slot's place -- Weapon lower left, Armor lower right, Utility below
   -- with the slot's mark on an empty place, an "ATK 5 / DEF 1" plate
   where modifiers change the printed numbers; the KO area as a
   greyed row beneath; the played area beside the row -- this turn's
   Actions face up, a Secret Action as the card back; the nameplate
   along the outer edge with the player, the team, and DECK, HAND and
   SCRAP as a word and a count each, the active player's carrying
   "<team>'s turn <n>". The battle strip between the panels while
   match.attack is set: the attacker's face and the defender's, their
   flipped cards in order each with the icons that counted ringed, and
   the headline's arithmetic in words. Stacked, the far side turned
   whole to face the near one with its nameplate upright, as the
   author chose for Codex; side by side under Swap view; the layout on
   the record. render_hand for the hand's picture: the cards numbered,
   each with its icons shown. scripts/render_tftcg_sample.py draws the
   opening position, a mid-game position staged with
   tftcg_positions.put (Upgrades on, a tapped character, damage, a KO)
   and a position mid-attack with the strip, in both layouts, into a
   folder for looking at. Put the pictures in the PR; the author's
   review of them is question 11's, and what it changes is written
   into the design note.

4. The hub line. cogs/d12ball/... -- the one file this step touches
   outside its own, named here: the hub's text gains a third line with
   the command mention </tftcg create_game:ID> read from
   data/tftcg_command_ids.json through gamebot.read_command_ids, the
   command's name in plain text when the file is absent, beside the
   Codex line and in its shape; the wording is the author's, asked on
   this PR. tests/test_d12ball_hub.py (or wherever the Codex line is
   tested) gains the third line the same way.

Record in docs/design/tftcg.md: "The service and its file", "The lobby
and the channel", "The board on Discord" (what is drawn and from what;
what the author changed on review), "Hidden information on Discord"
(the hand, the scrap piles on request).

Done when: two people reach the opening position on Discord; the tests
above pass; the three sample pictures are in the PR.

Stop: the author looks at the opening board, a mid-game board and the
battle strip, in both layouts, and says what is wrong with them.
```

### 4. The turn on Discord, and the undos

The whole of a turn, on the vanilla engine, driven from the active
player's ephemeral panel, with the defender's question as a public ask:
the turn message that is the turn's running summary, the three plays,
the attack with its defender and its flips, the arithmetic as a
headline, the extra attacks and the untap, the end of turn's rollover,
the undos, and the resume path. After this step two people can finish
a game.

```text
Step 4 of docs/tftcg-bot.md. Steps 1 to 3 have landed. Also read
cogs/codex/turns.py, cogs/codex_views/turn.py and turn_message.py (the
panel and the turn message you copy), cogs/d12ball_views/base.py's
SafeView and cogs/game_auth.send_new_prompt (the public ask's shape),
docs/design/maneuver-prompt.md (why a prompt is never edited, and what
the public ask does differently and why), docs/design/recovery.md and
docs/design/rate-limits.md again, and docs/design/codex.md "The undos".
Four commits: the turn message and the gate; the panel and the main
phase; the attack, the ask and the turn's end; the undos and resume.

1. The turn message. When a turn begins the cog posts the turn's
   message: "**Turn <n>** -- @player (<team>)", the mention notifying
   the new active player, and the lines the owed steps said at the
   turn's start (the draw as a count, the start-of-turn triggers), the
   model's lines with their tokens rendered at the door; its attachment
   the board; its buttons TurnMessageView's. It is pinned and the
   previous turn's message unpinned, the rollover post_new_play_board
   does for D12 Ball and draw_after does for Codex. After every action
   it is edited, through the gate, with the new lines and the
   re-rendered board; when the turn ends it is edited a last time,
   without its buttons, and stands. The text stays under 2000
   characters: past that, the earliest lines fold into "and n more",
   since the board carries the position. A cascade of the bot's own
   steps -- the damage, the KO, the post-attack triggers, the untap of
   all, the game's end -- is one edit. There is no other public message
   per action but the asks of commit 3, and no embed anywhere.

2. cogs/tftcg_views/turn.py: TurnPanelView, the control panel, built
   from MainActionOptions and nothing else. Its picture is
   render_hand's -- the cards in the hand as their own faces, numbered,
   greyed where not playable now -- re-rendered with every edit of the
   panel. Its controls: a select Flip listing the characters that may
   flip, each with the face it would show; a select Play an Action
   listing each playable Action by its number in the picture, its name
   and its icons; a select Play an Upgrade listing each playable
   Upgrade the same way, which opens a second select of the characters
   it may go on with the slot it would take and what it would scrap; a
   select Tap ability (empty and absent while none exists); a row of
   buttons Attack (opening the attacker select, commit 3), End turn
   (disabled with its reason as the label while the required attack is
   not done), and Undo (commit 4). Each click answers through
   SafeView.apply; the result's lines go to the turn message, the
   board through the gate, and the panel is edited in place
   (interaction.response.edit_message) with the new options. A click
   by anybody but the active player is refused ephemerally. My hand on
   the turn message creates the panel afresh for the active player
   (ephemeral), and so does /tftcg resume for them; the cog never
   looks for an old panel.

3. The attack, the ask and the turn's end. CHOOSE_ATTACKER and
   CHOOSE_DEFENDER render in the panel as selects of AttackerOptions
   and DefenderOptions -- each defender labelled with why it is legal
   ("tapped", "no tapped enemy") -- with Cancel back to the actions
   while the attacker is not yet tapped (choosing the attacker taps it,
   ER §1.3.1, so after that there is no cancel but an undo). FLIP_CARDS
   for the attacker renders in the panel as Flip, with the count it
   will flip; the click runs the attacker's flips and, when the
   defender has nothing to decide before theirs, the defender's too,
   the damage and the post-attack as one chain, one edit of the turn
   message with the battle strip, and the panel re-rendered on the
   extra attack it may offer, or on End turn. A prompt whose
   asked_player is the other seat -- FLIP_CARDS with something to
   decide (none in this set), GREEN_SWAP for the defender's green
   flips -- is a public ask: cogs/tftcg_views/ask.py's AskView, sent
   through send_new_prompt with the question in words and a mention,
   its buttons from the prompt's options -- Pass, and Answer where the
   choice touches the hand, which opens the ephemeral choice (the hand
   pictured, the green cards offered, a select) -- and edited to its
   outcome by the click that answers it, in that click's own response;
   a helper may answer through the confirmation game_auth has. The
   active player's panel meanwhile says "waiting on @player: a green
   swap" with its controls disabled. GREEN_SWAP for the attacking
   player renders in the panel the same way, no ask. End turn runs the
   owed end-of-turn chain and the rollover: the old message's last
   edit without buttons, the new turn's message with its mention.
   GAME_OVER renders as a public line naming the winner and the final
   board, with the Rematch button for step 8 left out for now.

4. The undos and resume. Undo on the turn message opens, to the
   active player alone (UndoView, ephemeral), the targets
   history.undo_targets gives: the fine undo's points named by the
   action each would take back ("before Megatron attacked"), To the
   start of my turn, and To the start of the previous turn, which
   posts a public confirmation the opponent answers with a button of
   their own (or a helper, through HelperConfirmationRequired); on
   confirmation the previous turn's message is edited back to its
   first lines plus "undone to the start of the turn" with the
   restored board and pinned again, the current turn's message is
   deleted (the one deletion in the flow), and that turn's player gets
   a fresh panel. A point closed by a draw is not offered, and the
   view says why in one line. The cog decides nothing about what a
   snapshot holds or which undos exist. /tftcg resume and My hand
   rebuild whatever the one reading says is pending -- the panel, or
   the ask re-sent -- and restore_saved_views re-arms the turn
   message's view on start. tests/test_tftcg_cog_turn.py drives a
   whole turn through the cog with the fakes: each panel edit is an
   edit of the ephemeral message, not a channel send; the public
   requests per action are one edit of the turn message through the
   gate; an attack with a green flip for the defender is one send (the
   ask) and the ask's one edit in the answering click's response; the
   hand never appears in a public send or edit; a stale panel's click
   is refused with the driver's words; an undo to the start of the
   turn leaves the turn message, the board and the panel showing the
   restored position; the previous-turn undo waits for the opponent's
   button. tests/test_tftcg_resume.py: a match saved mid-attack
   resumes to the same prompt from My hand and from /tftcg resume, and
   a pending ask is sent again, once.

Record in docs/design/tftcg.md: the panel, the turn message and the
gate, the public ask (decision 8: what it is, what it costs, why not
the panel or the turn message), the flips (decision 9: which wait and
which are owed), the request count per click and its bucket, the
undos and who may take each, and the resume path. Measure the requests
per click with the fakes and write the number in the PR.

Done when: two people finish a game on the vanilla engine; a bot
restart mid-turn resumes from My hand; all three undos work; the tests
above pass.

Stop: a whole game played by the author and the other developer on the
test server, with the request counts in the PR, one green swap
answered from an ask, and one undo taken.
```

### 5. The battle's fine print and the keywords

The keywords the set uses and the ones the next waves use, the green
swap, the ordering of triggers, Secret Actions as a shape, and the
three post-cancellation changes -- every keyword ruling on the site's
pages a test. After this step the engine's battle is the rules' battle,
and step 6 has only the cards' own text to do.

```text
Step 5 of docs/tftcg-bot.md. Steps 1 to 4 have landed. Also read
codex/keywords.py and docs/design/codex.md "The keywords" and "Which
choices an attack asks, and which it does not" (the shape of a keyword
table and of an attack that asks only where a choice exists), and the
site's pages for each keyword and term named below (the rulings are
in tftcg/data/rulings.json; cite each by its date). Three commits: the
keywords; the triggers and the swap; Secret Actions and the changes.

1. The keywords. tftcg/keywords.py becomes what the engine reads:
   per rules key and face, the keywords with their X, what adds and
   what does not (ER §6 -- Bold, Tough, Pierce, Focus and Safeguard
   add; Plan does not), and the engine's questions over it:
   flip_count with Bold and Tough from the face, the Upgrades and the
   modifiers; pierce_total; legal_defenders with Stealth (enemies
   attack other characters if able) and Brave (enemies attack this if
   able), the two cancelling on one character (Wizards, 2019-02-11),
   and neither overriding the tapped rule (2019-03-01); Safeguard X --
   an undamaged character takes at most X at once, the values adding
   and a higher number weaker (ER §6); Focus X -- before the flipping
   player flips, they look at the top X and scrap any, the values
   adding into one look -- as FLIP_CARDS's before-the-flip decision
   (FlipOptions.focus: the cards seen, ephemeral to the looker, with
   a scrap-any choice; the look closes the fine undo's earlier points,
   decision 12); Plan X -- up to X cards from hand on top in any
   order, a "may" (2019-02-22) -- as the PLAN prompt; hybrid icons
   counted only with the matching trait on the battling character.
   tests/test_tftcg_keywords.py: a test per keyword with the rulings
   as docstrings, by position staged with tftcg_positions.

2. The triggers and the swap. The resolve stack carries the pending
   rule whole: triggers from one event are queued to the attacking
   (active) player's first, then the defending player's; a player with
   two or more at once is asked their order (ORDER_TRIGGERS, a public
   ask for the defender, the panel for the active player) and never
   asked for one; an ability that triggers while another resolves goes
   first (ER §4); a trigger whose source has flipped, left or been KO'd
   still resolves; an Upgrade put inside an Action waits for the
   Action (ER §7); a card played from inside an Action queues its
   triggers behind the Action (ER §2). The green swap: after the
   attack, each player who flipped a green card may exchange one card
   from hand for one of them (GREEN_SWAP, the attacker's first, ER
   §1.4), the swapped-in card into the played area to be scrapped at
   the end of the turn; the shuffle's exception (ER §5: cards an Action
   or ability scrapped earlier in its own resolution wait). The battle
   strip shows the swap. tests/test_tftcg_triggers.py: the ordering
   cases of ER §4's two examples staged with Wave 1 cards whose text
   is still UNIMPLEMENTED but whose triggers the test wires by hand
   through the stack, so the machinery is tested before step 6 gives
   it cards; and tests/test_tftcg_green_swap.py.

3. Secret Actions and the changes. The shape, with no card of the set
   to use it (Wave 3 brings thirteen): play_action with face_down puts
   the card in the played area as a card back, its hold choice --
   reveal when it can, or ask me -- recorded on the instance and
   hidden with it (decision 10); the reveal windows the texts name
   (when one of your characters defends, as your opponent plays an
   Action, before your opponent chooses an attacker, and the rest the
   data holds), each a point where the engine asks, for a held card,
   REVEAL_SECRET of its owner (a public ask: Reveal, Pass -- the ask
   says nothing of whether the condition is met, and a Reveal whose
   condition is unmet is refused privately) or reveals a card held to
   reveal itself; a revealed card resolves its When Revealed and stays
   in the played area; the defending player's unrevealed Secret
   Actions are scrapped face up without effect at the end of the
   turn (ER §1.5); every face-down card is revealed at the game's end
   (ER §1.6); playing one counts as playing an Action (2019-03-01);
   its owner may look at it (an ephemeral picture from the panel).
   The three post-cancellation changes: black's Pierce until the end
   of the battle (already so from step 2; the test names the rule);
   an "any number" move of damage capped by the receiver's remaining
   Health (a DOES part, used by Dinobot Sludge in step 10); two
   opposing icon-colour changes cancelling (a part, used by
   Bellicosity and End Hostilities later). tests/test_tftcg_secret_actions.py
   with a card of Wave 3 wired by hand as above; tests/test_tftcg_rule_changes.py.

Record in docs/design/tftcg.md: "The keywords", "The triggers and the
pending rule", "Secret Actions" (decision 10 as built), "The three
changes".

Done when: every keyword ruling on the site's keyword, mode and term
pages that names a keyword of this step is a test, and the suite is
green.

Stop: Stealthiness on Bumblebee turns Megatron's attack onto Windblade
on the test server; the author reads the defender list's reasons.
```

### 6. Every card of the starter set does what it says

The texts, as data: the triggers, the costs, the targets, the nested
plays, the modifiers, the granted keywords and the statics, part by
part in `EFFECTS` and card by card in `TEXT`, until `UNIMPLEMENTED` is
empty over the twenty-five. After this step the starter set is the
real game.

```text
Step 6 of docs/tftcg-bot.md. Steps 1 to 5 have landed. Also read
codex/effects.py whole (Part, Effect, Cost, EFFECTS, TEXT, the static
tables) and codex/flow/resolve.py (DOES, the frames), and
docs/design/codex.md "Targeting and the effects" -- the shape you fill
with this game's parts. Three commits: the parts and the targets; the
cards; the tests and the empty set.

1. The parts. tftcg/effects.py's Part, Effect and Cost as Codex's,
   with this game's does -- draw(n), draw_per(count), damage(n, to:
   target or each_enemy), repair(n), scrap_upgrade(target), scrap_top,
   may_play(kind: action or upgrade, from: hand or the scrapped card),
   modify(stat or keyword, amount, until: turn or battle, target),
   delayed(part, at: end_of_turn, target), tap(target) as a cost --
   each a key in resolve.DOES; the target kinds -- an enemy, one of
   your characters, an enemy Upgrade, one of your untapped characters
   with 5★ or more -- each a key RulesEngine.target_candidates answers,
   and TARGET asked only where more than one candidate exists, as
   Codex's attack asks only where a choice exists; "may" as a Pass in
   the options; a mandatory part with no candidate skipped with a line.
   The triggers TEXT names: when_flipped_to(face), when_upgraded (this
   character gets an Upgrade), when_defends, after_attacks, on_put
   (an Upgrade put on a character), at_end_of_turn; the statics:
   grants(keyword, X) for an Upgrade or a face, stealth; the costs:
   tap a character meeting a condition. CHOOSE_FROM_HAND for a card
   from hand where a text asks one (none in the set; the kind exists
   from step 2).

2. The cards. TEXT for every rules key of the set, beside the printed
   sentence: Windblade's flip trigger; Megatron's when_upgraded; the
   two Bold and the one Tough faces through keywords.py; Pep Talk,
   Equipment Enthusiast, Strafing Run, Supercharge, Surprise Attack,
   Reckless Charge with its delayed part, Rest and Relaxation,
   Vaporize, Inferno Breath with its tap cost, New Designs' extra
   Upgrade play inside the Action with the put-triggers waiting (ER
   §7), Leap of Faith's two scrap-and-may-play parts with the played
   card an Action within an Action (ER §2) or an Upgrade that is not
   the turn's; Grenade Launcher's after_attacks scrap; Enforcement
   Batons' on_put scrap of an enemy Weapon; Security Console's
   when_defends draw and Plan, which is the defender's and asks them
   through the public ask with Answer opening the hidden choice;
   Stealthiness' stealth; the granted Bold and Tough of the Upgrades.
   The panel shows a card's cost and targets before it is chosen, and
   the turn message says what happened in the model's voice.

3. The tests and the empty set. tests/test_tftcg_effects.py: a test
   per card of the set, staged with tftcg_positions, with every ruling
   on it as a docstring (there are few; the keyword rulings are step
   5's), and UNIMPLEMENTED pinned as the empty set over the starter;
   test_every_part_is_carried_out as Codex's. The full-game test's
   policy now plays Actions with targets. tests/test_tftcg_cog_turn.py
   gains Security Console: the defender's ask with Answer, the hidden
   choice ephemeral, the ask edited to "perrytom drew a card and
   planned" with nothing of the card in it.

Record in docs/design/tftcg.md: "The effects" -- the parts, the
targets, the triggers, what is asked and what is not, the nested plays
and the pending rule as built.

Done when: UNIMPLEMENTED is empty over the twenty-five, every card of
the set has a test, and the suite is green.

Stop: Bumblebee and Windblade against Megatron and Starscream on the
test server, every card played for its text, the author reading the
turn messages.
```

### 7. The decks: the site's pre-constructed decks, and a deck a player brings

The lobby grows from the starter's two teams to the nine pre-constructed
decks the data holds and to a deck a player pastes or imports, with the
record refusing what breaks the building rules. The engine plays every
card it does not yet know for its numbers and the lobby says so, so
that a Wave 1 game can be played before step 10 makes it the real
thing.

```text
Step 7 of docs/tftcg-bot.md. Steps 1 to 6 have landed. Also read
tftcg/game.py's legal_team (step 2 wrote it for this step),
docs/design/game-service.md "setup and the lobby", and the site's deck
page format (a deck's page lists its characters as "Name N★ Subname"
and its battle cards under Actions, Secret Actions, Rolling Actions,
Weapons, Armor and Utilities as "<count> <name>"). Three commits: the
pre-constructed decks; a deck a player brings; the lobby.

1. The pre-constructed decks. The record's team gains a source (the
   starter's two, a pre-constructed deck by name, a player's own), and
   the lobby's team choice becomes a menu: the starter's two teams
   first, then the eight two-player pre-constructed decks from
   tftcg/data/decks.json (the Unicron Raid is co-operative and is
   left out, with a line in the note), each named with its characters
   and stars. A deck whose cards the engine plays for their numbers
   alone says so in the lobby ("14 cards of this deck are played for
   their numbers alone until a later step") from effects.UNIMPLEMENTED;
   nothing is hidden about what the engine does not know.

2. A deck a player brings. /tftcg deck paste <text>: the deck page's
   own text copied in, parsed by the format above -- characters by
   name and subname, battle cards by count and name, each resolved to
   the latest allowed printing by name through the catalog, a name
   that resolves to nothing refused by name -- then legal_team, whose
   refusal names the rule it breaks with its cite (26 stars: "R1
   §1.1"; a fourth copy; two of one character; a stratagem without
   its target: "ER §8"), and the deck saved on the record under the
   player's seat. /tftcg deck import <url>: a transformers.cards deck
   URL (/deck/<id>/<slug>), fetched once through the site's o8d export
   (/export?dl=octgn&deck=<id>) with the request made in a thread, a
   timeout and no retry, and read as the paste is -- the one outbound
   request any of the three bots makes, on a human's command, never
   in a game flow, and written up as such in the design note (question
   8; if the author says no, the command is not built and the paste
   stands). The ban list as a game setting, off by default, applied by
   legal_team when on. tests/test_tftcg_decks.py: the parse of each of
   the nine decks' page text round-trips to decks.json; each refusal
   with its cite; the o8d reader over a saved export.

3. The lobby. LobbyView: the team menu, and Bring a deck, which tells
   the clicker the two commands; a seat shows its team's name,
   characters and stars; Start refuses while a seat has no team. The
   board's row holds a team of five, and the nameplate names the deck.

Record in docs/design/tftcg.md: "The decks" -- the sources, the parse,
the legality, the one network request and its rules.

Done when: a game between two pre-constructed decks starts from the
lobby; a pasted deck of 26 stars is refused with "R1 §1.1"; the suite
is green.

Stop: the Thunderbee starter against the Timecop starter on the test
server, the lobby saying which of their cards are still numbers.
```

### 8. Finishing a game: concede, abandon, rematch, the golden

The end of a game and what comes after it, and the seeded whole game
pinned byte for byte, which is the safety net every later step stands
on.

```text
Step 8 of docs/tftcg-bot.md. Steps 1 to 7 have landed. Also read
cogs/codex/ending.py and cogs/codex_views/ending.py (the shapes you
copy) and tests/test_codex_golden.py. Two commits: the endings; the
golden.

1. The endings, copied from the Codex bot's: Concede on the turn
   message and /tftcg concede, behind a second click; /tftcg abandon,
   a player's own game or any for a helper; GAME_OVER's final board
   with the winner's line, a Rematch button (RematchView, persistent)
   that opens a new game with the same seats and teams and the first
   player switched (R1 §1.3), and the finished channel moved to the
   "TF TCG Archive" category; /tftcg admin reset_channels. Every
   face-down Secret Action is revealed in the final lines (ER §1.6).
   tests/test_tftcg_cog_ending.py with the fakes.

2. The golden. tests/test_tftcg_golden.py: a seeded whole game of the
   starter's two teams through GameService with the default Batching
   and the full-game test's policy, every GameResult and the final
   save pinned byte for byte in tests/golden/tftcg_service_transcript.txt
   and tftcg_service_final_match.json, reusing GOLDEN_DIR, UPDATING,
   golden_diff and render_final_match from test_golden_transcript as
   the Codex golden does; re-recorded with FOOLBOT_UPDATE_GOLDEN=1 only
   for a change to the model's wording or the game, which the PR says;
   test_nothing_hidden_is_written keeps hands and looks out of it.

Record in docs/design/tftcg.md: "The end of a game", "The golden".

Done when: a finished game ends cleanly, offers a rematch and is moved
aside; the golden is recorded; the suite is green.

Stop: the author reads the golden transcript whole.
```

### 9. The look back: what the Codex bot and this one share moves to one home

Steps 1 to 8 copied Codex's shapes by name. This step diffs the copies
against their originals and moves what is byte-identical -- or
identical but for the game's name -- into `gamekit/` or `botkit/`, with
both games' modules re-exporting the old names and both suites passing
unchanged. The Codex look back did this once for D12 Ball and Codex;
this is the same pass with three games to read.

```text
Step 9 of docs/tftcg-bot.md. Steps 1 to 8 have landed. Also read
docs/design/codex.md "What the two games share" and "Where the line
was drawn" (what was and was not moved last time, and why -- a common
base class is a design change, not a move), gamekit/ and botkit/ whole,
and tests/test_shared_kits.py. One commit per move, each small.

Diff each copied module against its Codex original: tftcg/history.py
against codex/history.py; gamesaves/tftcg/service.py's classes
(Batching, Narration, GameResult, StopHandling's use) against
gamesaves/codex/service.py's; cogs/tftcg_views/base.py's SafeView
(apply, the gates, picture_file, kept_pictures) against
cogs/codex_views/base.py's; the turn message's rollover and the panel's
put against cogs/codex/turns.py's; tftcg/flow/result.py and
tftcg/flow/driver.py's loop against codex/flow/'s; tftcg/tokens.py's
render against codex/tokens.py's; the cog fakes against
tests/codex_cog_fakes.py. For each that is identical, or identical but
for a name the caller can pass: move it to gamekit/ (model) or botkit/
(Discord), make both games import it, keep both old modules re-exporting
the old name, and run both suites unchanged -- the Codex golden, the six
D12 Ball tests and this bot's golden must not re-record. For each that
differs, say in the design note where the line is and why it stays each
game's. tests/test_shared_kits.py's ratchets (no discord, no Pillow, no
game imported, nothing async in gamekit) cover what moved. Do not
introduce a base class; what would need one stays copied, as last time.

Record in docs/design/tftcg.md "What the three games share", and in
docs/design/codex.md's "What the two games share" a line pointing at it.
CLAUDE.md's gamekit/ and botkit/ rows list what moved.

Done when: nothing copied in steps 1 to 8 remains byte-identical in two
places; the three suites are green and no golden re-recorded.

Stop: the diff of gamekit/ and botkit/ before and after, read by the
author for what moved and what did not.
```

### 10 to 15. After the starter set

The waves, in their own order, each a step: the step reads the wave's
cards from the data, its mechanics from the site's mode, trait and
keyword pages and the wave's FAQ, implements every card's text with its
rulings as tests, and ends with `UNIMPLEMENTED` empty over the wave.
Each is large; the community waves are several PRs. **Their prompts are
written when step 9 lands**, in the shape of steps 5 and 6, once the
starter set has shown what the effect parts look like; a routine, if
one runs this series, stops on a step with no prompt and says so. What
each step is for, so that steps 1 to 9 are written to fit:

- **10. Wave 1 whole** (121 cards, 40 characters): every Wave 1 card's
  text, with the Metroplex deck's deployables (a Titan with three
  characters under it), the Energon Edition and the convention pack;
  "your opponent chooses" and "look at your opponent's hand" as asks;
  "any number" damage moves under the capped rule (Dinobot Sludge).
  The starter's engine is built to hold a team of five and a character
  with cards under it.
- **11. Wave 2: Rise of the Combiners** (133 cards): the combiner cards
  (Devastator, Menasor, Superion, Volcanicus, Optimus Maximus, Predaking
  and their Enigmas), Triple Changers (Alt 1, Alt 2, Bot), the
  Devastator set's Tower; a character whose faces are more than two,
  and a character made of several, each kept on the record for the
  stratagems to name later.
- **12. Wave 3: Siege I** (112 cards): Battle Masters (bot mode and
  Upgrade mode, no alt, in bot mode from the start, played as the
  Upgrade when KO'd), the thirteen Secret Actions of decision 10 in
  play, the Blaster and Soundwave sets' Mini-Cassettes under their
  carrier, "start of game" searches (Wizards, 2019-04-26).
- **13. Wave 4: Siege II** (120 cards): Weaponizers (a character whose
  other face is an Upgrade for another), more Triple Changers, bot-only
  and alt-only characters, Trypticon; Safeguard in play.
- **14. Wave 5: Titan Masters Attack** (142 cards): heads and bodies (a
  Titan Master's head riding a body in either mode and deploying as a
  character when the body is KO'd), stratagems with their targets (ER
  §8) in the team's legality and on the record, hybrid icons in play,
  the Fortress Maximus set.
- **15. Waves 6 to 10, the community's** (454 cards and the outliers):
  Rolling Actions (a permanent Action that spins up), Stations, the
  Junkion keywords Bandit and Drifter, the Mercenary Bounty, the
  Decepticon Revenge, Oppress, the Void and Channel where the data has
  them, the replacement cards and the ban list as data; the last card
  in the data covered by the ratchets.

## What is not in these prompts, on purpose

- **Waves 1 to 10, in steps 1 to 9.** They are steps 10 to 15, with
  prompts written once step 9 has landed. Everything in steps 1 to 9
  is written so that they fit: a character with any number of faces, a
  team of up to five with cards under a character, the slots as data,
  the stratagem target on the record, every wave's data and art
  imported at step 1. Nothing in steps 1 to 9 builds them.
- **An AI opponent.** Decision 14. The first one worth writing is a
  random legal player for the tests, not an opponent.
- **Sideboards, best-of-three, tournaments, the formats.** Single
  games; the record can hold a sideboard later; the ban list is a
  setting from step 7.
- **The Unicron Raid and any co-operative or multiplayer play.**
  Two seats; nothing in the state assumes more than two players except
  the seats, and nothing is built for more.
- **A web page or a Godot client.** `tftcg/wire.py` exists from step 2
  so that one costs nothing here; no client is written.
- **Statistics and an archive export.** As the Codex bot: the event
  log stays in the save, a finished channel is moved to the archive
  category, and nothing is written from it or read out of it.
- **A cloud routine for the series.** None is created by this plan;
  "Claiming a step" says how one is added when the author asks.
- **A test of how the board looks.** The author's rule for everything
  rendered: render it and look.
- **Anything from teletraan1.net.** It is a different game (question
  2).
- **A rulebook of our own.** The bot cites a section; it reprints
  none. The rules pages are committed for the developers to read.

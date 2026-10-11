# The Codex bot's multiplayer modes: free-for-all and two-headed dragon

**This is a worksheet, not a specification.** It was written on
2026-10-10 from the author's ask -- the two multiplayer modes of
Sirlin Games' *Codex*, **free-for-all** (3 to 5 players, every base its
own) and **two-headed dragon** (two teams of two, one base a team) --
for the Codex bot that [codex-bot.md](codex-bot.md) built, and revised
on 2026-10-11 against the official rulebook and with the author's
answers to its questions. It is written against the rules as the
official rulebook has them, against Sirlin's rulings in
`codex/data/rulings.json` (seven name the modes), and against what the
bot is on `main` on 2026-10-10: steps 1 to 13 of the Codex series
landed, every printed card playing, the two undos on the turn message
(PR #525). Each step below has a prompt a Claude Code session is
started with. Strike a step when it lands and move what it settled into
[design/codex.md](design/codex.md). **Nothing in it is a rule.**

**The sources, in order** (the author, 2026-10-11). **The official
rulebook and the card database's rulings are the official source of the
rules.** The rulebook is the Core Set's, "Rulebook version 46" (2016),
committed at `docs/codex/Codex_Core_Set_Rulebook.pdf` and cited here as
`Rulebook p. n` by the number printed at the foot of the page (its
contents table lists the two modes one page later than the pages are
numbered: Two-Headed Dragon is p. 13, Free-for-all p. 14). The rulings
are the database's, imported whole into `codex/data/rulings.json`, and
govern where they and the rulebook's text differ, as the Codex series
already holds. The Unofficial Manual Rewrite v1.3
(`docs/codex/Codex_UMR_v13w.pdf`, `UMR p. n`) is useful and sometimes
wrong: it is cited below only where it adds a detail the official text
lacks, each such detail marked as the UMR's, and "Where the UMR differs
from the rulebook" lists every place the two were found to disagree on
these modes, with the rulebook's reading taken.

## What was found, and what it settles

### The two modes, in the terms the code will use

Both are played as the basic or the standard game with changes, so each
is a third axis on a game beside its hero count: `mode` (basic,
standard) says how many heroes a seat plays, and the new **variant**
says how many seats and how they stand to each other -- the **duel** the
bot plays today, a free-for-all, or a two-headed dragon. The author
confirmed both modes in the basic game as well as the standard one
(2026-10-11). What each adds, read from the rulebook and the rulings:

**Free-for-all** (3 to 5 players; Rulebook p. 14, with p. 4, 5, 9, 11
and 19):

- **Setup** (p. 14, 9). Who goes first is drawn at random, as in every
  game (p. 9); the players are numbered from the first in turn order,
  which for the bot is the lobby's seat order from the first seat drawn.
  Player 1 starts with 4 workers, players 2 to 5 with 5. **Player 3
  gets one 1/1 neutral Mercenary tech 0 unit during their first upkeep,
  players 4 and 5 two and three** -- it arrives then, without haste, so
  it cannot attack on its owner's first turn. The Mercenary is already
  in the card data as a token (`mercenary`, `kind: token`) and its face
  is cut from the module's token sheet (`scripts/import_codex_cards.py`,
  `tokens/mercenary`).
- **The ending** (p. 14). No elimination: the game ends when any base
  is destroyed, and at that moment the base with the most hit points
  wins. A tie for the most: the tied players each take one more turn,
  then the same comparison, repeated while the tie holds. The UMR adds
  that the current player's turn finishes first (UMR p. 12), which the
  rulebook neither says nor denies; built the UMR's way (question 13).
- **Repairing the base** (p. 14): an ability every base has in this
  mode, 3 gold to repair 1 damage, any number of times a turn.
- **Free gold** (p. 14): 1 gold each time the active player kills an
  enemy unit on their turn, to 3 gold a turn -- a unit, so never a hero
  or a building.
- **Lending patrollers** (p. 14). After the main phase, at the lock, a
  player may put their units and heroes in any open slot of any other
  player's patrol zone. The borrower gains control and the lender loses
  it; a lent card that dies goes to its owner's discard pile (a hero to
  its owner's command zone, by the general rule) and the owner gets the
  scavenger's and technician's bonuses; the exchange of control triggers
  no Arrives abilities and changes nothing on the card (its runes stay);
  every lent card comes back during the borrower's upkeep, to its
  owner's play zone and not their patrol zone. So a lender cannot
  protect the opponent whose turn follows their own.
- **A destroyed hero** (p. 11). Whenever a hero dies, one in-play hero
  *opposing* its owner levels up twice, **the active player choosing
  which** when there are several, and only one that can still level.
  With several opponents the choice is wider than a duel's: the active
  player may give the levels to any hero of any opponent of the dead
  hero's owner, their own included. The existing `LEVEL_GAIN` prompt is
  that choice.
- **The tower** (p. 4; the General group's tower rulings). One
  detection a turn: the first stealth or invisible attacker of its owner
  on each opponent's turn cannot ignore the patrollers; on its owner's
  turn it reveals one thing. Its damage falls only on an attacker of
  something its owner controls (the free-for-all ruling).
- **Armor** (p. 19) refreshes each turn, so a squad leader's refreshes
  on every opponent's turn (the Ironbark Treant ruling agrees). The
  bot already refreshes every side's armor as each turn begins.
- **Each opponent's patrol zone protects that opponent alone.** The
  squad leader "must be dealt with first" (p. 5) within its own zone;
  nothing in the free-for-all pools the zones as the dragon does, so an
  attacker chooses an opponent and takes that opponent's priorities.
- **Overpower** (the General group's overpower ruling): the excess goes
  to something controlled by the player whose patroller was attacked.
- **Moment's Peace** ("opposing units can't attack you") removes one
  player's things from the legal defenders; the others may still be
  attacked. Today's reading, "in a game of two, they can't attack at
  all", is the duel's special case.
- **The word "opponent"** on a card. The rulebook gives no general rule,
  so the plan reads the card texts (342 cards and heroes in
  `codex/data/`: 43 say "opponent" or "opposing", 21 "opponents" or
  "each opponent"): a plural or "each opponent" is every opponent
  (Reputable Newsman's "Opponents can't play"); "an opponent" or "an
  opponent's" is one the controller chooses -- Discord's "all of an
  opponent's tech 0 and I units", Carrion Curse's "an opponent's hand",
  Captured Bugblatter's "an opponent's base" -- which is the existing
  `TARGET` prompt over rows keyed by seat, asked only where more than one
  could be chosen, as every target is; "the opponent" in a context that
  names one (the player attacked, the owner of the unit that died) is
  that one. The step that builds the mode lists every card and the
  reading it got, for the author.

**Two-headed dragon** (four players in two teams; Rulebook p. 13, with
p. 4 and 11; the rulings):

- **Setup** (p. 13). Each team shares **one base with 30 hit points**
  and loses when it is destroyed. Teammates share the base and
  information -- they may show each other their cards and discuss
  strategy at any time -- and nothing else: each has their own hand,
  codex, draw pile, discard pile, tech buildings, patrol zone, workers
  and gold, which cannot be shared. **Each has one add-on slot, so a
  team may hold two add-ons, but never two of the same.** Each player on
  the team that goes first starts with 4 workers, each on the other
  with 5.
- **The team's turn** (p. 13). Teammates take their turn at the same
  time: both collect gold from their own workers in the team's upkeep,
  both play cards and attack in the shared main phase, both lock their
  patrollers at its end. The UMR words it as one phase at a time and
  the team taking and resolving one action at a time (UMR p. 12), which
  the rulebook does not say and which is the serialisation a bot needs
  regardless: the model runs the phases for both seats and takes one
  action at a time.
- **Attacking** (p. 13). The other team's two patrol zones protect both
  of its players: a player's buildings cannot be attacked while a
  patroller in the partner's zone could be, and facing two squad
  leaders an attacker that can attack one must, the attacker choosing
  which. Nobody puts a patroller in a teammate's zone.
- **"You means you"** (p. 13). "Your units", "units you have" and an
  implied "you" ("Take an extra turn") are the player's own: the
  teammate's units get no bonus, are not counted, and the teammate does
  not act in the extra turn. **"Friendly"** is the teammate's too:
  "friendly forces means all forces you and your teammate control".
  Eleven cards and heroes say "friendly" (Aged Sensei, Bloom, Eyes of
  the Chancellor, Focus Master, Forest's Favor, Fuzz Cuddles, Helpful
  Turtle, Savior Monk, Sparring Partner, Spirit of the Panda, Verdant
  Tree); 96 say "your" or "you control". Today the engine reads both as
  the controller's seat.
- **The tower** (p. 4; the tower ruling). The rulebook's tower detects
  "the first one of those that attacks you" -- and you means you, so an
  attack on the player or on the shared base, not on the teammate's
  cards (which is how the UMR words it, p. 9). The ruling puts its
  damage on an attacker of anything "controlled by the player (or team
  in 2v2)". Both as written: detection narrower than damage.
- **Overpower** (the overpower ruling): the excess may go to anything
  with HP "controlled by the player (or team in 2v2) whose patroller
  was attacked".
- **One base, hit once** (the Captured Bugblatter and Drakk Ramhorn
  rulings): an effect that damages "the opponent's base" per something
  damages the team's one base once.
- **Moment's Peace** (its ruling): protects its caster's cards and the
  shared base, not the teammate's cards.
- **A destroyed hero** (p. 11): the opposing hero that levels is any of
  the other team's, the active player choosing -- so a kill may level
  the teammate's hero.
- **Nothing of the free-for-all's three additions**: no repair, no free
  gold, no lending.

**What both leave alone**: the five phases, the hero count and the
codex, the tech choice standing while others play, the two undos, the
journal, abandon -- each with a decision where a seat became seats
(decisions 8, 15 and 16).

### Where the UMR differs from the rulebook

Found on 2026-10-11, reading the two side by side on these modes. The
rulebook's reading is taken in every case; the UMR's is noted so that a
step reading the UMR is not misled.

1. **Mercenaries** (UMR p. 4, 12: players 3 to 5 "begin with" them in
   play, with arrival fatigue through their owner's first turn). The
   rulebook (p. 14): they arrive **during the owner's first upkeep**, so
   players before them in the order cannot attack them on the first
   round, and their fatigue is the ordinary kind.
2. **A destroyed hero's levels** (UMR p. 10: "one of your heroes gains
   2 levels" when you destroy an opponent's hero). The rulebook (p. 11):
   one opposing hero levels, the active player choosing which -- in a
   free-for-all, any hero of any opponent of the dead hero's owner.
3. **The dragon's add-ons** (UMR p. 12: "Both teammates may construct
   one add-on"). The rulebook (p. 13) adds: never two of the same add-on
   on one team.
4. **The playoff's current turn** (UMR p. 12: finish the current
   player's turn, then the tied players' turns). The rulebook (p. 14) is
   silent on whether the current turn finishes; the UMR's reading is
   built, flagged as question 13.
5. **One action at a time** in a dragon (UMR p. 12). The rulebook
   (p. 13) says the teammates act simultaneously and no more; the bot
   serialises in any case.
6. **The tower's detection in a dragon** (UMR p. 9). The rulebook says
   nothing beyond "attacks you" and "you means you", from which the
   UMR's reading follows.

### What the bot assumes today: two seats, one opponent, one base

A survey of `codex/`, `gamesaves/codex/`, `cogs/codex*` and the tests on
2026-10-10, kept here because step 1 is written from it:

- **The record** (`codex/game.py`) has four fixed fields --
  `player_1_id`, `player_2_id`, `player_1_name`, `player_2_name` -- and
  `player_specs`, `player_decks`, `rematch_specs`, `rematch_decks` and
  `kept_heroes` keyed by seat 1 or 2; `seats_of`, `seat_of`, `seat_for`
  and `seat_name` are written over the two; `take_seat` refuses a third
  ("A game has seats 1 and 2"), `may_start` checks seats 1 and 2,
  `start` passes `(specs[1], specs[2])`, `rematch` swaps `{1: played[2],
  2: played[1]}`. `cogs/game_auth.py`'s `GameRecord` Protocol requires
  exactly those two id fields, and `game_participant_ids` builds its set
  from them.
- **The match** (`codex/components.py`) holds `players` as a list in
  seat order, `player(seat)` as `players[seat - 1]`, and
  **`opponent(seat)` as `players[2 - seat]`** -- called seven times.
  `validate` requires exactly two players and `first`, `active`,
  `winner` and `conceded` in `(1, 2)`. `codex/tokens.py` refuses a
  `{player:n}` for any seat but 1 and 2.
- **The idiom `2 if seat == 1 else 1` appears 66 times**: 25 in
  `engine.py`, 8 in `flow/combat.py`, 8 in `flow/resolve.py` (where
  `_against(top)` defaults to it for an effect frame with no `against`),
  5 in `flow/turn.py` (the next turn, `begin_tech` line 860; the winner
  on a destroyed base, `damage_base` line 94; concede), 3 in
  `prompts.py` (the one standing tech seat), 3 in `render.py`
  (`stacked_seats`, `compose_board`), and 10 across `cogs/codex/` and
  `cogs/codex_views/`. The cogs also spell `player_1_id if seat == 1
  else player_2_id` five times.
- **Combat records no defending seat**: `attacking` and the `combat`
  dict hold bare refs (`unit:<id>`, `hero:<slug>`, `base`, `tech1`,
  `add_on`), and `legal_defenders`, `blocking_patrollers`,
  `_standing`, `may_be_attacked`, `damage_back`, `overpower_excess`
  and every stage of `flow/combat.py` recompute "the other seat".
  `TargetRow` keys, by contrast, already carry a seat
  (`"<seat>:<ref>"`), and effect frames may carry `against`.
- **One base a seat**: `PlayerState.base_hp`, `BASE_HP = 20`,
  `damage_base(match, seat)`, three places set `winner` (a destroyed
  base, concede, a debt unpaid).
- **The turn**: `begin_tech` hands the turn to the other seat unless
  `extra_turns` names one; `standing_prompts` lists one seat's tech
  choice; `begin_turn` readies the active seat and refreshes armor on
  every side. `board.destroy` gives a dead hero's levels to
  `match.opponent(seat)`, with `LEVEL_GAIN` asking which hero.
  `hands_visible_to` returns the one opponent while Eyes of the
  Chancellor or Flagstone Spy's look reveals their hand.
- **The cog**: the turn message pings the one active seat, the hand
  goes to the clicker's seat (`seat_for(user, active)`), concede names
  "the other", the undo to the previous turn asks the one opponent, the
  channel is `codex-<n>-<p1>-vs-<p2>`, the lobby prints a row `for seat
  in (1, 2)`, Start and the deal pass two teams.
- **The board**: `render_panel` draws one seat and is seat-agnostic;
  `compose_board` composes exactly two, stacked (the far one turned) or
  side by side; the worker card prints x4 for the seat that went first
  and x5 for the other.
- **The tests**: the golden and the full-game test seat 101 and 202;
  `codex_positions.new_game` deals two; seven tests loop or assert over
  `(1, 2)`. **There is no Codex AI**; the whole-game test's `choose`
  policy plays every seat.

Much of the flow already loops over `match.players` and is count-free:
the ready and upkeep passes, the end-of-turn clean-up, most of
`resolve.py`'s side loops, `components.validate`'s per-player checks.

### What the repository already gives

- **Tokens that arrive**: Dancers, Squirrels and the rest are tokens
  the engine makes in play, with `made_by` where a card made them and
  the ordinary arrival fatigue; a Mercenary is one made by nobody, at
  an upkeep.
- **Owner against controller**: `CardInstance.owner` and `controller`
  since step 2, `returns_to` since step 11 for a card that goes back
  (Kidnapping), and the rule that a card leaving play returns to its
  owner. Lending is a control change with its own moment of return.
- **Targets keyed by seat**: `TargetRow` is `"<seat>:<ref>"`, so a
  `TARGET` prompt over several opponents' things needs no new shape.
- **The hero-level choice is already a prompt** (`LEVEL_GAIN`, with an
  asked seat and an owner), so the rulebook's wider choice is a wider
  candidate list.
- **Lists where a seat might have been one**: `extra_turns` is a list,
  `standing_prompts` returns a list, `KEPT_SNAPSHOTS` is three.
- **A revealed hand has a picture**: `hands_visible_to` and the turn
  message's `revealed_files` already picture another seat's hand under
  the clicker's, which is where a teammate's goes.
- **The lobby rebuilt from the record** on every change, so a third
  row and more seats are the record's rules and one view.
- **The save format's habit**: every field with a fallback, every
  older save reading on; `_upgrade_refs` and `upgrade_hero_refs` show
  how a bare ref grows a seat.

## The decisions

These are the ones the plan is built on. Each is the recommendation
and its reason; the author overrules any of them by saying so on the
PR, and the step's prompt is rewritten rather than argued with. Those
the author has already settled say so, with the date.

0. **Both modes, in the basic and the standard game, as the rulebook
   has them** (the author's ask, 2026-10-10; the basic game confirmed
   2026-10-11). The two-player game is **the duel** in the code and the
   docs from here on, and it changes in nothing a player can see: the
   duel golden stays byte for byte through every step.

1. **A refactor that changes nothing comes first.** The 66 inline
   sites each ask one of four questions, and step 1 gives each its one
   reading: **who are my opponents** (`engine.opponents(match, seat)`,
   a tuple, which a target set, a tower, Moment's Peace, the flagbearer
   and the hero-level choice read), **whom is this attack against** (the
   defending seat, carried on the combat record -- `combat["against"]`,
   and the declared attacker's target seat beside `attacking` -- rather
   than recomputed at every stage; an older save's bare refs read as
   against the one opponent, as `_upgrade_refs` reads an older journal),
   **whose turn is next** (`engine.next_seat(match)`), and **who may
   act now** (`engine.acting_seats(match)`, the active seat alone until
   the dragon). The base joins them as **`base_of(match, seat)`**, the
   one reading of which `base_hp` a seat's base is. The record's seats
   become a list. Nothing is built for a third seat in this step; its
   test is that the duel is unchanged and a three-seat match validates.
   **What it costs**: one large diff with no new behaviour, and a
   `grep` the PR shows at zero.

2. **The variant is the record's and the match's**: `variant` on
   `CodexGame` (saved; "duel" where the key is missing) and on
   `MatchState` (a saved field, "duel" in an older save), since the
   rules read the match -- the tower's reach, the free gold, the
   repair, the lending, the shared base -- and a match outlives the
   record's lobby. `codex.game.VARIANTS` holds the three names. The hero
   count stays `mode`; the two are independent, as the rulebook says.

3. **The record's seats are a list, saved beside the four old keys.**
   `seats` on the record holds `{id, name}` per seat in lobby order;
   `player_1_id` to `player_2_name` go on being written for the first
   two seats and read where `seats` is missing, so a record written by
   the new code still reads on the old (the live host between a pull
   and a restart) and no saved key is renamed. `seat_user_id(seat)`
   replaces the cogs' five `player_1_id if seat == 1 else player_2_id`.
   `game_auth.game_participant_ids` reads `seat_ids()` where the record
   has it and the two fields where it does not, so D12 Ball's record and
   tests are untouched. **What it costs**: two spellings of two seats
   in every save, until the author says the old keys may go.

4. **Free-for-all before two-headed dragon.** The free-for-all
   stretches the count and adds three rules, all of them on shapes the
   bot has; the dragon changes the shape of a turn (two seats acting in
   one main phase), which is the deeper change and better made once the
   count is already free. Each mode is one step through the driver and
   one on Discord, so there are four stops the author can look at
   instead of two.

5. **The free-for-all's ending lives on the match as `playoff`**, a
   saved list of the seats still owed a turn (`[]` otherwise). When a
   base is destroyed and one player leads on base HP, the game ends
   there, as a duel's does; when the lead is tied, the current turn
   runs to its end (the UMR's reading, question 13), `playoff` is
   filled with the tied seats in turn order from the next, `next_seat`
   reads it ahead of the normal order, and when it empties the
   comparison is made again -- a winner, or the list filled again. A
   base destroyed during a playoff is one more base at zero, compared
   when the playoff ends. `winner` stays one seat; `GameOverOptions`
   grows `winners` and the base HP of every seat, since the ask says
   the score. **There is no concession in a free-for-all** (the
   author, 2026-10-11): `concede` refuses on a free-for-all match, the
   Concede button is not on its turn message and `/codex concede`
   answers that the mode has none.

6. **Mercenaries arrive at the upkeep, as an upkeep effect.** The
   match remembers how many each seat is still owed
   (`PlayerState.mercenaries_owed`, saved, 0): the deal sets 1, 2 and 3
   for the third, fourth and fifth players in turn order, and that
   seat's first upkeep puts them in play -- tokens made by nobody, with
   the ordinary arrival fatigue (Rulebook p. 14: "it doesn't have haste,
   so it can't attack on their first turn") -- and clears the count.
   Nothing special is built for their fatigue.

7. **The three additions are rules behind `variant`, in the model.**
   *Repair* is a `MAIN_ACTION` option (`repair_base`), offered with its
   cost and refused as every option is, any number of times a turn.
   *Free gold* is `PlayerState.bounties`, the gold earned this turn
   (saved, 0), written where `board.destroy` destroys a unit -- a token
   included, never a hero or a building -- controlled by an opponent of
   the active seat during that seat's turn, capped at three, cleared
   when the turn begins. *Lending* is a control change: the `PATROL`
   prompt's options grow each opponent's empty slots (`zones`, keyed by
   seat), the lock action names where each card goes, a lent card's
   `controller` becomes the borrower and **`lent`** (a saved flag,
   false) marks it, the borrower's upkeep returns every card they
   control with `lent` set to its owner (`controller` back, out of the
   zone, into the owner's play zone and never their patrol zone, readied
   as the ready phase readies), no Arrives trigger fires on either
   exchange and nothing on the card changes (its runes, damage and
   attachments stay), the scavenger's and technician's payouts read the
   owner, and a lent card destroyed leaves play to its owner as every
   card does. A lent **hero** (the author, 2026-10-11: units and
   heroes) sits in the borrower's slot as `"<owner seat>:hero:<slug>"`
   (the spelling `attached_hero` already uses) with `lent_to` on the
   `HeroState` (saved, `None`); the hero stays on its owner's list and
   `controller_of` reads the field; a lent hero that dies goes to its
   owner's command zone with its summoning runes, and its levels go
   where decision 11 says.

8. **The dragon's two seats are two pending prompts.** `pending` stays
   the one reading of what a seat waits on, and grows a `seat`
   argument; `pending_prompts(engine, match)` lists one per acting
   seat, and `driver.answer` finds the prompt of the action's seat,
   which every action now names (`arguments["player"]`, as the tech
   actions already do) -- the journal records it with the action. The
   team acts one action at a time: while one teammate's action stands
   half-resolved (a defender, a target, an upkeep order owed), the
   other's `MAIN_ACTION` is not listed, so a click of theirs is refused
   with why. **The team's turn opens on both tech confirmations**: each
   teammate's `TECH_CONFIRM` (or `TECH_CHOICE`) is pending, and
   `begin_turn` runs once both are settled; it then readies and upkeeps
   the two seats in seat order, each `UPKEEP_ORDER` asked of its owner
   and the owed `BEGIN_TURN` resuming through the same step after the
   answer. The Mercenary rule never applies. Each seat's **patrol lock
   is its own** (`PlayerState.locked`, saved, false, cleared when the
   turn begins): the first lock ends that seat's actions, the second
   ends the team's main phase and the draw and tech phases run for both,
   whose choices then stand through the other team's turn. The
   snapshot is the team turn's, so **To the start of my turn** is the
   team's, with nobody's consent (the author, 2026-10-11). An extra turn
   from an effect is one seat's alone (p. 13): `extra_turns` names a
   seat and `acting_seats` is that seat while it runs.

9. **The dragon's base is the team's first seat's `base_hp`, through
   `base_of`.** Every read and write of a base goes through the one
   reading step 1 makes, so the shared base needs no field: the
   dragon's `base_of` is its first seat's, the second seat's `base_hp`
   is dealt at 30 too and never read. `MatchState.dragons` (saved, `[]`)
   holds the two pairs of seats; `engine.teammate(match, seat)` and
   `opponents` read it. A destroyed tech building or add-on deals its 2
   to the team's base. **A team never holds two of the same add-on**
   (p. 13): the build options refuse an add-on the teammate has, with
   the page. **What it costs**: a number in the save that means
   nothing, documented as such.

10. **"Friendly" is a flag on the effect's part.** The eleven cards and
    heroes that say "friendly" get `friendly=True` on the parts whose
    text says it, and the target filters `own_*` read the flag: the
    controller's own things, or in a dragon the teammate's too. "Your",
    "you control" and a count of what "you have" stay the controller's
    alone (p. 13, "you means you"). The audit of the eleven is in the
    step's PR, text beside flag.

11. **"An opponent's" is a target across opponents, and a kill's
    levels go where the rulebook says.** `target_candidates` enumerates
    every seat and filters by `opponents(seat)` instead of `side !=
    seat`; a part that names one opponent's thing lists each
    opponent's, and the existing `TARGET` prompt asks where more than
    one. A part that damages "the opponent's base" (Captured Bugblatter,
    Drakk) hits one base, the chosen opponent's, and in a dragon the one
    base once. An effect frame's `against` is set by what started it --
    the attack's defending seat, the chosen target's seat -- and
    `_against(top)` no longer has a default to fall back on. A dead
    hero's two levels go to an in-play hero of any opponent of its
    owner, the active player choosing through `LEVEL_GAIN` (p. 11) -- in
    a duel the same heroes as today, in a free-for-all any opponent's,
    in a dragon either of the other team's.

12. **The lobby's third row and the seats.** Beside **Basic game** /
    **Standard game**: **Duel** / **Free-for-all** / **Two-headed
    dragon** -- either seated player's, or anyone's while nobody sits,
    as the mode row is -- and the lobby prints a row per seat the
    variant takes: two, three to five (Start from three), or four in
    two teams, seats 1 and 2 one team and 3 and 4 the other, each team
    headed. A seat is taken in order, as now; a player who wants the
    other team leaves and sits again. Changing the variant keeps every
    seated player that still fits and clears the rest. A test game sits
    its one person on every seat. The channel is named
    `codex-<n>-ffa-<p1>-<p2>-<p3>` and `codex-<n>-<p1>-<p2>-vs-<p3>-<p4>`,
    capped at 100 as now; `CHANNEL_NAME_PATTERN` is unchanged.

13. **The turn message, the panels, and a teammate's hand.** The
    heading stays the model's: a free-for-all's is a duel's; a dragon's
    names both teammates -- "**Turn 7** -- @ann (Blood Anarchs) and @bo
    (Moss Sentinels)" -- and the post pings both. **My hand** answers by
    the clicker's seat as now: an acting seat's gets the panel, any
    other their hand. **Teammates see each other's hands freely** (the
    author, 2026-10-11, as p. 13 allows): `hands_visible_to` returns the
    teammate in a dragon, and the turn message's revealed-hand picture
    -- what Eyes of the Chancellor shows today -- carries the teammate's
    hand under the clicker's own, captioned by name, on My hand, under
    the panel and on `/codex hand`. The tech choice and the codex stay
    their owner's (question 14). In a dragon both teammates hold a panel
    at once; a public click by one posts the turn message again, and the
    other's panel stands above it until their next click, which the
    driver checks against the options as they stand and which sends
    their panel afresh under the board, as every public click does. The
    tech pickers stand for every seat whose turn has ended, as the one
    standing choice does today; in a dragon test game, where one person
    holds both acting seats, the panel is the first unlocked teammate's
    with a **Switch to <team>** button.

14. **The board is stacked only, in both modes.** A free-for-all is one
    panel above another, the acting seat's at the bottom with its rule
    and pill, the others above it **upright** in turn order, the next to
    play nearest: a table of five has no "across", and a turned panel
    tells the reader nothing a duel's does. A dragon is two rows of two,
    the far team's turned as the duel's far panel is, the shared base
    drawn once in each team's first panel's building column and the
    second column one tile shorter. **Swap view** is a duel's and is not
    on a multiplayer turn message: five panels in a row would be 10,000
    pixels wide. These are proposals for a picture, and the step's stop
    is the author looking at it (question 2).

15. **Undo, concede and abandon, as the author settled them**
    (2026-10-11). *To the start of my turn*: any acting seat's, without
    consent, the team's turn in a dragon. *To the start of the previous
    turn*: unwinds the previous seat's turn in a free-for-all, so that
    seat is asked, and the other team's in a dragon, so either of its
    players may **Agree** and anyone at the table **Refuse** -- the
    duel's consent, kept (question 12). *Concede*: none in a
    free-for-all (decision 5); **in a dragon a concession needs both
    teammates**: the first click is the clicker's own, ephemeral, as
    now; it then posts a public question naming the teammate, modelled
    on the undo's `UndoConfirmView` -- **Agree** the teammate's, or a
    game helper's behind the helper's confirmation; **Refuse** either
    teammate's -- and the game ends on Agree through the service's
    `concede`, the other team winning. Not persistent: after a restart
    the asker asks again. *Abandon* is unchanged -- a seated player's
    own game, or a helper's -- in every variant, until the author says
    otherwise (question 11).

16. **A multiplayer rematch is a fresh pick of heroes** (the author,
    2026-10-11: let the players choose their heroes and codex). The same
    seats and, in a dragon, the same teams, in the same channel; every
    seat's heroes and deck cleared, so each seat picks again from the
    lobby's menu or deck buttons as in a new lobby, the same picks
    allowed; the first player or team drawn again at Start. **Keep
    heroes** and the swap are a duel's and are not shown. The duel's
    rematch is unchanged.

17. **Two new goldens, one a mode**: a seeded three-player basic game
    and a seeded dragon, byte for byte in `tests/golden/codex_ffa_*` and
    `codex_dragon_*`, re-recorded as the duel's is. The duel's is not
    re-recorded for any of this: where a step must touch it, the PR says
    why and shows the normalised diff empty.

18. **No AI, still** (codex-bot.md, decision 13): the whole-game test's
    policy plays every seat, three to five.

19. **A series of its own, run by the cloud routine and claimable by
    hand** (the author, 2026-10-11). `multiplayer` in
    `scripts/claim_web_step.py`'s `SERIES`, worksheet this file,
    branches `codex-mp-step-<n>`, PRs titled `Codex multiplayer step
    <n>:`; step 1's prompt adds it. The routine and its extension are in
    "Claiming a step".

## Questions for the author

Each step's PR carries a `## Questions to the author` section; these
are the ones known before any step starts. A step whose prompt needs the
answer says what it builds until it has one. Those struck were answered
on 2026-10-11.

1. ~~**What is a two-player team called in the code and in the
   narration?** Built as `dragon` in the code and "team" in what the
   bot says.~~ Answered: dragon is fine. `dragons`, `dragon_of`,
   `teammate` in the code; "team" in what the bot says, as the rulebook
   says it ("the other team's base is destroyed"); the nameplate's hero
   team unchanged.
2. **How should a board of three to five, and a dragon's, look?**
   Decision 14 is a proposal; the step renders both with
   `scripts/render_codex_sample.py` and the author looks before the
   Discord step is worth starting.
3. ~~**Should both modes be offered in the basic game?** Built as
   yes.~~ Answered: yes.
4. ~~**May a teammate see the other's hand through the bot?** Built as
   no.~~ Answered: yes, freely. Decision 13.
5. ~~**What does conceding do in a free-for-all?**~~ Answered: there is
   no conceding in a free-for-all. Decision 5.
6. ~~**Does a teammate's concession end the team's game?** Built as
   yes, behind the second click.~~ Answered: a concession needs both
   teammates' approval. Decision 15.
7. ~~**Does the undo to the start of the team's turn need the
   teammate's consent?** Built as no.~~ Answered: no consent on the
   undo.
8. ~~**What does a rematch change in a multiplayer game?** Built as
   nothing but who goes first.~~ Answered: the players choose their
   heroes and codex again. Decision 16.
9. ~~**May lending be units only to start?** Built as both.~~ Answered:
   units and heroes.
10. ~~**Does the cloud routine run this series?**~~ Answered: it
    should, and the steps may also have to be run by hand. "Claiming a
    step".
11. **Who may abandon a multiplayer game?** Today any seated player
    abandons their own game, and a helper any. With no concession in a
    free-for-all, one player's abandon is the one way a seat leaves a
    game of five. Built as unchanged.
12. **Does the undo to the start of the previous turn keep the
    opponents' consent?** The author's "no need for consent on the
    undo" answered question 7, the teammate's. Built as the duel has it:
    the seat whose turn is unwound, or either player of the other team,
    agrees.
13. **In a tied free-for-all ending, does the current player's turn
    finish before the tied players' extra turns?** The rulebook (p. 14)
    does not say; the UMR (p. 12) says it does. Built as the UMR says.
14. **Does a teammate also see the other's tech choice and codex?**
    The rulebook lets teammates show each other their cards. Built as
    the hand alone; the picks are theirs to say in the channel. A
    **Teammate's tech** view is one more picture if wanted.

## The steps

In the order they pay off. Each is one branch off an up-to-date `main`,
one PR against the template, the suite green, the six D12 Ball
safety-net tests and the duel's golden untouched unless the step says
why. None changes any file under `d12ball/`, `gamesaves/d12ball/` or
`cogs/d12ball*`, and `cogs/game_auth.py` only as decision 3 says. Every
step ends on a **stop**: the thing the author looks at before the next
step is worth starting.

| # | Step | Size | Stop |
| --- | --- | --- | --- |
| 1 | Seats as a list, opponents as a set, the base as one reading -- nothing changes | large | the duel golden byte for byte; the idiom `2 if … == 1 else 1` gone from `codex/` and `cogs/codex*`; a three-seat and a four-seat match validate |
| 2 | Free-for-all through the driver | large | a test plays three and five players from the deal to a winner on base HP, through a tied playoff, with nothing from `cogs/` or `discord` imported; the three-player golden |
| 3 | Free-for-all's three additions: repair, free gold, lending | medium | a lent patroller defends, pays its owner and comes home at the borrower's upkeep; the golden re-recorded if the transcript gained a line |
| 4 | Free-for-all on Discord | large | three people reach the end of a game: the lobby, the channel, the stacked board of three, the pickers standing for two, rematch |
| 5 | Two-headed dragon through the driver | large | a test plays a dragon from the deal to a destroyed base, both teammates acting in one main phase; the dragon golden |
| 6 | Two-headed dragon on Discord | medium | four people finish a game: two panels at once, a teammate's hand, the board of two rows, the shared base, a concession both agreed to |
| 7 | The look back: what the modes left in two places, and the design note | small | nothing step 1 to 6 copied remains in two places; "Multiplayer" in docs/design/codex.md says what each step settled |
| -- | Later, and not now | -- | |

### Claiming a step

The series does not exist yet: **step 1's prompt adds it** -- one entry
in `SERIES` in `scripts/claim_web_step.py`
(`"multiplayer": ("docs/codex-multiplayer.md", "codex-mp-step", "Codex
multiplayer step")`), plus the `--series` help string and the module
docstring, which both list the series by hand. From then on
`python3 scripts/claim_web_step.py --series multiplayer <n>` claims a
step the way the other series are claimed: an empty commit on
`codex-mp-step-<n>` pushed create-only, refused if the row is struck on
`origin/main`, the branch exists, or an open PR is titled `Codex
multiplayer step <n>:`. A step lands by striking its row above
(`| ~~n~~ | ~~title~~ -- landed; what it settled is in
docs/design/codex.md, "Multiplayer" | ... |`).

**The cloud routine runs this series, and a person may claim a step by
hand as well** (the author, 2026-10-11). The routine is the Codex
series' (codex-bot.md, "Claiming a step": `trig_01FZvSJE78cUuHfbbNN97QPa`,
"fool-bot: start the next Codex step", disabled since the Codex series
landed), and its stored prompt names `docs/codex-bot.md`, the `codex`
series, `codex-step-<n>` branches and `Codex step <n>:` titles
throughout. **To run this series it is edited, by the author, when the
series is to start** -- it was not touched when this worksheet was
written, since the author was not starting yet: every one of those
names becomes this worksheet's (`docs/codex-multiplayer.md`,
`--series multiplayer`, `codex-mp-step-<n>`, `Codex multiplayer step
<n>:`), Gate 1 reads this file on `origin/main`, the by-hand claim for
step 1 pushes `codex-mp-step-1`, and the preamble it reads is this
file's "Preamble" block after codex-bot.md's; then the routine is
enabled. A step claimed by hand in the meantime is refused to the
routine by Gate 3 as any claim is. Every PR carries the two sections the
Codex series' PRs carry: `## Questions to the author` (`None.` when
empty) and `## For the author` -- what to do on the live host after
merging, and what can be tested in the server now, command by command.

## Preamble

Every step's prompt begins with **the Codex preamble in
[codex-bot.md](codex-bot.md), "Preamble"**, whole, and then this block,
which overrides it on which rulebook governs.

```text
The step is from docs/codex-multiplayer.md, the worksheet for the two
multiplayer modes: read its "The two modes, in the terms the code will
use" (the rules you implement, with the rulebook page each is on),
"Where the UMR differs from the rulebook", "What the bot assumes today"
(the survey step 1 is written from) and "The decisions"; then
docs/design/codex.md whole, since every section of it names a seat
somewhere.

Which rules govern (the author, 2026-10-11, overriding the Codex
preamble's preference for the UMR): the official rulebook,
docs/codex/Codex_Core_Set_Rulebook.pdf ("Rulebook version 46"), and
the card database's rulings in codex/data/rulings.json are the official
source of the rules; the rulings govern where they and the rulebook's
text differ. Read Rulebook p. 13 (Two-Headed Dragon) and p. 14
(Free-for-all) -- the pages as numbered at their foot; the contents
table is one off -- with p. 4 (the tower), p. 5 (the patrol slots),
p. 11 (a dead hero's levels) and p. 19 (armor); and the seven rulings
that say "2v2", "Two-Headed Dragon", "free-for-all" or "team" -- the
General group's overpower and tower rulings, Captured Bugblatter's,
Drakk Ramhorn's, Ironbark Treant's and Moment's Peace's. The Unofficial
Manual Rewrite (docs/codex/Codex_UMR_v13w.pdf, UMR p. 11-12 for the
modes) is useful and sometimes wrong: where it and the rulebook differ,
the rulebook governs, and the worksheet lists the differences found.
Cite the rulebook's page in a refusal and a docstring, the UMR's only
for a detail the rulebook lacks, saying so.

Added to the Codex preamble's hard rules:
- The two-player game is the duel, and it changes in nothing a player
  can see. tests/test_codex_golden.py is not re-recorded by a
  multiplayer step; where a step cannot avoid touching the duel's
  transcript or final match, the PR says why and shows the diff
  normalised to nothing.
- One reading each: engine.opponents, engine.acting_seats,
  engine.next_seat, base_of, and the defending seat on the combat
  record. Nothing computes "the other seat" inline; the PR shows
  grep -rn "2 if .* == 1 else 1" codex cogs/codex cogs/codex_views
  cogs/codex_helpers.py empty from step 1 on.
- A seat is any positive number the match has; nothing refuses a seat
  by naming 1 and 2. A rule that reads a variant reads match.variant,
  never the record's.
- The save format is the contract: every new field in its SavedField
  table with its fallback, every older save reading on, no saved key
  renamed; the record's player_1_* and player_2_* keys go on being
  written for the first two seats.
- A seat's hand, deck, discard and tech choice stay its own, with one
  exception the rulebook allows and the author chose: in a dragon a
  teammate sees the other's hand, through hands_visible_to and the
  revealed-hand picture, ephemerally, and nothing else of theirs. A
  lent card's borrower and a watcher see nothing hidden; nothing hidden
  reaches a public message or a log line, as the Codex preamble says.
- Nothing rendered is tested for how it looks: render it
  (scripts/render_codex_sample.py, which this series teaches the two
  modes) and put the picture in the PR.
- Run python3 -m unittest discover -s tests before the PR; a full run
  must not create data/. Strike this step's row in
  docs/codex-multiplayer.md, write what the step settled into
  docs/design/codex.md under a "Multiplayer" heading with the
  reasoning, and add a row to CLAUDE.md's tables only for a new module
  or a new hard rule.
```

### 1. Seats as a list, opponents as a set, the base as one reading -- nothing changes

The 66 inline readings of "the other seat" are the whole reason the
modes are not a day's work, and each is one of four questions that have
one answer today and several tomorrow. This step gives each question
its one reading while the answer is still one, so that the duel's
golden can say the refactor changed nothing -- the hash-verified
refactor of the board, done for seats -- and so that steps 2 and 5
change readings, not sites.

```text
Step 1 of docs/codex-multiplayer.md. No step of the series has
landed. Also read docs/design/game-service.md and
docs/design/model-discord-split.md for the shapes, and
docs/design/permissions.md for what cogs/game_auth.py reads. Four
commits: the series; the record; the match and the engine; the cog
and the tests.

0. The series. Add "multiplayer" to SERIES in scripts/claim_web_step.py
   ("docs/codex-multiplayer.md", "codex-mp-step", "Codex multiplayer
   step"), the --series help string and the module docstring, as the
   codex series was added. Claim this step with it by hand once it is
   on the branch.

1. The record (codex/game.py). CodexGame holds its seats as a list,
   seats, of {id, name} in lobby order, saved as "seats" and read from
   player_1_id/player_1_name/player_2_id/player_2_name where the key is
   missing; the four old keys go on being written for seats 1 and 2
   (decision 3), and player_1_id and the other three stay as
   properties over the list so nothing that reads them breaks. seats_of,
   seat_of, seat_for, seat_name, take_seat, leave, may_start, start,
   rematch, keep_heroes, heroes_kept and finish read the list; a seat
   count, seat_count, is the record's (two, until step 2 gives the
   variant a say), and take_seat refuses a seat beyond it with the
   count in the refusal rather than "A game has seats 1 and 2". Add
   seat_user_id(seat) and seat_ids(). player_specs, player_decks,
   rematch_specs, rematch_decks and kept_heroes keep their shapes, keyed
   by seat. cogs/game_auth.py: game_participant_ids reads seat_ids()
   where the record has it and the two Protocol fields where it does
   not, the Protocol unchanged, D12 Ball's tests untouched.

2. The match and the engine. components.MatchState.validate accepts two
   to five players in seat order, first/active/winner/conceded any seat
   the match has; opponent(seat) goes, replaced by engine.opponents(
   match, seat) -- a tuple of every other seat, which is where a dragon
   will later leave the teammate out -- and the seven callers read it,
   board.destroy's hero-level choice among them: its candidates are
   every in-play hero of every opponent of the dead hero's owner that
   can still level (Rulebook p. 11), the one opponent's today.
   engine.next_seat(match) is the one reading of whose turn follows
   (extra_turns first, then the seat after in order, wrapping);
   begin_tech reads it. engine.acting_seats(match) is (match.active,);
   prompts.pending asks it. base_of(match, seat) on the engine or the
   match is the one reading of a seat's base_hp, read and written by
   damage_base, base_floor, base_left_after, pass_prevents, the
   render's building column and every other site that reads base_hp.
   The combat record carries the defending seat: MatchState.attacking
   stays a ref and gains against (the seat attacked) beside it in the
   save -- read from the one opponent where an older save has none --
   and combat["against"] the same; declare_attack sets it from the
   defender chosen, and legal_defenders, defender_rows, _defender_rows,
   blocking_patrollers, _standing, may_be_attacked, attack_toll,
   ignores_patrollers, _unstoppable_by, damage_back, overpower_excess,
   overpower_candidates, sparkshot_candidates, obliterate_candidates,
   flown_over, _open_why, tower_detects, tower_sees, detect_option,
   attack_value, _conditioned_keywords and every stage of flow/combat.py
   read it rather than computing the other seat; where the attacker has
   not yet chosen (CHOOSE_DEFENDER), the rows are built per opponent and
   the DefenderOptions rows carry their seat as TargetRow does. Effect
   frames: _against(top) reads top["against"] and raises where a frame
   that needs one has none, and every place that opens a frame against
   a seat sets it (combat.py, board.py, resolve.py). target_candidates
   enumerates match.players and filters by opponents(seat) instead of
   side != seat; targetable and target_rows the same; hands_visible_to
   returns opponents(seat) for the reveal. standing_prompts lists every
   seat other than the active one with a tech choice owed.
   tokens.player and tokens.addressed accept any positive seat;
   formatting's plain-text fallback stays "Player n". The idiom 2 if x
   == 1 else 1 is gone from codex/ when this commit is done, and
   upgrade_hero_refs reads the seats it has rather than assuming two.

3. The cog and the tests. cogs/codex_helpers.py, cogs/codex/core.py,
   presentation.py, turns.py and cogs/codex_views/base.py read
   game.seat_user_id(seat); the channel's name joins every seat's name
   with "-vs-" for two (the same string as today); /codex games the
   same; turn_footer, side_shown, the label builders in
   cogs/codex_views/turn.py, ask_concede, roll_over and
   UndoConfirmView.opponent read engine.opponents or engine.next_seat;
   render.stacked_seats and compose_board read opponents for the far
   seat (a duel's one). The idiom is gone from cogs/codex* when this
   commit is done. Tests: codex_positions.new_game seats a list of
   teams, two by default; every test that loops or asserts over (1, 2)
   reads game.seats_of() or match.players; tests that called
   match.opponent read engine.opponents(match, seat)[0]. Add
   test_codex_seats.py: a three-seat and a four-seat MatchState built by
   hand round-trip through to_dict/from_dict/validate; opponents,
   next_seat and base_of answer for each seat; a record with three seats
   saves and loads, and one saved by the old code (the four keys, no
   "seats") loads with two.

The stop: tests/test_codex_golden.py passes unchanged, the request table
in docs/design/codex.md ("The requests per click") holds click for
click, and the PR shows the grep in the preamble empty.
```

### 2. Free-for-all through the driver

The mode as the model, before a line of Discord: the variant, the deal,
the Mercenaries at their upkeep, the turn order, the ending and its
playoff, the tower's and Moment's Peace's free-for-all readings, and
the reading of "opponent" on every card, played whole through
`driver.apply` by the test policy with nothing from `cogs/` imported --
the Codex series' step 2, for the mode.

```text
Step 2 of docs/codex-multiplayer.md. Step 1 has landed. Also read
tests/test_codex_driver_full_game.py and tests/test_codex_golden.py
(what you extend), codex/flow/turn.py whole (begin_turn, begin_tech,
damage_base, concede) and codex/effects.py's target filters. Four
commits: the variant and the deal; the turn and the ending; the tower,
Moment's Peace and "opponent"; the whole game and the golden.

1. The variant and the deal. codex.game.VARIANTS = ("duel",
   "free_for_all", "two_headed_dragon"); CodexGame.variant, saved,
   "duel" where missing, set by set_variant (refused once started, as
   set_mode is); seat_count reads it -- two, five, four -- and
   may_start needs at least three complete seats in a free-for-all and
   every taken seat complete; leaving a seat in the middle closes the
   gap (the seats after it move up), since turn order is seat order.
   MatchState.variant, a saved field, "duel" in an older save, set by
   new_match from the record. new_match takes any number of teams: the
   first seat drawn from them all (STARTING_WORKERS by whether the seat
   went first, as now), and in a free-for-all the third, fourth and
   fifth players IN TURN ORDER from the first are owed 1, 2 and 3
   Mercenaries (PlayerState.mercenaries_owed, saved, 0), which that
   seat's first upkeep puts in play as an upkeep effect -- mercenary
   tokens owned and controlled by the seat, made_by None, with the
   ordinary arrival fatigue -- and says so ("{player:3}'s Mercenary
   arrives." / "two Mercenaries arrive."), clearing the count (Rulebook
   p. 14; the UMR's "begin with them in play" is wrong, "Where the UMR
   differs"). Tests: a Mercenary is not on the board before its owner's
   first upkeep, cannot attack on that turn and can on the next; seat
   order and turn order differ when the first seat drawn is not seat 1,
   and the Mercenaries follow turn order. The board draws the token's
   face (tokens/mercenary) as it draws a Dancer's.

2. The turn and the ending. next_seat wraps through every seat.
   begin_turn clears bounties (step 3's; leave the field for it) and
   readies the active seat alone as now. damage_base on a free-for-all
   match, when it destroys a base: compare every seat's base_hp; a sole
   leader is the winner (the events, the headline and the GAME_OVER
   ask as now, the ask naming the score: "{player:3} wins with 14 base
   HP: {player:1}'s base is destroyed."); a tied lead fills
   MatchState.playoff (saved, []) with the tied seats in turn order
   from the seat after the active one, says so ("A tie at 14 base HP:
   {player:2} and {player:3} each take one more turn."), and the game
   goes on: the current turn finishes (question 13), next_seat reads
   playoff ahead of the order, popping the seat it hands out, and
   begin_tech, when playoff has emptied, makes the comparison again --
   a winner, or the list filled again. A base destroyed during a
   playoff is one more base at zero, compared when the playoff ends.
   There is no concession in a free-for-all (decision 5): concede
   refuses on such a match with RuleRefusal citing p. 14's "no player
   elimination". GameOverOptions grows winners (a tuple) and base_hp per
   seat; the duel's winners is (winner,). Test every branch of the
   playoff with a staged position, through the driver.

3. The tower, Moment's Peace and "opponent". tower_detects: in a
   free-for-all the tower detects one attacker a turn and only a card
   attacking its owner (p. 4); the tower's damage falls only on an
   attacker of something its owner controls (the free-for-all tower
   ruling). Armor refreshes at the start of every turn for every seat
   (p. 19, the Ironbark Treant ruling -- the Treant's own armor too):
   already so; pin it. Moment's Peace on a free-for-all match removes
   its caster's things from the legal defenders and nothing else
   (engine.attackers no longer reads one opponent's peace). legal_defenders
   for an attacker in a free-for-all: each opponent's zone protects
   that opponent alone (p. 5), the rows per opponent as step 1 built
   them; overpower's excess stays with the attacked opponent (the
   overpower ruling). Then the audit: every card whose text says
   "opponent", "opponent's", "opposing", "opponents", "opponents'" or
   "each opponent" (43 and 21 on 2026-10-10 -- list them with a script
   over codex/data/cards.json and heroes.json, bands included), and for
   each the reading decision 11 gives: a plural is every opponent; "an
   opponent's" lists each opponent's things as TargetRows and TARGET
   asks where more than one (a part that damages "an opponent's base"
   lists each base); "the opponent" in a context that names one is that
   one (the attack's against, the frame's). A dead hero's levels:
   LEVEL_GAIN's candidates are every in-play hero of every opponent of
   the dead hero's owner that can level, the active player choosing
   (p. 11), as step 1 wrote it -- a three-player test where the killer
   gives the levels to the third player's hero. Put the list in the PR
   with the reading each card got, for the author. Discord, Reputable
   Newsman, Granfalloon Flagbearer, Moment's Peace, Captured Bugblatter
   and Carrion Curse each get a three-player test.

4. The whole game and the golden. tests/test_codex_driver_full_game.py
   plays a three-player and a five-player basic game -- Bashing,
   Finesse and landed heroes of any colour (mirror games are fine) --
   to a winner, the policy playing every seat, standing tech choices
   answered for every seat that owes one; the test's print with -v is
   the transcript the author reads. One game is steered into a tied
   playoff. tests/test_codex_golden.py gains a seeded three-player
   game pinned in tests/golden/codex_ffa_transcript.txt and
   codex_ffa_final_match.json, re-recorded with FOOLBOT_UPDATE_GOLDEN=1
   as the duel's is; the duel's files do not change.

The stop: the two whole-game tests and the new golden pass, and the
transcript of the three-player game reads turn by turn with the score
at its end.
```

### 3. Free-for-all's three additions: repair, free gold, lending

The three rules Rulebook p. 14 adds, as options and fields behind
`match.variant`, in the model. Lending is the only one that changes who
controls a card, and the one that touches the patrol prompt both sides
read.

```text
Step 3 of docs/codex-multiplayer.md. Steps 1 and 2 have landed. Also
read docs/design/codex.md "The keywords" (the patrol bonuses) and "Red
and green" (control that returns), codex/flow/board.py's destroy and
the patrol lock in codex/flow/actions.py. Three commits: repair; free
gold; lending.

1. Repairing the base (Rulebook p. 14). A MAIN_ACTION option,
   repair_base, listed on a free-for-all match with its cost and why it
   may not be taken (under 3 gold, the base at 20, the variant not a
   free-for-all) -- the options' shape for hire and build -- and an
   action the driver runs: 3 gold for 1 base HP through base_of, any
   number of times a turn, journaled, narrated ("{player:2} repairs the
   base: 15 HP."). A test through the driver, and one that a duel never
   lists it.

2. Free gold (p. 14). PlayerState.bounties, saved, 0 in an older save,
   cleared in begin_turn. Where board.destroy destroys a unit -- a
   token included, never a hero or a building -- on a free-for-all
   match, during the active seat's turn, controlled by one of
   opponents(active) at that moment (a card lent to an opponent is
   theirs), the active seat gains 1 gold, to 3 a turn, said in the
   destroy line ("... and {player:1} collects 1 gold."), the gold cap
   respected. Tests: a kill in combat, a kill by a spell, a kill by an
   opponent's own trigger on the active player's turn, the fourth kill
   of a turn, a hero's death, a building's, a duel.

3. Lending patrollers (p. 14). PatrolOptions grows zones: each
   opponent's empty slots keyed by seat, on a free-for-all match alone,
   beside the owner's own slots; the patrol action's arguments name a
   seat per assigned slot (the owner's where none, so every older
   journal and the duel read as before); lock sets each lent card's
   controller to the borrower and lent (CardInstance, saved, false)
   true -- no Arrives trigger fires, and nothing on the card changes:
   its runes, damage, attachments, exhaustion -- and a lent hero's
   HeroState.lent_to (saved, None) with the borrower's slot holding
   "<owner seat>:hero:<slug>" -- the spelling attached_hero uses -- the
   hero staying on its owner's list and every controller reading of a
   hero going through controller_of. The borrower's upkeep returns
   every card they control with lent set and every hero with lent_to
   naming them: out of the zone, controller back to the owner, into the
   owner's play zone and never their patrol zone, readied as their
   ready phase would, no Arrives trigger, the card as it was. The
   scavenger's gold and the technician's card pay the owner; a lent
   card destroyed leaves play to its owner as every card does (a hero
   to its command zone with its summoning runes); the kill's levels go
   as decision 11 says; an effect on the borrower's "your units"
   reaches a lent card and the lender's does not. What the patrol
   bonuses do on a lent card (the squad leader's armor, the elite's
   ATK) is the borrower's zone's, as any patroller's. Tests for each
   sentence, and a journal replay (history.replay) through a turn that
   lends.

The free-for-all golden is re-recorded only if the transcript gained a
line (a repair, the free gold), and the PR says so; the duel's does not
change. The stop: a staged three-player position in which seat 2 lends
seat 3 a patroller, seat 1 attacks it on their turn, the owner collects
the technician's card, and the card returns at seat 3's upkeep -- as a
test, and as the transcript printed.
```

### 4. Free-for-all on Discord

The lobby, the channel, the turn message and the board for three to
five seats, over the mode as it plays through the driver. Nothing in
this step decides a rule; the record's seat rules and the variant are
step 2's.

```text
Step 4 of docs/codex-multiplayer.md. Steps 1 to 3 have landed. Also
read docs/design/codex.md "The lobby and the channel", "The board on
Discord", "The panel", "The turn message, posted again", "The two
undos, and who may take each", "The end of a game", "The requests per
click", and docs/design/rate-limits.md. Four commits: the lobby and
the channel; the turn message and the panels; the board; the end of
the game.

1. The lobby and the channel. cogs/codex_views/lobby.py's first row
   gains Duel / Free-for-all / Two-headed dragon (the third refused as
   "not in this bot yet" until step 6, with no page), the row either
   seated player's or anyone's while nobody sits, as the mode row is;
   set_variant is the service's door over the record's; the lobby
   prints a row per seat the variant takes, "Seat 3 -- open", and Start
   from three complete seats; a test game sits its one person on every
   seat and shows the picks once per seat ("P3: Blood Anarchs"). Start
   renames the channel codex-<n>-ffa-<p1>-<p2>-<p3>, every seat's name
   slugged, capped at 100; /codex games lists every seat. The turn
   message pings the active seat as now. Test with the fakes
   (tests/codex_cog_fakes.py): three people reach the opening position,
   and the requests per click of the lobby are the duel's.

2. The turn message and the panels. My hand answers by the clicker's
   seat as now -- the panel for the active seat, the hand for any other.
   The tech pickers: every seat whose turn has ended holds a standing
   choice (step 1's standing_prompts), so Tech on the turn message and
   under the hand finds the clicker's; the footer that names who is
   still to tech names each. An undo to the previous turn asks the seat
   whose turn is unwound (the snapshot's active seat is the reading),
   Agree theirs or a helper's, Refuse anyone's at the table (question
   12). There is no Concede on a free-for-all turn message and
   /codex concede answers that a free-for-all has none, citing p. 14.
   A TARGET whose rows lie on several seats is pictured with those
   seats stacked, as "both sides stacked" is today. The request table
   holds for every click that exists today; the PR extends it with the
   clicks a third seat adds.

3. The board. render.compose_board stacks n panels: the near seat's at
   the bottom with its rule and pill, the others above it upright in
   turn order from the near seat, the next to play nearest it, one
   divider between each (decision 14); the worker card prints x4 for
   the first seat and x5 for every other. Swap view is not on a
   free-for-all turn message (board_layout stays stacked). The Mercenary
   draws as a token. Render a three- and a five-player mid-game board
   with scripts/render_codex_sample.py, which this commit teaches a
   free-for-all position, and put both pictures in the PR for question
   2 -- the step's stop is the author looking at them, and if the
   author wants the panels otherwise the change is to compose_board
   alone.

4. The end of the game. The winner's line with the final board, the
   playoff's "one more turn" lines on the turn messages they fall in,
   Rematch opening a lobby with the same seats and every seat's heroes
   cleared to be picked again (decision 16), the channel to Codex
   Archive as now. Abandon is unchanged (question 11). The startup
   sweep re-arms a free-for-all's buttons as a duel's.

The stop: three people (or one person on three seats in a test game, in
the test server) play a free-for-all from /codex create_game to Rematch,
and the author has looked at the board of three and the board of five.
```

### 5. Two-headed dragon through the driver

The mode as the model: the teams, the shared base, the team's turn with
two seats acting in one main phase, the attack priorities over both
patrol zones, and the words "you" and "friendly" -- played whole through
the driver with nothing from `cogs/` imported.

```text
Step 5 of docs/codex-multiplayer.md. Steps 1 to 4 have landed. Also
read docs/design/codex.md "The prompt kinds", "The standing prompt"
and "Undo's groundwork", codex/prompts.py whole, codex/flow/driver.py
(answer, _find_prompt, SEATED_KINDS) and codex/history.py. Five
commits: the teams and the deal; the team's turn; attacking; the words;
the whole game and the golden.

1. The teams and the deal. On a two-headed dragon record seat_count is
   four, seats 1 and 2 one team and 3 and 4 the other (decision 12);
   MatchState.dragons, saved, [] in an older save and in every other
   variant, holds the two pairs; engine.dragon_of(match, seat),
   teammate(match, seat) and opponents (the other pair) read it.
   new_match draws the first team, deals both its seats 4 workers and
   the other's 5 (Rulebook p. 13), and sets every base_hp to 30
   (DRAGON_BASE_HP) -- base_of reads a dragon's first seat's, and the
   second's is never read (decision 9; say so in the field's
   docstring). A team never holds two of the same add-on (p. 13): the
   build options refuse an add-on the teammate has built, citing the
   page. Nothing of the free-for-all's three additions is listed on a
   dragon match, and no Mercenary is owed. hands_visible_to returns
   the teammate on a dragon match, always, beside any reveal.

2. The team's turn. acting_seats(match) is the dragon of match.active
   while neither has locked, then the one that has not. pending(engine,
   match, seat) asks for a seat; pending_prompts(engine, match) lists
   one per acting seat; pending_prompt keeps its one-seat reading for
   the duel and the free-for-all. The turn opens on both teammates'
   TECH_CONFIRM (or TECH_CHOICE), each pending, and begin_turn runs
   once both are settled; it readies and upkeeps both teammates in
   seat order, each UPKEEP_ORDER its owner's, the owed BEGIN_TURN
   resuming through the same step after an answer, and takes one
   snapshot for the team's turn. Every action names its seat
   (arguments["player"]; the driver fills it from match.active where an
   older journal has none) and driver.answer finds that seat's prompt;
   while one teammate's action stands half-resolved (CHOOSE_DEFENDER,
   the three choices inside an attack, TARGET, DIVIDE_DAMAGE,
   MODE_CHOICE, APPEL_STOMP_TOP, UPKEEP_ORDER, LEVEL_GAIN, STASH,
   CHOOSE_NUMBER, OATH), pending_prompts is that prompt alone and the
   other teammate's action is refused with "waiting on {player:n}'s
   attack". PlayerState.locked (saved, false) is set by a seat's patrol
   lock and cleared by begin_turn; the second lock runs the draw phase
   and begin_tech for both, and the tech choices of both stand through
   the other team's turn. An extra turn is one seat's alone (p. 13:
   "you means you"): extra_turns names a seat and acting_seats is that
   seat while it runs, the teammate's cards neither readying nor
   acting. next_seat hands the turn to the other dragon's first seat.
   The two undos work over the team turn's snapshot, and
   start_tech_over clears and asks again both teammates' picks and
   both opponents'; undo_targets is unchanged.

3. Attacking. legal_defenders for an attacker of a dragon seat: either
   opponent's squad leader -- the attacker choosing which when it
   could attack both -- then any other patroller in either opponent's
   zone, then anything with HP either opponent controls and the shared
   base (p. 13), the rows carrying their seat as step 1 made them; the
   tower detects a card attacking its owner or the shared base and not
   one attacking the teammate's cards (p. 4 with "you means you"), and
   hits an attacker of anything its owner's team controls (the tower
   ruling) -- both as written; if the author reads them as one rule the
   ruling governs; overpower's excess may go to anything the attacked
   team controls (the overpower ruling); Moment's Peace protects its
   caster's cards and the shared base (its ruling); a part that damages
   "an opponent's base" for each of something hits the one base once
   (the Captured Bugblatter and Drakk rulings); a destroyed tech
   building or add-on deals its 2 to its team's base; a dead hero's
   levels may go to either of the other team's heroes, the active
   player choosing (p. 11).

4. The words. "Friendly" on the eleven cards and heroes that say it
   (the worksheet lists them; confirm the list with a script) is a flag
   on the effect's part, friendly=True, which the own_* filters read:
   the controller's own things, or in a dragon the teammate's too;
   "your", "you control" and a count of what "you have" stay the
   controller's alone (p. 13). Nobody spends a teammate's gold, uses a
   teammate's abilities or patrols in a teammate's zone -- say in the
   PR where each is already impossible by construction and where a test
   holds it. The audit of "opponent" from step 2 is re-read for the
   dragon: a teammate is never an opponent.

5. The whole game and the golden. tests/test_codex_driver_full_game.py
   plays a dragon -- basic and standard -- to a destroyed base, the
   policy answering whichever seat pending_prompts lists, with a journal
   replay of one team turn; tests/test_codex_golden.py gains a seeded
   dragon pinned in tests/golden/codex_dragon_*; the duel's and the
   free-for-all's files do not change.

The stop: the whole-game test and the golden pass, and the transcript
of a team's turn reads as one turn with two players' actions in it.
```

### 6. Two-headed dragon on Discord

Two panels at once under one turn message, a teammate's hand, the
lobby's two teams, a concession both teammates agree to, and the board
as two rows with one base a team.

```text
Step 6 of docs/codex-multiplayer.md. Steps 1 to 5 have landed. Also
read what step 4 wrote into docs/design/codex.md, "Multiplayer", and
"The panel", "The end of a game" and "The requests per click". Three
commits: the lobby; the panels and the turn message; the board and the
end.

1. The lobby. Two-headed dragon on the variant row seats four in two
   teams, the lobby's rows headed "Team 1" and "Team 2"; a seat is
   taken in order, a player who wants the other team leaves and sits
   again; a test game sits its one person on all four. Start renames
   the channel codex-<n>-<p1>-<p2>-vs-<p3>-<p4>, capped at 100.

2. The panels and the turn message. The heading names both teammates
   and the post pings both (decision 13); My hand gives each acting
   seat its own panel from pending(engine, match, seat) and any other
   seat their hand, and in every case a dragon seat's teammate's hand
   pictured under it through hands_visible_to and the revealed-hand
   picture, captioned with the teammate's name ("<name>'s hand", not
   "Their hand"); /codex hand the same. A public click by either
   teammate posts the turn message again and sends that clicker's
   panel under it, the other's standing where it was until their next
   click, which the driver checks against the options as they stand
   and which puts their panel under the board afresh (as every public
   click does); a click refused because the teammate's action is
   half-resolved is shown in the panel, with the hand. In a test game,
   where one person holds both acting seats, the panel is the first
   unlocked teammate's with a Switch to <team> button that sends the
   other's. The tech pickers stand for both seats of the team whose
   turn ended. Undo: To the start of my turn is either teammate's
   without consent; the previous turn asks the other team, either of
   whose players may Agree and anyone Refuse (question 12). Concede
   (decision 15): the clicker's own ephemeral confirmation as now, then
   a public question naming the teammate -- Agree the teammate's or a
   helper's behind the helper's confirmation, Refuse either teammate's
   -- modelled on UndoConfirmView, not persistent; on Agree the
   service's concede ends the game, the other team winning. Extend the
   request table with the dragon's clicks; nothing already in it
   changes.

3. The board and the end. compose_board draws a dragon as two rows of
   two panels, the far team's turned as the duel's far panel is, the
   shared base drawn once in each team's first panel's building column
   and the second column one tile shorter (decision 14); teach
   scripts/render_codex_sample.py a dragon position and put the picture
   in the PR for question 2. No Swap view. The winner's line names the
   team ("{player:1} and {player:2} win: the other team's base is
   destroyed."), Rematch keeps the seats and the teams and clears every
   seat's heroes to be picked again (decision 16), the channel to
   Codex Archive as now.

The stop: four people (or one person on four seats in the test server)
finish a dragon, one of them having seen their teammate's hand, and
the author has looked at the board.
```

### 7. The look back: what the modes left in two places, and the design note

The Codex series' step 9, for the modes: once both play, what turned
out identical in the free-for-all's and the dragon's code moves to one
home, and the design note says what each step settled.

```text
Step 7 of docs/codex-multiplayer.md. Steps 1 to 6 have landed. Read
the "Multiplayer" section of docs/design/codex.md as the six steps
left it, and the diff of the series (git log --oneline main -- codex
cogs/codex cogs/codex_views gamesaves/codex since step 1's merge). Two
commits: the move; the note.

1. The move. Whatever steps 2 to 6 wrote twice -- a seat loop in the
   lobby view and the cog, a per-variant branch in two renders, a
   test staging helper in two test files -- moves to one home with the
   tests unchanged, as the Codex series' step 9 did; nothing changes
   behaviour, and the three goldens hold. List in the PR each thing
   moved and from where.

2. The note. docs/design/codex.md's "Multiplayer" section says, with
   the reasoning, what the series settled: the four readings, the
   variant and the seats, the playoff, lending's control, the dragon's
   two prompts and its one base, the words, the board, who may undo
   and concede, which rulebook governs -- and strikes nothing the
   author overruled without saying what replaced it. CLAUDE.md's tables
   gain a row only for a new module or a new hard rule; the "Read this
   before touching..." row for the Codex bot gains the multiplayer
   names.

The stop: nothing a step of this series copied remains in two places,
and the note reads as the one home of every decision above.
```

## What is not in these prompts, on purpose

- **Maps** (the deluxe variant). Not asked for; nothing in the state
  assumes none, and nothing is built for one.
- **An AI opponent.** Decision 18. A multiplayer game without one is
  three to five people, as the author asked.
- **A teammate's view of the other's tech choice or codex.** Question
  14; one picture later if the author wants it.
- **The finer undo.** Its infrastructure is in; the modes keep it
  working over the team's turn and do not build it.
- **Mixed tables** -- a duel's rules at three, or a dragon of three.
  The rulebook plays the modes as written and so does the bot.
- **A rotation of seats or teams at a rematch.** The author chose a
  fresh pick of heroes in the same seats (decision 16).
- **Statistics and an archive export.** Still not for this bot.
- **A rulebook of our own.** The bot cites a page; it does not reprint
  one. Both rulebooks are committed under `docs/codex/` for that.

# The Codex bot's multiplayer modes: free-for-all and two-headed dragon

**This is a worksheet, not a specification.** It was written on
2026-10-10 from the author's ask -- the two multiplayer modes of
Sirlin Games' *Codex*, **free-for-all** (3 to 5 players, every base its
own) and **two-headed dragon** (two teams of two, one base a team), for
the Codex bot that [codex-bot.md](codex-bot.md) built -- against the
rules as the Unofficial Manual Rewrite v1.3 has them (`UMR p. n`,
committed at `docs/codex/Codex_UMR_v13w.pdf`), against Sirlin's rulings
in `codex/data/rulings.json` (seven name the modes), and against what
the bot is on `main` that day: steps 1 to 13 of the Codex series landed,
every printed card playing, the two undos on the turn message (PR #525).
Each step below has a prompt a Claude Code session is started with.
Strike a step when it lands and move what it settled into
[design/codex.md](design/codex.md). **Nothing in it is a rule.**

Two notes on the sources. The UMR is a fan compilation -- Dean Ray
Johnson's, from Sirlin Games' manual and Chris Franka's rulings -- which
the author prefers to the official rulebooks and which should agree with
them on every matter (codex-bot.md, "What the three outside sources
give"); the official rulebooks at sirlingames.com could not be fetched
from the session that wrote this (the host is outside its network
policy), so nothing below has been checked against them, and a
disagreement found later is a question for the author, not a decision
here. The rulings are Sirlin's own and govern where they and the UMR's
text differ; the one place the two read differently on these modes is
the tower in a two-headed dragon, noted below.

## What was found, and what it settles

### The two modes, in the terms the code will use

Both are played "as the basic or standard game" with changes (UMR
p. 12), so each is a third axis on a game beside its hero count:
`mode` (basic, standard) says how many heroes a seat plays, and the
new **variant** says how many seats and how they stand to each other --
the **duel** the bot plays today, a free-for-all, or a two-headed
dragon. What each adds, read from the UMR and the rulings:

**Free-for-all** (3 to 5 players; UMR p. 12, with p. 4, 5, 9, 10, 11, 15
and 16):

- **Setup** (p. 4, 12). A first player drawn at random; turns in
  clockwise order, which for the bot is the lobby's seat order from the
  first player on. The first player starts with 4 workers, every other
  player with 5. The 3rd, 4th and 5th players start with 1, 2 and 3
  **Mercenaries** in play: neutral 1/1 units, with arrival fatigue on
  their owners' first turns. The Mercenary is already in the card data
  as a token (`mercenary`, `kind: token`, `starting_zone: trash`) and
  its face is cut from the module's token sheet
  (`scripts/import_codex_cards.py`, `tokens/mercenary`).
- **The ending** (p. 12). No elimination: the game ends when any base
  is destroyed, and the player with the most base HP left wins. A tie
  for most: finish the current player's turn, then every tied player
  takes one more turn, then the most HP wins, or the same again while
  the tie holds.
- **Repair base** (p. 11, 12): a main-phase action, 3 gold for 1 base
  HP, to a maximum of 20.
- **Unit bounties** (p. 11, 12): 1 gold each time the active player
  destroys an enemy unit on their turn, by any means, to 3 gold a turn;
  never for a hero or a building.
- **Lending patrollers** (p. 11, 12, 15): a player may lock cards in
  empty slots of any opponent's patrol zone, their own included, any
  number of zones at once. A lent card is under the borrower's control
  (p. 15: "that player gains temporary control of your card", so an
  effect on "your units" is the borrower's), the lender still gets the
  scavenger's gold and the technician's card when a lent patroller
  dies, a destroyed lent card goes to its owner's discard pile or
  command zone, and every lent patroller returns to its owner during
  the **borrower's** upkeep (p. 5, 11).
- **The tower** (p. 9; the General group's tower rulings): it detects
  one attacker on each opponent's turn, and only a card attacking its
  owner; it hits only an attacker of something its owner controls.
- **Armor** (p. 16; the Ironbark Treant ruling) refreshes at the
  beginning of every turn, each opponent's included.
- **A destroyed hero** (p. 10) gives two levels to one of the
  *destroyer's* heroes, as in a duel.
- **The word "opponent"** on a card. The UMR gives no general rule, so
  the plan reads the card texts (342 cards and heroes in
  `codex/data/`: 43 say "opponent" or "opposing", 21 "opponents" or
  "each opponent"): a plural or "each opponent" is every opponent; "an
  opponent" or "an opponent's" is one the controller chooses, which is
  the existing `TARGET` prompt over rows keyed by seat, asked only where
  more than one could be chosen, as every target is; "the opponent" in
  a context that names one (the player attacked, the owner of the unit
  that died) is that one. The step that builds the mode lists every
  card and the reading it got, for the author.

**Two-headed dragon** (four players in two teams; UMR p. 12, with p. 4,
9, 11, 17, 19 and 21):

- **Setup** (p. 4, 12). Each team shares **one base at 30 HP**; a team
  drawn to go first; both its players start with 4 workers, both of the
  other team's with 5. Every player has their own heroes, deck, codex,
  workers, hand, gold, tech buildings and patrol zone; **both teammates
  may construct one add-on**. Teammates may show each other their cards
  and talk strategy at any time (p. 12), which the bot neither helps nor
  prevents (question 4).
- **The team's turn** (p. 12). Teammates take their turns at the same
  time, one phase at a time: both ready, both upkeep, a main phase in
  which they act in any order **but the team takes and resolves one
  action at a time**, both draw, both tech. An extra turn from an
  effect is taken by that player alone.
- **Attacking** (p. 11, 12). Both teammates' patrol zones protect the
  whole base: an attacker must take either opponent's squad leader,
  then any other patroller in either opponent's zone, then anything
  with HP either opponent controls, the shared base included. Nobody
  patrols in a teammate's zone, spends a teammate's gold or uses a
  teammate's abilities.
- **"You" and "friendly"** (p. 12, 17). "You" is the player's own
  cards; "friendly" is the teammate's too ("Friendly: Something
  controlled by you or your teammate"). Eleven cards and heroes say
  "friendly" (Aged Sensei, Bloom, Eyes of the Chancellor, Focus Master,
  Forest's Favor, Fuzz Cuddles, Helpful Turtle, Savior Monk, Sparring
  Partner, Spirit of the Panda, Verdant Tree); 96 say "your" or "you
  control". Today the engine reads both as the controller's seat.
- **The tower** (p. 9; the tower ruling). The UMR: a tower detects a
  card attacking its owner or the shared base, not one attacking the
  teammate's cards. The ruling: the tower's damage goes to an attacker
  of anything "controlled by the player (or team in 2v2)". Read
  together, the detection is narrower than the damage; the step pins
  both as written, and if the author reads them as one rule the ruling
  governs.
- **Overpower** (the General group's overpower ruling): the excess may
  go to anything with HP "controlled by the player (or team in 2v2)
  whose patroller was attacked".
- **One base, hit once** (p. 19; the Captured Bugblatter and Drakk
  Ramhorn rulings): an effect that damages "the opponent's base" per
  something damages the team's one base once.
- **Moment's Peace** (p. 21; its ruling): protects its caster's cards
  and the shared base, not the teammate's cards.
- **Nothing of the free-for-all's three additions**: no repair, no
  bounties, no lending.

**What both leave alone**: the five phases, the hero count and the
codex, the tech choice standing while others play, the two undos, the
journal, concede and abandon -- each with a question where a seat became
seats (questions 5 to 8).

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
  every side.
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

- **Tokens of a deal**: Dancers, Squirrels and the rest are tokens the
  engine makes in play, with `made_by` where a card made them; a
  Mercenary is one made by nobody.
- **Owner against controller**: `CardInstance.owner` and `controller`
  since step 2, `returns_to` since step 11 for a card that goes back
  (Kidnapping), and the rule that a card leaving play returns to its
  owner. Lending is a control change with its own moment of return.
- **Targets keyed by seat**: `TargetRow` is `"<seat>:<ref>"`, so a
  `TARGET` prompt over several opponents' things needs no new shape.
- **Lists where a seat might have been one**: `extra_turns` is a list,
  `standing_prompts` returns a list, `KEPT_SNAPSHOTS` is three.
- **The lobby rebuilt from the record** on every change, so a third
  row and more seats are the record's rules and one view.
- **The save format's habit**: every field with a fallback, every
  older save reading on; `_upgrade_refs` and `upgrade_hero_refs` show
  how a bare ref grows a seat.

## The decisions

These are the ones the plan is built on. Each is the recommendation
and its reason; the author overrules any of them by saying so on the
PR, and the step's prompt is rewritten rather than argued with.

0. **Both modes, in the basic and the standard game, as UMR p. 12
   has them** (the author's ask, 2026-10-10). The two-player game is
   **the duel** in the code and the docs from here on, and it changes
   in nothing a player can see: the duel golden stays byte for byte
   through every step.

1. **A refactor that changes nothing comes first.** The 66 inline
   sites each ask one of four questions, and step 1 gives each its one
   reading: **who are my opponents** (`engine.opponents(match, seat)`,
   a tuple, which a target set, a tower, Moment's Peace and the
   flagbearer read), **whom is this attack against** (the defending
   seat, carried on the combat record -- `combat["against"]`, and the
   declared attacker's target seat beside `attacking` -- rather than
   recomputed at every stage; an older save's bare refs read as against
   the one opponent, as `_upgrade_refs` reads an older journal),
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
   rules read the match -- the tower's reach, the bounties, the repair,
   the lending, the shared base -- and a match outlives the record's
   lobby. `codex.game.VARIANTS` holds the three names. The hero count
   stays `mode`; the two are independent, as the rulebook says.

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
   runs to its end, `playoff` is filled with the tied seats in turn
   order from the next, `next_seat` reads it ahead of the normal order,
   and when it empties the comparison is made again -- a winner, or the
   list filled again. `winner` stays one seat; `GameOverOptions` grows
   `winners` and the base HP of every seat, since the ask says the
   score. The conceding player in a free-for-all is read as a player
   whose base was destroyed (question 5).

6. **Mercenaries are dealt, not built.** `new_match` puts 1, 2 and 3
   `mercenary` tokens in play for seats 3, 4 and 5 with arrival fatigue
   that lasts through their owner's first turn, whatever `arrived`
   means for a card played mid-turn -- the step reads how the engine
   holds fatigue and makes a dealt token hold it until its owner's
   first turn ends.

7. **The three additions are rules behind `variant`, in the model.**
   *Repair base* is a `MAIN_ACTION` option (`repair_base`), offered
   with its cost and refused as every option is. *Bounties* are
   `PlayerState.bounties`, the gold earned this turn (saved, 0),
   written where `board.destroy` destroys a unit -- a token included --
   controlled by an opponent of the active seat during that seat's
   turn, capped at three, cleared when the turn begins. *Lending* is a
   control change: the `PATROL` prompt's options grow each opponent's
   empty slots (`zones`, keyed by seat), the lock action names where
   each card goes, a lent card's `controller` becomes the borrower and
   **`lent`** (a saved flag, false) marks it, the borrower's upkeep
   returns every card they control with `lent` set to its owner
   (`controller` back, out of the zone, readied as the ready phase
   readies), the scavenger's and technician's payouts read the owner,
   and a lent card destroyed leaves play to its owner as every card
   does. A lent **hero** -- the rulebook says "cards", and heroes
   patrol -- sits in the borrower's slot as `"<owner seat>:hero:<slug>"`
   (the spelling `attached_hero` already uses) with `lent_to` on the
   `HeroState` (saved, `None`); the hero stays on its owner's list and
   `controller_of` reads the field. Built as both; question 9 is
   whether heroes may wait.

8. **The dragon's two seats are two pending prompts.** `pending` stays
   the one reading of what a seat waits on, and grows a `seat`
   argument; `pending_prompts(engine, match)` lists one per acting
   seat, and `driver.answer` finds the prompt of the action's seat,
   which every action now names (`arguments["player"]`, as the tech
   actions already do) -- the journal records it with the action. The
   team acts one action at a time (p. 12): while one teammate's action
   stands half-resolved (a defender, a target, an upkeep order owed),
   the other's `MAIN_ACTION` is not listed, so a click of theirs is
   refused with why. Each seat's **patrol lock is its own**
   (`PlayerState.locked`, saved, false, cleared when the turn begins):
   the first lock ends that seat's actions, the second ends the team's
   main phase and the draw and tech phases run for both. The snapshot
   is the team turn's, so **To the start of my turn** is the team's
   (question 7). The ready and the upkeep run for both teammates in
   seat order, each `UPKEEP_ORDER` asked of its owner.

9. **The dragon's base is the team's first seat's `base_hp`, through
   `base_of`.** Every read and write of a base goes through the one
   reading step 1 makes, so the shared base needs no field: the
   dragon's `base_of` is its first seat's, the second seat's `base_hp`
   is dealt at 30 too and never read. `MatchState.dragons` (saved, `[]`)
   holds the two pairs of seats; `engine.teammate(match, seat)` and
   `opponents` read it. **What it costs**: a number in the save that
   means nothing, documented as such.

10. **"Friendly" is a flag on the effect's part.** The eleven cards and
    heroes that say "friendly" get `friendly=True` on the parts whose
    text says it, and the target filters `own_*` read the flag: the
    controller's own things, or in a dragon the teammate's too. "Your"
    and "you control" stay the controller's alone. The audit of the
    eleven is in the step's PR, text beside flag.

11. **"An opponent's" is a target across opponents.** `target_candidates`
    enumerates every seat and filters by `opponents(seat)` instead of
    `side != seat`; a part that names one opponent's thing lists each
    opponent's, and the existing `TARGET` prompt asks where more than
    one. A part that damages "the opponent's base" (Captured Bugblatter,
    Drakk) hits one base, the chosen opponent's, and in a dragon the one
    base once. An effect frame's `against` is set by what started it --
    the attack's defending seat, the chosen target's seat -- and
    `_against(top)` no longer has a default to fall back on.

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

13. **The turn message and the panels.** The heading stays the model's:
    a free-for-all's is a duel's; a dragon's names both teammates --
    "**Turn 7** -- @ann (Blood Anarchs) and @bo (Moss Sentinels)" -- and
    the post pings both. **My hand** answers by the clicker's seat as
    now: an acting seat's gets the panel, any other their hand. In a
    dragon both teammates hold a panel at once; a public click by one
    posts the turn message again, and the other's panel stands above it
    until their next click, which the driver checks against the options
    as it stands and which sends their panel afresh under the board, as
    every public click does. The tech pickers stand for every seat whose
    turn has ended, as the one standing choice does today; in a dragon
    test game, where one person holds both acting seats, the panel is
    the first unlocked teammate's with a **Switch to <team>** button.

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

15. **Undo and concede, by default.** *To the start of my turn*: any
    acting seat's, without consent, the team's turn in a dragon. *To the
    start of the previous turn*: unwinds the previous seat's turn in a
    free-for-all, so that seat is asked, and the other team's in a
    dragon, so either of its players may **Agree** and anyone at the
    table **Refuse**. *Concede*: a free-for-all's conceding player ends
    the game as a destroyed base would, their base read as 0 for the
    comparison; a dragon's either teammate concedes for the team, behind
    the second click as now. Questions 5 to 7.

16. **A rematch keeps everything but who goes first.** The same seats,
    the same teams and heroes, the first player or team drawn again;
    **Keep heroes** and the swap are a duel's and are not shown. The
    author may want a rotation (question 8).

17. **Two new goldens, one a mode**: a seeded three-player basic game
    and a seeded dragon, byte for byte in `tests/golden/codex_ffa_*` and
    `codex_dragon_*`, re-recorded as the duel's is. The duel's is not
    re-recorded for any of this: where a step must touch it, the PR says
    why and shows the normalised diff empty.

18. **No AI, still** (codex-bot.md, decision 13): the whole-game test's
    policy plays every seat, three to five.

19. **A series of its own, claimed like the others**: `multiplayer` in
    `scripts/claim_web_step.py`'s `SERIES`, worksheet this file, branches
    `codex-mp-step-<n>`, PRs titled `Codex multiplayer step <n>:`. Step
    1's prompt adds it. Whether the cloud routine runs this series is
    the author's (question 10).

## Questions for the author

Each step's PR carries a `## Questions to the author` section; these
are the ones known before any step starts. A step whose prompt needs the
answer says what it builds until it has one.

1. **What is a two-player team called in the code and in the
   narration?** "Team" is taken: it is a player's heroes
   (`team_name`, "Blood Anarchs", the rematch "swaps the two teams"),
   and the rulebook uses it for both. Built as **`dragon`** in the code
   (`dragons`, `dragon_of`, `teammate`) and **"team"** in what the bot
   says, as the rulebook says it ("the other team's base is
   destroyed"), the nameplate's hero team unchanged.
2. **How should a board of three to five, and a dragon's, look?**
   Decision 14 is a proposal; the step renders both with
   `scripts/render_codex_sample.py` and the author looks before the
   Discord step is worth starting.
3. **Should both modes be offered in the basic game?** The rulebook
   allows it ("as the basic or standard game"). Built as yes.
4. **May a teammate see the other's hand through the bot?** The
   rulebook lets teammates show their cards. Built as **no**: teammates
   talk where they like, and the bot shows a hand to its owner alone,
   as it does today. A **Teammate's hand** button is one view later.
5. **What does conceding do in a free-for-all?** The rulebook has no
   elimination and no word on it. Built as decision 15: the game ends,
   the conceder's base read as destroyed.
6. **Does a teammate's concession end the team's game?** Built as yes,
   behind the second click.
7. **Does the undo to the start of the team's turn need the teammate's
   consent?** Built as no: the turn is the team's and the snapshot is
   one; the opposing team's consent is asked for the previous turn.
8. **What does a rematch change in a multiplayer game?** Built as
   decision 16: nothing but who goes first.
9. **May lending be units only to start?** Built as both, decision 7;
   if the author prefers, the hero's `lent_to` waits and the PATROL
   options list units alone.
10. **Does the cloud routine run this series?** It reads
    `docs/codex-bot.md`; a second routine over this file, or the one
    routine given a second worksheet, is the author's call. Until then
    the steps are claimed by hand.

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
| 3 | Free-for-all's three additions: repair, bounties, lending | medium | a lent patroller defends, pays its owner and comes home at the borrower's upkeep; the golden re-recorded if the transcript gained a line |
| 4 | Free-for-all on Discord | large | three people reach the end of a game: the lobby, the channel, the stacked board of three, the pickers standing for two, concede, rematch |
| 5 | Two-headed dragon through the driver | large | a test plays a dragon from the deal to a destroyed base, both teammates acting in one main phase; the dragon golden |
| 6 | Two-headed dragon on Discord | medium | four people finish a game: two panels at once, the board of two rows, the shared base |
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

Whether the cloud routine of codex-bot.md ("Claiming a step") runs this
series is question 10; until the author says, a human claims each step.
Every PR carries the two sections the Codex series' PRs carry:
`## Questions to the author` (`None.` when empty) and `## For the
author` -- what to do on the live host after merging, and what can be
tested in the server now, command by command.

## Preamble

Every step's prompt begins with **the Codex preamble in
[codex-bot.md](codex-bot.md), "Preamble"**, whole, and then this block.

```text
The step is from docs/codex-multiplayer.md, the worksheet for the two
multiplayer modes: read its "The two modes, in the terms the code will
use" (the rules you implement, with the UMR page each is on), "What the
bot assumes today" (the survey step 1 is written from) and "The
decisions"; then docs/design/codex.md whole, since every section of it
names a seat somewhere. Then UMR p. 12 (the two modes), p. 11 (bounties,
team patrol zones, repair, lending), p. 9 (the tower), p. 4 (setup), p.
5 (the upkeep's return), p. 15 (control), p. 16 (armor), p. 17 (the
glossary's "Friendly") and the Card FAQ entries on p. 19 and 21; and the
seven rulings in codex/data/rulings.json that say "2v2", "Two-Headed
Dragon", "free-for-all" or "team" -- the General group's overpower and
tower rulings, Captured Bugblatter's, Drakk Ramhorn's, Ironbark Treant's
and Moment's Peace's.

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
- A seat's hand, deck, discard and tech choice stay its own: a
  teammate's panel, a lent card's borrower and a watcher see none of
  it; nothing hidden reaches a public message or a log line, as the
  Codex preamble says.
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
   will later leave the teammate out -- and the seven callers read it.
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
   returns opponents(seat). standing_prompts lists every seat other than
   the active one with a tech choice owed. tokens.player and
   tokens.addressed accept any positive seat; formatting's plain-text
   fallback stays "Player n". The idiom 2 if x == 1 else 1 is gone from
   codex/ when this commit is done, and upgrade_hero_refs reads the
   seats it has rather than assuming two.

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
the turn order, the ending and its playoff, the tower's and armor's
free-for-all rules, and the reading of "opponent" on every card, played
whole through `driver.apply` by the test policy with nothing from
`cogs/` imported -- the Codex series' step 2, for the mode.

```text
Step 2 of docs/codex-multiplayer.md. Step 1 has landed. Also read
tests/test_codex_driver_full_game.py and tests/test_codex_golden.py
(what you extend), codex/flow/turn.py whole (begin_turn, begin_tech,
damage_base) and codex/effects.py's target filters. Four commits: the
variant and the deal; the turn and the ending; the tower, armor and
"opponent"; the whole game and the golden.

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
   went first, as now), and in a free-for-all seats 3, 4 and 5 are
   dealt 1, 2 and 3 mercenary tokens in play, owned and controlled by
   their seat, made_by None, with arrival fatigue that holds through
   their owner's first turn -- read how arrived is held and cleared and
   make a dealt token clear at the end of its owner's first turn, with
   a test that a Mercenary cannot attack on its owner's first turn and
   can on the second (UMR p. 12). The board draws the token's face
   (tokens/mercenary) as it draws a Dancer's.

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
   goes on: next_seat reads playoff ahead of the order, popping the
   seat it hands out, and begin_tech, when playoff has emptied, makes
   the comparison again -- a winner, or the list filled again. A base
   destroyed during a playoff is one more base at zero. Concede in a
   free-for-all sets the conceder's base to zero and makes the same
   comparison (question 5). GameOverOptions grows winners (a tuple)
   and base_hp per seat; the duel's winners is (winner,). Test every
   branch of the playoff with a staged position, through the driver.

3. The tower, armor and "opponent". tower_detects: in a free-for-all
   the tower detects one attacker on each opponent's turn and only a
   card attacking its owner (p. 9); the tower's damage falls only on an
   attacker of something its owner controls (the tower rulings). Armor
   refreshes at the start of every turn for every seat (p. 16, the
   Ironbark Treant ruling -- the Treant's own armor too). Then the
   audit: every card whose text says "opponent", "opponent's",
   "opposing", "opponents", "opponents'" or "each opponent" (43 and 21
   on 2026-10-10 -- list them with a script over codex/data/cards.json
   and heroes.json, bands included), and for each the reading decision
   11 gives: a plural is every opponent; "an opponent's" lists each
   opponent's things as TargetRows and TARGET asks where more than one
   (a part that damages "the opponent's base" lists each base); "the
   opponent" in a context that names one is that one (the attack's
   against, the frame's). Put the list in the PR with the reading each
   card got, for the author. Discord, Reputable Newsman, Flagbearer,
   Moment's Peace, Captured Bugblatter and Carrion Curse each get a
   three-player test.

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

### 3. Free-for-all's three additions: repair, bounties, lending

The three rules UMR p. 11 adds, as options and fields behind
`match.variant`, in the model. Lending is the only one that changes who
controls a card, and the one that touches the patrol prompt both sides
read.

```text
Step 3 of docs/codex-multiplayer.md. Steps 1 and 2 have landed. Also
read docs/design/codex.md "The keywords" (the patrol bonuses) and "Red
and green" (control that returns), codex/flow/board.py's destroy and
the patrol lock in codex/flow/actions.py. Three commits: repair;
bounties; lending.

1. Repair base (UMR p. 11, 12). A MAIN_ACTION option, repair_base,
   listed on a free-for-all match with its cost and why it may not be
   taken (under 3 gold, the base at 20, the variant not a free-for-all)
   -- the options' shape for hire and build -- and an action the driver
   runs: 3 gold for 1 base HP through base_of, repeatable, journaled,
   narrated ("{player:2} repairs the base: 15 HP."). A test through the
   driver, and one that a duel never lists it.

2. Unit bounties (p. 11, 12). PlayerState.bounties, saved, 0 in an
   older save, cleared in begin_turn. Where board.destroy destroys a
   unit -- a token included, never a hero or a building -- on a
   free-for-all match, during the active seat's turn, controlled by one
   of opponents(active) at that moment (a card lent to an opponent is
   theirs), the active seat gains 1 gold, to 3 a turn, said in the
   destroy line ("... and {player:1} collects a bounty, 1 gold."), the
   gold cap respected. Tests: a kill in combat, a kill by a spell, a
   kill by an opponent's own trigger on the active player's turn, the
   fourth kill of a turn, a hero's death, a building's, a duel.

3. Lending patrollers (p. 5, 11, 12, 15). PatrolOptions grows zones:
   each opponent's empty slots keyed by seat, on a free-for-all match
   alone, beside the owner's own slots; the patrol action's arguments
   name a seat per assigned slot (the owner's where none, so every
   older journal and the duel read as before); lock sets each lent
   card's controller to the borrower and lent (CardInstance, saved,
   false) true, and a lent hero's HeroState.lent_to (saved, None) with
   the borrower's slot holding "<owner seat>:hero:<slug>" -- the
   spelling attached_hero uses -- the hero staying on its owner's list
   and every controller reading of a hero going through controller_of.
   The borrower's upkeep returns every card they control with lent set
   and every hero with lent_to naming them: out of the zone, controller
   back to the owner, in the owner's play zone, readied as their ready
   phase would (p. 5). The scavenger's gold and the technician's card
   pay the owner (p. 11); a lent card destroyed leaves play to its owner
   as every card does; the kill's levels go to the destroyer's hero
   (p. 10); an effect on the borrower's "your units" reaches a lent card
   and the lender's does not (p. 15). What the patrol bonuses do on a
   lent card (the squad leader's armor, the elite's ATK) is the
   borrower's zone's, as any patroller's. Tests for each sentence, and
   a journal replay (history.replay) through a turn that lends.

The free-for-all golden is re-recorded only if the transcript gained a
line (a repair, a bounty), and the PR says so; the duel's does not
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
   whose turn is unwound (engine.next_seat run backwards is not a
   reading; the snapshot's active seat is), Agree theirs or a helper's,
   Refuse anyone's at the table. Concede, the first click, names what
   decision 15 says will happen. The request table holds for every
   click that exists today; the PR extends it with the clicks a third
   seat adds.

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
   Rematch opening a lobby with the same seats and no Keep heroes
   (decision 16), the channel to Codex Archive as now. The startup
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
   the other's 5 (p. 12), and sets every base_hp to 30 (DRAGON_BASE_HP)
   -- base_of reads a dragon's first seat's, and the second's is never
   read (decision 9; say so in the field's docstring). Nothing of the
   free-for-all's three additions is listed on a dragon match.

2. The team's turn. acting_seats(match) is the dragon of match.active
   while neither has locked, then the one that has not. pending(engine,
   match, seat) asks for a seat; pending_prompts(engine, match) lists
   one per acting seat; pending_prompt keeps its one-seat reading for
   the duel and the free-for-all. Every action names its seat
   (arguments["player"]; the driver fills it from match.active where an
   older journal has none) and driver.answer finds that seat's prompt;
   while one teammate's action stands half-resolved (CHOOSE_DEFENDER,
   the three choices inside an attack, TARGET, DIVIDE_DAMAGE,
   MODE_CHOICE, APPEL_STOMP_TOP, UPKEEP_ORDER, LEVEL_GAIN, STASH,
   CHOOSE_NUMBER, OATH), pending_prompts is that prompt alone and the
   other teammate's action is refused with "waiting on {player:n}'s
   attack" (p. 12: one action at a time). begin_turn readies and
   upkeeps both teammates in seat order, each UPKEEP_ORDER its owner's,
   and takes one snapshot for the team's turn; PlayerState.locked
   (saved, false) is set by a seat's patrol lock and cleared by
   begin_turn; the second lock runs the draw phase and begin_tech for
   both, and the tech choices of both stand through the other team's
   turn. An extra turn is one seat's alone (p. 12): extra_turns names
   a seat and acting_seats is that seat while it runs. next_seat hands
   the turn to the other dragon's first seat. The two undos work over
   the team turn's snapshot; undo_targets is unchanged.

3. Attacking. legal_defenders for an attacker of a dragon seat: either
   opponent's squad leader, then any other patroller in either
   opponent's zone, then anything with HP either opponent controls and
   the shared base (p. 11), the rows carrying their seat as step 1 made
   them; the tower detects a card attacking its owner or the shared
   base and not one attacking the teammate's cards (p. 9), and hits an
   attacker of anything its owner's team controls (the tower ruling) --
   both as written, as "The two modes" in the worksheet has them; if
   the author reads them as one rule the ruling governs; overpower's
   excess may go to anything the attacked team controls (the overpower
   ruling); Moment's Peace protects its caster's cards and the shared
   base (p. 21, its ruling); a part that damages "the opponent's base"
   for each of something hits the one base once (p. 19, the Captured
   Bugblatter and Drakk rulings); a destroyed tech building or add-on
   deals its 2 to its team's base. Both teammates may each hold an
   add-on (p. 12).

4. The words. "Friendly" on the eleven cards and heroes that say it
   (the worksheet lists them; confirm the list with a script) is a flag
   on the effect's part, friendly=True, which the own_* filters read:
   the controller's own things, or in a dragon the teammate's too;
   "your" and "you control" stay the controller's alone (p. 12, 17).
   Nobody spends a teammate's gold, uses a teammate's abilities or
   patrols in a teammate's zone -- say in the PR where each is already
   impossible by construction and where a test holds it. The audit of
   "opponent" from step 2 is re-read for the dragon: a teammate is never
   an opponent.

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

Two panels at once under one turn message, the lobby's two teams, and
the board as two rows with one base a team.

```text
Step 6 of docs/codex-multiplayer.md. Steps 1 to 5 have landed. Also
read what step 4 wrote into docs/design/codex.md, "Multiplayer", and
"The panel" and "The requests per click". Three commits: the lobby;
the panels and the turn message; the board and the end.

1. The lobby. Two-headed dragon on the variant row seats four in two
   teams, the lobby's rows headed by team ("Team 1", "Team 2" -- the
   wording question 1 settles); a seat is taken in order, a player who
   wants the other team leaves and sits again; a test game sits its one
   person on all four. Start renames the channel
   codex-<n>-<p1>-<p2>-vs-<p3>-<p4>, capped at 100.

2. The panels and the turn message. The heading names both teammates
   and the post pings both (decision 13); My hand gives each acting
   seat its own panel from pending(engine, match, seat) and any other
   seat their hand; a public click by either teammate posts the turn
   message again and sends that clicker's panel under it, the other's
   standing where it was until their next click, which the driver
   checks against the options as they stand and which puts their panel
   under the board afresh (as every public click does); a click refused
   because the teammate's action is half-resolved is shown in the
   panel, with the hand. In a test game, where one person holds both
   acting seats, the panel is the first unlocked teammate's with a
   Switch to <team> button that sends the other's. The tech pickers
   stand for both seats of the team whose turn ended. Undo: To the
   start of my turn is either teammate's without consent (question 7);
   the previous turn asks the other team, either of whose players may
   Agree and anyone Refuse. Concede: either teammate's, for the team
   (question 6), the confirmation saying so. Extend the request table
   with the dragon's clicks; nothing already in it changes.

3. The board and the end. compose_board draws a dragon as two rows of
   two panels, the far team's turned as the duel's far panel is, the
   shared base drawn once in each team's first panel's building column
   and the second column one tile shorter (decision 14); teach
   scripts/render_codex_sample.py a dragon position and put the picture
   in the PR for question 2. No Swap view. The winner's line names the
   team ("{player:1} and {player:2} win: the other team's base is
   destroyed."), Rematch keeps the seats and the teams (decision 16),
   the channel to Codex Archive as now.

The stop: four people (or one person on four seats in the test server)
finish a dragon, and the author has looked at the board.
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
   and concede -- and strikes nothing the author overruled without
   saying what replaced it. CLAUDE.md's tables gain a row only for a
   new module or a new hard rule; the "Read this before touching..."
   row for the Codex bot gains the multiplayer names.

The stop: nothing a step of this series copied remains in two places,
and the note reads as the one home of every decision above.
```

## What is not in these prompts, on purpose

- **Maps** (the deluxe variant). Not asked for; nothing in the state
  assumes none, and nothing is built for one.
- **An AI opponent.** Decision 18. A multiplayer game without one is
  three to five people, as the author asked.
- **A teammate seeing the other's hand**, and anything else that helps
  a team talk. Question 4; one view later if the author wants it.
- **The finer undo.** Its infrastructure is in; the modes keep it
  working over the team's turn and do not build it.
- **Mixed tables** -- a duel's rules at three, or a dragon of three.
  The rulebook plays the modes as written and so does the bot.
- **A rotation of seats or teams at a rematch.** Question 8.
- **Statistics and an archive export.** Still not for this bot.
- **A rulebook of our own.** The bot cites a page; it does not reprint
  one.

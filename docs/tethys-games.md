# Two games on the Tethys deck: Tethys Hold 'em and Tethys Gang

**This is a worksheet, not a specification.** It was written on
2026-10-11 from the author's ask: "for the Tethys deck -- use the card
images we made for the Tethys deck commands. Make a plan for two games
-- Tethys Hold 'em, a poker style game with the ranks I've made that
has players play with 3 pocket cards forming sets of 6 cards, and
Tethys Gang which is a variant of cooperative Poker published as The
Gang." It is written against what is on `main` on that day: the deck
drawn as pictures (`tethysdeck/`, [design/tethys-deck.md](design/tethys-deck.md)),
Tethys poker's sets counted exactly (`tethysdeck/sets.py`), and the
`/tethyscards` commands dealing the same 72 cards as text
(`cogs/tethysdeck.py`). Each step below has a prompt a Claude Code
session is started with. Strike a step when it lands and move what it
settled into a new design note, `docs/design/tethys-games.md`.
**Nothing in it is a rule** -- the rules are the author's, and the
questions below are open until they answer.

**The sources.** Tethys poker is the author's, recorded in
[design/tethys-deck.md](design/tethys-deck.md), "Tethys poker: the
six-card sets". Texas Hold 'em is the common game, as any card room
plays it. The Gang is John Cooper and Kory Heath's, published by
KOSMOS in 2024; its rulebook is the publisher's
(<https://www.thamesandkosmos.com/manuals/full/683887_TheGang_Manual-Web_051624.pdf>),
cited here as `Gang p. n` by the number printed on the page, and **not
committed** -- it is someone else's book, and what this worksheet needs
of it is summarised below in its own words.

## What was found, and what it settles

### The deck and the sets, as they stand

Six suits of twelve -- Money, Tools, Might, Fiends, States, Fools; the
numbers 1 to 10, Left and Right -- six Fortune and six Doom in every
suit (`deck.fate_of`). Tethys poker reads **six cards the way poker
reads five**: all six count; Left and Right sit after 10 and **pair
only with each other** (a Left and a Right are a pair, two Lefts are
not); either follows 10 in a straight; nothing wraps. The ranking,
rarest first: six of a kind, 6-card straight flush, five of a kind,
6-card flush, two triples, four of a kind, 6-card straight, three
pairs, three of a kind, two pairs, one pair, no set. `sets.set_of` is
the one reading of which set six cards make; `sets.census` counts every
hand of six exactly, mixed and uniform (all six Fortune or all six
Doom).

What `sets.py` does **not** have, and both games need:

- **The order within a set.** `set_of` says two hands are both "two
  pairs"; a showdown needs to know which two pairs is higher, and when
  two hands are exactly equal. Poker's answer is the kicker. Tethys
  poker's has to say where a ruler stands as a kicker and how high the
  Left-and-Right pair is -- decision 4, from the author's answers.
- **The best six of more than six.** Both games deal each player three
  pocket cards and lay community cards beside them; a hand is the best
  six a player can make from all of them.

### Six of eight: how many cards a hand is chosen from

"Three pocket cards forming sets of six" leaves open how many community
cards there are. In Texas Hold 'em a hand is the best five of seven
(two pocket, five community). The Tethys ranking was built as the order
of rarity of **six cards dealt**; choosing the best six from more cards
changes how often each set comes up, and if it changes it enough a set
ends up ranked above one that is rarer than it. A sample of 40,000
hands for each deal (a script in the session's scratchpad, not
committed) gave:

| Set | 6 dealt | best 6 of 8 (3 + 5) | best 6 of 9 (3 + 6) | 3 pocket + exactly 3 of 5 |
| --- | ---: | ---: | ---: | ---: |
| Five of a kind | ~0 | 0.02% | 0.03% | 0.02% |
| 6-card flush | 0.01% | 0.07% | 0.22% | 0.03% |
| Two triples | 0.02% | 0.32% | 0.77% | 0.10% |
| Four of a kind | 0.20% | 0.87% | 1.59% | 0.81% |
| 6-card straight | 0.21% | 2.65% | 5.80% | 1.45% |
| Three pairs | 0.48% | **10.10%** | **22.31%** | 4.02% |
| Three of a kind | 6.09% | **12.97%** | **15.55%** | 14.03% |
| Two pairs | 16.31% | 34.99% | 33.97% | 38.18% |
| One pair | 49.66% | 31.95% | 17.76% | 34.47% |
| No set | 27.03% | 6.08% | 2.01% | 6.90% |

(Six of a kind and the straight flush did not come up in 40,000 of
any deal; they are a few in a hundred million dealt.)

- **Three pocket and five community, any six of the eight, keeps the
  ranking in order of rarity** from five of a kind down to three of a
  kind. Below that it inverts the way Texas Hold 'em's own table does
  -- two pairs come up more often than one pair, and no set is rarer
  than either -- which is harmless: a player cannot choose a weaker
  set than the cards make, and Hold 'em has lived with high card being
  rarer than a pair for as long as it has existed.
- **Six community cards breaks it**: three pairs come up half again as
  often as three of a kind, and still outrank it.
- **Exactly three pocket and three community** (Omaha's rule, which
  makes you use your pocket) also keeps the order, with less of the
  board shared. It is a fine variant and a worse default: every player
  must work out which three of the board are theirs, and the board
  alone can never be anybody's hand.

So decision 3 deals **three pocket cards and five community cards**,
on the streets Hold 'em has -- three on the flop, one on the turn, one
on the river -- which is also The Gang's four rounds unchanged.

### Tethys Hold 'em, in the terms the code will use

Texas Hold 'em, with the Tethys deck and Tethys poker's sets:

- **A table** of two to ten **seats**. The **button** moves one seat
  left each **hand**; the two seats after it post the **small blind**
  and the **big blind** (heads-up, the button posts the small blind and
  acts first before the flop, last after it, as Hold 'em plays it).
- **The deal**: three **pocket cards** each, face down, from a shuffled
  72 (`engine.rng`).
- **Four streets**: **pre-flop** (no board), **flop** (three community
  cards), **turn** (one more), **river** (one more), each a **betting
  round**. Before the flop the action starts left of the big blind;
  after it, left of the button.
- **Actions**: fold, check, call, bet, raise, all-in. **No limit**
  (decision 6): a bet or raise is at least the big blind or the last
  raise's size, at most the player's stack. A betting round ends when
  every player still in has matched the high bet or is all in, and
  everybody has acted since the last raise.
- **Pots**: an all-in for less than the bet splits the pot into a
  **main pot** and **side pots**, each contested by the players who
  put into it.
- **Showdown**: every player still in shows their pocket cards; each
  hand is the best six of their three and the five on the board; the
  highest wins each pot it is in; equal hands split it, the odd dinky
  to the first seat left of the button. A hand that wins because
  everybody else folded is never shown.
- **The game**: everybody starts with the same stack, the blinds rise
  on a schedule, and the last seat with chips wins (a sit-and-go;
  decision 6).

### Tethys Gang, in the terms the code will use

The Gang is cooperative Texas Hold 'em for 3 to 6 players (Gang p. 1).
Nobody bets; the players together try to rank their own hands, weakest
to strongest, without telling one another what they hold. In outline,
in this worksheet's words:

- **A game is a run of heists**; win three before three fail, so three
  to five heists a game (Gang p. 4). Each heist is a deal and four
  **rounds**, the four streets above: pre-flop, flop (three community
  cards), turn (one), river (one) (Gang p. 5-8).
- **Each round has its own set of chips**, numbered one star to as
  many stars as there are players, in the round's colour -- white,
  yellow, orange, red (Gang p. 3-4). A chip says where its holder
  thinks their hand stands at the table now: one star the weakest, the
  most stars the strongest.
- **Taking a chip has no turn order** (Gang p. 5): anyone may at any
  time take any of the round's chips, from the middle or from in front
  of another player; nobody holds two of one round's colour; a player
  may put theirs back in the middle; nobody ever gives a chip to
  another. Whoever loses a chip to a taker is left without one until
  they take another. The round ends when everybody holds one (Gang p. 6).
  Earlier rounds' chips stay in front of their holders, in a row, as
  the record of how each player's estimate moved.
- **Nobody says, shows or hints what they hold**, nor anything they
  know about another's hand only because of their own (Gang p. 2). The
  chips are the only signal.
- **The showdown** (Gang p. 8-9, 12): only the red chips count. Hands
  are shown from the one-star red chip up; each hand is the best five
  of seven; if every hand shown is at least as strong as the one
  before it, the heist succeeds, otherwise it fails. Players whose
  hands are exactly equal may hold their chips in either order.
- **Advanced mode** (Gang p. 14-19) adds two stacks of ten cards. The
  first heist is plain. After a success the next challenge card is
  active for the next heist (it is harder); after a failure the next
  specialist card is (it is easier; most let the players share a
  little information). **Professional mode** (Gang p. 15) also has one
  random challenge active all game; **Master Thief mode** removes the
  specialists and one alarm (two failures lose) and always has two
  challenges active, the older one replaced each heist.

**Tethys Gang** is that game on the Tethys deck: three pocket cards
and five community, a hand the best six of eight, compared by the same
evaluator as Tethys Hold 'em (decision 2). The table count matters: 72
cards deal three each and five to the board for up to 22 players, so
the deck sets no limit The Gang's chips do not already set.

**The challenge and specialist cards read ranks in four places**, and
each needs a Tethys reading. The proposal, which question 10 asks the
author to confirm, keyed in the code by what the card does rather than
by The Gang's name for it (decision 13):

| What it does (Gang p.) | The Gang's reading | The Tethys reading proposed |
| --- | --- | --- |
| No white chips; straight to the flop (16) | -- | unchanged |
| The 1-star chips of rounds 1-3 cannot change hands once taken (16) | -- | unchanged |
| The holder of the white 1-star chip redraws their pocket if the flop shows a face card (16) | J, Q or K on the flop | **a ruler on the flop** (about 43% of flops, against 55% for a face card in 52 cards) |
| The top chips of rounds 1-3 cannot change hands once taken (17) | -- | unchanged |
| The holder of the top white chip redraws their pocket on the flop's condition (17) | "if none" on p. 17's text, "if at least one" on the card itself (Laser Tripwires) -- the book disagrees with itself | **a ruler-free flop**, the explanation's reading (question 11) |
| No orange chips; straight to the river (16) | -- | unchanged |
| Each round's chips are discarded when the next round's are laid out (17) | -- | unchanged |
| Before the strongest hand is shown, the rest agree on a card value it holds in its pocket (16) | 2 to ace | **1 to 10, Left, Right** |
| Before the strongest hand is shown, the rest agree on its hand ranking (17) | high card to royal flush | **no set to six of a kind** |
| Everybody plays one more pocket card (17) | best five of eight | **four pocket, best six of nine** (the ranking inverts at three pairs here, as the table above shows -- part of what makes it a challenge) |
| One player shows one other player one pocket card (18) | -- | unchanged |
| One player tells everyone their hand's current ranking (18) | -- | unchanged, in Tethys sets |
| Everyone says how many face cards they hold (18) | J, Q, K | **how many rulers** |
| One player says how many of a value they hold (18) | 2 to ace | **1 to 10, Left, Right** |
| One player draws a pocket card and discards one (18) | -- | unchanged |
| Everyone passes one pocket card to the left (18) | -- | unchanged |
| A suitless jack joins one player's pocket in place of a card (19) | a jack of no suit | question 12 |
| Everyone says the sum of their pocket cards (19) | J, Q, K 10, A 11 | **the cards' worth**, `deck.worth` -- a ruler 12 |
| The dealt pockets are gathered, shuffled and dealt again (19) | -- | unchanged |
| One player's hand beats every other hand of its ranking (19) | -- | unchanged |

The deck has one thing poker's does not, **fate**, and The Gang's
information cards are a natural home for it: a specialist "everyone
says how many of their pocket cards are Fortune" is the Investor's
shape over the Tethys deck's own split. Question 10 asks whether to add
it, and whether fate does anything else in either game.

### The cards as pictures, and what the commands show today

`tethysdeck/cards.card(icon_set, suit, rank)` draws one face at
750 x 1050; `back.py` draws the back. **All 72 faces render in about
1.7 seconds** on the Mac, and resizing them to 150 x 210 takes another
0.3 (measured 2026-10-11), so a process can draw the whole deck once
as it starts, off the event loop, and never touch the disk or Pillow's
compositing again per click -- the Codex bot's `preload_pictures`
shape (codex.md), at a fraction of its cost.

The `/tethyscards` commands (`cogs/tethysdeck.py`, its helpers and
views) deal **strings** -- `"7 of ⚔ Might"`, built by
`tethysdeck_helpers.build_deck` -- into a per-channel deck, hands and
discard saved in `data/tethysdeck_decks.json`, and show a hand as a
comma-separated list. Nothing in them draws a card. Those strings are
the save format: a channel's deck in progress outlives the commit, so
the first step reads them into `(suit, rank)` through one parser
rather than changing what is saved.

### What the repository already gives

- **The model's shapes**, twice over: D12 Ball's and Codex's
  `components` with `SavedField` tables, a game record with the lobby's
  rules refusing with `RuleRefusal`, `RulesEngine` with the one `rng`,
  `pending` as the one reading of what a match waits on, a `flow/`
  whose steps return what happened, and a driver that is the one door.
  `gamekit/` holds what both share (`jsonable`, `MOVED_ON`/`STEP_OWED`,
  `Resolver`, `StopHandling`, `SavedField`, the games file's guarded
  read and write); `botkit/` the channel helpers and `GameLockedView`.
- **The hidden-information pattern**, which D12 Ball never needed and
  Codex built: a public message with the position and a **My hand**
  button that answers by who clicked, ephemerally; nothing hidden in a
  public message, a log line or the #logs mirror ([codex-bot.md](codex-bot.md),
  "Hidden information").
- **The turn message posted again at the foot of the channel after
  each action**, the old one deleted, so the next player is mentioned
  by a post that pings and the panel sits under the board
  ([design/codex.md](design/codex.md), "The turn message, posted
  again"), and its cost: a post and a delete per action in the
  channel's bucket.
- **`interaction.response.edit_message` is not the channel's bucket**
  ([design/rate-limits.md](design/rate-limits.md)): an edit made as a
  click's own answer is free of the five-in-five limit every other edit
  in a channel shares.
- **Who may act**: `cogs/game_auth.py`, a player first and a
  `manage_channels` helper second, behind a confirmation.
- **The studio's coins** as emoji (`cogs/coins.py`,
  `d12ball/images/emoji/coin_*`), worth their dinkies by the Coins tab
  (1B = 1, 3B = 3, 1S = 6, 1G = 12, 3S = 18, 3G = 36) -- the Money
  suit's own denominations, and a ready-made look for a stack of chips.

## The decisions

The recommendation and its reason; the author overrules any of them by
saying so on the PR, and the step's prompt is rewritten rather than
argued with.

1. **Both games live in fool-bot**, beside `/tethyscards`, rather than
   in a bot of their own. The Codex bot is its own process because it
   is its own application with its own name in the member list; these
   are the studio's own deck's games and the deck's commands are
   already here. Question 1 asks.

2. **One evaluator, in `tethysdeck/`**, for both games and the aid:
   `tethysdeck/hands.py` -- `hand_value(six) -> HandValue`, a value that
   sorts (the set's place in `SETS`, then the set's own tie-break), and
   `best_six(cards) -> (HandValue, six cards)`, the best of any number
   of cards from six up. It asks `sets.set_of` for the set and adds
   only the order within it, so there is still one reading of what a
   set is. No Pillow, no `discord`; the purity ratchet grows to cover
   it.

3. **Three pocket cards and five community, any six of the eight**,
   dealt on Hold 'em's four streets, in both games -- see "Six of
   eight". Burn cards are dealt as Hold 'em deals them (one before
   each street) since the deck has room and players expect it.

4. **The order within a set**: a hand's matched groups are compared
   largest group first, then highest, then the unmatched cards high to
   low -- poker's kicker rule. Heights: the numbers 1 to 10, then **a
   Doom ruler, then a Fortune ruler** -- "left and right alternate.
   whoever is fortune is higher than whoever is doom" (the author,
   2026-10-11): which of Left and Right is Fortune changes from suit to
   suit (`deck.LEFT_FATE`), and the Fortune one is the higher. **The
   Left-and-Right pair is the highest pair** (the author, 2026-10-11),
   above a pair of 10s. So two triples compare the higher triple, then
   the lower; three pairs the highest, then the middle, then the
   lowest; four of a kind its four, then its two others high to low (a
   pair among them is only two kickers); a flush its cards high to low.
   Two hands equal in all of that are equal, and split.
   - **Two readings that follow, built so until the author says
     otherwise.** A ruler pair can be two Fortune rulers, one of each,
     or two Doom (a Left and a Right of different suits can share a
     fate), so two ruler pairs compare their higher card, then their
     lower: Fortune and Fortune above Fortune and Doom above Doom and
     Doom. And a straight ending on a ruler ends on the ruler's height,
     so one ending on a Fortune ruler beats one ending on a Doom ruler.
     Neither changes which set a hand makes: in a straight both rulers
     still follow 10, so `sets.py` and its census stand.

5. **Fate decides the rulers' order and nothing else to start**
   (question 5): a uniform hand is the same set as a mixed one. It is
   the one thing the deck has that poker does not, so it is the first
   candidate for a rule once the games are played, and the evaluator
   carries `uniform` on its value so a rule can read it without
   another pass.

6. **Tethys Hold 'em is no-limit, played as a sit-and-go in dinkies**:
   every seat starts with the same stack, the blinds rise every so many
   hands, the last seat with chips wins. Chips are dinkies, shown as
   the studio's coins. The numbers are the author's to pick from the
   three structures in question 6 -- each the common sit-and-go shape
   (about 75 big blinds deep, each level a third to a half up on the
   last) with blinds the coins can pay -- built as **the Tethys
   standard** until they do.

7. **Each game has its own channel, as Codex's do** (`/tethys holdem
   create_game` and `/tethys gang create_game` open it; a thread where
   the bot may not; the channel the command was typed in where neither
   -- Codex's `venue`). The game's record is the bot's, saved through
   its service once per action like every other game here.

8. **The public message is the table, posted again after each
   action** in Hold 'em -- the board as a picture (the five community
   cards, backs for those not yet dealt), every seat's stack, bet and
   state as text, the pot, and the next player mentioned -- with **My
   cards** under it: their three pocket cards ephemerally, and for the
   player to act the action panel under the cards. A post pings; an
   edit does not; a player must know it is their turn. The cost is the
   Codex turn message's: a post and a delete per action.

9. **Tethys Gang's round message is edited by the clicks themselves**:
   chips change hands fast and simultaneously, nobody waits on a ping,
   and every chip click answers with `interaction.response.edit_message`,
   which is not the channel's bucket. The board picture changes only
   when a street is dealt, and that is a new message, which pings
   everybody. **The round ends when everybody holds a chip and has
   pressed Ready** (the author, 2026-10-11: "gang round must wait for
   ready"), Ready cleared for everyone whenever a chip changes hands --
   online, "as soon as everyone has a chip" (Gang p. 6) would end a
   round the instant the last chip was taken, before anybody could
   take it back.

10. **Hidden is hidden**: a pocket card is never in a public message, a
    log line, the #logs mirror or a refusal's text. A folded Hold 'em
    hand is never shown. A Gang hand is shown at the showdown, every
    one, since that is the game.

11. **Nobody is forced to act by a clock to start** (question 8). A
    Hold 'em seat waited on is mentioned again by **Nudge** on the
    table, at most once a few minutes; a helper may fold or sit out a
    seat behind the confirmation `game_auth` already has. A player may
    sit out between hands and come back; their blinds are posted or
    their seat skipped as question 8 settles.

12. **The model is a package of its own, `tethyspoker/`**, the Codex
    shapes copied: `table.py` for what both games share (seats, the
    deal, the streets, the board), `holdem/` and `gang/` each with
    `components`, `game`, `engine`, `prompts`, `flow/`, `driver`;
    `gamesaves/tethyspoker/` the two services and the one games file,
    `data/tethys_poker_games.json`; `cogs/tethyspoker/` and
    `cogs/tethyspoker_views/` the frontend. The pictures -- a row of
    cards, the board with backs, a showdown -- are
    `tethysdeck/strips.py`, beside the faces they draw, never in the
    model.

13. **The Gang's words are kept** (the author, 2026-10-11: "keep gang
    words"): heist, vault, alarm, the four chip colours, challenge,
    specialist, and each card's name. A card is still keyed in the code
    by what it does (`no_first_chips`, `fixed_lowest_chips`,
    `ruler_flop_redraw`, ...), its name read from one table, so a later
    renaming is a table edit.

14. **The `/tethyscards` commands show pictures first**, before either
    game, since it is the author's first ask and the games' pictures
    are made of the same strip: a hand, a draw and the discard as a row
    of the deck's own faces, the saved strings read through one parser
    (`tethysdeck_helpers.parse_card`) and the save format unchanged.

## Questions for the author

Each step's PR carries a `## Questions to the author` section; these are
the ones known before any step starts. A step whose prompt needs an
answer says what it builds until it has one. Those struck were answered
on 2026-10-11.

1. **Do the two games live in fool-bot, or a bot of their own?** Built
   as fool-bot (decision 1).
2. **What are the commands called?** Built as one `/tethys` group with
   `holdem` and `gang` subgroups, `/tethyscards` left as it is.
3. ~~**Where does a ruler stand as a kicker, and is Right above
   Left?**~~ Answered: Left and Right alternate, and whichever is
   Fortune is higher than whichever is Doom. Decision 4, with the two
   readings that follow from it, which the author may still overrule.
4. ~~**Is the Left-and-Right pair the highest pair?**~~ Answered: yes.
5. **Does fate do anything beyond ordering the rulers?** For example:
   a uniform hand beats a mixed hand of the same set and heights, or
   a uniform hand wins a bonus from every other seat, or nothing.
   Built as nothing (decision 5).
6. **Hold 'em's numbers.** The common sit-and-go -- the shape the
   online rooms made standard -- starts every seat at 1,500 with
   blinds of 10 and 20, about 75 big blinds deep, and raises each
   level a third to a half on the last ([PokerNews on sit-and-go
   structures](https://www.pokernews.com/strategy/10-tips-for-sit-go-success-assessing-structures-speeds-27573.htm);
   home-game ladders run 10/20, 15/30, 25/50, 50/100 and on). Its
   levels are minutes; on Discord a hand takes minutes of its own, so
   a level here is a number of hands. Three structures on offer:

   | | Stack | Deep | Blinds, level by level | A level |
   | --- | --- | --- | --- | --- |
   | **Tethys standard** (built) | 432 dinkies, twelve 3G | 72 BB | 3/6, 6/12, 9/18, 12/24, 18/36, 24/48, 36/72, 54/108, 72/144, 108/216, 144/288 | 10 hands |
   | **Tethys turbo** | 216 dinkies, six 3G | 36 BB | the same ladder | 6 hands |
   | **The room's numbers** | 1,500 | 75 BB | 10/20, 15/30, 25/50, 50/100, 75/150, 100/200, 150/300, 200/400, 300/600, 400/800 | 10 hands |

   The Tethys ladder is the common shape with the coins' own values:
   every big blind is a coin or a few of one kind (6 a silver, 12 a
   gold, 18 three silver, 36 three gold, 72 two 3G), the first step
   doubles as 5/10 to 10/20 does, and each after it is a third or a
   half up. Also open: the seats (built as 2 to 9, the full ring), and
   whether a turbo or the room's numbers should be a setting at the
   lobby beside the standard.
7. ~~**Does a Gang round end the moment everybody holds a chip, or
   once everybody has also pressed Ready?**~~ Answered: it waits for
   Ready. Decision 9.
8. **What happens to a player who does not act?** Built as no clock, a
   **Nudge**, and a helper who may fold or sit out the seat. And does a
   seat sitting out still post its blinds?
9. ~~**The Gang's names**~~ Answered: keep The Gang's words. Decision
   13.
10. **The challenge and specialist translations** in the table above:
    rulers for face cards, 1 to 10, Left and Right for card values,
    Tethys sets for hand rankings, worth for the sum, a fourth pocket
    card. And should there be a Fortune-count specialist?
11. **Laser Tripwires** (challenge 7): the rulebook's explanation on
    p. 17 has the holder of the top white chip redraw "if none" of the
    flop is a J, Q or K; the card printed beside it says "if at least
    one". The explanation makes it Motion Detector's mirror -- Motion
    Detector (challenge 3) redraws the 1-star holder's pocket when the
    flop *has* a face card, Tripwires the top holder's when it has
    none -- and the card's wording reads like Motion Detector's copied.
    Built as the explanation's "none", over rulers: the top white chip
    redraws when the flop shows no ruler.
12. **The suitless jack** (specialist 7, "Jack"): in Tethys Gang, a
    suitless card that counts as what? A ruler that pairs with either
    Left or Right, chosen at the showdown, is one reading; a suitless
    10 another. And if a ruler, Fortune or Doom?
13. **How many players does Tethys Gang take?** Built as 3 to 8 (The
    Gang plays 3 to 6, and 10 with its expansion; more players is
    harder).
14. **Should either game have an AI seat?** The Gang needs three people
    at once, which a Discord server may not have at the same time.
    Built as no AI to start; the step list keeps a place for it.

## The steps

In the order they pay off. Each is one branch off an up-to-date `main`,
one PR, the suite green, and nothing under `d12ball/`,
`gamesaves/d12ball/`, `cogs/d12ball*`, `codex/` or `cogs/codex*`
changed. Every step ends on a **stop**: the thing the author looks at
before the next step is worth starting.

| # | Step | Size | Stop |
| --- | --- | --- | --- |
| 1 | The `/tethyscards` commands show the cards as pictures | small | a draw, a hand and the discard in a server, each a row of the deck's own faces; an old channel's deck still loads |
| 2 | The evaluator: the order within a set, the best six of eight | small | the tie-break table in the PR, as pictures of pairs of hands and which wins; the best-of-eight chances by a large sample, beside the dealt-six census |
| 3 | Tethys Hold 'em through the driver, with no frontend | large | a seeded test plays a sit-and-go from the first deal to one seat holding every dinky, through side pots and a split pot; the Hold 'em golden |
| 4 | Tethys Hold 'em on Discord | large | three people play to a winner: the lobby, the channel, the table posted again, My cards, the panel, the showdown's picture, Nudge |
| 5 | Tethys Gang through the driver, with no frontend | medium | a seeded test plays three heists won and a game lost; simultaneous chip moves, Ready, the showdown's order with a true tie |
| 6 | Tethys Gang on Discord | medium | three people finish a game: the round message edited by clicks, the streets posted, the showdown revealed in red-chip order, the vaults and alarms |
| 7 | Tethys Gang's advanced, professional and master thief modes | medium | every challenge and specialist played once in a test; the group agreements (who uses a specialist, the guesses) on Discord |
| 8 | The look back, and the design note | small | nothing copied in two places; docs/design/tethys-games.md says what each step settled |
| -- | Later, and not now | -- | an AI seat in either game; the games on the web app; a printed chip and vault set for the table |

### Claiming a step

The series does not exist yet: **step 1's prompt adds it** -- one entry
in `SERIES` in `scripts/claim_web_step.py`
(`"tethys": ("docs/tethys-games.md", "tethys-step", "Tethys step")`),
plus the `--series` help string and the module docstring, which list
the series by hand. From then on `python3 scripts/claim_web_step.py
--series tethys <n>` claims a step as the other series are claimed. A
step lands by striking its row above (`| ~~n~~ | ~~title~~ -- landed;
what it settled is in docs/design/tethys-games.md | ... |`). No cloud
routine runs this series unless the author sets one up. Every PR
carries `## Questions to the author` (`None.` when empty) and `## For
the author` -- what to do on the live host after merging, and what to
try in the server, command by command.

## Preamble

Every step's prompt begins with this block.

```text
You are working in the fool-bot repository on the two Tethys deck games
planned in docs/tethys-games.md: Tethys Hold 'em (Texas Hold 'em with
three pocket cards and Tethys poker's six-card sets) and Tethys Gang
(the cooperative poker game The Gang, on the same deal). Read that
worksheet first -- "What was found", "The decisions" and the questions
the author has answered -- then docs/design/tethys-deck.md (the deck,
the fate rule, Tethys poker's sets), then docs/design/codex.md's
sections on hidden information, the turn message posted again and the
requests per click, and docs/design/model-discord-split.md and
docs/design/game-service.md (the shape you are copying). Read the rest
of docs/design/ only where a step names a file.

Start on a fresh branch off an up-to-date main (the claim script has
made it: git fetch && git checkout tethys-step-<n>), in a worktree of
your own if another session may be using the checkout. Never work on
main.

Hard rules for every step:
- tethyspoker/, gamesaves/tethyspoker/ and tethysdeck/hands.py import
  no discord, define no async def and import no Pillow. Pictures are
  tethysdeck/strips.py's. Add the packages to the purity ratchet the
  step they first appear in; never loosen it.
- A rule is a question the model answers and the cog asks. Nothing in
  cogs/tethyspoker* decides a rule, computes a legal bet, a pot, a
  winner or whose turn it is; a view builds its controls from
  PendingPrompt.options and nothing else, and the driver refuses what
  the options do not offer, with RuleRefusal, never a bare ValueError.
- One reading each: tethysdeck.sets.set_of is what set six cards make,
  tethysdeck.hands.best_six is a player's hand, the engine's rng is
  every shuffle. Nothing else ranks a hand.
- Nothing hidden -- a pocket card, the deck's order, a folded hand --
  is written into a public message, a log line, the #logs mirror or a
  refusal. Say in the PR where you checked.
- The save format is the contract: every field in its SavedField table
  with its fallback, nothing renamed once it has been on main. The
  /tethyscards strings in data/tethysdeck_decks.json stay as they are.
- Rate limits: the fix is always fewer requests, never slower ones.
  Count what a click spends, with a faked Discord that logs every
  request by route, as tests/codex_cog_fakes.py does; say the count in
  the PR. Every render goes through asyncio.to_thread; the faces are
  drawn once as the cog loads.
- Look at every picture you change and put it in the PR; nothing drawn
  is tested for how it looks.
- Run python3 -m unittest discover -s tests before the PR; a full run
  must not create data/. Strike the step's row in docs/tethys-games.md,
  write what it settled into docs/design/tethys-games.md with the
  reasoning, and add a row to CLAUDE.md's map for a new module.
```

### 1. The `/tethyscards` commands show the cards as pictures

```text
Step 1 of docs/tethys-games.md. Decision 14.

Add the series to scripts/claim_web_step.py ("Claiming a step").

Make tethysdeck/strips.py: the deck's faces drawn once
(tethysdeck.cards.deck_cards over one IconSet) and kept at a small
size -- 150 x 210 is a start; look at it on a phone -- and a row of
cards as one PNG, wrapping to a second row past twelve, with a back
(tethysdeck.back) for a card face down. Nothing in it reads Discord.

In the cog, read the saved strings through one parser,
tethysdeck_helpers.parse_card("7 of ⚔ Might") -> ("might", "7"),
tested over every string build_deck makes; the save format does not
change. Draw the faces once in cog_load through asyncio.to_thread.
Then: a draw shows the cards drawn as a picture, a hand (yours or
another's) as a picture, the discard as a picture, each with the text
it has today as the message's words. The deck status message stays
text. A hand's picture is the ephemeral reply it already is.

Stop: send the author a draw, a hand of eight and a discard of thirty
from a server, and confirm a data/tethysdeck_decks.json from before
the change loads.
```

### 2. The evaluator: the order within a set, the best six of eight

```text
Step 2 of docs/tethys-games.md. Decisions 2, 3, 4 and 5, and
question 5 -- build what the decisions say for any the author has
not answered, and say so in the PR. Decision 4's rulers are the
author's: the Fortune ruler of a Left and Right is the higher, and
the Left-and-Right pair is the highest pair.

Write tethysdeck/hands.py: HandValue (sorts; the set's place in
sets.SETS first, then the set's own tie-break, and uniform carried
beside it, read by nothing yet), hand_value(six), and best_six(cards)
for six or more cards. hand_value asks sets.set_of for the set; it
adds only the order within it. Test it against set_of over a large
seeded sample, test every set's tie-break with hands named by
(suit, rank), and test true ties.

Extend sets_aid.py or add beside it: the chances of each set as a
player's best six of eight (three pocket, five community), by a
seeded sample large enough that the rarest sets the aid shows have a
few hundred hands each, or exactly if a count can be found; draw it as
a column beside the dealt-six chances in the chart. Put
docs/tethys-games.md's 40,000-hand table right if the larger count
moves it.

Stop: the PR shows, as pictures of the cards, a pair of hands for
every tie-break rule and which wins; and the chart with both columns.
The author confirms the order within each set before step 3 builds on
it.
```

### 3. Tethys Hold 'em through the driver, with no frontend

```text
Step 3 of docs/tethys-games.md. Read "Tethys Hold 'em, in the terms
the code will use", decisions 3, 6, 10 and 12, and question 6.

Create tethyspoker/ (table.py, holdem/ with components, game, engine,
prompts, flow/, driver) and gamesaves/tethyspoker/ (the Hold 'em
GameService, storage in data/tethys_poker_games.json through gamekit's
guarded read and write). The game record holds the lobby's rules
(join, leave, the settings, start), refusing with RuleRefusal. The
match holds the seats, stacks, button, blinds and their schedule, the
deck (shuffled by engine.rng), each seat's pocket, the board, the
street, each seat's bet this street and whether it has folded, is all
in or sits out, the pots, and the hand's journal of actions.

pending is the one reading of what the match waits on: the seat to
act and its options (fold, check or call and the amount, the smallest
and largest bet or raise, all in), or a step the bot owes (deal the
next street, the showdown, the next hand). Side pots: every all-in for
less splits the pot, each pot is won by the best hand among those in
it, a tie splits it with the odd dinky to the first seat left of the
button. Heads-up plays as Hold 'em plays heads-up.

Tests: every legal action and every refusal (a bet below the minimum,
acting out of turn, checking facing a bet); a seeded sit-and-go of
four seats from the first deal to one seat holding every dinky, with
nothing from cogs/ or discord imported; a three-way all-in with two
side pots; a split pot; and a golden of that game's narration, tokens
intact, re-recorded only for a change to the wording or the game.

Stop: the PR shows one hand of the golden's narration in full.
```

### 4. Tethys Hold 'em on Discord

```text
Step 4 of docs/tethys-games.md. Decisions 1, 7, 8, 10 and 11, and
questions 1, 2 and 8.

The cog: cogs/tethyspoker/ (mixins as cogs/codex/ is: core, lobby,
turns, presentation, slash_commands) and cogs/tethyspoker_views/
(base with SafeView over botkit's GameLockedView and game_auth's
gates). Load it in foolbot.py's EXTENSIONS.

/tethys holdem create_game opens the game's channel and posts the
lobby (Join, Leave, the settings, Start). From Start: the table
message -- the board as a picture from tethysdeck/strips.py (five
places, backs where nothing is dealt), each seat's stack, bet and state
as text with the coins as emoji, the pot, the street, and the seat to
act mentioned -- posted again at the foot of the channel after each
action and the old one deleted, as the Codex turn message is. Under
it: My cards (the clicker's three pocket cards ephemerally; for the
seat to act the panel under them -- Fold, Check or Call, a menu of
raises from the options (the minimum, half the pot, the pot, all in)
and Other..., a modal for an amount), Nudge, and Leave after this hand.
The showdown is one message: each hand shown, its best six marked and
its set named, and who won which pot. A hand won by folds says so and
shows nothing.

Count the requests an action spends with a faked Discord and put the
number in the PR. Nothing hidden reaches a public message or a log
line: test that a pocket card's name never appears in anything the
fake recorded as public.

Stop: three people play to a winner in a server; the PR has pictures
of the table on the pre-flop, the river and a showdown, at a phone's
width as well as a desktop's.
```

### 5. Tethys Gang through the driver, with no frontend

```text
Step 5 of docs/tethys-games.md. Read "Tethys Gang, in the terms the
code will use" and decision 9, and question 13. The Gang's
rules are summarised in the worksheet; do not commit its rulebook.

tethyspoker/gang/ with components, game, engine, prompts, flow/,
driver, sharing table.py's deal and streets with Hold 'em, and its
GameService in gamesaves/tethyspoker/ over the same games file. A game
is heists until three vaults or three alarms; a heist is the deal and
four rounds. Chip moves are simultaneous: pending answers every player
at once (take any of the round's chips, from the middle or from a
holder; put yours back; Ready), and the round ends when everybody holds
one and everybody is Ready, Ready cleared for everyone when a chip
changes hands. The showdown reveals hands from the lowest red chip
up, compares each hand with tethysdeck.hands.best_six, and lets equal
hands stand in either order.

Tests: the chip rules (no two of a colour, never given, taking from a
holder leaves them without, Ready cleared); a seeded game of three
players won, and one lost; a true tie in either order; a golden.

Stop: the PR shows one heist's narration in full.
```

### 6. Tethys Gang on Discord

```text
Step 6 of docs/tethys-games.md. Decisions 7, 9, 10 and 13.

/tethys gang create_game opens the channel and the lobby. Each street
is a new message (the board as a picture, everybody mentioned); under
it the round's chips as buttons, each labelled with its stars and its
holder, Put back and Ready, and the earlier rounds' chips per player as
text. A chip click answers with interaction.response.edit_message --
the click's own route, not the channel's bucket -- and nothing else.
My cards shows the clicker's pocket ephemerally. The showdown is one
message: the hands shown in red-chip order, each with its best six
marked and its set named, and the verdict: a vault, or an alarm and
where the order broke. The game's tally of vaults and alarms is on
every street's message.

Count what a chip click spends with a faked Discord, and test that six
players clicking in one second spend nothing in the channel's bucket.

Stop: three people finish a game in a server; pictures of a street's
message and a showdown in the PR.
```

### 7. Tethys Gang's advanced, professional and master thief modes

```text
Step 7 of docs/tethys-games.md. The table in "Tethys Gang, in the
terms the code will use", decision 13, and questions 10, 11 and 12.

Every challenge and specialist as data keyed by what it does, with its
display name from one table. The mode is a setting on the record:
basic, advanced, professional, master thief, played as Gang p. 14-15
has them. The specialists that need the group to agree -- which player
uses one, whom they show a card to, the guesses before the strongest
hand is shown -- are a proposal any player makes and every other
player confirms, as a prompt asked of everybody; the one asked about
is not asked. What a specialist reveals goes to whom it says: a shown
card to one player ephemerally, a count or a set to everybody.

Tests: every card played once in a seeded heist; professional's
standing challenge; master thief's two challenges and two alarms.

Stop: the author plays an advanced game in a server.
```

### 8. The look back, and the design note

```text
Step 8 of docs/tethys-games.md. Read what steps 1 to 7 built. Move to
one home anything they copied -- between the two games, and between
them and gamekit/ or botkit/ (a lobby, a seat list, the
posted-again table message). Write docs/design/tethys-games.md whole
from the worksheet's struck rows: what each game is, why each decision
went the way it did, with the author's dated answers. Add CLAUDE.md's
rows: the map for the new packages, and the "Read this before
touching" row for the design note.

Stop: the PR's diff shows nothing behaving differently; the goldens
unchanged.
```

## What is not in these prompts, on purpose

- **An AI seat.** A Hold 'em AI worth playing reads pot odds and
  ranges; a Gang AI must read the chips as people do. Each is its own
  piece of work once the games are played and the author wants one
  (question 14).
- **The web app.** The model is built to the split's rules so a second
  frontend could play it, as `webapp/` plays D12 Ball, but nobody has
  asked for it.
- **Fate as a rule.** Question 5. The evaluator carries it so the rule
  is a few lines when it comes.
- **Printed chips, vaults and alarms** for the table, as the D12 Ball
  kit prints its tokens. The deck already prints.
- **Real money, or anything that looks like it.** Dinkies are the
  game's and go nowhere outside it.

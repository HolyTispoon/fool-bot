"""
D12 Ball 2.1's maneuver deck: each coach's twenty-four cards, the hand
of five drawn from them, and the discard pile -- as data and the few
moves made on them. See docs/design/maneuver-deck.md and
docs/rules-2.1.md.

**The cards.** Twenty-four single-faced cards, four for each basic
maneuver -- P1 to P4 Pass, B1 to B4 Dribble, H1 to H4 High Ball on
offense, F1 to F4 Deflect, S1 to S4 Steal, R1 to R4 Pressure on defense
(the `maneuvers 2.1` tab, 2026-10-31). Every card plays its rank's
basic maneuver; what tells the four apart is a **special**, a role
interaction its player plays when they hold one of the roles it names
(`RulesEngine.card_special`). There are no advanced maneuvers.

**A card is named by its index**, the sheet's `Index` ("P3"), never by
its name: two names are 1.0 cards' names. `plays_as` is what a card
plays on a side -- its own maneuver on its own side, and **flipped**,
on the other side, the maneuver of the same rank there, which costs an
extra card from the hand and plays no special (rules-2.1 2.3).

**A deck is a plain dict of three lists** -- `draw`, `hand`, `discard`
-- because it is saved as it stands (`MatchState.maneuver_decks`). The
draw pile is face down and in order: its first entry is the next card
drawn. Nothing here decides who may play what; `RulesEngine.card_plays`
asks `plays_as` over the hand.

No Discord, no Pillow and no `async` (the model's purity rules), and
every shuffle is the engine's `rng`, handed in.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Optional

from d12ball.components import (
    MANEUVER_TIER_BASIC,
    DeckCard,
    ManeuverCatalog,
)

#: The cards a coach holds at a time.
HAND_SIZE = 5

#: The three piles a deck is saved as.
DRAW = "draw"
HAND = "hand"
DISCARD = "discard"

@dataclass(frozen=True)
class CardPlay:
    """
    One way a 2.1 coach may play a card from their hand this maneuver
    (`RulesEngine.card_plays`): the card, the maneuver it plays on the
    side, whether that is a flip, the cards a flip may discard with it,
    and whether its special is live -- the player making the maneuver
    holds a role it names. A pick answers with `card_id` and, for a
    flip, one of `extra_ids`.
    """

    card_id: str
    maneuver_key: str
    flip: bool = False
    extra_ids: tuple[str, ...] = ()
    special: bool = False

    def to_dict(self) -> dict:
        return {
            "card_id": self.card_id,
            "maneuver_key": self.maneuver_key,
            "flip": self.flip,
            "extra_ids": list(self.extra_ids),
            "special": self.special,
        }


#: The other side, for a flipped card.
OTHER_SIDE = {"offense": "defense", "defense": "offense"}


def deck_cards(catalog: ManeuverCatalog) -> list[str]:
    """
    The twenty-four cards of one coach's deck, unshuffled, by index:
    offense then defense, each rank's cards 1 to 4. Read off the
    catalog, so the cards are the data's.
    """
    return [card.index for card in catalog.deck_cards]


def basic_on(
    catalog: ManeuverCatalog, side: str, rank: int,
) -> Optional[str]:
    """The key of the basic maneuver on `side`'s `rank`, or None."""
    for maneuver in catalog.for_tier(side, MANEUVER_TIER_BASIC):
        if maneuver.rank == rank:
            return maneuver.key
    return None


def plays_as(
    catalog: ManeuverCatalog, card_id: str, side: str,
) -> tuple[Optional[str], bool]:
    """
    The maneuver `card_id` plays on `side` ("offense" or "defense"),
    and whether that is a **flip** -- the card turned to play the other
    side's maneuver of its rank (rules-2.1 2.3). `(None, False)` for a
    card the catalog does not have.
    """
    card = catalog.deck_card(card_id)
    if card is None:
        return None, False
    if card.side == side:
        return card.maneuver, False
    return basic_on(catalog, side, card.rank), True


def card_of(catalog: ManeuverCatalog, card_id: str) -> Optional[DeckCard]:
    """The card behind an index, or None."""
    return catalog.deck_card(card_id)


def new_deck(catalog: ManeuverCatalog, rng: random.Random) -> dict:
    """A coach's deck shuffled, and their opening hand of five drawn."""
    draw = deck_cards(catalog)
    rng.shuffle(draw)
    deck = {DRAW: draw, HAND: [], DISCARD: []}
    draw_cards(deck, rng, HAND_SIZE)
    return deck


def draw_cards(deck: dict, rng: random.Random, count: int) -> int:
    """
    Draw `count` cards into the hand, and say how many times the
    discard pile was shuffled into a new deck along the way.

    **The discard becomes the new deck the moment the last card is
    drawn**, not when a draw finds the pile empty (the author,
    2026-10-16): "when you draw the last card of your deck, you
    shuffle your discard to make a new deck". So a deck is never left
    empty between turns while there is a discard to shuffle.
    """
    reshuffles = 0
    for _ in range(count):
        if not deck[DRAW]:
            # Every card is in the hand: nothing left to draw.
            break
        deck[HAND].append(deck[DRAW].pop(0))
        if not deck[DRAW] and deck[DISCARD]:
            deck[DRAW] = list(deck[DISCARD])
            deck[DISCARD] = []
            rng.shuffle(deck[DRAW])
            reshuffles += 1
    return reshuffles


def play_cards(deck: dict, card_ids: list[str], rng: random.Random) -> int:
    """
    `card_ids` played out of the hand onto the discard pile -- the card,
    and the extra card a flip discards with it -- and the hand drawn
    back up to five. Returns how many times the discard was shuffled
    into a new deck by that draw.
    """
    for card_id in card_ids:
        deck[HAND].remove(card_id)
        deck[DISCARD].append(card_id)
    return draw_cards(deck, rng, HAND_SIZE - len(deck[HAND]))


def reshuffled(deck: dict, rng: random.Random) -> dict:
    """
    Every card a coach has -- hand, deck and discard -- shuffled into a
    new deck, and a fresh hand of five drawn from it: what halftime
    does (the author, 2026-10-16).
    """
    cards = deck[DRAW] + deck[HAND] + deck[DISCARD]
    rng.shuffle(cards)
    fresh = {DRAW: cards, HAND: [], DISCARD: []}
    draw_cards(fresh, rng, HAND_SIZE)
    return fresh


def pile_counts(deck: dict) -> tuple[int, int]:
    """How many cards are face down in the deck and in the discard --
    public, where the hand is its coach's alone."""
    return len(deck[DRAW]), len(deck[DISCARD])


# -- The cards whose specials the rules read, by index ----------------
#
# A rule site asks `RulesEngine.card_special(match, side) == PINPOINT`,
# as it asks a maneuver by its key. The indexes are the sheet's, and
# `tests/test_maneuver_deck_cards.py` holds each to a card in the data.

#: P1 Pass: a Winger's completed Pass may set up scoring.
WINGER_PASS = "P1"
#: P2 Pass and Run: a Midfielder or Striker may run forward 1.
PASS_AND_RUN = "P2"
#: P3 Pinpoint: a Playmaker may pick a teammate up to 2 spaces away.
PINPOINT = "P3"
#: P4 Reset: a Fullback or Defender may pass to the Playmaker.
RESET = "P4"
#: B1 Dribble: a Striker may attempt scoring.
DRIBBLE_SHOT = "B1"
#: B2 Advance: a Midfielder or Playmaker may advance 1 more space.
ADVANCE = "B2"
#: B3 Spin: a Fullback or Defender may change the speed by up to
#: their defensive skill.
SPIN = "B3"
#: B4 Drive: a Winger's teammate sharing the space may take the ball.
DRIVE = "B4"
#: H1 High Ball: a Fullback or Defender may throw it 4.
LONG_HIGH_BALL = "H1"
#: H2 Long shot: a Playmaker may throw it to the Striker instead.
LONG_SHOT = "H2"
#: H3 Set up: a Midfielder may throw it 2 with no contest instead.
SET_UP = "H3"
#: H4 Vertical Ball: a Winger or Striker may throw it 0 or 1 instead.
VERTICAL_BALL = "H4"
#: F1 Deflect: a Fullback's goes a space further.
FULLBACK_DEFLECT = "F1"
#: F2 Follow: a Defender or Midfielder may follow the ball.
FOLLOW = "F2"
#: F3 Boot: a Winger or Striker may set up scoring.
BOOT = "F3"
#: F4 Block: a Playmaker contests the ball on the spot.
BLOCK = "F4"
#: S1 Steal: a Playmaker may change the speed by up to their
#: offensive skill.
STEAL_SPEED = "S1"
#: S2 Pickpocket: a Midfielder does not move back with the ball.
PICKPOCKET = "S2"
#: S3 My Turf!: a Fullback or Defender adds 3 to the skill test.
MY_TURF = "S3"
#: S4 Toss: a Winger or Striker plays the ball to the nearest teammate
#: behind, staying in place.
TOSS = "S4"
#: R1 Pressure: a Defender's is a turnover, and nobody moves.
PRESSURE_STEAL = "R1"
#: R2 Control: a Fullback or Playmaker sends the ball to the handler's
#: nearest teammate behind, and follows it.
CONTROL = "R2"
#: R3 Stay Close: a Midfielder's handler exhausts 1.
STAY_CLOSE = "R3"
#: R4 Stress: a Striker or Winger contests the ball where it is.
STRESS = "R4"

SPECIAL_INDEXES = (
    WINGER_PASS, PASS_AND_RUN, PINPOINT, RESET,
    DRIBBLE_SHOT, ADVANCE, SPIN, DRIVE,
    LONG_HIGH_BALL, LONG_SHOT, SET_UP, VERTICAL_BALL,
    FULLBACK_DEFLECT, FOLLOW, BOOT, BLOCK,
    STEAL_SPEED, PICKPOCKET, MY_TURF, TOSS,
    PRESSURE_STEAL, CONTROL, STAY_CLOSE, STRESS,
)


# -- What the 2.1 cards say, as numbers -------------------------------
#
# Each is a number printed on the `maneuvers 2.1` tab, held here beside
# the deck so the engine's readings and the effects read one value.

#: Pass adds 1 to ball speed and Dribble 2 (the rank's Effect).
PASS_SPEED_BONUS = 1
DRIBBLE_SPEED_BONUS = 2
#: P3: a teammate up to 2 spaces away, either way.
PINPOINT_REACH = 2
#: The basic High Ball's one distance, and the specials' others.
HIGH_BALL_DISTANCE = 3
LONG_HIGH_BALL_DISTANCE = 4
SET_UP_DISTANCE = 2
VERTICAL_BALL_DISTANCES = (0, 1)
#: R3: the handler exhausts 1.
STAY_CLOSE_EXHAUSTION = 1
#: S3: added to the skill test.
MY_TURF_BONUS = 3

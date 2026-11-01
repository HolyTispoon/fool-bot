"""
D12 Ball 2.2's maneuver deck: each coach's twelve split cards, the
hand of three drawn from them, and the discard pile -- as data and the
few moves made on them. See docs/design/maneuver-deck.md and
docs/rules-2.2.md.

**The halves.** Twenty-four halves, four for each basic maneuver --
P1 to P4 Pass, B1 to B4 Dribble, H1 to H4 High Ball on offense, F1 to
F4 Deflect, S1 to S4 Steal, R1 to R4 Pressure on defense (the
`maneuvers 2.1` tab, 2026-10-31), each a `DeckCard` of the catalog's.
They were 2.1's twenty-four single-faced cards (archive/rules-2.1/).
Every half plays its rank's basic maneuver; what tells the four apart
is a **special**, a role interaction its player plays when they hold
one of the roles it names (`RulesEngine.card_special`). There are no
advanced maneuvers.

**The cards.** **Each card is an offensive half over the defensive
half of the same rank and number** -- P2 over F2, B3 over S3, H4 over
R4 (rules-2.2 1.1, 2026-11-01) -- so a deck is twelve cards and every
card plays on either side: `face_on` is the half a side plays. A card's
id is its two indexes, offense first, "P2/F2" (`split_card_id`).

**A deck is a plain dict of three lists** -- `draw`, `hand`, `discard`
-- because it is saved as it stands (`MatchState.maneuver_decks`). The
draw pile is face down and in order: its first entry is the next card
drawn. Nothing here decides who may play what; `RulesEngine.card_plays`
asks `face_on` over the hand.

No Discord, no Pillow and no `async` (the model's purity rules), and
every shuffle is the engine's `rng`, handed in.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

from d12ball.components import (
    MANEUVER_TIER_BASIC,
    DeckCard,
    ManeuverCatalog,
)

#: The cards a coach holds at a time (rules-2.2 1.2).
HAND_SIZE = 3

#: Between a split card's two indexes in its id, "P2/F2".
SPLIT = "/"

#: The three piles a deck is saved as.
DRAW = "draw"
HAND = "hand"
DISCARD = "discard"

@dataclass(frozen=True)
class CardPlay:
    """
    One way a 2.2 coach may play a card from their hand this maneuver
    (`RulesEngine.card_plays`): the card, the half it plays on the side
    (`half`, its index -- "F2" for P2/F2 on defense), the maneuver that
    half plays, and whether its special is live -- the player making
    the maneuver holds a role it names. A pick answers with `card_id`.
    """

    card_id: str
    half: str
    maneuver_key: str
    special: bool = False

    def to_dict(self) -> dict:
        return {
            "card_id": self.card_id,
            "half": self.half,
            "maneuver_key": self.maneuver_key,
            "special": self.special,
        }


#: The other side, for what a half beats, ties and loses to.
OTHER_SIDE = {"offense": "defense", "defense": "offense"}


def split_card_id(offense: DeckCard, defense: DeckCard) -> str:
    """A split card's id: its offensive half's index, then its
    defensive half's, "P2/F2"."""
    return f"{offense.index}{SPLIT}{defense.index}"


def deck_cards(catalog: ManeuverCatalog) -> list[str]:
    """
    The twelve cards of one coach's deck, unshuffled: each offensive
    half paired with the defensive half of the same rank and number,
    by rank and then number -- P1/F1 to P4/F4, B1/S1 to B4/S4, H1/R1 to
    H4/R4. Read off the catalog, so the halves are the data's; a half
    with no partner is not dealt.
    """
    defense = {
        (card.rank, card.number): card
        for card in catalog.deck_cards if card.side == "defense"
    }
    return [
        split_card_id(card, defense[(card.rank, card.number)])
        for card in sorted(
            (card for card in catalog.deck_cards if card.side == "offense"),
            key=lambda card: (card.rank, card.number),
        )
        if (card.rank, card.number) in defense
    ]


@lru_cache(maxsize=None)
def faces(catalog: ManeuverCatalog, card_id: str) -> tuple[DeckCard, ...]:
    """
    **A card's two halves**, offense first, or none for an id that is
    not a split card of the catalog's. Kept, since the catalog is fixed
    and every prompt asks it of every card in a hand.
    """
    indexes = card_id.split(SPLIT)
    if len(indexes) != 2:
        return ()
    halves = tuple(catalog.deck_card(index) for index in indexes)
    return () if any(half is None for half in halves) else halves


def face_on(
    catalog: ManeuverCatalog, card_id: str, side: str,
) -> Optional[DeckCard]:
    """
    **The half `card_id` plays on `side`** -- its top half on offense
    and its bottom half on defense -- or None for an id the catalog
    does not have.
    """
    for half in faces(catalog, card_id):
        if half.side == side:
            return half
    return None


def card_words(
    catalog: ManeuverCatalog, card_id: str, side: Optional[str] = None,
) -> str:
    """
    A card in a line of text: the half `side` plays, "P2 Pass (Pass and
    Run)", or, with no side, both halves, "P2 Pass (Pass and Run) /
    F2 Deflect (Follow)". The id itself for a card the catalog does not
    have.
    """
    halves = faces(catalog, card_id)
    if side is not None:
        half = face_on(catalog, card_id, side)
        if half is not None:
            halves = (half,)
    if not halves:
        return card_id
    return " / ".join(half_words(catalog, half) for half in halves)


def half_words(catalog: ManeuverCatalog, half: DeckCard) -> str:
    """One half in a line of text: "P2 Pass (Pass and Run)"."""
    return f"{half.index} {catalog.card_label(half)}"


def basic_on(
    catalog: ManeuverCatalog, side: str, rank: int,
) -> Optional[str]:
    """The key of the basic maneuver on `side`'s `rank`, or None."""
    for maneuver in catalog.for_tier(side, MANEUVER_TIER_BASIC):
        if maneuver.rank == rank:
            return maneuver.key
    return None


def new_deck(catalog: ManeuverCatalog, rng: random.Random) -> dict:
    """A coach's deck shuffled, and their opening hand of three drawn."""
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
    `card_ids` -- the one card played -- out of the hand onto the
    discard pile, and the hand drawn back up to three. Returns how many
    times the discard was shuffled into a new deck by that draw.
    """
    for card_id in card_ids:
        deck[HAND].remove(card_id)
        deck[DISCARD].append(card_id)
    return draw_cards(deck, rng, max(0, HAND_SIZE - len(deck[HAND])))


def reshuffled(deck: dict, rng: random.Random) -> dict:
    """
    Every card a coach has -- hand, deck and discard -- shuffled into a
    new deck, and a fresh hand of three drawn from it: what halftime
    does (the author, 2026-10-16).
    """
    cards = deck[DRAW] + deck[HAND] + deck[DISCARD]
    rng.shuffle(cards)
    fresh = {DRAW: cards, HAND: [], DISCARD: []}
    draw_cards(fresh, rng, HAND_SIZE)
    return fresh


def hand_order(catalog: ManeuverCatalog, side: str):
    """
    **The one order a 2.2 hand is shown in on `side`**, as a sort key
    over card ids: by the rank and number of the half played on `side`,
    an id the catalog does not have last. The hand's picture and the
    buttons under it both sort by it, so the buttons read left to right
    as the cards do (the author, 2026-11-01).
    """
    def order(card_id: str) -> tuple:
        half = face_on(catalog, card_id, side)
        if half is None:
            return (1, 0, 0)
        return (0, half.rank, half.number)

    return order


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


# -- What the cards say, as numbers ----------------------------------
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

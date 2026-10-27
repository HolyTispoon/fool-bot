"""
D12 Ball 2.0's maneuver deck: each coach's eighteen cards, the hand of
five drawn from them, and the discard pile -- as data and the few moves
made on it. See docs/design/maneuver-deck.md and docs/rules-2.0.md.

**The cards.** Twelve are **two-headed basic cards**, four a rank,
**each a different pair** (the `maneuvers 2.0` tab, 2026-10-27): the
top half is one of the rank's four basic offensive maneuvers and the
bottom half, upside down, the defensive maneuver on the same row of
the rank -- the tab numbers them 1 to 4, and row 1 of rank 1 is Pass
on offense and Deflect on defense, row 2 Curved Pass and Follow. The
other six are the **advanced maneuvers**, row 5 of each rank, one card
each, and an advanced card plays on its own side alone. Three are
offense and three defense, so a hand of five always holds at least one
card either side can play.

**A card is named by an id**, never by what it plays: a basic card is
`basic_<rank>` for row 1 -- the id every two-headed card had when the
deck was four copies of it, so a game saved then still plays -- and
`basic_<rank>_<row>` for rows 2 to 4; an advanced card is its maneuver
key (`skilled_pass`, `intercept`). Which maneuver a card plays is
`plays_as`, asked with the side it is played on, because a two-headed
card is two maneuvers and the side decides which.

**A deck is a plain dict of three lists** -- `draw`, `hand`, `discard`
-- because it is saved as it stands (`MatchState.maneuver_decks`). The
draw pile is face down and in order: its first entry is the next card
drawn. Nothing here decides who may play what; `RulesEngine.maneuver_hand`
asks `plays_as` over the hand.

No Discord, no Pillow and no `async` (the model's purity rules), and
every shuffle is the engine's `rng`, handed in.
"""

from __future__ import annotations

import random
from typing import Optional

from d12ball.components import (
    MANEUVER_TIER_BASIC,
    MANEUVER_TIER_GAMBIT,
    ManeuverCatalog,
    ManeuverDefinition,
)

#: The cards a coach holds at a time.
HAND_SIZE = 5

#: Two-headed cards a rank: the tab's rows 1 to 4. A catalog loaded
#: without the 2.0 tab -- a test's -- has row 1 alone, and its deck
#: carries this many copies of it, as every deck did before the tab.
BASIC_COPIES = 4

#: The rows of a rank that are two-headed cards.
TWO_HEADED_ROWS = (1, 2, 3, 4)

#: A two-headed basic card's id is this and its rank, and `_<row>` past
#: the first row.
BASIC_CARD_PREFIX = "basic_"

#: The three piles a deck is saved as.
DRAW = "draw"
HAND = "hand"
DISCARD = "discard"


def basic_card_id(rank: int, row: int = 1) -> str:
    """The id of the two-headed basic card on `rank`'s `row`."""
    if row == 1:
        return f"{BASIC_CARD_PREFIX}{rank}"
    return f"{BASIC_CARD_PREFIX}{rank}_{row}"


def is_basic_card(card_id: str) -> bool:
    """Whether `card_id` is a two-headed basic card."""
    return card_id.startswith(BASIC_CARD_PREFIX)


def basic_card_rank(card_id: str) -> int:
    """The rank a two-headed basic card carries on both halves."""
    return int(card_id[len(BASIC_CARD_PREFIX):].split("_")[0])


def basic_card_row(card_id: str) -> int:
    """Which row of its rank a two-headed card is -- 1 for `basic_<rank>`."""
    parts = card_id[len(BASIC_CARD_PREFIX):].split("_")
    return int(parts[1]) if len(parts) > 1 else 1


def _row_card(
    catalog: ManeuverCatalog, side: str, rank: int, row: int,
) -> Optional[ManeuverDefinition]:
    """The basic maneuver on `side`'s `rank` and `row`, or `None`. Row 1
    is the 1.0 basic card whether or not the catalog has the 2.0 tab."""
    for maneuver in catalog.deck_side(side):
        if maneuver.rank != rank or maneuver.tier == MANEUVER_TIER_GAMBIT:
            continue
        if maneuver.deck_index == row:
            return maneuver
        if row == 1 and maneuver.tier == MANEUVER_TIER_BASIC:
            return maneuver
    return None


def deck_cards(catalog: ManeuverCatalog) -> list[str]:
    """
    The eighteen cards of one coach's deck, unshuffled: each rank's
    two-headed cards, rows 1 to 4, then the six advanced maneuvers.
    Read off the catalog, so the ranks, the rows and the advanced keys
    are the data's. A row is a card only where both sides have it, so a
    catalog without the 2.0 tab deals `BASIC_COPIES` of row 1.
    """
    ranks = sorted({
        maneuver.rank
        for maneuver in catalog.for_tier("offense", MANEUVER_TIER_BASIC)
    })
    cards = []
    for rank in ranks:
        rows = [
            row for row in TWO_HEADED_ROWS
            if all(
                _row_card(catalog, side, rank, row) is not None
                for side in ("offense", "defense")
            )
        ]
        if rows == [1]:
            rows = [1] * BASIC_COPIES
        cards.extend(basic_card_id(rank, row) for row in rows)
    for side in ("offense", "defense"):
        cards.extend(
            maneuver.key
            for maneuver in sorted(
                catalog.for_tier(side, MANEUVER_TIER_GAMBIT),
                key=lambda item: item.rank,
            )
        )
    return cards


def plays_as(
    catalog: ManeuverCatalog, card_id: str, side: str,
) -> Optional[ManeuverDefinition]:
    """
    The maneuver `card_id` plays on `side` ("offense" or "defense"), or
    `None` where it cannot be played there -- an advanced card on the
    other side's. A two-headed card plays the basic maneuver of its
    rank and row on whichever side it is turned to.
    """
    if is_basic_card(card_id):
        return _row_card(
            catalog, side, basic_card_rank(card_id), basic_card_row(card_id),
        )
    maneuver = catalog.get(card_id)
    if maneuver is None or maneuver not in catalog.side(side):
        return None
    return maneuver


def card_for_maneuver(
    catalog: ManeuverCatalog, hand: list[str], side: str, key: str,
) -> Optional[str]:
    """
    Which card in `hand` plays maneuver `key` on `side`, or `None` where
    none does. Two copies of a basic card are the same card to play,
    so the first is as good as any.
    """
    for card_id in hand:
        maneuver = plays_as(catalog, card_id, side)
        if maneuver is not None and maneuver.key == key:
            return card_id
    return None


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


def play_card(deck: dict, card_id: str, rng: random.Random) -> int:
    """
    `card_id` played out of the hand onto the discard pile, and the
    hand drawn back up to five. Returns how many times the discard was
    shuffled into a new deck by that draw.
    """
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


# -- What the 2.0 cards say, as numbers -------------------------------
#
# Each is a number printed on a card of the `maneuvers 2.0` tab, held
# here beside the deck rather than in the flow so the engine's readings
# and the effects read one value. See docs/rules-2.0.md section 7.

#: 2.0's Pass and Dribble each add 2 to ball speed.
PASS_SPEED_BONUS = 2
DRIBBLE_SPEED_BONUS = 2
#: Curved Pass reaches any teammate up to 2 spaces away, either way.
CURVED_PASS_REACH = 2
#: Advance carries the ball up to 2 spaces forward.
ADVANCE_DISTANCES = (1, 2)
#: Spin moves a teammate in the handler's zone up to 2 spaces.
SPIN_MOVE_REACH = 2
#: Drive takes 2 off the ball's speed.
DRIVE_SPEED_DROP = 2
#: 2.0's High Ball always goes 3 spaces, and Set up 2.
HIGH_BALL_DISTANCE = 3
SET_UP_DISTANCE = 2
#: Where 2.0's Cross may land, and Vertical Ball.
CROSS_DISTANCES = (0, 1, 2, 3)
VERTICAL_BALL_DISTANCES = (0, 1)
#: Follow adds 3 to ball speed; Boot knocks the ball back 2.
FOLLOW_SPEED_GAIN = 3
BOOT_DISTANCE = 2
#: Stay Close: the handler exhausts 1 and the ball loses 2 speed.
STAY_CLOSE_EXHAUSTION = 1
STAY_CLOSE_SPEED_DROP = 2
#: My Turf!: a Defender's or a Midfielder's bonus in the tie's skill
#: test.
MY_TURF_BONUS = 3

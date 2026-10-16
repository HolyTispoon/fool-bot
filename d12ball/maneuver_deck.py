"""
D12 Ball 2.0's maneuver deck: each coach's fifteen cards, the hand of
four drawn from them, and the discard pile -- as data and the few moves
made on it. See docs/design/maneuver-deck.md and docs/rules-2.0.md.

**The cards.** Nine are **two-headed basic cards**, three copies of each
rank, whose top half is the basic offensive maneuver of that rank and
whose bottom half, upside down, is the basic defensive maneuver of the
same rank: one card plays Low Pass on offense and Deflect on defense.
The other six are the **advanced maneuvers**, one card each, and an
advanced card plays on its own side alone. Three are offense and three
defense, so a hand of four always holds at least one card either side
can play.

**A card is named by an id**, never by what it plays: a basic card is
`basic_<rank>` (`basic_1` is the Low Pass / Deflect card), an advanced
card its maneuver key (`skilled_pass`, `intercept`). Which maneuver a
card plays is `plays_as`, asked with the side it is played on, because
a two-headed card is two maneuvers and the side decides which.

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
HAND_SIZE = 4

#: Copies of each rank's two-headed basic card in a deck.
BASIC_COPIES = 3

#: A two-headed basic card's id is this and its rank.
BASIC_CARD_PREFIX = "basic_"

#: The three piles a deck is saved as.
DRAW = "draw"
HAND = "hand"
DISCARD = "discard"


def basic_card_id(rank: int) -> str:
    """The id of the two-headed basic card on `rank`."""
    return f"{BASIC_CARD_PREFIX}{rank}"


def is_basic_card(card_id: str) -> bool:
    """Whether `card_id` is a two-headed basic card."""
    return card_id.startswith(BASIC_CARD_PREFIX)


def basic_card_rank(card_id: str) -> int:
    """The rank a two-headed basic card carries on both halves."""
    return int(card_id[len(BASIC_CARD_PREFIX):])


def deck_cards(catalog: ManeuverCatalog) -> list[str]:
    """
    The fifteen cards of one coach's deck, unshuffled: three of each
    rank's two-headed basic card, then the six advanced maneuvers.
    Read off the catalog, so the ranks and the advanced keys are the
    data's.
    """
    ranks = sorted({
        maneuver.rank
        for maneuver in catalog.for_tier("offense", MANEUVER_TIER_BASIC)
    })
    cards = [
        basic_card_id(rank)
        for rank in ranks
        for _ in range(BASIC_COPIES)
    ]
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
    rank on whichever side it is turned to.
    """
    if is_basic_card(card_id):
        rank = basic_card_rank(card_id)
        for maneuver in catalog.for_tier(side, MANEUVER_TIER_BASIC):
            if maneuver.rank == rank:
                return maneuver
        return None
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
    """A coach's deck shuffled, and their opening hand of four drawn."""
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
    hand drawn back up to four. Returns how many times the discard was
    shuffled into a new deck by that draw.
    """
    deck[HAND].remove(card_id)
    deck[DISCARD].append(card_id)
    return draw_cards(deck, rng, HAND_SIZE - len(deck[HAND]))


def reshuffled(deck: dict, rng: random.Random) -> dict:
    """
    Every card a coach has -- hand, deck and discard -- shuffled into a
    new deck, and a fresh hand of four drawn from it: what halftime
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

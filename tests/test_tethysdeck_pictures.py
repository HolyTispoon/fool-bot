"""The /tethyscards commands' pictures: every saved card name reads as a
card the deck draws, and a row of faces is laid out as the strip says.
How the faces look is not tested -- see docs/design/tethys-deck.md."""
import unittest
from types import SimpleNamespace

from PIL import Image

from cogs.tethysdeck_helpers import (
    DECK_KINDS,
    build_deck,
    format_discard_text,
    format_hand_text,
    parse_card,
    remove_cards,
)
from gamesaves.tethysdeck.storage import ChannelDeck
from tethysdeck import deck_2d12
from tethysdeck.deck import RANKS, SUITS
from tethysdeck.strips import FACE_H, FACE_W, GAP, PER_ROW, Faces


class ParseCardTests(unittest.TestCase):
    def test_every_saved_name_is_a_card_of_the_deck(self):
        parsed = [parse_card(card) for card in build_deck()]
        self.assertEqual(
            sorted(parsed),
            sorted((suit, rank) for suit in SUITS for rank in RANKS),
        )

    def test_a_ruler_and_a_ten(self):
        self.assertEqual(parse_card("Left of 〠 Fiends"), ("fiends", "Left"))
        self.assertEqual(parse_card("10 of $ Money"), ("money", "10"))

    def test_every_2d12_name_is_a_card_of_that_deck(self):
        names = build_deck(deck_2d12.KEY)
        self.assertEqual(len(names), 72)
        self.assertEqual([parse_card(card) for card in names], deck_2d12.cards())

    def test_a_2d12_name_carries_its_fate(self):
        self.assertEqual(parse_card("13 of $ Money (Doom)"), deck_2d12.Card("money", 13, "doom"))
        self.assertEqual(parse_card("2 of 〠 Fiends (Doom)"), deck_2d12.Card("fiends", 2, "doom"))
        self.assertIn("13 of $ Money (Fortune)", build_deck(deck_2d12.KEY))

    def test_a_deck_saved_before_the_2d12_deck_is_classic(self):
        self.assertEqual(ChannelDeck(**{"deck": [], "discard": [], "hands": {}}).kind, "classic")
        self.assertEqual(set(DECK_KINDS), {"classic", deck_2d12.KEY})


class RemoveCardsTests(unittest.TestCase):
    """The 2d12 deck holds some cards twice, so a hand can too."""

    def test_a_card_held_twice_and_chosen_twice_goes_twice(self):
        hand = ["13 of $ Money (Doom)", "5 of $ Money (Fortune)", "13 of $ Money (Doom)"]
        self.assertEqual(remove_cards(hand, ["13 of $ Money (Doom)"] * 2), ["13 of $ Money (Doom)"] * 2)
        self.assertEqual(hand, ["5 of $ Money (Fortune)"])

    def test_a_card_no_longer_held_is_skipped(self):
        hand = ["13 of $ Money (Doom)"]
        self.assertEqual(remove_cards(hand, ["13 of $ Money (Doom)"] * 2), ["13 of $ Money (Doom)"])
        self.assertEqual(hand, [])


class CaptionTests(unittest.TestCase):
    """Under a picture the words say whose cards and how many, and name
    none -- the picture shows them (the author, 2026-10-11). Without one
    every card is named, as before."""

    HAND = ["2 of ⚔ Might", "6 of $ Money"]
    USER = SimpleNamespace(display_name="HolyTispoon")

    def test_a_pictured_hand_names_no_card(self):
        self.assertEqual(
            format_hand_text(self.USER, self.HAND, header="Drew 2 cards.", listed=False),
            "Drew 2 cards.\nHolyTispoon's hand (2 cards):",
        )

    def test_a_hand_in_words_names_every_card(self):
        self.assertEqual(
            format_hand_text(self.USER, self.HAND),
            "HolyTispoon's hand (2 cards): 2 of ⚔ Might, 6 of $ Money",
        )

    def test_an_empty_hand_is_the_same_either_way(self):
        for listed in (True, False):
            self.assertEqual(
                format_hand_text(self.USER, [], listed=listed),
                "HolyTispoon's hand is empty.",
            )

    def test_the_discard_pile(self):
        self.assertEqual(
            format_discard_text(self.HAND, listed=False), "Discard pile (2 cards):",
        )
        self.assertEqual(
            format_discard_text(self.HAND),
            "Discard pile (2 cards): 2 of ⚔ Might, 6 of $ Money",
        )
        self.assertEqual(
            format_discard_text([], listed=False), "The discard pile is empty.",
        )


class StripTests(unittest.TestCase):
    def setUp(self):
        # A plain face per card, so the layout is tested without drawing the deck.
        self.faces = Faces({
            (suit, rank): Image.new("RGBA", (FACE_W, FACE_H), "white")
            for suit in SUITS for rank in RANKS
        })
        self.cards = [(suit, rank) for suit in SUITS for rank in RANKS]

    def test_one_row_up_to_per_row(self):
        image = self.faces.row(self.cards[:3])
        self.assertEqual(image.size, (3 * FACE_W + 2 * GAP, FACE_H))

    def test_wraps_after_per_row(self):
        image = self.faces.row(self.cards[:PER_ROW + 1])
        self.assertEqual(
            image.size,
            (PER_ROW * FACE_W + (PER_ROW - 1) * GAP, 2 * FACE_H + GAP),
        )

    def test_a_face_keeps_the_printed_cards_proportions(self):
        self.assertEqual(750 * FACE_H, 1050 * FACE_W)

    def test_png(self):
        self.assertTrue(self.faces.row_png(self.cards[:2]).startswith(b"\x89PNG"))

    def test_a_2d12_row_shows_a_card_held_twice_twice(self):
        faces = Faces({c: Image.new("RGBA", (FACE_W, FACE_H), "white") for c in deck_2d12.faces()})
        twice = deck_2d12.Card("money", 13, "doom")
        self.assertEqual(faces.row([twice, twice]).size, (2 * FACE_W + GAP, FACE_H))


if __name__ == "__main__":
    unittest.main()

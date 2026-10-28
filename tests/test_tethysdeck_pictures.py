"""The /tethyscards commands' pictures: every saved card name reads as a
card the deck draws, and a row of faces is laid out as the strip says.
How the faces look is not tested -- see docs/design/tethys-deck.md."""
import unittest
from types import SimpleNamespace

from PIL import Image

from cogs.tethysdeck_helpers import (
    build_deck,
    format_discard_text,
    format_hand_text,
    parse_card,
    remove_cards,
    shuffled_before_replacement,
)
from gamesaves.tethysdeck.storage import ChannelDeck
from tethysdeck import deck
from tethysdeck.strips import FACE_H, FACE_W, GAP, PER_ROW, Faces


class ParseCardTests(unittest.TestCase):
    def test_every_saved_name_is_a_card_of_the_deck(self):
        names = build_deck()
        self.assertEqual(len(names), 72)
        self.assertEqual([parse_card(card) for card in names], deck.cards())

    def test_a_name_carries_its_fate(self):
        self.assertEqual(parse_card("13 of $ Money (Doom)"), deck.Card("money", 13, "doom"))
        self.assertEqual(parse_card("2 of 〠 Fiends (Doom)"), deck.Card("fiends", 2, "doom"))
        self.assertIn("13 of $ Money (Fortune)", build_deck())


class ReplacedDeckTests(unittest.TestCase):
    """A channel that shuffled the deck of 1 to 10, Left and Right before
    this one replaced it plays on in words until it shuffles anew."""

    def test_its_names_are_no_card_of_this_deck(self):
        self.assertIsNone(parse_card("Left of 〠 Fiends"))
        self.assertIsNone(parse_card("10 of $ Money"))

    def test_a_channel_is_read_by_any_of_its_cards(self):
        old = ChannelDeck(deck=[], discard=[], hands={"1": ["Left of 〠 Fiends"]})
        self.assertTrue(shuffled_before_replacement(old))
        self.assertFalse(shuffled_before_replacement(ChannelDeck(deck=build_deck())))
        self.assertFalse(shuffled_before_replacement(ChannelDeck()))


class RemoveCardsTests(unittest.TestCase):
    """The deck holds some cards twice, so a hand can too."""

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

    HAND = ["7 of ⚔ Might (Doom)", "6 of $ Money (Fortune)"]
    USER = SimpleNamespace(display_name="HolyTispoon")

    def test_a_pictured_hand_names_no_card(self):
        self.assertEqual(
            format_hand_text(self.USER, self.HAND, header="Drew 2 cards.", listed=False),
            "Drew 2 cards.\nHolyTispoon's hand (2 cards):",
        )

    def test_a_hand_in_words_names_every_card(self):
        self.assertEqual(
            format_hand_text(self.USER, self.HAND),
            "HolyTispoon's hand (2 cards): 7 of ⚔ Might (Doom), 6 of $ Money (Fortune)",
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
            "Discard pile (2 cards): 7 of ⚔ Might (Doom), 6 of $ Money (Fortune)",
        )
        self.assertEqual(
            format_discard_text([], listed=False), "The discard pile is empty.",
        )


class StripTests(unittest.TestCase):
    def setUp(self):
        # A plain face per card, so the layout is tested without drawing the deck.
        self.faces = Faces({c: Image.new("RGBA", (FACE_W, FACE_H), "white") for c in deck.faces()})
        self.cards = deck.cards()

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

    def test_a_card_held_twice_shows_twice(self):
        twice = deck.Card("money", 13, "doom")
        self.assertEqual(self.faces.row([twice, twice]).size, (2 * FACE_W + GAP, FACE_H))


if __name__ == "__main__":
    unittest.main()

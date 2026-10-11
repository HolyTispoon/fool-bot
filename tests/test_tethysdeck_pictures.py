"""The /tethyscards commands' pictures: every saved card name reads as a
card the deck draws, and a row of faces is laid out as the strip says.
How the faces look is not tested -- see docs/design/tethys-deck.md."""
import unittest

from PIL import Image

from cogs.tethysdeck_helpers import build_deck, parse_card
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


if __name__ == "__main__":
    unittest.main()

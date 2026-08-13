"""
The roster printed as cards.

The suite cannot see a picture, so what it checks is what a print gets
wrong silently: a card that is no longer poker size, an ability long
enough to squeeze the portrait out of the card, and the one rule about
the wording -- the printed card carries the whole ability sentence, and
shortening it here is a rules judgement the author makes upstream.
"""
import unittest
from pathlib import Path

from d12ball import player_cards
from d12ball.cards import (
    BLEED,
    CARD_FACE,
    CARD_HEIGHT,
    CARD_WIDTH,
    FRAME,
    Pen,
)
from d12ball.components import load_player_catalog
from d12ball.player_cards import (
    HEADER_HEIGHT,
    PORTRAIT_GAP,
    STATS_HEIGHT,
    STATS_TOP_GAP,
    ability_lines,
    render_player_card,
)

# The portrait is the reason a player card exists as a picture at all,
# so a layout that leaves it less than this much of a 1050-unit card
# has stopped being a player card and become a paragraph.
MIN_PORTRAIT_HEIGHT = 380


class D12BallPlayerCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.players = [
            player
            for roster in cls.catalog.teams.values()
            for player in roster.players
        ]

    def test_every_player_renders_at_poker_size(self) -> None:
        for player in self.players:
            with self.subTest(player=player.name):
                card = render_player_card(self.catalog, player, bleed=False)
                self.assertEqual(card.size, (CARD_WIDTH, CARD_HEIGHT))

    def test_a_bleed_card_carries_an_eighth_of_an_inch_all_round(
        self,
    ) -> None:
        player = self.players[0]
        card = render_player_card(self.catalog, player, bleed=True)
        self.assertEqual(
            card.size, (CARD_WIDTH + BLEED * 2, CARD_HEIGHT + BLEED * 2)
        )

    def test_the_ability_band_leaves_the_portrait_room(self) -> None:
        """
        The bands are laid out from the two edges in and the portrait
        takes what is left, so a longer ability eats into the picture
        rather than overflowing the card -- which is exactly the
        failure nothing else would notice. The Fullback's two-sentence
        ability is the long one today; an import that doubles one
        should fail here rather than print.
        """
        pen = Pen((CARD_WIDTH, CARD_HEIGHT), CARD_FACE)
        portrait_top = FRAME + HEADER_HEIGHT + STATS_TOP_GAP + STATS_HEIGHT

        for player in self.players:
            profile = self.catalog.effective_profile(player)
            _, ability_height = ability_lines(pen, profile.ability)
            portrait_bottom = CARD_HEIGHT - FRAME - 18 - ability_height
            with self.subTest(player=player.name):
                self.assertGreaterEqual(
                    portrait_bottom - PORTRAIT_GAP * 2 - portrait_top,
                    MIN_PORTRAIT_HEIGHT,
                )

    def test_the_card_never_shortens_an_ability(self) -> None:
        """
        Which half of a two-part ability survives is a rules judgement,
        so the short form is written upstream and imported -- see
        "Every ability is imported twice" in CLAUDE.md. A printed card
        is the only place its coach can read the rule, so it carries
        the sentence; this is the guard against somebody reaching for
        `ability_short` to buy a line of room back.
        """
        source = Path(player_cards.__file__).read_text(encoding="utf-8")
        for name in ("ability_short", "short_ability"):
            with self.subTest(attribute=name):
                self.assertNotIn(f".{name}", source)


if __name__ == "__main__":
    unittest.main()

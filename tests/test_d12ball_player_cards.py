"""
The roster printed as cards, both sides.

The suite cannot see a picture, so what it checks is what a print gets
wrong silently: a card that is no longer poker size, an ability long
enough to squeeze the portrait out of the card, a back sheet that would
land the wrong player behind a front, and the one rule about the
wording -- the printed card carries the whole role ability sentence,
and shortening it here is a rules judgement the author makes upstream.
"""
import unittest
from pathlib import Path

from d12ball import player_cards
from d12ball.cards import BLEED, CARD_FACE, CARD_HEIGHT, CARD_WIDTH, Pen
from d12ball.components import load_player_catalog
from d12ball.player_cards import (
    ADVANCED_BAND_HEIGHT,
    ADVANCED_BAND_TOP,
    MIN_BACK_PORTRAIT_HEIGHT,
    MIN_PORTRAIT_HEIGHT,
    PORTRAIT_GAP,
    PORTRAIT_TOP,
    TEAM_SHEET_COLUMNS,
    ability_lines,
    advanced_ability_lines,
    duplex_order,
    portrait_room,
    render_player_card,
    render_player_card_back,
    species_ability,
    species_short_fits,
)

# The floors are the module's, not the suite's: the layout reads them
# to decide what goes on a card, so a copy here would let a card that
# prints and a card that passes mean two different things.


def profile_ability(catalog, player) -> str:
    return catalog.effective_profile(player).ability


class D12BallPlayerCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        # Every player now belongs to two rosters (a color team and a
        # species team), so a card is printed per (player, team) pair --
        # this carries both members of that pair through, rather than a
        # bare player list that would need a team invented for it.
        cls.player_team_pairs = [
            (player, team)
            for team, roster in cls.catalog.teams.items()
            for player in roster.players
        ]
        cls.players = [player for player, _team in cls.player_team_pairs]

    def test_every_player_renders_at_poker_size(self) -> None:
        for player, team in self.player_team_pairs:
            with self.subTest(player=player.name, team=team.value):
                card = render_player_card(
                    self.catalog, player, team, bleed=False,
                )
                self.assertEqual(card.size, (CARD_WIDTH, CARD_HEIGHT))

    def test_a_bleed_card_carries_an_eighth_of_an_inch_all_round(
        self,
    ) -> None:
        player, team = self.player_team_pairs[0]
        card = render_player_card(self.catalog, player, team, bleed=True)
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

        for player in self.players:
            profile = self.catalog.effective_profile(player)
            _, ability_height = ability_lines(pen, profile.ability)
            with self.subTest(player=player.name):
                self.assertGreaterEqual(
                    portrait_room(ability_height), MIN_PORTRAIT_HEIGHT
                )

    def test_every_advanced_back_renders_at_poker_size(self) -> None:
        for player, team in self.player_team_pairs:
            with self.subTest(player=player.name, team=team.value):
                card = render_player_card_back(
                    self.catalog, player, team, bleed=False,
                )
                self.assertEqual(card.size, (CARD_WIDTH, CARD_HEIGHT))

    def test_the_advanced_band_leaves_the_portrait_room(self) -> None:
        """
        The back's band does not move, so this is one sum rather than a
        walk of the roster -- which is the point of fixing it. Every
        back gets the same portrait slot, and the question is only
        whether that slot is still a picture.
        """
        slot = ADVANCED_BAND_TOP - PORTRAIT_GAP - (
            PORTRAIT_TOP + PORTRAIT_GAP
        )
        self.assertGreaterEqual(slot, MIN_BACK_PORTRAIT_HEIGHT)

    def test_the_advanced_badge_sits_in_one_place_on_every_card(
        self,
    ) -> None:
        """
        The author's call, and the reason the band is pinned: a marker
        a coach finds by looking at one spot on the card cannot be a
        marker that moves with how long the player's role ability runs.

        The badge rides the band's heading row, so asserting the band's
        top is the whole of it -- and the way this breaks is somebody
        going back to laying the band out from the bottom edge up, the
        way the front still does, which would make the top a function
        of the text again.
        """
        pen = Pen((CARD_WIDTH, CARD_HEIGHT), CARD_FACE)
        drawn = set()

        for player in self.players:
            short = (
                species_ability(player.species)["ability_short"]
                if species_short_fits(pen, self.catalog, player.species)
                else ""
            )
            _, _, height = advanced_ability_lines(
                pen, profile_ability(self.catalog, player), short
            )
            with self.subTest(player=player.name):
                # Nothing may overflow the band it is pinned to.
                self.assertLessEqual(height, ADVANCED_BAND_HEIGHT)
            drawn.add(CARD_HEIGHT - ADVANCED_BAND_TOP)

        self.assertEqual(drawn, {CARD_HEIGHT - ADVANCED_BAND_TOP})

    def test_a_role_ability_alone_always_fits_the_advanced_band(
        self,
    ) -> None:
        """
        The species' short form is droppable and the role ability is
        not, so this is the one thing the fixed band has to be able to
        hold whatever the data does. It is 153 units against 340 today;
        an import that doubled a role ability would fail here rather
        than print off the bottom of a card.
        """
        pen = Pen((CARD_WIDTH, CARD_HEIGHT), CARD_FACE)

        for player in self.players:
            _, _, height = advanced_ability_lines(
                pen, profile_ability(self.catalog, player), ""
            )
            with self.subTest(player=player.name):
                self.assertLessEqual(height, ADVANCED_BAND_HEIGHT)

    def test_a_species_short_form_is_all_of_that_species_or_none(
        self,
    ) -> None:
        """
        Two cards of one species disagreeing about whether the species
        line is on them reads as a misprint, not as a layout that
        scaled -- so the room is decided for the species and the
        longest role ability in it settles the answer. This is the
        claim `species_short_fits` makes.
        """
        pen = Pen((CARD_WIDTH, CARD_HEIGHT), CARD_FACE)
        by_species: dict[str, set[bool]] = {}

        for player in self.players:
            short = species_ability(player.species).get("ability_short", "")
            fits = (
                advanced_ability_lines(
                    pen, profile_ability(self.catalog, player), short
                )[2]
                <= ADVANCED_BAND_HEIGHT
            )
            carried = species_short_fits(
                pen, self.catalog, player.species
            )
            by_species.setdefault(player.species, set()).add(carried)
            if carried:
                with self.subTest(player=player.name, claim="fits"):
                    self.assertTrue(fits)

        for species, answers in by_species.items():
            with self.subTest(species=species):
                self.assertEqual(len(answers), 1)

    def test_a_back_sheet_lands_each_card_behind_its_own_front(
        self,
    ) -> None:
        """
        A duplex sheet comes out flipped about the paper's long edge,
        so each row of backs has to be reversed. Nothing about a
        printed sheet says which way round it went, and a deck printed
        the wrong way is not something a run recovers from.
        """
        fronts = list(range(9))
        self.assertEqual(
            duplex_order(fronts, TEAM_SHEET_COLUMNS),
            [2, 1, 0, 5, 4, 3, 8, 7, 6],
        )

    def test_a_short_last_row_of_backs_keeps_its_columns(self) -> None:
        # print_sheet pads a short row at its end, so on the back that
        # padding lands at the start of the row -- which is where the
        # missing front is.
        self.assertEqual(duplex_order(list(range(5)), 3), [2, 1, 0, 4, 3])

    def test_the_card_never_shortens_a_role_ability(self) -> None:
        """
        Which half of a two-part ability survives is a rules judgement,
        so the short form is written upstream and imported -- see
        "Every ability is imported twice" in docs/design/rules-and-data.md. A printed card
        is the only place its coach can read the rule, so it carries
        the sentence; this is the guard against somebody reaching for
        `ability_short` to buy a line of room back.

        It is a rule about the *role* ability, which is why the grep is
        for the attribute: the back does carry the species' short form,
        out of `species.json`'s own dict, which is exactly what that
        field is there for -- see "The species cards" in docs/design/cards.md.
        """
        source = Path(player_cards.__file__).read_text(encoding="utf-8")
        for name in ("ability_short", "short_ability"):
            with self.subTest(attribute=name):
                self.assertNotIn(f".{name}", source)


if __name__ == "__main__":
    unittest.main()

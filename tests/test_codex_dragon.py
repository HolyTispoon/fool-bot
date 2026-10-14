"""
The two-headed dragon through the driver (docs/codex-multiplayer.md,
step 5): the teams and the deal, the team's turn with two seats acting in
one main phase, the attack priorities over both patrol zones, and the
words "you" and "friendly" -- each staged by slug and played through
`driver.apply`.

The rules are Rulebook p. 13 (with p. 4, 5 and 11 where a test says so)
and the General group's overpower and tower rulings, Captured
Bugblatter's, Drakk Ramhorn's and Moment's Peace's.
"""

from __future__ import annotations

import unittest

from codex.components import MatchState
from codex.engine import DRAGON_BASE_HP, RulesEngine
from codex.game import CodexGame, RuleRefusal

from codex_positions import begin, built, hero_in_play, new_game, put

FOUR = (("bashing",), ("finesse",), ("bashing",), ("finesse",))
DRAGON = "two_headed_dragon"


def dragon(teams=FOUR, first=1, seed=7):
    """A dragon dealt and standing on the first team's turn."""
    return new_game(seed=seed, first=first, teams=teams, variant=DRAGON)


class DealTests(unittest.TestCase):
    """The teams and the deal (Rulebook p. 13)."""

    def test_four_seats_in_two_teams_with_one_base_of_thirty_each(self) -> None:
        engine, game, match = dragon()
        self.assertEqual(match.dragons, [[1, 2], [3, 4]])
        self.assertEqual(engine.dragon_of(match, 2), (1, 2))
        self.assertEqual(engine.teammate(match, 3), 4)
        self.assertEqual(engine.opponents(match, 1), (3, 4))
        self.assertEqual([match.base_of(seat) for seat in (1, 2, 3, 4)], [DRAGON_BASE_HP] * 4)
        self.assertEqual(DRAGON_BASE_HP, 30)
        match.validate(engine.catalog)

    def test_the_first_team_starts_with_four_workers_each_and_the_other_five(self) -> None:
        """Rulebook p. 13: each player on the team that goes first starts
        with 4 workers, each on the other with 5."""
        for first in (1, 3):
            engine, game, match = dragon(first=first)
            going = engine.dragon_of(match, first)
            for player in match.players:
                self.assertEqual(player.workers, 4 if player.seat in going else 5)
            self.assertEqual(match.first, going[0])
            self.assertEqual(match.active, going[0])

    def test_the_first_team_is_drawn_when_not_given(self) -> None:
        engine = RulesEngine(seed=5)
        match = engine.new_match([["bashing"], ["finesse"], ["bashing"], ["finesse"]],
                                 variant=DRAGON)
        self.assertIn(match.first, (1, 3))

    def test_the_bases_are_one_reading(self) -> None:
        """A team's base is its head's `base_hp`; the second seat's is
        never read (decision 9)."""
        engine, game, match = dragon()
        match.set_base(2, 24)
        self.assertEqual(match.player(1).base_hp, 24)
        self.assertEqual(match.base_of(1), 24)
        self.assertEqual(match.base_of(2), 24)
        self.assertEqual(match.base_of(3), 30)

    def test_no_mercenary_is_owed_and_no_addition_is_listed(self) -> None:
        """Nothing of the free-for-all's three additions is on a dragon."""
        engine, game, match = dragon()
        self.assertTrue(all(player.mercenaries_owed == 0 for player in match.players))
        begin(engine, game, match)
        self.assertIsNone(engine.repair_option(match))
        self.assertEqual(engine.lending_zones(match), ())

    def test_the_dragons_are_saved_and_a_duel_saves_none(self) -> None:
        engine, game, match = dragon()
        saved = match.to_dict()
        self.assertEqual(saved["dragons"], [[1, 2], [3, 4]])
        self.assertEqual(MatchState.from_dict(saved).dragons, [[1, 2], [3, 4]])
        _, _, duel = new_game()
        for key in ("dragons", "solo"):
            self.assertNotIn(key, duel.to_dict())
        for player in duel.to_dict()["players"]:
            self.assertNotIn("locked", player)
            self.assertNotIn("locking", player)

    def test_a_dragon_needs_four_seats_in_two_teams(self) -> None:
        engine, game, match = dragon()
        match.dragons = [[1, 2], [3, 3]]
        with self.assertRaises(ValueError):
            match.validate(engine.catalog)
        _, _, duel = new_game()
        duel.dragons = [[1, 2]]
        with self.assertRaises(ValueError):
            duel.validate(engine.catalog)


class AddOnTests(unittest.TestCase):
    """A team never holds two of the same add-on (Rulebook p. 13)."""

    def test_the_build_options_refuse_the_teammates_add_on(self) -> None:
        from codex.components import AddOnState

        engine, game, match = dragon()
        begin(engine, game, match)
        match.player(2).add_on = AddOnState(slug="tower", hp=4, under_construction=True)
        mine = match.player(1)
        option = engine.build_option(mine, "tower", match)
        self.assertFalse(option.allowed)
        self.assertIn("teammate", option.why_not)
        self.assertTrue(engine.build_option(mine, "surplus", match).why_not != option.why_not)
        # The other team's add-on is nothing to do with it.
        match.player(3).add_on = AddOnState(slug="surplus", hp=4)
        self.assertNotIn("teammate", engine.build_option(mine, "surplus", match).why_not)


class SeeingTests(unittest.TestCase):
    """What a teammate may see: the hand, the codex and the tech choice,
    and nothing else (decision 13)."""

    def test_team_sees_names_the_teammate_in_a_dragon_and_nobody_in_a_duel(self) -> None:
        engine, game, match = dragon()
        self.assertEqual(engine.team_sees(match, 1), 2)
        self.assertEqual(engine.team_sees(match, 4), 3)
        _, _, duel = new_game()
        self.assertIsNone(engine.team_sees(duel, 1))

    def test_hands_visible_to_folds_it_in_beside_a_reveal(self) -> None:
        engine, game, match = dragon()
        self.assertEqual(engine.hands_visible_to(match, 1), (2,))
        put(match, 1, "eyes_of_the_chancellor")
        self.assertEqual(engine.hands_visible_to(match, 1), (2, 3, 4))

    def test_the_codex_and_the_tech_choice_are_shown_to_a_teammate_alone(self) -> None:
        engine, game, match = dragon()
        match.player(2).tech_choice = ["iron_man"]
        self.assertEqual(engine.tech_picks_of(match, 1, 2), ["iron_man"])
        self.assertEqual(engine.tech_picks_of(match, 2, 2), ["iron_man"])
        self.assertTrue(engine.codex_remaining(match, 2, viewer=1))
        self.assertTrue(engine.own_deck(match, 2, viewer=1).cards)
        for foe in (3, 4):
            with self.assertRaises(RuleRefusal) as refused:
                engine.tech_picks_of(match, 1, foe)
            self.assertEqual(refused.exception.cite, "Rulebook p. 13")
            with self.assertRaises(RuleRefusal):
                engine.codex_remaining(match, foe, viewer=1)
            with self.assertRaises(RuleRefusal):
                engine.own_deck(match, foe, viewer=1)
        # In a duel nobody sees the other's.
        _, _, duel = new_game()
        with self.assertRaises(RuleRefusal):
            engine.codex_remaining(duel, 2, viewer=1)


if __name__ == "__main__":
    unittest.main()

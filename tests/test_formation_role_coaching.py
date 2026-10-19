"""
D12 Ball 2.0's Coaching Choice: a player's role decides how they may
be moved (docs/rules-2.0.md 4.6; "Roles" in
docs/design/maneuver-deck.md).
"""

from __future__ import annotations

import unittest
from unittest import mock

from d12ball import prompts
from d12ball.ai import DinkyAI
from d12ball.components import (
    CoachingOccasion,
    PlayerRole,
    RuleRefusal,
    TeamSide,
    Zone,
)
from d12ball.game import Edition, Formation

from roster import fielded
from test_formation_roles import kickoff, space_of

HOME = TeamSide.HOME


def hub_options(engine, game, match, side: TeamSide = HOME):
    """The Coaching Choice's options for an open window on `side`."""
    match.pending_coaching_side = side.value
    return prompts._coaching_hub_options(engine, game, match, None)


def by_role(engine, match, zone: Zone, role: PlayerRole) -> list[str]:
    """A side's cards in `zone` holding `role`, in zone order."""
    return [
        card for card in match.home.zones[zone]
        if engine.role_of(match, card) == role
    ]


class SpacePositioningTests(unittest.TestCase):
    """4.6d: a unique role holds its space; a standard role moves to an
    empty space or trades with another standard role."""

    def test_a_unique_role_may_not_move(self) -> None:
        engine, _, match = kickoff(Edition.TWO, 9)
        for role in (
            PlayerRole.FULLBACK, PlayerRole.PLAYMAKER, PlayerRole.STRIKER,
        ):
            card = fielded(match, role)
            zone, space = space_of(match, card)
            with self.subTest(role=role):
                self.assertEqual(match.positioning_targets(HOME, card), [])
                other = (space + 1) % len(match.board.spaces[zone])
                with self.assertRaises(RuleRefusal):
                    match.position_meeple(HOME, card, other)

    def test_a_standard_role_may_not_move_onto_a_unique_roles_space(
        self,
    ) -> None:
        engine, _, match = kickoff(Edition.TWO, 9)
        defender = fielded(match, PlayerRole.DEFENDER)
        fullback = fielded(match, PlayerRole.FULLBACK)
        self.assertEqual(space_of(match, defender), (Zone.HOME_ZONE, 2))
        self.assertEqual(
            match.positioning_targets(HOME, defender), [(1, ())],
        )
        with self.assertRaises(RuleRefusal):
            match.position_meeple(HOME, defender, 0)
        self.assertEqual(space_of(match, fullback), (Zone.HOME_ZONE, 0))

        self.assertIsNone(match.position_meeple(HOME, defender, 1))
        self.assertEqual(space_of(match, defender), (Zone.HOME_ZONE, 1))

    def test_two_standard_roles_swap_places(self) -> None:
        engine, game, match = kickoff(Edition.TWO, 9)
        engine.apply_formation(match, HOME, Formation.ONE_TWO_THREE, game)
        first, second = by_role(
            engine, match, Zone.VISITORS_ZONE, PlayerRole.WINGER,
        )
        _, there = space_of(match, second)
        targets = dict(match.positioning_targets(HOME, first))
        self.assertEqual(targets[there], (second,))

        _, here = space_of(match, first)
        self.assertEqual(match.position_meeple(HOME, first, there), second)
        self.assertEqual(space_of(match, first), (Zone.VISITORS_ZONE, there))
        self.assertEqual(space_of(match, second), (Zone.VISITORS_ZONE, here))

    def test_one_point_oh_moves_anybody_anywhere_in_their_zone(self) -> None:
        engine, _, match = kickoff(Edition.ONE, 9)
        fullback = fielded(match, PlayerRole.FULLBACK)
        self.assertEqual(
            [space for space, _ in match.positioning_targets(HOME, fullback)],
            [1, 2],
        )


class OozeTests(unittest.TestCase):
    """4.6e: a Spreadable Ooze bends the rule. `MatchState` does not
    know a species, so the test names the card the engine would."""

    def test_an_ooze_in_a_standard_role_may_share_any_space(self) -> None:
        engine, _, match = kickoff(Edition.TWO, 9)
        defender = fielded(match, PlayerRole.DEFENDER)
        fullback = fielded(match, PlayerRole.FULLBACK)
        self.assertEqual(
            match.positioning_targets(HOME, defender, {defender}),
            [(0, ()), (1, ())],
        )
        self.assertIsNone(
            match.position_meeple(
                HOME, defender, 0, spread_exempt_ids={defender},
            )
        )
        self.assertEqual(space_of(match, fullback), (Zone.HOME_ZONE, 0))
        self.assertEqual(space_of(match, defender), (Zone.HOME_ZONE, 0))

    def test_an_ooze_in_a_unique_role_is_locked_but_shares(self) -> None:
        engine, _, match = kickoff(Edition.TWO, 9)
        defender = fielded(match, PlayerRole.DEFENDER)
        fullback = fielded(match, PlayerRole.FULLBACK)
        self.assertEqual(
            match.positioning_targets(HOME, fullback, {fullback}), [],
        )
        self.assertEqual(
            match.positioning_targets(HOME, defender, {fullback}),
            [(0, ()), (1, ())],
        )
        self.assertIsNone(
            match.position_meeple(
                HOME, defender, 0, spread_exempt_ids={fullback},
            )
        )
        self.assertEqual(space_of(match, fullback), (Zone.HOME_ZONE, 0))


class MovingOffTests(unittest.TestCase):
    """A teammate sharing an Ooze's unique space is moved off once
    somebody who is not an Ooze takes the role; with a choice, the
    coach chooses (the author, 2026-10-18)."""

    def share_the_fullbacks_space(self, board_size: int):
        engine, game, match = kickoff(Edition.TWO, board_size)
        fullback = fielded(match, PlayerRole.FULLBACK)
        defender = fielded(match, PlayerRole.DEFENDER)
        winger = fielded(match, PlayerRole.WINGER)
        ooze = {fullback}
        match.position_meeple(HOME, defender, 0, spread_exempt_ids=ooze)
        match.exchange_field_players(HOME, fullback, winger)
        self.assertEqual(engine.role_of(match, winger), PlayerRole.FULLBACK)
        return engine, game, match, defender, ooze

    def test_one_open_space_moves_them_there(self) -> None:
        engine, _, match, defender, ooze = self.share_the_fullbacks_space(7)
        self.assertEqual(match.unique_space_sharers(HOME, ooze), [defender])
        self.assertEqual(
            match.settle_unique_space_sharers(HOME, ooze),
            [(defender, Zone.HOME_ZONE, 1)],
        )
        self.assertEqual(match.unique_space_sharers(HOME, ooze), [])

    def test_a_choice_of_spaces_is_the_coachs(self) -> None:
        engine, game, match, defender, ooze = self.share_the_fullbacks_space(9)
        self.assertEqual(match.settle_unique_space_sharers(HOME, ooze), [])
        self.assertEqual(space_of(match, defender), (Zone.HOME_ZONE, 0))
        self.assertEqual(
            match.positioning_targets(HOME, defender, ooze),
            [(1, ()), (2, ())],
        )

        match.pending_coaching_occasion = CoachingOccasion.SETUP.value
        with mock.patch.object(engine, "spread_exempt_ids", return_value=ooze):
            options = hub_options(engine, game, match)
            self.assertEqual(options.must_move, (defender,))
            self.assertIsNotNone(options.finish_refusal)
            match.position_meeple(HOME, defender, 2, spread_exempt_ids=ooze)
            self.assertIsNone(
                engine.coaching_finish_refusal(match, HOME, game),
            )

    def test_dinky_moves_them_before_it_is_done(self) -> None:
        engine, game, match, defender, ooze = self.share_the_fullbacks_space(9)
        match.pending_coaching_occasion = CoachingOccasion.SETUP.value
        with mock.patch.object(engine, "spread_exempt_ids", return_value=ooze):
            prompt = prompts.PendingPrompt(
                kind=prompts.PromptKind.COACHING_HUB, ask="",
                side=HOME, options=hub_options(engine, game, match),
            )
        action = DinkyAI(engine.player_catalog, engine.maneuver_catalog).choose(
            prompt, game, match, HOME,
        )
        self.assertEqual(action.choice, "reposition")
        self.assertEqual(action.arguments["player_id"], defender)
        self.assertEqual(action.arguments["space_index"], 1)

    def test_one_point_oh_has_nobody_to_move(self) -> None:
        _, _, match = kickoff(Edition.ONE, 9)
        self.assertEqual(match.unique_space_sharers(HOME), [])


class ZoneAssignmentTests(unittest.TestCase):
    """4.6c: a zone assignment trades two roles, in the same zone too."""

    def test_two_in_the_same_zone_trade_roles_and_spaces(self) -> None:
        engine, _, match = kickoff(Edition.TWO, 9)
        fullback = fielded(match, PlayerRole.FULLBACK)
        defender = fielded(match, PlayerRole.DEFENDER)
        match.exchange_field_players(HOME, fullback, defender)
        self.assertEqual(engine.role_of(match, defender), PlayerRole.FULLBACK)
        self.assertEqual(engine.role_of(match, fullback), PlayerRole.DEFENDER)
        self.assertEqual(space_of(match, defender), (Zone.HOME_ZONE, 0))
        self.assertEqual(space_of(match, fullback), (Zone.HOME_ZONE, 2))

    def test_two_in_the_same_standard_role_are_not_a_trade(self) -> None:
        engine, game, match = kickoff(Edition.TWO, 9)
        engine.apply_formation(match, HOME, Formation.ONE_TWO_THREE, game)
        first, second = by_role(
            engine, match, Zone.VISITORS_ZONE, PlayerRole.WINGER,
        )
        with self.assertRaises(RuleRefusal):
            match.exchange_field_players(HOME, first, second)

    def test_one_point_oh_refuses_the_same_zone(self) -> None:
        _, _, match = kickoff(Edition.ONE, 9)
        with self.assertRaises(RuleRefusal):
            match.exchange_field_players(
                HOME,
                fielded(match, PlayerRole.FULLBACK),
                fielded(match, PlayerRole.DEFENDER),
            )


class HubOptionsTests(unittest.TestCase):
    """The hub offers what the model allows, and nothing else."""

    def test_two_point_oh_offers_the_same_zones_other_role(self) -> None:
        engine, game, match = kickoff(Edition.TWO, 9)
        options = hub_options(engine, game, match)
        fullback = fielded(match, PlayerRole.FULLBACK)
        partners = next(
            swap.partner_ids for swap in options.swaps
            if swap.player_id == fullback
        )
        self.assertIn(fielded(match, PlayerRole.DEFENDER), partners)
        self.assertEqual(len(partners), 5)

    def test_a_unique_role_is_not_offered_a_space(self) -> None:
        engine, game, match = kickoff(Edition.TWO, 9)
        options = hub_options(engine, game, match)
        offered = {entry.player_id for entry in options.repositions}
        self.assertEqual(offered, {
            fielded(match, role)
            for role in (
                PlayerRole.DEFENDER, PlayerRole.MIDFIELDER, PlayerRole.WINGER,
            )
        })
        defender = fielded(match, PlayerRole.DEFENDER)
        spaces = next(
            entry.spaces for entry in options.repositions
            if entry.player_id == defender
        )
        self.assertEqual([space.space_index for space in spaces], [1])

    def test_one_point_oh_is_unchanged(self) -> None:
        engine, game, match = kickoff(Edition.ONE, 9)
        options = hub_options(engine, game, match)
        fullback = fielded(match, PlayerRole.FULLBACK)
        partners = next(
            swap.partner_ids for swap in options.swaps
            if swap.player_id == fullback
        )
        self.assertNotIn(fielded(match, PlayerRole.DEFENDER), partners)
        self.assertEqual(len(partners), 4)
        self.assertEqual(len(options.repositions), 6)


class FormationChangeTests(unittest.TestCase):
    """A 2.0 formation change keeps the Fullback, Playmaker and Striker
    on their spaces and fills the standard roles by defensive skill
    (the author, 2026-10-18)."""

    def test_the_unique_roles_keep_their_holders_and_spaces(self) -> None:
        for board_size, formation in (
            (7, Formation.TWO_THREE_ONE),
            (9, Formation.ONE_TWO_THREE),
            (9, Formation.THREE_TWO_ONE),
            (10, Formation.ONE_THREE_TWO),
        ):
            engine, game, match = kickoff(Edition.TWO, board_size)
            unique = {
                role: fielded(match, role)
                for role in (
                    PlayerRole.FULLBACK, PlayerRole.PLAYMAKER,
                    PlayerRole.STRIKER,
                )
            }
            before = {role: space_of(match, card) for role, card in unique.items()}
            engine.apply_formation(match, HOME, formation, game)
            for role, card in unique.items():
                with self.subTest(board=board_size, formation=formation, role=role):
                    self.assertEqual(engine.role_of(match, card), role)
                    self.assertEqual(space_of(match, card), before[role])
            self.assertEqual(engine.current_formation(match, HOME), formation)

    def test_the_best_defender_left_goes_furthest_back(self) -> None:
        engine, game, match = kickoff(Edition.TWO, 9)
        engine.apply_formation(match, HOME, Formation.ONE_TWO_THREE, game)
        (midfielder,) = by_role(
            engine, match, Zone.MIDFIELD, PlayerRole.MIDFIELDER,
        )
        wingers = by_role(
            engine, match, Zone.VISITORS_ZONE, PlayerRole.WINGER,
        )
        defense = lambda card: engine.skills(game, card).defense
        self.assertTrue(all(
            defense(midfielder) >= defense(winger) for winger in wingers
        ))
        # Behind the Playmaker, toward their own goal.
        self.assertEqual(space_of(match, midfielder), (Zone.MIDFIELD, 0))


if __name__ == "__main__":
    unittest.main()

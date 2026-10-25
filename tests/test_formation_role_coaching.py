"""
D12 Ball 2.0's Coaching Choice: a player's role decides how they may
be moved (docs/rules-2.0.md 4.6; "Roles" in
docs/design/maneuver-deck.md).
"""

from __future__ import annotations

import unittest
from unittest import mock

from d12ball import prompts
from d12ball.flow import driver, windows
from d12ball.ai import DinkyAI
from d12ball.components import (
    CoachingOccasion,
    MatchState,
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
    """The model's reading of where a 2.0 player may be moved
    (`positioning_targets`): a unique role holds its space; a standard
    role moves to an empty space or trades with another standard role.
    A coach no longer moves anybody with it (4.6, the author,
    2026-10-25), but a teammate moved off a unique role's space still
    goes by it."""

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
            # The coach moves them by rearranging (4.6): every space
            # with room is offered, in any zone.
            moves = [
                edit for edit in options.arrangement.edits(defender)
                if edit.kind == "move"
            ]
            self.assertIn(
                (Zone.HOME_ZONE, 2),
                [(edit.space.zone, edit.space.space_index) for edit in moves],
            )
            match.position_meeple(HOME, defender, 2, spread_exempt_ids=ooze)
            self.assertIsNone(
                engine.coaching_finish_refusal(match, HOME, game),
            )

    def test_dinky_moves_them_before_it_is_done(self) -> None:
        engine, game, match, defender, ooze = self.share_the_fullbacks_space(9)
        open_setup(engine, match)
        with mock.patch.object(engine, "spread_exempt_ids", return_value=ooze):
            prompt = prompts.PendingPrompt(
                kind=prompts.PromptKind.COACHING_HUB, ask="",
                side=HOME, options=hub_options(engine, game, match),
            )
        action = DinkyAI(engine.player_catalog, engine.maneuver_catalog).choose(
            prompt, game, match, HOME,
        )
        self.assertEqual(action.choice, "arrange")
        with mock.patch.object(engine, "spread_exempt_ids", return_value=ooze):
            run = driver.apply(engine, game, match, action)
        self.assertNotIsInstance(run, driver.Refusal)
        self.assertNotEqual(space_of(match, defender), (Zone.HOME_ZONE, 0))
        self.assertEqual(match.unique_space_sharers(HOME, ooze), [])

    def test_one_point_oh_has_nobody_to_move(self) -> None:
        _, _, match = kickoff(Edition.ONE, 9)
        self.assertEqual(match.unique_space_sharers(HOME), [])


class ZoneAssignmentTests(unittest.TestCase):
    """The model's trade of two 2.0 roles, in the same zone too -- no
    longer offered in a Coaching Choice (4.6), where a rearrangement's
    trade does it."""

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

    def test_two_point_oh_is_moved_by_rearranging_alone(self) -> None:
        # 4.6, the author, 2026-10-25: no zone assignment and no space
        # positioning; a rearrangement's trades and moves cover both.
        engine, game, match = kickoff(Edition.TWO, 9)
        options = hub_options(engine, game, match)
        self.assertIsNotNone(options.arrangement)
        self.assertEqual(options.swaps, ())
        self.assertEqual(options.repositions, ())

    def test_two_point_oh_refuses_a_swap_and_a_reposition(self) -> None:
        engine, game, match = kickoff(Edition.TWO, 9)
        open_setup(engine, match)
        fullback = fielded(match, PlayerRole.FULLBACK)
        defender = fielded(match, PlayerRole.DEFENDER)
        before = match.to_dict()
        for choice, arguments in (
            ("swap", {"player_id": fullback, "other_player_id": defender}),
            ("reposition", {"player_id": defender, "space_index": 1}),
        ):
            with self.subTest(choice=choice):
                refused = driver.apply(engine, game, match, driver.Action(
                    prompts.PromptKind.COACHING_HUB, choice,
                    {"side": "home", **arguments},
                ))
                self.assertIsInstance(refused, driver.Refusal)
        self.assertEqual(match.to_dict(), before)

    def test_dinky_stands_a_playmaker_back_on_the_kickoff_space(self) -> None:
        engine, game, match = kickoff(Edition.TWO, 9)
        open_setup(engine, match)
        playmaker = fielded(match, PlayerRole.PLAYMAKER)
        kickoff_space = space_of(match, playmaker)
        match.board.place_meeple(playmaker, Zone.HOME_ZONE, 1)
        options = hub_options(engine, game, match)
        self.assertIsNotNone(options.finish_refusal)
        prompt = prompts.PendingPrompt(
            kind=prompts.PromptKind.COACHING_HUB, ask="",
            side=HOME, options=options,
        )
        action = DinkyAI(engine.player_catalog, engine.maneuver_catalog).choose(
            prompt, game, match, HOME,
        )
        self.assertEqual(action.choice, "arrange")
        self.assertNotIsInstance(
            driver.apply(engine, game, match, action), driver.Refusal,
        )
        self.assertEqual(space_of(match, playmaker), kickoff_space)
        self.assertIsNone(engine.coaching_finish_refusal(match, HOME, game))

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


def arrangement(holders: dict, placed: list) -> dict:
    """An arrangement as the hub sends it: the roles by name, and each
    placement as `[player, zone, space_index]`."""
    return {
        **holders,
        "placed": [
            {"player_id": player, "zone": zone.value, "space_index": index}
            for player, zone, index in placed
        ],
    }


def open_setup(engine, match, side: TeamSide = HOME) -> None:
    """Open setup's Coaching Choice on `side`, as kickoff does."""
    match.open_coaching_window(
        side,
        CoachingOccasion.SETUP,
        formation=engine.shape_name(match, side),
    )


class ArrangementTests(unittest.TestCase):
    """A 2.0 side has no formations: its coach names the Fullback, the
    Playmaker and the Striker, and places three more anywhere they may
    stand, each taking their zone's standard role (docs/rules-2.0.md
    4.3, the author, 2026-10-24)."""

    def unique_cards(self, match) -> dict:
        return {
            role.value: fielded(match, role)
            for role in (
                PlayerRole.FULLBACK, PlayerRole.PLAYMAKER, PlayerRole.STRIKER,
            )
        }

    def test_two_point_oh_offers_an_arrangement_and_no_formations(
        self,
    ) -> None:
        engine, game, match = kickoff(Edition.TWO, 9)
        options = hub_options(engine, game, match)
        self.assertEqual(options.formations, ())
        self.assertIsNotNone(options.arrangement)
        self.assertEqual(
            [space.takes for space in options.arrangement.unique],
            [PlayerRole.FULLBACK, PlayerRole.PLAYMAKER, PlayerRole.STRIKER],
        )
        self.assertEqual(len(options.arrangement.spaces), 9)

    def test_one_point_oh_offers_formations_and_no_arrangement(self) -> None:
        engine, game, match = kickoff(Edition.ONE, 9)
        options = hub_options(engine, game, match)
        self.assertTrue(options.formations)
        self.assertIsNone(options.arrangement)

    def test_setup_arranges_from_the_squad_and_play_from_the_six(
        self,
    ) -> None:
        engine, _, match = kickoff(Edition.TWO, 9)
        open_setup(engine, match)
        self.assertEqual(len(match.arrangement_pool(HOME)), 9)
        match.close_coaching_window()
        match.open_coaching_window(HOME, CoachingOccasion.HALFTIME)
        self.assertEqual(
            match.arrangement_pool(HOME), match.home.field_players,
        )

    def test_an_arrangement_makes_its_own_shape(self) -> None:
        engine, game, match = kickoff(Edition.TWO, 9)
        open_setup(engine, match)
        holders = self.unique_cards(match)
        others = [
            card for card in match.home.field_players
            if card not in holders.values()
        ]
        engine.apply_arrangement(game, match, HOME, holders, [
            (others[0], Zone.HOME_ZONE, 1),
            (others[1], Zone.HOME_ZONE, 2),
            (others[2], Zone.VISITORS_ZONE, 0),
        ])
        self.assertEqual(engine.shape_name(match, HOME), "3-1-2")
        self.assertIsNone(engine.current_formation(match, HOME))
        for role, card in holders.items():
            self.assertEqual(engine.role_of(match, card), PlayerRole(role))
        self.assertEqual(space_of(match, holders["fullback"]), (Zone.HOME_ZONE, 0))
        self.assertEqual(
            space_of(match, holders["playmaker"]),
            (Zone.MIDFIELD, match.kickoff_space_for(HOME)),
        )
        self.assertEqual(space_of(match, holders["striker"]), (Zone.VISITORS_ZONE, 2))
        self.assertEqual(engine.role_of(match, others[0]), PlayerRole.DEFENDER)
        self.assertEqual(engine.role_of(match, others[1]), PlayerRole.DEFENDER)
        self.assertEqual(engine.role_of(match, others[2]), PlayerRole.WINGER)

    def test_board_ten_reaches_a_shape_no_formation_had(self) -> None:
        engine, game, match = kickoff(Edition.TWO, 10)
        open_setup(engine, match)
        holders = self.unique_cards(match)
        others = [
            card for card in match.home.field_players
            if card not in holders.values()
        ]
        kickoff_space = match.kickoff_space_for(HOME)
        free = [
            index for index in range(4) if index != kickoff_space
        ]
        engine.apply_arrangement(game, match, HOME, holders, [
            (card, Zone.MIDFIELD, index) for card, index in zip(others, free)
        ])
        self.assertEqual(engine.shape_name(match, HOME), "1-4-1")
        self.assertEqual(
            [engine.role_of(match, card) for card in others],
            [PlayerRole.MIDFIELDER] * 3,
        )

    def test_setup_brings_the_bench_on(self) -> None:
        engine, game, match = kickoff(Edition.TWO, 9)
        open_setup(engine, match)
        holders = self.unique_cards(match)
        bench = list(match.home.team_board.bench)
        left_out = [
            card for card in match.home.field_players
            if card not in holders.values()
        ]
        engine.apply_arrangement(game, match, HOME, holders, [
            (bench[0], Zone.HOME_ZONE, 1),
            (bench[1], Zone.MIDFIELD, 0),
            (bench[2], Zone.VISITORS_ZONE, 1),
        ])
        self.assertEqual(
            sorted(match.home.team_board.bench), sorted(left_out),
        )
        self.assertEqual(match.home.team_board.back_bench, [])
        self.assertEqual(len(match.pending_coaching_swaps), 3)
        self.assertEqual(engine.shape_name(match, HOME), "2-2-2")

    def test_nobody_but_an_ooze_shares_a_space(self) -> None:
        engine, game, match = kickoff(Edition.TWO, 9)
        open_setup(engine, match)
        holders = self.unique_cards(match)
        others = [
            card for card in match.home.field_players
            if card not in holders.values()
        ]
        for placed in (
            # Onto the Fullback's space.
            [(others[0], Zone.HOME_ZONE, 0), (others[1], Zone.HOME_ZONE, 1),
             (others[2], Zone.HOME_ZONE, 2)],
            # Two onto one space.
            [(others[0], Zone.HOME_ZONE, 1), (others[1], Zone.HOME_ZONE, 1),
             (others[2], Zone.HOME_ZONE, 2)],
        ):
            before = match.to_dict()
            with self.subTest(placed=placed):
                with self.assertRaises(RuleRefusal):
                    match.arrange_side(HOME, holders, placed)
                self.assertEqual(match.to_dict(), before)

        ooze = {others[0]}
        # An Ooze shares, but no zone holds more players than spaces:
        # with the Fullback and the Ooze on one space, a third player
        # is a fourth in the three-space zone.
        before = match.to_dict()
        with self.assertRaises(RuleRefusal):
            match.arrange_side(HOME, holders, [
                (others[0], Zone.HOME_ZONE, 0),
                (others[1], Zone.HOME_ZONE, 1),
                (others[2], Zone.HOME_ZONE, 2),
            ], spread_exempt_ids=ooze)
        self.assertEqual(match.to_dict(), before)

        match.arrange_side(HOME, holders, [
            (others[0], Zone.HOME_ZONE, 0),
            (others[1], Zone.HOME_ZONE, 1),
            (others[2], Zone.MIDFIELD, 0),
        ], spread_exempt_ids=ooze)
        self.assertEqual(space_of(match, others[0]), (Zone.HOME_ZONE, 0))
        self.assertEqual(engine.role_of(match, others[0]), PlayerRole.DEFENDER)
        self.assertEqual(
            engine.role_of(match, holders["fullback"]), PlayerRole.FULLBACK,
        )

    def test_the_options_start_from_the_side_as_it_stands(self) -> None:
        engine, game, match = kickoff(Edition.TWO, 9)
        options = hub_options(engine, game, match).arrangement
        self.assertEqual(dict(options.holders), self.unique_cards(match))
        for role in (
            PlayerRole.DEFENDER, PlayerRole.MIDFIELDER, PlayerRole.WINGER,
        ):
            card = fielded(match, role)
            self.assertIn((card, *space_of(match, card)), options.placed)
            self.assertEqual(options.standing_of(card).takes, role)
        self.assertIsNone(options.refusal(options.holders, options.placed))

    def test_every_change_offered_is_one_the_match_accepts(self) -> None:
        for board_size in (7, 9, 10):
            engine, game, match = kickoff(Edition.TWO, board_size)
            open_setup(engine, match)
            options = hub_options(engine, game, match).arrangement
            for player in options.fielded:
                for edit in options.edits(player):
                    trial = MatchState.from_dict(
                        match.to_dict(), engine.basic_ruleset,
                    )
                    with self.subTest(
                        board=board_size, player=player, kind=edit.kind,
                        other=edit.other, space=edit.space,
                    ):
                        engine.apply_arrangement(
                            game, trial, HOME, dict(edit.holders),
                            list(edit.placed),
                        )
                        after = dict(trial.current_arrangement(HOME)[0])
                        self.assertEqual(after, dict(edit.holders))

    def test_a_move_leaves_everybody_else_where_they_stand(self) -> None:
        engine, game, match = kickoff(Edition.TWO, 9)
        options = hub_options(engine, game, match).arrangement
        defender = fielded(match, PlayerRole.DEFENDER)
        before = {
            card: space_of(match, card)
            for card in options.fielded if card != defender
        }
        move = next(
            edit for edit in options.edits(defender)
            if edit.kind == "move" and edit.space.zone == Zone.MIDFIELD
        )
        engine.apply_arrangement(
            game, match, HOME, dict(move.holders), list(move.placed),
        )
        self.assertEqual(
            {card: space_of(match, card) for card in before}, before,
        )
        self.assertEqual(engine.role_of(match, defender), PlayerRole.MIDFIELDER)
        self.assertEqual(engine.shape_name(match, HOME), "1-3-2")

    def test_a_trade_swaps_places_and_roles(self) -> None:
        engine, game, match = kickoff(Edition.TWO, 9)
        options = hub_options(engine, game, match).arrangement
        fullback = fielded(match, PlayerRole.FULLBACK)
        winger = fielded(match, PlayerRole.WINGER)
        spots = (space_of(match, fullback), space_of(match, winger))
        trade = next(
            edit for edit in options.edits(fullback)
            if edit.kind == "trade" and edit.other == winger
        )
        engine.apply_arrangement(
            game, match, HOME, dict(trade.holders), list(trade.placed),
        )
        self.assertEqual(engine.role_of(match, winger), PlayerRole.FULLBACK)
        self.assertEqual(engine.role_of(match, fullback), PlayerRole.WINGER)
        self.assertEqual(
            (space_of(match, winger), space_of(match, fullback)), spots,
        )

    def test_the_bench_is_offered_only_before_kickoff(self) -> None:
        engine, game, match = kickoff(Edition.TWO, 9)
        striker = fielded(match, PlayerRole.STRIKER)
        open_setup(engine, match)
        setup = hub_options(engine, game, match).arrangement
        self.assertEqual(
            sum(edit.kind == "replace" for edit in setup.edits(striker)), 3,
        )
        match.close_coaching_window()
        match.open_coaching_window(HOME, CoachingOccasion.HALFTIME)
        halftime = hub_options(engine, game, match).arrangement
        self.assertFalse(
            any(edit.kind == "replace" for edit in halftime.edits(striker)),
        )

    def test_an_ooze_shares_but_never_overfills_a_zone(self) -> None:
        engine, game, match = kickoff(Edition.TWO, 7)
        defender = fielded(match, PlayerRole.DEFENDER)
        with mock.patch.object(
            type(engine), "spreadable_among", return_value={defender},
        ):
            options = hub_options(engine, game, match).arrangement
        moves = {
            (edit.space.zone, edit.space.space_index)
            for edit in options.edits(defender) if edit.kind == "move"
        }
        # Board 7's Home Zone is two spaces, the Fullback and the
        # Defender: the Ooze may share the Fullback's, and anywhere with
        # room elsewhere, but no third player goes into a full zone.
        self.assertIn(space_of(match, fielded(match, PlayerRole.FULLBACK)), moves)
        midfielder = fielded(match, PlayerRole.MIDFIELDER)
        winger = fielded(match, PlayerRole.WINGER)
        self.assertIn(space_of(match, midfielder), moves)
        self.assertNotIn(space_of(match, winger), {
            (edit.space.zone, edit.space.space_index)
            for edit in options.edits(midfielder) if edit.kind == "move"
        })

    def test_the_driver_answers_an_arrangement_and_refuses_a_formation(
        self,
    ) -> None:
        engine, game, match = kickoff(Edition.TWO, 9)
        open_setup(engine, match)
        holders = self.unique_cards(match)
        others = [
            card for card in match.home.field_players
            if card not in holders.values()
        ]
        refused = driver.apply(engine, game, match, driver.Action(
            prompts.PromptKind.COACHING_HUB, "formation",
            {"side": "home", "formation": Formation.TWO_THREE_ONE.value},
        ))
        self.assertIsInstance(refused, driver.Refusal)
        run = driver.apply(engine, game, match, driver.Action(
            prompts.PromptKind.COACHING_HUB, "arrange",
            {"side": "home", "arrangement": arrangement(holders, [
                (others[0], Zone.MIDFIELD, 0),
                (others[1], Zone.MIDFIELD, 2),
                (others[2], Zone.VISITORS_ZONE, 0),
            ])},
        ))
        self.assertNotIsInstance(run, driver.Refusal)
        self.assertEqual(engine.shape_name(match, HOME), "1-3-2")
        self.assertIn(
            "Formation: **2-2-2 → 1-3-2**.",
            windows.coaching_summary(engine, match, HOME),
        )


if __name__ == "__main__":
    unittest.main()

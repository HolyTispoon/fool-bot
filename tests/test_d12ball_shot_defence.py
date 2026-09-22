"""
What a score attempt is up against.

A defender sharing the ball's space is worth their whole defensive
skill; anyone else between the ball and the goal is worth half of it,
rounded up, per player rather than over the group's total. See "Score
attempt" in docs/living-rules.md and ShotDefender in
d12ball/components.py.

Three things read that value and none of them may sum raw skills: the
roll (ScoreAttemptView.roll), the composition image
(D12Ball.build_score_attempt_file), and the dice image's detail lines.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

from cogs.d12ball import D12Ball
from cogs.d12ball_views import ScoreAttemptView
from d12ball.components import (
    MatchState,
    PlayerDefinition,
    PlayerRole,
    ShotDefender,
    TeamSide,
    Zone,
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
)
from d12ball.engine import RulesEngine
from d12ball.game import D12BallGame, Team
from d12ball.render import (
    TEAM_COLORS,
    ChallengeSide,
    group_text_lines,
    render_score_attempt,
)
from save_patches import suppressed_cog_saves
from cog_steps import start_set_up_shot


def build_cog() -> D12Ball:
    cog = object.__new__(D12Ball)
    cog.games = {}
    cog.player_catalog = load_player_catalog()
    cog.maneuver_catalog = load_maneuver_catalog()
    cog.basic_ruleset = load_basic_ruleset()
    cog.engine = RulesEngine(
        cog.player_catalog, cog.basic_ruleset, cog.maneuver_catalog, {},
    )
    cog.refresh_match_image = mock.AsyncMock()
    cog.begin_run_back = mock.AsyncMock()
    return cog


def build_game() -> D12BallGame:
    return D12BallGame(
        game_id="g1",
        game_number=1,
        guild_id=1,
        channel_id=1,
        message_id=None,
        player_1_id=111,
        player_2_id=222,
        player_1_name="One",
        player_2_name="Two",
        player_1_team=Team.ORANGE,
        player_2_team=Team.PURPLE,
        home_player_number=1,
        visiting_player_number=2,
    )


def build_interaction() -> SimpleNamespace:
    return SimpleNamespace(
        user=SimpleNamespace(id=111, display_name="One"),
        channel=SimpleNamespace(
            send=mock.AsyncMock(return_value=SimpleNamespace(id=999)),
        ),
        guild=None,
        followup=SimpleNamespace(
            send=mock.AsyncMock(return_value=SimpleNamespace(id=999)),
        ),
        response=SimpleNamespace(
            defer=mock.AsyncMock(),
            edit_message=mock.AsyncMock(),
            send_message=mock.AsyncMock(),
            is_done=lambda: True,
        ),
        edit_original_response=mock.AsyncMock(),
    )


def a_player(name: str) -> PlayerDefinition:
    """
    A defender built here rather than read out of the catalog: these
    tests are about the arithmetic ShotDefender does, and the skill is
    passed in beside the player rather than taken off them.

    **The names are deliberately off the roster.** A synthetic fixture
    carrying a real player's name is not looked up and so cannot break
    when that player is renamed -- but it reads as a roster reference,
    and the next rename sends somebody chasing it. See "The test suite"
    in docs/design/testing.md.
    """
    return PlayerDefinition(
        player_id=f"teal_{name.lower().replace(' ', '_')}",
        name=name,
        role=PlayerRole.DEFENDER,
        stat_overrides={},
    )


class ShotDefenderValueTests(unittest.TestCase):
    def test_the_ball_space_is_worth_the_whole_skill(self) -> None:
        for defense in range(1, 7):
            with self.subTest(defense=defense):
                self.assertEqual(
                    ShotDefender(a_player("Defender A"), defense, True).value,
                    defense,
                )

    def test_everyone_else_is_worth_half_rounded_up(self) -> None:
        # Rounded up, so an odd skill keeps the better half and a
        # defensive skill of 1 never rounds away to nothing.
        expected = {1: 1, 2: 1, 3: 2, 4: 2, 5: 3, 6: 3}
        for defense, value in expected.items():
            with self.subTest(defense=defense):
                self.assertEqual(
                    ShotDefender(a_player("Defender B"), defense, False).value,
                    value,
                )

    def test_halving_is_per_player_and_not_over_the_total(self) -> None:
        # Two 5s in the way add 3 + 3, where halving their sum would
        # give 5. The two readings only agree when at most one defender
        # rounds up, which is why this is worth its own test.
        in_the_way = [
            ShotDefender(a_player("Defender A"), 5, False),
            ShotDefender(a_player("Defender B"), 5, False),
        ]
        self.assertEqual(sum(d.value for d in in_the_way), 6)


class InterveningDefenderTests(unittest.TestCase):
    """The cog's reading of the board, against a real standard deal."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()

    def build_match(self) -> MatchState:
        return MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=7,
            home_team=Team.ORANGE,
            visiting_team=Team.TEAL,
        )

    def test_only_the_ball_space_keeps_its_whole_skill(self) -> None:
        cog = build_cog()
        match = self.build_match()
        match.ball.zone = Zone.MIDFIELD
        match.ball.space_index = 1

        defenders = cog.engine.intervening_defenders(match)

        self.assertEqual(
            [defender.on_ball for defender in defenders],
            [True] + [False] * (len(defenders) - 1),
        )
        self.assertEqual(defenders[0].value, defenders[0].defense)
        for defender in defenders[1:]:
            self.assertEqual(
                defender.value, -(-defender.defense // 2),
            )

    def test_a_shot_at_an_empty_path_faces_nobody(self) -> None:
        cog = build_cog()
        match = self.build_match()
        match.ball.zone = Zone.VISITORS_GOAL
        match.ball.space_index = 1
        for player_id in list(match.visiting.field_players):
            match.move_meeple(player_id, Zone.HOME_GOAL, 0)

        self.assertEqual(cog.engine.intervening_defenders(match), [])


class ShotRollTests(unittest.IsolatedAsyncioTestCase):
    """The total the defence actually rolls against, and what it says."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()

    def build_shot(self, cog: D12Ball, defenders: list[ShotDefender]):
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=7,
            home_team=Team.ORANGE,
            visiting_team=Team.PURPLE,
        )
        match.active_player_id = match.setup_for_side(
            match.ball.possession
        ).field_players[0]
        match.move_meeple(
            match.active_player_id, match.ball.zone, match.ball.space_index,
        )
        match.pending_action = "shoot"
        cog.engine.intervening_defenders = mock.Mock(return_value=defenders)
        game = build_game()
        game.match_state = match.to_dict()
        cog.games[game.game_id] = game
        return game, match

    async def roll(self, cog: D12Ball, game: D12BallGame, rolls: list[int]):
        """Roll the shot, and hand back what the dice image was told."""
        interaction = build_interaction()
        view = ScoreAttemptView(cog, game.game_id)
        with suppressed_cog_saves(), mock.patch(
            "random.Random.randint", side_effect=rolls,
        ), mock.patch(
            "cogs.d12ball_views.base.render_skill_test_dice",
        ) as dice, mock.patch("discord.File"):
            await view.roll(interaction)
        return dice.call_args.args[0][1]

    async def test_the_defence_totals_the_halved_values(self) -> None:
        # 6 on the ball and 5 + 2 in the way is 6 + 3 + 1, not 13.
        cog = build_cog()
        game, _ = self.build_shot(
            cog,
            [
                ShotDefender(a_player("Defender A"), 6, True),
                ShotDefender(a_player("Defender B"), 5, False),
                ShotDefender(a_player("Defender C"), 2, False),
            ],
        )

        _, _, _, detail, total, _, _ = await self.roll(cog, game, [12, 1])

        self.assertEqual(total, 1 + 10)
        self.assertIn("Total defensive skill +10", detail)

    async def test_a_halved_defender_says_what_it_was_halved_from(
        self,
    ) -> None:
        # A bare "+3" beside a card showing 5 reads as a bug.
        cog = build_cog()
        game, _ = self.build_shot(
            cog,
            [
                ShotDefender(a_player("Defender A"), 6, True),
                ShotDefender(a_player("Defender B"), 5, False),
            ],
        )

        _, _, _, detail, total, _, _ = await self.roll(cog, game, [12, 1])

        self.assertIn("Defender A [DD] +6", detail)
        self.assertIn("Defender B [DD] +3 (half of 5)", detail)
        self.assertEqual(total, 1 + 9)


class ShotClockCostTests(unittest.IsolatedAsyncioTestCase):
    """
    The score attempt's own flat clock cost (2026-08-16), and how it
    stacks with the maneuver that offered a set-up rather than
    replacing it -- see `MatchState.pending_shot_setup_cost` and
    "When a maneuver includes a setup" in docs/rules-log.md.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()

    build_shot = ShotRollTests.build_shot
    roll = ShotRollTests.roll

    async def test_an_ordinary_shot_costs_its_flat_minute(self) -> None:
        cog = build_cog()
        game, match = self.build_shot(cog, [])
        self.assertFalse(match.pending_shot_is_set_up)
        self.assertEqual(match.pending_shot_setup_cost, 0)

        await self.roll(cog, game, [1, 1])

        cog.begin_run_back.assert_awaited_once()
        _, kwargs = cog.begin_run_back.call_args
        self.assertEqual(kwargs["distance_moved"], 1)

    async def test_a_setup_shot_stacks_on_top_of_the_makers_cost(
        self,
    ) -> None:
        # A High Pass's own flat cost is 2; taking the set-up shot it
        # offers costs that plus the shot's own 1, not one or the
        # other.
        cog = build_cog()
        game, match = self.build_shot(cog, [])
        match.pending_shot_is_set_up = True
        match.pending_shot_setup_cost = 2
        game.match_state = match.to_dict()

        await self.roll(cog, game, [1, 1])

        cog.begin_run_back.assert_awaited_once()
        _, kwargs = cog.begin_run_back.call_args
        self.assertEqual(kwargs["distance_moved"], 3)

    async def test_start_set_up_shot_defaults_to_the_flat_maneuver_cost(
        self,
    ) -> None:
        # Deflect's overshoot set-up (begin_shooter_choice) and
        # ShooterChoiceView never pass maneuver_cost -- Deflect
        # is always 1, so the default has to be too.
        cog = build_cog()
        game, match = self.build_shot(cog, [])
        cog.begin_score_attempt = mock.AsyncMock()
        shooter_id = match.active_player_id

        with suppressed_cog_saves():
            await start_set_up_shot(cog, 
                build_interaction(), game, match, shooter_id,
            )

        self.assertTrue(match.pending_shot_is_set_up)
        self.assertEqual(match.pending_shot_setup_cost, 1)

    async def test_start_set_up_shot_carries_a_high_pass_cost_of_two(
        self,
    ) -> None:
        # offer_scoring_attempt_choice's AI branch and
        # SetUpAttemptChoiceView.attempt both pass the maneuver's own
        # distance_moved through explicitly -- 2 for a High Pass.
        cog = build_cog()
        game, match = self.build_shot(cog, [])
        cog.begin_score_attempt = mock.AsyncMock()
        shooter_id = match.active_player_id

        with suppressed_cog_saves():
            await start_set_up_shot(cog, 
                build_interaction(), game, match, shooter_id,
                maneuver_cost=2,
            )

        self.assertEqual(match.pending_shot_setup_cost, 2)


class ShotImageTests(unittest.TestCase):
    """
    The composition image. It cannot be read back, so what is asserted
    is the text it is built from and that it renders at all -- see
    "Working on the board image" in docs/design/board-image.md.
    """

    def side(
        self, name: str, skill: int, contribution: int, halved: bool,
    ) -> ChallengeSide:
        return ChallengeSide(
            name=name,
            role="D",
            team_color=TEAM_COLORS[Team.TEAL],
            team_label="Teal",
            skill_name="Defensive",
            skill=skill,
            ability="",
            contribution=contribution,
            halved=halved,
        )

    def test_the_group_sums_contributions_not_skills(self) -> None:
        lines = group_text_lines(
            [
                self.side("Defender A", 6, 6, False),
                self.side("Defender B", 5, 3, True),
                self.side("Defender C", 2, 1, True),
            ],
            with_ability=False,
        )

        self.assertIn(
            "Defensive skill: 6 + 3 + 1 = 10",
            [text for text, _, _, _ in lines],
        )

    def test_a_lone_halved_defender_shows_where_it_came_from(self) -> None:
        lines = group_text_lines(
            [self.side("Defender B", 5, 3, True)], with_ability=False,
        )

        self.assertIn(
            "Defensive skill +3 (half of 5)",
            [text for text, _, _, _ in lines],
        )

    def test_a_lone_defender_on_the_ball_reads_as_it_always_did(
        self,
    ) -> None:
        lines = group_text_lines(
            [self.side("Defender A", 6, 6, False)], with_ability=False,
        )

        self.assertIn(
            "Defensive skill +6", [text for text, _, _, _ in lines],
        )

    def test_a_defensive_skill_of_one_still_reads_as_halved(self) -> None:
        # Halving 1 leaves 1, so the numbers alone cannot say which
        # band a defender is in -- only the flag can.
        lines = group_text_lines(
            [self.side("Defender A", 1, 1, True)], with_ability=False,
        )

        self.assertIn(
            "Defensive skill +1 (half of 1)",
            [text for text, _, _, _ in lines],
        )

    def test_the_image_renders_with_both_bands(self) -> None:
        shooter = ChallengeSide(
            name="Shooter",
            role="S",
            team_color=TEAM_COLORS[Team.ORANGE],
            team_label="Orange",
            skill_name="Offensive",
            skill=6,
            ability="+3 for scoring off setup",
            modifiers=("+1 ball speed (3)",),
        )

        image = render_score_attempt(
            shooter,
            [
                self.side("Defender A", 6, 6, False),
                self.side("Defender B", 5, 3, True),
            ],
            location="V1 → Teal goal",
        )

        self.assertTrue(image.getvalue().startswith(b"\x89PNG"))

    def test_an_open_goal_still_renders(self) -> None:
        shooter = ChallengeSide(
            name="Shooter",
            role="S",
            team_color=TEAM_COLORS[Team.ORANGE],
            team_label="Orange",
            skill_name="Offensive",
            skill=6,
            ability="+3 for scoring off setup",
        )

        image = render_score_attempt(shooter, [], location="V1 → Teal goal")

        self.assertTrue(image.getvalue().startswith(b"\x89PNG"))


if __name__ == "__main__":
    unittest.main()

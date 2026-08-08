"""
Where a result is announced relative to the dice that decided it.

Discord renders a message's attachments *below* its content, so a
verdict written into the message the dice image is attached to is read
before the roll it is announcing. Every one of these results therefore
leaves the roll's arithmetic on the dice message and posts the verdict
as the message after it: skill tests, goals, and missed attempts.

The tie is the exception -- its message also carries the roll-again
button, so its text stays with it. See SkillTestView.roll and
ScoreAttemptView.roll in cogs/d12ball_views.py.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

from cogs.d12ball import D12Ball
from cogs.d12ball_views import ScoreAttemptView, SkillTestView
from d12ball.components import (
    MatchState,
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
)
from d12ball.game import D12BallGame, Team


def build_cog() -> D12Ball:
    cog = object.__new__(D12Ball)
    cog.games = {}
    cog.player_catalog = load_player_catalog()
    cog.maneuver_catalog = load_maneuver_catalog()
    cog.basic_ruleset = load_basic_ruleset()
    cog.team_emojis = {}
    cog.condition_emojis = {}
    cog.refresh_match_image = mock.AsyncMock()
    cog.run_injury_test = mock.AsyncMock()
    cog.begin_effect_resolution = mock.AsyncMock()
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
        channel=None,
        guild=None,
        followup=SimpleNamespace(
            send=mock.AsyncMock(return_value=SimpleNamespace(id=999)),
        ),
        response=SimpleNamespace(
            defer=mock.AsyncMock(),
            edit_message=mock.AsyncMock(),
            send_message=mock.AsyncMock(),
        ),
        edit_original_response=mock.AsyncMock(),
    )


def sent_texts(interaction: SimpleNamespace) -> list[str]:
    """The content of every follow-up message, in the order sent."""
    return [
        call.args[0]
        for call in interaction.followup.send.await_args_list
        if call.args
    ]


class AnnouncementOrderTests(unittest.IsolatedAsyncioTestCase):
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
            visiting_team=Team.PURPLE,
        )

    # -- Skill test ----------------------------------------------------

    def build_skill_test(self, cog: D12Ball):
        match = self.build_match()
        game = build_game()
        match.active_player_id = match.setup_for_side(
            match.ball.possession
        ).field_players[0]
        match.challenger_id = match.setup_for_side(
            match.defending_side()
        ).field_players[0]
        for offense in (m.name for m in cog.maneuver_catalog.offense):
            for defense in (m.name for m in cog.maneuver_catalog.defense):
                if cog.maneuver_catalog.resolve(offense, defense) == "tie":
                    match.offense_maneuver = offense
                    match.defense_maneuver = defense
                    break
        game.match_state = match.to_dict()
        cog.games[game.game_id] = game
        return game, match

    async def test_the_skill_test_winner_is_announced_after_the_dice(
        self,
    ) -> None:
        cog = build_cog()
        game, match = self.build_skill_test(cog)
        interaction = build_interaction()

        view = SkillTestView(cog, game.game_id)
        with mock.patch("cogs.d12ball_views.save_games"), mock.patch(
            "cogs.d12ball_views.random.randint", side_effect=[12, 1],
        ), mock.patch("cogs.d12ball_views.render_skill_test_dice"), mock.patch(
            "cogs.d12ball_views.discord.File",
        ):
            await view.roll(interaction)

        dice_message = interaction.edit_original_response.await_args.kwargs
        self.assertNotIn("wins the skill test", dice_message["content"])
        self.assertIn(
            f"**{match.offense_maneuver}** wins the skill test!",
            sent_texts(interaction)[0],
        )

    # -- Maneuver won outright -----------------------------------------

    async def test_a_maneuver_won_outright_is_headed_and_names_nobody(
        self,
    ) -> None:
        # The other way a maneuver is won -- one action beating the
        # other, no skill test -- gets the same heading a won skill
        # test does, and stops at the result. It used to trail
        # "<@id> (Orange) resolves the effect:", which named someone
        # who is either prompted by name a moment later or has nothing
        # to decide at all.
        cog = build_cog()
        match = self.build_match()
        game = build_game()
        cog.games[game.game_id] = game
        match.active_player_id = match.setup_for_side(
            match.ball.possession
        ).field_players[0]
        match.challenger_id = match.setup_for_side(
            match.defending_side()
        ).field_players[0]
        winner = None
        for offense in (m.name for m in cog.maneuver_catalog.offense):
            for defense in (m.name for m in cog.maneuver_catalog.defense):
                if cog.maneuver_catalog.resolve(offense, defense) == "offense":
                    match.offense_maneuver = offense
                    match.defense_maneuver = defense
                    winner = offense
                    break
        game.match_state = match.to_dict()
        interaction = build_interaction()

        with mock.patch("cogs.d12ball.save_games"):
            await cog.resolve_maneuver(interaction, game, match)

        announcement = sent_texts(interaction)[0]
        self.assertIn(f"## **{winner}** wins!", announcement)
        self.assertNotIn("resolves the effect", announcement)
        self.assertNotIn("<@", announcement)
        cog.begin_effect_resolution.assert_awaited_once()

    # -- Score attempt -------------------------------------------------

    def build_score_attempt(self, cog: D12Ball):
        # Nobody in the way, so the two dice alone decide the attempt
        # and a 12 against a 1 is a goal either way round.
        cog.intervening_defenders = mock.Mock(return_value=[])
        match = self.build_match()
        game = build_game()
        match.active_player_id = match.setup_for_side(
            match.ball.possession
        ).field_players[0]
        match.move_meeple(
            match.active_player_id, match.ball.zone, match.ball.space_index,
        )
        match.pending_action = "shoot"
        game.match_state = match.to_dict()
        cog.games[game.game_id] = game
        return game, match

    async def roll_score_attempt(self, cog, game, rolls) -> SimpleNamespace:
        interaction = build_interaction()
        view = ScoreAttemptView(cog, game.game_id)
        with mock.patch("cogs.d12ball_views.save_games"), mock.patch(
            "cogs.d12ball_views.random.randint", side_effect=rolls,
        ), mock.patch("cogs.d12ball_views.render_skill_test_dice"), mock.patch(
            "cogs.d12ball_views.discord.File",
        ):
            await view.roll(interaction)
        return interaction

    async def test_a_goal_is_announced_after_the_dice(self) -> None:
        cog = build_cog()
        game, _ = self.build_score_attempt(cog)

        interaction = await self.roll_score_attempt(cog, game, [12, 1])

        dice_message = interaction.response.edit_message.await_args.kwargs
        self.assertNotIn("GOAL!", dice_message["content"])
        self.assertIn("# GOAL!", sent_texts(interaction)[0])

    async def test_the_scorer_s_portrait_follows_the_goal(self) -> None:
        cog = build_cog()
        game, _ = self.build_score_attempt(cog)

        interaction = await self.roll_score_attempt(cog, game, [12, 1])

        calls = interaction.followup.send.await_args_list
        self.assertIn("# GOAL!", calls[0].args[0])
        self.assertIn("file", calls[1].kwargs)

    async def test_a_miss_is_announced_after_the_dice_and_shouts(
        self,
    ) -> None:
        cog = build_cog()
        game, _ = self.build_score_attempt(cog)

        # The shooter's offensive skill is still added to their roll,
        # so a 1 against a 12 is the pair that misses regardless of who
        # is shooting.
        interaction = await self.roll_score_attempt(cog, game, [1, 12])

        dice_message = interaction.response.edit_message.await_args.kwargs
        self.assertNotIn("Missed attempt", dice_message["content"])
        # Same heading level as a goal -- a miss is just as big a
        # moment for the side that avoided it.
        self.assertTrue(sent_texts(interaction)[0].startswith("# Missed"))

    # -- Own goal ------------------------------------------------------

    async def roll_own_goal(self, roll: int) -> tuple:
        cog = build_cog()
        cog.finish_maneuver_resolution = mock.AsyncMock()
        match = self.build_match()
        game = build_game()
        cog.games[game.game_id] = game

        match.active_player_id = match.setup_for_side(
            match.ball.possession
        ).field_players[0]
        match.move_meeple(
            match.active_player_id, match.ball.zone, match.ball.space_index,
        )
        game.match_state = match.to_dict()

        interaction = build_interaction()
        with mock.patch("cogs.d12ball.save_games"), mock.patch(
            "cogs.d12ball.random.randint", return_value=roll,
        ), mock.patch("cogs.d12ball.render_own_goal_dice"), mock.patch(
            "cogs.d12ball.discord.File",
        ):
            await cog.run_own_goal_roll(
                interaction, game, match, distance_moved=1,
            )
        return cog, interaction

    async def test_an_own_goal_is_announced_after_its_dice(self) -> None:
        _, interaction = await self.roll_own_goal(1)

        first, second = interaction.followup.send.await_args_list[:2]
        self.assertIn("file", first.kwargs)
        self.assertNotIn("Own goal!", first.args[0])
        self.assertIn("# Own goal!", second.args[0])

    async def test_avoiding_an_own_goal_is_announced_after_its_dice(
        self,
    ) -> None:
        _, interaction = await self.roll_own_goal(12)

        first, second = interaction.followup.send.await_args_list[:2]
        self.assertIn("file", first.kwargs)
        self.assertNotIn("avoided", first.args[0])
        self.assertIn("## Own goal avoided!", second.args[0])

    # -- Which turnovers open a substitution window ---------------------
    #
    # A goal, an own goal and a missed attempt all restart from a dead
    # ball, so all three are new plays. See "Steals and new plays" in
    # docs/living-rules.md.

    async def test_a_conceded_own_goal_is_a_new_play(self) -> None:
        cog, _ = await self.roll_own_goal(1)

        cog.begin_run_back.assert_awaited_once()
        self.assertTrue(cog.begin_run_back.await_args.kwargs["new_play"])

    async def test_a_goal_is_a_new_play(self) -> None:
        cog = build_cog()
        game, _ = self.build_score_attempt(cog)

        await self.roll_score_attempt(cog, game, [12, 1])

        cog.begin_run_back.assert_awaited_once()
        self.assertTrue(cog.begin_run_back.await_args.kwargs["new_play"])

    async def test_a_missed_attempt_is_a_new_play(self) -> None:
        cog = build_cog()
        game, _ = self.build_score_attempt(cog)

        await self.roll_score_attempt(cog, game, [1, 12])

        cog.begin_run_back.assert_awaited_once()
        self.assertTrue(cog.begin_run_back.await_args.kwargs["new_play"])


if __name__ == "__main__":
    unittest.main()

"""
The challenge image and Glompex's offer (Law 21), on Discord.

The matchup image is what the coaches pick their cards over, and
Glompex may step onto the ball's space before the cards -- so while
that offer is outstanding the image waits, and it goes up once the
offer is answered (the author, 2026-09-28). The walk-in still goes up
where it did. `D12Ball.present` / `challenge_placement` place it.

Driven through the real cog: the offense's Maneuver click, a defender
already on the ball as the challenger, and the offer answered by a
coach's click or by the AI.
"""

import pathlib
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from cogs.d12ball_views import JoinTheBallView, PlayerActionView
from d12ball.components import TeamSide, catalog_player_id
from d12ball.game import AIOpponent, GameMode
from d12ball.personal_abilities import PERSONAL_ABILITIES, PersonalAbility
from d12ball.prompts import PromptKind
from save_patches import suppressed_cog_saves
from test_d12ball_challenger_choice import build_cog, build_game


def build_interaction(record: list, user_id: int = 111) -> SimpleNamespace:
    """An interaction whose every post is written into `record`, in
    order, beside the challenge image."""

    async def send(*args, **kwargs):
        view = kwargs.get("view")
        record.append(
            ("view", type(view).__name__) if view is not None
            else ("text", args[0] if args else kwargs.get("content", ""))
        )
        return SimpleNamespace(id=999)

    sender = mock.AsyncMock(side_effect=send)
    return SimpleNamespace(
        user=SimpleNamespace(id=user_id, display_name="One"),
        channel=SimpleNamespace(send=sender),
        guild=None,
        response=SimpleNamespace(
            defer=mock.AsyncMock(),
            edit_message=mock.AsyncMock(),
            send_message=mock.AsyncMock(),
            is_done=lambda: True,
        ),
        followup=SimpleNamespace(send=sender),
        message=SimpleNamespace(content="the turn prompt"),
    )


class JoinTheBallImageTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        # Nobody but the test's own joiner has an ability, so who is
        # fielded where decides nothing.
        cleared = mock.patch.dict(PERSONAL_ABILITIES, {}, clear=True)
        cleared.start()
        self.addCleanup(cleared.stop)

    def build(self, joiner_side: TeamSide, **game_overrides):
        """
        Home on the ball at flat space 3, one visiting defender on it
        -- the challenger, walked in for nothing -- and a joiner of
        `joiner_side` beside it at 2. Everybody else stands at 0.
        """
        cog = build_cog()
        # That fixture stubs the walk-in, which this test is about.
        del cog.auto_resolve_challenger
        cog.announce_maneuver_challenge = mock.AsyncMock()
        game = build_game(mode=GameMode.ADVANCED, **game_overrides)
        cog.games[game.game_id] = game
        match = cog.engine.initialize_standard_match(game)
        match.ball.possession = TeamSide.HOME

        home = match.home.field_players
        visiting = match.visiting.field_players
        handler, challenger = home[0], visiting[0]
        joiner = (home if joiner_side is TeamSide.HOME else visiting)[1]
        for player_id in home + visiting:
            match.move_meeple(
                player_id, *match.board.position_at_flat_index(0),
            )
        for player_id, flat in ((handler, 3), (challenger, 3), (joiner, 2)):
            match.move_meeple(
                player_id, *match.board.position_at_flat_index(flat),
            )
        match.set_ball_space(*match.board.position_at_flat_index(3))
        match.active_player_id = handler
        game.match_state = match.to_dict()

        self.ability = mock.patch.dict(
            PERSONAL_ABILITIES,
            {catalog_player_id(joiner): (PersonalAbility.JOINS_THE_BALL, "test")},
        )
        return cog, game, challenger, joiner

    def track_image(self, cog, record: list) -> None:
        """The challenge image and each prompt put up, into `record`
        beside the messages."""

        async def image(interaction, match, challenger_id, text, game=None):
            record.append(("image", challenger_id))

        async def prompt(interaction, game, match, pending, lead_in=""):
            if lead_in:
                record.append(("text", lead_in))
            record.append(("prompt", pending.kind))

        cog.announce_maneuver_challenge.side_effect = image
        cog.render_prompt = mock.AsyncMock(side_effect=prompt)

    async def maneuver(self, cog, game, record: list) -> None:
        view = PlayerActionView(cog, game.game_id)
        with suppressed_cog_saves():
            await view.choose_action(build_interaction(record), "maneuver")

    async def test_the_image_waits_for_the_coach_s_answer(self) -> None:
        cog, game, challenger, joiner = self.build(TeamSide.HOME)
        record = []
        self.track_image(cog, record)

        with self.ability:
            await self.maneuver(cog, game, record)

            self.assertNotIn(("image", challenger), record)
            self.assertIn(("prompt", PromptKind.JOIN_THE_BALL), record)

            record.clear()
            view = JoinTheBallView(cog, game.game_id, joiner)
            with suppressed_cog_saves():
                await view.accept(build_interaction(record))

        self.assertEqual(
            [entry for entry in record if entry[0] != "text"],
            [
                ("image", challenger),
                ("prompt", PromptKind.MANEUVER_ACTION),
            ],
        )

    async def test_the_image_goes_up_under_the_ai_s_answer(self) -> None:
        cog, game, challenger, _ = self.build(
            TeamSide.VISITING, player_2_id=None, ai_opponent=AIOpponent.DINKY,
        )
        record = []
        self.track_image(cog, record)

        with self.ability:
            await self.maneuver(cog, game, record)

        answered = next(
            index for index, entry in enumerate(record)
            if entry[0] == "text" and "stays where they are" in entry[1]
        )
        image = record.index(("image", challenger))
        self.assertGreater(image, answered)
        self.assertEqual(record.count(("image", challenger)), 1)
        self.assertEqual(
            record[-1], ("prompt", PromptKind.MANEUVER_ACTION),
        )

    async def test_without_an_offer_the_image_rides_on_the_walk_in(
        self,
    ) -> None:
        cog, game, challenger, _ = self.build(TeamSide.HOME)
        record = []
        self.track_image(cog, record)

        # No `self.ability`: nobody may join.
        await self.maneuver(cog, game, record)

        self.assertEqual(
            [entry for entry in record if entry[0] != "text"],
            [
                ("image", challenger),
                ("prompt", PromptKind.MANEUVER_ACTION),
            ],
        )


if __name__ == "__main__":
    unittest.main()

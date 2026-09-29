"""
The coin on the Discord maneuver prompt (Law 19.3).

- **"Gambit" is on the prompt for the hand whose coach holds the coin**,
  while nobody has declared one -- pressed by anybody else it answers
  with a refusal and changes nothing.
- **Declaring puts the pick up again**: the prompt that was answered is
  deleted and a new one posted, since both hands have changed.
- **"Confirm maneuver" is on the hand whose pick a gambit put back in
  question**, and the reply names the card to its own coach only.

The rules themselves are `tests/test_d12ball_gambits.py`'s; this is the
frontend over them.
"""

import unittest
from unittest import mock

from cogs.d12ball_views import ManeuverActionPromptView
from cogs.d12ball_views.turn import CONFIRM_BUTTON_LABEL, GAMBIT_BUTTON_LABEL
from d12ball.components import TeamSide
from d12ball.game import GameMode

from prompt_fixtures import challenge
from save_patches import suppressed_cog_saves
from test_d12ball_uncontested_maneuver import (
    build_cog,
    build_game,
    build_interaction,
)

HOME_COACH, VISITING_COACH = 111, 222


class CoinButtonTests(unittest.IsolatedAsyncioTestCase):
    def build(self):
        cog = build_cog()
        cog.present = mock.AsyncMock()
        cog.close_turn_prompt = mock.AsyncMock()
        game = build_game(mode=GameMode.ADVANCED)
        cog.games[game.game_id] = game
        match = cog.engine.initialize_standard_match(game)
        challenge(match)
        game.match_state = match.to_dict()
        return cog, game

    def labels(self, cog, game) -> list[tuple[str, str]]:
        view = ManeuverActionPromptView(cog, game.game_id)
        return [
            (item.label, item.custom_id)
            for item in view.children
            if item.label in (GAMBIT_BUTTON_LABEL, CONFIRM_BUTTON_LABEL)
        ]

    async def press_gambit(self, cog, game, user_id, side="offense"):
        interaction = build_interaction(user_id=user_id)
        with suppressed_cog_saves():
            await ManeuverActionPromptView(cog, game.game_id).declare_gambit(
                interaction, side,
            )
        return interaction

    def test_the_holder_s_hand_carries_the_gambit_button(self) -> None:
        cog, game = self.build()

        self.assertEqual(
            self.labels(cog, game),
            [(GAMBIT_BUTTON_LABEL, "d12ball:maneuver_gambit:g1:offense")],
        )

    def test_a_standard_game_has_no_coin_buttons(self) -> None:
        cog, game = self.build()
        game.mode = GameMode.STANDARD

        self.assertEqual(self.labels(cog, game), [])

    async def test_the_other_coach_is_refused_and_nothing_changes(
        self,
    ) -> None:
        cog, game = self.build()
        before = dict(game.match_state)

        interaction = await self.press_gambit(cog, game, VISITING_COACH)

        reply = interaction.response.send_message.await_args
        self.assertIn("holding the coin", reply.args[0])
        self.assertTrue(reply.kwargs["ephemeral"])
        self.assertEqual(game.match_state, before)
        cog.present.assert_not_awaited()

    async def test_the_holder_declares_and_the_prompt_is_put_up_again(
        self,
    ) -> None:
        cog, game = self.build()

        interaction = await self.press_gambit(cog, game, HOME_COACH)

        match = cog.engine.load_match_state(game)
        self.assertEqual(match.gambit_declared_by, "offense")
        self.assertEqual(match.coin_holder, TeamSide.VISITING)
        self.assertTrue(
            interaction.response.send_message.await_args.kwargs["ephemeral"]
        )
        cog.close_turn_prompt.assert_awaited_once()
        result = cog.present.await_args.args[2]
        self.assertEqual(result.prompt.kind.name, "MANEUVER_ACTION")
        # The coin has crossed, so the new prompt has no Gambit button.
        self.assertEqual(self.labels(cog, game), [])

    async def test_a_pick_put_in_question_gets_a_confirm_button(self) -> None:
        cog, game = self.build()
        pick = build_interaction(user_id=VISITING_COACH)
        with suppressed_cog_saves():
            await ManeuverActionPromptView(cog, game.game_id).pick(
                pick, "defense", "steal",
            )
        await self.press_gambit(cog, game, HOME_COACH)

        self.assertEqual(
            self.labels(cog, game),
            [(CONFIRM_BUTTON_LABEL, "d12ball:maneuver_confirm:g1:defense")],
        )

        confirm = build_interaction(user_id=VISITING_COACH)
        with suppressed_cog_saves():
            await ManeuverActionPromptView(cog, game.game_id).confirm(
                confirm, "defense",
            )
        reply = confirm.response.send_message.await_args
        self.assertEqual(
            reply.args[0],
            f"You confirmed **{cog.engine.maneuver_name('steal')}**.",
        )
        self.assertTrue(reply.kwargs["ephemeral"])
        match = cog.engine.load_match_state(game)
        self.assertIsNone(match.pick_unconfirmed)
        self.assertEqual(match.defense_maneuver, "steal")


if __name__ == "__main__":
    unittest.main()

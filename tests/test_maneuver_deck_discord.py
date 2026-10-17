"""
D12 Ball 2.0 on Discord: the public maneuver prompt carries no cards,
only a hand button a side; pressing it shows a coach their own four
cards, ephemerally, with the maneuvers they can play under it; and a
pick from there plays the card. The rules are `test_maneuver_deck`'s;
this is the frontend over them.
"""

import unittest
from unittest import mock

from cogs.d12ball_helpers import HAND_BUTTON_LABELS
from cogs.d12ball_views import ManeuverActionPromptView
from cogs.d12ball_views.turn import ManeuverHandView
from d12ball.components import TeamSide
from d12ball.game import Edition, GameMode
from d12ball.prompts import PromptKind

from prompt_fixtures import challenge
from save_patches import suppressed_cog_saves
from test_d12ball_uncontested_maneuver import (
    build_cog,
    build_game,
    build_interaction,
)

HOME_COACH, VISITING_COACH = 111, 222


class SecretHandTests(unittest.IsolatedAsyncioTestCase):
    def build(self):
        cog = build_cog()
        cog.present = mock.AsyncMock()
        cog.close_turn_prompt = mock.AsyncMock()
        cog.build_deck_hand_file = mock.AsyncMock(
            return_value=mock.sentinel.hand_file,
        )
        game = build_game(mode=GameMode.STANDARD, edition=Edition.TWO)
        cog.games[game.game_id] = game
        cog.engine.rng.seed(3)
        match = cog.engine.initialize_standard_match(game)
        challenge(match)
        game.match_state = match.to_dict()
        return cog, game

    def test_the_public_prompt_carries_a_hand_button_a_side_and_no_card(self) -> None:
        cog, game = self.build()
        view = ManeuverActionPromptView(cog, game.game_id)
        labels = [item.label for item in view.children]
        self.assertIn(HAND_BUTTON_LABELS["offense"], labels)
        self.assertIn(HAND_BUTTON_LABELS["defense"], labels)
        names = {maneuver.name for maneuver in cog.maneuver_catalog.offense
                 + cog.maneuver_catalog.defense}
        self.assertFalse(names & set(labels))

    async def test_a_coach_is_shown_their_own_hand_alone(self) -> None:
        cog, game = self.build()
        match = cog.engine.load_match_state(game)
        offense_team = TeamSide(match.ball.possession)
        offense_coach = (
            HOME_COACH if offense_team == TeamSide.HOME else VISITING_COACH
        )
        other_coach = VISITING_COACH if offense_coach == HOME_COACH else HOME_COACH

        refused = build_interaction(user_id=other_coach)
        await ManeuverActionPromptView(cog, game.game_id).show_hand(
            refused, "offense",
        )
        self.assertTrue(refused.response.send_message.await_args.kwargs["ephemeral"])
        refused.followup.send.assert_not_awaited()

        shown = build_interaction(user_id=offense_coach)
        await ManeuverActionPromptView(cog, game.game_id).show_hand(
            shown, "offense",
        )
        sent = shown.followup.send.await_args
        self.assertTrue(sent.kwargs["ephemeral"])
        self.assertIs(sent.kwargs["file"], mock.sentinel.hand_file)
        held = cog.build_deck_hand_file.await_args.args[0]
        self.assertEqual(
            tuple(held), cog.engine.maneuver_deck_hand(match, offense_team),
        )
        hand_view = sent.kwargs["view"]
        self.assertIsInstance(hand_view, ManeuverHandView)
        self.assertEqual(
            sorted(item.label for item in hand_view.children),
            sorted(m.name for m in cog.engine.maneuver_hand(game, match, "offense")),
        )

    async def test_both_picks_play_their_cards(self) -> None:
        cog, game = self.build()
        match = cog.engine.load_match_state(game)
        offense_team = TeamSide(match.ball.possession)
        coaches = {
            "offense": HOME_COACH if offense_team == TeamSide.HOME else VISITING_COACH,
        }
        coaches["defense"] = (
            VISITING_COACH if coaches["offense"] == HOME_COACH else HOME_COACH
        )
        for side in ("offense", "defense"):
            match = cog.engine.load_match_state(game)
            options_hand = next(
                hand for hand in ManeuverActionPromptView(cog, game.game_id)
                .prompt_options(game, match, PromptKind.MANEUVER_ACTION).hands
                if hand.side == side
            )
            view = ManeuverHandView(cog, game.game_id, options_hand)
            interaction = build_interaction(user_id=coaches[side])
            with suppressed_cog_saves():
                await view.pick(interaction, side, options_hand.maneuver_keys[0])
        match = cog.engine.load_match_state(game)
        for deck in match.maneuver_decks.values():
            self.assertEqual(len(deck["hand"]), 4)
            self.assertEqual(len(deck["discard"]), 1)


class DiscardPictureTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_picture_until_something_is_discarded(self) -> None:
        cog = build_cog()
        game = build_game(mode=GameMode.STANDARD, edition=Edition.TWO)
        cog.engine.rng.seed(3)
        match = cog.engine.initialize_standard_match(game)
        self.assertIsNone(await cog.build_discard_file(game, match))

        home = match.maneuver_decks["home"]
        home["discard"].append(home["hand"].pop(0))
        picture = await cog.build_discard_file(game, match)
        self.assertEqual(picture.filename, "discard_piles.png")


if __name__ == "__main__":
    unittest.main()

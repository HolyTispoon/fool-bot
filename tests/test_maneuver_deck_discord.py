"""
D12 Ball 2.0 on Discord: the public maneuver prompt carries no cards,
only one hand button; pressing it shows a coach their own four cards, ephemerally, with the maneuvers they can play under it; and a
pick from there plays the card. The rules are `test_maneuver_deck`'s;
this is the frontend over them.
"""

import unittest
from unittest import mock

from cogs.d12ball_helpers import HAND_BUTTON_LABEL
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

    def test_the_public_prompt_carries_one_hand_button_and_no_card(self) -> None:
        cog, game = self.build()
        view = ManeuverActionPromptView(cog, game.game_id)
        labels = [item.label for item in view.children]
        self.assertEqual(labels.count(HAND_BUTTON_LABEL), 1)
        names = {maneuver.name for maneuver in cog.maneuver_catalog.offense
                 + cog.maneuver_catalog.defense}
        self.assertFalse(names & set(labels))

    def coaches(self, cog, game):
        match = cog.engine.load_match_state(game)
        offense_team = TeamSide(match.ball.possession)
        offense_coach = (
            HOME_COACH if offense_team == TeamSide.HOME else VISITING_COACH
        )
        defense_coach = (
            VISITING_COACH if offense_coach == HOME_COACH else HOME_COACH
        )
        return match, {"offense": offense_coach, "defense": defense_coach}

    async def test_each_coach_is_shown_their_own_hand_alone(self) -> None:
        cog, game = self.build()
        match, coaches = self.coaches(cog, game)
        for side, coach in coaches.items():
            cog.build_deck_hand_file.reset_mock()
            shown = build_interaction(user_id=coach)
            await ManeuverActionPromptView(cog, game.game_id).show_hand(shown)
            sent = shown.followup.send.await_args_list
            self.assertEqual(len(sent), 1)
            self.assertTrue(sent[0].kwargs["ephemeral"])
            self.assertIs(sent[0].kwargs["file"], mock.sentinel.hand_file)
            held, drawn_side = cog.build_deck_hand_file.await_args.args
            self.assertEqual(drawn_side, side)
            team = cog.engine.maneuver_side_team(match, side)
            self.assertEqual(
                tuple(held), cog.engine.maneuver_deck_hand(match, team),
            )
            hand_view = sent[0].kwargs["view"]
            self.assertIsInstance(hand_view, ManeuverHandView)
            self.assertEqual(
                sorted(item.label for item in hand_view.children),
                sorted(m.name for m in cog.engine.maneuver_hand(game, match, side)),
            )

    async def test_somebody_coaching_neither_side_is_refused(self) -> None:
        cog, game = self.build()
        refused = build_interaction(user_id=333)
        await ManeuverActionPromptView(cog, game.game_id).show_hand(refused)
        self.assertTrue(refused.response.send_message.await_args.kwargs["ephemeral"])
        refused.followup.send.assert_not_awaited()
        cog.build_deck_hand_file.assert_not_awaited()

    async def test_a_coach_on_both_sides_is_shown_both_hands(self) -> None:
        cog, game = self.build()
        game.player_2_id = HOME_COACH
        shown = build_interaction(user_id=HOME_COACH)
        await ManeuverActionPromptView(cog, game.game_id).show_hand(shown)
        sent = shown.followup.send.await_args_list
        self.assertEqual(
            [call.args[0].split(" (")[0] for call in sent],
            ["Your hand on offense", "Your hand on defense"],
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

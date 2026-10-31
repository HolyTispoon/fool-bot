"""
D12 Ball 2.1 on Discord: the public maneuver prompt carries no cards,
only one hand button; pressing it shows a coach their own five cards, ephemerally, with the maneuvers they can play under it; and a
pick from there plays the card. The rules are `test_maneuver_deck`'s;
this is the frontend over them.
"""

import unittest
from unittest import mock

from cogs.d12ball_helpers import HAND_BUTTON_LABEL
from cogs.d12ball_views import ManeuverActionPromptView
from cogs.d12ball_views.turn import FlipExtraView, ManeuverHandView
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
            # One button a way to play a card: its own, or flipped.
            plays = cog.engine.card_plays(game, match, side)
            self.assertEqual(len(hand_view.children), len(plays))
            for item, play in zip(hand_view.children, plays):
                self.assertIn(play.card_id, item.label)
                self.assertEqual(item.label.startswith("\u21c5"), play.flip)

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
            play = next(play for play in options_hand.cards if not play.flip)
            with suppressed_cog_saves():
                await view.pick(
                    interaction, side, play.maneuver_key, play.card_id,
                )
        match = cog.engine.load_match_state(game)
        for deck in match.maneuver_decks.values():
            self.assertEqual(len(deck["hand"]), 5)
            self.assertEqual(len(deck["discard"]), 1)


    async def test_a_flip_asks_its_extra_card_and_discards_both(self) -> None:
        cog, game = self.build()
        match = cog.engine.load_match_state(game)
        team = cog.engine.maneuver_side_team(match, "offense")
        deck = match.maneuver_decks[team.value]
        # A hand with a defensive card the offense can only flip.
        others = [card for card in deck["draw"] if card.startswith("F")]
        deck["draw"] = [c for c in deck["draw"] if c != others[0]] + deck["hand"][:1]
        deck["hand"][0] = others[0]
        game.match_state = match.to_dict()
        options_hand = next(
            hand for hand in ManeuverActionPromptView(cog, game.game_id)
            .prompt_options(game, match, PromptKind.MANEUVER_ACTION).hands
            if hand.side == "offense"
        )
        flip = next(play for play in options_hand.cards if play.flip)
        extras = FlipExtraView(cog, game.game_id, "offense", flip)
        self.assertEqual(len(extras.children), len(flip.extra_ids))
        coach = HOME_COACH if team == TeamSide.HOME else VISITING_COACH
        with suppressed_cog_saves():
            await extras.pick(
                build_interaction(user_id=coach), "offense",
                flip.maneuver_key, flip.card_id, flip.extra_ids[0],
            )
        match = cog.engine.load_match_state(game)
        self.assertEqual(match.maneuver_cards["offense"], [flip.card_id, flip.extra_ids[0]])
        self.assertEqual(match.offense_maneuver, "low_pass")


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

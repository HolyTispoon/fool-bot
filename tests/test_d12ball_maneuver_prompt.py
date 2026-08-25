"""
The public "Choose Your Maneuver" prompt's own lifetime.

Both sides pick from the same message, so it has to stay up while
either of them still has a pick to make -- and go away once neither
does, rather than leaving a button that can only answer "you have
already chosen".
"""

import unittest
from types import SimpleNamespace
from unittest import mock

import discord

from cogs.d12ball import D12Ball
from cogs.d12ball_views import (
    ManeuverActionPromptView,
)
from d12ball.cards import render_maneuver_hands
from d12ball.components import (
    MANEUVER_TIER_BASIC,
    MatchState,
    Zone,
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
)
from d12ball.engine import RulesEngine
from d12ball.game import D12BallGame, Team


def build_cog() -> D12Ball:
    cog = object.__new__(D12Ball)
    cog.games = {}
    cog.player_catalog = load_player_catalog()
    cog.maneuver_catalog = load_maneuver_catalog()
    cog.basic_ruleset = load_basic_ruleset()
    cog.team_emojis = {}
    cog.condition_emojis = {}
    cog.engine = RulesEngine(
        cog.player_catalog, cog.basic_ruleset, cog.maneuver_catalog, {},
    )
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


def build_interaction(prompt_message) -> SimpleNamespace:
    return SimpleNamespace(
        channel=SimpleNamespace(
            get_partial_message=mock.Mock(return_value=prompt_message),
        ),
    )


class ManeuverPromptLifetimeTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()

    def build_match(self, cog: D12Ball) -> MatchState:
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=7,
            home_team=Team.ORANGE,
            visiting_team=Team.PURPLE,
        )
        match.active_player_id = match.home.field_players[0]
        match.challenger_id = match.visiting.field_players[0]
        return match

    def build_prompt_message(self) -> SimpleNamespace:
        return SimpleNamespace(
            edit=mock.AsyncMock(),
            delete=mock.AsyncMock(),
        )

    async def refresh(self, cog, game, match, prompt_message) -> None:
        with mock.patch("cogs.d12ball.save_games"):
            await cog.close_maneuver_prompt(
                build_interaction(prompt_message), game, match,
            )

    async def test_the_prompt_stays_up_while_one_side_is_still_picking(
        self,
    ) -> None:
        # And is not touched: the message names who it is waiting on
        # and both sides share one button, so re-editing it after a
        # pick changed nothing a coach could see -- it only spent a
        # request out of the bucket the board refresh needs.
        cog = build_cog()
        game = build_game()
        game.turn_message_id = 555
        match = self.build_match(cog)
        match.choose_offense_maneuver(cog.maneuver_catalog.offense[0].name)

        prompt_message = self.build_prompt_message()
        await self.refresh(cog, game, match, prompt_message)

        prompt_message.edit.assert_not_awaited()
        prompt_message.delete.assert_not_awaited()
        self.assertEqual(game.turn_message_id, 555)

    async def test_the_prompt_is_deleted_once_both_sides_have_picked(
        self,
    ) -> None:
        cog = build_cog()
        game = build_game()
        game.turn_message_id = 555
        match = self.build_match(cog)
        match.choose_offense_maneuver(cog.maneuver_catalog.offense[0].name)
        match.choose_defense_maneuver(cog.maneuver_catalog.defense[0].name)

        prompt_message = self.build_prompt_message()
        await self.refresh(cog, game, match, prompt_message)

        prompt_message.delete.assert_awaited_once()
        prompt_message.edit.assert_not_awaited()
        # Nothing should try to edit or re-attach a view to it later.
        self.assertIsNone(game.turn_message_id)

    async def test_an_already_deleted_prompt_is_not_an_error(self) -> None:
        cog = build_cog()
        game = build_game()
        game.turn_message_id = 555
        match = self.build_match(cog)
        match.choose_offense_maneuver(cog.maneuver_catalog.offense[0].name)
        match.choose_defense_maneuver(cog.maneuver_catalog.defense[0].name)

        prompt_message = self.build_prompt_message()
        prompt_message.delete = mock.AsyncMock(
            side_effect=discord.NotFound(
                mock.Mock(status=404), "already gone",
            ),
        )
        await self.refresh(cog, game, match, prompt_message)

        self.assertIsNone(game.turn_message_id)


class ManeuverChallengeAnnouncementTests(unittest.IsolatedAsyncioTestCase):
    """
    How a settled challenge is announced.

    It used to be two lines of prose -- "has chosen to maneuver" and
    "will challenge" -- naming players a coach can already see on the
    board and saying nothing about them. It is now one image, carrying
    the skills and abilities the maneuver about to be picked is
    weighed against.
    """

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

    def build_interaction(self) -> SimpleNamespace:
        return SimpleNamespace(
            channel=None,
            guild=None,
            followup=SimpleNamespace(
                send=mock.AsyncMock(return_value=SimpleNamespace(id=999)),
            ),
            delete_original_response=mock.AsyncMock(),
        )

    async def resolve(self, walk_in: bool):
        cog = build_cog()
        cog.refresh_match_image = mock.AsyncMock()
        cog.begin_maneuver_action_selection = mock.AsyncMock()
        game = build_game()
        cog.games[game.game_id] = game

        match = self.build_match()
        match.select_ball_handler(match.eligible_ball_handlers()[0])
        if walk_in:
            # A defender already on the ball is the whole of the
            # challenge -- nobody may be walked in past them (see
            # MatchState.challenge_candidates) -- and the kickoff space
            # has one standing on it. Clear them out first.
            for player_id in match.automatic_challengers():
                match.move_meeple(player_id, Zone.VISITORS_GOAL, 0)
        challenger = next(
            player_id
            for player_id in match.challenge_candidates()
            if (match.distance_to_ball(player_id) > 0) == walk_in
        )
        game.match_state = match.to_dict()

        interaction = self.build_interaction()
        with mock.patch("cogs.d12ball.save_games"):
            await cog.auto_resolve_challenger(
                interaction, game, match, challenger,
            )
        return interaction

    async def test_the_matchup_is_posted_as_an_image_and_not_as_prose(
        self,
    ) -> None:
        interaction = await self.resolve(walk_in=False)

        calls = interaction.followup.send.await_args_list
        self.assertEqual(len(calls), 1)
        self.assertIn("file", calls[0].kwargs)
        self.assertFalse(calls[0].args)

    async def test_the_walk_in_is_posted_above_the_image(self) -> None:
        # Above, not below: the image is meant to sit directly on top
        # of the maneuver prompt it is being read for.
        interaction = await self.resolve(walk_in=True)

        calls = interaction.followup.send.await_args_list
        self.assertEqual(len(calls), 2)
        self.assertIn("has moved", calls[0].args[0])
        self.assertIn("file", calls[1].kwargs)

    def test_the_image_captions_a_player_with_the_short_ability(
        self,
    ) -> None:
        # The sentence version is a caption under a portrait here, next
        # to another player's, so the image takes the abbreviated form
        # the abilities sheet carries. The roster still shows the
        # sentence.
        cog = build_cog()
        match = self.build_match()
        player_id = match.home.field_players[0]
        profile = cog.player_catalog.effective_profile(
            cog.engine.get_player_definition(player_id),
        )

        side = cog.engine.challenge_side(
            player_id, match.team_for_player(player_id), attacking=True,
        )

        self.assertEqual(side.ability, profile.ability_short)
        self.assertNotEqual(side.ability, profile.ability)

    async def test_dropping_the_turn_prompt_clears_its_id(self) -> None:
        cog = build_cog()
        game = build_game()
        game.turn_message_id = 555
        interaction = self.build_interaction()

        with mock.patch("cogs.d12ball.save_games"):
            await cog.drop_turn_prompt(interaction, game)

        interaction.delete_original_response.assert_awaited_once()
        self.assertIsNone(game.turn_message_id)

    async def test_an_already_deleted_turn_prompt_is_not_an_error(
        self,
    ) -> None:
        cog = build_cog()
        game = build_game()
        game.turn_message_id = 555
        interaction = self.build_interaction()
        interaction.delete_original_response = mock.AsyncMock(
            side_effect=discord.NotFound(
                mock.Mock(status=404), "already gone",
            ),
        )

        with mock.patch("cogs.d12ball.save_games"):
            await cog.drop_turn_prompt(interaction, game)

        self.assertIsNone(game.turn_message_id)


class ManeuverPickHarness:
    """
    Putting the maneuver pick up, for the two things it puts in front
    of both coaches: the hands, and the field they would be played on.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()
        # Drawn once for the whole class, as the cog draws it once for
        # the whole process -- the cards are most of a second apiece.
        catalog = load_maneuver_catalog()
        # Keyed the way the cog keys them -- by the sides on the prompt
        # *and* by the tiers they may play. A basic game is the only one
        # this harness builds, so the advanced entry is the same bytes
        # rather than a second render: nothing here reads it, and
        # drawing thirteen more cards a class is seconds for nothing.
        drawn = {
            sides: render_maneuver_hands(catalog, cls.catalog, sides).read()
            for sides in (("offense",), ("defense",), ("offense", "defense"))
        }
        cls.hands = {
            (sides, tiers): image
            for sides, image in drawn.items()
            for tiers in (("basic",), ("basic", "advanced"))
        }

    def build_ready_cog(self) -> D12Ball:
        cog = build_cog()
        cog.maneuver_hand_image_bytes = dict(self.hands)
        return cog

    async def put_up_prompt(self, cog: D12Ball, uncontested: bool = False):
        """
        Run the real prompt send and hand back the interaction, so a
        test can read the prompt itself and the field message under it.
        """
        game = build_game()
        game.match_state = {}
        cog.games[game.game_id] = game

        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=7,
            home_team=Team.ORANGE,
            visiting_team=Team.PURPLE,
        )
        match.active_player_id = match.home.field_players[0]
        if uncontested:
            match.maneuver_uncontested = True
        else:
            match.challenger_id = match.visiting.field_players[0]
        game.match_state = match.to_dict()

        cog.engine.load_match_state = mock.Mock(return_value=match)

        sent = SimpleNamespace(id=999, attachments=[])
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=111),
            guild=None,
            response=SimpleNamespace(send_message=mock.AsyncMock()),
            followup=SimpleNamespace(send=mock.AsyncMock(return_value=sent)),
        )
        with mock.patch("cogs.d12ball.save_games"), mock.patch(
            "cogs.d12ball.add_full_image_button", new=mock.AsyncMock(),
        ):
            await cog.begin_maneuver_action_selection(
                interaction, game, match,
            )
        return interaction, game, match

    def prompt_kwargs(self, interaction):
        """The kwargs the prompt itself went out with."""
        return interaction.followup.send.await_args_list[0].kwargs


class ManeuverPickShowsTheCardsTests(
    ManeuverPickHarness,
    unittest.IsolatedAsyncioTestCase,
):
    """
    The prompt puts both hands and both rows of buttons on one public
    message. It used to be a public button that opened an ephemeral
    menu of the clicking coach's own cards -- which cost a click and a
    round trip to hide nothing, since the cards are public information
    and what stays secret is the pick.
    """

    async def test_the_prompt_carries_both_hands(self) -> None:
        interaction, _, _ = await self.put_up_prompt(self.build_ready_cog())

        sent = self.prompt_kwargs(interaction)
        self.assertEqual(
            sent["file"].filename, "maneuver_hand_offense_defense.png",
        )

    async def test_an_uncontested_maneuver_carries_the_offense_alone(
        self,
    ) -> None:
        interaction, _, _ = await self.put_up_prompt(
            self.build_ready_cog(), uncontested=True,
        )

        sent = self.prompt_kwargs(interaction)
        self.assertEqual(sent["file"].filename, "maneuver_hand_offense.png")

    async def test_the_prompt_is_public(self) -> None:
        # The whole point: neither coach has to hold an interaction for
        # this message to reach them, which is what the extra click was
        # buying.
        interaction, _, _ = await self.put_up_prompt(self.build_ready_cog())

        self.assertNotIn("ephemeral", self.prompt_kwargs(interaction))

    async def test_the_prompt_message_is_what_a_restart_re_arms(
        self,
    ) -> None:
        interaction, game, _ = await self.put_up_prompt(
            self.build_ready_cog(),
        )

        self.assertTrue(self.prompt_kwargs(interaction)["wait"])
        self.assertEqual(game.turn_message_id, 999)

    def test_the_prompt_offers_both_sides_then_the_reference(self) -> None:
        # Both sides' maneuvers in rank order, offense first, and the
        # "Maneuver Reference" button last. The card back carries the
        # same defeat cycle, but as one card among several at a third of
        # print size -- the hexagon is what a coach reads a matchup off,
        # so it is a click away rather than gone.
        cog = self.build_ready_cog()
        game = build_game()
        cog.games[game.game_id] = game
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=7,
            home_team=Team.ORANGE,
            visiting_team=Team.PURPLE,
        )
        match.challenger_id = match.visiting.field_players[0]
        game.match_state = match.to_dict()
        cog.engine.load_match_state = mock.Mock(return_value=match)

        view = ManeuverActionPromptView(cog, game.game_id)

        self.assertEqual(
            [item.label for item in view.children],
            [
                maneuver.name
                for side in ("offense", "defense")
                for maneuver in cog.maneuver_catalog.for_tier(
                    side, MANEUVER_TIER_BASIC,
                )
            ]
            + ["Maneuver Reference"],
        )

    def test_each_side_gets_its_own_row_and_its_own_colour(self) -> None:
        # A coach picks their row out of a prompt holding both without
        # reading the labels: offense red, defense green, exactly as the
        # cards and the reference hexagon draw them.
        cog = self.build_ready_cog()
        game = build_game()
        cog.games[game.game_id] = game
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=7,
            home_team=Team.ORANGE,
            visiting_team=Team.PURPLE,
        )
        match.challenger_id = match.visiting.field_players[0]
        game.match_state = match.to_dict()
        cog.engine.load_match_state = mock.Mock(return_value=match)

        view = ManeuverActionPromptView(cog, game.game_id)
        by_side = {}
        for item in view.children:
            if not (item.custom_id or "").startswith(
                "d12ball:maneuver_pick:"
            ):
                continue
            by_side.setdefault(
                item.custom_id.split(":")[3], set()
            ).add((item.row, item.style))

        self.assertEqual(
            by_side["offense"], {(0, discord.ButtonStyle.danger)},
        )
        self.assertEqual(
            by_side["defense"], {(1, discord.ButtonStyle.success)},
        )

    def test_the_reference_button_is_addressed_per_game(self) -> None:
        # One button for a prompt holding both sides -- the hexagon is
        # the same picture for either coach, so it carries the game and
        # no side.
        cog = self.build_ready_cog()
        game = build_game()
        cog.games[game.game_id] = game

        ids = [
            item.custom_id
            for item in ManeuverActionPromptView(cog, game.game_id).children
            if item.label == "Maneuver Reference"
        ]

        self.assertEqual(ids, ["d12ball:maneuver_reference:g1"])

    async def test_the_hand_is_drawn_once_and_re_wrapped_per_send(
        self,
    ) -> None:
        # Uploading a discord.File consumes the stream inside it, so a
        # second prompt must not be handed the emptied one.
        cog = self.build_ready_cog()
        first, _, _ = await self.put_up_prompt(cog)
        second, _, _ = await self.put_up_prompt(cog)

        first_file = self.prompt_kwargs(first)["file"]
        second_file = self.prompt_kwargs(second)["file"]
        self.assertIsNot(first_file, second_file)
        self.assertEqual(
            first_file.fp.getvalue(), second_file.fp.getvalue(),
        )


class ManeuverPickShowsTheFieldTests(
    ManeuverPickHarness,
    unittest.IsolatedAsyncioTestCase,
):
    """
    And under the hands, where everybody is standing. What a maneuver
    would do depends on the position, and the persistent board has
    usually scrolled up the channel by the time a turn resolves.
    """

    async def test_the_field_follows_the_prompt(self) -> None:
        interaction, _, _ = await self.put_up_prompt(self.build_ready_cog())

        sent = interaction.followup.send.await_args_list[-1].kwargs
        self.assertEqual(sent["file"].filename, "d12ball-field.png")
        # The message has to come back, or there is nothing to hang the
        # full-image link on -- the field is the smallest thing the bot
        # sends inline.
        self.assertTrue(sent["wait"])

    async def test_the_field_is_public_like_the_prompt(self) -> None:
        # One upload for both coaches, where it used to be one apiece.
        interaction, _, _ = await self.put_up_prompt(self.build_ready_cog())

        sent = interaction.followup.send.await_args_list[-1].kwargs
        self.assertNotIn("ephemeral", sent)

    async def test_the_field_is_a_message_of_its_own(self) -> None:
        # Not a second attachment on the prompt. Discord lays two images
        # on one message out side by side, which halves the width of a
        # field that is already the widest thing here -- and the
        # prompt's own full-image link reads the first attachment, so a
        # coach clicking it under the hands gets the hands.
        interaction, _, _ = await self.put_up_prompt(self.build_ready_cog())

        prompt = self.prompt_kwargs(interaction)
        self.assertNotIn("files", prompt)
        self.assertEqual(
            prompt["file"].filename, "maneuver_hand_offense_defense.png",
        )
        self.assertEqual(interaction.followup.send.await_count, 2)

    async def test_the_field_is_the_board_as_it_stands(self) -> None:
        # It is rendered per maneuver, unlike the cards: it is the
        # position, so it is different every time and cannot be drawn at
        # startup.
        interaction, _, _ = await self.put_up_prompt(self.build_ready_cog())

        image = interaction.followup.send.await_args_list[-1].kwargs["file"].fp
        self.assertTrue(image.getvalue().startswith(b"\x89PNG"))

    async def test_a_failed_field_send_does_not_lose_the_prompt(self) -> None:
        # The prompt is already up and clickable by then, which is worth
        # more than the picture under it.
        cog = self.build_ready_cog()
        game = build_game()
        game.match_state = {}
        cog.games[game.game_id] = game
        cog.build_field_file = mock.AsyncMock(
            side_effect=discord.HTTPException(
                mock.Mock(status=500), "no thanks",
            ),
        )

        interaction = SimpleNamespace(
            followup=SimpleNamespace(send=mock.AsyncMock()),
        )
        with mock.patch(
            "cogs.d12ball.add_full_image_button", new=mock.AsyncMock(),
        ):
            await cog.post_field_image(interaction, game)

        interaction.followup.send.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()

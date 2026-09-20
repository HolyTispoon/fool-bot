"""
Where a result is announced relative to the dice that decided it.

Discord renders a message's attachments *below* its content, so a
verdict written into the message the dice image is attached to is read
before the roll it is announcing. Every one of these results therefore
posts the verdict as the message *after* the dice: skill tests, high
passes and loose balls, goals, and missed attempts. The dice message
itself carries no text at all -- the image already names both players
and shows every modifier that built the totals.

The tie is the exception -- its message also carries the roll-again
button, so its text stays with it. See SkillTestView.roll and
ScoreAttemptView.roll in cogs/d12ball_views.py.

A maneuver challenge is announced the same way round for the same
reason, except that there the image is the whole announcement.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

from cogs.d12ball import D12Ball
from cogs.d12ball_views import (
    LooseBallSkillTestView,
    ScoreAttemptView,
    SkillTestView,
)
from d12ball.components import (
    MatchState,
    TeamSide,
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
)
from d12ball.engine import IgnitedRoll, RulesEngine
from d12ball.game import D12BallGame, Team
from save_patches import suppressed_cog_saves, suppressed_view_saves


def build_cog() -> D12Ball:
    cog = object.__new__(D12Ball)
    cog.games = {}
    cog.player_catalog = load_player_catalog()
    cog.maneuver_catalog = load_maneuver_catalog()
    cog.basic_ruleset = load_basic_ruleset()
    cog.engine = RulesEngine(
        cog.player_catalog, cog.basic_ruleset, cog.maneuver_catalog, {},
    )
    cog.team_emojis = {}
    cog.refresh_match_image = mock.AsyncMock()
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
    # `channel.send` and `followup.send` share one mock: which route a
    # post takes depends on whether the interaction still had a response
    # to give, and these tests read back "everything this posted" in
    # order without caring which route carried which message.
    send = mock.AsyncMock(return_value=SimpleNamespace(id=999))
    return SimpleNamespace(
        user=SimpleNamespace(id=111, display_name="One"),
        channel=SimpleNamespace(send=send),
        guild=None,
        followup=SimpleNamespace(send=send),
        response=SimpleNamespace(
            defer=mock.AsyncMock(),
            edit_message=mock.AsyncMock(),
            send_message=mock.AsyncMock(),
            is_done=lambda: True,
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
        for offense in (m.key for m in cog.maneuver_catalog.offense):
            for defense in (m.key for m in cog.maneuver_catalog.defense):
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
        # **Both suppressions**, since Phase 4: a skill test that owes
        # no injury tests now saves once through the cog's own
        # `persist`, because the wrapper saves after the step rather
        # than the step saving itself (principle 9).
        with suppressed_cog_saves(), suppressed_view_saves(), mock.patch(
            "random.randint", side_effect=[12, 1],
        ), mock.patch("cogs.d12ball_views.base.render_skill_test_dice"), mock.patch(
            "discord.File",
        ):
            await view.roll(interaction)

        dice_message = interaction.edit_original_response.await_args.kwargs
        # No content at all: the dice image carries the whole roll, so
        # the message it is attached to is the image and nothing else.
        self.assertIsNone(dice_message["content"])
        self.assertIn(
            "**"
            f"{cog.engine.maneuver_name(match.offense_maneuver)}"
            "** wins the skill test!",
            sent_texts(interaction)[0],
        )

    # -- High pass and loose ball --------------------------------------

    def build_contest(
        self,
        cog: D12Ball,
        is_high_pass: bool,
        on_empty_space: bool = True,
    ):
        match = self.build_match()
        game = build_game()
        match.active_player_id = match.setup_for_side(
            match.ball.possession
        ).field_players[0]
        match.move_meeple(
            match.active_player_id, match.ball.zone, match.ball.space_index,
        )
        match.pending_loose_ball = True
        match.pending_loose_ball_is_high_pass = is_high_pass
        match.pending_loose_ball_on_empty_space = on_empty_space
        match.loose_ball_offense_player = match.setup_for_side(
            match.ball.possession
        ).field_players[0]
        match.loose_ball_defense_player = match.setup_for_side(
            match.defending_side()
        ).field_players[0]
        game.match_state = match.to_dict()
        cog.games[game.game_id] = game
        return game, match

    async def roll_contest(self, cog, game, rolls) -> SimpleNamespace:
        interaction = build_interaction()
        view = LooseBallSkillTestView(cog, game.game_id)
        with suppressed_view_saves(), suppressed_cog_saves(), mock.patch(
            "random.randint", side_effect=rolls,
        ), mock.patch("cogs.d12ball_views.base.render_skill_test_dice"), mock.patch(
            "discord.File",
        ):
            await view.roll(interaction)
        return interaction

    async def test_keeping_a_high_pass_is_announced_after_the_dice(
        self,
    ) -> None:
        # This one used to write its result into the dice message,
        # unlike every other skill test, so a coach read "keeps
        # possession" above the roll that settled it.
        cog = build_cog()
        game, _ = self.build_contest(cog, is_high_pass=True)

        interaction = await self.roll_contest(cog, game, [12, 1])

        dice_message = interaction.response.edit_message.await_args.kwargs
        self.assertIsNone(dice_message["content"])
        self.assertIn(
            "keeps possession after the high pass",
            sent_texts(interaction)[0],
        )

    async def test_a_loose_ball_turnover_is_announced_after_the_dice(
        self,
    ) -> None:
        cog = build_cog()
        game, _ = self.build_contest(cog, is_high_pass=False)

        interaction = await self.roll_contest(cog, game, [1, 12])

        dice_message = interaction.response.edit_message.await_args.kwargs
        self.assertIsNone(dice_message["content"])
        announcement = sent_texts(interaction)[0]
        self.assertTrue(announcement.startswith("# Turnover!"))
        self.assertIn("wins the loose ball!", announcement)

    async def test_a_contest_on_an_occupied_space_is_not_called_loose(
        self,
    ) -> None:
        # Only a ball lying where nobody is standing is *loose* (the
        # author, 2026-08-26). Both sides having somebody there is a
        # contest, and the result used to announce it as a loose ball
        # anyway -- telling a coach the opposite of what they had just
        # watched. The noun is read off the position, like every other
        # message on this path; see contest_noun.
        cog = build_cog()
        game, _ = self.build_contest(
            cog, is_high_pass=False, on_empty_space=False,
        )

        interaction = await self.roll_contest(cog, game, [1, 12])

        announcement = sent_texts(interaction)[0]
        self.assertIn("wins the ball!", announcement)
        self.assertNotIn("loose", announcement)

    # -- The tie -------------------------------------------------------

    async def test_a_tied_skill_test_is_headed_like_every_other_outcome(
        self,
    ) -> None:
        # A tie is one of the ways a skill test lands, and the other
        # three are announced at `##`. Left as bold body text it read
        # as a footnote to the dice rather than the result of them.
        cog = build_cog()
        game, _ = self.build_skill_test(cog)
        interaction = build_interaction()

        view = SkillTestView(cog, game.game_id)
        with suppressed_view_saves(), suppressed_cog_saves(), mock.patch.object(
            SkillTestView,
            "score_skill_test",
            # The two trailing IgnitedRolls are what Volatile did to
            # each side's die; a tie that never ignited is two bare
            # faces, which is what every roll in a basic game is.
            return_value=([], 7, 7, IgnitedRoll(face=7), IgnitedRoll(face=7)),
        ), mock.patch(
            "cogs.d12ball_views.base.render_skill_test_dice",
        ), mock.patch("discord.File"):
            await view.roll(interaction)

        # The tie is the one result that stays on the dice message,
        # because that message also carries the roll-again button.
        content = interaction.edit_original_response.await_args.kwargs[
            "content"
        ]
        self.assertTrue(content.startswith("## "), content)
        self.assertIn("It's a tie (7-7)!", content)

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
        for offense in (m.key for m in cog.maneuver_catalog.offense):
            for defense in (m.key for m in cog.maneuver_catalog.defense):
                if cog.maneuver_catalog.resolve(offense, defense) == "offense":
                    match.offense_maneuver = offense
                    match.defense_maneuver = defense
                    winner = offense
                    break
        game.match_state = match.to_dict()
        interaction = build_interaction()

        with suppressed_cog_saves():
            await cog.resolve_maneuver(interaction, game, match)

        # **Read off what the effect was handed**, not off the
        # channel: since Phase 4 the reveal is `resolve_maneuver_step`'s
        # narration and `begin_effect_resolution` -- mocked here -- is
        # what posts it, on its own, a line before the effect's own
        # message. Same two messages in the same order; one hop later
        # in the code.
        cog.begin_effect_resolution.assert_awaited_once()
        announcement = cog.begin_effect_resolution.await_args.kwargs["lead_in"]
        self.assertIn(
            f"## **{cog.engine.maneuver_name(winner)}** wins!", announcement,
        )
        self.assertNotIn("resolves the effect", announcement)
        self.assertNotIn("<@", announcement)

    # -- Score attempt -------------------------------------------------

    def build_score_attempt(self, cog: D12Ball):
        # Nobody in the way, so the two dice alone decide the attempt
        # and a 12 against a 1 is a goal either way round.
        cog.engine.intervening_defenders = mock.Mock(return_value=[])
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

    async def test_the_attempt_is_composed_as_an_image(self) -> None:
        # What the shot is made of used to be a paragraph of prose
        # above the roll prompt, listing the same skills and abilities
        # the image now shows. Only the prompt is text now.
        cog = build_cog()
        game, match = self.build_score_attempt(cog)
        interaction = build_interaction()

        with suppressed_cog_saves():
            await cog.begin_score_attempt(interaction, game, match)

        calls = interaction.followup.send.await_args_list
        self.assertEqual(len(calls), 2)
        self.assertIn("file", calls[0].kwargs)
        self.assertFalse(calls[0].args)
        self.assertIn("Either player can roll", calls[1].args[0])

    async def test_every_defender_in_the_way_is_drawn(self) -> None:
        cog = build_cog()
        game, match = self.build_score_attempt(cog)
        # The real thing, rather than build_score_attempt's empty stub:
        # a shot from the ball's own space has the whole defending side
        # between it and the goal, which is the case that wraps onto a
        # second row.
        cog.engine.intervening_defenders = (
            RulesEngine.intervening_defenders.__get__(cog.engine)
        )
        self.assertGreater(len(cog.engine.intervening_defenders(match)), 1)
        interaction = build_interaction()

        with suppressed_cog_saves():
            await cog.begin_score_attempt(interaction, game, match)

        self.assertIn(
            "file", interaction.followup.send.await_args_list[0].kwargs,
        )

    async def roll_score_attempt(self, cog, game, rolls) -> SimpleNamespace:
        interaction = build_interaction()
        view = ScoreAttemptView(cog, game.game_id)
        with suppressed_view_saves(), suppressed_cog_saves(), mock.patch(
            "random.randint", side_effect=rolls,
        ), mock.patch("cogs.d12ball_views.base.render_skill_test_dice"), mock.patch(
            "discord.File",
        ):
            await view.roll(interaction)
        return interaction

    async def test_a_goal_is_announced_after_the_dice(self) -> None:
        cog = build_cog()
        game, _ = self.build_score_attempt(cog)

        interaction = await self.roll_score_attempt(cog, game, [12, 1])

        dice_message = interaction.response.edit_message.await_args.kwargs
        self.assertIsNone(dice_message["content"])
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
        self.assertIsNone(dice_message["content"])
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
        match.pending_own_goal = True
        match.pending_own_goal_distance = 1
        game.match_state = match.to_dict()

        interaction = build_interaction()
        with suppressed_cog_saves(), mock.patch(
            "random.randint", return_value=roll,
        ), mock.patch("cogs.d12ball.effects.render_own_goal_dice"), mock.patch(
            "discord.File",
        ):
            await cog.run_own_goal_roll(interaction, game, match)
        return cog, interaction

    async def test_an_own_goal_is_announced_after_its_dice(self) -> None:
        _, interaction = await self.roll_own_goal(1)

        # The roll prompt becomes the dice, and the verdict follows it
        # in a message of its own.
        dice_message = interaction.edit_original_response.await_args.kwargs
        self.assertIn("attachments", dice_message)
        self.assertNotIn("Own goal!", dice_message["content"])
        self.assertIn("# Own goal!", sent_texts(interaction)[0])

    async def test_avoiding_an_own_goal_is_announced_after_its_dice(
        self,
    ) -> None:
        _, interaction = await self.roll_own_goal(12)

        dice_message = interaction.edit_original_response.await_args.kwargs
        self.assertIn("attachments", dice_message)
        self.assertNotIn("avoided", dice_message["content"])
        self.assertIn("## Own goal avoided!", sent_texts(interaction)[0])

    # -- Which turnovers open a substitution window ---------------------
    #
    # A goal, a missed attempt and a conceded own goal all restart from
    # a dead ball, so all three are new plays -- and so is an own goal
    # that gets avoided, even though nothing died and possession never
    # changes. See "Own goal" and "Steals and new plays" in
    # docs/living-rules.md.

    async def test_a_conceded_own_goal_is_a_new_play(self) -> None:
        cog, _ = await self.roll_own_goal(1)

        cog.begin_run_back.assert_awaited_once()
        self.assertTrue(cog.begin_run_back.await_args.kwargs["new_play"])

    async def test_a_conceded_own_goal_owes_no_pickup(self) -> None:
        # A conceded own goal restarts from the kickoff space, exactly
        # as any other goal -- the existing, unaffected
        # pending_kickoff_fill path, not this one.
        cog, _ = await self.roll_own_goal(1)

        match = cog.engine.load_match_state(cog.games["g1"])
        self.assertFalse(match.pending_ball_recovery)

    async def test_an_avoided_own_goal_is_a_new_play(self) -> None:
        cog, _ = await self.roll_own_goal(12)

        cog.begin_run_back.assert_awaited_once()
        self.assertTrue(cog.begin_run_back.await_args.kwargs["new_play"])
        self.assertTrue(cog.begin_run_back.await_args.kwargs["turnover_occurred"])

    async def test_an_avoided_own_goal_owes_a_pickup(self) -> None:
        # The ball stays exactly where the overshot Pressure left it,
        # with no coverage guarantee at all -- unlike a goal's kickoff
        # space. Since 2026-08-24 that is the same one-sided pickup an
        # out-of-bounds ball owes (begin_ball_recovery, which itself
        # asks nobody once the reset already covers it) rather than a
        # two-sided loose ball.
        cog, interaction = await self.roll_own_goal(12)

        match = cog.engine.load_match_state(cog.games["g1"])
        self.assertTrue(match.pending_ball_recovery)

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

    async def test_a_missed_attempt_owes_a_pickup(self) -> None:
        # Unlike a goal's kickoff space, nothing guarantees the space
        # closest to the defending side's own goal is covered by an
        # arrangement -- so, since 2026-08-24, a miss owes the same
        # one-sided pickup an out-of-bounds ball does.
        cog = build_cog()
        game, _ = self.build_score_attempt(cog)

        await self.roll_score_attempt(cog, game, [1, 12])

        match = cog.engine.load_match_state(game)
        self.assertTrue(match.pending_ball_recovery)

    async def test_a_goal_owes_no_pickup(self) -> None:
        # A goal restarts from the kickoff space instead, which every
        # arrangement is required to cover -- that is the existing,
        # unaffected pending_kickoff_fill path.
        cog = build_cog()
        game, _ = self.build_score_attempt(cog)

        await self.roll_score_attempt(cog, game, [12, 1])

        match = cog.engine.load_match_state(game)
        self.assertFalse(match.pending_ball_recovery)

        cog.begin_run_back.assert_awaited_once()
        self.assertTrue(cog.begin_run_back.await_args.kwargs["new_play"])


class RoleEmojiOnTheCogTests(unittest.TestCase):
    """
    A message names a player through `D12Ball.player_label`, and the
    role emoji reach it through one dict held on the engine -- the
    cog's `role_emojis` is a view of that copy, so a load that lands
    on the cog is what the engine's own prompt builders read too.
    """

    def test_the_cog_and_the_engine_share_one_dict(self) -> None:
        from d12ball.components import PlayerRole

        cog = build_cog()
        badges = {(PlayerRole.STRIKER, Team.ORANGE): "<:role_striker_orange:100>"}

        cog.role_emojis = badges

        self.assertIs(cog.engine.role_emojis, badges)
        self.assertIs(cog.role_emojis, badges)

    def test_player_label_carries_the_role_emoji(self) -> None:
        from d12ball.components import PlayerRole
        from d12ball.formatting import role_initials

        cog = build_cog()
        match = MatchState.standard(
            catalog=cog.player_catalog,
            ruleset=cog.basic_ruleset,
            board_size=7,
            home_team=Team.ORANGE,
            visiting_team=Team.PURPLE,
        )
        home = match.setup_for_side(TeamSide.HOME)
        players = [cog.engine.get_player_definition(i) for i in home.field_players]
        striker = next(p for p in players if p.role == PlayerRole.STRIKER)
        other = next(p for p in players if p.role != PlayerRole.STRIKER)
        cog.role_emojis = {
            (PlayerRole.STRIKER, Team.ORANGE): "<:role_striker_orange:100>",
        }

        # `player_label` reads the side off the match and asks for the
        # badge in that side's own colour -- so the ring in front and
        # the badge after cannot name two different teams.
        self.assertEqual(
            cog.player_label(match, striker),
            f"🟠 {striker.name} <:role_striker_orange:100>",
        )
        self.assertEqual(
            cog.player_id_label(match, other.player_id),
            f"🟠 {other.name} [{role_initials(other)}]",
        )

    def test_the_same_card_on_the_other_side_is_named_in_that_colour(
        self,
    ) -> None:
        """
        A player fielded on both sides is one person and two cards,
        and the badge is the card's -- the visiting copy carries the
        visitors' colour. It falls out of `player_label` reading
        `match.team_for_player`, which is the same lookup the team
        emoji in front already made; the point is that the two now
        cannot disagree. See "One player, both sides" in docs/design/teams-and-players.md.
        """
        from d12ball.components import PlayerRole
        from d12ball.game import Team

        cog = build_cog()
        match = MatchState.standard(
            catalog=cog.player_catalog,
            ruleset=cog.basic_ruleset,
            board_size=7,
            home_team=Team.ORANGE,
            visiting_team=Team.PURPLE,
        )
        cog.role_emojis = {
            (PlayerRole.STRIKER, Team.ORANGE): "<:role_striker_orange:100>",
            (PlayerRole.STRIKER, Team.PURPLE): "<:role_striker_purple:101>",
        }

        for side, emoji, badge in (
            (TeamSide.HOME, "🟠", "<:role_striker_orange:100>"),
            (TeamSide.VISITING, "🟣", "<:role_striker_purple:101>"),
        ):
            setup = match.setup_for_side(side)
            striker = next(
                player
                for player in (
                    cog.engine.get_player_definition(player_id)
                    for player_id in setup.field_players
                )
                if player.role == PlayerRole.STRIKER
            )
            with self.subTest(side=side):
                self.assertEqual(
                    cog.player_label(match, striker),
                    f"{emoji} {striker.name} {badge}",
                )


if __name__ == "__main__":
    unittest.main()

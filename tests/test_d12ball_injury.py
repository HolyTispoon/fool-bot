"""
The injured player's maneuver disadvantage.

"They automatically lose a challenge, and must win a skill test even
when their maneuver beats their opponent's outright" (docs/living-rules.md,
"Injured players" under Exhaustion and injury). So a tie against exactly
one injured participant is settled without a roll, and a decisive
maneuver owed to an injured player is downgraded to a skill test they
still have to win.

`settled_maneuver_winner` is the only place that rule lives, because the
ranking on its own now disagrees with the turn in both directions -- it
takes wins away and hands them out. The tests at the bottom pin the two
callers that reconstruct a prompt after a restart to the same answer.

The disadvantage has a second, separate half: in a **contest** an
injured player adds no skill modifier, rolling the bare d12. That is
the skill only, and a contest only -- ball speed, role abilities, a
maneuver's skill test and a score attempt are all untouched. Those
boundaries are what the middle three classes are for; each of them has
been on the wrong side of this at least once.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

from cogs.d12ball import D12Ball
from cogs.d12ball_views import (
    LooseBallSkillTestView,
    LowPassChoiceView,
    ScoreAttemptView,
    SkillTestView,
)
from d12ball.ai import build_ai_strategies
from d12ball.engine import RulesEngine
from d12ball.components import (
    MatchState,
    PlayerRole,
    TeamSide,
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
)
from d12ball.game import D12BallGame, GameStatus, Team
from save_patches import suppressed_cog_saves, suppressed_view_saves


def build_cog() -> D12Ball:
    cog = object.__new__(D12Ball)
    cog.games = {}
    cog.player_catalog = load_player_catalog()
    cog.maneuver_catalog = load_maneuver_catalog()
    cog.basic_ruleset = load_basic_ruleset()
    cog.coin_emojis = {}
    cog.ai_strategies = build_ai_strategies(
        cog.player_catalog, cog.maneuver_catalog,
    )
    cog.engine = RulesEngine(
        cog.player_catalog, cog.basic_ruleset, cog.maneuver_catalog,
        cog.ai_strategies,
    )
    cog.refresh_match_image = mock.AsyncMock()
    cog.begin_effect_resolution = mock.AsyncMock()
    return cog


def build_game() -> D12BallGame:
    return D12BallGame(
        game_id="g1",
        game_number=1,
        guild_id=1,
        channel_id=2,
        message_id=None,
        player_1_id=111,
        player_2_id=222,
        player_1_name="One",
        player_2_name="Two",
        player_1_team=Team.ORANGE,
        player_2_team=Team.PURPLE,
        status=GameStatus.IN_PROGRESS,
        home_player_number=1,
        visiting_player_number=2,
    )


def build_interaction() -> SimpleNamespace:
    # `channel.send` and `followup.send` share one mock: which route a
    # post takes depends on whether the interaction still had a response
    # to give, and these tests read back "what this posted" without
    # caring which route carried it.
    send = mock.AsyncMock(return_value=SimpleNamespace(id=999))
    return SimpleNamespace(
        response=SimpleNamespace(is_done=lambda: True),
        channel=SimpleNamespace(send=send),
        followup=SimpleNamespace(send=send),
    )


class ManeuverInjuryTests(unittest.IsolatedAsyncioTestCase):
    def build(self) -> tuple[D12Ball, D12BallGame, MatchState]:
        """
        Home in possession, challenged by a visiting player -- the
        ordinary two-player maneuver.
        """
        cog = build_cog()
        game = build_game()
        cog.games[game.game_id] = game
        match = cog.engine.initialize_standard_match(game)
        match.active_player_id = match.home.field_players[0]
        match.challenger_id = match.visiting.field_players[0]
        return cog, game, match

    async def resolve(self, cog, game, match) -> SimpleNamespace:
        interaction = build_interaction()
        with suppressed_cog_saves():
            await cog.resolve_maneuver(interaction, game, match)
        return interaction

    def last_view(self, interaction):
        for call in reversed(interaction.followup.send.await_args_list):
            if "view" in call.kwargs:
                return call.kwargs["view"]
        return None

    async def test_decisive_win_by_healthy_player_resolves_automatically(
        self,
    ) -> None:
        cog, game, match = self.build()
        match.offense_maneuver = "low_pass"
        match.defense_maneuver = "pressure"  # Low Pass beats Pressure.

        await self.resolve(cog, game, match)

        cog.begin_effect_resolution.assert_awaited_once()
        self.assertEqual(
            cog.begin_effect_resolution.await_args.args[3], "low_pass",
        )

    async def test_decisive_win_by_injured_player_forces_a_skill_test(
        self,
    ) -> None:
        cog, game, match = self.build()
        match.offense_maneuver = "low_pass"
        match.defense_maneuver = "pressure"  # Would auto-win for offense.
        match.injured.add(match.active_player_id)

        interaction = await self.resolve(cog, game, match)

        # No automatic effect resolution -- a skill test goes up instead.
        cog.begin_effect_resolution.assert_not_awaited()
        self.assertIsInstance(self.last_view(interaction), SkillTestView)

    async def test_decisive_win_by_injured_defender_forces_a_skill_test(
        self,
    ) -> None:
        cog, game, match = self.build()
        match.offense_maneuver = "low_pass"
        match.defense_maneuver = "steal"  # Beats Low Pass.
        match.injured.add(match.challenger_id)

        interaction = await self.resolve(cog, game, match)

        cog.begin_effect_resolution.assert_not_awaited()
        self.assertIsInstance(self.last_view(interaction), SkillTestView)

    async def test_tie_with_one_injured_participant_is_an_auto_loss(
        self,
    ) -> None:
        cog, game, match = self.build()
        match.offense_maneuver = "low_pass"
        match.defense_maneuver = "deflect"  # Same rank -- a tie.
        match.injured.add(match.active_player_id)

        await self.resolve(cog, game, match)

        # The healthy side (defense) wins outright, no skill test.
        cog.begin_effect_resolution.assert_awaited_once()
        self.assertEqual(
            cog.begin_effect_resolution.await_args.args[3], "deflect",
        )

    async def test_an_auto_loss_charges_neither_side_a_token(self) -> None:
        cog, game, match = self.build()
        match.offense_maneuver = "low_pass"
        match.defense_maneuver = "deflect"
        match.injured.add(match.active_player_id)

        await self.resolve(cog, game, match)

        # The token is what a player pays for entering the test, and no
        # test was rolled.
        self.assertNotIn(match.active_player_id, match.exhaustion)
        self.assertNotIn(match.challenger_id, match.exhaustion)

    async def test_tie_with_both_injured_still_runs_a_skill_test(
        self,
    ) -> None:
        cog, game, match = self.build()
        match.offense_maneuver = "low_pass"
        match.defense_maneuver = "deflect"
        match.injured.add(match.active_player_id)
        match.injured.add(match.challenger_id)

        interaction = await self.resolve(cog, game, match)

        # Neither has the relative advantage, so it's an ordinary tie.
        cog.begin_effect_resolution.assert_not_awaited()
        self.assertIsInstance(self.last_view(interaction), SkillTestView)

    async def test_an_injured_players_uncontested_maneuver_still_succeeds(
        self,
    ) -> None:
        cog, game, match = self.build()
        match.offense_maneuver = "low_pass"
        match.defense_maneuver = None
        match.challenger_id = None
        match.maneuver_uncontested = True
        match.injured.add(match.active_player_id)

        await self.resolve(cog, game, match)

        # Nobody to be disadvantaged against and no challenge to lose,
        # so the disadvantage has nothing to bite on.
        cog.begin_effect_resolution.assert_awaited_once()
        self.assertEqual(
            cog.begin_effect_resolution.await_args.args[3], "low_pass",
        )


class SkillTestIsNotAContestTests(unittest.IsolatedAsyncioTestCase):
    """
    The skill modifier is withheld **in a contest**, and a maneuver's
    skill test is not one -- an injured player's disadvantage there is
    the tie-loss and the forced test, and it is not compounded by a
    third penalty. So a skill test rolls the same whether or not a
    participant is injured, Midfielder's +3 included.

    This went in backwards once, withholding the role's bonus instead
    of the skill and doing it here rather than in the contest, so both
    halves are pinned.
    """

    def build(self, injure_midfielder: bool):
        cog = build_cog()
        game = build_game()
        cog.games[game.game_id] = game
        match = cog.engine.initialize_standard_match(game)

        midfielder = next(
            player_id
            for player_id in match.home.field_players
            if cog.engine.get_player_definition(player_id).role
            == PlayerRole.MIDFIELDER
        )
        match.active_player_id = midfielder
        match.challenger_id = match.visiting.field_players[0]
        match.offense_maneuver = "low_pass"
        match.defense_maneuver = "deflect"
        if injure_midfielder:
            match.injured.add(midfielder)
        game.match_state = match.to_dict()
        return cog, game, midfielder

    async def roll(self, cog, game):
        send = mock.AsyncMock()
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=game.player_1_id),
            response=SimpleNamespace(
                defer=mock.AsyncMock(),
                send_message=mock.AsyncMock(),
                is_done=lambda: True,
            ),
            edit_original_response=mock.AsyncMock(),
            channel=SimpleNamespace(send=send),
            followup=SimpleNamespace(send=send),
        )
        view = SkillTestView(cog, game.game_id)
        # Both, which is the usual shape for a view: since Phase 4 the
        # injury queue's own step is dispatched through
        # `D12Ball.persist` even when no test is owed -- the driver
        # writes once after a step rather than the step deciding
        # whether the write is worth it (principle 9).
        with suppressed_cog_saves(), suppressed_view_saves(), mock.patch(
            "discord.File",
        ), mock.patch(
            "random.randint", return_value=7,
        ), mock.patch(
            "cogs.d12ball_views.base.render_skill_test_dice",
        ) as render:
            await view.roll(interaction)
        # The offense entry: (roll, colour, team, detail lines, total).
        return render.call_args.args[0][0]

    async def test_a_healthy_midfielder_adds_skill_and_ability(self) -> None:
        cog, game, _ = self.build(injure_midfielder=False)
        _, _, _, detail, total, _, _ = await self.roll(cog, game)

        self.assertIn("+3 Midfielder ability", detail)
        self.assertIn("Offensive skill +3", detail)
        # d12 of 7, offensive skill 3, ability +3.
        self.assertEqual(total, 13)

    async def test_an_injured_midfielder_adds_both_just_the_same(
        self,
    ) -> None:
        cog, game, _ = self.build(injure_midfielder=True)
        _, _, _, detail, total, _, _ = await self.roll(cog, game)

        self.assertIn("+3 Midfielder ability", detail)
        self.assertIn("Offensive skill +3", detail)
        self.assertEqual(total, 13)


class InjuredStrikerKeepsTheSetUpBonusTests(unittest.IsolatedAsyncioTestCase):
    """
    The disadvantage is losing the ability modifier *when someone is
    contesting them*, and nobody contests a shot -- so an injured
    Striker keeps their +3 off a set-up. The author's, 2026-08-09.
    This is the counterpart to the Midfielder tests above and exists to
    stop the two being "made consistent" with each other.
    """

    async def roll_attempt(self, injure: bool) -> list:
        cog = build_cog()
        cog.engine.intervening_defenders = mock.Mock(return_value=[])
        cog.announce_board_update = mock.AsyncMock()
        game = build_game()
        cog.games[game.game_id] = game
        match = cog.engine.initialize_standard_match(game)

        striker = next(
            player_id
            for player_id in match.home.field_players
            if cog.engine.get_player_definition(player_id).role == PlayerRole.STRIKER
        )
        match.active_player_id = striker
        match.ball.possession = TeamSide.HOME
        match.set_ball_space(*match.board.meeple_position(striker))
        match.pending_action = "shoot"
        match.pending_shot_is_set_up = True
        match.ball.speed = 1  # speed // 2 == 0, so no ball speed term.
        if injure:
            match.injured.add(striker)
        game.match_state = match.to_dict()

        interaction = SimpleNamespace(
            user=SimpleNamespace(id=game.player_1_id),
            response=SimpleNamespace(
                defer=mock.AsyncMock(),
                send_message=mock.AsyncMock(),
                edit_message=mock.AsyncMock(),
            ),
            edit_original_response=mock.AsyncMock(),
            followup=SimpleNamespace(
                send=mock.AsyncMock(return_value=SimpleNamespace(id=999)),
            ),
        )
        # Only the arithmetic is under test, and it is all in the
        # entries handed to the dice render. Everything past that point
        # is the goal-or-miss aftermath -- a new play, a run back, a
        # board post -- so the render stops the roll once it has what
        # this needs.
        entries = []

        class Stop(Exception):
            pass

        def capture(rows):
            entries.append(rows)
            raise Stop

        view = ScoreAttemptView(cog, game.game_id)
        with suppressed_view_saves(), suppressed_cog_saves(), mock.patch(
            "random.randint", return_value=7,
        ), mock.patch(
            "cogs.d12ball_views.base.render_skill_test_dice", side_effect=capture,
        ):
            with self.assertRaises(Stop):
                await view.roll(interaction)
        return entries[0][0]

    async def test_a_healthy_striker_adds_the_set_up_bonus(self) -> None:
        _, _, _, detail, total, _, _ = await self.roll_attempt(injure=False)

        self.assertIn("+3 Striker ability", detail)
        # d12 of 7, offensive skill 6, ability +3.
        self.assertEqual(total, 16)

    async def test_an_injured_striker_keeps_it(self) -> None:
        _, _, _, detail, total, _, _ = await self.roll_attempt(injure=True)

        self.assertIn("+3 Striker ability", detail)
        self.assertEqual(total, 16)


class InjuredContestantAddsNoSkillTests(unittest.IsolatedAsyncioTestCase):
    """
    The one place the skill modifier is withheld: a contest -- keeping
    a long High Pass, or a loose ball. The injured contestant rolls the
    bare d12, and **only** the skill comes off. A High Pass receiver
    still gets the ball speed modifier, which is the case that killed
    the old "adds nothing" wording.
    """

    async def contest(self, injure=None, high_pass=True) -> list:
        cog = build_cog()
        cog.apply_exhaustion = mock.Mock(return_value="")
        game = build_game()
        cog.games[game.game_id] = game
        match = cog.engine.initialize_standard_match(game)

        offense = next(
            player_id
            for player_id in match.home.field_players
            if cog.engine.get_player_definition(player_id).role == PlayerRole.STRIKER
        )
        defense = next(
            player_id
            for player_id in match.visiting.field_players
            if cog.engine.get_player_definition(player_id).role
            == PlayerRole.FULLBACK
        )
        match.pending_loose_ball = True
        match.pending_loose_ball_is_high_pass = high_pass
        match.loose_ball_offense_player = offense
        match.loose_ball_defense_player = defense
        match.ball.speed = 6  # speed // 2 == 3.
        if injure == "offense":
            match.injured.add(offense)
        elif injure == "defense":
            match.injured.add(defense)
        game.match_state = match.to_dict()

        entries = []

        class Stop(Exception):
            pass

        def capture(rows):
            entries.append(rows)
            raise Stop

        interaction = SimpleNamespace(
            user=SimpleNamespace(id=game.player_1_id),
            response=SimpleNamespace(
                defer=mock.AsyncMock(),
                send_message=mock.AsyncMock(),
                edit_message=mock.AsyncMock(),
            ),
            edit_original_response=mock.AsyncMock(),
            followup=SimpleNamespace(
                send=mock.AsyncMock(return_value=SimpleNamespace(id=999)),
            ),
        )
        view = LooseBallSkillTestView(cog, game.game_id)
        with suppressed_view_saves(), suppressed_cog_saves(), mock.patch(
            "random.randint", return_value=7,
        ), mock.patch(
            "cogs.d12ball_views.base.render_skill_test_dice", side_effect=capture,
        ):
            with self.assertRaises(Stop):
                await view.roll(interaction)
        return entries[0]

    async def test_healthy_contestants_add_their_skill(self) -> None:
        (
            (_, _, _, off_detail, off_total, _, _),
            (_, _, _, _, def_total, _, _),
        ) = await self.contest()

        self.assertIn("Offensive skill +6", off_detail)
        self.assertIn("+3 ball speed modifier", off_detail)
        # d12 of 7, offensive skill 6, ball speed +3.
        self.assertEqual(off_total, 16)
        # Fullback's defensive skill is 6.
        self.assertEqual(def_total, 13)

    async def test_an_injured_receiver_keeps_only_the_ball_speed(
        self,
    ) -> None:
        (_, _, _, off_detail, off_total, _, _), _ = await self.contest(
            injure="offense",
        )

        self.assertIn("Injured — no skill modifier", off_detail)
        self.assertNotIn("Offensive skill +6", off_detail)
        # The modifier the roll grants survives -- this is the case
        # "adds nothing" got wrong.
        self.assertIn("+3 ball speed modifier", off_detail)
        self.assertEqual(off_total, 10)

    async def test_an_injured_defender_rolls_bare(self) -> None:
        _, (_, _, _, def_detail, def_total, _, _) = await self.contest(
            injure="defense",
        )

        self.assertIn("Injured — no skill modifier", def_detail)
        self.assertEqual(def_total, 7)

    async def test_it_applies_to_a_plain_loose_ball_too(self) -> None:
        (_, _, _, off_detail, off_total, _, _), _ = await self.contest(
            injure="offense", high_pass=False,
        )

        # No ball speed on a genuine loose ball, so nothing is left.
        self.assertIn("Injured — no skill modifier", off_detail)
        self.assertEqual(off_total, 7)


class SettledWinnerRestoreTests(unittest.TestCase):
    """
    A restart mid-maneuver reconstructs its prompt from match state, so
    `build_effect_choice_view` has to reach the same verdict
    `resolve_maneuver` did. Deriving it from the ranking alone gets both
    injury cases backwards.
    """

    def build(self) -> tuple[D12Ball, D12BallGame, MatchState]:
        cog = build_cog()
        game = build_game()
        cog.games[game.game_id] = game
        match = cog.engine.initialize_standard_match(game)
        match.active_player_id = match.home.field_players[0]
        match.challenger_id = match.visiting.field_players[0]
        return cog, game, match

    def test_no_effect_choice_while_an_injured_player_owes_a_test(
        self,
    ) -> None:
        cog, game, match = self.build()
        match.offense_maneuver = "low_pass"
        match.defense_maneuver = "pressure"
        match.injured.add(match.active_player_id)

        self.assertIsNone(cog.engine.settled_maneuver_winner(match))
        # The ranking says Low Pass won; the turn says roll for it.
        self.assertIsNone(cog.build_effect_choice_view(game.game_id, match))

    def test_an_auto_loss_restores_the_winners_effect_choice(self) -> None:
        cog, game, match = self.build()
        match.offense_maneuver = "low_pass"
        match.defense_maneuver = "deflect"
        match.injured.add(match.challenger_id)

        # The ranking says tie, which used to mean "a skill test is
        # pending"; the injured challenger has already lost it.
        self.assertEqual(cog.engine.settled_maneuver_winner(match), "low_pass")
        self.assertIsInstance(
            cog.build_effect_choice_view(game.game_id, match),
            LowPassChoiceView,
        )

    def test_an_uncontested_maneuver_is_its_own_winner(self) -> None:
        cog, game, match = self.build()
        match.offense_maneuver = "low_pass"
        match.defense_maneuver = None
        match.challenger_id = None
        match.maneuver_uncontested = True

        self.assertEqual(cog.engine.settled_maneuver_winner(match), "low_pass")


if __name__ == "__main__":
    unittest.main()

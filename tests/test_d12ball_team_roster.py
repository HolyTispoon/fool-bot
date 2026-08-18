"""
The team roster: how it is grouped, and where it can be asked for.

A roster is read to answer "where is everyone, and how tired are
they", so it is grouped by place -- each board zone in board order,
then the benches -- rather than by the catalog's order. The grouping
follows the meeple, not the player card's assigned zone, since a
maneuver can leave a player standing outside their zone until they run
back. The Coaching Choice hub carries a button to the same text, because
that is the decision it exists for.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

from cogs.d12ball import D12Ball
from cogs.d12ball_views import (
    CoachingHubView,
)
from d12ball.components import (
    CoachingOccasion,
    MatchState,
    TeamSide,
    Zone,
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
)
from d12ball.engine import RulesEngine
from d12ball.game import D12BallGame, Team, team_display_name


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


class TeamRosterGroupingTests(unittest.TestCase):
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

    def test_places_run_zones_first_then_the_benches(self) -> None:
        cog = build_cog()
        match = self.build_match()

        headings = [
            heading
            for heading, _ in cog.engine.roster_places(match, match.home)
        ]

        self.assertEqual(
            headings,
            ["Home Goal", "Midfield", "Visitors Goal", "Bench", "Back Bench"],
        )

    def test_every_roster_player_is_listed_exactly_once(self) -> None:
        cog = build_cog()
        match = self.build_match()

        listed = [
            player_id
            for _, members in cog.engine.roster_places(match, match.home)
            for player_id, _ in members
        ]

        self.assertEqual(
            sorted(listed),
            sorted(
                player.player_id
                for player in self.catalog.teams[match.home.team].players
            ),
        )

    def test_a_zone_s_players_are_ordered_by_space(self) -> None:
        cog = build_cog()
        match = self.build_match()

        # Swap the two home-goal meeples' spaces; the roster follows
        # the board, so the listing order swaps with them.
        zone = Zone.HOME_GOAL
        first, second = (
            player_id
            for player_id in match.home.field_players
            if match.board.meeple_position(player_id)[0] == zone
        )
        match.board.place_meeple(first, zone, 1)
        match.board.place_meeple(second, zone, 0)

        places = dict(cog.engine.roster_places(match, match.home))
        self.assertEqual(
            places["Home Goal"],
            [(second, "H1"), (first, "H2")],
        )

    def test_a_displaced_player_is_listed_where_they_stand(self) -> None:
        # Their card still says Home Goal; the meeple is in midfield
        # until they run back, and that is where they are.
        cog = build_cog()
        match = self.build_match()

        player_id = match.home.zones[Zone.HOME_GOAL][0]
        match.board.place_meeple(player_id, Zone.MIDFIELD, 0)

        places = dict(cog.engine.roster_places(match, match.home))
        self.assertNotIn(
            player_id, [listed for listed, _ in places["Home Goal"]],
        )
        self.assertIn((player_id, "M1"), places["Midfield"])

    def test_an_empty_place_still_gets_a_heading(self) -> None:
        # A zone nobody is standing in is information, not clutter.
        cog = build_cog()
        match = self.build_match()

        text = cog.build_team_roster_section(match, match.home)

        self.assertIn("__Back Bench__\n*nobody*", text)
        for heading in ("Home Goal", "Midfield", "Visitors Goal", "Bench"):
            self.assertIn(f"__{heading}__", text)

    def test_a_roster_section_fits_in_one_discord_message(self) -> None:
        # Headings made the section longer; abilities are the longest
        # form of it, and it is sent as a single message.
        cog = build_cog()
        match = self.build_match()

        text = cog.build_team_roster_section(
            match, match.home, show_abilities=True,
        )

        self.assertLess(len(text), 2000)


class RosterVisibilityTests(unittest.TestCase):
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

    def test_a_coach_gets_their_own_team(self) -> None:
        cog = build_cog()
        match = self.build_match()
        game = build_game()

        self.assertEqual(
            cog.engine.roster_setups_for_user(game, match, game.player_2_id),
            [match.visiting],
        )

    def test_a_spectator_gets_nothing(self) -> None:
        cog = build_cog()
        match = self.build_match()
        game = build_game()

        self.assertIsNone(
            cog.engine.roster_setups_for_user(game, match, 999),
        )

    def test_a_test_game_s_owner_runs_both_sides(self) -> None:
        cog = build_cog()
        match = self.build_match()
        game = build_game()
        game.test_game = True

        self.assertEqual(
            cog.engine.roster_setups_for_user(game, match, game.player_1_id),
            [match.home, match.visiting],
        )


class CoachingRosterButtonTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()

    def build_open_window(self) -> tuple[D12Ball, D12BallGame, MatchState]:
        cog = build_cog()
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=7,
            home_team=Team.ORANGE,
            visiting_team=Team.PURPLE,
        )
        match.open_coaching_window(TeamSide.HOME, CoachingOccasion.NEW_PLAY)
        game = build_game()
        game.match_state = match.to_dict()
        cog.games[game.game_id] = game
        return cog, game, match

    def labels(self, view) -> list[str]:
        return [child.label for child in view.children]

    def test_the_coaching_hub_offers_the_roster(self) -> None:
        # One message means one place the button has to be, rather
        # than one on every prompt in the flow.
        cog, game, match = self.build_open_window()
        match.declare_coaching()
        game.match_state = match.to_dict()

        self.assertIn(
            "Team roster",
            self.labels(CoachingHubView(cog, game.game_id)),
        )

    async def test_the_button_answers_privately_with_your_own_team(
        self,
    ) -> None:
        cog, game, match = self.build_open_window()
        view = CoachingHubView(cog, game.game_id)

        interaction = SimpleNamespace(
            user=SimpleNamespace(id=game.player_1_id),
            response=SimpleNamespace(send_message=mock.AsyncMock()),
        )
        await view.show_roster(interaction)

        interaction.response.send_message.assert_awaited_once()
        content, keywords = interaction.response.send_message.await_args
        self.assertTrue(keywords["ephemeral"])
        self.assertIn(team_display_name(match.home.team), content[0])
        self.assertNotIn(
            team_display_name(match.visiting.team), content[0],
        )

    async def test_the_waiting_coach_can_read_theirs_too(self) -> None:
        # Reading a roster is not acting on the window, so it is not
        # gated on holding it -- see CoachingHubView.show_roster.
        cog, game, match = self.build_open_window()
        view = CoachingHubView(cog, game.game_id)

        interaction = SimpleNamespace(
            user=SimpleNamespace(id=game.player_2_id),
            response=SimpleNamespace(send_message=mock.AsyncMock()),
        )
        await view.show_roster(interaction)

        content, _ = interaction.response.send_message.await_args
        self.assertIn(team_display_name(match.visiting.team), content[0])


if __name__ == "__main__":
    unittest.main()

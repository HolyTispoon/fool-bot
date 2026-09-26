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
from d12ball.game import D12BallGame, GameMode, Team, team_display_name
from space_codes import code


def build_cog() -> D12Ball:
    cog = object.__new__(D12Ball)
    cog.games = {}
    cog.player_catalog = load_player_catalog()
    cog.maneuver_catalog = load_maneuver_catalog()
    cog.basic_ruleset = load_basic_ruleset()
    cog.engine = RulesEngine(
        cog.player_catalog, cog.basic_ruleset, cog.maneuver_catalog, {},
    )
    return cog


def build_game(**overrides) -> D12BallGame:
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
        **overrides,
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
            ["Home Zone", "Midfield", "Visitors Zone", "Bench", "Back Bench"],
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
            places["Home Zone"],
            [
                (second, code(match.board, "H1")),
                (first, code(match.board, "H2")),
            ],
        )

    def test_a_displaced_player_is_listed_where_they_stand(self) -> None:
        # Their card still says Home Zone; the meeple is in midfield
        # until they run back, and that is where they are.
        cog = build_cog()
        match = self.build_match()

        player_id = match.home.zones[Zone.HOME_GOAL][0]
        match.board.place_meeple(player_id, Zone.MIDFIELD, 0)

        places = dict(cog.engine.roster_places(match, match.home))
        self.assertNotIn(
            player_id, [listed for listed, _ in places["Home Zone"]],
        )
        self.assertIn(
            (player_id, code(match.board, "M1")), places["Midfield"],
        )

    def test_an_empty_place_still_gets_a_heading(self) -> None:
        # A zone nobody is standing in is information, not clutter.
        cog = build_cog()
        match = self.build_match()

        text = cog.build_team_roster_section(build_game(), match, match.home)

        self.assertIn("__Back Bench__\n*nobody*", text)
        for heading in ("Home Zone", "Midfield", "Visitors Zone", "Bench"):
            self.assertIn(f"__{heading}__", text)

    def test_a_roster_section_fits_in_one_discord_message(self) -> None:
        # Headings made the section longer; abilities are the longest
        # form of it, and it is sent as a single message.
        cog = build_cog()
        match = self.build_match()

        text = cog.build_team_roster_section(
            build_game(), match, match.home, show_role_abilities=True,
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


class PersonalAbilityRosterTests(unittest.TestCase):
    """
    In advanced mode the roster shows each player's personal ability
    (Law 21) unless the coach turns it off; the role's is shown only
    when asked for. The players are picked off the data -- who has a
    personal ability is the sheet's to revise -- never by id.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()

    def setUp(self) -> None:
        self.cog = build_cog()
        self.match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=7,
            home_team=Team.ORANGE,
            visiting_team=Team.PURPLE,
        )
        players = [
            self.cog.engine.get_player_definition(player_id)
            for _, members in self.cog.engine.roster_places(
                self.match, self.match.home,
            )
            for player_id, _ in members
        ]
        self.holder = next(p for p in players if p.advanced_ability)
        self.without = next(p for p in players if not p.advanced_ability)

    def entry(self, game: D12BallGame, player, **flags) -> str:
        return self.cog.format_team_roster_entry(
            game, self.match, player.player_id, **flags,
        )

    def test_an_advanced_game_shows_the_personal_ability_by_default(
        self,
    ) -> None:
        game = build_game(mode=GameMode.ADVANCED)
        line = self.entry(game, self.holder)
        self.assertIn(self.holder.advanced_ability, line)
        role = self.catalog.effective_profile(self.holder).ability
        self.assertNotIn(role, line)

    def test_the_coach_may_turn_the_personal_ability_off(self) -> None:
        game = build_game(mode=GameMode.ADVANCED)
        line = self.entry(game, self.holder, show_advanced_abilities=False)
        self.assertNotIn(self.holder.advanced_ability, line)

    def test_both_abilities_show_when_both_are_asked_for(self) -> None:
        game = build_game(mode=GameMode.ADVANCED)
        line = self.entry(game, self.holder, show_role_abilities=True)
        self.assertIn(self.holder.advanced_ability, line)
        self.assertIn(
            self.catalog.effective_profile(self.holder).ability, line,
        )

    def test_a_player_with_no_personal_ability_gets_no_line(self) -> None:
        game = build_game(mode=GameMode.ADVANCED)
        self.assertNotIn("\n", self.entry(game, self.without))

    def test_no_other_mode_shows_a_personal_ability(self) -> None:
        for game in (
            build_game(mode=GameMode.BASIC),
            build_game(mode=GameMode.TRAINING),
            build_game(mode=GameMode.ADVANCED, tutorial=True),
        ):
            with self.subTest(mode=game.mode, tutorial=game.tutorial):
                self.assertEqual(
                    self.cog.engine.personal_ability_text(
                        game, self.holder.player_id,
                    ),
                    "",
                )
                self.assertNotIn(
                    self.holder.advanced_ability,
                    self.entry(game, self.holder),
                )

    def test_every_advanced_roster_fits_in_one_discord_message(
        self,
    ) -> None:
        # Both abilities is the longest a section gets, and it is sent
        # as a single message.
        game = build_game(mode=GameMode.ADVANCED)
        for home, visiting in (
            (Team.ORANGE, Team.PURPLE),
            (Team.FIRE_DEMONS, Team.CYBORGS),
            (Team.TELEKINETICS, Team.OOZES),
            (Team.TEAL, Team.SLIME),
        ):
            match = MatchState.standard(
                catalog=self.catalog,
                ruleset=self.rules,
                board_size=7,
                home_team=home,
                visiting_team=visiting,
            )
            for setup in (match.home, match.visiting):
                with self.subTest(team=setup.team):
                    text = self.cog.build_team_roster_section(
                        game, match, setup, show_role_abilities=True,
                    )
                    self.assertLess(len(text), 2000)


if __name__ == "__main__":
    unittest.main()

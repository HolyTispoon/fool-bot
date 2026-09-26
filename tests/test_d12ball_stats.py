"""
The statistics: the fold that reads a match's event log back, and the
tables it renders.

Three things are worth testing here and they fail for different
reasons:

- **The cut.** `match_turns` and `possessions` turn a flat list into
  the two structures every report is built on, and they read the
  log's *order* rather than any stored counter -- so an event landing
  in the wrong turn is a whole report being quietly wrong.
- **The rates.** Which plays count towards a success rate is a rules
  question, not an arithmetic one: an uncontested maneuver always
  wins and must not be in the denominator.
- **The tables.** They go into a Discord code block, which scrolls
  rather than wraps, so a row wider than the fence is one a coach has
  to drag sideways to read.

The events are built by hand here rather than played out through the
cog. That is deliberate and it is not the whole story: the fold needs
fixtures a real game would take fifty turns to reach (an injury, a
tie re-rolled twice), and what a real game actually logs is asserted
where a real game is already being played -- `TutorialPlaythroughTests`
walks the five scripted beats through the real cog, and
`EveryMatchupResolvesTests` puts all thirty-six pairings through
`resolve_maneuver`. Between them, this file checks the reading and
those two check the writing.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

import discord

from cogs.d12ball import D12Ball
from d12ball import stats
from d12ball.ai import build_ai_strategies
from d12ball.engine import RulesEngine
from d12ball.components import (
    DECISION_CARDS,
    DECISION_INJURY_FORFEIT,
    DECISION_SKILL_TEST,
    DECISION_UNCONTESTED,
    EVENT_GOAL,
    EVENT_INJURY_TEST,
    EVENT_MANEUVER,
    EVENT_OWN_GOAL_ROLL,
    EVENT_SHOT,
    EVENT_SKILL_TEST,
    EVENT_TIME_OUT,
    EVENT_TURN_ACTION,
    MatchState,
    PlayerRole,
    TeamSide,
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
)
from d12ball.game import D12BallGame, Team

from roster import fielded
from save_patches import suppressed_cog_saves
from cog_steps import run_injury_test, run_own_goal_roll


def build_match() -> MatchState:
    return MatchState.standard(
        catalog=load_player_catalog(),
        ruleset=load_basic_ruleset(),
        board_size=7,
        home_team=Team.ORANGE,
        visiting_team=Team.TEAL,
    )


def build_game(**kwargs) -> D12BallGame:
    defaults = dict(
        game_id="g1",
        game_number=1,
        guild_id=1,
        channel_id=2,
        message_id=None,
        player_1_id=10,
        player_2_id=11,
    )
    defaults.update(kwargs)
    return D12BallGame(**defaults)


def turn(
    match: MatchState,
    side: TeamSide = TeamSide.HOME,
    action: str = "maneuver",
    exhaustion: dict | None = None,
    by_ai: bool = False,
) -> None:
    match.record_event(
        EVENT_TURN_ACTION,
        side=side,
        player_id="somebody",
        action=action,
        by_ai=by_ai,
        exhaustion=exhaustion or {},
    )


def maneuver(
    match: MatchState,
    offense_key: str,
    defense_key: str,
    winner_key: str,
    decision: str = DECISION_CARDS,
    side: TeamSide = TeamSide.HOME,
) -> None:
    match.record_event(
        EVENT_MANEUVER,
        side=side,
        offense_key=offense_key,
        defense_key=defense_key,
        winner_key=winner_key,
        decision=decision,
    )


class TurnCuttingTests(unittest.TestCase):
    """
    That the flat log reads back as turns, which is what every report
    below is folded over.
    """

    def test_an_event_belongs_to_the_turn_action_before_it(self) -> None:
        match = build_match()
        turn(match)
        maneuver(match, "low_pass", "deflect", "low_pass")
        turn(match, side=TeamSide.VISITING)
        maneuver(match, "high_pass", "steal", "steal")

        turns = stats.match_turns(match)
        self.assertEqual(len(turns), 2)
        self.assertEqual(
            turns[0].first(EVENT_MANEUVER).details["offense_key"],
            "low_pass",
        )
        self.assertEqual(
            turns[1].first(EVENT_MANEUVER).details["offense_key"],
            "high_pass",
        )

    def test_anything_before_the_first_turn_is_dropped(self) -> None:
        """
        A game reaches the log when somebody takes a turn. An event
        before that belongs to setup and has no turn to be counted
        under -- which is a real state, not a defensive branch: a
        halftime token recovery charges exhaustion between turns.
        """
        match = build_match()
        match.record_event(EVENT_GOAL, side=TeamSide.HOME)
        turn(match)

        turns = stats.match_turns(match)
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0].events, [])

    def test_exhaustion_is_charged_to_the_open_turn(self) -> None:
        """
        The attribution `add_exhaustion` makes, asserted through the
        real method rather than by writing the details dict by hand --
        it is the one place the model reaches into the log, and the
        thing worth checking is that a charge lands on the turn that
        made it.
        """
        match = build_match()
        striker = fielded(match, PlayerRole.STRIKER)
        turn(match)
        match.add_exhaustion(striker, 3)
        turn(match, side=TeamSide.VISITING)
        match.add_exhaustion(striker, 1)

        turns = stats.match_turns(match)
        self.assertEqual(turns[0].exhaustion, {striker: 3})
        self.assertEqual(turns[1].exhaustion, {striker: 1})

    def test_a_charge_between_turns_is_attributed_to_nobody(self) -> None:
        match = build_match()
        striker = fielded(match, PlayerRole.STRIKER)
        match.add_exhaustion(striker, 2)

        self.assertEqual(match.exhaustion[striker], 2)
        self.assertEqual(stats.match_turns(match), [])


class PossessionTests(unittest.TestCase):
    def test_consecutive_turns_by_one_side_are_one_possession(self) -> None:
        match = build_match()
        turn(match, side=TeamSide.HOME)
        turn(match, side=TeamSide.HOME)
        turn(match, side=TeamSide.VISITING)
        turn(match, side=TeamSide.HOME)

        runs = stats.possessions(stats.match_turns(match))
        self.assertEqual([len(run) for run in runs], [2, 1, 1])

    def test_a_goal_is_credited_to_every_maneuver_of_its_possession(
        self,
    ) -> None:
        """
        The reason possessions exist. A pass that works pays off on
        the shot it set up a turn later, so charging a maneuver only
        with its own turn's goals would credit the shot's maneuver and
        nothing else.
        """
        match = build_match()
        turn(match)
        maneuver(match, "low_pass", "deflect", "low_pass")
        turn(match)
        maneuver(match, "high_pass", "steal", "high_pass")
        match.record_event(EVENT_GOAL, side=TeamSide.HOME)

        report = stats.collect_maneuvers([match])
        self.assertEqual(report.records["low_pass"].goals_for, 1)
        self.assertEqual(report.records["high_pass"].goals_for, 1)

    def test_the_defending_side_reads_the_same_goal_the_other_way(
        self,
    ) -> None:
        match = build_match()
        turn(match)
        maneuver(match, "high_pass", "steal", "high_pass")
        match.record_event(EVENT_GOAL, side=TeamSide.HOME)

        report = stats.collect_maneuvers([match])
        self.assertEqual(report.records["high_pass"].goals_for, 1)
        self.assertEqual(report.records["steal"].goals_for, 0)
        self.assertEqual(report.records["steal"].goals_against, 1)


class SuccessRateTests(unittest.TestCase):
    """
    Which plays a win rate is measured over, which is a rules question
    rather than an arithmetic one.
    """

    def test_an_uncontested_maneuver_is_not_in_the_denominator(
        self,
    ) -> None:
        """
        The one that matters. An unchallenged maneuver always wins, so
        counting it would report the defense's decision to send nobody
        as the offense card's own success -- and the offense cards a
        coach reaches for unchallenged would all read near 100%.
        """
        match = build_match()
        turn(match)
        maneuver(
            match, "low_pass", None, "low_pass",
            decision=DECISION_UNCONTESTED,
        )
        turn(match)
        maneuver(match, "low_pass", "deflect", "deflect")

        record = stats.collect_maneuvers([match]).records["low_pass"]
        self.assertEqual(record.picks, 2)
        self.assertEqual(record.uncontested, 1)
        self.assertEqual(record.contested, 1)
        self.assertEqual(record.wins, 0)
        self.assertEqual(record.win_rate, 0.0)

    def test_a_skill_test_win_counts_and_is_marked_as_one(self) -> None:
        match = build_match()
        turn(match)
        maneuver(
            match, "low_pass", "deflect", "low_pass",
            decision=DECISION_SKILL_TEST,
        )

        record = stats.collect_maneuvers([match]).records["low_pass"]
        self.assertEqual(record.wins, 1)
        self.assertEqual(record.skill_tests, 1)
        self.assertEqual(record.skill_test_rate, 1.0)

    def test_an_injury_forfeit_is_a_loss_for_the_side_that_forfeited(
        self,
    ) -> None:
        match = build_match()
        turn(match)
        maneuver(
            match, "low_pass", "deflect", "deflect",
            decision=DECISION_INJURY_FORFEIT,
        )

        report = stats.collect_maneuvers([match])
        self.assertEqual(report.records["low_pass"].losses, 1)
        self.assertEqual(report.records["deflect"].wins, 1)
        self.assertEqual(report.records["low_pass"].injury_forfeits, 1)

    def test_a_rate_with_no_denominator_is_none_rather_than_zero(
        self,
    ) -> None:
        """
        A card played once, unchallenged, has no contested plays --
        and "0%" would say it always loses, which is the opposite of
        what happened. The formatters draw None as a dash.
        """
        match = build_match()
        turn(match)
        maneuver(
            match, "low_pass", None, "low_pass",
            decision=DECISION_UNCONTESTED,
        )

        record = stats.collect_maneuvers([match]).records["low_pass"]
        self.assertIsNone(record.win_rate)
        self.assertIsNone(record.skill_test_rate)

    def test_both_sides_of_a_pairing_are_counted(self) -> None:
        match = build_match()
        turn(match)
        maneuver(match, "low_pass", "deflect", "deflect")

        report = stats.collect_maneuvers([match])
        self.assertEqual(report.records["low_pass"].offense_picks, 1)
        self.assertEqual(report.records["low_pass"].defense_picks, 0)
        self.assertEqual(report.records["deflect"].defense_picks, 1)
        self.assertEqual(report.matchups["low_pass"]["deflect"], 1)


class ScopeTests(unittest.TestCase):
    """
    The three kinds of game the author asked to keep apart.
    """

    def test_a_test_game_is_a_test_game_before_it_is_anything_else(
        self,
    ) -> None:
        """
        A test game is one person playing both sides. It is never
        solo, but the check still has to come first -- reading it as
        human-vs-human would count one person's rehearsal as two
        people's match.
        """
        game = build_game(player_2_id=10, test_game=True)
        self.assertEqual(stats.game_category(game), stats.SCOPE_TEST)

    def test_a_game_with_no_second_player_is_dinkys(self) -> None:
        game = build_game(player_2_id=None)
        self.assertEqual(stats.game_category(game), stats.SCOPE_DINKY)

    def test_two_players_is_a_human_game(self) -> None:
        self.assertEqual(
            stats.game_category(build_game()), stats.SCOPE_HUMAN
        )

    def test_every_category_is_a_scope_that_can_be_asked_for(self) -> None:
        """
        A category with no scope behind it would be a group of games
        nothing could ever report on.
        """
        for game in (
            build_game(),
            build_game(player_2_id=None),
            build_game(player_2_id=10, test_game=True),
        ):
            category = stats.game_category(game)
            self.assertIn(category, stats.SCOPE_LABELS)
            self.assertEqual(
                stats.games_in_scope([game], category), [game]
            )
            self.assertEqual(stats.games_in_scope([game], stats.SCOPE_ALL), [game])


class SourceTests(unittest.TestCase):
    """
    Which system a game was played on: the second cut, across the
    kinds. Read off `guild_id`, which a Discord game always has and a
    web game never does.
    """

    def test_a_game_in_a_server_is_discords(self) -> None:
        self.assertEqual(
            stats.game_source(build_game(guild_id=1)), stats.SOURCE_DISCORD,
        )

    def test_a_game_in_no_server_is_the_web_apps(self) -> None:
        game = build_game(guild_id=None, channel_id=None)
        self.assertEqual(stats.game_source(game), stats.SOURCE_WEB)

    def test_a_source_cuts_across_the_kinds(self) -> None:
        bot = build_game(game_id="bot", player_2_id=None)
        web = build_game(
            game_id="web", guild_id=None, channel_id=None, player_2_id=None,
        )
        games = [bot, web]
        for source, expected in (
            (stats.SOURCE_DISCORD, [bot]),
            (stats.SOURCE_WEB, [web]),
            (stats.SOURCE_BOTH, [bot, web]),
        ):
            self.assertEqual(
                stats.games_in_scope(games, stats.SCOPE_DINKY, source),
                expected,
            )
            self.assertEqual(
                stats.games_in_scope(games, stats.SCOPE_HUMAN, source), [],
            )

    def test_every_source_has_a_label(self) -> None:
        for source in (
            stats.SOURCE_DISCORD, stats.SOURCE_WEB, stats.SOURCE_BOTH,
        ):
            heading = "\n".join(
                stats.format_scope_heading(stats.SCOPE_ALL, 1, 0, source)
            )
            self.assertIn(stats.SOURCE_LABELS[source], heading)

    def test_the_heading_says_when_there_are_no_web_games(self) -> None:
        heading = "\n".join(
            stats.format_scope_heading(
                stats.SCOPE_ALL, 0, 0, stats.SOURCE_WEB, no_web_games=True,
            )
        )
        self.assertIn("no web games yet", heading)


class OverviewTests(unittest.TestCase):
    def test_an_abandoned_game_is_counted_but_its_score_is_not_a_result(
        self,
    ) -> None:
        """
        Both ways of reaching FINISHED leave a scoreboard behind, and
        only one of them left a result on it. See
        `D12BallGame.abandoned`.
        """
        match = build_match()
        match.scoreboard.home_score = 3
        game = build_game()
        game.start_game()
        game.abandon()

        report = stats.collect_overview([(game, match)])
        self.assertEqual(report.finished, 1)
        self.assertEqual(report.abandoned, 1)
        self.assertEqual(report.results, [])
        self.assertEqual(report.home_wins, 0)

    def test_a_played_out_game_names_its_winner(self) -> None:
        match = build_match()
        match.scoreboard.home_score = 2
        match.scoreboard.visiting_score = 1
        game = build_game()
        game.start_game()
        game.finish_game()

        report = stats.collect_overview([(game, match)])
        self.assertEqual(report.home_wins, 1)
        self.assertEqual(report.visiting_wins, 0)
        self.assertFalse(report.results[0].went_to_shootout)

    def test_a_shootout_is_not_added_to_the_score_a_second_time(
        self,
    ) -> None:
        """
        `shootout_goals` is a tally, not a second scoreboard -- the
        goals are already on it. Adding them would double every
        shootout goal in the game.
        """
        match = build_match()
        match.scoreboard.home_score = 4
        match.scoreboard.visiting_score = 3
        match.shootout_goals = {"home": 4, "visiting": 3}
        game = build_game()
        game.start_game()
        game.finish_game()

        result = stats.collect_overview([(game, match)]).results[0]
        self.assertEqual((result.home_score, result.visiting_score), (4, 3))
        self.assertEqual(result.winner, TeamSide.HOME)
        self.assertTrue(result.went_to_shootout)

    def test_a_game_with_nothing_recorded_is_counted_and_said_so(
        self,
    ) -> None:
        """
        A game saved before the log existed. It must not vanish from
        the count, or a report would stand on four games out of nine
        and say nine.
        """
        report = stats.collect_overview([(build_game(), build_match())])
        self.assertEqual(report.total, 1)
        self.assertEqual(report.games_without_events, 1)


class ShotTests(unittest.TestCase):
    def test_set_up_shots_are_split_out_from_the_rest(self) -> None:
        match = build_match()
        turn(match, action="shoot")
        match.record_event(
            EVENT_SHOT, scored=True, set_up=True, defender_count=0,
        )
        turn(match, action="shoot")
        match.record_event(
            EVENT_SHOT, scored=False, set_up=False, defender_count=2,
        )

        report = stats.collect_shots([match])
        self.assertEqual(report.attempts, 2)
        self.assertEqual(report.goals, 1)
        self.assertEqual(report.set_up_conversion, 1.0)
        self.assertEqual(report.plain_conversion, 0.0)
        self.assertEqual(report.by_defenders, {0: [1, 1], 2: [1, 0]})


class ConditionTests(unittest.TestCase):
    def test_injury_tests_are_counted_whether_or_not_they_injure(
        self,
    ) -> None:
        """
        A log holding only the failures has no denominator, and the
        rate is the whole question -- see `run_injury_test`, which
        logs both for this reason.
        """
        match = build_match()
        turn(match)
        match.record_event(EVENT_INJURY_TEST, player_id="a", injured=False)
        match.record_event(EVENT_INJURY_TEST, player_id="b", injured=True)

        report = stats.collect_conditions([match])
        self.assertEqual(report.injury_tests, 2)
        self.assertEqual(report.injuries, 1)
        self.assertEqual(report.injury_rate, 0.5)
        self.assertEqual(report.injuries_by_player["b"], 1)

    def test_a_tie_that_re_rolls_is_counted_as_a_roll(self) -> None:
        match = build_match()
        turn(match)
        match.record_event(EVENT_SKILL_TEST, tied=True)
        match.record_event(EVENT_SKILL_TEST, tied=False)

        report = stats.collect_conditions([match])
        self.assertEqual(report.skill_tests, 2)
        self.assertEqual(report.skill_test_ties, 1)


class SerializationTests(unittest.TestCase):
    def test_the_log_survives_a_save_and_a_load(self) -> None:
        match = build_match()
        turn(match, exhaustion={"someone": 2})
        maneuver(match, "low_pass", "deflect", "deflect")

        restored = MatchState.from_dict(
            match.to_dict(), load_basic_ruleset(),
        )
        self.assertEqual(
            [event.to_dict() for event in restored.events],
            [event.to_dict() for event in match.events],
        )

    def test_a_save_written_before_the_log_loads_with_an_empty_one(
        self,
    ) -> None:
        """
        Both developers run the bot against their own saves, so a
        half-finished game outlives the commit that added the field.
        """
        data = build_match().to_dict()
        del data["events"]

        restored = MatchState.from_dict(data, load_basic_ruleset())
        self.assertEqual(restored.events, [])

    def test_two_matches_do_not_share_one_empty_log(self) -> None:
        """
        The mutable-default bug, which `SavedField` splits `default`
        and `factory` to avoid. It would show as every game in the
        save file reporting every other game's turns.
        """
        first = build_match()
        second = build_match()
        turn(first)
        self.assertEqual(second.events, [])


class TableTests(unittest.TestCase):
    """
    The tables go into a Discord code block, which scrolls rather than
    wraps.
    """

    def setUp(self) -> None:
        self.catalog = load_maneuver_catalog()
        self.match = build_match()
        turn(self.match, exhaustion={"a": 2})
        maneuver(self.match, "low_pass", "deflect", "deflect")
        turn(self.match, action="shoot")
        self.match.record_event(
            EVENT_SHOT, scored=True, set_up=True, defender_count=1,
        )
        self.match.record_event(EVENT_GOAL, side=TeamSide.HOME, player_id="a")
        self.report = stats.collect_maneuvers([self.match])

    def test_a_time_out_is_counted_but_is_not_a_turn(self) -> None:
        # The author, 2026-09-16: recorded for the statistics, but not
        # as a turn action -- a possession is a run of consecutive turn
        # actions by one side, and a pause is not a turn anybody
        # played. It sits below the rule, with no share of the turns'
        # denominator.
        match = build_match()
        turn(match, action="maneuver")
        match.record_event(EVENT_TIME_OUT, side=TeamSide.HOME)
        turn(match, action="shoot")
        report = stats.collect_maneuvers([match])

        self.assertEqual(report.turns, 2)
        self.assertEqual(report.time_outs, 1)
        self.assertNotIn("time_out", report.actions)

        table = "\n".join(stats.format_turn_actions(report))
        self.assertIn("time outs called", table)
        # No percentage on that row: it has no claim on the turns.
        self.assertNotIn("%", table.rsplit("time outs called", 1)[1])

    def every_table(self) -> list[list[str]]:
        conditions = stats.collect_conditions([self.match])
        return [
            stats.format_scope_heading(stats.SCOPE_ALL, 3, 1),
            stats.format_turn_actions(self.report),
            stats.format_maneuver_usage(self.report, self.catalog),
            stats.format_maneuver_cost(self.report, self.catalog),
            stats.format_matchups(self.report, self.catalog),
            stats.format_shots(stats.collect_shots([self.match])),
            stats.format_conditions(conditions),
            stats.format_players(conditions, lambda player_id: player_id),
            stats.format_roles(conditions, load_player_catalog()),
            stats.format_overview(
                stats.collect_overview([(build_game(), self.match)])
            ),
        ]

    def test_no_row_is_wider_than_the_fence(self) -> None:
        for table in self.every_table():
            for line in table:
                self.assertLessEqual(
                    len(line),
                    stats.TABLE_WIDTH,
                    f"{line!r} is {len(line)} characters",
                )

    def test_no_row_carries_trailing_space(self) -> None:
        """
        Invisible in a terminal, and not in a code block -- it widens
        the fence and shifts the table off centre on a phone.
        """
        for table in self.every_table():
            for line in table:
                self.assertEqual(line, line.rstrip())

    def test_a_rule_is_drawn_to_its_own_table_and_no_wider(self) -> None:
        for table in self.every_table():
            body = [line for line in table if set(line) - set("-=")]
            rules = [line for line in table if line and not (set(line) - set("-="))]
            if not rules or not body:
                continue
            widest = max(len(line) for line in body)
            for rule in rules:
                self.assertLessEqual(len(rule), widest)

    def test_the_heading_says_how_many_games_had_nothing_recorded(
        self,
    ) -> None:
        heading = " ".join(
            stats.format_scope_heading(stats.SCOPE_ALL, 9, 5)
        )
        self.assertIn("9", heading)
        self.assertIn("5", heading)

    def test_a_rate_with_no_denominator_is_drawn_as_a_dash(self) -> None:
        empty = stats.collect_shots([build_match()])
        rendered = "\n".join(stats.format_shots(empty))
        self.assertIn("-", rendered)
        self.assertNotIn("0%", rendered)

    def test_the_rows_are_in_the_catalogs_own_order(self) -> None:
        """
        Rank order, not frequency: a table whose rows move between two
        runs cannot be compared with the one a coach read last week.
        """
        keys = ["deflect", "low_pass", "high_pass"]
        catalogued = [
            maneuver.key
            for maneuver in self.catalog.offense + self.catalog.defense
        ]
        ordered = stats.maneuver_order(self.catalog, keys)
        self.assertEqual(
            ordered,
            [key for key in catalogued if key in set(keys)],
        )

    def test_a_maneuver_the_catalog_no_longer_carries_still_appears(
        self,
    ) -> None:
        """
        A game saved against an older `maneuvers.json` holds a key the
        catalog has since dropped. Leaving it out would quietly shrink
        the totals it is part of.
        """
        ordered = stats.maneuver_order(
            self.catalog, ["low_pass", "retired_card"],
        )
        self.assertIn("retired_card", ordered)
        self.assertEqual(ordered[-1], "retired_card")


class FakeResponse:
    def __init__(self) -> None:
        self.deferred = False

    async def defer(self, ephemeral: bool = False) -> None:
        self.deferred = True

    def is_done(self) -> bool:
        # Every caller reaches these deep in a cascade whose own
        # response was already given earlier -- see `send_new_prompt`
        # in cogs/d12ball_helpers.py -- so this is always True here,
        # independent of whether this particular fixture ever called
        # `defer`.
        return True


class FakeMessageable:
    def __init__(self) -> None:
        self.sent: list[tuple[str, bool]] = []

    async def send(self, content=None, **kwargs):
        self.sent.append((content, kwargs.get("ephemeral")))
        return SimpleNamespace(id=len(self.sent))


class FakeFollowup(FakeMessageable):
    pass


class FakeThread(FakeMessageable):
    mention = "<#9001>"


class FakeChannel(FakeMessageable):
    name = "d12ball-pbd1"

    def __init__(self) -> None:
        super().__init__()
        self.thread = FakeThread()
        self.create_thread_calls: list[dict] = []

    async def create_thread(self, **kwargs):
        self.create_thread_calls.append(kwargs)
        return self.thread


def build_interaction(channel_id: int = 2, guild_id: int = 1, in_thread=False):
    interaction = mock.Mock()
    interaction.response = FakeResponse()
    interaction.followup = FakeFollowup()
    interaction.channel = (
        mock.Mock(spec=discord.Thread) if in_thread else FakeChannel()
    )
    if in_thread:
        interaction.channel.send = mock.AsyncMock()
    interaction.channel_id = channel_id
    interaction.guild_id = guild_id
    return interaction


def build_cog() -> D12Ball:
    cog = object.__new__(D12Ball)
    cog.games = {}
    cog.player_catalog = load_player_catalog()
    cog.maneuver_catalog = load_maneuver_catalog()
    cog.basic_ruleset = load_basic_ruleset()
    cog.ai_strategies = build_ai_strategies(
        cog.player_catalog, cog.maneuver_catalog,
    )
    cog.engine = RulesEngine(
        cog.player_catalog,
        cog.basic_ruleset,
        cog.maneuver_catalog,
        cog.ai_strategies,
    )
    return cog


def played_game(cog: D12Ball, **overrides) -> D12BallGame:
    """A game with one turn in it, filed on the cog."""
    game = build_game(**overrides)
    match = build_match()
    turn(match)
    maneuver(match, "low_pass", "deflect", "deflect")
    game.match_state = match.to_dict()
    cog.games[game.game_id] = game
    return game


class CommandTests(unittest.IsolatedAsyncioTestCase):
    """
    The five commands, at the seam where a scope becomes a set of
    matches.
    """

    async def run_command(self, cog, name, interaction, **kwargs):
        await getattr(type(cog), name).callback(cog, interaction, **kwargs)
        return interaction.followup.sent

    async def test_another_servers_games_are_not_counted(self) -> None:
        """
        `self.games` is every game on every server the bot is in. One
        server's players have no business reading another's, and there
        is deliberately no option to widen it.
        """
        cog = build_cog()
        played_game(cog, game_id="ours", guild_id=1, channel_id=2)
        played_game(cog, game_id="theirs", guild_id=99, channel_id=3)

        pairs, _, heading = cog.stats_matches(
            build_interaction(guild_id=1), stats.SCOPE_ALL,
        )
        self.assertEqual([game.game_id for game, _ in pairs], ["ours"])
        self.assertIn("1 all games", heading)

    async def test_a_scope_only_counts_its_own_kind_of_game(self) -> None:
        cog = build_cog()
        played_game(cog, game_id="human", player_2_id=11)
        played_game(cog, game_id="solo", player_2_id=None, channel_id=3)
        played_game(
            cog, game_id="test", player_2_id=10, test_game=True, channel_id=4,
        )

        for scope, expected in (
            (stats.SCOPE_HUMAN, ["human"]),
            (stats.SCOPE_DINKY, ["solo"]),
            (stats.SCOPE_TEST, ["test"]),
        ):
            pairs, _, _ = cog.stats_matches(build_interaction(), scope)
            self.assertEqual(
                sorted(game.game_id for game, _ in pairs), expected,
            )

    async def test_a_game_whose_match_will_not_load_is_left_out_not_fatal(
        self,
    ) -> None:
        """
        A saved game older than a player rename refuses to build --
        see the legacy-migration gotcha in docs/design/gotchas.md. A report that
        dies on one bad record is worse than one that counts the other
        forty.
        """
        cog = build_cog()
        played_game(cog, game_id="good")
        broken = played_game(cog, game_id="broken", channel_id=3)
        broken.match_state = dict(broken.match_state)
        broken.match_state["home"] = {"nonsense": True}

        pairs, empty, heading = cog.stats_matches(
            build_interaction(), stats.SCOPE_ALL,
        )
        self.assertEqual([game.game_id for game, _ in pairs], ["good"])
        self.assertEqual(empty, 1)
        self.assertIn("nothing recorded", heading)

    async def test_this_game_reads_the_channels_own_game(self) -> None:
        cog = build_cog()
        played_game(cog, game_id="here", channel_id=2)
        played_game(cog, game_id="elsewhere", channel_id=3)

        pairs, _, _ = cog.stats_matches(
            build_interaction(channel_id=3), stats.SCOPE_THIS_GAME,
        )
        self.assertEqual([game.game_id for game, _ in pairs], ["elsewhere"])

    async def test_a_channel_with_no_game_is_told_so_rather_than_raising(
        self,
    ) -> None:
        cog = build_cog()
        sent = await self.run_command(
            cog, "stats_game", build_interaction(channel_id=404),
        )
        self.assertEqual(len(sent), 1)
        self.assertIn("no D12 Ball game", sent[0][0])

    async def test_a_game_with_nothing_recorded_says_so(self) -> None:
        """
        A game that was already under way when the bot started keeping
        a log. Reporting zeroes at a coach would read as a game in
        which nothing had happened.
        """
        cog = build_cog()
        game = build_game()
        game.match_state = build_match().to_dict()
        cog.games[game.game_id] = game

        sent = await self.run_command(
            cog, "stats_game", build_interaction(),
        )
        self.assertEqual(len(sent), 1)
        self.assertIn("Nothing has been played yet", sent[0][0])

    async def test_a_scope_with_no_games_reports_nothing_rather_than_zero(
        self,
    ) -> None:
        cog = build_cog()
        sent = await self.run_command(
            cog, "stats_maneuvers", build_interaction(), scope=None,
        )
        self.assertEqual(len(sent), 1)
        self.assertIn("nothing to report", sent[0][0])

    STATS_COMMANDS = (
        "stats_game",
        "stats_maneuvers",
        "stats_matchups",
        "stats_overview",
        "stats_players",
    )

    async def test_a_report_goes_in_a_thread_of_its_own_unless_shared(
        self,
    ) -> None:
        """
        A stats dump is several messages of wide code block, and a
        coach asking about maneuver usage mid-game is not asking to
        put them into the channel both sides are playing in -- but an
        ephemeral one was gone on the next restart and invisible to
        the other coach. So it goes in a thread, and the caller is
        pointed at it.
        """
        for name in self.STATS_COMMANDS:
            kwargs = {} if name == "stats_game" else {"scope": None}

            cog = build_cog()
            played_game(cog)
            interaction = build_interaction()
            await self.run_command(cog, name, interaction, share=False, **kwargs)

            self.assertEqual(
                len(interaction.channel.create_thread_calls), 1, name,
            )
            thread_blocks = [c for c, _ in interaction.channel.thread.sent]
            self.assertTrue(
                any(c.startswith("```") for c in thread_blocks), name,
            )
            # Nothing fenced reaches the channel or the caller directly.
            self.assertFalse(
                any(c.startswith("```") for c, _ in interaction.channel.sent),
                name,
            )
            for content, ephemeral in interaction.followup.sent:
                self.assertFalse(content.startswith("```"), name)
            self.assertTrue(
                all(e for _, e in interaction.followup.sent), name,
            )

    async def test_sharing_posts_straight_into_the_channel(self) -> None:
        for name in self.STATS_COMMANDS:
            kwargs = {} if name == "stats_game" else {"scope": None}

            cog = build_cog()
            played_game(cog)
            interaction = build_interaction()
            sent = await self.run_command(
                cog, name, interaction, share=True, **kwargs
            )

            self.assertEqual(interaction.channel.create_thread_calls, [], name)
            fenced = [c for c, _ in sent if c.startswith("```")]
            self.assertTrue(fenced, name)
            for block in fenced:
                self.assertTrue(block.endswith("```"), name)
            for _, ephemeral in sent:
                self.assertFalse(ephemeral, name)

    async def test_a_command_run_in_a_thread_stays_there(self) -> None:
        """Threads do not nest, so a report asked for inside one is
        posted in it rather than starting a child thread."""
        cog = build_cog()
        played_game(cog)
        interaction = build_interaction(in_thread=True)
        sent = await self.run_command(
            cog, "stats_maneuvers", interaction, share=False, scope=None,
        )
        fenced = [c for c, _ in sent if c and c.startswith("```")]
        self.assertTrue(fenced)

    async def test_a_scope_choice_is_offered_for_every_category(
        self,
    ) -> None:
        """
        A category with no choice behind it is a group of games
        nothing could ever report on -- and the choices are what
        Discord shows, so a missing one is a scope a coach cannot ask
        for even though the code would answer it.
        """
        offered = {choice.value for choice in D12Ball.STATS_SCOPE_CHOICES}
        self.assertEqual(offered, set(stats.SCOPE_LABELS))


class RollsReachTheLogTests(unittest.IsolatedAsyncioTestCase):
    """
    That the two rolls the tutorial and the matchup sweep never reach
    -- an injury test and an own-goal roll -- log what they did, and
    that what they logged **survives the save**.

    The reload is the whole point of these two. An event written onto
    a match and not persisted is invisible until the next click loads
    the match back out of the save file, which no unit test asserting
    on the live object would ever notice -- and is exactly how beat 1
    of the tutorial went missing. So each of these asserts against
    `load_match_state`, never against the match it just passed in.
    """

    def build_cog(self) -> D12Ball:
        cog = build_cog()
        cog.team_emojis = {}
        cog.refresh_match_image = mock.AsyncMock()
        cog.begin_run_back = mock.AsyncMock()
        cog.finish_maneuver_resolution = mock.AsyncMock()
        cog.continue_injury_tests = mock.AsyncMock()
        return cog

    def build_interaction(self):
        return SimpleNamespace(
            user=SimpleNamespace(id=10, display_name="One"),
            channel=SimpleNamespace(
                send=mock.AsyncMock(return_value=SimpleNamespace(id=999)),
            ),
            guild=None,
            followup=SimpleNamespace(
                send=mock.AsyncMock(return_value=SimpleNamespace(id=999)),
            ),
            response=SimpleNamespace(
                defer=mock.AsyncMock(),
                edit_message=mock.AsyncMock(),
                send_message=mock.AsyncMock(),
                is_done=lambda: True,
            ),
            edit_original_response=mock.AsyncMock(),
        )

    def on_the_ball(self, match: MatchState) -> str:
        """A home player standing on the ball, which both rolls need."""
        player_id = match.home.field_players[0]
        zone, space_index = match.board.meeple_position(player_id)
        match.ball.possession = TeamSide.HOME
        match.set_ball_space(zone, space_index)
        match.active_player_id = player_id
        return player_id

    async def run_injury_test(self, cog, game, match, player_id, roll):
        with suppressed_cog_saves(), mock.patch(
            "random.Random.randint", return_value=roll,
        ), mock.patch("cogs.d12ball.core.render_injury_test_die"), mock.patch(
            "discord.File",
        ):
            await run_injury_test(cog, 
                self.build_interaction(),
                game,
                match,
                cog.engine.get_player_definition(player_id),
            )

    async def test_an_injury_test_logs_whichever_way_it_goes(self) -> None:
        for roll, injured in ((12, False), (1, True)):
            with self.subTest(injured=injured):
                cog = self.build_cog()
                match = build_match()
                game = build_game()
                cog.games[game.game_id] = game
                player_id = self.on_the_ball(match)
                match.add_exhaustion(player_id, 6)
                match.pending_injury_tests = [player_id]
                game.match_state = match.to_dict()

                await self.run_injury_test(cog, game, match, player_id, roll)

                logged = [
                    event
                    for event in cog.engine.load_match_state(game).events
                    if event.kind == EVENT_INJURY_TEST
                ]
                self.assertEqual(len(logged), 1)
                self.assertEqual(logged[0].player_id, player_id)
                self.assertEqual(logged[0].details["injured"], injured)
                self.assertEqual(logged[0].side, TeamSide.HOME)

    async def test_an_own_goal_roll_logs_whichever_way_it_goes(self) -> None:
        for roll, conceded in ((12, False), (1, True)):
            with self.subTest(conceded=conceded):
                cog = self.build_cog()
                match = build_match()
                game = build_game()
                cog.games[game.game_id] = game
                player_id = self.on_the_ball(match)
                match.pending_own_goal = True
                match.pending_own_goal_distance = 1
                game.match_state = match.to_dict()

                with suppressed_cog_saves(), mock.patch(
                    "random.Random.randint", return_value=roll,
                ), mock.patch(
                    "cogs.d12ball.effects.render_own_goal_dice",
                ), mock.patch("discord.File"):
                    await run_own_goal_roll(cog, 
                        self.build_interaction(), game, match,
                    )

                logged = [
                    event
                    for event in cog.engine.load_match_state(game).events
                    if event.kind == EVENT_OWN_GOAL_ROLL
                ]
                self.assertEqual(len(logged), 1)
                self.assertEqual(logged[0].details["conceded"], conceded)

    async def test_a_conceded_own_goal_reaches_the_statistics(self) -> None:
        """
        The whole chain for the one goal nobody meant to score: the
        roll is logged, `concede_own_goal` logs the goal beside it,
        and the fold reads both back.
        """
        cog = self.build_cog()
        match = build_match()
        game = build_game()
        cog.games[game.game_id] = game
        player_id = self.on_the_ball(match)
        match.pending_own_goal = True
        match.pending_own_goal_distance = 1
        game.match_state = match.to_dict()

        with suppressed_cog_saves(), mock.patch(
            "random.Random.randint", return_value=1,
        ), mock.patch(
            "cogs.d12ball.effects.render_own_goal_dice",
        ), mock.patch("discord.File"):
            await run_own_goal_roll(cog, 
                self.build_interaction(), game, match,
            )

        reloaded = cog.engine.load_match_state(game)
        shots = stats.collect_shots([reloaded])
        self.assertEqual(shots.own_goal_rolls, 1)
        self.assertEqual(shots.own_goals, 1)

        overview = stats.collect_overview([(game, reloaded)])
        self.assertEqual(overview.goals, 1)
        self.assertEqual(overview.own_goals, 1)

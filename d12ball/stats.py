"""
Every statistic the bot reports, as a fold over the match event log.

**Nothing here touches Discord and nothing here touches the game
flow**, which is the whole point: a statistic is a reading of what
happened, and a reading that could change what happens is a bug
waiting to be written. The one input is `MatchState.events` (see
`MatchEvent`) plus the game records around it; the one output is
plain data -- and the plain-text tables at the foot of this file,
which `cogs/d12ball/slash_commands.py` posts in a code fence and
nothing else consumes. The tables live here rather than in the cog
for the reason `d12ball/formatting.py` exists: they are words about
match data with no Discord in them, and a formatter that cannot
import discord cannot grow a dependency on a live interaction.

Three layers, each built on the one above:

- **Turns.** `match_turns` cuts the flat log into turns, because the
  log's order is its structure: every event belongs to the last
  `turn_action` before it. Everything below reads turns, never the
  raw list.
- **Possessions.** `possessions` groups consecutive turns by the side
  taking them, which is what makes "a goal that followed this
  maneuver" answerable -- a maneuver's payoff is rarely on its own
  turn.
- **Reports.** One function per command, each returning a dataclass
  the caller formats.

**A game with no events is not a game with no statistics -- it is a
game the bot was not counting yet.** Every report carries its own
`games_without_events`, and the formatters say so out loud, for the
reason `build_goal_log` counts itself against the scoreboard rather
than trusting the two agree: a table that silently reports on four
games out of nine is worse than one that reports on four and says it.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Iterable, Optional

from d12ball.components import (
    CONTESTED_DECISIONS,
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
    ManeuverCatalog,
    MatchEvent,
    MatchState,
    PlayerCatalog,
    TeamSide,
)
from d12ball.game import D12BallGame, GameStatus


# The three kinds of game the statistics are kept apart by, which is
# how the author asked for them and is also the only split that means
# anything: Dinky plays one strategy, and a test game
# is one person moving both sides, so folding either into the
# human-vs-human numbers would report a habit of the bot's as a habit
# of the players'.
SCOPE_DINKY = "dinky"
SCOPE_TEST = "test"
SCOPE_HUMAN = "human"
SCOPE_ALL = "all"
SCOPE_THIS_GAME = "this_game"

SCOPE_LABELS = {
    SCOPE_DINKY: "games against Dinky",
    SCOPE_TEST: "test games",
    SCOPE_HUMAN: "games between two players",
    SCOPE_ALL: "all games",
    SCOPE_THIS_GAME: "this game",
}


def game_category(game: D12BallGame) -> str:
    """
    Which of the three a game belongs to.

    **Test first.** A test game is one person playing both sides and
    is never solo, but the check has to come first anyway: a test game
    is a rehearsal whichever way it was set up, and reading it as
    human-vs-human would count one person's experiment as two people's
    match.
    """
    if game.test_game:
        return SCOPE_TEST
    if game.is_solo_game:
        return SCOPE_DINKY
    return SCOPE_HUMAN


def games_in_scope(
    games: Iterable[D12BallGame],
    scope: str,
) -> list[D12BallGame]:
    """
    Every game the scope covers, still in setup or not.

    Games in setup are kept rather than filtered: they have no events,
    so they contribute nothing to any total, and dropping them here
    would make `games_without_events` under-report by exactly the
    games nobody has played yet.
    """
    if scope == SCOPE_ALL:
        return list(games)
    return [game for game in games if game_category(game) == scope]


@dataclass
class Turn:
    """
    One turn: the action a coach chose, and everything that followed
    it before the next coach chose.

    `exhaustion` is the whole turn's charge, not one player's and not
    one maneuver's -- see `add_exhaustion`. A turn's cost is shared by
    both sides (a tie charges each of them a token, a walk-in charges
    the side that walked), so a per-maneuver figure built off this is
    "what a turn playing this card cost, all in", which is what it is
    called everywhere below. Splitting it further would be inventing
    an attribution the log does not carry.
    """

    action: str
    side: Optional[TeamSide]
    player_id: Optional[str]
    by_ai: bool
    period: str
    time: int
    exhaustion: dict[str, int]
    events: list[MatchEvent]

    def of_kind(self, kind: str) -> list[MatchEvent]:
        return [event for event in self.events if event.kind == kind]

    def first(self, kind: str) -> Optional[MatchEvent]:
        found = self.of_kind(kind)
        return found[0] if found else None

    @property
    def exhaustion_total(self) -> int:
        return sum(self.exhaustion.values())

    @property
    def injuries(self) -> int:
        return sum(
            1
            for event in self.of_kind(EVENT_INJURY_TEST)
            if event.details.get("injured")
        )


def match_turns(match: MatchState) -> list[Turn]:
    """
    The match's log cut into turns.

    Anything logged before the first `turn_action` is dropped, which
    is right: a game only reaches the log once somebody takes a turn,
    and an event before that belongs to setup.
    """
    turns: list[Turn] = []
    for event in match.events:
        if event.kind == EVENT_TURN_ACTION:
            turns.append(
                Turn(
                    action=event.details.get("action", ""),
                    side=event.side,
                    player_id=event.player_id,
                    by_ai=bool(event.details.get("by_ai")),
                    period=event.period.value,
                    time=event.time,
                    exhaustion=dict(event.details.get("exhaustion", {})),
                    events=[],
                )
            )
        elif turns:
            turns[-1].events.append(event)
    return turns


def possessions(turns: list[Turn]) -> list[list[Turn]]:
    """
    Consecutive turns by the same side, grouped.

    This is the unit a maneuver's payoff is measured over: a Low Pass
    that works pays off two turns later, on the shot it set up, and
    charging it only with goals scored on its own turn would credit
    the High Pass and nothing else. A side keeps the ball until it
    does not, so a run of turns is exactly a possession.
    """
    runs: list[list[Turn]] = []
    for turn in turns:
        if runs and runs[-1][-1].side == turn.side:
            runs[-1].append(turn)
        else:
            runs.append([turn])
    return runs


@dataclass
class ManeuverRecord:
    """One maneuver's line in the usage table."""

    key: str
    offense_picks: int = 0
    defense_picks: int = 0
    wins: int = 0
    losses: int = 0
    uncontested: int = 0
    skill_tests: int = 0
    injury_forfeits: int = 0
    # The turn totals for every turn this was played in -- see Turn.
    exhaustion: int = 0
    injuries: int = 0
    # Goals in the possession this was played in, split by whether
    # they went to the side that played it.
    goals_for: int = 0
    goals_against: int = 0

    @property
    def picks(self) -> int:
        return self.offense_picks + self.defense_picks

    @property
    def contested(self) -> int:
        """
        Plays that were actually a contest.

        **An uncontested maneuver is excluded from every rate below**,
        and that is a rules point rather than a modelling nicety: a
        maneuver nobody challenged always wins, so counting those
        would report the defense's decision to send nobody as the
        offense card's own success. See CONTESTED_DECISIONS.
        """
        return self.wins + self.losses

    @property
    def win_rate(self) -> Optional[float]:
        return self.wins / self.contested if self.contested else None

    @property
    def skill_test_rate(self) -> Optional[float]:
        return self.skill_tests / self.contested if self.contested else None

    @property
    def exhaustion_per_play(self) -> Optional[float]:
        return self.exhaustion / self.picks if self.picks else None

    @property
    def goals_per_play(self) -> Optional[float]:
        return self.goals_for / self.picks if self.picks else None


@dataclass
class ManeuverReport:
    records: dict[str, ManeuverRecord] = field(default_factory=dict)
    # offense key -> defense key -> times they met.
    matchups: dict[str, Counter] = field(
        default_factory=lambda: defaultdict(Counter)
    )
    turns: int = 0
    actions: Counter = field(default_factory=Counter)
    # Time outs are counted apart from the actions, because a time out
    # is not a turn: it is a pause inside one side's possession, and
    # the log records it as its own event kind for exactly that reason
    # (see EVENT_TIME_OUT). Counting it as an action would give it a
    # share of a denominator it is not part of.
    time_outs: int = 0
    games_counted: int = 0

    def record(self, key: str) -> ManeuverRecord:
        if key not in self.records:
            self.records[key] = ManeuverRecord(key=key)
        return self.records[key]

    @property
    def total_picks(self) -> int:
        return sum(record.picks for record in self.records.values())


def collect_maneuvers(matches: Iterable[MatchState]) -> ManeuverReport:
    """
    Fold every match's turns into the maneuver table.

    Both keys of a pairing are counted, on both sides of it: a
    maneuver's record is what happened when it was played, and it was
    played by whoever picked it. The winner decides which of the two
    gets the win, and `decision` decides whether either does -- see
    ManeuverRecord.contested.
    """
    report = ManeuverReport()

    for match in matches:
        turns = match_turns(match)
        if not turns:
            continue
        report.games_counted += 1
        report.turns += len(turns)
        for turn in turns:
            report.actions[turn.action] += 1
        report.time_outs += sum(
            1 for event in match.events if event.kind == EVENT_TIME_OUT
        )

        # Goals are attributed to the whole possession, so they are
        # counted once here and shared out to every maneuver played in
        # it -- a maneuver that kept the ball moving is part of the
        # goal it led to, and the log cannot say which of them mattered
        # more.
        for run in possessions(turns):
            goals_for = 0
            goals_against = 0
            for turn in run:
                for goal in turn.of_kind(EVENT_GOAL):
                    if goal.side == run[0].side:
                        goals_for += 1
                    else:
                        goals_against += 1

            for turn in run:
                maneuver = turn.first(EVENT_MANEUVER)
                if maneuver is None:
                    continue
                details = maneuver.details
                offense_key = details.get("offense_key")
                defense_key = details.get("defense_key")
                winner_key = details.get("winner_key")
                decision = details.get("decision")
                contested = decision in CONTESTED_DECISIONS

                if offense_key and defense_key:
                    report.matchups[offense_key][defense_key] += 1

                for key, is_offense in (
                    (offense_key, True),
                    (defense_key, False),
                ):
                    if not key:
                        continue
                    record = report.record(key)
                    if is_offense:
                        record.offense_picks += 1
                    else:
                        record.defense_picks += 1
                    record.exhaustion += turn.exhaustion_total
                    record.injuries += turn.injuries
                    # A card's goals are its *own side's*: the offense
                    # picked with the ball, the defense picked without
                    # it, so the same possession's goals read opposite
                    # ways for the two of them.
                    record.goals_for += goals_for if is_offense else goals_against
                    record.goals_against += (
                        goals_against if is_offense else goals_for
                    )

                    if decision == DECISION_UNCONTESTED:
                        record.uncontested += 1
                        continue
                    if decision == DECISION_SKILL_TEST:
                        record.skill_tests += 1
                    if decision == DECISION_INJURY_FORFEIT:
                        record.injury_forfeits += 1
                    if contested:
                        if key == winner_key:
                            record.wins += 1
                        else:
                            record.losses += 1

    return report


@dataclass
class ShotReport:
    attempts: int = 0
    goals: int = 0
    set_up_attempts: int = 0
    set_up_goals: int = 0
    # Conversion against the number of defenders in the way, which is
    # the one thing a coach positions for.
    by_defenders: dict[int, list[int]] = field(default_factory=dict)
    own_goal_rolls: int = 0
    own_goals: int = 0

    @property
    def conversion(self) -> Optional[float]:
        return self.goals / self.attempts if self.attempts else None

    @property
    def set_up_conversion(self) -> Optional[float]:
        if not self.set_up_attempts:
            return None
        return self.set_up_goals / self.set_up_attempts

    @property
    def plain_attempts(self) -> int:
        return self.attempts - self.set_up_attempts

    @property
    def plain_conversion(self) -> Optional[float]:
        plain = self.plain_attempts
        if not plain:
            return None
        return (self.goals - self.set_up_goals) / plain


def collect_shots(matches: Iterable[MatchState]) -> ShotReport:
    report = ShotReport()
    for match in matches:
        for event in match.events:
            if event.kind == EVENT_SHOT:
                scored = bool(event.details.get("scored"))
                report.attempts += 1
                report.goals += scored
                if event.details.get("set_up"):
                    report.set_up_attempts += 1
                    report.set_up_goals += scored
                bucket = report.by_defenders.setdefault(
                    int(event.details.get("defender_count", 0)), [0, 0]
                )
                bucket[0] += 1
                bucket[1] += scored
            elif event.kind == EVENT_OWN_GOAL_ROLL:
                report.own_goal_rolls += 1
                report.own_goals += bool(event.details.get("conceded"))
    return report


@dataclass
class ConditionReport:
    """Exhaustion and injury, which are the two prices of playing."""

    exhaustion_charged: int = 0
    injury_tests: int = 0
    injuries: int = 0
    skill_tests: int = 0
    skill_test_ties: int = 0
    # player_id -> count, for the roster breakdown.
    injuries_by_player: Counter = field(default_factory=Counter)
    exhaustion_by_player: Counter = field(default_factory=Counter)
    goals_by_player: Counter = field(default_factory=Counter)

    @property
    def injury_rate(self) -> Optional[float]:
        if not self.injury_tests:
            return None
        return self.injuries / self.injury_tests


def collect_conditions(matches: Iterable[MatchState]) -> ConditionReport:
    report = ConditionReport()
    for match in matches:
        for turn in match_turns(match):
            for player_id, tokens in turn.exhaustion.items():
                report.exhaustion_charged += tokens
                report.exhaustion_by_player[player_id] += tokens
            for event in turn.events:
                if event.kind == EVENT_INJURY_TEST:
                    report.injury_tests += 1
                    if event.details.get("injured"):
                        report.injuries += 1
                        if event.player_id:
                            report.injuries_by_player[event.player_id] += 1
                elif event.kind == EVENT_SKILL_TEST:
                    report.skill_tests += 1
                    report.skill_test_ties += bool(event.details.get("tied"))
                elif event.kind == EVENT_GOAL and event.player_id:
                    report.goals_by_player[event.player_id] += 1
    return report


@dataclass
class GameResult:
    """One finished game's result, as the overview counts it."""

    game_id: str
    home_score: int
    visiting_score: int
    winner: Optional[TeamSide]
    went_to_shootout: bool


@dataclass
class OverviewReport:
    total: int = 0
    in_setup: int = 0
    in_progress: int = 0
    finished: int = 0
    abandoned: int = 0
    results: list[GameResult] = field(default_factory=list)
    goals: int = 0
    own_goals: int = 0
    shootout_goals: int = 0
    games_without_events: int = 0
    turns: int = 0

    @property
    def home_wins(self) -> int:
        return sum(
            1 for result in self.results if result.winner == TeamSide.HOME
        )

    @property
    def visiting_wins(self) -> int:
        return sum(
            1 for result in self.results if result.winner == TeamSide.VISITING
        )

    @property
    def shootouts(self) -> int:
        return sum(1 for result in self.results if result.went_to_shootout)

    @property
    def goals_per_game(self) -> Optional[float]:
        return self.goals / self.finished if self.finished else None


def match_result(game: D12BallGame, match: MatchState) -> GameResult:
    """
    Who won, read off the scoreboard the game ended on.

    **The shootout is already in the scoreboard**, so the winner is
    just the higher score -- `shootout_goals` is a tally of its own,
    not a second score, and adding it would count those goals twice.
    A level score on a finished game means the shootout has not been
    played out, so there is no winner to name.
    """
    home = match.scoreboard.home_score
    visiting = match.scoreboard.visiting_score
    winner: Optional[TeamSide] = None
    if home > visiting:
        winner = TeamSide.HOME
    elif visiting > home:
        winner = TeamSide.VISITING
    return GameResult(
        game_id=game.game_id,
        home_score=home,
        visiting_score=visiting,
        winner=winner,
        went_to_shootout=bool(match.shootout_goals),
    )


def collect_overview(
    pairs: list[tuple[D12BallGame, Optional[MatchState]]],
) -> OverviewReport:
    """
    The game-level counts. `pairs` is every game in scope with its
    match, or None where the match could not be loaded.

    **An abandoned game is counted and its result is not.** It was
    given up rather than played out, so its scoreboard is a position
    and not a result -- see `D12BallGame.abandoned`.
    """
    report = OverviewReport(total=len(pairs))
    for game, match in pairs:
        if game.status == GameStatus.SETUP:
            report.in_setup += 1
        elif game.status == GameStatus.IN_PROGRESS:
            report.in_progress += 1
        else:
            report.finished += 1
        if game.abandoned:
            report.abandoned += 1

        if match is None:
            continue
        if not match.events:
            report.games_without_events += 1
        report.turns += len(match_turns(match))
        for goal in match.goals:
            report.goals += 1
            report.own_goals += goal.own_goal
            report.shootout_goals += goal.shootout

        if game.status == GameStatus.FINISHED and not game.abandoned:
            report.results.append(match_result(game, match))
    return report


def maneuver_order(
    catalog: ManeuverCatalog,
    keys: Iterable[str],
) -> list[str]:
    """
    The keys in the catalog's own order -- rank, then tier, offense
    before defense -- with anything the catalog no longer carries last.

    Sorting by frequency was the obvious alternative and is worse: a
    table whose rows move between two runs cannot be compared with the
    one a coach read last week, and rank order is the order the cards
    and the reference hexagon already put them in.
    """
    catalogued = [
        maneuver.key for maneuver in catalog.offense + catalog.defense
    ]
    known = [key for key in catalogued if key in set(keys)]
    unknown = sorted(set(keys) - set(catalogued))
    return known + unknown


def role_of(catalog: PlayerCatalog, player_id: str) -> str:
    """
    A card's role, for a breakdown that groups by it. Falls back to
    the id for a player the catalog no longer carries, the way
    `display_name` falls back to a maneuver key.
    """
    try:
        return catalog.player_by_id(player_id).role.value
    except (KeyError, ValueError):
        return player_id


# -- The tables ------------------------------------------------------
#
# Every one of these returns a list of lines the cog wraps in a code
# fence, and every one is sized to **58 characters**. That is not
# arbitrary: a Discord code block does not wrap, it scrolls, and a
# table wider than a phone's message column is one a coach has to drag
# sideways to read a row of. Adding a column means taking one out.


TABLE_WIDTH = 58


def _percent(value: Optional[float], width: int = 5) -> str:
    """A rate, or a dash where there is no denominator to divide by."""
    if value is None:
        return "-".rjust(width)
    return f"{value * 100:.0f}%".rjust(width)


def _number(value: Optional[float], width: int = 5) -> str:
    if value is None:
        return "-".rjust(width)
    return f"{value:.1f}".rjust(width)


# A rule is written as this sentinel while a table is being built and
# widened to the finished table at the end -- see `_ruled`. Sizing it
# to TABLE_WIDTH instead drew every rule past the end of its own
# table, which reads as a table that has been cut off.
RULE = "\x00rule"
DOUBLE_RULE = "\x00double"


def _rule(char: str = "-") -> str:
    return DOUBLE_RULE if char == "=" else RULE


def _ruled(lines: list[str]) -> list[str]:
    """
    Finish a table: draw its rules to the width of its widest row, and
    take the trailing space off every line.

    Trailing space is invisible in a terminal and not in a Discord
    code block, where it widens the fence and shifts the whole table
    off centre on a phone.
    """
    body = [line for line in lines if line not in (RULE, DOUBLE_RULE)]
    width = min(TABLE_WIDTH, max((len(line) for line in body), default=0))
    return [
        "-" * width
        if line == RULE
        else "=" * width
        if line == DOUBLE_RULE
        else line.rstrip()
        for line in lines
    ]


def _short_name(name: str, width: int) -> str:
    """
    A maneuver's name cut to fit a column head.

    Cut rather than abbreviated by a table of nicknames: the names
    come from a spreadsheet the author edits, so any hand-written
    short form is one an import can silently invalidate.
    """
    return name if len(name) <= width else name[: width - 1] + "."


def format_scope_heading(scope: str, report_games: int, empty: int) -> list[str]:
    """
    The line every report opens with: what was counted, and what was
    not. The second half is the point -- see the module docstring.
    """
    label = SCOPE_LABELS.get(scope, scope)
    line = f"{report_games} {label}"
    if empty:
        line += f"  ({empty} with nothing recorded)"
    return _ruled([line, _rule("=")])


def format_maneuver_usage(
    report: ManeuverReport,
    catalog: ManeuverCatalog,
) -> list[str]:
    """
    Who gets played, and who wins.

    `share` is of every pick in the scope, both sides together, so the
    six offense cards and the six defense cards each add to about half
    of it -- which is what makes an offense card's share comparable to
    another offense card's and to nothing else.
    """
    total = report.total_picks
    lines = [
        f"{'MANEUVER':<16}{'plays':>6}{'share':>7}{'won':>5}"
        f"{'lost':>5}{'win%':>6}",
        _rule(),
    ]
    for key in maneuver_order(catalog, report.records):
        record = report.records[key]
        share = record.picks / total if total else None
        lines.append(
            f"{_short_name(catalog.display_name(key), 15):<16}"
            f"{record.picks:>6}"
            f"{_percent(share, 7)}"
            f"{record.wins:>5}"
            f"{record.losses:>5}"
            f"{_percent(record.win_rate, 6)}"
        )
    lines.append(_rule())
    lines.append(
        "win% is of contested plays only -- an unchallenged"
    )
    lines.append("maneuver always wins, so it is counted apart.")
    return _ruled(lines)


def format_maneuver_cost(
    report: ManeuverReport,
    catalog: ManeuverCatalog,
) -> list[str]:
    """
    What a maneuver costs and what it pays.

    `exh` and `inj` are the **turn's** figures, not the card's -- a
    turn is charged to both sides, and the log does not say which of
    the two a token belonged to. `goals` is the possession's, shared
    by every maneuver played in it, for the reason `possessions`
    exists: a pass that works pays off on the shot it set up.
    """
    lines = [
        f"{'MANEUVER':<16}{'plays':>6}{'unopp':>6}{'->test':>7}"
        f"{'exh':>6}{'inj':>5}{'goals':>6}",
        _rule(),
    ]
    for key in maneuver_order(catalog, report.records):
        record = report.records[key]
        lines.append(
            f"{_short_name(catalog.display_name(key), 15):<16}"
            f"{record.picks:>6}"
            f"{record.uncontested:>6}"
            f"{_percent(record.skill_test_rate, 7)}"
            f"{_number(record.exhaustion_per_play, 6)}"
            f"{record.injuries:>5}"
            f"{_number(record.goals_per_play, 6)}"
        )
    lines.append(_rule())
    lines.append("exh and inj are the whole turn's, shared by both")
    lines.append("cards; goals are the possession's, per play.")
    return _ruled(lines)


def format_matchups(
    report: ManeuverReport,
    catalog: ManeuverCatalog,
) -> list[str]:
    """
    Every pairing that has actually been played, offense down the
    side and defense across the top.

    Blank rather than zero for a pairing nobody has met in: a grid of
    zeroes reads as data, and what this is showing is mostly which
    corners of the matrix the players never go near.
    """
    offense_keys = maneuver_order(catalog, report.matchups.keys())
    defense_keys = maneuver_order(
        catalog,
        {key for counts in report.matchups.values() for key in counts},
    )
    if not offense_keys or not defense_keys:
        return ["Nothing has been played yet."]

    # Column width is what is left once the row labels have theirs,
    # floored at 4 so a three-digit count still fits under its head.
    column = max(4, min(7, (TABLE_WIDTH - 14) // len(defense_keys)))
    header = " " * 14 + "".join(
        _short_name(catalog.display_name(key), column - 1).rjust(column)
        for key in defense_keys
    )
    lines = [header, _rule()]
    for offense_key in offense_keys:
        counts = report.matchups[offense_key]
        row = _short_name(catalog.display_name(offense_key), 13).ljust(14)
        for defense_key in defense_keys:
            count = counts.get(defense_key, 0)
            row += (str(count) if count else "").rjust(column)
        lines.append(row)
    lines.append(_rule())
    lines.append("Offense down the side, defense across the top.")
    return _ruled(lines)


def format_shots(report: ShotReport) -> list[str]:
    lines = [
        f"{'SHOTS':<22}{'taken':>8}{'scored':>8}{'rate':>8}",
        _rule(),
        f"{'All attempts':<22}{report.attempts:>8}{report.goals:>8}"
        f"{_percent(report.conversion, 8)}",
        f"{'  off a set-up':<22}{report.set_up_attempts:>8}"
        f"{report.set_up_goals:>8}"
        f"{_percent(report.set_up_conversion, 8)}",
        f"{'  taken on its own':<22}{report.plain_attempts:>8}"
        f"{report.goals - report.set_up_goals:>8}"
        f"{_percent(report.plain_conversion, 8)}",
    ]
    if report.by_defenders:
        lines.append(_rule())
        lines.append(f"{'DEFENDERS IN THE WAY':<22}{'taken':>8}"
                     f"{'scored':>8}{'rate':>8}")
        lines.append(_rule())
        for count in sorted(report.by_defenders):
            taken, scored = report.by_defenders[count]
            label = "none" if count == 0 else f"{count}"
            lines.append(
                f"{'  ' + label:<22}{taken:>8}{scored:>8}"
                f"{_percent(scored / taken if taken else None, 8)}"
            )
    if report.own_goal_rolls:
        lines.append(_rule())
        lines.append(
            f"{'Own-goal rolls':<22}{report.own_goal_rolls:>8}"
            f"{report.own_goals:>8}"
            f"{_percent(report.own_goals / report.own_goal_rolls, 8)}"
        )
    return _ruled(lines)


def format_conditions(report: ConditionReport) -> list[str]:
    tie_rate = (
        report.skill_test_ties / report.skill_tests
        if report.skill_tests
        else None
    )
    lines = [
        f"{'EXHAUSTION AND INJURY':<34}{'count':>10}{'rate':>10}",
        _rule(),
        f"{'Exhaustion tokens charged':<34}"
        f"{report.exhaustion_charged:>10}{'':>10}",
        f"{'Skill tests rolled':<34}{report.skill_tests:>10}{'':>10}",
        f"{'  of them tied and re-rolled':<34}"
        f"{report.skill_test_ties:>10}"
        f"{_percent(tie_rate, 10)}",
        f"{'Injury tests rolled':<34}{report.injury_tests:>10}{'':>10}",
        f"{'  that ended in an injury':<34}{report.injuries:>10}"
        f"{_percent(report.injury_rate, 10)}",
    ]
    return _ruled(lines)


def format_players(
    report: ConditionReport,
    display_name,
    limit: int = 10,
) -> list[str]:
    """
    The roster's own numbers -- goals, injuries, tokens.

    `display_name` is passed in rather than looked up here because a
    card id is not always the catalog's: a visiting side fielding a
    player both rosters hold carries a suffixed id, and only the
    caller knows how it wants that written. See `duplicate_card_id`.
    """
    everyone = (
        set(report.goals_by_player)
        | set(report.injuries_by_player)
        | set(report.exhaustion_by_player)
    )
    if not everyone:
        return ["Nobody has done anything worth counting yet."]

    ranked = sorted(
        everyone,
        key=lambda player_id: (
            -report.goals_by_player[player_id],
            -report.exhaustion_by_player[player_id],
            player_id,
        ),
    )[:limit]
    lines = [
        f"{'PLAYER':<28}{'goals':>8}{'inj':>6}{'exh':>6}",
        _rule(),
    ]
    for player_id in ranked:
        lines.append(
            f"{_short_name(display_name(player_id), 27):<28}"
            f"{report.goals_by_player[player_id]:>8}"
            f"{report.injuries_by_player[player_id]:>6}"
            f"{report.exhaustion_by_player[player_id]:>6}"
        )
    return _ruled(lines)


def format_roles(
    report: ConditionReport,
    catalog: PlayerCatalog,
) -> list[str]:
    """
    The same three numbers grouped by role rather than by player.

    Worth its own table because it is the one that generalises: a
    player's tally says who has been fielded a lot, and a role's says
    what the role is *for* -- whether Strikers score, whether
    Defenders are the ones who get hurt. Roles are the same six on
    every team, so this reads across a whole server's games where a
    player's line does not.
    """
    totals: dict[str, list[int]] = {}
    for source, index in (
        (report.goals_by_player, 0),
        (report.injuries_by_player, 1),
        (report.exhaustion_by_player, 2),
    ):
        for player_id, count in source.items():
            role = role_of(catalog, player_id)
            totals.setdefault(role, [0, 0, 0])[index] += count
    if not totals:
        return ["Nobody has done anything worth counting yet."]

    lines = [
        f"{'ROLE':<20}{'goals':>8}{'inj':>7}{'exh':>7}",
        _rule(),
    ]
    for role in sorted(totals, key=lambda name: (-totals[name][0], name)):
        goals, injuries, exhaustion = totals[role]
        lines.append(
            f"{role.replace('_', ' ').title():<20}"
            f"{goals:>8}{injuries:>7}{exhaustion:>7}"
        )
    return _ruled(lines)


def format_overview(report: OverviewReport) -> list[str]:
    played = len(report.results)
    lines = [
        f"{'GAMES':<34}{'count':>10}",
        _rule(),
        f"{'In setup':<34}{report.in_setup:>10}",
        f"{'In progress':<34}{report.in_progress:>10}",
        f"{'Finished':<34}{report.finished:>10}",
        f"{'  of them abandoned':<34}{report.abandoned:>10}",
        f"{'  played out to a result':<34}{played:>10}",
        _rule(),
        f"{'Turns taken':<34}{report.turns:>10}",
        f"{'Goals scored':<34}{report.goals:>10}",
        f"{'  own goals':<34}{report.own_goals:>10}",
        f"{'  in a shootout':<34}{report.shootout_goals:>10}",
        f"{'Goals per finished game':<34}"
        f"{_number(report.goals_per_game, 10)}",
    ]
    if played:
        lines += [
            _rule(),
            f"{'Home wins':<34}{report.home_wins:>10}",
            f"{'Visiting wins':<34}{report.visiting_wins:>10}",
            f"{'Settled by a shootout':<34}{report.shootouts:>10}",
        ]
    return _ruled(lines)


def format_turn_actions(report: ManeuverReport) -> list[str]:
    total = sum(report.actions.values())
    lines = [
        f"{'TURN ACTIONS':<34}{'count':>10}{'share':>10}",
        _rule(),
    ]
    # The two a coach can pick today, then anything else the log holds
    # -- which is "cede", in games played before 2026-09-16. Listing
    # the leftovers rather than naming them keeps a retired action
    # reported for as long as a game remembers one, and drops it from
    # the table on its own once none does.
    actions = ["maneuver", "shoot"]
    actions += sorted(set(report.actions) - set(actions))
    for action in actions:
        count = report.actions.get(action, 0)
        lines.append(
            f"{'  ' + action:<34}{count:>10}"
            f"{_percent(count / total if total else None, 10)}"
        )
    # Below the rule and with no share: a time out is not one of the
    # turns above and has no claim on their denominator.
    lines += [
        _rule(),
        f"{'  time outs called':<34}{report.time_outs:>10}",
    ]
    return _ruled(lines)

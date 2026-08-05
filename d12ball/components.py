import json
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

from d12ball.game import Team


DATA_FOLDER = Path(__file__).resolve().parent / "data"
PLAYERS_FILE = DATA_FOLDER / "players.json"
BASIC_RULES_FILE = DATA_FOLDER / "basic_rules.json"
MANEUVERS_FILE = DATA_FOLDER / "maneuvers.json"


class Zone(str, Enum):
    HOME_GOAL = "home_goal"
    MIDFIELD = "midfield"
    VISITORS_GOAL = "visitors_goal"


class PlayerRole(str, Enum):
    FULLBACK = "fullback"
    DEFENDER = "defender"
    MIDFIELDER = "midfielder"
    PLAYMAKER = "playmaker"
    WINGER = "winger"
    STRIKER = "striker"


class TeamSide(str, Enum):
    HOME = "home"
    VISITING = "visiting"


class AssignmentEdge(str, Enum):
    BELOW = "below"
    ABOVE = "above"


class AttackDirection(str, Enum):
    LEFT_TO_RIGHT = "left_to_right"
    RIGHT_TO_LEFT = "right_to_left"


class MatchPeriod(str, Enum):
    FIRST_HALF = "first_half"
    SECOND_HALF = "second_half"


@dataclass(frozen=True)
class RoleProfile:
    offense: int
    defense: int
    ability: str

    def __post_init__(self) -> None:
        if self.offense not in range(1, 7):
            raise ValueError("Offensive skill must be from 1 to 6.")
        if self.defense not in range(1, 7):
            raise ValueError("Defensive skill must be from 1 to 6.")
        if not self.ability:
            raise ValueError("A player ability is required.")


@dataclass(frozen=True)
class PlayerDefinition:
    player_id: str
    name: str
    team: Team
    role: PlayerRole
    stat_overrides: dict


@dataclass(frozen=True)
class TeamDefinition:
    team: Team
    players: tuple[PlayerDefinition, ...]

    def __post_init__(self) -> None:
        if len(self.players) != 9:
            raise ValueError(
                f"{self.team.value.title()} must have exactly 9 players."
            )
        if len({player.player_id for player in self.players}) != 9:
            raise ValueError("Player IDs must be unique within a team.")


@dataclass(frozen=True)
class PlayerCatalog:
    data_version: int
    source: str
    role_profiles: dict[PlayerRole, RoleProfile]
    teams: dict[Team, TeamDefinition]

    def effective_profile(
        self,
        player: PlayerDefinition,
    ) -> RoleProfile:
        base = self.role_profiles[player.role]
        values = {
            "offense": base.offense,
            "defense": base.defense,
            "ability": base.ability,
        }
        values.update(player.stat_overrides)
        return RoleProfile(**values)

    def player_by_id(self, player_id: str) -> PlayerDefinition:
        for roster in self.teams.values():
            for player in roster.players:
                if player.player_id == player_id:
                    return player
        raise ValueError(f"Unknown player: {player_id}")


@dataclass(frozen=True)
class BoardLayout:
    board_size: int
    zone_spaces: dict[Zone, int]

    def __post_init__(self) -> None:
        if set(self.zone_spaces) != set(Zone):
            raise ValueError("Every board layout must define all three zones.")
        if any(count < 1 for count in self.zone_spaces.values()):
            raise ValueError("Every zone must contain at least one space.")
        if sum(self.zone_spaces.values()) != self.board_size:
            raise ValueError(
                "The zone-space total must equal the board size."
            )


@dataclass
class BoardState:
    layout: BoardLayout
    spaces: dict[Zone, list[list[str]]]

    @classmethod
    def empty(cls, layout: BoardLayout) -> "BoardState":
        return cls(
            layout=layout,
            spaces={
                zone: [[] for _ in range(count)]
                for zone, count in layout.zone_spaces.items()
            },
        )

    def place_meeple(
        self,
        player_id: str,
        zone: Zone,
        space_index: int,
    ) -> None:
        self.remove_meeple(player_id, required=False)
        zone = Zone(zone)
        if space_index not in range(len(self.spaces[zone])):
            raise ValueError("The target board space does not exist.")
        self.spaces[zone][space_index].append(player_id)

    def remove_meeple(
        self,
        player_id: str,
        required: bool = True,
    ) -> None:
        for spaces in self.spaces.values():
            for occupants in spaces:
                if player_id in occupants:
                    occupants.remove(player_id)
                    return
        if required:
            raise ValueError(f"{player_id} does not have a fielded meeple.")

    def meeple_position(
        self,
        player_id: str,
    ) -> Optional[tuple[Zone, int]]:
        for zone, spaces in self.spaces.items():
            for space_index, occupants in enumerate(spaces):
                if player_id in occupants:
                    return zone, space_index
        return None

    def flat_index(self, zone: Zone, space_index: int) -> int:
        """
        Convert a (zone, space_index) position into a single left-to-right
        index across the whole board, so distances can be measured between
        spaces even when they fall in different zones.
        """
        zone = Zone(zone)
        offset = 0
        for board_zone in Zone:
            if board_zone == zone:
                return offset + space_index
            offset += len(self.spaces[board_zone])
        raise ValueError("Unknown zone.")

    def spaces_in_order(self) -> list[list[str]]:
        """
        Every space's occupants as one left-to-right list, indexed the
        same way flat_index() numbers them, so a run of spaces can be
        scanned across zone boundaries.
        """
        return [
            occupants
            for zone in Zone
            for occupants in self.spaces[zone]
        ]

    def position_at_flat_index(self, index: int) -> tuple[Zone, int]:
        """
        The inverse of flat_index(): the (zone, space_index) at a given
        left-to-right position across the whole board.
        """
        offset = 0
        for zone in Zone:
            count = len(self.spaces[zone])
            if index < offset + count:
                return zone, index - offset
            offset += count
        raise ValueError("Flat index is off the board.")


@dataclass(frozen=True)
class DieDefinition:
    sides: int
    color: str


@dataclass(frozen=True)
class PlayerBoardDefinition:
    areas: tuple[str, ...]
    offense_die: DieDefinition
    defense_die: DieDefinition
    team_die: DieDefinition


@dataclass
class PlayerBoardState:
    bench: list[str]
    back_bench: list[str] = field(default_factory=list)
    offense_die_value: Optional[int] = None
    defense_die_value: Optional[int] = None
    team_die_value: Optional[int] = None


@dataclass
class TeamSetup:
    team: Team
    side: TeamSide
    zones: dict[Zone, list[str]]
    player_board: PlayerBoardState

    @property
    def assignment_edge(self) -> AssignmentEdge:
        if self.side == TeamSide.HOME:
            return AssignmentEdge.BELOW
        return AssignmentEdge.ABOVE

    @property
    def attack_direction(self) -> AttackDirection:
        if self.side == TeamSide.HOME:
            return AttackDirection.LEFT_TO_RIGHT
        return AttackDirection.RIGHT_TO_LEFT

    @property
    def field_players(self) -> list[str]:
        return [
            player_id
            for zone in Zone
            for player_id in self.zones[zone]
        ]

    def assigned_zone(self, player_id: str) -> Zone:
        for zone, player_ids in self.zones.items():
            if player_id in player_ids:
                return zone
        raise ValueError(f"{player_id} is not assigned to a zone.")

    def validate(self, roster: TeamDefinition) -> None:
        """
        Check that every roster player is assigned exactly once across
        the zones and both benches. This intentionally does not assume
        any particular distribution (e.g. two players per zone) since
        /coach and /ref can leave zones and benches uneven.
        """
        if set(self.zones) != set(Zone):
            raise ValueError("A setup must assign players to all zones.")

        assigned = (
            self.field_players
            + self.player_board.bench
            + self.player_board.back_bench
        )
        if len(set(assigned)) != len(assigned):
            raise ValueError("Every roster player must be assigned once.")
        if set(assigned) != {
            player.player_id
            for player in roster.players
        }:
            raise ValueError("The setup does not match the team roster.")

    def to_dict(self) -> dict:
        return {
            "team": self.team.value,
            "side": self.side.value,
            "zones": {
                zone.value: list(players)
                for zone, players in self.zones.items()
            },
            "player_board": {
                "bench": list(self.player_board.bench),
                "back_bench": list(self.player_board.back_bench),
                "offense_die_value": (
                    self.player_board.offense_die_value
                ),
                "defense_die_value": (
                    self.player_board.defense_die_value
                ),
                "team_die_value": self.player_board.team_die_value,
            },
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TeamSetup":
        board_data = data["player_board"]
        return cls(
            team=Team(data["team"]),
            side=TeamSide(data["side"]),
            zones={
                Zone(zone): list(players)
                for zone, players in data["zones"].items()
            },
            player_board=PlayerBoardState(
                bench=list(board_data["bench"]),
                back_bench=list(board_data.get("back_bench", [])),
                offense_die_value=board_data.get("offense_die_value"),
                defense_die_value=board_data.get("defense_die_value"),
                team_die_value=board_data.get("team_die_value"),
            ),
        )


@dataclass(frozen=True)
class BasicRuleset:
    ruleset_id: str
    board_layouts: dict[int, BoardLayout]
    standard_setup: dict[str, tuple[PlayerRole, ...]]
    player_board: PlayerBoardDefinition


@dataclass(frozen=True)
class ManeuverDefinition:
    name: str
    rank: int
    die_values: tuple[int, ...]
    defeats: str
    effect: str
    time: str


@dataclass(frozen=True)
class ManeuverCatalog:
    data_version: int
    source: str
    offense: tuple[ManeuverDefinition, ...]
    defense: tuple[ManeuverDefinition, ...]

    def offense_by_name(self) -> dict[str, ManeuverDefinition]:
        return {maneuver.name: maneuver for maneuver in self.offense}

    def defense_by_name(self) -> dict[str, ManeuverDefinition]:
        return {maneuver.name: maneuver for maneuver in self.defense}

    def offense_for_die(self, value: int) -> ManeuverDefinition:
        for maneuver in self.offense:
            if value in maneuver.die_values:
                return maneuver
        raise ValueError(f"No offense maneuver covers die value {value}.")

    def defense_for_die(self, value: int) -> ManeuverDefinition:
        for maneuver in self.defense:
            if value in maneuver.die_values:
                return maneuver
        raise ValueError(f"No defense maneuver covers die value {value}.")

    def resolve(self, offense_name: str, defense_name: str) -> str:
        """
        The outcome of an offense maneuver against a defense maneuver:
        "offense" or "defense" if one defeats the other, otherwise "tie".
        """
        offense = self.offense_by_name()[offense_name]
        defense = self.defense_by_name()[defense_name]

        if offense.defeats == defense_name:
            return "offense"
        if defense.defeats == offense_name:
            return "defense"
        return "tie"


@dataclass
class BallState:
    zone: Zone
    space_index: int
    possession: TeamSide
    speed: int = 1

    def __post_init__(self) -> None:
        self.zone = Zone(self.zone)
        self.possession = TeamSide(self.possession)
        if self.speed not in range(1, 13):
            raise ValueError("Ball speed must be from 1 to 12.")


@dataclass
class ScoreboardState:
    home_score: int = 0
    visiting_score: int = 0
    time: int = 0
    period: MatchPeriod = MatchPeriod.FIRST_HALF
    last_possession: bool = False

    def __post_init__(self) -> None:
        self.period = MatchPeriod(self.period)
        if self.home_score < 0 or self.visiting_score < 0:
            raise ValueError("Scores cannot be negative.")
        if self.time not in range(0, 16):
            raise ValueError("The game clock must be from 00 to 15.")


def kickoff_space_index(midfield_spaces: int, kicking_side: TeamSide) -> int:
    """
    The midfield space a kickoff (or any other restart) places the ball
    on: the middle of the board when the midfield has an odd number of
    spaces, otherwise whichever of the two middle spaces sits closer to
    the kicking team's own goal. Home attacks from low indices to high,
    so a kicking home team is biased low and a kicking visiting team is
    biased high; the two formulas agree on the true middle when the
    zone is odd-sized (i.e. board sizes 7 and 9), which is what makes
    this one rule instead of two.
    """
    kicking_side = TeamSide(kicking_side)
    if kicking_side == TeamSide.HOME:
        return (midfield_spaces - 1) // 2
    return midfield_spaces // 2


@dataclass
class MatchState:
    ruleset_id: str
    player_data_version: int
    board: BoardState
    home: TeamSetup
    visiting: TeamSetup
    ball: BallState
    scoreboard: ScoreboardState
    active_player_id: Optional[str] = None
    pending_action: Optional[str] = None
    challenger_id: Optional[str] = None
    offense_maneuver: Optional[str] = None
    defense_maneuver: Optional[str] = None
    exhaustion: dict[str, int] = field(default_factory=dict)
    exhausted: set[str] = field(default_factory=set)
    injured: set[str] = field(default_factory=set)
    pending_run_back: bool = False
    pending_run_back_distance: int = 1
    pending_run_back_turnover: bool = True
    pending_run_back_stays_player_id: Optional[str] = None
    pending_run_back_speed_choice: bool = False
    pending_kickoff_fill: bool = False
    pending_shot_is_set_up: bool = False
    pending_loose_ball: bool = False
    pending_loose_ball_distance: int = 1
    loose_ball_offense_player: Optional[str] = None
    loose_ball_defense_player: Optional[str] = None
    declared_substitution: set[str] = field(default_factory=set)
    pending_substitution_side: Optional[str] = None
    pending_substitution_used: int = 0
    pending_substitution_is_response: bool = False
    pending_substitution_declared: bool = False

    @classmethod
    def standard(
        cls,
        catalog: PlayerCatalog,
        ruleset: BasicRuleset,
        board_size: int,
        home_team: Team,
        visiting_team: Team,
    ) -> "MatchState":
        layout = ruleset.board_layouts[board_size]
        board = BoardState.empty(layout)
        home = create_standard_setup(
            catalog.teams[Team(home_team)],
            TeamSide.HOME,
            ruleset,
        )
        visiting = create_standard_setup(
            catalog.teams[Team(visiting_team)],
            TeamSide.VISITING,
            ruleset,
        )

        def player_role(player_id: str) -> PlayerRole:
            for roster in catalog.teams.values():
                for player in roster.players:
                    if player.player_id == player_id:
                        return player.role
            raise ValueError(f"Unknown player: {player_id}")

        for setup in (home, visiting):
            for zone, player_ids in setup.zones.items():
                final_space = len(board.spaces[zone]) - 1

                for player_id in player_ids:
                    role = player_role(player_id)
                    if role == PlayerRole.FULLBACK:
                        space_index = (
                            0
                            if setup.side == TeamSide.HOME
                            else final_space
                        )
                    elif role == PlayerRole.DEFENDER:
                        space_index = (
                            min(1, final_space)
                            if setup.side == TeamSide.HOME
                            else max(0, final_space - 1)
                        )
                    elif role == PlayerRole.MIDFIELDER:
                        space_index = (
                            0
                            if setup.side == TeamSide.HOME
                            else final_space
                        )
                    elif role == PlayerRole.PLAYMAKER:
                        space_index = (
                            min(1, final_space)
                            if setup.side == TeamSide.HOME
                            else max(0, final_space - 1)
                        )
                    elif role == PlayerRole.STRIKER:
                        space_index = (
                            min(1, final_space)
                            if setup.side == TeamSide.HOME
                            else max(0, final_space - 1)
                        )
                    else:
                        space_index = (
                            0
                            if setup.side == TeamSide.HOME
                            else final_space
                        )

                    board.place_meeple(player_id, zone, space_index)

        match = cls(
            ruleset_id=ruleset.ruleset_id,
            player_data_version=catalog.data_version,
            board=board,
            home=home,
            visiting=visiting,
            ball=BallState(
                zone=Zone.MIDFIELD,
                space_index=kickoff_space_index(
                    len(board.spaces[Zone.MIDFIELD]),
                    TeamSide.HOME,
                ),
                possession=TeamSide.HOME,
                speed=1,
            ),
            scoreboard=ScoreboardState(),
        )
        match.validate(catalog)
        return match

    def setup_for_side(self, side: TeamSide) -> TeamSetup:
        if TeamSide(side) == TeamSide.HOME:
            return self.home
        return self.visiting

    def eligible_ball_handlers(self) -> list[str]:
        possessing_team = self.setup_for_side(self.ball.possession)
        possessing_players = set(possessing_team.field_players)
        occupants = self.board.spaces[self.ball.zone][
            self.ball.space_index
        ]
        return [
            player_id
            for player_id in occupants
            if player_id in possessing_players
        ]

    def select_ball_handler(self, player_id: str) -> None:
        if player_id not in self.eligible_ball_handlers():
            raise ValueError(
                "The selected player is not an eligible ball handler."
            )
        self.active_player_id = player_id
        self.pending_action = None
        self.challenger_id = None

    def distance_to_ball(self, player_id: str) -> int:
        """
        Number of spaces a fielded player's meeple would need to move to
        reach the ball's current space.
        """
        position = self.board.meeple_position(player_id)
        if position is None:
            raise ValueError(f"{player_id} does not have a fielded meeple.")
        zone, space_index = position
        player_flat = self.board.flat_index(zone, space_index)
        ball_flat = self.board.flat_index(
            self.ball.zone,
            self.ball.space_index,
        )
        return abs(ball_flat - player_flat)

    def is_ball_at_scoring_space(self) -> bool:
        """
        True when the ball sits on the space of its zone that is closest
        to the goal belonging to the team that does not have possession.
        """
        opponent_goal_zone = (
            Zone.VISITORS_GOAL
            if self.ball.possession == TeamSide.HOME
            else Zone.HOME_GOAL
        )
        if self.ball.zone != opponent_goal_zone:
            return False

        final_space = len(self.board.spaces[opponent_goal_zone]) - 1
        closest_space = (
            final_space
            if opponent_goal_zone == Zone.VISITORS_GOAL
            else 0
        )
        return self.ball.space_index == closest_space

    def own_goal_restart_space(self, side: TeamSide) -> tuple[Zone, int]:
        """
        The space closest to `side`'s own goal -- where a missed score
        attempt restarts play for the team that just defended it.
        """
        side = TeamSide(side)
        goal_zone = Zone.HOME_GOAL if side == TeamSide.HOME else Zone.VISITORS_GOAL
        final_space = len(self.board.spaces[goal_zone]) - 1
        closest_space = final_space if goal_zone == Zone.VISITORS_GOAL else 0
        return goal_zone, closest_space

    def defending_side(self) -> TeamSide:
        return (
            TeamSide.VISITING
            if self.ball.possession == TeamSide.HOME
            else TeamSide.HOME
        )

    def spaces_to_goal(self) -> int:
        """
        How many spaces the ball travels through on a shot at goal,
        counting the space it starts from. This is both the time a
        score attempt costs in space minutes and the number of spaces
        that can hold defenders in the way.

        Home attacks towards the high end of the board's left-to-right
        indexing and the visitors towards the low end, so the count
        runs to whichever edge the shooting team is aiming at.
        """
        ball_flat = self.board.flat_index(
            self.ball.zone,
            self.ball.space_index,
        )
        if self.ball.possession == TeamSide.HOME:
            return self.board.layout.board_size - ball_flat
        return ball_flat + 1

    def defenders_between_ball_and_goal(self) -> list[str]:
        """
        Fielded players of the defending team standing anywhere between
        the ball and the goal it is being shot at, including any that
        share the ball's own space. Ordered outwards from the ball, so
        the list reads the way the shot travels.

        Opposing spaces are one and the same space, so both teams'
        meeples share these occupant lists and only the team a meeple
        belongs to decides whether it is in the way.
        """
        defending_players = set(
            self.setup_for_side(self.defending_side()).field_players
        )
        ordered = self.board.spaces_in_order()
        ball_flat = self.board.flat_index(
            self.ball.zone,
            self.ball.space_index,
        )

        if self.ball.possession == TeamSide.HOME:
            span = ordered[ball_flat:]
        else:
            span = list(reversed(ordered[: ball_flat + 1]))

        return [
            player_id
            for occupants in span
            for player_id in occupants
            if player_id in defending_players
        ]

    def fielded_players_in_zone(
        self,
        side: TeamSide,
        zone: Zone,
    ) -> list[str]:
        """
        A side's fielded players anywhere in `zone` -- the pool of
        nearby candidates who can contest a loose ball landing in an
        empty space there.
        """
        side_players = set(self.setup_for_side(side).field_players)
        return [
            player_id
            for occupants in self.board.spaces[zone]
            for player_id in occupants
            if player_id in side_players
        ]

    def eligible_challengers(self) -> list[str]:
        """
        Fielded players belonging to the defending team who share the
        ball's zone, and so can be chosen to maneuver and challenge the
        ball handler.
        """
        return self.fielded_players_in_zone(
            self.defending_side(), self.ball.zone,
        )

    def award_goal(self) -> None:
        """
        Credit a goal to the team in possession. Scores have no upper
        bound, so unlike the clock this needs no clamp and cannot put
        the scoreboard into a state that fails to reload.
        """
        if self.ball.possession == TeamSide.HOME:
            self.scoreboard.home_score += 1
        else:
            self.scoreboard.visiting_score += 1

    def concede_own_goal(self) -> None:
        """
        Credit a goal to the team WITHOUT possession -- an own goal by
        the team currently holding the ball.
        """
        if self.ball.possession == TeamSide.HOME:
            self.scoreboard.visiting_score += 1
        else:
            self.scoreboard.home_score += 1

    def restart_after_goal(self, conceding_side: TeamSide) -> None:
        """
        Restart from midfield with the conceding side in possession.
        This is shared by ordinary goals and own goals.

        The conceding side isn't guaranteed to already have a meeple on
        that exact space -- their two midfield players could easily be
        standing elsewhere in the zone from open play -- so this flags
        pending_kickoff_fill whenever nobody's there, the same way a
        turnover flags pending_run_back. The caller is responsible for
        resolving that (see D12Ball.continue_run_back) before the ball
        is treated as live.
        """
        conceding_side = TeamSide(conceding_side)
        kickoff_index = kickoff_space_index(
            len(self.board.spaces[Zone.MIDFIELD]),
            conceding_side,
        )
        self.set_ball_space(Zone.MIDFIELD, kickoff_index)
        self.ball.possession = conceding_side
        self.ball.speed = 1
        self.pending_kickoff_fill = not self.eligible_ball_handlers()

    def kickoff_fill_candidates(self) -> list[str]:
        """
        The side in possession's midfield-zone-native fielded players,
        nearest the kickoff space first. Only zone-native players
        qualify -- run-back always returns a player to their own
        assigned zone, so anyone else placed on the kickoff space
        wouldn't be allowed to stay there.
        """
        setup = self.setup_for_side(self.ball.possession)
        kickoff_flat = self.board.flat_index(
            self.ball.zone, self.ball.space_index,
        )
        candidates = [
            player_id
            for player_id in setup.zones[Zone.MIDFIELD]
            if self.board.meeple_position(player_id) is not None
        ]
        return sorted(
            candidates,
            key=lambda player_id: abs(
                self.board.flat_index(
                    *self.board.meeple_position(player_id)
                )
                - kickoff_flat
            ),
        )

    def fill_kickoff(self, player_id: str) -> int:
        """
        Move `player_id` onto the ball's kickoff space to start play,
        clearing pending_kickoff_fill. Returns the distance traveled,
        for the exhaustion token any run-back-style movement costs.
        """
        if player_id not in self.kickoff_fill_candidates():
            raise ValueError(
                f"{player_id} cannot fill the kickoff -- not a fielded "
                "midfield player for the side now in possession."
            )
        origin_flat = self.board.flat_index(
            *self.board.meeple_position(player_id)
        )
        destination_flat = self.board.flat_index(
            self.ball.zone, self.ball.space_index,
        )
        distance = abs(destination_flat - origin_flat)
        self.board.place_meeple(
            player_id, self.ball.zone, self.ball.space_index,
        )
        self.pending_kickoff_fill = False
        return distance

    def restart_after_missed_score(self, defending_side: TeamSide) -> None:
        """Restart beside the defending side's goal after a missed shot."""
        defending_side = TeamSide(defending_side)
        restart_zone, restart_index = self.own_goal_restart_space(
            defending_side
        )
        self.set_ball_space(restart_zone, restart_index)
        self.ball.possession = defending_side
        self.ball.speed = 1

    def advance_time(self, minutes: int) -> bool:
        """
        Advance the clock by `minutes` space minutes, clamped at 15.
        Returns True only the moment this call first reaches 15
        (entering last possession), so callers can react to it once.
        """
        if minutes <= 0 or self.scoreboard.last_possession:
            return False
        self.scoreboard.time = min(15, self.scoreboard.time + minutes)
        if self.scoreboard.time >= 15:
            self.scoreboard.last_possession = True
            return True
        return False

    def add_exhaustion(self, player_id: str, amount: int) -> None:
        if amount <= 0 or player_id in self.injured:
            return
        self.exhaustion[player_id] = (
            self.exhaustion.get(player_id, 0) + amount
        )

    def mark_exhausted_if_needed(
        self,
        player_id: str,
        defense_skill: int,
    ) -> bool:
        """
        Mark a player exhausted the moment their token count first
        exceeds their defense skill. Returns True only on that
        transition, so callers can announce it once.
        """
        if player_id in self.injured or player_id in self.exhausted:
            return False
        if self.exhaustion.get(player_id, 0) > defense_skill:
            self.exhausted.add(player_id)
            return True
        return False

    def mark_injured(self, player_id: str) -> None:
        self.injured.add(player_id)
        self.exhaustion.pop(player_id, None)
        self.exhausted.discard(player_id)

    def choose_challenger(self, player_id: str) -> int:
        """
        Move the defending player's chosen meeple into the ball's space
        (if it is not already there), gaining one exhaustion token per
        space moved. Returns the number of spaces moved.
        """
        if self.challenger_id is not None:
            raise ValueError("A defender has already been chosen.")
        if player_id not in self.eligible_challengers():
            raise ValueError(
                "The selected player cannot challenge for the ball."
            )

        distance = self.distance_to_ball(player_id)
        if distance > 0:
            self.move_meeple(player_id, self.ball.zone, self.ball.space_index)
            self.add_exhaustion(player_id, distance)

        self.challenger_id = player_id
        self.pending_action = None
        return distance

    def choose_offense_maneuver(self, name: str) -> None:
        if self.offense_maneuver is not None:
            raise ValueError("The offense has already chosen a maneuver.")
        self.offense_maneuver = name

    def choose_defense_maneuver(self, name: str) -> None:
        if self.defense_maneuver is not None:
            raise ValueError("The defense has already chosen a maneuver.")
        self.defense_maneuver = name

    def begin_loose_ball(self, distance_moved: int) -> None:
        self.pending_loose_ball = True
        self.pending_loose_ball_distance = distance_moved

    def choose_loose_ball_offense_player(self, player_id: str) -> None:
        if self.loose_ball_offense_player is not None:
            raise ValueError("The offense has already picked a player.")
        self.loose_ball_offense_player = player_id

    def choose_loose_ball_defense_player(self, player_id: str) -> None:
        if self.loose_ball_defense_player is not None:
            raise ValueError("The defense has already picked a player.")
        self.loose_ball_defense_player = player_id

    def reset_maneuver(self) -> None:
        """
        Clear the ball-handler and maneuver-selection state once a
        maneuver resolves, so the match no longer looks mid-turn.
        """
        self.active_player_id = None
        self.pending_action = None
        self.challenger_id = None
        self.offense_maneuver = None
        self.defense_maneuver = None
        self.pending_run_back = False
        self.pending_run_back_distance = 1
        self.pending_run_back_turnover = True
        self.pending_run_back_stays_player_id = None
        self.pending_run_back_speed_choice = False
        self.pending_kickoff_fill = False
        self.pending_shot_is_set_up = False
        self.pending_loose_ball = False
        self.pending_loose_ball_distance = 1
        self.loose_ball_offense_player = None
        self.loose_ball_defense_player = None

    def move_meeple(
        self,
        player_id: str,
        zone: Zone,
        space_index: int,
    ) -> None:
        fielded_players = set(
            self.home.field_players + self.visiting.field_players
        )
        if player_id not in fielded_players:
            raise ValueError("Only a fielded player's meeple can move.")
        self.board.place_meeple(player_id, zone, space_index)

    def move_card(
        self,
        side: TeamSide,
        player_id: str,
        destination: str,
    ) -> None:
        """
        Move one team's player card to a zone or a bench, for manual
        board correction (/coach and /ref).

        A zone destination fields the card and places its meeple in an
        empty space of that zone, or, if none is empty, in the space
        closest to the team's own goal. A "bench"/"back_bench"
        destination benches the card and clears its meeple.
        """
        side = TeamSide(side)
        setup = self.setup_for_side(side)
        roster_ids = (
            setup.field_players
            + setup.player_board.bench
            + setup.player_board.back_bench
        )
        if player_id not in roster_ids:
            raise ValueError(f"{player_id} is not assigned to this team.")

        for zone_players in setup.zones.values():
            if player_id in zone_players:
                zone_players.remove(player_id)
        if player_id in setup.player_board.bench:
            setup.player_board.bench.remove(player_id)
        if player_id in setup.player_board.back_bench:
            setup.player_board.back_bench.remove(player_id)
        self.board.remove_meeple(player_id, required=False)

        if destination in ("bench", "back_bench"):
            getattr(setup.player_board, destination).append(player_id)
            return

        zone = Zone(destination)
        setup.zones[zone].append(player_id)
        spaces = self.board.spaces[zone]
        empty_index = next(
            (
                index
                for index, occupants in enumerate(spaces)
                if not occupants
            ),
            None,
        )
        if empty_index is None:
            empty_index = 0 if side == TeamSide.HOME else len(spaces) - 1
        self.board.place_meeple(player_id, zone, empty_index)

    def set_ball_space(self, zone: Zone, space_index: int) -> None:
        """
        Reposition the ball as a maneuver effect, without `move_ball`'s
        "a meeple must already be there" requirement -- a pass or
        deflection can legitimately land on an empty space. Possession
        is left untouched; callers apply a turnover separately via
        `set_possession`.
        """
        zone = Zone(zone)
        if space_index not in range(len(self.board.spaces[zone])):
            raise ValueError("The target board space does not exist.")
        self.ball.zone = zone
        self.ball.space_index = space_index

    def move_ball_relative(self, side: TeamSide, spaces: int) -> int:
        """
        Move the ball `spaces` steps in `side`'s attack direction
        (negative moves it backward relative to that side), clamped to
        the board edge. Returns the actual distance traveled, which may
        be less than requested if it was clamped. Possession is left
        untouched.
        """
        origin_flat = self.board.flat_index(
            self.ball.zone, self.ball.space_index
        )
        target_flat = self.relative_flat_index(origin_flat, side, spaces)
        zone, space_index = self.board.position_at_flat_index(target_flat)
        self.set_ball_space(zone, space_index)
        return abs(target_flat - origin_flat)

    def move_player_relative(
        self,
        player_id: str,
        side: TeamSide,
        spaces: int,
    ) -> int:
        """
        Move a fielded player's meeple `spaces` steps in `side`'s attack
        direction, clamped to the board edge. Returns the actual
        distance traveled.
        """
        position = self.board.meeple_position(player_id)
        if position is None:
            raise ValueError(f"{player_id} does not have a fielded meeple.")
        origin_flat = self.board.flat_index(*position)
        target_flat = self.relative_flat_index(origin_flat, side, spaces)
        zone, space_index = self.board.position_at_flat_index(target_flat)
        self.board.place_meeple(player_id, zone, space_index)
        return abs(target_flat - origin_flat)

    def relative_flat_index(
        self,
        origin_flat: int,
        side: TeamSide,
        spaces: int,
    ) -> int:
        """
        `origin_flat` shifted `spaces` steps in `side`'s attack
        direction, clamped to the board edge. Shared by
        move_ball_relative/move_player_relative; also useful on its own
        to detect an overshoot by comparing the clamped distance
        against the requested one.
        """
        direction = (
            1
            if self.setup_for_side(side).attack_direction
            == AttackDirection.LEFT_TO_RIGHT
            else -1
        )
        target_flat = origin_flat + direction * spaces
        return max(0, min(self.board.layout.board_size - 1, target_flat))

    def move_ball(self, zone: Zone, space_index: int) -> None:
        """
        Move the ball to any board space. Possession changes to
        whichever team has meeples there, if only one side is present;
        it is unchanged when both or neither side is present. Fails if
        the space has no meeple at all.
        """
        zone = Zone(zone)
        if space_index not in range(len(self.board.spaces[zone])):
            raise ValueError("The target board space does not exist.")

        occupants = self.board.spaces[zone][space_index]
        if not occupants:
            raise ValueError(
                "The ball can't be moved there until a meeple is present."
            )

        home_present = any(
            player_id in self.home.field_players
            for player_id in occupants
        )
        visiting_present = any(
            player_id in self.visiting.field_players
            for player_id in occupants
        )

        self.ball.zone = zone
        self.ball.space_index = space_index
        if home_present and not visiting_present:
            self.ball.possession = TeamSide.HOME
        elif visiting_present and not home_present:
            self.ball.possession = TeamSide.VISITING

    def set_possession(self, side: TeamSide) -> None:
        side = TeamSide(side)
        setup = self.setup_for_side(side)
        occupants = self.board.spaces[self.ball.zone][self.ball.space_index]
        if not any(player_id in setup.field_players for player_id in occupants):
            raise ValueError(
                "The ball's current space has no player from that team."
            )
        self.ball.possession = side

    def displaced_players(self, side: TeamSide) -> list[str]:
        """
        That side's fielded players whose meeple currently sits outside
        the zone their player card is assigned to -- the players a
        turnover sends running back.
        """
        setup = self.setup_for_side(side)
        displaced = []
        for player_id in setup.field_players:
            position = self.board.meeple_position(player_id)
            if position is None:
                continue
            zone, _ = position
            if zone != setup.assigned_zone(player_id):
                displaced.append(player_id)
        return displaced

    def crowded_players(self, side: TeamSide) -> list[str]:
        """
        That side's zone-native fielded players sharing a space with a
        teammate assigned to the same zone, beyond the first such
        player at each space -- run-back has to spread these out too,
        not just the players displaced_players() finds outside their
        zone, so a zone's spaces stay covered as fully as possible.
        `pending_run_back_stays_player_id`, if one of the pair, is
        preferred as the one who stays (see begin_run_back). Capped to
        each zone's currently open spaces, so a zone with more
        zone-native players than spaces is left doubled up rather than
        handed movers with nowhere to go.
        """
        stays_player_id = self.pending_run_back_stays_player_id
        setup = self.setup_for_side(side)
        team_players = set(setup.field_players)
        movers: list[str] = []
        for zone in Zone:
            extra: list[str] = []
            for occupants in self.board.spaces[zone]:
                zone_native = [
                    player_id
                    for player_id in occupants
                    if player_id in team_players
                    and setup.assigned_zone(player_id) == zone
                ]
                if len(zone_native) < 2:
                    continue
                if stays_player_id in zone_native:
                    zone_native.remove(stays_player_id)
                    zone_native.insert(0, stays_player_id)
                extra.extend(zone_native[1:])
            open_spaces = len(self.open_spaces_in_zone(side, zone))
            movers.extend(extra[:open_spaces])
        return movers

    def open_spaces_in_zone(self, side: TeamSide, zone: Zone) -> list[int]:
        """
        Space indices in `zone` not already holding a meeple belonging
        to `side`. The one-player-per-space limit run-back enforces is
        per team, so an opposing meeple never blocks a space here.
        """
        zone = Zone(zone)
        setup = self.setup_for_side(side)
        team_players = set(setup.field_players)
        return [
            index
            for index, occupants in enumerate(self.board.spaces[zone])
            if not team_players.intersection(occupants)
        ]

    def run_back_player(
        self,
        player_id: str,
        zone: Zone,
        space_index: int,
    ) -> int:
        """
        Move a displaced player's meeple back into their assigned zone,
        at a space still open for their team. Returns the distance
        traveled, for the exhaust tokens run-back costs.
        """
        side = (
            TeamSide.HOME
            if player_id in self.home.field_players
            else TeamSide.VISITING
        )
        setup = self.setup_for_side(side)
        zone = Zone(zone)

        if zone != setup.assigned_zone(player_id):
            raise ValueError(
                f"{player_id} is not assigned to {zone.value}."
            )
        if space_index not in self.open_spaces_in_zone(side, zone):
            raise ValueError(
                "That space is already occupied by a teammate."
            )

        origin_flat = self.board.flat_index(
            *self.board.meeple_position(player_id)
        )
        destination_flat = self.board.flat_index(zone, space_index)
        distance = abs(destination_flat - origin_flat)

        self.board.place_meeple(player_id, zone, space_index)
        return distance

    def injured_field_players(self, side: TeamSide) -> list[str]:
        setup = self.setup_for_side(side)
        return [
            player_id
            for player_id in setup.field_players
            if player_id in self.injured
        ]

    def may_declare_substitution(self, side: TeamSide) -> bool:
        """A side declares at most once per half."""
        return TeamSide(side).value not in self.declared_substitution

    def must_declare_substitution(self, side: TeamSide) -> bool:
        """
        An injured player's team has to declare at their next
        opportunity and sub them off -- "if they can", which means
        they have not already declared this half and somebody is
        available to come on.
        """
        side = TeamSide(side)
        if not self.may_declare_substitution(side):
            return False
        return any(
            self.substitution_pool(side, player_id)
            for player_id in self.injured_field_players(side)
        )

    def open_substitution_window(
        self,
        side: TeamSide,
        is_response: bool = False,
    ) -> None:
        """
        Offer the window to `side`, who has not taken it up yet. Kept
        distinct from `declare_substitution` so that a bot restart
        mid-offer knows whether it is still asking or already
        substituting.
        """
        self.pending_substitution_side = TeamSide(side).value
        self.pending_substitution_used = 0
        self.pending_substitution_is_response = is_response
        self.pending_substitution_declared = False

    def declare_substitution(self) -> None:
        """
        Take up the offered window. Declaring spends that side's
        once-per-half; answering the other team's declaration does
        not, which is how a side can end up substituting twice in a
        half.
        """
        if self.pending_substitution_side is None:
            raise ValueError("No substitution window is open.")
        self.pending_substitution_declared = True
        if not self.pending_substitution_is_response:
            self.declared_substitution.add(self.pending_substitution_side)

    def close_substitution_window(self) -> None:
        self.pending_substitution_side = None
        self.pending_substitution_used = 0
        self.pending_substitution_is_response = False
        self.pending_substitution_declared = False

    def substitutions_remaining(self) -> int:
        """
        How many more swaps the side holding the window may make: two
        for the team that declared, one for the team answering.
        """
        if self.pending_substitution_side is None:
            return 0
        allowance = 1 if self.pending_substitution_is_response else 2
        return max(0, allowance - self.pending_substitution_used)

    def substitution_pool(
        self,
        side: TeamSide,
        outgoing_player_id: Optional[str] = None,
    ) -> list[str]:
        """
        Who `side` may bring on, given who is going off.

        The bench is the only pool while anyone is still sitting on it.
        The back bench -- where everyone subbed out ends up -- opens
        only once the bench is empty *and* the player going off is
        injured, and it never offers an injured player back: leaving
        the field injured is one way.
        """
        setup = self.setup_for_side(side)
        if setup.player_board.bench:
            return list(setup.player_board.bench)
        if outgoing_player_id is None:
            return []
        if outgoing_player_id not in self.injured:
            return []
        return [
            player_id
            for player_id in setup.player_board.back_bench
            if player_id not in self.injured
        ]

    def substitute(
        self,
        side: TeamSide,
        fielded_player_id: str,
        incoming_player_id: str,
    ) -> None:
        """
        Swap a fielded player for one off the bench, in place: whoever
        comes on inherits the outgoing player's zone assignment and
        stands where they stood, and the outgoing player goes to the
        back bench.

        Standing where they stood matters because the substitution
        window opens *before* the run back, so the outgoing player may
        well be displaced -- in which case the player coming on
        inherits the run back too, and pays for the distance like
        anyone else.

        A player returning from the back bench loses half their
        exhaustion tokens, rounded up. Their Exhausted flag is cleared
        here but not recomputed: the threshold is a defensive skill
        this module deliberately does not carry, so callers put the
        remaining count back through `mark_exhausted_if_needed`.
        """
        side = TeamSide(side)
        setup = self.setup_for_side(side)

        if fielded_player_id not in setup.field_players:
            raise ValueError("The outgoing player is not on the field.")

        if incoming_player_id not in self.substitution_pool(
            side, fielded_player_id
        ):
            if incoming_player_id in self.injured:
                raise ValueError(
                    "An injured player can never be subbed back in."
                )
            if setup.player_board.bench:
                raise ValueError(
                    "The incoming player card is not on the bench."
                )
            raise ValueError(
                "With the bench empty, the back bench can only be drawn "
                "from to replace an injured player."
            )

        position = self.board.meeple_position(fielded_player_id)
        if position is None:
            raise ValueError(
                f"{fielded_player_id} has no meeple on the board."
            )
        _, space_index = position
        zone = setup.assigned_zone(fielded_player_id)

        zone_index = setup.zones[zone].index(fielded_player_id)
        setup.zones[zone][zone_index] = incoming_player_id

        if incoming_player_id in setup.player_board.bench:
            setup.player_board.bench.remove(incoming_player_id)
        else:
            setup.player_board.back_bench.remove(incoming_player_id)
            tokens = self.exhaustion.get(incoming_player_id, 0)
            if tokens:
                self.exhaustion[incoming_player_id] = tokens // 2
            self.exhausted.discard(incoming_player_id)
        setup.player_board.back_bench.append(fielded_player_id)

        self.board.remove_meeple(fielded_player_id)
        self.board.place_meeple(incoming_player_id, position[0], space_index)
        self.inherit_run_back_exemption(
            fielded_player_id, incoming_player_id,
        )

    def inherit_run_back_exemption(
        self,
        leaving_player_id: str,
        arriving_player_id: str,
    ) -> None:
        """
        Move a steal's run-back exemption to whoever took that
        player's place. The exemption belongs to the position, not the
        player: it exists because that meeple is standing on the ball,
        so leaving it behind would run the new ball carrier away from
        the ball and charge them for it.
        """
        if self.pending_run_back_stays_player_id == leaving_player_id:
            self.pending_run_back_stays_player_id = arriving_player_id

    def swap_field_positions(
        self,
        side: TeamSide,
        player_id: str,
        other_player_id: str,
    ) -> None:
        """
        Exchange two of a side's fielded players' zone assignments --
        which zone each player's card belongs to, not where their
        meeples currently stand. This is the whole of "move around
        player assignments": basic mode allows the 2-2-2 formation
        only, and a swap is the largest rearrangement that cannot
        break it, so no formation check is needed. Repeated swaps
        reach any arrangement.

        No role or player is tied to a space or zone outside of this
        assignment and the run back's own requirement (see Author
        clarifications in docs/d12ball-rules.md), so a swapped
        player's meeple is free to stay right where it is -- it simply
        now counts as displaced, exactly like a meeple a maneuver
        pushed out of its zone, until it's moved into the new zone.
        `reposition_player` (an explicit choice, free of exhaustion)
        or the ordinary run back (at the usual per-space cost, next
        time one happens) both resolve that the same way.
        """
        side = TeamSide(side)
        setup = self.setup_for_side(side)

        if player_id == other_player_id:
            raise ValueError("Pick two different players to swap.")
        for candidate in (player_id, other_player_id):
            if candidate not in setup.field_players:
                raise ValueError(f"{candidate} is not on the field.")

        zone = setup.assigned_zone(player_id)
        other_zone = setup.assigned_zone(other_player_id)

        setup.zones[zone][setup.zones[zone].index(player_id)] = (
            other_player_id
        )
        setup.zones[other_zone][
            setup.zones[other_zone].index(other_player_id)
        ] = player_id

    def reposition_player(
        self,
        side: TeamSide,
        player_id: str,
        space_index: int,
    ) -> int:
        """
        Move `player_id`'s meeple to an open space in their own
        currently-assigned zone -- the free-of-exhaustion counterpart
        to run_back_player, offered any time a coach wants to place a
        meeple by hand (typically right after a formation swap)
        instead of leaving it for the next turnover's run back.
        Returns the distance traveled, for display only -- unlike an
        actual run back, this never costs exhaustion.
        """
        side = TeamSide(side)
        setup = self.setup_for_side(side)
        if player_id not in setup.field_players:
            raise ValueError(f"{player_id} is not on the field.")
        zone = setup.assigned_zone(player_id)
        return self.run_back_player(player_id, zone, space_index)

    def swap_meeple_positions(
        self,
        side: TeamSide,
        player_id: str,
        other_player_id: str,
    ) -> None:
        """
        Exchange two of a side's fielded players' physical board
        positions, without touching either one's zone assignment.

        This is what actually resolves a formation swap on a
        fully-packed zone -- typically a 6-board, where the standard
        2-2-2 leaves no slack. Reassigning two players' zones
        (swap_field_positions) can leave each one's *new* zone still
        fully occupied by whoever hasn't moved yet, with no open space
        for either to step into one at a time: trading their two
        meeples directly sidesteps that, since an even exchange never
        needs an intermediate open space.
        """
        side = TeamSide(side)
        setup = self.setup_for_side(side)

        if player_id == other_player_id:
            raise ValueError("Pick two different players to trade with.")
        for candidate in (player_id, other_player_id):
            if candidate not in setup.field_players:
                raise ValueError(f"{candidate} is not on the field.")

        position = self.board.meeple_position(player_id)
        other_position = self.board.meeple_position(other_player_id)
        if position is None or other_position is None:
            raise ValueError("Both players need a meeple on the board.")

        self.board.remove_meeple(player_id)
        self.board.remove_meeple(other_player_id)
        self.board.place_meeple(player_id, *other_position)
        self.board.place_meeple(other_player_id, *position)

        stays_player_id = self.pending_run_back_stays_player_id
        if stays_player_id == player_id:
            self.pending_run_back_stays_player_id = other_player_id
        elif stays_player_id == other_player_id:
            self.pending_run_back_stays_player_id = player_id

    def validate(self, catalog: PlayerCatalog) -> None:
        self.home.validate(catalog.teams[self.home.team])
        self.visiting.validate(catalog.teams[self.visiting.team])

        fielded_players = set(
            self.home.field_players + self.visiting.field_players
        )
        meeples = [
            player_id
            for spaces in self.board.spaces.values()
            for occupants in spaces
            for player_id in occupants
        ]
        if len(meeples) != len(set(meeples)):
            raise ValueError("A player meeple appears more than once.")
        if set(meeples) != fielded_players:
            raise ValueError(
                "Fielded cards and meeples must remain synchronized."
            )

        benched_players = set(
            self.home.player_board.bench
            + self.home.player_board.back_bench
            + self.visiting.player_board.bench
            + self.visiting.player_board.back_bench
        )
        if benched_players.intersection(meeples):
            raise ValueError("Benched players cannot have fielded meeples.")

        if self.ball.space_index not in range(
            len(self.board.spaces[self.ball.zone])
        ):
            raise ValueError("The ball is in an invalid board space.")

        # Once both sides have picked a maneuver, its effect is free to
        # move the ball away from active_player_id (a pass), flip
        # possession without moving the challenger (Steal Intercept),
        # or otherwise leave the pre-effect ball-handler/challenger
        # pairing stale until reset_maneuver() clears it at the end of
        # the pipeline -- this invariant only describes the state
        # before an effect has started applying.
        # challenger_id is only ever set while a maneuver is in
        # progress and cleared by reset_maneuver(), so it alone
        # identifies this phase -- pending_action itself is cleared to
        # None by choose_challenger() right when the challenger is
        # picked, well before an effect can be resolving.
        maneuver_effect_in_progress = (
            self.challenger_id is not None
            and self.offense_maneuver is not None
            and self.defense_maneuver is not None
        )
        if (
            self.active_player_id is not None
            and self.active_player_id not in self.eligible_ball_handlers()
            and not maneuver_effect_in_progress
            and not self.pending_run_back
            and not self.pending_kickoff_fill
        ):
            raise ValueError(
                "The active player must share the ball's space and "
                "belong to the team in possession."
            )

    def to_dict(self) -> dict:
        return {
            "ruleset_id": self.ruleset_id,
            "player_data_version": self.player_data_version,
            "board": {
                "board_size": self.board.layout.board_size,
                "spaces": {
                    zone.value: [
                        list(occupants)
                        for occupants in spaces
                    ]
                    for zone, spaces in self.board.spaces.items()
                },
            },
            "home": self.home.to_dict(),
            "visiting": self.visiting.to_dict(),
            "ball": {
                "zone": self.ball.zone.value,
                "space_index": self.ball.space_index,
                "possession": self.ball.possession.value,
                "speed": self.ball.speed,
            },
            "scoreboard": {
                "home_score": self.scoreboard.home_score,
                "visiting_score": self.scoreboard.visiting_score,
                "time": self.scoreboard.time,
                "period": self.scoreboard.period.value,
                "last_possession": self.scoreboard.last_possession,
            },
            "active_player_id": self.active_player_id,
            "pending_action": self.pending_action,
            "challenger_id": self.challenger_id,
            "offense_maneuver": self.offense_maneuver,
            "defense_maneuver": self.defense_maneuver,
            "exhaustion": dict(self.exhaustion),
            "exhausted": sorted(self.exhausted),
            "injured": sorted(self.injured),
            "pending_run_back": self.pending_run_back,
            "pending_run_back_distance": self.pending_run_back_distance,
            "pending_run_back_turnover": self.pending_run_back_turnover,
            "pending_run_back_stays_player_id": (
                self.pending_run_back_stays_player_id
            ),
            "pending_run_back_speed_choice": (
                self.pending_run_back_speed_choice
            ),
            "pending_kickoff_fill": self.pending_kickoff_fill,
            "pending_shot_is_set_up": self.pending_shot_is_set_up,
            "pending_loose_ball": self.pending_loose_ball,
            "pending_loose_ball_distance": self.pending_loose_ball_distance,
            "loose_ball_offense_player": self.loose_ball_offense_player,
            "loose_ball_defense_player": self.loose_ball_defense_player,
            "declared_substitution": sorted(self.declared_substitution),
            "pending_substitution_side": self.pending_substitution_side,
            "pending_substitution_used": self.pending_substitution_used,
            "pending_substitution_is_response": (
                self.pending_substitution_is_response
            ),
            "pending_substitution_declared": (
                self.pending_substitution_declared
            ),
        }

    @classmethod
    def from_dict(
        cls,
        data: dict,
        ruleset: BasicRuleset,
    ) -> "MatchState":
        board_size = data["board"]["board_size"]
        board = BoardState(
            layout=ruleset.board_layouts[board_size],
            spaces={
                Zone(zone): [
                    list(occupants)
                    for occupants in spaces
                ]
                for zone, spaces in data["board"]["spaces"].items()
            },
        )
        injured = set(data.get("injured", []))
        exhaustion = {
            player_id: amount
            for player_id, amount in data.get("exhaustion", {}).items()
            if player_id not in injured
        }
        exhausted = set(data.get("exhausted", [])) - injured
        return cls(
            ruleset_id=data["ruleset_id"],
            player_data_version=data["player_data_version"],
            board=board,
            home=TeamSetup.from_dict(data["home"]),
            visiting=TeamSetup.from_dict(data["visiting"]),
            ball=BallState(
                **data.get(
                    "ball",
                    {
                        "zone": Zone.MIDFIELD.value,
                        "space_index": 1,
                        "possession": TeamSide.HOME.value,
                        "speed": 1,
                    },
                )
            ),
            scoreboard=ScoreboardState(
                **data.get("scoreboard", {})
            ),
            active_player_id=data.get("active_player_id"),
            pending_action=data.get("pending_action"),
            challenger_id=data.get("challenger_id"),
            offense_maneuver=data.get("offense_maneuver"),
            defense_maneuver=data.get("defense_maneuver"),
            exhaustion=exhaustion,
            exhausted=exhausted,
            injured=injured,
            pending_run_back=data.get("pending_run_back", False),
            pending_run_back_distance=data.get(
                "pending_run_back_distance", 1
            ),
            pending_run_back_turnover=data.get(
                "pending_run_back_turnover", True
            ),
            pending_run_back_stays_player_id=data.get(
                "pending_run_back_stays_player_id"
            ),
            pending_run_back_speed_choice=data.get(
                "pending_run_back_speed_choice", False
            ),
            pending_kickoff_fill=data.get("pending_kickoff_fill", False),
            pending_shot_is_set_up=data.get(
                "pending_shot_is_set_up", False
            ),
            pending_loose_ball=data.get("pending_loose_ball", False),
            pending_loose_ball_distance=data.get(
                "pending_loose_ball_distance", 1
            ),
            loose_ball_offense_player=data.get(
                "loose_ball_offense_player"
            ),
            loose_ball_defense_player=data.get(
                "loose_ball_defense_player"
            ),
            declared_substitution=set(
                data.get("declared_substitution", [])
            ),
            pending_substitution_side=data.get(
                "pending_substitution_side"
            ),
            pending_substitution_used=data.get(
                "pending_substitution_used", 0
            ),
            pending_substitution_is_response=data.get(
                "pending_substitution_is_response", False
            ),
            pending_substitution_declared=data.get(
                "pending_substitution_declared", False
            ),
        )


def load_player_catalog(
    path: Path = PLAYERS_FILE,
) -> PlayerCatalog:
    data = json.loads(path.read_text(encoding="utf-8"))

    role_profiles = {
        PlayerRole(role): RoleProfile(**profile)
        for role, profile in data["role_profiles"].items()
    }
    teams: dict[Team, TeamDefinition] = {}
    all_player_ids: set[str] = set()

    for team_value, team_data in data["teams"].items():
        team = Team(team_value)
        players = tuple(
            PlayerDefinition(
                player_id=player["id"],
                name=player["name"],
                team=team,
                role=PlayerRole(player["role"]),
                stat_overrides=player.get("stat_overrides", {}),
            )
            for player in team_data["players"]
        )
        team_definition = TeamDefinition(team=team, players=players)

        overlap = all_player_ids.intersection(
            player.player_id for player in players
        )
        if overlap:
            raise ValueError(
                "Player IDs must be globally unique: "
                + ", ".join(sorted(overlap))
            )
        all_player_ids.update(player.player_id for player in players)
        teams[team] = team_definition

    if set(teams) != set(Team):
        raise ValueError("The player catalog must define every team.")

    return PlayerCatalog(
        data_version=data["data_version"],
        source=data["source"],
        role_profiles=role_profiles,
        teams=teams,
    )


def load_basic_ruleset(
    path: Path = BASIC_RULES_FILE,
) -> BasicRuleset:
    data = json.loads(path.read_text(encoding="utf-8"))

    layouts = {
        int(board_size): BoardLayout(
            board_size=int(board_size),
            zone_spaces={
                Zone(zone): count
                for zone, count in zone_counts.items()
            },
        )
        for board_size, zone_counts in data["board_layouts"].items()
    }
    if set(layouts) != {6, 7, 9}:
        raise ValueError("Basic rules must define board sizes 6, 7, and 9.")

    standard_setup = {
        area: tuple(PlayerRole(role) for role in roles)
        for area, roles in data["standard_setup"].items()
    }
    if set(standard_setup) != {
        "own_goal",
        "midfield",
        "opponent_goal",
    }:
        raise ValueError("The standard setup has invalid areas.")

    dice = data["player_board"]["head_coach_dice"]
    player_board = PlayerBoardDefinition(
        areas=tuple(data["player_board"]["areas"]),
        offense_die=DieDefinition(**dice["offense"]),
        defense_die=DieDefinition(**dice["defense"]),
        team_die=DieDefinition(**dice["team"]),
    )

    return BasicRuleset(
        ruleset_id=data["ruleset_id"],
        board_layouts=layouts,
        standard_setup=standard_setup,
        player_board=player_board,
    )


def load_maneuver_catalog(
    path: Path = MANEUVERS_FILE,
) -> ManeuverCatalog:
    data = json.loads(path.read_text(encoding="utf-8"))

    def build(maneuver_type: str) -> tuple[ManeuverDefinition, ...]:
        return tuple(
            ManeuverDefinition(
                name=maneuver["name"],
                rank=maneuver["rank"],
                die_values=tuple(maneuver["die_values"]),
                defeats=maneuver["defeats"],
                effect=maneuver["effect"],
                time=maneuver["time"],
            )
            for maneuver in data["maneuvers"][maneuver_type]
        )

    return ManeuverCatalog(
        data_version=data["data_version"],
        source=data["source"],
        offense=build("offense"),
        defense=build("defense"),
    )


def create_standard_setup(
    roster: TeamDefinition,
    side: TeamSide,
    ruleset: BasicRuleset,
) -> TeamSetup:
    side = TeamSide(side)
    players_by_role: dict[
        PlayerRole,
        deque[PlayerDefinition],
    ] = defaultdict(deque)

    for player in roster.players:
        players_by_role[player.role].append(player)

    def select(roles: tuple[PlayerRole, ...]) -> list[str]:
        selected: list[str] = []
        for role in roles:
            if not players_by_role[role]:
                raise ValueError(
                    f"{roster.team.value.title()} has no available "
                    f"{role.value} for the standard setup."
                )
            selected.append(players_by_role[role].popleft().player_id)
        return selected

    own_goal_zone = (
        Zone.HOME_GOAL
        if side == TeamSide.HOME
        else Zone.VISITORS_GOAL
    )
    opponent_goal_zone = (
        Zone.VISITORS_GOAL
        if side == TeamSide.HOME
        else Zone.HOME_GOAL
    )
    zones = {
        own_goal_zone: select(ruleset.standard_setup["own_goal"]),
        Zone.MIDFIELD: select(ruleset.standard_setup["midfield"]),
        opponent_goal_zone: select(
            ruleset.standard_setup["opponent_goal"]
        ),
    }
    selected_ids = {
        player_id
        for players in zones.values()
        for player_id in players
    }
    bench = [
        player.player_id
        for player in roster.players
        if player.player_id not in selected_ids
    ]

    setup = TeamSetup(
        team=roster.team,
        side=side,
        zones=zones,
        player_board=PlayerBoardState(bench=bench),
    )
    setup.validate(roster)
    return setup

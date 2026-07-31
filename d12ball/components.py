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
    card_image: str
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

    def validate(self, roster: TeamDefinition) -> None:
        if set(self.zones) != set(Zone):
            raise ValueError("A setup must assign players to all zones.")
        if any(len(players) != 2 for players in self.zones.values()):
            raise ValueError(
                "The standard setup must assign two players to each zone."
            )

        assigned = self.field_players + self.player_board.bench
        if len(self.field_players) != 6:
            raise ValueError("Exactly six players must start on the field.")
        if len(self.player_board.bench) != 3:
            raise ValueError("Exactly three players must start on the bench.")
        if len(set(assigned)) != 9:
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

    def __post_init__(self) -> None:
        self.period = MatchPeriod(self.period)
        if self.home_score < 0 or self.visiting_score < 0:
            raise ValueError("Scores cannot be negative.")
        if self.time not in range(0, 16):
            raise ValueError("The game clock must be from 00 to 15.")


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
                space_index=min(
                    1,
                    len(board.spaces[Zone.MIDFIELD]) - 1,
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

    def eligible_challengers(self) -> list[str]:
        """
        Fielded players belonging to the defending team who share the
        ball's zone, and so can be chosen to maneuver and challenge the
        ball handler.
        """
        defending_side = (
            TeamSide.VISITING
            if self.ball.possession == TeamSide.HOME
            else TeamSide.HOME
        )
        defending_players = set(
            self.setup_for_side(defending_side).field_players
        )
        return [
            player_id
            for occupants in self.board.spaces[self.ball.zone]
            for player_id in occupants
            if player_id in defending_players
        ]

    def add_exhaustion(self, player_id: str, amount: int) -> None:
        if amount <= 0:
            return
        self.exhaustion[player_id] = (
            self.exhaustion.get(player_id, 0) + amount
        )

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

    def reset_maneuver(self) -> None:
        """
        Clear the ball-handler and maneuver-clash state once a maneuver
        resolves, so the match no longer looks mid-turn.
        """
        self.active_player_id = None
        self.pending_action = None
        self.challenger_id = None
        self.offense_maneuver = None
        self.defense_maneuver = None

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

    def substitute(
        self,
        side: TeamSide,
        fielded_player_id: str,
        bench_player_id: str,
        zone: Zone,
        space_index: int,
    ) -> None:
        setup = self.setup_for_side(side)
        zone = Zone(zone)

        if fielded_player_id not in setup.zones[zone]:
            raise ValueError(
                "The outgoing player card is not assigned to that zone."
            )
        if bench_player_id not in setup.player_board.bench:
            raise ValueError("The incoming player card is not on the bench.")

        player_index = setup.zones[zone].index(fielded_player_id)
        setup.zones[zone][player_index] = bench_player_id
        bench_index = setup.player_board.bench.index(bench_player_id)
        setup.player_board.bench[bench_index] = fielded_player_id

        self.board.remove_meeple(fielded_player_id)
        self.board.place_meeple(bench_player_id, zone, space_index)

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

        if (
            self.active_player_id is not None
            and self.active_player_id not in self.eligible_ball_handlers()
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
            },
            "active_player_id": self.active_player_id,
            "pending_action": self.pending_action,
            "challenger_id": self.challenger_id,
            "offense_maneuver": self.offense_maneuver,
            "defense_maneuver": self.defense_maneuver,
            "exhaustion": dict(self.exhaustion),
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
            exhaustion=dict(data.get("exhaustion", {})),
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
                card_image=player["card_image"],
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

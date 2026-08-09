import json
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

from d12ball.game import Formation, Team


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


class CoachingOccasion(str, Enum):
    """
    The three occasions that offer a coach a Coaching Choice. They run
    the same four actions and differ only in the three things below --
    see "Coaching Choice" in docs/living-rules.md.
    """

    SETUP = "setup"
    NEW_PLAY = "new_play"
    HALFTIME = "halftime"

    @property
    def substitution_allowance(self) -> Optional[int]:
        """
        How many substitutions this occasion allows, or None for no
        limit. Setup is unlimited because nobody has played yet;
        halftime's 2 are its own, and a new play's come out of the
        side's 2 for the half.
        """
        return None if self == CoachingOccasion.SETUP else 2

    @property
    def counts_against_the_half(self) -> bool:
        """
        Whether a substitution here spends one of the side's two for
        the half. Only open play's does, which is what lets a side
        substitute six times in a game -- two a half, plus halftime's
        own two.
        """
        return self == CoachingOccasion.NEW_PLAY

    @property
    def spends_declaration(self) -> bool:
        """
        Whether taking this window up costs the side their once-a-half
        declaration. Setup and halftime are given rather than declared,
        so neither is asked for and neither is charged.
        """
        return self == CoachingOccasion.NEW_PLAY

    @property
    def retires_outgoing_players(self) -> bool:
        """
        Whether a player taken off goes to the back bench, where they
        can never return. At setup they go back to the bench instead:
        the game has not started, so nobody has been used up and a
        coach trying out a line-up should not be retiring players to do
        it.
        """
        return self != CoachingOccasion.SETUP


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
    """
    What a role is, in basic mode. `ability_short` is the same ability
    written to fit beside something else -- it comes from its own
    column in the abilities sheet rather than being cut down here,
    because which half of a two-part ability matters is a rules
    question and the author answers it upstream.

    It is optional, and `short_ability` falls back to the sentence: a
    players.json written before the column existed still loads, and a
    caller that wants the short form always gets something to draw.
    """

    offense: int
    defense: int
    ability: str
    ability_short: str = ""

    def __post_init__(self) -> None:
        if self.offense not in range(1, 7):
            raise ValueError("Offensive skill must be from 1 to 6.")
        if self.defense not in range(1, 7):
            raise ValueError("Defensive skill must be from 1 to 6.")
        if not self.ability:
            raise ValueError("A player ability is required.")

    @property
    def short_ability(self) -> str:
        return self.ability_short or self.ability


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
            "ability_short": base.ability_short,
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

    def is_in_shooting_range(self, side: TeamSide, index: int) -> bool:
        """
        Whether the space at `index` is within `side`'s **shooting
        range** -- the far part of the field, and the only place they
        may shoot from.

        Shooting range is not a board zone: it is measured from the
        middle of the board and cuts across midfield. A board with an
        odd number of spaces has a true middle space, which is the
        kickoff space, and it is in neither side's range -- comparing
        doubled indices against the last index is what leaves it out
        of both. Home attacks from low indices to high, the visitors
        the other way.
        """
        last_index = self.layout.board_size - 1
        if TeamSide(side) == TeamSide.HOME:
            return 2 * index > last_index
        return 2 * index < last_index


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


# The three areas a formation and a card assignment are written in,
# from the coach's own end forward. They are not board zones: a coach
# reads their own shape from their own goal, and which end of the board
# that is depends on the side they are playing (zone_for_area).
SETUP_AREAS = ("own_goal", "midfield", "opponent_goal")
FIELD_PLAYER_COUNT = 6


@dataclass(frozen=True)
class FormationShape:
    """How many cards a formation puts in each of the three areas."""

    own_goal: int
    midfield: int
    opponent_goal: int

    def __post_init__(self) -> None:
        if self.total != FIELD_PLAYER_COUNT:
            raise ValueError(
                f"A formation must field {FIELD_PLAYER_COUNT} players."
            )
        if min(self.own_goal, self.midfield, self.opponent_goal) < 1:
            raise ValueError("A formation must fill every zone.")

    @property
    def total(self) -> int:
        return self.own_goal + self.midfield + self.opponent_goal

    def count(self, area: str) -> int:
        if area not in SETUP_AREAS:
            raise ValueError(f"Unknown setup area: {area}")
        return getattr(self, area)

    def counts(self) -> dict[str, int]:
        return {area: self.count(area) for area in SETUP_AREAS}


@dataclass(frozen=True)
class BasicRuleset:
    ruleset_id: str
    board_layouts: dict[int, BoardLayout]
    formations: dict[Formation, FormationShape]
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

    def relationships(self, name: str, side: str) -> tuple[str, str, str]:
        """
        The opposing-side maneuver `name` defeats, is defeated by, and
        ties with -- each offense maneuver beats exactly one defense
        maneuver and loses to exactly one other, so the third is
        always a tie.
        """
        if side == "offense":
            own = self.offense_by_name()[name]
            opposing = self.defense
        else:
            own = self.defense_by_name()[name]
            opposing = self.offense

        defeats = own.defeats
        defeated_by = next(m.name for m in opposing if m.defeats == name)
        ties_with = next(
            m.name for m in opposing if m.name not in (defeats, defeated_by)
        )
        return defeats, defeated_by, ties_with


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


def setup_space_order(
    side: TeamSide,
    zone_spaces: int,
    player_count: int,
) -> list[int]:
    """
    Which space each of a zone's cards starts on, in the order the
    coach assigned them: one per space working out from that side's own
    end of the zone, then round the zone again for anyone a formation
    leaves over. That satisfies the run back's coverage rule from the
    kickoff -- every space taken before any space takes a second player
    -- and spreads a surplus evenly rather than piling it up, which is
    legal either way and easier to read on the board.

    Home defends the low indices and the visiting team the high ones,
    so the two orders are mirror images. With the standard 2-2-2 deal
    this places exactly what the by-role placement it replaced did.
    """
    side = TeamSide(side)
    order = (
        list(range(zone_spaces))
        if side == TeamSide.HOME
        else list(reversed(range(zone_spaces)))
    )
    return [order[index % zone_spaces] for index in range(player_count)]


def formation_stack_space(
    side: TeamSide,
    zone: Zone,
    zone_spaces: int,
) -> int:
    """
    The one space a zone piles its surplus on when a formation puts
    more cards in it than it has spaces -- see "Changing formation" in
    docs/living-rules.md.

    A three-space zone stacks in the middle. A two-space zone stacks on
    the space nearer the middle of the board, which for the two goal
    zones is the one facing midfield. **Board 6's midfield is the
    exception**: its two spaces straddle the middle and neither is
    nearer it, so the surplus goes on the space nearer that coach's own
    goal. That is also the only zone on any board where the question
    comes up -- three cards in a two-space midfield is the one stack
    the three basic shapes can produce.
    """
    side = TeamSide(side)
    zone = Zone(zone)
    if zone_spaces >= 3:
        return zone_spaces // 2
    if zone_spaces < 2:
        return 0
    if zone == Zone.HOME_GOAL:
        return zone_spaces - 1
    if zone == Zone.VISITORS_GOAL:
        return 0
    return 0 if side == TeamSide.HOME else zone_spaces - 1


def formation_space_order(
    side: TeamSide,
    zone: Zone,
    zone_spaces: int,
    player_count: int,
) -> list[int]:
    """
    Which space each of a zone's cards stands on after a formation
    change, in the order they were dealt: one per space working out
    from that coach's own end, then every one left over onto the
    zone's stack space.

    Unlike `setup_space_order`, which spreads a surplus round the zone
    again, this piles it on one space. The two differ because a
    formation change is a deliberate re-deal a coach asked for and can
    then adjust, where the standard setup is the shape everyone starts
    from.
    """
    side = TeamSide(side)
    outward = (
        list(range(zone_spaces))
        if side == TeamSide.HOME
        else list(reversed(range(zone_spaces)))
    )
    stack = formation_stack_space(side, zone, zone_spaces)
    return [
        outward[index] if index < zone_spaces else stack
        for index in range(player_count)
    ]


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
    # Set instead of challenger_id when the defending team has nobody
    # in the ball's zone: the offense picks a maneuver on its own and
    # it succeeds outright. Unlike challenger_id this is persisted --
    # it is what tells a restart that the missing defense_maneuver is
    # never coming. See begin_uncontested_maneuver.
    maneuver_uncontested: bool = False
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
    pending_loose_ball_is_high_pass: bool = False
    loose_ball_offense_player: Optional[str] = None
    loose_ball_defense_player: Optional[str] = None
    loose_ball_offense_declined: bool = False
    loose_ball_defense_declined: bool = False
    pending_ball_recovery: bool = False
    declared_substitution: set[str] = field(default_factory=set)
    # How many substitutions each side has spent in the half it is in,
    # keyed by TeamSide value. Halftime's own allowance is not counted
    # here -- see substitutions_remaining -- and end_period clears it.
    half_substitutions_used: dict[str, int] = field(default_factory=dict)
    pending_coaching_side: Optional[str] = None
    # Which of the three occasions the open window is, as a
    # CoachingOccasion value. It decides the substitution allowance,
    # whether a declaration is asked for and spent, and where a player
    # taken off goes -- see open_coaching_window.
    pending_coaching_occasion: Optional[str] = None
    pending_coaching_substitutions: int = 0
    pending_coaching_is_response: bool = False
    pending_coaching_declared: bool = False
    pending_halftime_stage: Optional[str] = None
    # Which side is still to take their Coaching Choice before kickoff,
    # as a SETUP_STAGES value. None once both have, which is every
    # game saved before setup offered one -- those kicked off on the
    # standard deal and are already past this.
    pending_setup_stage: Optional[str] = None
    # Where each coach last *put* their meeples, as player_id ->
    # [zone, space_index]. See set_assigned_positions.
    assigned_positions: dict[str, list] = field(default_factory=dict)

    @classmethod
    def standard(
        cls,
        catalog: PlayerCatalog,
        ruleset: BasicRuleset,
        board_size: int,
        home_team: Team,
        visiting_team: Team,
        home_formation: Formation = Formation.TWO_TWO_TWO,
        visiting_formation: Formation = Formation.TWO_TWO_TWO,
        home_assignment: Optional[dict[str, list[str]]] = None,
        visiting_assignment: Optional[dict[str, list[str]]] = None,
    ) -> "MatchState":
        layout = ruleset.board_layouts[board_size]
        board = BoardState.empty(layout)
        home = create_standard_setup(
            catalog.teams[Team(home_team)],
            TeamSide.HOME,
            ruleset,
            formation=home_formation,
            assignment=home_assignment,
        )
        visiting = create_standard_setup(
            catalog.teams[Team(visiting_team)],
            TeamSide.VISITING,
            ruleset,
            formation=visiting_formation,
            assignment=visiting_assignment,
        )

        for setup in (home, visiting):
            for zone, player_ids in setup.zones.items():
                for player_id, space_index in zip(
                    player_ids,
                    setup_space_order(
                        setup.side,
                        len(board.spaces[zone]),
                        len(player_ids),
                    ),
                ):
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
        # The standard setup is the first arrangement a coach has, and
        # the one a new play falls back to until a substitution window
        # replaces it.
        for side in (TeamSide.HOME, TeamSide.VISITING):
            match.set_assigned_positions(side)
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
        self.maneuver_uncontested = False

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

    def can_attempt_score(self, side: Optional[TeamSide] = None) -> bool:
        """
        Whether a shot at goal is legal from where the ball is: only
        from within the shooting team's range (see "Score attempt" in
        the living rules). `side` is who would be shooting, defaulting
        to the team in possession; the maneuver effects pass theirs
        explicitly, since they read the offense once at the top and
        resolve the whole effect against it.

        This governs a set-up's shot as much as the ordinary turn's,
        because a set-up sends a player into an ordinary score
        attempt: what the set-up buys is the shot out of turn, not a
        shot from anywhere.
        """
        return self.board.is_in_shooting_range(
            self.ball.possession if side is None else side,
            self.board.flat_index(self.ball.zone, self.ball.space_index),
        )

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
        pending_kickoff_fill, the same way a turnover flags
        pending_run_back. The caller is responsible for resolving that
        (see D12Ball.continue_run_back) before the ball is treated as
        live.

        The flag says "this restart still owes a kickoff-space check",
        not "nobody is standing there": everyone moves between here and
        the check -- a new play resets both sides to their coaches'
        arrangement, and a substitution window can place meeples freely
        -- so an answer taken now would be stale by the time it is
        acted on. continue_run_back asks the question once everyone has
        settled, and clears the flag with nobody moving if the space is
        already covered.
        """
        conceding_side = TeamSide(conceding_side)
        kickoff_index = kickoff_space_index(
            len(self.board.spaces[Zone.MIDFIELD]),
            conceding_side,
        )
        self.set_ball_space(Zone.MIDFIELD, kickoff_index)
        self.ball.possession = conceding_side
        self.ball.speed = 1
        self.pending_kickoff_fill = True

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

    def recover_exhaustion(
        self,
        player_id: str,
        amount: int,
        defense_skill: int,
    ) -> int:
        """
        Remove up to `amount` exhaustion tokens (floored at 0) from a
        player during halftime recovery, re-testing Exhausted against
        the given defense skill rather than assuming it clears --
        mirrors add_exhaustion/mark_exhausted_if_needed's split, since
        recovery can drop a player back under the threshold that put
        them there. A no-op for an injured player, who never carries
        exhaustion. Returns the number of tokens actually removed.
        """
        if amount <= 0 or player_id in self.injured:
            return 0
        current = self.exhaustion.get(player_id, 0)
        if current <= 0:
            return 0
        removed = min(amount, current)
        remaining = current - removed
        if remaining:
            self.exhaustion[player_id] = remaining
        else:
            self.exhaustion.pop(player_id, None)
        if remaining <= defense_skill:
            self.exhausted.discard(player_id)
        return removed

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

    def begin_uncontested_maneuver(self) -> None:
        """
        The no-challenger branch of "determine the two players": the
        defending team has nobody in the ball's zone, so there is no
        second player and the maneuver the offense picks succeeds --
        see "Maneuver" in docs/living-rules.md.

        Clears `pending_action` for the same reason choose_challenger
        does: the action is settled and what happens next is the
        maneuver selection, not another prompt for this one.
        """
        if self.eligible_challengers():
            raise ValueError(
                "The defending team has a player who can challenge."
            )
        self.maneuver_uncontested = True
        self.pending_action = None

    @property
    def maneuver_selections_complete(self) -> bool:
        """
        Whether every maneuver this turn is waiting on has been
        picked. An uncontested maneuver waits on the offense alone --
        nobody is going to fill in `defense_maneuver`, so checking
        both would hang the turn.
        """
        if self.offense_maneuver is None:
            return False
        return self.maneuver_uncontested or self.defense_maneuver is not None

    def choose_offense_maneuver(self, name: str) -> None:
        if self.offense_maneuver is not None:
            raise ValueError("The offense has already chosen a maneuver.")
        self.offense_maneuver = name

    def choose_defense_maneuver(self, name: str) -> None:
        if self.defense_maneuver is not None:
            raise ValueError("The defense has already chosen a maneuver.")
        self.defense_maneuver = name

    def begin_loose_ball(
        self, distance_moved: int, is_high_pass: bool = False,
    ) -> None:
        self.pending_loose_ball = True
        self.pending_loose_ball_distance = distance_moved
        self.pending_loose_ball_is_high_pass = is_high_pass

    def choose_loose_ball_offense_player(self, player_id: str) -> None:
        if self.loose_ball_offense_player is not None:
            raise ValueError("The offense has already picked a player.")
        self.loose_ball_offense_player = player_id

    def choose_loose_ball_defense_player(self, player_id: str) -> None:
        if self.loose_ball_defense_player is not None:
            raise ValueError("The defense has already picked a player.")
        self.loose_ball_defense_player = player_id

    def decline_loose_ball(self, side: TeamSide) -> None:
        """
        Send nobody after the ball. A coach with a player in the zone
        may always keep them where they are instead -- and if both
        sides do, or neither had anyone to send, the ball is out of
        bounds (see resolve_loose_ball).
        """
        side = TeamSide(side)
        if side == self.ball.possession:
            self.loose_ball_offense_declined = True
        else:
            self.loose_ball_defense_declined = True

    def recover_out_of_bounds_ball(self, player_id: str) -> int:
        """
        Move `player_id` onto the ball's space after an out-of-bounds
        turnover, clearing pending_ball_recovery. Returns the distance
        traveled, for the exhaustion it costs at the usual run-back
        rate.

        Any fielded player of the side that just won the ball will do,
        from anywhere on the field -- unlike the kickoff fill, which
        is limited to the zone's own players. This happens after the
        run back, not before, so the player placed here is the one who
        stays on the ball rather than being run back off it.
        """
        if player_id not in self.setup_for_side(
            self.ball.possession
        ).field_players:
            raise ValueError(
                f"{player_id} cannot recover the ball -- not a fielded "
                "player for the side now in possession."
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
        self.pending_ball_recovery = False
        return distance

    def reset_maneuver(self) -> None:
        """
        Clear the ball-handler and maneuver-selection state once a
        maneuver resolves, so the match no longer looks mid-turn.
        """
        self.active_player_id = None
        self.pending_action = None
        self.challenger_id = None
        self.maneuver_uncontested = False
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
        self.pending_loose_ball_is_high_pass = False
        self.loose_ball_offense_player = None
        self.loose_ball_defense_player = None
        self.loose_ball_offense_declined = False
        self.loose_ball_defense_declined = False
        self.pending_ball_recovery = False

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

        A zone destination fields the card and places its meeple on a
        space of that zone the team has not covered, or, if it covers
        them all, on the space closest to the team's own goal. A
        "bench"/"back_bench" destination benches the card and clears
        its meeple.
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
        uncovered = self.open_spaces_in_zone(side, zone)
        space_index = (
            uncovered[0]
            if uncovered
            else (0 if side == TeamSide.HOME else len(spaces) - 1)
        )
        self.board.place_meeple(player_id, zone, space_index)

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
        each zone's currently uncovered spaces, which is what the
        coverage rule asks for: a stack only has to break up while
        some space in the zone still has nobody on it, so a formation
        that puts more players in a zone than it has spaces (2-3-1 or
        1-3-2 on a six-space board) settles with the surplus doubled
        up and nobody moving.
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
        Space indices in `zone` that `side` has not covered -- no
        meeple of theirs standing there. Coverage is per team, so an
        opposing meeple never blocks a space here.
        """
        zone = Zone(zone)
        setup = self.setup_for_side(side)
        team_players = set(setup.field_players)
        return [
            index
            for index, occupants in enumerate(self.board.spaces[zone])
            if not team_players.intersection(occupants)
        ]

    def placement_spaces_in_zone(
        self,
        side: TeamSide,
        zone: Zone,
        player_id: Optional[str] = None,
    ) -> list[int]:
        """
        Where one of `side`'s meeples may legally be put down in
        `zone`: every space the side has yet to cover, or -- once its
        other meeples cover them all -- every space in the zone, since
        the surplus a formation like 2-3-1 leaves over has to stack
        somewhere. This is the run back's coverage rule (see
        "Turnovers and running back" in docs/living-rules.md) and the
        same rule governs the free placements at a substitution window
        and at halftime.

        `player_id` is the meeple being moved, and is discounted: a
        space it is the only one standing on is uncovered the moment
        it leaves, so it stays a legal destination -- and a zone whose
        spaces only *it* fills does not read as covered and let the
        rest of the team pile up.
        """
        zone = Zone(zone)
        setup = self.setup_for_side(side)
        others = set(setup.field_players) - {player_id}
        uncovered = [
            index
            for index, occupants in enumerate(self.board.spaces[zone])
            if not others.intersection(occupants)
        ]
        if uncovered:
            return uncovered
        return list(range(len(self.board.spaces[zone])))

    def run_back_player(
        self,
        player_id: str,
        zone: Zone,
        space_index: int,
    ) -> int:
        """
        Move a displaced player's meeple back into their assigned zone,
        at a space the coverage rule allows them (see
        placement_spaces_in_zone). Returns the distance traveled, for
        the exhaust tokens run-back costs.
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
        if space_index not in self.placement_spaces_in_zone(
            side, zone, player_id,
        ):
            raise ValueError(
                "That zone still has a space with nobody on it."
            )

        origin_flat = self.board.flat_index(
            *self.board.meeple_position(player_id)
        )
        destination_flat = self.board.flat_index(zone, space_index)
        distance = abs(destination_flat - origin_flat)

        self.board.place_meeple(player_id, zone, space_index)
        return distance

    # -- The arrangement a coach set --------------------------------

    def set_assigned_positions(self, side: TeamSide) -> None:
        """
        Remember where `side`'s meeples are standing as the arrangement
        their coach chose. Called at the three moments a coach actually
        places meeples -- setup, the end of a substitution window, and
        halftime's free repositioning -- and nowhere else. A run back
        is a scramble, not a choice, so it never overwrites this.
        """
        side = TeamSide(side)
        setup = self.setup_for_side(side)
        for player_id in setup.field_players:
            position = self.board.meeple_position(player_id)
            if position is not None:
                zone, space_index = position
                self.assigned_positions[player_id] = [
                    Zone(zone).value, space_index,
                ]

    def restore_assigned_positions(
        self,
        side: TeamSide,
    ) -> list[tuple[str, Zone, int]]:
        """
        Put `side`'s meeples back on the spaces their coach last set,
        and report every player who actually moved. This is what a new
        play does for both sides (see "Resetting after a new play",
        docs/living-rules.md), and it **costs no exhaustion** -- it is
        the coach's shape reasserting itself, not a player running.

        Restoring one meeple at a time can pass through arrangements
        occupancy would refuse, so this places directly rather than
        going through run_back_player. The end state is a whole
        arrangement that was valid when it was saved.

        A player with nothing remembered (never placed under this
        arrangement) is left alone: the window's own placement, or the
        run back that follows, sorts them out.
        """
        side = TeamSide(side)
        setup = self.setup_for_side(side)
        moved: list[tuple[str, Zone, int]] = []
        for player_id in setup.field_players:
            remembered = self.assigned_positions.get(player_id)
            if remembered is None:
                continue
            zone, space_index = Zone(remembered[0]), remembered[1]
            if self.board.meeple_position(player_id) == (zone, space_index):
                continue
            self.board.place_meeple(player_id, zone, space_index)
            moved.append((player_id, zone, space_index))
        return moved

    def injured_field_players(self, side: TeamSide) -> list[str]:
        setup = self.setup_for_side(side)
        return [
            player_id
            for player_id in setup.field_players
            if player_id in self.injured
        ]

    def may_declare_coaching(self, side: TeamSide) -> bool:
        """
        A side declares at most once per half, and that is the whole
        gate on being *offered* a new play's window. Nothing ever
        *forces* a declaration: an injured player used to compel their
        team to sub them off at the next window, which is no longer a
        rule -- a coach may leave them on, disadvantaged, for as long
        as they like.

        The two substitutions a side has for the half are a separate
        count (substitutions_remaining), and the two limits do
        different jobs: a side that spent both substitutions answering
        someone else's declaration can still declare later in the half
        and get the rearrangement without the swaps.
        """
        return TeamSide(side).value not in self.declared_substitution

    def open_coaching_window(
        self,
        side: TeamSide,
        occasion: CoachingOccasion,
        is_response: bool = False,
    ) -> None:
        """
        Offer the window to `side`, who has not taken it up yet. Kept
        distinct from `declare_coaching` so that a bot restart
        mid-offer knows whether it is still asking or already coaching.

        `occasion` carries every difference between the three: the
        substitution allowance, whether a declaration is asked for and
        charged, and where a player taken off goes. Only a new play
        asks -- setup and halftime are given, so both open declared.
        """
        occasion = CoachingOccasion(occasion)
        self.pending_coaching_side = TeamSide(side).value
        self.pending_coaching_occasion = occasion.value
        self.pending_coaching_substitutions = 0
        self.pending_coaching_is_response = is_response
        self.pending_coaching_declared = False
        if not occasion.spends_declaration:
            self.declare_coaching()

    @property
    def coaching_occasion(self) -> Optional[CoachingOccasion]:
        if self.pending_coaching_occasion is None:
            return None
        return CoachingOccasion(self.pending_coaching_occasion)

    def declare_coaching(self) -> None:
        """
        Take up the offered window. Declaring spends that side's
        once-per-half; answering the other team's declaration does
        not, and neither do setup and halftime, which is how a side can
        end up coaching more than once in a half.
        """
        if self.pending_coaching_side is None:
            raise ValueError("No coaching window is open.")
        self.pending_coaching_declared = True
        occasion = self.coaching_occasion
        if (
            not self.pending_coaching_is_response
            and occasion is not None
            and occasion.spends_declaration
        ):
            self.declared_substitution.add(self.pending_coaching_side)

    def close_coaching_window(self) -> None:
        self.pending_coaching_side = None
        self.pending_coaching_occasion = None
        self.pending_coaching_substitutions = 0
        self.pending_coaching_is_response = False
        self.pending_coaching_declared = False

    def substitutions_remaining(self) -> Optional[int]:
        """
        How many more substitutions the side holding the window may
        make, or **None for no limit** -- which setup is, and which
        callers have to handle rather than treating as zero.

        A new play's come out of the side's two for the half, spent
        across every window they get in it; halftime's two are its own
        and are counted within the window.
        """
        occasion = self.coaching_occasion
        if self.pending_coaching_side is None or occasion is None:
            return 0
        allowance = occasion.substitution_allowance
        if allowance is None:
            return None
        spent = (
            self.half_substitutions_used.get(self.pending_coaching_side, 0)
            if occasion.counts_against_the_half
            else self.pending_coaching_substitutions
        )
        return max(0, allowance - spent)

    def may_substitute(self) -> bool:
        remaining = self.substitutions_remaining()
        return remaining is None or remaining > 0

    def record_substitution(self) -> None:
        """
        Charge the open window one substitution, to whichever counter
        the occasion draws on.
        """
        occasion = self.coaching_occasion
        if self.pending_coaching_side is None or occasion is None:
            raise ValueError("No coaching window is open.")
        self.pending_coaching_substitutions += 1
        if occasion.counts_against_the_half:
            side_value = self.pending_coaching_side
            self.half_substitutions_used[side_value] = (
                self.half_substitutions_used.get(side_value, 0) + 1
            )

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
        retire_outgoing: bool = True,
    ) -> None:
        """
        Swap a fielded player for one off the bench, in place: whoever
        comes on inherits the outgoing player's zone assignment and
        stands where they stood, and the outgoing player goes to the
        back bench.

        `retire_outgoing` False sends them to the ordinary bench
        instead, which is setup's exception: the game has not started,
        so there is nothing for the back bench to record and a coach
        trying out a line-up should not be retiring players to do it.
        See CoachingOccasion.retires_outgoing_players.

        Standing where they stood matters because the coaching window
        opens *before* the run back, so the outgoing player may well be
        displaced -- in which case the player coming on inherits the
        run back too, and pays for the distance like anyone else.

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
        if retire_outgoing:
            setup.player_board.back_bench.append(fielded_player_id)
        else:
            setup.player_board.bench.append(fielded_player_id)

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
        meeples currently stand.

        A swap cannot change the shape a team is in, whichever one that
        is, so it needs no formation check: repeated swaps reach every
        arrangement of that shape and no other. Changing shape is
        `reassign_field_zones`.

        No role or player is tied to a space or zone outside of this
        assignment and the run back's own requirement (see "Turnovers
        and running back" in docs/living-rules.md), so a swapped
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

    def exchange_field_players(
        self,
        side: TeamSide,
        player_id: str,
        other_player_id: str,
    ) -> None:
        """
        Trade two fielded players completely: their zone assignments
        and their meeples both. This is the Coaching Choice's zone
        assignment action -- see "Coaching Choice" in
        docs/living-rules.md.

        Moving the meeples is what keeps the two in step. Exchanging
        the cards alone used to leave both meeples standing in the
        zone they had just left, displaced, for a later placement step
        or the next run back to collect; trading the spaces too means
        a Coaching Choice can never leave a meeple outside its own
        zone, and there is nothing left over to place.

        An even exchange also needs no open space to pass through, so
        it works on zones that are already full -- which one-at-a-time
        movement cannot do.
        """
        side = TeamSide(side)
        self.swap_field_positions(side, player_id, other_player_id)
        self.swap_meeple_positions(side, player_id, other_player_id)

    def positioning_swap_candidates(
        self,
        side: TeamSide,
        player_id: str,
        space_index: int,
    ) -> list[str]:
        """
        Which teammates a space-positioning move onto `space_index`
        would have to trade with, in the coach's own assigned zone.

        Empty when the move is an ordinary one: either the target has
        none of this side's meeples on it, or the mover is leaving
        teammates behind and so is free to stack onto it. More than one
        means the coach has to pick which of them comes back -- see
        position_meeple.
        """
        side = TeamSide(side)
        setup = self.setup_for_side(side)
        zone = setup.assigned_zone(player_id)
        team_players = set(setup.field_players)

        position = self.board.meeple_position(player_id)
        if position is not None and position == (zone, space_index):
            return []

        on_target = [
            occupant
            for occupant in self.board.spaces[zone][space_index]
            if occupant in team_players and occupant != player_id
        ]
        if not on_target:
            return []
        if position is not None:
            left_behind = [
                occupant
                for occupant in self.board.spaces[position[0]][position[1]]
                if occupant in team_players and occupant != player_id
            ]
            if left_behind:
                return []
        return on_target

    def position_meeple(
        self,
        side: TeamSide,
        player_id: str,
        space_index: int,
        swap_with: Optional[str] = None,
    ) -> Optional[str]:
        """
        Move one meeple to another space in its own assigned zone, for
        no exhaustion, and report who it traded with (None for an
        ordinary move).

        The rule is local rather than a coverage check, and that is
        what lets every space of the zone simply be offered: **if the
        target is occupied and the mover is the only one of their team
        on the space they leave, the two trade places.** Every other
        move is a plain one. Coverage comes out of that for free --
        leaving a space covered by a teammate uncovers nothing, a trade
        uncovers nothing, and a move between two spaces neither of
        which is shared keeps the count of covered spaces the same.
        """
        side = TeamSide(side)
        setup = self.setup_for_side(side)
        if player_id not in setup.field_players:
            raise ValueError(f"{player_id} is not on the field.")
        zone = setup.assigned_zone(player_id)
        if not 0 <= space_index < len(self.board.spaces[zone]):
            raise ValueError("That space is not in that zone.")
        if self.board.meeple_position(player_id) == (zone, space_index):
            raise ValueError("They are already standing there.")

        candidates = self.positioning_swap_candidates(
            side, player_id, space_index,
        )
        if not candidates:
            if swap_with is not None:
                raise ValueError("That move does not trade with anybody.")
            self.board.place_meeple(player_id, zone, space_index)
            return None

        if swap_with is None:
            if len(candidates) > 1:
                raise ValueError(
                    "More than one teammate is on that space -- pick "
                    "which of them comes back."
                )
            swap_with = candidates[0]
        elif swap_with not in candidates:
            raise ValueError("They are not on the space being moved to.")

        self.swap_meeple_positions(side, player_id, swap_with)
        return swap_with

    def deploy_side(
        self,
        side: TeamSide,
        placement: list[tuple[str, Zone, int]],
    ) -> None:
        """
        Put a side's whole line-up down at once -- every card's zone
        assignment and every meeple's space, together. This is what a
        formation change is made of: the six are re-dealt by defensive
        skill rather than asked for one zone at a time, so nothing
        partial ever reaches the match.

        Places directly rather than through run_back_player: it costs
        no exhaustion, and laying six meeples down one at a time passes
        through arrangements occupancy would refuse even though the one
        being built is fine. The caller builds a covering placement --
        see D12Ball.formation_placement.
        """
        side = TeamSide(side)
        setup = self.setup_for_side(side)

        placed = [player_id for player_id, _, _ in placement]
        if len(set(placed)) != len(placed):
            raise ValueError("A player cannot be placed twice.")
        if set(placed) != set(setup.field_players):
            raise ValueError(
                "A deployment must place every fielded player, and "
                "nobody else."
            )
        for _, zone, space_index in placement:
            if not 0 <= space_index < len(self.board.spaces[Zone(zone)]):
                raise ValueError("That space is not in that zone.")

        zones: dict[Zone, list[str]] = {zone: [] for zone in Zone}
        for player_id, zone, _ in placement:
            zones[Zone(zone)].append(player_id)
        setup.zones = zones

        for player_id, zone, space_index in placement:
            self.board.place_meeple(player_id, Zone(zone), space_index)

    def reassign_field_zones(
        self,
        side: TeamSide,
        zones: dict[Zone, list[str]],
    ) -> None:
        """
        Rewrite which zone each of a side's fielded cards is assigned
        to. This is the general form of `swap_field_positions`, and
        what changing formation is made of: a swap keeps the shape a
        team is in, and only rewriting the lot can move it from 2-2-2
        into 2-3-1 or 1-3-2.

        The shape itself is not checked here -- a MatchState does not
        carry the ruleset that says which shapes basic mode allows, so
        the caller checks it against `BasicRuleset.formations` (see
        D12Ball.apply_formation_change) and this only insists that the
        same six cards come back, one zone each.

        Meeples do not move, exactly as a swap leaves them: everyone
        now standing outside their new zone simply counts as
        displaced, to be placed by hand (free) or by the next run back
        (at the usual cost per space).
        """
        side = TeamSide(side)
        setup = self.setup_for_side(side)

        if set(zones) != set(Zone):
            raise ValueError("A reassignment must name every zone.")

        reassigned = [
            player_id
            for zone in Zone
            for player_id in zones[zone]
        ]
        if len(set(reassigned)) != len(reassigned):
            raise ValueError("A player cannot be assigned to two zones.")
        if set(reassigned) != set(setup.field_players):
            raise ValueError(
                "A reassignment must place every fielded player, and "
                "nobody else."
            )

        setup.zones = {zone: list(zones[zone]) for zone in Zone}

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

    def reposition_meeple_anywhere(
        self,
        side: TeamSide,
        player_id: str,
        zone: Zone,
        space_index: int,
    ) -> None:
        """
        Halftime-only free placement: move a fielded player's meeple
        to a space in any zone, not just their own currently-assigned
        one the way `reposition_player` is -- "the coach can change
        their team's formation and the players' assignment as they
        please" (End of Time). The zone is free; the space still
        answers to the coverage rule, so a coach cannot leave a space
        of a zone they are standing in empty in order to stack
        somewhere else in it. Costs no exhaustion,
        same as `reposition_player`. Leaves the player card's zone
        assignment untouched, so the meeple counts as displaced (same
        as `swap_field_positions` leaves one) until a future run back
        or another reposition moves it back into its assigned zone.
        """
        side = TeamSide(side)
        setup = self.setup_for_side(side)
        if player_id not in setup.field_players:
            raise ValueError(f"{player_id} is not on the field.")
        zone = Zone(zone)
        if space_index not in self.placement_spaces_in_zone(
            side, zone, player_id,
        ):
            raise ValueError("That zone still has a space with nobody on it.")
        self.board.place_meeple(player_id, zone, space_index)

    def kickoff_space_occupied_by(self, side: TeamSide) -> bool:
        """
        Whether one of `side`'s fielded meeples currently stands on
        the ball's space -- used at halftime to confirm the visiting
        team has a player on the second-half kickoff space, which
        `end_period` has already moved the ball onto by the time this
        is checked.
        """
        side = TeamSide(side)
        occupants = self.board.spaces[self.ball.zone][self.ball.space_index]
        team_players = set(self.setup_for_side(side).field_players)
        return bool(team_players.intersection(occupants))

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
        # An uncontested maneuver has no challenger and never will
        # have a defense_maneuver, so maneuver_uncontested stands in
        # for both.
        maneuver_effect_in_progress = self.offense_maneuver is not None and (
            self.maneuver_uncontested
            or (
                self.challenger_id is not None
                and self.defense_maneuver is not None
            )
        )
        if (
            self.active_player_id is not None
            and self.active_player_id not in self.eligible_ball_handlers()
            and not maneuver_effect_in_progress
            and not self.pending_run_back
            and not self.pending_kickoff_fill
            # An out-of-bounds ball has nobody on it at all until the
            # winning side places someone there, which happens after
            # the run back -- see recover_out_of_bounds_ball.
            and not self.pending_ball_recovery
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
            "maneuver_uncontested": self.maneuver_uncontested,
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
            "pending_loose_ball_is_high_pass": (
                self.pending_loose_ball_is_high_pass
            ),
            "loose_ball_offense_player": self.loose_ball_offense_player,
            "loose_ball_defense_player": self.loose_ball_defense_player,
            "loose_ball_offense_declined": self.loose_ball_offense_declined,
            "loose_ball_defense_declined": self.loose_ball_defense_declined,
            "pending_ball_recovery": self.pending_ball_recovery,
            "declared_substitution": sorted(self.declared_substitution),
            "half_substitutions_used": dict(self.half_substitutions_used),
            "pending_coaching_side": self.pending_coaching_side,
            "pending_coaching_occasion": self.pending_coaching_occasion,
            "pending_coaching_substitutions": (
                self.pending_coaching_substitutions
            ),
            "pending_coaching_is_response": (
                self.pending_coaching_is_response
            ),
            "pending_coaching_declared": self.pending_coaching_declared,
            "pending_halftime_stage": self.pending_halftime_stage,
            "pending_setup_stage": self.pending_setup_stage,
            "assigned_positions": {
                player_id: list(position)
                for player_id, position in self.assigned_positions.items()
            },
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
            maneuver_uncontested=data.get("maneuver_uncontested", False),
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
            pending_loose_ball_is_high_pass=data.get(
                "pending_loose_ball_is_high_pass", False
            ),
            loose_ball_offense_player=data.get(
                "loose_ball_offense_player"
            ),
            loose_ball_defense_player=data.get(
                "loose_ball_defense_player"
            ),
            loose_ball_offense_declined=data.get(
                "loose_ball_offense_declined", False
            ),
            loose_ball_defense_declined=data.get(
                "loose_ball_defense_declined", False
            ),
            pending_ball_recovery=data.get("pending_ball_recovery", False),
            declared_substitution=set(
                data.get("declared_substitution", [])
            ),
            half_substitutions_used=dict(
                data.get("half_substitutions_used", {})
            ),
            # The `pending_substitution_*` fallbacks are for a game
            # saved with a window open before the three occasions
            # became one Coaching Choice. Both developers run the bot
            # from their own working tree against their own saves, so
            # a half-finished game outlives the change that renamed
            # these. An old window comes back as a new play's, which
            # is the only kind the old code could leave open mid-game.
            pending_coaching_side=data.get(
                "pending_coaching_side",
                data.get("pending_substitution_side"),
            ),
            pending_coaching_occasion=data.get(
                "pending_coaching_occasion",
                (
                    CoachingOccasion.NEW_PLAY.value
                    if data.get("pending_substitution_side")
                    else None
                ),
            ),
            pending_coaching_substitutions=data.get(
                "pending_coaching_substitutions",
                data.get("pending_substitution_used", 0),
            ),
            pending_coaching_is_response=data.get(
                "pending_coaching_is_response",
                data.get("pending_substitution_is_response", False),
            ),
            pending_coaching_declared=data.get(
                "pending_coaching_declared",
                data.get("pending_substitution_declared", False),
            ),
            pending_halftime_stage=data.get("pending_halftime_stage"),
            pending_setup_stage=data.get("pending_setup_stage"),
            # A game saved before arrangements were remembered has
            # none. Left empty, restore_assigned_positions moves
            # nobody, so such a game simply keeps the old behaviour
            # until its next window sets an arrangement.
            assigned_positions={
                player_id: list(position)
                for player_id, position in data.get(
                    "assigned_positions", {},
                ).items()
            },
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

    formations = {
        Formation(name): FormationShape(**counts)
        for name, counts in data["formations"].items()
    }
    if set(formations) != set(Formation):
        raise ValueError(
            "Basic rules must give a shape for every formation."
        )

    standard_setup = {
        area: tuple(PlayerRole(role) for role in roles)
        for area, roles in data["standard_setup"].items()
    }
    if set(standard_setup) != set(SETUP_AREAS):
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
        formations=formations,
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


def next_unfilled_area(assignment: dict[str, list[str]]) -> Optional[str]:
    """
    The area a coach still has to fill, working from their own goal
    forward, or None once an assignment is complete.
    """
    for area in SETUP_AREAS:
        if area not in assignment:
            return area
    return None


def fill_forced_areas(
    assignment: dict[str, list[str]],
    shape: FormationShape,
    candidates: list[str],
) -> dict[str, list[str]]:
    """
    Fill in every area the coach has no choice left about -- always
    the last one, since whoever is unplaced goes there, and any
    earlier one the formation leaves no slack in. Saves asking a
    question that has only one answer.
    """
    filled = dict(assignment)
    for area in SETUP_AREAS:
        if area in filled:
            continue
        placed = {
            player_id
            for players in filled.values()
            for player_id in players
        }
        remaining = [
            player_id
            for player_id in candidates
            if player_id not in placed
        ]
        if shape.count(area) != len(remaining):
            continue
        filled[area] = remaining
    return filled


def validate_assignment(
    roster: TeamDefinition,
    shape: FormationShape,
    assignment: dict[str, list[str]],
) -> None:
    """
    Check a coach's card assignment against the formation they picked:
    every area filled to its number, no card in two places, and every
    card one of theirs. Benching is what is left over, so this never
    names the bench.
    """
    if set(assignment) != set(SETUP_AREAS):
        raise ValueError("An assignment must name every zone.")

    assigned = [
        player_id
        for area in SETUP_AREAS
        for player_id in assignment[area]
    ]
    if len(set(assigned)) != len(assigned):
        raise ValueError("A player cannot be assigned to two zones.")

    roster_ids = {player.player_id for player in roster.players}
    unknown = set(assigned) - roster_ids
    if unknown:
        raise ValueError(
            "The assignment names players outside the team roster."
        )

    for area in SETUP_AREAS:
        count = shape.count(area)
        if len(assignment[area]) != count:
            raise ValueError(
                f"This formation puts {count} players in "
                f"{area.replace('_', ' ')}, not "
                f"{len(assignment[area])}."
            )


def zone_for_area(side: TeamSide, area: str) -> Zone:
    """
    The board zone a setup area names for one side. The areas are
    written from the coach's point of view -- own goal, midfield,
    opponent goal -- because a formation and a card assignment are both
    settled before the coin toss says which end of the board that is.
    """
    side = TeamSide(side)
    if area == "midfield":
        return Zone.MIDFIELD
    if area == "own_goal":
        return (
            Zone.HOME_GOAL
            if side == TeamSide.HOME
            else Zone.VISITORS_GOAL
        )
    if area == "opponent_goal":
        return (
            Zone.VISITORS_GOAL
            if side == TeamSide.HOME
            else Zone.HOME_GOAL
        )
    raise ValueError(f"Unknown setup area: {area}")


def default_formation_deal(
    roster: TeamDefinition,
    ruleset: BasicRuleset,
    formation: Formation,
) -> dict[str, list[str]]:
    """
    Which cards a formation gets when nobody has assigned them by hand
    -- the AI's team, and any side whose coach left the choice alone.

    The standard setup's roles, read back to front (fullback, defender,
    midfielder, playmaker, winger, striker), are dealt into the zones in
    the formation's numbers. For 2-2-2 that reproduces the standard
    setup exactly; 2-3-1 pulls the winger back into midfield and 1-3-2
    pushes the defender up into it.
    """
    players_by_role: dict[
        PlayerRole,
        deque[PlayerDefinition],
    ] = defaultdict(deque)

    for player in roster.players:
        players_by_role[player.role].append(player)

    ordered: list[str] = []
    for area in SETUP_AREAS:
        for role in ruleset.standard_setup[area]:
            if not players_by_role[role]:
                raise ValueError(
                    f"{roster.team.value.title()} has no available "
                    f"{role.value} for the standard setup."
                )
            ordered.append(players_by_role[role].popleft().player_id)

    shape = ruleset.formations[Formation(formation)]
    deal: dict[str, list[str]] = {}
    taken = 0
    for area in SETUP_AREAS:
        count = shape.count(area)
        deal[area] = ordered[taken:taken + count]
        taken += count
    return deal


def create_standard_setup(
    roster: TeamDefinition,
    side: TeamSide,
    ruleset: BasicRuleset,
    formation: Formation = Formation.TWO_TWO_TWO,
    assignment: Optional[dict[str, list[str]]] = None,
) -> TeamSetup:
    """
    Field six of a team's cards in `formation`, benching the rest.

    `assignment` is the coach's own choice of which card goes where,
    keyed by setup area; leaving it out deals the formation by role
    (see default_formation_deal). Either way the shape is checked
    against the ruleset, so a saved assignment that no longer matches
    its formation is caught here rather than on the board.
    """
    side = TeamSide(side)
    formation = Formation(formation)
    shape = ruleset.formations[formation]

    if assignment is None:
        assignment = default_formation_deal(roster, ruleset, formation)
    else:
        validate_assignment(roster, shape, assignment)

    zones = {
        zone_for_area(side, area): list(assignment[area])
        for area in SETUP_AREAS
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

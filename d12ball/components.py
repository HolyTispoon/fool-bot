import json
import re
from collections import defaultdict, deque
from collections.abc import Collection
from dataclasses import dataclass, field, replace
from enum import Enum
from math import ceil
from pathlib import Path
from typing import Any, Callable, Optional

from d12ball.game import Formation, Team, team_display_name


DATA_FOLDER = Path(__file__).resolve().parent / "data"
PLAYERS_FILE = DATA_FOLDER / "players.json"
BASIC_RULES_FILE = DATA_FOLDER / "basic_rules.json"
MANEUVERS_FILE = DATA_FOLDER / "maneuvers.json"
SPECIES_FILE = DATA_FOLDER / "species.json"


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
    The five occasions that offer a coach a Coaching Choice. They run
    the same four actions -- save FULL_TIME, which runs one of them --
    and differ otherwise only in the properties below. See "Coaching
    Choice" in docs/living-rules.md.

    CEDED is open play's other one: a side out of shooting range may
    give the ball up to coach (see may_cede_possession), which is the
    same window a new play offers and is charged the same way. It is
    its own occasion rather than a flag because the ball was ceded
    *for* it -- so it is never offered, only opened.
    """

    SETUP = "setup"
    NEW_PLAY = "new_play"
    CEDED = "ceded"
    HALFTIME = "halftime"
    FULL_TIME = "full_time"

    @property
    def substitution_allowance(self) -> Optional[int]:
        """
        How many substitutions this occasion allows, or None for no
        limit. Setup is unlimited because nobody has played yet;
        halftime's 2 and full time's 1 are their own, and open play's
        -- a new play's or a ceded ball's -- come out of the side's 2
        for the half.
        """
        if self == CoachingOccasion.SETUP:
            return None
        return 1 if self == CoachingOccasion.FULL_TIME else 2

    @property
    def counts_against_the_half(self) -> bool:
        """
        Whether a substitution here spends one of the side's two for
        the half. Only open play's does, which is what lets a side
        substitute seven times in a game -- two a half, plus halftime's
        own two and full time's one.
        """
        return self in (CoachingOccasion.NEW_PLAY, CoachingOccasion.CEDED)

    @property
    def offers_positioning(self) -> bool:
        """
        Whether this occasion offers the three actions that move
        meeples -- formation, zone assignment, space positioning -- on
        top of the substitution. Full time does not: the shootout is
        played by whoever is on the field and by nothing about where
        they stand, so all three would rearrange a side that never
        plays from a position again.

        It governs the arrangement as well as the menu, which is the
        same fact read at both ends: a window with no positioning in it
        neither opens on the coach's arrangement nor records one.
        """
        return self != CoachingOccasion.FULL_TIME

    @property
    def spends_declaration(self) -> bool:
        """
        Whether taking this window up costs the side their once-a-half
        declaration. Setup, halftime and full time are given rather
        than declared, so none is charged -- full time has no half left
        for a declaration to belong to. Ceding is charged like a new
        play's: it is the same once-a-half, bought with the ball
        instead of with a turnover.
        """
        return self in (CoachingOccasion.NEW_PLAY, CoachingOccasion.CEDED)

    @property
    def asks_declaration(self) -> bool:
        """
        Whether the coach is put the declare-or-pass offer, as opposed
        to being handed the window already declared. Only a new play
        asks: setup, halftime and full time are given, and a ceded ball
        was ceded *to* coach -- the button that gave the ball up is the
        declaration, and a coach offered the chance to pass after
        paying for it would have paid for nothing.

        Kept apart from `spends_declaration`, which the two occasions
        of open play share, because the charge and the question are
        different facts: ceding charges without asking.
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


# The four species, as the keys `players.json` and `species.json` both
# store them. They live here rather than in `d12ball/species_cards.py`,
# which defined them while they were only a print concern: the engine
# reads them now (see "Species abilities" in docs/living-rules.md) and
# must not import a Pillow module to ask what a species is called.
# `species_cards.py` re-exports `SPECIES_ORDER` from here, so there is
# still exactly one list -- the arrangement `cogs/d12ball_helpers.py`
# has with `d12ball/formatting.py`.
SPECIES_FIRE_DEMON = "fire_demon"
SPECIES_CYBORG = "cyborg"
SPECIES_TELEKINETIC = "telekinetic"
SPECIES_OOZE = "ooze"

SPECIES_ORDER: tuple[str, ...] = (
    SPECIES_FIRE_DEMON,
    SPECIES_CYBORG,
    SPECIES_TELEKINETIC,
    SPECIES_OOZE,
)

# Lithium Powered's three numbers -- see "Lithium Powered (Cyborg)" in
# docs/living-rules.md. All three are the author's and none is
# derivable, so they are named here rather than written into the
# predicates that read them. The Drained line was simplified from
# "offensive + defensive skill" (which is 7 for every current player
# anyway) to a flat 7 on 2026-09-06, and the Overdrive price was raised
# from 2-for-+3 to 3-for-+5 the same day.
CYBORG_DRAINED_AT = 7
OVERDRIVE_DRAIN_COST = 3
OVERDRIVE_BONUS = 5

# Mind Pull's two numbers: what trying costs, and the faces that land
# it. Both the author's -- the steal number stayed at 1-2 when the
# trigger was broadened from "through" to "to or through" on
# 2026-09-06, which is the change that makes a 1-space pass pullable
# at all.
MIND_PULL_TOKEN_COST = 1
MIND_PULL_SUCCESS_FACES = (1, 2)

# What each ability is called, for the messages the bot posts when one
# fires. The names are the author's and are on the printed cards, so a
# coach reading "Volatile" in the channel and one holding the reference
# card are reading the same word.
SPECIES_ABILITY_NAMES: dict[str, str] = {
    SPECIES_FIRE_DEMON: "Volatile",
    SPECIES_CYBORG: "Lithium Powered",
    SPECIES_TELEKINETIC: "Mind Pull",
    SPECIES_OOZE: "Slimey",
}


def load_species_abilities() -> dict[str, dict[str, str]]:
    """
    The four species abilities as `species.json` holds them, keyed
    `fire_demon` / `cyborg` / `telekinetic` / `ooze`.

    Here rather than in `d12ball/species_cards.py`, which had it while
    the abilities were print-only: the bot plays them now and cannot
    import a Pillow module to read a JSON file. `species_cards.py`
    re-exports it.
    """
    data = json.loads(SPECIES_FILE.read_text(encoding="utf-8"))
    return data["species"]


@dataclass(frozen=True)
class PlayerDefinition:
    """
    A player, independent of any team -- since the 2026-08-17 eight-team
    split, one player belongs to two rosters at once (a color team and
    a species team), so there is no single `Team` that is theirs to
    carry. `PlayerCatalog.teams` says which rosters hold a given id;
    `MatchState.team_for_player` says which of them a *match* is
    fielding the player as. Nothing here should grow a `team` field
    back -- see "Team colors" in CLAUDE.md.
    """

    player_id: str
    name: str
    role: PlayerRole
    stat_overrides: dict
    # A player's species -- Fire Demon, Cyborg, Telekinetic or Ooze --
    # which is what a species team's roster is drawn from and what a
    # color team's roster now mixes three-of-its-own with two of each
    # other. Optional so a players.json written before the column
    # existed still loads; nothing here defaults a missing species to
    # anything meaningful, so a caller that needs one has to check.
    species: str = ""


@dataclass(frozen=True)
class ShotDefender:
    """
    A defending player in the way of a score attempt, and how much of
    their defensive skill the shot is actually up against.

    Standing on the ball is worth all of it; anyone further along the
    way to goal is worth half, rounded up -- see "Score attempt" in
    docs/living-rules.md. **The halving is per player, not over the
    group's total**: two 5s in the way add 3 + 3 = 6, where halving
    their sum would give 5. That is the author's reading, and the two
    diverge whenever more than one defender rounds up.

    `defense` is the skill the player has, kept beside the value they
    contribute because the image and the dice roll both show the
    arithmetic -- a lone 2 in the way is unreadable without the 4 it
    came from.
    """

    player: PlayerDefinition
    defense: int
    on_ball: bool

    @property
    def value(self) -> int:
        return self.defense if self.on_ball else ceil(self.defense / 2)


# A player belongs to two rosters -- their color team and their species
# team -- so the two sides of a match can field the same person twice.
# That is a duplicate, not a shared card: the two copies are separate
# players of the game, exhausted, injured, substituted and sent about
# independently, and they can be made to challenge each other. See "One
# player, both sides" in CLAUDE.md.
#
# Everything in a match is keyed by a **card id**, which is the catalog
# player's id for the home copy and this suffix on top of it for the
# visiting one. Keeping the ids distinct is what lets the board, the
# benches, the exhaustion counts, the injury queue and every button's
# custom_id go on saying "this player" with one string, as they always
# have -- the alternative was making all of them carry a side as well.
#
# One suffix level is enough and always will be: two rosters can share
# a player and a match has two sides, so a third copy has nowhere to
# come from. `TeamDefinition`'s own uniqueness check is what holds the
# other half of that up.
DUPLICATE_CARD_SUFFIX = "~2"


def duplicate_card_id(player_id: str) -> str:
    """The visiting side's card id for a player the home side fields."""
    return f"{player_id}{DUPLICATE_CARD_SUFFIX}"


def catalog_player_id(card_id: str) -> str:
    """
    The catalog player a match card is a copy of -- itself, for every
    card but a duplicate.

    A pure function of the id rather than a lookup on the match, so
    anything holding a card id can resolve it: `player_by_id`,
    `player_index` in `d12ball/render.py` (which pre-aliases both forms
    rather than calling this per lookup), and a saved game reloaded
    without the catalog to hand.
    """
    if card_id.endswith(DUPLICATE_CARD_SUFFIX):
        return card_id[: -len(DUPLICATE_CARD_SUFFIX)]
    return card_id


@dataclass(frozen=True)
class TeamDefinition:
    team: Team
    players: tuple[PlayerDefinition, ...]

    def __post_init__(self) -> None:
        if len(self.players) != 9:
            raise ValueError(
                f"{team_display_name(self.team)} must have exactly 9 players."
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
        """
        The player a card id names, **carrying that card's own id**.

        A duplicate resolves to the same person as the card it copies
        -- same name, role, skills and portrait -- but comes back
        under the id it was asked for. That is what keeps
        `match.team_for_player(player.player_id)` right: some ninety
        call sites resolve a card id to a definition and then read the
        id back off it to ask which side the card is on, and a
        definition handing back the *catalog* id would answer for the
        home copy every time. The card id is the identity in a match;
        the catalog id is only how the roster is looked up.
        """
        wanted = catalog_player_id(player_id)
        for roster in self.teams.values():
            for player in roster.players:
                if player.player_id == wanted:
                    return (
                        player
                        if player_id == wanted
                        else replace(player, player_id=player_id)
                    )
        raise ValueError(f"Unknown player: {player_id}")

    def shared_player_ids(self, first: Team, second: Team) -> set[str]:
        """
        The players on both of these teams' rosters -- the ones a match
        between them fields twice, once a side.
        """
        return {
            player.player_id
            for player in self.teams[Team(first)].players
        } & {
            player.player_id
            for player in self.teams[Team(second)].players
        }


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
class TeamBoardDefinition:
    areas: tuple[str, ...]
    offense_die: DieDefinition
    defense_die: DieDefinition
    team_die: DieDefinition


@dataclass
class TeamBoardState:
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
    team_board: TeamBoardState

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

    def card_id_for(self, player_id: str) -> str:
        """
        The id this side holds a catalog player under -- their own, or
        `duplicate_card_id` when this is the copy of somebody the
        other side is fielding too. See "One player, both sides" in
        CLAUDE.md.

        Anything walking a *roster* and asking the match about each
        player has to come through here, since the roster is the
        catalog's and the match is keyed by card.
        """
        duplicate = duplicate_card_id(player_id)
        if duplicate in (
            self.field_players
            + self.team_board.bench
            + self.team_board.back_bench
        ):
            return duplicate
        return player_id

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
            + self.team_board.bench
            + self.team_board.back_bench
        )
        if len(set(assigned)) != len(assigned):
            raise ValueError("Every roster player must be assigned once.")
        # Card ids, which are the roster's own except where this side
        # is the duplicate of a player the other side fields too. A
        # side is checked against its whole roster either way -- the
        # suffix says which copy of a player this is, never which
        # player.
        if {
            catalog_player_id(card_id) for card_id in assigned
        } != {
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
            "team_board": {
                "bench": list(self.team_board.bench),
                "back_bench": list(self.team_board.back_bench),
                "offense_die_value": (
                    self.team_board.offense_die_value
                ),
                "defense_die_value": (
                    self.team_board.defense_die_value
                ),
                "team_die_value": self.team_board.team_die_value,
            },
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TeamSetup":
        # `player_board` is what this key was called before the board was
        # renamed, and a game saved under the old name outlives the rename
        # -- both developers run the bot against their own saves. Written
        # only as `team_board`, so the old name dies out on its own.
        board_data = data.get("team_board") or data["player_board"]
        return cls(
            team=Team(data["team"]),
            side=TeamSide(data["side"]),
            zones={
                Zone(zone): list(players)
                for zone, players in data["zones"].items()
            },
            team_board=TeamBoardState(
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

# The shortest High Pass a coach may choose. A Fullback's ability
# raises the maximum to 4, never this -- and this is the one that
# decides whether there is a choice to make at all, since a position
# where even a 2 runs out of field makes every distance identical.
# See MatchState.high_pass_distance_is_moot.
MIN_HIGH_PASS_DISTANCE = 2


@dataclass(frozen=True)
class FormationShape:
    """How many cards a formation puts in each of the three areas."""

    own_goal: int
    midfield: int
    opponent_goal: int
    # Which board sizes the shape may be played on, or None for every
    # board -- which is what the three shapes every game has always had
    # carry. It is data rather than a rule read off the geometry
    # because the two disagree: 2-3-1 overfills a six-space midfield and
    # is played there anyway. See Formation in d12ball/game.py.
    board_sizes: Optional[tuple[int, ...]] = None

    def __post_init__(self) -> None:
        if self.total != FIELD_PLAYER_COUNT:
            raise ValueError(
                f"A formation must field {FIELD_PLAYER_COUNT} players."
            )
        if min(self.own_goal, self.midfield, self.opponent_goal) < 1:
            raise ValueError("A formation must fill every zone.")
        if self.board_sizes is not None and not self.board_sizes:
            raise ValueError(
                "A formation restricted to no board at all cannot be "
                "played; leave board_sizes out to allow every board."
            )

    @property
    def total(self) -> int:
        return self.own_goal + self.midfield + self.opponent_goal

    def count(self, area: str) -> int:
        if area not in SETUP_AREAS:
            raise ValueError(f"Unknown setup area: {area}")
        return getattr(self, area)

    def counts(self) -> dict[str, int]:
        return {area: self.count(area) for area in SETUP_AREAS}

    def allows_board(self, board_size: int) -> bool:
        return self.board_sizes is None or board_size in self.board_sizes

    def board_size_label(self) -> str:
        """Which boards the shape is played on, for a refusal."""
        sizes = self.board_sizes or ()
        return " or ".join(f"{size}-space" for size in sorted(sizes))


@dataclass(frozen=True)
class BasicRuleset:
    ruleset_id: str
    board_layouts: dict[int, BoardLayout]
    formations: dict[Formation, FormationShape]
    standard_setup: dict[str, tuple[PlayerRole, ...]]
    team_board: TeamBoardDefinition

    def formations_for_board(
        self,
        board_size: int,
    ) -> dict[Formation, FormationShape]:
        """
        The shapes a coach may pick on a board this size, in the
        ruleset's own order. **This is the only reading of which
        formations a board offers** -- the menu builds from it, the
        board a side is standing in is named from it, and
        `formation_shape` refuses on it, so a shape cannot be offered
        in one place and refused in another.
        """
        return {
            formation: shape
            for formation, shape in self.formations.items()
            if shape.allows_board(board_size)
        }

    def formation_shape(
        self,
        formation: Formation,
        board_size: int,
    ) -> FormationShape:
        """
        A formation's counts, refusing one this board does not play.
        Every caller has a board in hand, so the check costs nothing and
        the refusal is worded once.
        """
        formation = Formation(formation)
        shape = self.formations[formation]
        if not shape.allows_board(board_size):
            raise ValueError(
                f"{formation.value} is played on a "
                f"{shape.board_size_label()} board, and this one has "
                f"{board_size} spaces."
            )
        return shape


# The two tiers a maneuver can belong to. Basic is the game as it has
# always been played; advanced is the second set the 2026-08-17 ruling
# added, one card per basic card at the same rank -- see "Advanced
# maneuvers" in docs/living-rules.md.
# Setup Pass's three distances, and its clock cost. It is High Pass's
# rank and carries High Pass's two space minutes; 0 is a teammate
# sharing the passer's own space.
SETUP_PASS_DISTANCES = (0, 1, 3)
# The Fullback's +1, which is the same ability that takes a basic High
# Pass from 3 to 4 and a Clear from 3 to 4 (the author, 2026-08-19).
SETUP_PASS_FULLBACK_DISTANCE = 4
SETUP_PASS_CLOCK_COST = 2
# How far a Skilled Pass reaches, either way. The card was Precise
# Pass and read "any teammate", which on the nine-space board is a
# pass across the whole field; the author bounded it at 3 and renamed
# it on 2026-08-26. A distance running off the end of the board is
# dropped by `RulesEngine.low_pass_receivers`, so this is a reach and
# not a promise that all seven destinations exist.
SKILLED_PASS_REACH = 3
# How far a Dribble Burst runs, at most -- the coach picks 1 up to
# this, or as far as the field allows if that is shorter. It used to
# be a run to the last space of the goal they attack, which was no
# choice at all; the author bounded it on 2026-08-26 and the pick is
# what the exhaustion is charged against.
DRIBBLE_BURST_MAX_DISTANCE = 4

MANEUVER_TIER_BASIC = "basic"
MANEUVER_TIER_ADVANCED = "advanced"
MANEUVER_TIERS = (MANEUVER_TIER_BASIC, MANEUVER_TIER_ADVANCED)


def maneuver_key(name: str) -> str:
    """
    The stable identifier for a maneuver, derived from its printed
    name: `"Steal Intercept"` -> `"steal_intercept"`.

    **A maneuver's identity is not its printed name.** It used to be:
    `match.offense_maneuver` held the string `"Low Pass"` and a dozen
    sites compared against those literals, which meant a rename
    upstream was a code change and a saved game held a display string.
    The author renamed the basic D2 card from "Steal Intercept" to
    "Steal" on 2026-08-18, when the advanced D2 card became
    "Intercept", and that is exactly the change that would have
    silently broken every one of them.
    """
    return re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")


# **What a rename leaves behind**, which is the one thing a key cannot
# be derived through. A key is the slug of the printed name, so a card
# renamed upstream gets a new key -- and a game saved mid-turn holds
# the old one, either as the key itself or, for a game older than keys
# altogether, as the printed name in
# `offense_maneuver`/`defense_maneuver`. Both forms slug to the same
# string, so one table answers for both.
#
# Same tolerant shape as `player_board`/`team_board` and `tie_mode`:
# nothing writes the old form any more, so each entry dies out on its
# own. Don't add a migration pass for it, and don't drop an entry until
# no half-finished game can predate that rename -- both developers run
# the bot from their own tree against their own saves.
LEGACY_MANEUVER_KEYS = {
    "steal_intercept": "steal",
    "block_deflect": "deflect",
    # The author renamed the advanced O1 card from "Precise Pass" to
    # "Skilled Pass" on 2026-08-26, when its reach was bounded at 3.
    "precise_pass": "skilled_pass",
}


def legacy_maneuver_key(stored: Optional[str]) -> Optional[str]:
    """A stored maneuver, as a key, whichever form it was saved in."""
    if stored is None:
        return None
    key = maneuver_key(stored)
    return LEGACY_MANEUVER_KEYS.get(key, key)


@dataclass(frozen=True)
class ManeuverDefinition:
    """
    One maneuver as the spreadsheet prints it.

    `key` is what the match, the buttons and every dispatch table hold;
    `name` is only ever displayed. `defeats_rank` is the *rank* this
    maneuver beats rather than a name, because since advanced mode
    landed each rank has two cards on it -- the basic one and its
    advanced counterpart -- and **rank alone decides** who wins (the
    author, 2026-08-18). Naming one of the two would be naming half a
    relation.
    """

    name: str
    key: str
    rank: int
    tier: str
    die_values: tuple[int, ...]
    defeats_rank: int
    effect: str
    time: str

    @property
    def is_advanced(self) -> bool:
        return self.tier == MANEUVER_TIER_ADVANCED


@dataclass(frozen=True)
class ManeuverCatalog:
    """
    Every maneuver in the game, both tiers, split by side.

    **Lookups are by key, never by printed name.** `offense`/`defense`
    hold basic and advanced together, ordered by rank then tier, and a
    caller that wants only one tier asks `for_tier`. Which maneuvers a
    particular game offers is the game's mode to decide, not the
    catalog's -- see `RulesEngine.maneuver_hand`.
    """

    data_version: int
    source: str
    offense: tuple[ManeuverDefinition, ...]
    defense: tuple[ManeuverDefinition, ...]

    def side(self, side: str) -> tuple[ManeuverDefinition, ...]:
        return self.offense if side == "offense" else self.defense

    def by_key(self) -> dict[str, ManeuverDefinition]:
        return {
            maneuver.key: maneuver
            for maneuver in self.offense + self.defense
        }

    def get(self, key: str) -> Optional[ManeuverDefinition]:
        return self.by_key().get(key)

    def definition(self, key: str) -> ManeuverDefinition:
        maneuver = self.get(key)
        if maneuver is None:
            raise KeyError(f"Unknown maneuver key {key!r}.")
        return maneuver

    def display_name(self, key: Optional[str]) -> str:
        """
        What to print for a maneuver key. Falls back to the key itself
        for a maneuver the data no longer carries, so a game saved
        against an older `maneuvers.json` still words its messages.
        """
        if key is None:
            return ""
        maneuver = self.get(key)
        return maneuver.name if maneuver is not None else key

    def for_tier(
        self, side: str, tier: str,
    ) -> tuple[ManeuverDefinition, ...]:
        return tuple(
            maneuver
            for maneuver in self.side(side)
            if maneuver.tier == tier
        )

    def counterpart(self, maneuver: ManeuverDefinition) -> ManeuverDefinition:
        """
        The card on the same side and rank in the other tier -- an
        advanced maneuver's basic equivalent, or the other way round.

        The pairing is by **rank**, not by a table: every advanced card
        is identical to its basic counterpart in every column but
        `Effect` (see docs/advanced-maneuver-matrix.md), which is what
        makes "a skill test resolves it as the basic card" a rule the
        data can answer rather than six sentences somebody wrote down.
        """
        other = (
            MANEUVER_TIER_BASIC
            if maneuver.is_advanced
            else MANEUVER_TIER_ADVANCED
        )
        for candidate in self.for_tier(self.side_of(maneuver.key), other):
            if candidate.rank == maneuver.rank:
                return candidate
        raise KeyError(
            f"{maneuver.name} has no {other} counterpart at rank "
            f"{maneuver.rank}."
        )

    def side_of(self, key: str) -> str:
        if any(maneuver.key == key for maneuver in self.offense):
            return "offense"
        if any(maneuver.key == key for maneuver in self.defense):
            return "defense"
        raise KeyError(f"Unknown maneuver key {key!r}.")

    def offense_for_die(self, value: int) -> ManeuverDefinition:
        for maneuver in self.for_tier("offense", MANEUVER_TIER_BASIC):
            if value in maneuver.die_values:
                return maneuver
        raise ValueError(f"No offense maneuver covers die value {value}.")

    def defense_for_die(self, value: int) -> ManeuverDefinition:
        for maneuver in self.for_tier("defense", MANEUVER_TIER_BASIC):
            if value in maneuver.die_values:
                return maneuver
        raise ValueError(f"No defense maneuver covers die value {value}.")

    def resolve(self, offense_key: str, defense_key: str) -> str:
        """
        The outcome of an offense maneuver against a defense maneuver:
        "offense" or "defense" if one defeats the other, otherwise
        "tie".

        **Rank alone decides** (the author, 2026-08-18), so advanced
        mode adds no new way to win a maneuver: the 12x12 grid is the
        existing 3x3 cycle repeated four times. An advanced card beats
        exactly what its basic counterpart beats, including that
        counterpart itself.
        """
        offense = self.definition(offense_key)
        defense = self.definition(defense_key)

        if offense.defeats_rank == defense.rank:
            return "offense"
        if defense.defeats_rank == offense.rank:
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


# One running clock over both periods: 00-15 in the first half, 16-30
# in the second -- see "Clock, halftime, and full time" in
# docs/living-rules.md. A period's last minute is where **last
# possession** begins and not where the clock stops; the clock keeps
# counting for as long as that possession runs, so a first half can
# genuinely end at 19. The second half then starts at 16 regardless,
# which is what makes minutes 16 and up occur twice in a game.
FIRST_HALF_LAST_MINUTE = 15
SECOND_HALF_START_MINUTE = 16
SECOND_HALF_LAST_MINUTE = 30


def period_last_minute(period: MatchPeriod) -> int:
    """
    The minute at which a period's last possession begins. The only
    number the running clock adds: the rule is still "at the period's
    last minute, use last possession", asked of a clock that no longer
    resets between halves.
    """
    return (
        FIRST_HALF_LAST_MINUTE
        if MatchPeriod(period) == MatchPeriod.FIRST_HALF
        else SECOND_HALF_LAST_MINUTE
    )


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
        # A floor and nothing else. The clock used to be checked
        # against range(0, 16), which was the clamp restated -- with
        # the clamp gone there is no upper bound to restate, since
        # nothing caps how long a last possession runs. A saved game
        # from before the running clock is inside this either way.
        if self.time < 0:
            raise ValueError("The game clock cannot be negative.")

    @property
    def last_minute(self) -> int:
        """Where this period's last possession begins."""
        return period_last_minute(self.period)

    @property
    def past_last_minute(self) -> bool:
        """
        Whether the clock has run beyond this period's last minute,
        which only a last possession can do. It is what tells a first
        half's minute 17 from the second half's -- see the goal log.
        """
        return self.time > self.last_minute


@dataclass
class GoalRecord:
    """
    One goal, as the game will want to read it back at full time: who
    it counts for, who put it in, and when.

    **`side` is who it counts for and `player_id` is who kicked it**,
    which is the same person for every goal but an own goal -- there
    the defender who failed the roll is credited with it in the *other*
    team's column, marked (OG). Storing the pair rather than the
    scoring side alone is the whole of what makes that possible after
    the fact.

    **The period is stored beside the minute and is not decoration.**
    The clock runs past a period's last minute, so a first half can
    reach 17 and so can the second; without the period a goal in the
    first half's last possession is indistinguishable from one in the
    opening minutes of the second. See `overran_the_period`.
    """

    side: TeamSide
    player_id: str
    time: int
    period: MatchPeriod
    own_goal: bool = False
    # A shootout goal has no minute worth reading -- it is scored after
    # the whistle -- so it is listed apart from the game's own goals
    # rather than at whatever the clock happened to stop on.
    shootout: bool = False

    def __post_init__(self) -> None:
        self.side = TeamSide(self.side)
        self.period = MatchPeriod(self.period)

    @property
    def in_first_half_overrun(self) -> bool:
        """
        Whether this goal's minute is one the second half will reach
        again: a first-half goal past 15, scored in that half's last
        possession. It is exactly the condition the **(FH)** marker
        states, so the marker cannot drift from what it means.

        The second half needs no marker of its own. It overruns as
        readily -- a goal at 31 or 32 -- but no first-half minute is
        stamped with the marker missing, so an unmarked number can only
        be read one way.
        """
        return (
            not self.shootout
            and self.period == MatchPeriod.FIRST_HALF
            and self.time > period_last_minute(self.period)
        )

    def to_dict(self) -> dict:
        return {
            "side": self.side.value,
            "player_id": self.player_id,
            "time": self.time,
            "period": self.period.value,
            "own_goal": self.own_goal,
            "shootout": self.shootout,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GoalRecord":
        return cls(
            side=TeamSide(data["side"]),
            player_id=data["player_id"],
            time=data["time"],
            period=MatchPeriod(data["period"]),
            own_goal=data.get("own_goal", False),
            shootout=data.get("shootout", False),
        )


# What a MatchEvent's `kind` may be. Strings rather than an Enum for
# the reason the maneuver keys are strings: they go into a save file
# and come back out of one, and a kind written by a build older than
# the reader has to survive the round trip rather than raise. An
# unrecognised kind is skipped by the fold in `d12ball/stats.py` and
# kept in the log.
EVENT_TURN_ACTION = "turn_action"
EVENT_MANEUVER = "maneuver"
EVENT_SKILL_TEST = "skill_test"
EVENT_SHOT = "shot"
EVENT_OWN_GOAL_ROLL = "own_goal_roll"
EVENT_INJURY_TEST = "injury_test"
EVENT_GOAL = "goal"

# How a maneuver came to be won -- `details["decision"]` on a
# `maneuver` event. The four are what `resolve_maneuver` already words
# four different ways, named so the fold can tell them apart:
# `CARDS` is the ranking deciding it outright, `SKILL_TEST` a tie (or
# an injured player's downgraded win) settled on the dice,
# `INJURY_FORFEIT` a tie one injured participant loses with nothing
# rolled, and `UNCONTESTED` a maneuver the defense never challenged.
#
# **Only the first three are a contest**, which is what a success rate
# has to be measured over: an uncontested maneuver always wins, so
# counting it inflates every offense card it is available to. See
# `contested_maneuvers` in `d12ball/stats.py`.
DECISION_CARDS = "cards"
DECISION_SKILL_TEST = "skill_test"
DECISION_INJURY_FORFEIT = "injury_forfeit"
DECISION_UNCONTESTED = "uncontested"

CONTESTED_DECISIONS = frozenset(
    {DECISION_CARDS, DECISION_SKILL_TEST, DECISION_INJURY_FORFEIT}
)


@dataclass
class MatchEvent:
    """
    One thing that happened in a match, in the order it happened --
    the record `d12ball/stats.py` folds into every statistic the bot
    reports.

    It exists for the reason `GoalRecord` does, one step further on:
    a match holds the *current* position, so who was injured is
    readable and what injured them is not, and how many tokens a
    player is carrying is readable and what charged them is not.
    Neither can be reconstructed after the fact, so they are written
    down as they happen.

    **The list's order is the whole of its structure.** There is no
    turn counter and no possession counter, deliberately: an event
    belongs to the last `turn_action` before it, and a possession is
    a run of consecutive `turn_action`s by one side. Both are exact
    reads of the order, where a stored counter is a second thing that
    can disagree with it -- and a counter would have to be cleared,
    bumped and persisted in step with a flow that already has enough
    of those.

    `details` is per-kind and documented on the recorder that writes
    it (`MatchState.record_event`'s callers). A dict rather than a
    field per kind because the kinds share almost nothing -- a shot
    carries its two totals, a maneuver carries two keys and a winner
    -- and the one consumer is a fold that already branches on kind.
    """

    kind: str
    period: MatchPeriod
    time: int
    side: Optional[TeamSide] = None
    player_id: Optional[str] = None
    details: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.period = MatchPeriod(self.period)
        if self.side is not None:
            self.side = TeamSide(self.side)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "period": self.period.value,
            "time": self.time,
            "side": None if self.side is None else self.side.value,
            "player_id": self.player_id,
            "details": dict(self.details),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MatchEvent":
        return cls(
            kind=data["kind"],
            period=MatchPeriod(data["period"]),
            time=data["time"],
            side=(
                None
                if data.get("side") is None
                else TeamSide(data["side"])
            ),
            player_id=data.get("player_id"),
            details=dict(data.get("details", {})),
        )


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
    zone: Zone,
    zone_spaces: int,
    player_count: int,
) -> list[int]:
    """
    Which space each of a zone's cards starts on, in the order the
    coach assigned them.

    **A goal zone spreads its cards over its whole depth**: the first
    stands on that side's own end of the zone, the last on the far
    end, and any in between are spaced evenly. A zone no deeper than
    it is full comes out exactly as packing it would -- which is every
    goal zone on boards 6 and 7 -- so this is only ever visible on
    board 9, where the three-space zones would otherwise bunch each
    pair against one edge and leave the third space empty. There it
    puts the home Defender on H3 and the home Striker on V3.

    **Midfield is packed outward from that side's own end instead**,
    because the kickoff space is in it: the side kicking off has to
    have somebody standing on that space, and spreading two cards
    across a three-space midfield would leave the middle one -- the
    kickoff space on boards 7 and 9 -- empty and hold the coach in the
    setup window until they moved somebody onto it.

    Either way a surplus goes round the zone again, so every space is
    taken before any space takes a second player. That satisfies the
    run back's coverage rule from the kickoff, and spreads a surplus
    rather than piling it up, which is legal either way and easier to
    read on the board.

    Home defends the low indices and the visiting team the high ones,
    so the two orders are mirror images.
    """
    side = TeamSide(side)
    zone = Zone(zone)
    order = (
        list(range(zone_spaces))
        if side == TeamSide.HOME
        else list(reversed(range(zone_spaces)))
    )
    if zone != Zone.MIDFIELD and 1 < player_count <= zone_spaces:
        step = (zone_spaces - 1) / (player_count - 1)
        order = [order[round(index * step)] for index in range(player_count)]
    return [order[index % len(order)] for index in range(player_count)]


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


@dataclass(frozen=True)
class SavedField:
    """
    One field of a match that is saved and read back on its own terms:
    its key, what a save older than the field comes back as, and any
    conversion either way.

    `default` is for an immutable fallback and `factory` for a mutable
    one, exactly as `dataclasses.field` splits them -- a shared `[]`
    handed to every game that predates a field is the same bug there
    as anywhere else.

    `write` and `read` are the copies. A mutable field written straight
    into the dict is one the live match can go on mutating between
    `to_dict` and the save landing, and one read straight out is a
    match holding a reference into the loaded JSON. Both directions are
    usually the same callable; `declared_substitution` is the one that
    differs, stored `sorted` so a save file is stable and read back as
    a set.
    """

    name: str
    default: Any = None
    factory: Optional[Callable[[], Any]] = None
    write: Optional[Callable[[Any], Any]] = None
    read: Optional[Callable[[Any], Any]] = None

    def stored(self, value: Any) -> Any:
        """The value as it goes into the save."""
        return self.write(value) if self.write is not None else value

    def restored(self, data: dict) -> Any:
        """The value as it comes back, for a save that may predate it."""
        if self.name not in data:
            return self.factory() if self.factory is not None else self.default
        value = data[self.name]
        return self.read(value) if self.read is not None else value


def copy_lists(mapping: dict) -> dict:
    """`{key: list(value)}` -- one level deeper than `dict()` copies."""
    return {key: list(value) for key, value in mapping.items()}


# Every field of a match whose save is "write it, read it back, and
# fall back to this when the file predates it". The structured ones --
# the board, the two setups, the ball, the scoreboard, the maneuver
# keys with their legacy translation, the five coaching fields with
# their `pending_substitution_*` fallbacks, and the goal log -- are
# spelled out in `to_dict`/`from_dict` themselves, because each of
# them says something a table cannot.
#
# **A field on MatchState that is in neither place is not saved**, and
# nothing about that failure is visible until a restart drops it.
# `MatchStateSerializationTests` is what makes it impossible: it walks
# the dataclass and fails on any field this table and the explicit set
# between them do not name.
MATCH_SAVED_FIELDS: tuple[SavedField, ...] = (
    SavedField("active_player_id"),
    SavedField("ball_carrier_id"),
    SavedField("pending_action"),
    SavedField("challenger_id"),
    SavedField("maneuver_uncontested", default=False),
    SavedField("volatile_tier_upgrade", default=False),
    SavedField(
        "pending_overdrive", factory=list, write=list, read=list,
    ),
    # Mind Pull. The path is a list of [zone, index] pairs, so the
    # copies are deep enough to matter: a shallow list() would hand a
    # restored match the same inner lists the saved dict holds.
    SavedField(
        "last_ball_path",
        factory=list,
        write=lambda path: [list(step) for step in path],
        read=lambda path: [list(step) for step in path],
    ),
    SavedField(
        "pending_mind_pull", factory=list, write=list, read=list,
    ),
    SavedField("pending_mind_pull_resume"),
    SavedField("pending_run_back", default=False),
    SavedField("pending_run_back_distance", default=1),
    SavedField("pending_run_back_turnover", default=True),
    SavedField("pending_run_back_stays_player_id"),
    SavedField("pending_run_back_speed_choice", default=False),
    SavedField("pending_effect_continuation"),
    SavedField("pending_double_team", factory=list, write=list, read=list),
    # The event log. Empty for a game saved before it existed, which
    # is what makes such a game load and simply report no statistics
    # rather than a wrong set of them -- see build_stats_report.
    SavedField(
        "events",
        factory=list,
        write=lambda events: [event.to_dict() for event in events],
        read=lambda events: [MatchEvent.from_dict(event) for event in events],
    ),
    SavedField("pending_kickoff_fill", default=False),
    SavedField("pending_shot_is_set_up", default=False),
    SavedField("pending_shot_setup_cost", default=0),
    SavedField("pending_high_pass_overshoot", default=False),
    SavedField("pending_own_goal", default=False),
    SavedField("pending_own_goal_distance", default=1),
    SavedField("pending_injury_tests", factory=list, write=list, read=list),
    # Copied on the way out only. It is a dict or None, and the read
    # side has never copied it.
    SavedField(
        "pending_injury_resume",
        write=lambda value: dict(value) if value is not None else None,
    ),
    SavedField("pending_loose_ball", default=False),
    SavedField("pending_loose_ball_distance", default=1),
    SavedField("pending_loose_ball_is_high_pass", default=False),
    # True for a save that predates it, which is the old behaviour: a
    # ball was loose wherever it landed, so every side could be sent.
    SavedField("pending_loose_ball_on_empty_space", default=True),
    SavedField("loose_ball_offense_player"),
    SavedField("loose_ball_defense_player"),
    SavedField("loose_ball_offense_declined", default=False),
    SavedField("loose_ball_defense_declined", default=False),
    SavedField("pending_ball_recovery", default=False),
    SavedField("pending_cede", default=False),
    SavedField(
        "declared_substitution", factory=set, write=sorted, read=set,
    ),
    SavedField(
        "half_substitutions_used", factory=dict, write=dict, read=dict,
    ),
    SavedField(
        "pending_coaching_swaps",
        factory=list,
        write=lambda swaps: [list(swap) for swap in swaps],
        read=lambda swaps: [list(swap) for swap in swaps],
    ),
    # A window open when the bot went down keeps its summary, so a
    # resumed Coaching Choice still closes with what the coach did
    # before the restart. A game saved before these existed comes back
    # with nothing recorded, and closes saying only that the side is
    # done.
    SavedField("pending_coaching_formation"),
    SavedField("pending_halftime_stage"),
    SavedField("pending_setup_stage"),
    # None for every game saved before the whistle offered a window,
    # including one already in a shootout: those went straight from
    # full time to the order prompt and are past this either way.
    SavedField("pending_full_time_stage"),
    # A game saved before arrangements were remembered has none. Left
    # empty, restore_assigned_positions moves nobody, so such a game
    # keeps the old behaviour until its next window sets one.
    SavedField(
        "assigned_positions", factory=dict, write=copy_lists, read=copy_lists,
    ),
    SavedField("pending_shootout", default=False),
    SavedField("shootout_round", default=0),
    SavedField(
        "shootout_orders", factory=dict, write=copy_lists, read=copy_lists,
    ),
    SavedField(
        "shootout_used", factory=dict, write=copy_lists, read=copy_lists,
    ),
    SavedField("shootout_shooters", factory=dict, write=dict, read=dict),
    SavedField("shootout_goals", factory=dict, write=dict, read=dict),
)

# The fields `to_dict`/`from_dict` handle themselves, listed so the
# coverage test can tell "deliberately explicit" from "forgotten".
MATCH_EXPLICIT_FIELDS: frozenset[str] = frozenset(
    {
        "ruleset_id",
        "player_data_version",
        "board",
        "home",
        "visiting",
        "ball",
        "scoreboard",
        # Read back together: exhaustion and exhausted are both
        # filtered against injured.
        "exhaustion",
        "exhausted",
        "injured",
        # legacy_maneuver_key on the way in.
        "offense_maneuver",
        "defense_maneuver",
        # Each carries a pending_substitution_* fallback.
        "pending_coaching_side",
        "pending_coaching_occasion",
        "pending_coaching_substitutions",
        "pending_coaching_is_response",
        "pending_coaching_declared",
        "goals",
    }
)


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
    # Who the last resolution left the ball with, when it left it with
    # somebody in particular -- the dribbler, the player pushed back by
    # a Pressure, the stealer, the player a pass was aimed at. That
    # player takes their side's next turn instead of the coach picking
    # again off the ball's space. Cleared when the ball comes free, and
    # consumed by select_ball_handler. See "Choosing the handler" in
    # docs/living-rules.md.
    ball_carrier_id: Optional[str] = None
    pending_action: Optional[str] = None
    challenger_id: Optional[str] = None
    # Set instead of challenger_id when the defending team has nobody
    # in the ball's zone: the offense picks a maneuver on its own and
    # it succeeds outright. Unlike challenger_id this is persisted --
    # it is what tells a restart that the missing defense_maneuver is
    # never coming. See begin_uncontested_maneuver.
    maneuver_uncontested: bool = False
    # Both hold a **maneuver key** (`low_pass`, `double_team`), never a
    # printed name -- see `maneuver_key`. A game saved before the keys
    # existed holds a name, which `legacy_maneuver_key` translates on
    # load.
    offense_maneuver: Optional[str] = None
    defense_maneuver: Optional[str] = None
    # **Volatile's tier rider**: the skill test that just resolved was
    # ignited in a way that raises the *winner's* maneuver to its
    # advanced version -- see "Volatile (Fire Demon)" in
    # docs/living-rules.md.
    #
    # The rules name two cases and both come to the same one: a surge
    # on the winning side raises that side's maneuver, and a backfire
    # on the losing side raises "the opponent's", who is the winner.
    # So this is one flag rather than a side, and `resolving_maneuver`
    # is the only thing that reads it.
    #
    # **It is already gated when it is set.** `SkillTestView.roll` only
    # raises it in a game playing both modules, so a game that took the
    # species abilities without the advanced maneuvers -- where there
    # is no tier to change and the ignite is only the number -- never
    # sets it, and the reader needs no `game` to ask.
    #
    # Persisted, because the injury tests run between the roll and the
    # effect: a restart in that window has to resolve the maneuver the
    # tier the dice decided, and nothing else on the match records it.
    # `reset_maneuver` clears it with the rest of the turn.
    volatile_tier_upgrade: bool = False
    # **Overdrive declared, and not yet spent**: the Cyborgs who have
    # taken 3 drain to add +5 to the roll that is about to happen. See
    # "Lithium Powered (Cyborg)" in docs/living-rules.md.
    #
    # A list rather than a flag because a contest has two rollers and
    # both may be Cyborgs, and because the ids are what say *whose*
    # total the +5 goes on. Membership is also the "once per roll"
    # check -- `declare_overdrive` refuses a second declaration.
    #
    # It is **declared and paid before the die is thrown** and cleared
    # by the roll that reads it (`consume_overdrive`), which is what
    # makes a tie's re-roll a fresh roll: the +5 does not carry, and
    # the re-roll may be Overdriven again for another 3 drain.
    #
    # Persisted, because the declaration and the roll are two separate
    # clicks with a save between them -- the whole point of declaring
    # blind is that a coach commits and *then* somebody presses Roll.
    pending_overdrive: list[str] = field(default_factory=list)
    # **Mind Pull.** Three fields, and all three exist because a pull
    # is a *choice with a roll* that has to happen before the ball
    # settles -- see "Mind Pull (Telekinetic)" in docs/living-rules.md.
    #
    # `last_ball_path` is where the ball just went, recorded by
    # `set_ball_space` (the one funnel every maneuver's movement comes
    # through) and read by the three arrival points that may offer a
    # pull. `pending_mind_pull` is the Telekinetics still to be asked,
    # **in the order the ball reached them** -- "the first to succeed
    # stops the ball there and the rest get no roll", which is why it
    # is an ordered queue rather than a set, exactly like
    # `pending_injury_tests`. `pending_mind_pull_resume` is the arrival
    # the pull interrupted, so a queue that runs out can put the turn
    # back where it found it -- the same shape, and for the same
    # reason, as `pending_injury_resume`.
    #
    # All three are persisted: a coach may take minutes over the offer,
    # and between the interrupt and the answer these are the only thing
    # on the match saying what the ball was about to do.
    last_ball_path: list[list] = field(default_factory=list)
    pending_mind_pull: list[str] = field(default_factory=list)
    pending_mind_pull_resume: Optional[dict] = None
    exhaustion: dict[str, int] = field(default_factory=dict)
    exhausted: set[str] = field(default_factory=set)
    injured: set[str] = field(default_factory=set)
    pending_run_back: bool = False
    pending_run_back_distance: int = 1
    pending_run_back_turnover: bool = True
    pending_run_back_stays_player_id: Optional[str] = None
    pending_run_back_speed_choice: bool = False
    # **What a maneuver's effect still owes once its last prompt has
    # been answered**, as `{"kind": ..., ...}` -- or None, which is
    # nearly always.
    #
    # Two of the advanced effects reach past their own maneuver.
    # Setup Pass adjusts ball speed and *then* sets up a scoring
    # opportunity; Skilled Pass, when it is beaten, hands the defense
    # an unopposed Low Pass once the steal has settled. Both sit behind
    # a speed choice, which is the last human step of an effect and has
    # always led straight into `finish_maneuver_resolution`. Rather
    # than a flag per case this says what is left to do, the same shape
    # `pending_injury_resume` uses for the same reason -- and it is
    # persisted for the same reason too: a restart between the roll and
    # what it was going to lead to has no other way to know.
    pending_effect_continuation: Optional[dict] = None
    # The two defenders a won Double Team put on the ball, who both
    # challenge the ball holder on the defending side's **next**
    # maneuver, each adding their defensive skill. Empty otherwise.
    # Cleared by a new play, which is the one thing the card says ends
    # it: "so long as it's not a new play".
    pending_double_team: list[str] = field(default_factory=list)
    pending_kickoff_fill: bool = False
    pending_shot_is_set_up: bool = False
    # The base clock cost of the maneuver that offered a pending set-up
    # shot -- 0 for an ordinary shot, otherwise the maneuver's own flat
    # cost (1, or 2 for a High Pass), so ScoreAttemptView.roll can add
    # the shot's own extra minute on top of it rather than replacing it.
    # See "When a maneuver includes a setup" and start_set_up_shot.
    pending_shot_setup_cost: int = 0
    # A High Pass was clamped short of the distance thrown, so the
    # ball speed modifier is paid the other way round for whatever
    # that overshoot leads to -- the set-up's shot, or the long-pass
    # contest behind it. Persisted because both of those outlive the
    # effect that set it: the shot is a view a restart re-attaches,
    # and the contest is rolled a click later. See ball_speed_modifier.
    pending_high_pass_overshoot: bool = False
    # An own-goal roll waiting on a button. The distance is the clock
    # cost of the maneuver that risked it, held here because it is the
    # roll's continuation that spends it and the roll is now a step of
    # its own -- see begin_own_goal_roll.
    pending_own_goal: bool = False
    pending_own_goal_distance: int = 1
    # The injury tests a resolved skill test still owes, in the order
    # they are asked for, and what the contest was going to do once
    # they were done. Both are consumed by continue_injury_tests.
    pending_injury_tests: list[str] = field(default_factory=list)
    pending_injury_resume: Optional[dict] = None
    pending_loose_ball: bool = False
    pending_loose_ball_distance: int = 1
    pending_loose_ball_is_high_pass: bool = False
    # **Whether the ball came down on an empty space**, recorded when
    # it arrived rather than read back off the board. A ball is loose
    # only where nothing is standing (the author, 2026-08-26), and by
    # the time the roll and the result are worded the contestants have
    # been walked onto the space -- so the position that decides the
    # word is gone. Same reason `pending_loose_ball_is_high_pass` is
    # stored: neither is derivable after the fact.
    #
    # A game saved before this field defaults to True, which is what
    # every arrival was called before the correction.
    pending_loose_ball_on_empty_space: bool = True
    loose_ball_offense_player: Optional[str] = None
    loose_ball_defense_player: Optional[str] = None
    loose_ball_offense_declined: bool = False
    loose_ball_defense_declined: bool = False
    pending_ball_recovery: bool = False
    # The ball has been given up to coach and neither side's window has
    # closed yet -- see cede_possession. Persisted because the whole of
    # a cede happens either side of two coaching windows, and by the
    # time the second one closes nothing else in the match says how it
    # got there: the turn was reset before the first one opened, so
    # without this the tail reads as a run back nobody owes. Cleared by
    # reset_maneuver with everything else the turn set.
    pending_cede: bool = False
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
    # What the open window has changed, for the summary it closes with.
    # The whole flow lives on one message, so every note a step leaves
    # -- "so-and-so comes on for so-and-so" above all -- is written
    # over by the next step and gone by the time the coach is done.
    # These two are what survives it: the shape the side was in when
    # the window opened, as a Formation value, and every swap made in
    # it as an [outgoing, incoming] pair.
    pending_coaching_formation: Optional[str] = None
    pending_coaching_swaps: list[list[str]] = field(default_factory=list)
    pending_halftime_stage: Optional[str] = None
    # Which side is still to take their Coaching Choice before kickoff,
    # as a SETUP_STAGES value. None once both have, which is every
    # game saved before setup offered one -- those kicked off on the
    # standard deal and are already past this.
    pending_setup_stage: Optional[str] = None
    # Which side is still to take their Coaching Choice between the
    # whistle and the shootout, as a FULL_TIME_STAGES value. Set only
    # on a level score, and cleared before the shootout opens -- so a
    # saved game has this or `pending_shootout`, never both.
    pending_full_time_stage: Optional[str] = None
    # Where each coach last *put* their meeples, as player_id ->
    # [zone, space_index]. See set_assigned_positions.
    assigned_positions: dict[str, list] = field(default_factory=dict)
    # The extreme shootout, which settles a game level at full time.
    # See "Extreme shootout" in docs/living-rules.md and begin_shootout
    # below. Every one of these is keyed by TeamSide *value*, so it
    # survives a round trip through JSON.
    pending_shootout: bool = False
    # 1 is the ordered round; 2 and up are sudden death, where each
    # shooter is chosen a test at a time. 0 is "no shootout".
    shootout_round: int = 0
    # The six, in the order their coach set them. First round only:
    # sudden death chooses instead, so it writes nothing here.
    shootout_orders: dict[str, list[str]] = field(default_factory=dict)
    # Who has already shot this round, which is what a sudden-death
    # round's eligibility is read from. Cleared when a round ends.
    shootout_used: dict[str, list[str]] = field(default_factory=dict)
    # The player each side has revealed for the test being rolled.
    shootout_shooters: dict[str, str] = field(default_factory=dict)
    # Goals scored in the shootout. They go on the scoreboard as well,
    # so this is not the score -- it is what the "cannot be caught"
    # stop counts, and what the full-time summary reports.
    shootout_goals: dict[str, int] = field(default_factory=dict)
    # Every goal of the game in the order it was scored, shootout ones
    # included. The scoreboard is a running total and cannot be read
    # backwards; this is what says who scored and when. See
    # record_goal, which is the only thing that writes to it.
    goals: list[GoalRecord] = field(default_factory=list)
    # Everything that happened in the match, in the order it happened
    # -- see MatchEvent, and d12ball/stats.py, which is the only thing
    # that reads it. `record_event` is the only thing that writes to
    # it, the way `record_goal` is for the goal log above.
    #
    # It is not state: nothing in the game asks it a question, and a
    # match with an empty log plays identically. That is deliberate,
    # and is what makes a game saved before this field loads and
    # simply reports nothing -- see build_stats_report, which counts
    # itself against the scoreboard rather than trusting the two
    # agree, exactly as build_goal_log does.
    events: list[MatchEvent] = field(default_factory=list)

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
        # create_standard_setup deals a shape without knowing what board
        # it is dealt onto, so this is where the two meet and the only
        # place a match can be built in a shape its board does not play.
        for formation in (home_formation, visiting_formation):
            ruleset.formation_shape(formation, board_size)
        board = BoardState.empty(layout)
        # A color team and a species team overlap -- the color roster
        # is 3 of its own species plus 2 of each other, so any color
        # side meets any species side holding 2 or 3 of the same
        # people. Those are played as two cards, and the visiting one
        # carries the suffix; see "One player, both sides" in CLAUDE.md
        # and `catalog_player_id`. Two teams on one axis are disjoint
        # and this is empty, which is every match before the reshuffle
        # and most of them since.
        shared = catalog.shared_player_ids(home_team, visiting_team)
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
            duplicate_ids=shared,
        )

        for setup in (home, visiting):
            for zone, player_ids in setup.zones.items():
                for player_id, space_index in zip(
                    player_ids,
                    setup_space_order(
                        setup.side,
                        zone,
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

    def team_for_player(self, player_id: str) -> Team:
        """
        Which `Team` this match is fielding `player_id` as -- never the
        player's own `.team`, because `PlayerDefinition` no longer has
        one. A player can belong to two rosters (their color team and
        their species team), so the only thing that decides which one a
        card is being played as is which side of *this match* it is on.

        Checked against `field_players` plus both benches, the same
        roster-membership test `move_meeple` already uses, so a benched
        or back-benched player still resolves.
        """
        for side in (TeamSide.HOME, TeamSide.VISITING):
            setup = self.setup_for_side(side)
            roster_ids = (
                setup.field_players
                + setup.team_board.bench
                + setup.team_board.back_bench
            )
            if player_id in roster_ids:
                return setup.team
        raise ValueError(
            f"{player_id} is not on either side of this match."
        )

    def side_for_player(self, player_id: str) -> TeamSide:
        """
        Which side of this match `player_id` is playing for --
        `team_for_player` asking the same question and answering with
        the position rather than the roster.

        The two are not interchangeable: a card's `Team` is what
        colours it, and its `TeamSide` is what a statistic is grouped
        by. Reading a side back off a team would be wrong exactly
        where it matters, since a color side and a species side can
        field the same person as two cards.
        """
        for side in (TeamSide.HOME, TeamSide.VISITING):
            setup = self.setup_for_side(side)
            roster_ids = (
                setup.field_players
                + setup.team_board.bench
                + setup.team_board.back_bench
            )
            if player_id in roster_ids:
                return side
        raise ValueError(
            f"{player_id} is not on either side of this match."
        )

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

    def turn_handler_candidates(
        self, slip_in_ids: Collection[str] = (),
    ) -> list[str]:
        """
        Who may take this turn: the ball carrier alone when the last
        resolution left the ball in somebody's hands, otherwise every
        eligible handler for the coach to choose between.

        A carrier who is no longer standing on the ball for the side in
        possession is ignored rather than trusted -- the fallback keeps
        a value left over from a period that has since ended, or from a
        state saved before this field existed, from narrowing the
        choice to a player who cannot take the turn.

        **`slip_in_ids` is Slimey**, and it widens the narrow case: an
        Ooze standing on the ball may take the handler's turn from
        whoever the resolution left it with (see "Slimey (Ooze)" in
        docs/living-rules.md). They are already eligible handlers --
        an Ooze on the ball's space for the side in possession is one
        by definition -- so this does not add anybody, it declines to
        narrow past them. Which ids those are is
        `RulesEngine.slip_in_candidates`; passing them in rather than
        asking is what keeps `MatchState` from having to know what a
        species is, the same way `mark_exhausted_if_needed` takes a
        threshold rather than a player's skills.

        The carrier stays **first**, so a coach reading the prompt sees
        who actually won the ball ahead of who may take it off them.
        """
        candidates = self.eligible_ball_handlers()
        if self.ball_carrier_id in candidates:
            return [self.ball_carrier_id] + [
                player_id
                for player_id in candidates
                if player_id != self.ball_carrier_id
                and player_id in slip_in_ids
            ]
        return candidates

    def set_ball_carrier(self, player_id: Optional[str]) -> None:
        self.ball_carrier_id = player_id

    def clear_ball_carrier(self) -> None:
        """
        The ball has come free -- a loose ball, an out-of-bounds, a new
        play -- so nobody is carrying it and the side that ends up with
        it chooses who picks it up.
        """
        self.ball_carrier_id = None

    def select_ball_handler(
        self, player_id: str, slip_in_ids: Collection[str] = (),
    ) -> None:
        if player_id not in self.turn_handler_candidates(slip_in_ids):
            raise ValueError(
                "The selected player is not an eligible ball handler."
            )
        self.active_player_id = player_id
        # Consumed: the carrier has taken their turn, and what happens
        # next decides who carries it after this one.
        self.ball_carrier_id = None
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

    def may_cancel_pending_shot(self) -> bool:
        """
        Whether the "Back" button on the score attempt prompt has
        anything to undo: a shot chosen but not yet rolled, whether it
        is an ordinary turn's or a set-up's. A set-up's shot
        (`pending_shot_is_set_up`) already has a real "reconsider"
        point of its own -- `SetUpAttemptChoiceView`'s "attempt or
        decline" choice, the same one an ordinary turn's "Shoot to
        score" button is -- so Back undoes whichever of the two
        `start_set_up_shot`/`begin_shot_action` just committed to,
        rather than being withheld for one of them.
        """
        return self.pending_action == "shoot"

    def retract_pending_shot(self) -> None:
        """
        Undo an ordinary (not a set-up's) "shoot" turn choice nobody
        has rolled yet, for that Back button.

        Safe because nothing can happen between choosing to shoot and
        backing out of it: a score attempt costs no exhaustion and owes
        no injury check until it is actually rolled (see
        `ScoreAttemptView`), so the `turn_action` it logged is still
        the last thing in the event log. Popping it is exactly a coach
        who has not, after all, taken a turn -- see `record_turn_action`
        and the same reasoning for a cede backed out of its confirm.

        A set-up's shot never reaches here: it never recorded a
        `turn_action` of its own (the maneuver that earned it already
        recorded one) and there is no ordinary turn prompt to return
        to, so `ScoreAttemptView.back` handles it separately, by
        rebuilding `SetUpAttemptChoiceView` instead.
        """
        self.pending_action = None
        if self.events and self.events[-1].kind == EVENT_TURN_ACTION and (
            self.events[-1].details.get("action") == "shoot"
        ):
            self.events.pop()

    def may_cede_possession(self) -> bool:
        """
        Whether the team in possession may give the ball up to coach --
        see "Ceding the ball" in docs/living-rules.md. Two conditions
        and no others:

        - **They are out of shooting range.** A side with a shot on is
          not stuck, and the rule exists for a side that is. It is the
          same read as `can_attempt_score`, from the other end, which
          is why the turn prompt can explain both missing buttons in
          one sentence.
        - **They still have their once-a-half declaration.** Ceding is
          charged exactly like declaring at a new play, so a side that
          has already declared this half has nothing left to buy the
          window with.

        Deliberately *not* conditional on having anyone to bring on.
        The window is the whole Coaching Choice -- formation, zones,
        spaces -- and a side with both benches spent may still want it;
        that state needs every one of three substitutions to have come
        off injured, and is rare enough that hiding the button for it
        would mislead far more often than it helped.
        """
        return (
            not self.can_attempt_score()
            and self.may_declare_coaching(self.ball.possession)
        )

    def cede_possession(self) -> TeamSide:
        """
        Give the ball up to coach, and report the side that now has it.

        The ball does not move and play does not stop: possession
        crosses on the space it was ceded on, at speed 1 like any other
        turnover, and it costs its flat space minute like any other
        maneuver (2026-08-16) even though nothing travelled. The turn
        that was being taken is cleared, carrier included, because the
        side that has just been handed the ball chooses their own
        handler when the coaching is over.

        `pending_cede` is set *after* the reset, which clears it: the
        two coaching windows and the tail behind them all run off this
        flag, and reset_maneuver is the last thing to happen before
        they start.

        `pending_run_back_distance` is the turn's clock cost, which
        reset_maneuver already leaves at 1 -- restated here explicitly
        so a cede's cost reads as a deliberate 1, not a leftover
        default. It is read back by whatever the tail still owes -- an
        empty ball space sends the receiving side to pick the ball up,
        and that step spans a restart, so it reads the cost from here
        rather than from a parameter.
        """
        side = self.defending_side()
        self.reset_maneuver()
        self.clear_ball_carrier()
        self.ball.possession = side
        self.ball.speed = 1
        self.pending_run_back_distance = 1
        self.pending_cede = True
        return side

    def high_pass_overshoots(self, side: TeamSide, distance: int) -> bool:
        """
        Whether a High Pass of `distance` in `side`'s attack direction
        runs out of field -- the ball is clamped short of where it was
        aimed. Read before the ball moves, since the clamp is what
        loses the evidence.
        """
        origin_flat = self.board.flat_index(
            self.ball.zone, self.ball.space_index,
        )
        target_flat = self.relative_flat_index(origin_flat, side, distance)
        return abs(target_flat - origin_flat) < distance

    def high_pass_distances(
        self, side: TeamSide, max_distance: int,
    ) -> list[int]:
        """
        The distances a High Pass may actually be thrown at from where
        the ball is: the minimum up to `max_distance`, less any that
        run out of field. **A distance is dropped when a shorter one
        already reaches the space it would land on**, because the
        longer one is then the same pass at a disadvantage -- it
        counts as an overshoot, so it pays the ball speed modifier the
        wrong way round and owes a contest the shorter one does not.
        So a Fullback two spaces from the end is offered 2 and 3 but
        not 4, and anyone one space further out is offered 2 alone.

        Empty when even the shortest overshoots -- see
        high_pass_distance_is_moot, which is the same question asked
        without needing to know the handler's maximum.
        """
        return [
            distance
            for distance in range(MIN_HIGH_PASS_DISTANCE, max_distance + 1)
            if not self.high_pass_overshoots(side, distance)
        ]

    def high_pass_receivers_at(
        self, side: TeamSide, distance: int,
    ) -> list[str]:
        """
        Which of `side` would be standing where a High Pass of
        `distance` lands, less the passer -- who never receives their
        own pass. Read before the ball moves, so it is the lookahead
        `high_pass_receiver_candidates` is after the fact.

        It is what lets a coach -- or Dinky -- prefer a distance that
        reaches somebody over one that merely goes further.
        """
        origin_flat = self.board.flat_index(
            self.ball.zone, self.ball.space_index,
        )
        target_flat = self.relative_flat_index(origin_flat, side, distance)
        zone, space_index = self.board.position_at_flat_index(target_flat)
        occupants = set(self.board.spaces[zone][space_index])
        return [
            player_id
            for player_id in self.setup_for_side(side).field_players
            if player_id in occupants and player_id != self.active_player_id
        ]

    def high_pass_distance_is_moot(self, side: TeamSide) -> bool:
        """
        Whether there is anything to choose about a High Pass's
        distance: there is not when even the shortest one already
        overshoots, because 2, 3 and 4 then all land on the same
        space -- the one closest to the goal. That is the ball sitting
        0 or 1 spaces from the end of the field, and it makes the pass
        an overshoot before anyone has picked anything. See "High
        Pass" in the living rules.
        """
        return self.high_pass_overshoots(side, MIN_HIGH_PASS_DISTANCE)

    def ball_speed_modifier(self) -> int:
        """
        The ball speed modifier as this turn pays it: the speed halved
        and rounded down, but **negated** when a High Pass overshot the
        field -- see "Ball speed" and "High Pass" in the living rules.
        A pass that ran out of field arrives too fast to do anything
        with, so the speed that would have helped is what makes the
        shot hard, and the same sign carries into the long-pass contest
        a declined set-up falls into.

        This is the modifier a *High Pass outcome* pays: the set-up's
        shot and that contest. The one place the modifier is paid to
        somebody else -- a skill test the defense won with Steal
        Intercept -- reads the speed itself, because the overshoot is
        the offense's problem and the intercept happens before any
        High Pass has been thrown.
        """
        modifier = self.ball.speed // 2
        return -modifier if self.pending_high_pass_overshoot else modifier

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
        counting the space it starts from -- the number of spaces that
        can hold defenders in the way. A score attempt's own clock
        cost is a flat space minute regardless of this (2026-08-16);
        it no longer reads this value.

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

    def defenders_between_ball_and_goal(self) -> list[tuple[str, bool]]:
        """
        Fielded players of the defending team standing anywhere between
        the ball and the goal it is being shot at, including any that
        share the ball's own space. Ordered outwards from the ball, so
        the list reads the way the shot travels.

        Each is paired with whether they are on the ball's own space,
        because that is what decides how much of their defensive skill
        the shot is up against -- see ShotDefender. This is the only
        place that knows it: by the time a caller has the skill in hand
        the position is gone.

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
            (player_id, index == 0)
            for index, occupants in enumerate(span)
            for player_id in occupants
            if player_id in defending_players
        ]

    def contest_candidates(self, side: TeamSide) -> list[str]:
        """
        Who `side` may send to the ball's space -- the whole of "Sending
        a player" in docs/living-rules.md, and the one pool behind all
        four rules that ask for somebody: the maneuver challenge, the
        loose ball, the long High Pass contest, and the pickup after an
        out-of-bounds or ceded ball.

        **Distance decides it, not zone.** The nearest of that side's
        fielded players on each side of the space, plus every player
        tied for nearest, since two players the same distance away
        differ only in who they are and that is the coach's call. So it
        is two candidates in the ordinary case and never the whole
        field -- which is what the out-of-bounds pickup used to offer,
        and what a list of six spread over the board reduces to a
        distance sum the coach has to do themselves.

        **Anyone already standing on the space is included**, at
        distance 0. They are not *sent* anywhere -- every caller
        recognises them and short-circuits (automatic_challengers, the
        High Pass contest's forced contestant, an eligible ball
        handler) -- but they are candidates, or automatic_challengers
        would have nothing to filter.
        """
        # The setup's own order, not the board's and not a set's: the
        # buttons a coach is offered should come back the same way
        # twice, and a tie is a list this returns whole.
        side_players = self.setup_for_side(side).field_players
        ball_flat = self.board.flat_index(
            self.ball.zone, self.ball.space_index,
        )

        # Keyed by which way along the field they lie: 0 is on the ball
        # itself, -1 and +1 the two directions. Naming them "forward"
        # and "back" would be naming them from one side's point of
        # view, and both sides read this.
        nearest: dict[int, tuple[int, list[str]]] = {}
        for player_id in side_players:
            position = self.board.meeple_position(player_id)
            if position is None:
                continue
            offset = self.board.flat_index(*position) - ball_flat
            direction = (offset > 0) - (offset < 0)
            distance = abs(offset)
            best, players = nearest.get(direction, (distance, []))
            if distance < best:
                best, players = distance, []
            if distance == best:
                players.append(player_id)
            nearest[direction] = (best, players)

        return [
            player_id
            for direction in (0, -1, 1)
            for player_id in nearest.get(direction, (0, []))[1]
        ]

    def eligible_challengers(self) -> list[str]:
        """
        The defending players who may be sent in to challenge the ball
        handler -- contest_candidates read from the defense's end.
        """
        return self.contest_candidates(self.defending_side())

    def contest_occupants(self, side: TeamSide) -> list[str]:
        """
        `side`'s players already standing on the ball's own space --
        their contestant in a [loose ball](docs/living-rules.md), put up
        for nothing rather than sent. The same players
        automatic_challengers picks out for the defense, asked of either
        side.

        In the setup's own order rather than the board's: where there
        are several the coach picks between them, and the buttons they
        are offered have to come back the same way twice.
        """
        occupants = set(
            self.board.spaces[self.ball.zone][self.ball.space_index]
        )
        return [
            player_id
            for player_id in self.setup_for_side(side).field_players
            if player_id in occupants
        ]

    def loose_ball_occupants(self, side: TeamSide) -> list[str]:
        """
        `side`'s contestants already on the ball in *this* loose ball --
        contest_occupants, less the passer where it is a High Pass
        contest and `side` threw it. They never receive their own pass,
        so the contest is fought by whoever did.

        That exclusion can only bite on a pass the field clamped to 0
        spaces, which reaches finish_maneuver_resolution rather than any
        contest. It is stated as a rule about every High Pass anyway, so
        a later maneuver that moves a handler cannot reopen the hole
        quietly -- exactly as high_pass_receiver_candidates states it.

        This, and not contest_occupants, is what the pool, the decline
        and the auto-pick all read, so the three cannot disagree about
        who is standing there.
        """
        occupants = self.contest_occupants(side)
        if (
            self.pending_loose_ball_is_high_pass
            and TeamSide(side) == self.ball.possession
        ):
            return [
                player_id
                for player_id in occupants
                if player_id != self.active_player_id
            ]
        return occupants

    def may_decline_loose_ball(self, side: TeamSide) -> bool:
        """
        Whether `side` may send nobody after a loose ball. A side with
        somebody standing on the ball may not: declining is a refusal
        to pay a walk-in's exhaustion and they have no walk-in to pay
        for, exactly as with a challenge (may_decline_challenge).

        It is also what keeps out of bounds an empty space's outcome
        alone -- see "The loose ball" in docs/living-rules.md.
        """
        return not self.loose_ball_occupants(side)

    def automatic_challengers(self) -> list[str]:
        """
        Eligible challengers already standing on the ball's own space.
        Theirs is the one challenge a defense may not decline:
        declining is a refusal to pay the walk-in's exhaustion, and
        they have no walk-in to pay for -- see "Maneuvers" in
        docs/living-rules.md.
        """
        return [
            player_id
            for player_id in self.eligible_challengers()
            if self.distance_to_ball(player_id) == 0
        ]

    def challenge_candidates(self) -> list[str]:
        """
        Who the defending coach may put up against the maneuver, which
        is one of two pools and never a mixture of them.

        **A defender already on the ball challenges**, so where there
        are any, they are the whole of the choice: the defense may not
        walk somebody else in past a player who is standing on the ball
        already, and may not decline (see may_decline_challenge). With
        nobody there it is the ordinary send, from the nearest players
        either side of the space.

        The coach picks between two defenders on the ball the same way
        they pick between two players tied for nearest -- they differ
        only in who they are, and a challenge is settled on defensive
        skill (the author, 2026-08-17). One of them is not a choice at
        all, which is why the prompt is skipped there.
        """
        return self.automatic_challengers() or self.eligible_challengers()

    def may_decline_challenge(self) -> bool:
        """
        Whether the defense is being *offered* the challenge rather
        than made to take it: somebody to send, but nobody already on
        the ball. A side with nobody fielded at all has no choice to
        decline, and the maneuver is uncontested either way -- which
        since 2026-08-16 is the only way the first half of this can be
        false, distance having replaced the zone as the measure.
        """
        return bool(self.eligible_challengers()) and not (
            self.automatic_challengers()
        )

    def record_event(
        self,
        kind: str,
        side: Optional[TeamSide] = None,
        player_id: Optional[str] = None,
        **details,
    ) -> MatchEvent:
        """
        Append one thing that happened to the match's event log,
        stamped with the clock as it stands.

        **The only writer.** Everything in `d12ball/stats.py` is a
        fold over this list, so a second way in is a second thing
        that can disagree about what a match did -- the same reason
        `record_goal` below is the only writer of the goal log.

        The stamp is the clock at the moment of the event, before
        whatever it costs is charged, so the log reads as the minute
        something happened rather than the minute play restarted.
        """
        event = MatchEvent(
            kind=kind,
            period=self.scoreboard.period,
            time=self.scoreboard.time,
            side=None if side is None else TeamSide(side),
            player_id=player_id,
            details=details,
        )
        self.events.append(event)
        return event

    def events_this_turn(self) -> list[MatchEvent]:
        """
        Every event since the turn began -- the `turn_action` that
        opened it and everything logged under it.

        This is what "the current turn" means anywhere it is asked,
        and it is read off the order rather than off a counter: see
        MatchEvent. Empty before the first turn action of a game,
        which is what a charge made during setup or halftime answers
        to.
        """
        for index in range(len(self.events) - 1, -1, -1):
            if self.events[index].kind == EVENT_TURN_ACTION:
                return self.events[index:]
        return []

    def current_turn_event(self) -> Optional[MatchEvent]:
        """
        The `turn_action` the match is inside, or None when it is
        between turns -- setup, halftime, or a game that has not
        kicked off. What `add_exhaustion` charges its tokens to.
        """
        turn = self.events_this_turn()
        return turn[0] if turn else None

    def record_goal(
        self,
        side: TeamSide,
        player_id: str,
        own_goal: bool = False,
        shootout: bool = False,
    ) -> GoalRecord:
        """
        Add a goal to the log, stamped with the clock as it stands.

        **Nothing calls this on its own.** The three ways to score all
        go through the award methods below, and each of them logs --
        which is what stops a scoreboard and a goal log that disagree.
        A new way to score has to say who scored it, the same way it
        has to say whose ball it is afterwards.

        The stamp is the clock at the moment the ball crosses the line,
        before the action's own cost is charged: the log reads as the
        minute a goal went in, not the minute play restarted.
        """
        record = GoalRecord(
            side=TeamSide(side),
            player_id=player_id,
            time=self.scoreboard.time,
            period=self.scoreboard.period,
            own_goal=own_goal,
            shootout=shootout,
        )
        self.goals.append(record)
        # Logged twice on purpose, and the two are not redundant. The
        # goal log answers "what was the score and when"; the event
        # carries the goal's *position in the run of play*, which is
        # what attributes it to the turn -- and so to the maneuver --
        # that produced it. A GoalRecord has no way to say that, and
        # giving it one would be a second ordering to keep in step
        # with the log's own.
        self.record_event(
            EVENT_GOAL,
            side=record.side,
            player_id=player_id,
            own_goal=own_goal,
            shootout=shootout,
        )
        return record

    def goals_for(self, side: TeamSide) -> list[GoalRecord]:
        """
        Every goal on a side's half of the scoresheet, in the order
        they were scored -- an own goal among them, since it counts for
        the side it is listed under and not the one that kicked it.
        """
        side = TeamSide(side)
        return [goal for goal in self.goals if goal.side == side]

    def award_goal(self, scorer_id: str) -> None:
        """
        Credit a goal to the team in possession. Scores have no upper
        bound, so unlike the clock this needs no clamp and cannot put
        the scoreboard into a state that fails to reload.
        """
        if self.ball.possession == TeamSide.HOME:
            self.scoreboard.home_score += 1
        else:
            self.scoreboard.visiting_score += 1
        self.record_goal(self.ball.possession, scorer_id)

    def concede_own_goal(self, player_id: str) -> None:
        """
        Credit a goal to the team WITHOUT possession -- an own goal by
        the team currently holding the ball.

        `player_id` is the defender who failed the roll, and they are
        logged in the *other* team's column marked (OG): the goal is
        that side's, the kick was this one's, and a scoresheet that
        named neither would be the one goal nobody can account for.
        """
        conceded_to = (
            TeamSide.VISITING
            if self.ball.possession == TeamSide.HOME
            else TeamSide.HOME
        )
        if conceded_to == TeamSide.VISITING:
            self.scoreboard.visiting_score += 1
        else:
            self.scoreboard.home_score += 1
        self.record_goal(conceded_to, player_id, own_goal=True)

    def restart_after_goal(self, conceding_side: TeamSide) -> None:
        """
        Restart from midfield with the conceding side in possession.
        This is shared by ordinary goals and own goals.

        `pending_kickoff_fill` is the flag the caller resolves before
        the ball is treated as live (see D12Ball.continue_run_back). It
        says "this restart still owes a kickoff-space check", not
        "nobody is standing there": everyone moves between here and the
        check -- a new play resets both sides to their coaches'
        arrangement, and a substitution window can place meeples freely
        -- so an answer taken now would be stale by the time it is
        acted on.

        **The check now nearly always passes for nothing.** Every
        arrangement covers its own side's kickoff space, so the reset
        this restart runs through puts a conceding player there by
        construction. What is left is the fallback: an arrangement
        saved before that rule landed, which both developers have in
        their own game files.
        """
        conceding_side = TeamSide(conceding_side)
        self.set_ball_space(
            Zone.MIDFIELD, self.kickoff_space_for(conceding_side),
        )
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
        Advance the clock by `minutes` space minutes. It has no ceiling:
        every turn of a last possession is charged like any other, so a
        period ends on the minute its last turnover falls on rather than
        on its last minute.

        Returns True only the moment this call first reaches the
        period's last minute (entering last possession), so callers can
        react to it once.

        **"The clock has reached the last minute" and "last possession
        is live" are two facts, not one.** They were one while the clock
        stopped: reaching 15 both set the flag and froze the number, so
        a last possession lasting four turns read 15 for all of them.
        The flag alone ends the period now -- on the first turnover
        under it -- and the clock is nobody's signal for it.
        """
        if minutes <= 0:
            return False
        self.scoreboard.time += minutes
        if self.scoreboard.last_possession:
            return False
        if self.scoreboard.time >= self.scoreboard.last_minute:
            self.scoreboard.last_possession = True
            return True
        return False

    def add_exhaustion(self, player_id: str, amount: int) -> None:
        """
        Charge exhaustion tokens, and attribute them to the turn that
        charged them.

        **Every path that charges bottoms out here** -- the cog's
        `apply_exhaustion`, the run back's own charge, and the AI's --
        which is why the attribution is here and not at those three.

        It is written onto the open turn's own event rather than
        logged as an event apiece: a game makes something like a
        hundred of these calls, and what any statistic asks is "what
        did this maneuver cost", never "in what order were the tokens
        handed out". A charge made between turns -- a halftime
        recovery, a setup placement -- belongs to no turn and is
        simply not attributed.
        """
        if amount <= 0 or player_id in self.injured:
            return
        self.exhaustion[player_id] = (
            self.exhaustion.get(player_id, 0) + amount
        )
        turn = self.current_turn_event()
        if turn is not None:
            charged = turn.details.setdefault("exhaustion", {})
            charged[player_id] = charged.get(player_id, 0) + amount

    def apply_mind_pull(self, player_id: str) -> None:
        """
        A pull that landed: the ball stops on the Telekinetic's space,
        their side takes possession, and they hold it.

        **It is a steal**, so the caller runs the ordinary turnover --
        ball speed back to 1, everyone displaced runs back, and this
        player is the carrier who does not (`begin_run_back` reads the
        exemption off `ball_carrier_id`, which is why setting it here
        is the whole of arranging that).

        The path is cleared with it: the movement that offered this
        pull is over, and leaving it set would offer the same pull
        again at the next arrival point.
        """
        zone, space_index = self.board.meeple_position(player_id)
        self.ball.zone = zone
        self.ball.space_index = space_index
        self.ball.possession = self.side_for_player(player_id)
        self.set_ball_carrier(player_id)
        self.last_ball_path = []
        self.pending_mind_pull = []

    def declare_overdrive(self, player_id: str, threshold: int) -> None:
        """
        Take Overdrive's 3 drain tokens and record the declaration, so
        the next roll this player makes adds its +5.

        Refuses a second declaration for the same roll -- "once per
        roll" -- rather than charging twice for a bonus that does not
        stack. It goes through `add_exhaustion` like every other
        charge, so the tokens are attributed to the open turn, and it
        re-tests Drained afterwards because 3 at once is enough to
        cross the line on its own. **A Drained Cyborg may still
        Overdrive**, which is why nothing here refuses on the flag: the
        drain stacks, and the cost of being past 7 is the injury check,
        not a ban on spending.
        """
        if player_id in self.pending_overdrive:
            raise ValueError("Overdrive has already been declared.")
        if player_id in self.injured:
            # An injured player carries no tokens and cannot gain any,
            # so there is nothing to spend. Overdrive itself is not
            # withheld by injury -- it is a flat bonus, not the skill
            # modifier -- but the price cannot be paid.
            raise ValueError("An injured player cannot Overdrive.")
        self.add_exhaustion(player_id, OVERDRIVE_DRAIN_COST)
        self.mark_exhausted_if_needed(player_id, threshold)
        self.pending_overdrive.append(player_id)

    def overdrive_modifier(self, player_id: str) -> int:
        """What a declared Overdrive adds to this player's roll."""
        return (
            OVERDRIVE_BONUS if player_id in self.pending_overdrive else 0
        )

    def consume_overdrive(self) -> None:
        """
        Spend every declaration -- called by the roll that read them.

        Every roll site clears this, win or lose, so a declaration
        cannot leak onto the next roll: a tie that is re-rolled is a
        fresh roll and has to be Overdriven again.
        """
        self.pending_overdrive = []

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
        """
        Take a player out of the game.

        Nothing is logged here: the roll that decides an injury is
        one step up, in `run_injury_test`, which is the only caller
        and the only place that knows a *passed* test happened at all.
        Logging both would put a failed test in the record twice.
        """
        self.injured.add(player_id)
        self.exhaustion.pop(player_id, None)
        self.exhausted.discard(player_id)

    def recover_exhaustion(
        self,
        player_id: str,
        amount: int,
        threshold: int,
    ) -> int:
        """
        Remove up to `amount` exhaustion tokens (floored at 0),
        re-testing Exhausted against `threshold` rather than assuming
        it clears -- mirrors add_exhaustion/mark_exhausted_if_needed's
        split, since taking tokens off can drop a player back under
        the threshold that put them there. A no-op for an injured
        player, who never carries exhaustion. Returns the number of
        tokens actually removed.

        `threshold` is what the count has to stay **at or below** to
        clear the flag -- a player's defensive skill, or a Cyborg's
        flat Drained line. It is `RulesEngine.exhaustion_threshold`'s
        answer, and is a plain number here for the reason
        `mark_exhausted_if_needed` takes one: `MatchState` does not
        know a player's skills, let alone which modules the game is
        playing.

        Two callers: halftime recovery, and Lithium Powered's
        Charge-up.
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
        if remaining <= threshold:
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
        if player_id not in self.challenge_candidates():
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
        The no-challenger branch of "determine the two players": there
        is no second player, so the maneuver the offense picks succeeds
        -- see "Maneuvers" in docs/living-rules.md.

        Two ways in, and the state they leave is the same one: the
        defending team has nobody fielded to send, or it has somebody
        and has sent nobody rather than pay the walk-in's exhaustion.
        The second is now all but the only one -- distance replaced the
        zone as the measure on 2026-08-16, so any side with a meeple on
        the board has a candidate. Only a defender already on the ball
        is refused here, since that challenge costs nothing and so
        cannot be declined.

        Clears `pending_action` for the same reason choose_challenger
        does: the action is settled and what happens next is the
        maneuver selection, not another prompt for this one.
        """
        if self.automatic_challengers():
            raise ValueError(
                "A defender on the ball's space has to challenge."
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

    def spaces_to_attacking_end(
        self, player_id: str, side: TeamSide,
    ) -> int:
        """
        How far `player_id` is from the last space of the goal zone
        `side` attacks -- what a Dribble Burst runs, and what it is
        charged a token a space for.

        Measured off the board rather than off the zone, because "the
        last space of the goal they attack" is the far end of the
        field: `relative_flat_index` clamps there, so asking for the
        whole board is asking for exactly that space.
        """
        origin_flat = self.board.flat_index(
            *self.board.meeple_position(player_id)
        )
        target_flat = self.relative_flat_index(
            origin_flat, side, self.board.layout.board_size,
        )
        return abs(target_flat - origin_flat)

    def opposing_maneuver(self, key: str) -> Optional[str]:
        """
        The card played against `key` this maneuver, or None when `key`
        is neither side's pick -- which is how an uncontested maneuver
        answers, since there is no defense card at all.
        """
        if key == self.offense_maneuver:
            return self.defense_maneuver
        if key == self.defense_maneuver:
            return self.offense_maneuver
        return None

    def choose_offense_maneuver(self, key: str) -> None:
        """
        Record the offense's pick, by **maneuver key** -- see
        `maneuver_key`. The printed name is never stored: a rename
        upstream would then be a change to every saved game.
        """
        if self.offense_maneuver is not None:
            raise ValueError("The offense has already chosen a maneuver.")
        self.offense_maneuver = key

    def choose_defense_maneuver(self, key: str) -> None:
        """The defense's pick, by maneuver key -- see above."""
        if self.defense_maneuver is not None:
            raise ValueError("The defense has already chosen a maneuver.")
        self.defense_maneuver = key

    def begin_loose_ball(
        self, distance_moved: int, is_high_pass: bool = False,
    ) -> None:
        self.pending_loose_ball = True
        self.pending_loose_ball_distance = distance_moved
        self.pending_loose_ball_is_high_pass = is_high_pass
        # Read now, while the space still holds what the ball landed
        # on. Every contestant this arrival puts up is walked onto it
        # before the result is worded, so this is the last moment the
        # answer exists.
        self.pending_loose_ball_on_empty_space = not self.board.spaces[
            self.ball.zone
        ][self.ball.space_index]

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

        The pool is `contest_candidates` -- the nearest player either
        side of the ball, from any zone -- and not the whole field, as
        it was until 2026-08-16. It is the same pickup a ceded ball
        asks for, and both happen after the reset that puts everyone
        back on their arrangement, so the player placed here is the one
        who stays on the ball rather than being run back off it.
        """
        if player_id not in self.contest_candidates(self.ball.possession):
            raise ValueError(
                f"{player_id} cannot recover the ball -- not one of the "
                "nearest players for the side now in possession."
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

        `ball_carrier_id` is deliberately not cleared here. The effect
        that just resolved is what sets it, and this runs after that
        effect and before the next turn's prompt, so clearing it would
        wipe the carrier between the two -- and `/d12ball
        offensive_choice`, which calls this to start a turn fresh,
        would become a way to hand the ball to somebody else. It is
        consumed by select_ball_handler and cleared by
        clear_ball_carrier when the ball comes free.
        """
        self.active_player_id = None
        self.pending_action = None
        self.challenger_id = None
        self.maneuver_uncontested = False
        self.offense_maneuver = None
        self.defense_maneuver = None
        self.volatile_tier_upgrade = False
        self.pending_overdrive = []
        self.last_ball_path = []
        self.pending_mind_pull = []
        self.pending_mind_pull_resume = None
        self.pending_run_back = False
        self.pending_run_back_distance = 1
        self.pending_run_back_turnover = True
        self.pending_run_back_stays_player_id = None
        self.pending_run_back_speed_choice = False
        self.pending_effect_continuation = None
        self.pending_kickoff_fill = False
        self.pending_shot_is_set_up = False
        self.pending_shot_setup_cost = 0
        self.pending_high_pass_overshoot = False
        self.pending_own_goal = False
        self.pending_own_goal_distance = 1
        self.pending_injury_tests = []
        self.pending_injury_resume = None
        self.pending_loose_ball = False
        self.pending_loose_ball_distance = 1
        self.pending_loose_ball_is_high_pass = False
        self.pending_loose_ball_on_empty_space = True
        self.loose_ball_offense_player = None
        self.loose_ball_defense_player = None
        self.loose_ball_offense_declined = False
        self.loose_ball_defense_declined = False
        self.pending_ball_recovery = False
        self.pending_cede = False

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
            + setup.team_board.bench
            + setup.team_board.back_bench
        )
        if player_id not in roster_ids:
            raise ValueError(f"{player_id} is not assigned to this team.")

        for zone_players in setup.zones.values():
            if player_id in zone_players:
                zone_players.remove(player_id)
        if player_id in setup.team_board.bench:
            setup.team_board.bench.remove(player_id)
        if player_id in setup.team_board.back_bench:
            setup.team_board.back_bench.remove(player_id)
        self.board.remove_meeple(player_id, required=False)

        if destination in ("bench", "back_bench"):
            getattr(setup.team_board, destination).append(player_id)
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

        **It records the path it travelled**, in `last_ball_path`, so
        Mind Pull can be offered to every Telekinetic the ball crossed
        -- see "Mind Pull (Telekinetic)" in docs/living-rules.md. This
        is the one funnel every maneuver's ball movement comes through
        (`move_ball_relative` included), which is what makes the path
        recordable in one place rather than at eleven effect sites.

        Recording is unconditional and reading is not: a kickoff and a
        period restart come through here too and are not a ball moving
        through play, so the three arrival points that *consult* the
        path are what decide when a pull may be offered, and each
        clears it as it goes.
        """
        zone = Zone(zone)
        if space_index not in range(len(self.board.spaces[zone])):
            raise ValueError("The target board space does not exist.")
        self.last_ball_path = self.ball_path_to(zone, space_index)
        self.ball.zone = zone
        self.ball.space_index = space_index

    def ball_path_to(
        self, zone: Zone, space_index: int,
    ) -> list[list]:
        """
        The spaces a move from the ball's current position to
        `(zone, space_index)` crosses -- **excluding where it starts
        and including where it lands**.

        That is exactly what "to or through" means: "it passes over the
        space on its way somewhere, or comes to rest on it", and "the
        ball's own starting space does not count as moved to". A move
        that goes nowhere is an empty path, so a clamped pass offers
        nobody a pull.

        Each entry is `[zone value, space index]` rather than a tuple,
        because this is persisted with the rest of the match and JSON
        has no tuples.
        """
        origin = self.board.flat_index(self.ball.zone, self.ball.space_index)
        target = self.board.flat_index(Zone(zone), space_index)
        if target == origin:
            return []
        step = 1 if target > origin else -1
        path = []
        for flat in range(origin + step, target + step, step):
            crossed_zone, crossed_index = self.board.position_at_flat_index(
                flat,
            )
            path.append([crossed_zone.value, crossed_index])
        return path

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

    def relative_move_destination(
        self,
        player_id: str,
        side: TeamSide,
        spaces: int,
    ) -> Optional[tuple[Zone, int]]:
        """
        Where `player_id` would end up moving `spaces` in `side`'s
        attacking direction -- the space `move_player_relative` would
        put them on, asked before the move rather than read off it
        afterwards, and clamped to the field the same way.

        A coach choosing a distance is choosing a space, and "1 or 2"
        says nothing about which; the Playmaker's Dribble Advance menu
        labels its buttons from this. None when the player has no
        meeple on the field, which the move raises on.
        """
        position = self.board.meeple_position(player_id)
        if position is None:
            return None
        return self.board.position_at_flat_index(
            self.relative_flat_index(
                self.board.flat_index(*position), side, spaces,
            )
        )

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

    def crowded_candidates(self, side: TeamSide) -> list[str]:
        """
        Who could be the next of `side` to run back out of a stack --
        every one of their zone-native fielded players sharing a space
        with a teammate assigned to the same zone, in a zone that still
        has a space nobody of theirs is standing on. Run-back has to
        spread these out as well as the players displaced_players()
        finds outside their zone, so a zone's spaces stay covered as
        fully as possible.

        **It offers the whole stack rather than picking out of it**,
        because which of two teammates on one space runs back is the
        coach's call (the author, 2026-08-17; see "Running back after a
        steal" in docs/living-rules.md). It used to keep whoever the
        space's occupant list happened to start with -- placement
        order, so effectively arbitrary -- and hand the rest to the run
        back with nobody asked. The one player never offered is the
        ball's holder (`pending_run_back_stays_player_id`), who does not
        run back at all: a pair holding the ball between them is
        therefore one candidate and no choice, which is the same answer
        the old reading gave.

        Only one of them moves per pass and the caller asks again, so
        a zone with two uncovered spaces breaks its stack up twice and
        the coach chooses both times. A zone with none is left alone,
        which is what the coverage rule asks for: a stack only has to
        break up while some space in the zone still has nobody on it,
        so a formation that puts more players in a zone than it has
        spaces (2-3-1 or 1-3-2 on a six-space board) settles with the
        surplus doubled up and nobody moving.
        """
        stays_player_id = self.pending_run_back_stays_player_id
        setup = self.setup_for_side(side)
        team_players = set(setup.field_players)
        candidates: list[str] = []
        for zone in Zone:
            if not self.open_spaces_in_zone(side, zone):
                continue
            for occupants in self.board.spaces[zone]:
                zone_native = [
                    player_id
                    for player_id in occupants
                    if player_id in team_players
                    and setup.assigned_zone(player_id) == zone
                ]
                if len(zone_native) < 2:
                    continue
                candidates.extend(
                    player_id
                    for player_id in zone_native
                    if player_id != stays_player_id
                )
        return candidates

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
        "Turnovers, resets, and running back" in docs/living-rules.md)
        and the
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

    def run_back_distance(
        self,
        player_id: str,
        zone: Zone,
        space_index: int,
    ) -> int:
        """
        How far `player_id` would travel to reach that space, and so
        what running back there costs them in exhaustion tokens.

        Asked before the move as well as measured by it: the run-back
        prompt labels each destination with its cost, so a coach
        choosing between two spaces is choosing between two prices.
        `run_back_player` charges what this reports, which is why it is
        one reading and not two.

        A player with no meeple on the board (nothing places one until
        setup) is nowhere, and travels nothing.
        """
        origin = self.board.meeple_position(player_id)
        if origin is None:
            return 0
        return abs(
            self.board.flat_index(Zone(zone), space_index)
            - self.board.flat_index(*origin)
        )

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

        distance = self.run_back_distance(player_id, zone, space_index)
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
        formation: Optional[str] = None,
    ) -> None:
        """
        Offer the window to `side`, who has not taken it up yet. Kept
        distinct from `declare_coaching` so that a bot restart
        mid-offer knows whether it is still asking or already coaching.

        `occasion` carries every difference between the five: the
        substitution allowance, whether a declaration is asked for and
        whether it is charged, and where a player taken off goes. Only
        a new play asks -- setup, halftime, full time and a ceded ball
        all open declared.

        `formation` is the shape the side is in as the window opens,
        kept so that closing it can say whether they changed it. It is
        given rather than derived because which shape a set of zone
        counts is belongs to the ruleset, which the match does not
        hold -- see D12Ball.current_formation.
        """
        occasion = CoachingOccasion(occasion)
        self.pending_coaching_side = TeamSide(side).value
        self.pending_coaching_occasion = occasion.value
        self.pending_coaching_substitutions = 0
        self.pending_coaching_is_response = is_response
        self.pending_coaching_declared = False
        self.pending_coaching_formation = formation
        self.pending_coaching_swaps = []
        # An occasion that does not ask opens declared. For setup,
        # halftime and full time that costs nothing; for a ceded ball
        # it charges the declaration the ball was given up for, which
        # is why this reads `asks_declaration` and not
        # `spends_declaration` -- the two part company exactly here.
        if not occasion.asks_declaration:
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
        self.pending_coaching_formation = None
        self.pending_coaching_swaps = []

    def substitutions_remaining(self) -> Optional[int]:
        """
        How many more substitutions the side holding the window may
        make, or **None for no limit** -- which setup is, and which
        callers have to handle rather than treating as zero.

        A new play's come out of the side's two for the half, spent
        across every window they get in it; halftime's two and full
        time's one are their own and are counted within the window.
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

    def record_substitution(
        self,
        outgoing_player_id: Optional[str] = None,
        incoming_player_id: Optional[str] = None,
    ) -> None:
        """
        Charge the open window one substitution, to whichever counter
        the occasion draws on, and remember the pair for the summary
        the window closes with -- see pending_coaching_swaps.
        """
        occasion = self.coaching_occasion
        if self.pending_coaching_side is None or occasion is None:
            raise ValueError("No coaching window is open.")
        self.pending_coaching_substitutions += 1
        if outgoing_player_id is not None and incoming_player_id is not None:
            self.pending_coaching_swaps.append(
                [outgoing_player_id, incoming_player_id]
            )
        if occasion.counts_against_the_half:
            side_value = self.pending_coaching_side
            self.half_substitutions_used[side_value] = (
                self.half_substitutions_used.get(side_value, 0) + 1
            )

    def substitution_pool(self, side: TeamSide) -> list[str]:
        """
        Who `side` may bring on -- see "Who may come on" in
        docs/living-rules.md.

        The bench is the only pool while anyone is still sitting on it;
        once it has drained, the back bench opens. Injured players are
        dropped from whichever pool is in play: leaving the field
        injured is one way, and that is about the player rather than
        about which bench they are sitting on.

        **It does not depend on who is going off.** It used to: the
        back bench opened only to replace an injured player, which is
        not the rule. Callers that pass an outgoing player are asking
        the wrong question -- the answer is the same for all six.
        """
        setup = self.setup_for_side(side)
        pool = setup.team_board.bench or setup.team_board.back_bench
        return [
            player_id
            for player_id in pool
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

        if incoming_player_id not in self.substitution_pool(side):
            if incoming_player_id in self.injured:
                raise ValueError(
                    "An injured player can never be subbed back in."
                )
            if setup.team_board.bench:
                raise ValueError(
                    "The incoming player card is not on the bench, which "
                    "is the only pool until it has drained."
                )
            raise ValueError(
                "The incoming player card is not on the back bench."
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

        if incoming_player_id in setup.team_board.bench:
            setup.team_board.bench.remove(incoming_player_id)
        else:
            setup.team_board.back_bench.remove(incoming_player_id)
            tokens = self.exhaustion.get(incoming_player_id, 0)
            if tokens:
                self.exhaustion[incoming_player_id] = tokens // 2
            self.exhausted.discard(incoming_player_id)
        if retire_outgoing:
            setup.team_board.back_bench.append(fielded_player_id)
        else:
            setup.team_board.bench.append(fielded_player_id)

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
        Move the run-back exemption, and the carry it comes from, to
        whoever took that player's place. Both belong to the position
        rather than to the player: they exist because that meeple is
        standing on the ball, so leaving them behind would run the new
        ball carrier away from the ball and charge them for it.

        The two move together because they are one fact -- see
        begin_run_back, which reads the exemption off the carry.
        """
        if self.pending_run_back_stays_player_id == leaving_player_id:
            self.pending_run_back_stays_player_id = arriving_player_id
        if self.ball_carrier_id == leaving_player_id:
            self.ball_carrier_id = arriving_player_id

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

    def kickoff_space_for(self, side: TeamSide) -> int:
        """
        The midfield space `side` would kick off from, whether or not
        anything is being kicked off right now. Boards 7 and 9 give
        both sides the same space; board 6's midfield has no middle, so
        each side has its own -- see "Field, direction, and shooting
        range" in docs/living-rules.md.

        Read off the rule rather than off the ball, because every
        arrangement has to cover this space and arrangements are set in
        windows where the ball is somewhere else entirely.
        """
        return kickoff_space_index(
            len(self.board.spaces[Zone.MIDFIELD]), TeamSide(side),
        )

    def kickoff_space_occupied_by(self, side: TeamSide) -> bool:
        """
        Whether one of `side`'s fielded meeples stands on that side's
        own kickoff space -- the coverage every arrangement owes (see
        "Coaching Choice" in docs/living-rules.md).
        """
        side = TeamSide(side)
        occupants = self.board.spaces[Zone.MIDFIELD][
            self.kickoff_space_for(side)
        ]
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

        # The exemption and the carry follow the space, not the player
        # -- see inherit_run_back_exemption for why they move together.
        stays_player_id = self.pending_run_back_stays_player_id
        if stays_player_id == player_id:
            self.pending_run_back_stays_player_id = other_player_id
        elif stays_player_id == other_player_id:
            self.pending_run_back_stays_player_id = player_id

        carrier_id = self.ball_carrier_id
        if carrier_id == player_id:
            self.ball_carrier_id = other_player_id
        elif carrier_id == other_player_id:
            self.ball_carrier_id = player_id

    # -- The extreme shootout -------------------------------------

    def begin_shootout(self) -> None:
        """
        Open the shootout that settles a game level at full time.

        **The six who shoot are the six on the field**, in the state
        the second period left them: exhaustion counts, injuries and
        all. The whistle's own Coaching Choice has already closed by
        the time this runs, and it is the last substitution either
        side gets -- so there is no squad to record here. Every method
        below reads `setup_for_side(...).field_players`, which is the
        same six until the game ends.
        """
        self.pending_shootout = True
        self.shootout_round = 1
        self.shootout_orders = {}
        self.shootout_used = {}
        self.shootout_shooters = {}
        self.shootout_goals = {}

    def shootout_squad(self, side: TeamSide) -> list[str]:
        return list(self.setup_for_side(side).field_players)

    def set_shootout_order(
        self,
        side: TeamSide,
        player_ids: list[str],
    ) -> None:
        """Record a whole order at once -- how the AI sets its own."""
        squad = self.shootout_squad(side)
        if sorted(player_ids) != sorted(squad):
            raise ValueError(
                "A shootout order has to be all six field players."
            )
        self.shootout_orders[TeamSide(side).value] = list(player_ids)

    def add_to_shootout_order(self, side: TeamSide, player_id: str) -> None:
        """
        Put one more player at the back of a coach's order.

        **A part-built order lives here, not on the view building it**
        -- unlike a part-made coaching pick, which restarts at the hub.
        The menu is ephemeral, so a restart cannot re-attach to it (see
        restore_shootout_menus), and a coach who had ordered five would
        otherwise come back to an empty list with no way to tell that
        from having ordered none.
        """
        if player_id not in self.shootout_order_remaining(side):
            raise ValueError(
                "That player is not still to be put in the order."
            )
        self.shootout_orders.setdefault(
            TeamSide(side).value, []
        ).append(player_id)

    def clear_shootout_order(self, side: TeamSide) -> None:
        self.shootout_orders.pop(TeamSide(side).value, None)

    def shootout_order(self, side: TeamSide) -> list[str]:
        return list(self.shootout_orders.get(TeamSide(side).value, []))

    def shootout_order_remaining(self, side: TeamSide) -> list[str]:
        ordered = set(self.shootout_order(side))
        return [
            player_id
            for player_id in self.shootout_squad(side)
            if player_id not in ordered
        ]

    def shootout_order_complete(self, side: TeamSide) -> bool:
        return not self.shootout_order_remaining(side)

    @property
    def shootout_orders_complete(self) -> bool:
        return all(
            self.shootout_order_complete(side)
            for side in (TeamSide.HOME, TeamSide.VISITING)
        )

    def shootout_tests_taken(self, side: TeamSide) -> int:
        return len(self.shootout_used.get(TeamSide(side).value, []))

    def shootout_eligible(self, side: TeamSide) -> list[str]:
        """
        Who this side may still send out this round -- the field
        players who have not gone yet. In the first round the order
        already answers that; this is what a sudden-death round
        chooses from, and it resets every time a round does.
        """
        gone = set(self.shootout_used.get(TeamSide(side).value, []))
        return [
            player_id
            for player_id in self.shootout_squad(side)
            if player_id not in gone
        ]

    def set_shootout_shooter(self, side: TeamSide, player_id: str) -> None:
        if player_id not in self.shootout_eligible(side):
            raise ValueError(
                "That player has already shot in this round."
            )
        self.shootout_shooters[TeamSide(side).value] = player_id

    def shootout_shooter(self, side: TeamSide) -> Optional[str]:
        """
        Who this side has out for the test about to be rolled.

        **Round 1 never chooses one.** The order already says who is
        next, so it is read off the order rather than written down --
        which is what makes the first round's reveal a step with no
        state of its own to lose. Sudden death has no order to read,
        so there it is exactly what the coach picked.
        """
        chosen = self.shootout_shooters.get(TeamSide(side).value)
        if chosen is not None:
            return chosen

        if self.shootout_round != 1:
            return None
        order = self.shootout_order(side)
        index = self.shootout_tests_taken(side)
        if index >= len(order):
            return None
        return order[index]

    @property
    def shootout_shooters_complete(self) -> bool:
        return all(
            self.shootout_shooter(side) is not None
            for side in (TeamSide.HOME, TeamSide.VISITING)
        )

    def shootout_goals_for(self, side: TeamSide) -> int:
        return self.shootout_goals.get(TeamSide(side).value, 0)

    def award_shootout_goal(self, side: TeamSide, shooter_id: str) -> None:
        """
        A shootout goal is a goal: it goes on the scoreboard like any
        other (the author, 2026-08-10), so a 2:2 game settled 4-3 is
        announced as 6:5. The separate tally is what the "cannot be
        caught" stop counts and what the summary reads to say how the
        game was won.

        It goes in the goal log too, and for the same reason it gets a
        tally of its own it is flagged there: the log is listed by the
        minute a goal was scored, and a shootout has no minute.
        """
        side = TeamSide(side)
        self.shootout_goals[side.value] = self.shootout_goals_for(side) + 1
        if side == TeamSide.HOME:
            self.scoreboard.home_score += 1
        else:
            self.scoreboard.visiting_score += 1
        self.record_goal(side, shooter_id, shootout=True)

    def finish_shootout_test(self) -> None:
        """
        Retire both revealed shooters and start the next round when
        everybody has been out. A round is over when all six have
        gone, whichever round it is -- the first one ends after its
        six, and a sudden-death round resets eligibility rather than
        ending the shootout.

        **The roll calls it, in the same save as the goal it scored**,
        so a restart between the roll and what follows it comes back
        to the next test rather than re-rolling one already paid for.
        Nothing else may call it: the first round derives its shooter
        from the order rather than recording one, so a second call
        would quietly retire the next pair as well. In particular the
        injury queue's continuation (`continue_shootout`) does not --
        the retirement has already happened by the time it runs, which
        is what lets it count the tests still to come by asking who is
        left.
        """
        shooters = {
            side: self.shootout_shooter(side)
            for side in (TeamSide.HOME, TeamSide.VISITING)
        }
        for side, shooter_id in shooters.items():
            self.shootout_shooters.pop(TeamSide(side).value, None)
            if shooter_id is not None:
                self.shootout_used.setdefault(
                    TeamSide(side).value, []
                ).append(shooter_id)

        if all(
            not self.shootout_eligible(side)
            for side in (TeamSide.HOME, TeamSide.VISITING)
        ):
            self.shootout_round += 1
            self.shootout_used = {}

    def shootout_winner(self) -> Optional[TeamSide]:
        """
        Who has won the shootout, or None while it is still open.

        The two rounds are decided differently and both are here
        because "is it over?" is one question. In the **first** round a
        lead bigger than the tests still to come settles it -- there is
        no point rolling a sixth at 4-1 -- and so does any lead once
        all six have gone. **Sudden death** starts level by
        construction, so any lead at all is the test that just won it.
        """
        home = self.shootout_goals_for(TeamSide.HOME)
        visiting = self.shootout_goals_for(TeamSide.VISITING)
        lead = abs(home - visiting)
        if not lead:
            return None

        leader = TeamSide.HOME if home > visiting else TeamSide.VISITING
        if self.shootout_round > 1:
            return leader

        remaining = len(self.shootout_eligible(TeamSide.HOME))
        if lead > remaining:
            return leader
        return None

    def shootout_score_line(self) -> str:
        """
        How the shootout went, for the full-time summary. Empty until
        one has been played, and it reports the score at the whistle
        as well, since the scoreboard no longer shows it.
        """
        if not self.shootout_goals:
            return ""

        home = self.shootout_goals_for(TeamSide.HOME)
        visiting = self.shootout_goals_for(TeamSide.VISITING)
        return (
            f"({self.scoreboard.home_score - home}:"
            f"{self.scoreboard.visiting_score - visiting} at full time, "
            f"settled {home}-{visiting} on the extreme shootout)"
        )

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
            self.home.team_board.bench
            + self.home.team_board.back_bench
            + self.visiting.team_board.bench
            + self.visiting.team_board.back_bench
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
        """
        The match as it goes into `data/d12ball_games.json`.

        The structured half is spelled out here because each part says
        something a table cannot -- the board flattens its zones, the
        two setups and the goal log have `to_dict`s of their own. Every
        other field is `MATCH_SAVED_FIELDS`, which is also what
        `from_dict` reads, so neither direction can gain a field the
        other does not know about.
        """
        saved = {
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
            "offense_maneuver": self.offense_maneuver,
            "defense_maneuver": self.defense_maneuver,
            "exhaustion": dict(self.exhaustion),
            "exhausted": sorted(self.exhausted),
            "injured": sorted(self.injured),
            "pending_coaching_side": self.pending_coaching_side,
            "pending_coaching_occasion": self.pending_coaching_occasion,
            "pending_coaching_substitutions": (
                self.pending_coaching_substitutions
            ),
            "pending_coaching_is_response": (
                self.pending_coaching_is_response
            ),
            "pending_coaching_declared": self.pending_coaching_declared,
            "goals": [goal.to_dict() for goal in self.goals],
        }
        for saved_field in MATCH_SAVED_FIELDS:
            saved[saved_field.name] = saved_field.stored(
                getattr(self, saved_field.name),
            )
        return saved

    @classmethod
    def from_dict(
        cls,
        data: dict,
        ruleset: BasicRuleset,
    ) -> "MatchState":
        """
        A match read back out of a save, tolerantly.

        **A save older than a field is not an error**, it is the
        ordinary case: both developers run the bot from their own tree
        against their own games, so a half-finished match routinely
        outlives the change that added a field to it. Every fallback
        lives in `MATCH_SAVED_FIELDS` beside the field it belongs to.

        What stays spelled out here is what a table cannot say: the
        board and the two setups rebuild objects, the maneuver keys go
        through `legacy_maneuver_key`, exhaustion and exhausted are
        both filtered against injured, and the five coaching fields
        each carry a `pending_substitution_*` fallback from before the
        three occasions became one Coaching Choice.
        """
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
            offense_maneuver=legacy_maneuver_key(
                data.get("offense_maneuver")
            ),
            defense_maneuver=legacy_maneuver_key(
                data.get("defense_maneuver")
            ),
            exhaustion=exhaustion,
            exhausted=exhausted,
            injured=injured,
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
            # A game saved before the log existed comes back with an
            # empty one and keeps playing: the scoreboard is the score,
            # and this only ever adds to what is reported. Such a game
            # logs the goals it has left rather than none, so a
            # half-finished game finishes with a part scoresheet --
            # which is what the summary's own note is for.
            goals=[
                GoalRecord.from_dict(goal)
                for goal in data.get("goals", [])
            ],
            **{
                saved_field.name: saved_field.restored(data)
                for saved_field in MATCH_SAVED_FIELDS
            },
        )


def load_player_catalog(
    path: Path = PLAYERS_FILE,
) -> PlayerCatalog:
    """
    A flat `"players"` table (one entry a player, keyed by id) plus a
    `"teams"` table naming each roster's ids into it -- since the
    2026-08-17 eight-team split, one player's id is named by two
    rosters (their color team and their species team), so embedding
    the player's own record under each team would mean carrying every
    dual-membership player's data twice. `players_by_id` is built once
    and shared: a `TeamDefinition`'s `players` is a tuple of the same
    `PlayerDefinition` objects a sibling roster names, not a copy.
    """
    data = json.loads(path.read_text(encoding="utf-8"))

    role_profiles = {
        PlayerRole(role): RoleProfile(**profile)
        for role, profile in data["role_profiles"].items()
    }

    players_by_id: dict[str, PlayerDefinition] = {
        player_id: PlayerDefinition(
            player_id=player_id,
            name=player_data["name"],
            role=PlayerRole(player_data["role"]),
            stat_overrides=player_data.get("stat_overrides", {}),
            species=player_data.get("species", ""),
        )
        for player_id, player_data in data["players"].items()
    }

    teams: dict[Team, TeamDefinition] = {}
    for team_value, team_data in data["teams"].items():
        team = Team(team_value)
        try:
            players = tuple(
                players_by_id[player_id]
                for player_id in team_data["player_ids"]
            )
        except KeyError as error:
            raise ValueError(
                f"{team.value}: roster names an unknown player id "
                f"{error.args[0]!r}."
            ) from error
        teams[team] = TeamDefinition(team=team, players=players)

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

    formations: dict[Formation, FormationShape] = {}
    for name, entry in data["formations"].items():
        counts = dict(entry)
        sizes = counts.pop("board_sizes", None)
        formations[Formation(name)] = FormationShape(
            board_sizes=(
                tuple(int(size) for size in sizes)
                if sizes is not None
                else None
            ),
            **counts,
        )
    if set(formations) != set(Formation):
        raise ValueError(
            "Basic rules must give a shape for every formation."
        )
    # A shape is named by its counts, read own goal forward, which is
    # what lets the printed team board list the names alone and what
    # makes "2-3-1" mean the same thing in a button label and in the
    # data behind it.
    for formation, shape in formations.items():
        dealt = "-".join(str(shape.count(area)) for area in SETUP_AREAS)
        if formation.value != dealt:
            raise ValueError(
                f"Formation {formation.value} is dealt {dealt}; a "
                "formation is named by its own counts."
            )
    unknown = sorted(
        {
            size
            for shape in formations.values()
            for size in (shape.board_sizes or ())
            if size not in layouts
        }
    )
    if unknown:
        raise ValueError(
            "A formation is restricted to board sizes with no layout: "
            f"{', '.join(str(size) for size in unknown)}."
        )
    # Every team is dealt 2-2-2, whatever board they are dealt onto, so
    # it is the one shape that cannot be restricted to some of them.
    if formations[Formation.TWO_TWO_TWO].board_sizes is not None:
        raise ValueError(
            "2-2-2 is the shape every team is dealt, so it must be "
            "open to every board."
        )

    standard_setup = {
        area: tuple(PlayerRole(role) for role in roles)
        for area, roles in data["standard_setup"].items()
    }
    if set(standard_setup) != set(SETUP_AREAS):
        raise ValueError("The standard setup has invalid areas.")

    dice = data["team_board"]["head_coach_dice"]
    team_board = TeamBoardDefinition(
        areas=tuple(data["team_board"]["areas"]),
        offense_die=DieDefinition(**dice["offense"]),
        defense_die=DieDefinition(**dice["defense"]),
        team_die=DieDefinition(**dice["team"]),
    )

    return BasicRuleset(
        ruleset_id=data["ruleset_id"],
        board_layouts=layouts,
        formations=formations,
        standard_setup=standard_setup,
        team_board=team_board,
    )


def load_maneuver_catalog(
    path: Path = MANEUVERS_FILE,
) -> ManeuverCatalog:
    data = json.loads(path.read_text(encoding="utf-8"))

    def build(maneuver_type: str) -> tuple[ManeuverDefinition, ...]:
        maneuvers = tuple(
            ManeuverDefinition(
                name=maneuver["name"],
                key=maneuver.get("key") or maneuver_key(maneuver["name"]),
                rank=maneuver["rank"],
                tier=maneuver.get("tier", MANEUVER_TIER_BASIC),
                die_values=tuple(maneuver["die_values"]),
                defeats_rank=maneuver["defeats_rank"],
                effect=maneuver["effect"],
                time=maneuver["time"],
            )
            for maneuver in data["maneuvers"][maneuver_type]
        )
        for maneuver in maneuvers:
            if maneuver.tier not in MANEUVER_TIERS:
                raise ValueError(
                    f"{maneuver.name}: unknown tier {maneuver.tier!r}."
                )
        # One card per rank per tier, so nothing can quietly go missing
        # and nothing can double up -- which is the whole of what makes
        # `resolve` answerable from a rank.
        seen = {(m.rank, m.tier) for m in maneuvers}
        if len(seen) != len(maneuvers):
            raise ValueError(
                f"{maneuver_type} maneuvers must be one per rank per tier."
            )
        return maneuvers

    return ManeuverCatalog(
        data_version=data["data_version"],
        source=data["source"],
        offense=build("offense"),
        defense=build("defense"),
    )


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
                    f"{team_display_name(roster.team)} has no available "
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
    duplicate_ids: Collection[str] = (),
) -> TeamSetup:
    """
    Field six of a team's cards in `formation`, benching the rest.

    `assignment` is the coach's own choice of which card goes where,
    keyed by setup area; leaving it out deals the formation by role
    (see default_formation_deal). Either way the shape is checked
    against the ruleset, so a saved assignment that no longer matches
    its formation is caught here rather than on the board.

    `duplicate_ids` are the roster's players the *other* side is
    fielding as well, and they are dealt under `duplicate_card_id` --
    so a match between two overlapping rosters is nine cards a side
    with eighteen distinct ids, rather than two sides sharing a card.
    Applied after the deal rather than before it, since the deal and
    the assignment are both about which of a team's *players* stand
    where, and the roster this is checked against is the catalog's.
    """
    side = TeamSide(side)
    formation = Formation(formation)
    shape = ruleset.formations[formation]

    if assignment is None:
        assignment = default_formation_deal(roster, ruleset, formation)
    else:
        validate_assignment(roster, shape, assignment)

    duplicated = set(duplicate_ids)

    def card_id(player_id: str) -> str:
        return (
            duplicate_card_id(player_id)
            if player_id in duplicated
            else player_id
        )

    zones = {
        zone_for_area(side, area): [
            card_id(player_id) for player_id in assignment[area]
        ]
        for area in SETUP_AREAS
    }
    selected_ids = {
        catalog_player_id(player_id)
        for players in zones.values()
        for player_id in players
    }
    bench = [
        card_id(player.player_id)
        for player in roster.players
        if player.player_id not in selected_ids
    ]

    setup = TeamSetup(
        team=roster.team,
        side=side,
        zones=zones,
        team_board=TeamBoardState(bench=bench),
    )
    setup.validate(roster)
    return setup

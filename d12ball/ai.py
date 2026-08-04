"""AI opponent templates for a solo D12 Ball game's Player 2.

Each concrete AIStrategy captures one AI opponent's decisions. Adding a new
AI opponent means adding a subclass here and registering it in
build_ai_strategies() — the cog and UI only ever talk to the AIOpponent enum
and the AIStrategy interface, never to a specific template.
"""

import random
from abc import ABC, abstractmethod
from typing import Optional

from .components import MatchState, ManeuverCatalog, PlayerCatalog
from .game import AIOpponent, HomeChoice


class AIStrategy(ABC):
    def __init__(
        self,
        player_catalog: PlayerCatalog,
        maneuver_catalog: ManeuverCatalog,
    ):
        self.player_catalog = player_catalog
        self.maneuver_catalog = maneuver_catalog

    @abstractmethod
    def choose_home_or_visiting(self) -> HomeChoice:
        ...

    @abstractmethod
    def choose_challenger(self, match: MatchState) -> str:
        ...

    @abstractmethod
    def choose_ball_handler(self, match: MatchState) -> str:
        ...

    @abstractmethod
    def choose_action(self, match: MatchState) -> str:
        ...

    @abstractmethod
    def choose_maneuver_action(self, side: str) -> str:
        ...

    @abstractmethod
    def choose_low_pass(self, match: MatchState) -> tuple[str, int]:
        """(direction, distance) -- direction is "forward"/"backward",
        distance is 1 or 2."""
        ...

    @abstractmethod
    def choose_high_pass_distance(self, match: MatchState) -> int:
        """2 or 3."""
        ...

    @abstractmethod
    def choose_speed_delta(self, skill: int) -> int:
        """A change to apply to the ball's speed, magnitude at most
        `skill` in either direction. The caller clamps the result to a
        valid speed."""
        ...

    @abstractmethod
    def choose_shooter(
        self,
        candidates: list[str],
        match: MatchState,
    ) -> str:
        """Which offensive player takes a scoring-opportunity shot."""
        ...

    @abstractmethod
    def choose_run_back_space(self, open_spaces: list[int]) -> int:
        ...

    @abstractmethod
    def choose_substitution(
        self,
        match: MatchState,
        side: str,
    ) -> Optional[tuple[str, str]]:
        """
        (player going off, player coming on), or None to make no
        further substitution and close out this side's window.
        """
        ...

    @abstractmethod
    def choose_loose_ball_player(
        self,
        candidates: list[str],
        skill_type: str,
    ) -> str:
        """Which zone-mate contests a loose ball; skill_type is
        "offense" or "defense", matching the skill the test uses."""
        ...


class DinkyAI(AIStrategy):
    """
    The original D12 Ball AI opponent: closest-player and
    higher-skill tie-breaks, maneuvering whenever it isn't already at
    the scoring space, and a random die roll for maneuver choice.
    """

    def choose_home_or_visiting(self) -> HomeChoice:
        return random.choice((HomeChoice.HOME, HomeChoice.VISITING))

    def choose_challenger(self, match: MatchState) -> str:
        """
        Always the player closest to the ball, with ties broken in
        favor of the higher defensive skill.
        """
        candidates = match.eligible_challengers()
        if not candidates:
            raise ValueError(
                "There are no eligible challengers to choose from."
            )

        def sort_key(player_id: str) -> tuple[int, int]:
            distance = match.distance_to_ball(player_id)
            defense = self.player_catalog.effective_profile(
                self.player_catalog.player_by_id(player_id)
            ).defense
            return (distance, -defense)

        return min(candidates, key=sort_key)

    def choose_ball_handler(self, match: MatchState) -> str:
        """
        When more than one of its players shares the ball's space,
        pick the one with the higher offensive skill.
        """
        candidates = match.eligible_ball_handlers()
        if not candidates:
            raise ValueError(
                "There are no eligible ball handlers to choose from."
            )

        def sort_key(player_id: str) -> int:
            return -self.player_catalog.effective_profile(
                self.player_catalog.player_by_id(player_id)
            ).offense

        return min(candidates, key=sort_key)

    def choose_action(self, match: MatchState) -> str:
        """
        Shoot when the ball is already on the space closest to the
        opponent's goal, otherwise always maneuver to advance it.
        """
        if match.is_ball_at_scoring_space():
            return "shoot"
        return "maneuver"

    def choose_maneuver_action(self, side: str) -> str:
        """
        Always roll a d6 and take whichever maneuver that die value
        maps to.
        """
        roll = random.randint(1, 6)
        if side == "offense":
            return self.maneuver_catalog.offense_for_die(roll).name
        return self.maneuver_catalog.defense_for_die(roll).name

    def _has_teammate_at_pass_distance(
        self,
        match: MatchState,
        distance: int,
    ) -> bool:
        """
        Whether a fielded teammate already occupies the space the ball
        would land on (clamped to the board edge) at this pass
        distance in the current attack direction.
        """
        offense_side = match.ball.possession
        origin_flat = match.board.flat_index(
            match.ball.zone, match.ball.space_index,
        )
        target_flat = match.relative_flat_index(
            origin_flat, offense_side, distance,
        )
        zone, space_index = match.board.position_at_flat_index(target_flat)
        offense_setup = match.setup_for_side(offense_side)
        occupants = match.board.spaces[zone][space_index]
        return any(
            player_id in offense_setup.field_players
            for player_id in occupants
        )

    def choose_low_pass(self, match: MatchState) -> tuple[str, int]:
        """
        Always forward -- backward risks an own goal for no advancing
        benefit. Prefers the farthest distance that still lands on a
        teammate, since passing into an empty space triggers a
        contested loose-ball skill test instead of a clean reception;
        only passes into empty space if no distance has a teammate.
        """
        for distance in (2, 1):
            if self._has_teammate_at_pass_distance(match, distance):
                return "forward", distance
        return "forward", 2

    def choose_high_pass_distance(self, match: MatchState) -> int:
        """
        Prefers the farthest distance (most likely to overshoot into a
        scoring opportunity) that still lands on a teammate; same
        loose-ball reasoning as choose_low_pass.
        """
        for distance in (3, 2):
            if self._has_teammate_at_pass_distance(match, distance):
                return distance
        return 3

    def choose_speed_delta(self, skill: int) -> int:
        """
        Always maximize the ball's speed. This ignores the tradeoff
        that a faster ball is also harder to keep possession of --
        simple by design, the same spirit as the rest of this AI.
        """
        return skill

    def choose_shooter(
        self,
        candidates: list[str],
        match: MatchState,
    ) -> str:
        """The candidate with the higher offensive skill."""

        def sort_key(player_id: str) -> int:
            return -self.player_catalog.effective_profile(
                self.player_catalog.player_by_id(player_id)
            ).offense

        return min(candidates, key=sort_key)

    def choose_run_back_space(self, open_spaces: list[int]) -> int:
        return min(open_spaces)

    def choose_substitution(
        self,
        match: MatchState,
        side: str,
    ) -> Optional[tuple[str, str]]:
        """
        Only ever substitutes to get an injured player off, which is
        the one case the rules make compulsory. Dinky stays a
        dice-roller: it never spends a declaration on a tactical swap
        and never rearranges.
        """
        for player_id in match.injured_field_players(side):
            pool = match.substitution_pool(side, player_id)
            if pool:
                return player_id, pool[0]
        return None

    def choose_loose_ball_player(
        self,
        candidates: list[str],
        skill_type: str,
    ) -> str:
        """The candidate with the higher skill of whichever type this
        side rolls with."""

        def sort_key(player_id: str) -> int:
            profile = self.player_catalog.effective_profile(
                self.player_catalog.player_by_id(player_id)
            )
            skill = (
                profile.offense if skill_type == "offense"
                else profile.defense
            )
            return -skill

        return min(candidates, key=sort_key)


def build_ai_strategies(
    player_catalog: PlayerCatalog,
    maneuver_catalog: ManeuverCatalog,
) -> dict[AIOpponent, AIStrategy]:
    return {
        AIOpponent.DINKY: DinkyAI(player_catalog, maneuver_catalog),
    }

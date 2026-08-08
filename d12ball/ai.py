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
    def choose_low_pass(
        self,
        match: MatchState,
        candidates: list[tuple[int, str]],
    ) -> int:
        """Which destination to pass to, as the signed distance (-2 to
        2, forward positive) from a (distance, receiver_id) candidate
        list -- Low Pass has no fixed distance, only the nearest
        teammate each way within 2 spaces and one sharing the ball's
        space. Never called with an empty candidate list: a handler
        with nobody to pass to has no choice to make, and
        resolve_low_pass settles that case."""
        ...

    @abstractmethod
    def choose_low_pass_receiver(
        self,
        match: MatchState,
        receivers: list[str],
    ) -> str:
        """Which teammate on the destination space actually takes the
        pass. Usually only one is standing there and there is nothing
        to choose; a formation that stacks (4-1-1, 2-1-3) can put two
        or three on it, and the pick decides who a Winger's set-up
        hands the shot to. Never called with an empty list."""
        ...

    @abstractmethod
    def choose_dribble_advance_distance(self, match: MatchState) -> int:
        """1 or 2 -- only ever asked of a Playmaker, everyone else
        advances a fixed 1 space with no choice to make."""
        ...

    @abstractmethod
    def choose_high_pass_distance(
        self,
        match: MatchState,
        max_distance: int,
    ) -> int:
        """2 up to max_distance (3, or 4 for a Fullback)."""
        ...

    @abstractmethod
    def choose_scoring_opportunity_attempt(self, match: MatchState) -> bool:
        """Whether to take an offered scoring-opportunity shot -- a
        High Pass's own 2-space pass, or a Winger's Low Pass --
        instead of letting the maneuver resolve normally."""
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

    def choose_low_pass(
        self,
        match: MatchState,
        candidates: list[tuple[int, str]],
    ) -> int:
        """Always the most forward teammate-occupied space available
        -- same maximizing spirit as choose_speed_delta."""
        return max(distance for distance, _ in candidates)

    def choose_low_pass_receiver(
        self,
        match: MatchState,
        receivers: list[str],
    ) -> str:
        """The best attacker standing there. The receiver only matters
        when the passer is a Winger, whose ability offers this player
        the shot, so offense is the skill to pick on."""
        return max(
            receivers,
            key=lambda player_id: self.player_catalog.effective_profile(
                self.player_catalog.player_by_id(player_id)
            ).offense,
        )

    def choose_dribble_advance_distance(self, match: MatchState) -> int:
        """Always take the full 2 spaces -- same maximizing spirit as
        choose_speed_delta."""
        return 2

    def choose_high_pass_distance(
        self,
        match: MatchState,
        max_distance: int,
    ) -> int:
        """Always take the longest pass available -- same maximizing
        spirit as choose_dribble_advance_distance. This never chases
        the 2-space scoring-opportunity option in favor of distance."""
        return max_distance

    def choose_scoring_opportunity_attempt(self, match: MatchState) -> bool:
        """Always take the shot when offered one."""
        return True

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
        Only ever substitutes to get an injured player off. The rules
        no longer compel that -- an injured player may stay on all
        game -- but it is still the one swap worth making without
        reading the position, and Dinky stays a dice-roller: it never
        spends a declaration on a tactical swap and never rearranges.
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

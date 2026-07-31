"""AI opponent templates for a solo D12 Ball game's Player 2.

Each concrete AIStrategy captures one AI opponent's decisions. Adding a new
AI opponent means adding a subclass here and registering it in
build_ai_strategies() — the cog and UI only ever talk to the AIOpponent enum
and the AIStrategy interface, never to a specific template.
"""

import random
from abc import ABC, abstractmethod

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


def build_ai_strategies(
    player_catalog: PlayerCatalog,
    maneuver_catalog: ManeuverCatalog,
) -> dict[AIOpponent, AIStrategy]:
    return {
        AIOpponent.DINKY: DinkyAI(player_catalog, maneuver_catalog),
    }

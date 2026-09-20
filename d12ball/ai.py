"""AI opponent templates for a solo D12 Ball game's Player 2.

Each concrete AIStrategy captures one AI opponent's decisions. Adding a new
AI opponent means adding a subclass here and registering it in
build_ai_strategies() — the cog and UI only ever talk to the AIOpponent enum
and the AIStrategy interface, never to a specific template.
"""

import random
from abc import ABC, abstractmethod
from typing import Optional, Sequence

from .components import (
    MANEUVER_TIER_BASIC,
    ManeuverCatalog,
    ManeuverDefinition,
    MatchState,
    PlayerCatalog,
)
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
        """Which zone player walks in to challenge a maneuver. A
        human defense may also send nobody and let the maneuver
        through; no strategy is offered that, so this returns a player
        rather than an Optional -- see DinkyAI.choose_challenger."""
        ...

    @abstractmethod
    def choose_ball_handler(self, match: MatchState) -> str:
        ...

    @abstractmethod
    def choose_action(self, match: MatchState) -> str:
        """One of "shoot", "maneuver" or "time_out". A strategy may
        only return "shoot" where `match.can_attempt_score()` is true
        and "time_out" where `match.may_call_time_out()` is -- both are
        gated by the rules, and a human is offered no button for either
        outside them."""
        ...

    @abstractmethod
    def choose_maneuver_action(
        self,
        side: str,
        hand: Optional[Sequence[ManeuverDefinition]] = None,
    ) -> str:
        """The maneuver **key** this side plays. `hand` is what the
        game actually offers -- three cards in a basic game, six in an
        advanced one -- and None means the basic three."""
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
        to choose; a formation that stacks (2-3-1 or 1-3-2 on a
        six-space board) can put two on it, and the pick decides who a
        Winger's set-up hands the shot to. Never called with an empty
        list."""
        ...

    @abstractmethod
    def choose_dribble_advance_distance(self, match: MatchState) -> int:
        """1 or 2 -- only ever asked of a Playmaker, everyone else
        advances a fixed 1 space with no choice to make."""
        ...

    @abstractmethod
    def choose_dribble_burst_distance(
        self,
        match: MatchState,
        distances: list[int],
    ) -> int:
        """
        One of `distances` -- how far to run a won Dribble Burst,
        which is 1 up to `DRIBBLE_BURST_MAX_DISTANCE` less anything
        the end of the field takes away. Never called with an empty
        list: a handler already on the last space has no run to
        choose, and D12Ball.resolve_dribble_burst takes that branch
        before asking anyone. See RulesEngine.dribble_burst_distances.
        """
        ...

    @abstractmethod
    def choose_high_pass_distance(
        self,
        match: MatchState,
        distances: list[int],
    ) -> int:
        """
        One of `distances` -- what the coach's own menu would offer,
        which is 2 up to the handler's maximum less anything that runs
        out of field. Never called with an empty list: a position
        where every distance overshoots has no choice in it at all,
        and D12Ball.resolve_high_pass takes that branch before asking
        anyone. See MatchState.high_pass_distances.

        **Setup Pass asks this too**, with its own 0/1/3 (and 4)
        list. It is the same question -- how far to pick the ball out,
        knowing a landing space with nobody on it gives the ball away
        -- so it gets the same answer rather than a policy of its own.
        """
        ...

    @abstractmethod
    def choose_scoring_opportunity_attempt(self, match: MatchState) -> bool:
        """Whether to take an offered scoring-opportunity shot -- a
        High Pass's own 2-space pass, a High Pass that overshoots, or a
        Winger's Low Pass -- instead of letting the maneuver resolve
        normally. Declining an overshoot is a contest for the ball
        rather than a settled pass."""
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
    def choose_run_back_player(
        self,
        match: MatchState,
        candidates: list[str],
    ) -> str:
        """
        Which of a stack of teammates on one space runs back out of it.
        Only asked where the choice is real: a stack the ball's holder
        is standing in offers one candidate and is settled without
        anybody being asked.
        """
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
        match: MatchState,
        candidates: list[str],
        skill_type: str,
    ) -> str:
        """Which of the nearest players contests a loose ball;
        skill_type is "offense" or "defense", matching the skill the
        test uses. `match` is what puts a distance on a candidate."""
        ...

    @abstractmethod
    def choose_shootout_order(self, field_players: list[str]) -> list[str]:
        """The six, in the order they shoot in the shootout's first
        round. Must be a permutation of what it was given."""
        ...

    @abstractmethod
    def choose_shootout_shooter(self, candidates: list[str]) -> str:
        """Who goes out next in a sudden-death round, from those who
        have not shot yet this round."""
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
        favor of the higher defensive skill. Asked of
        `challenge_candidates`, which is the defenders already standing
        on the ball wherever there are any -- the same pool a coach is
        offered, and the same answer the distance sort would have
        reached from the wider one.

        Dinky always challenges. Sending nobody rather than paying the
        walk-in's exhaustion is legal since 2026-08-12, and it is a
        judgement about a game two turns from now -- the same kind of
        call Dinky does not make when it declines to Smooth the ball or
        to leave a loose ball alone.
        """
        candidates = match.challenge_candidates()
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
        pick the one with the higher offensive skill. A ball carrier
        leaves nothing to pick -- turn_handler_candidates narrows to
        them, so this is a one-element list and the skill sort is moot.

        **Dinky never takes a Smooth**, so a carrier still narrows
        this to one. That is decided at the arrival gate rather than
        here -- `continue_smooth` skips an AI side's Telekinetics the
        way `continue_mind_pull` skips them -- which is the same call
        as never ceding, never declining a challenge and never leaving
        a loose ball uncontested. In a solo game the option is the
        human's alone. This asks the match rather than the engine
        because the two now answer identically and the match is the
        shorter road.
        """
        candidates = match.turn_handler_candidates()
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
        opponent's goal; call a time out to get an injured player off;
        otherwise maneuver to advance the ball.

        The scoring space is always within shooting range, so this
        never picks a shot the range rule forbids, and the time out is
        gated on `may_call_time_out` for the same reason.

        **The time out is the one call Dinky makes that looks like
        judgement and is not** (the author, 2026-09-16). Everything
        else Dinky declines to do -- ceding, as this used to be,
        declining a challenge, taking a Smooth, pulling the ball -- is a
        weighing-up with no right answer. Getting an injured player off
        is not: an injured player rolls without their skill modifier
        for the rest of the game and can never recover, so there is
        nothing to weigh. The test is a fact about the board, which is
        the only kind of decision Dinky makes.

        It is checked **after** the shot, because a shot on is worth
        more than a substitution and the time out will still be there
        next turn. It is checked **before** the maneuver for the
        opposite reason: a maneuver is what Dinky does when it has
        nothing better to do.

        Nothing here asks whether there is anybody to bring on. The
        rules deliberately do not gate the window on that either (see
        `may_call_time_out`), and a side with both benches spent is
        rare enough that asking would cost more than it saved -- Dinky
        opens the window, finds no swap available, and closes it, one
        wasted minute in a game that will not see the state twice.
        """
        if match.is_ball_at_scoring_space():
            return "shoot"
        if (
            match.may_call_time_out()
            and match.injured_field_players(match.ball.possession)
        ):
            return "time_out"
        return "maneuver"

    def choose_maneuver_action(
        self,
        side: str,
        hand: Optional[Sequence[ManeuverDefinition]] = None,
    ) -> str:
        """
        Always roll a d6 and take whichever maneuver that die value
        maps to -- then, when the hand holds more than one card on that
        rank, pick between the tiers at random.

        **Dinky makes no judgement here and this does not change
        that.** The die picks a rank, exactly as it always has; the
        second draw only decides whether the card is the basic one or
        its advanced counterpart, which is the same coin-flip
        indifference Dinky brings to every other choice it is not
        maximizing. What it is *not* is a policy: an advanced card
        carries a cost as well as a benefit and weighing the two is
        judgement, which Dinky does not do -- see "Dinky never cedes"
        (it calls a time out, which is a different kind of call).
        The alternative was Dinky never playing an advanced card at
        all, which would leave half of advanced mode unreachable in a
        solo game.
        """
        roll = random.randint(1, 6)
        if side == "offense":
            rank = self.maneuver_catalog.offense_for_die(roll).rank
        else:
            rank = self.maneuver_catalog.defense_for_die(roll).rank

        if hand is None:
            hand = self.maneuver_catalog.for_tier(side, MANEUVER_TIER_BASIC)
        on_rank = [maneuver for maneuver in hand if maneuver.rank == rank]
        if not on_rank:
            # A hand that does not cover every rank is not a state the
            # game produces, but picking out of what is actually there
            # is cheaper than a branch that can never be right.
            on_rank = list(hand)
        return random.choice(on_rank).key

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

    def choose_dribble_burst_distance(
        self,
        match: MatchState,
        distances: list[int],
    ) -> int:
        """
        Always run the full distance on offer -- same maximizing
        spirit as choose_dribble_advance_distance.

        The exhaustion is a token a space, so a shorter burst is a
        real option and Dinky is deliberately not taking it: weighing
        field position against a player's stamina is judgement, and
        Dinky makes none. Same call as never ceding and never playing
        an advanced card for its cost rather than its benefit.
        """
        return distances[-1]

    def choose_high_pass_distance(
        self,
        match: MatchState,
        distances: list[int],
    ) -> int:
        """
        The longest pass that actually reaches a teammate, and
        otherwise the longest available -- the author, 2026-08-18.
        Distance alone was throwing the ball past everybody: a pass
        landing where the offense has nobody is a loose ball, so
        maximizing it was maximizing how often Dinky gave the ball
        away.

        Still maximizing within that, in the same spirit as
        choose_dribble_advance_distance, and still never chasing the
        2-space scoring-opportunity option for its own sake. The list
        is already free of distances that overshoot, so the longest is
        a real pass rather than a clamped one.

        **Setup Pass is answered from here as well** (2026-08-25),
        since a Setup Pass that lands on nobody now leaves the ball
        lying there for the other side exactly as a High Pass does.
        Its 0 counts as reaching somebody only when a teammate shares
        the passer's space, which is what high_pass_receivers_at
        already says.
        """
        reaching = [
            distance
            for distance in distances
            if match.high_pass_receivers_at(match.ball.possession, distance)
        ]
        return (reaching or distances)[-1]

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

    def choose_run_back_player(
        self,
        match: MatchState,
        candidates: list[str],
    ) -> str:
        """
        The freshest of them -- running back costs a token a space, so
        the one carrying the fewest is the one who can best afford the
        walk. Ties go to the first, which keeps the pick deterministic
        the way every other Dinky answer is.
        """
        return min(
            candidates,
            key=lambda player_id: (
                match.exhaustion.get(player_id, 0),
                candidates.index(player_id),
            ),
        )

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

        Who comes on is the nearest replacement for the player going
        off rather than whoever is at the front of the bench -- see
        closest_role_replacement. Replacing a striker with a defender
        is a change of shape, and Dinky does not make those.
        """
        pool = match.substitution_pool(side)
        injured = match.injured_field_players(side)
        if pool and injured:
            outgoing_player_id = injured[0]
            return (
                outgoing_player_id,
                self.closest_role_replacement(outgoing_player_id, pool),
            )
        return None

    def closest_role_replacement(
        self,
        outgoing_player_id: str,
        pool: list[str],
    ) -> str:
        """
        Whoever in `pool` plays nearest the outgoing player's role --
        the same role when the pool has one, and otherwise the closest
        role to it.

        The six roles are a single spectrum, fullback (1/6) through to
        striker (6/1), so a role's *offensive skill is* its place on it
        and the distance between two roles is the gap between those.
        That is read off `role_profiles` rather than off the two
        players, because a stat_override moves one player's numbers
        without moving their role, and it is the role being matched.

        A tie -- a midfielder with a defender and a playmaker to choose
        between, either of them one step away -- goes to whichever the
        pool lists first, which is bench order. There is no rules
        answer to which way a coach should lean, and Dinky does not
        read the position to invent one.
        """
        rank = self.role_rank(outgoing_player_id)
        return min(
            pool,
            key=lambda player_id: abs(self.role_rank(player_id) - rank),
        )

    def role_rank(self, player_id: str) -> int:
        return self.player_catalog.role_profiles[
            self.player_catalog.player_by_id(player_id).role
        ].offense

    def choose_loose_ball_player(
        self,
        match: MatchState,
        candidates: list[str],
        skill_type: str,
    ) -> str:
        """
        The nearest candidate, with ties broken in favour of the
        higher skill of whichever type this side rolls with.

        It used to be the higher skill outright, which was a fair read
        of a pool that was the whole of a zone. Since 2026-08-16 the
        pool is the nearest player either side of the ball, so the
        choice is a token or three against a point or two of skill --
        a trade Dinky has no way to price, and the cheap end of it is
        what keeps its side off the Exhausted list. Same answer as
        every other player it sends anywhere.
        """

        def sort_key(player_id: str) -> tuple[int, int]:
            profile = self.player_catalog.effective_profile(
                self.player_catalog.player_by_id(player_id)
            )
            skill = (
                profile.offense if skill_type == "offense"
                else profile.defense
            )
            return (match.distance_to_ball(player_id), -skill)

        return min(candidates, key=sort_key)

    def choose_shootout_order(self, field_players: list[str]) -> list[str]:
        """
        A random permutation. Only the first round is ordered, and the
        shootout's early stop means the later cards may never be
        reached, so stacking the top is the stronger play -- but who
        shoots when is a read of the other coach's order, which Dinky
        does not make, the same call as the maneuver die and never
        ceding.
        """
        order = list(field_players)
        random.shuffle(order)
        return order

    def choose_shootout_shooter(self, candidates: list[str]) -> str:
        return random.choice(candidates)


def build_ai_strategies(
    player_catalog: PlayerCatalog,
    maneuver_catalog: ManeuverCatalog,
) -> dict[AIOpponent, AIStrategy]:
    return {
        AIOpponent.DINKY: DinkyAI(player_catalog, maneuver_catalog),
    }

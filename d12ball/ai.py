"""AI opponent templates for a solo D12 Ball game's Player 2.

Each concrete AIStrategy captures one AI opponent's decisions. Adding a
new AI opponent means adding a subclass here and registering it in
build_ai_strategies() -- the cog and UI only ever talk to the AIOpponent
enum and the AIStrategy interface, never to a specific template.

**The AI answers prompts.** `choose` takes the `PendingPrompt` the match
is waiting on -- the same question a coach is asked, carrying the same
`options` -- and hands back the `Action` a click would, which
`GameService.run` puts through `driver.answer` like anyone else's
(ARCHITECTURE.md, "AI"; step 7 of docs/architecture-migration.md). So
a strategy reads what the prompt offers and never the wider position
for a candidate list: an answer outside the offer is refused, the way a
stale click is, and the refusal is a bug in the strategy. Until step 7
the AI was nineteen methods called from inside the flow behind
`side_is_ai` forks, each mutating the match through its own path; the
decisions those methods made are the branches of `DinkyAI.choose`, one
per kind, with their reasoning kept beside them.

**The AI never rolls.** Every roll waits behind a button either coach
may press (CLAUDE.md, "Nothing rolls dice on its own"); a roll prompt
is nobody's question (`d12ball.prompts.asked_sides`), so `choose` is
never asked one.

**A rail wins.** Where the tutorial's script fixes a choice the
prompt's options say which (`railed`), and the adapter refuses anything
else; Dinky's own policy applies only where the script leaves the
choice free. The one place the script names Dinky's card outright, the
maneuver pick, is a rail on its hand like the coach's on theirs.
"""

import random
from abc import ABC, abstractmethod
from typing import Optional

from .components import (
    ManeuverCatalog,
    MatchState,
    PlayerCatalog,
    TeamSide,
    Zone,
)
from .formatting import format_ai_name
from .game import AIOpponent, HomeChoice, Team
from .prompts import (
    Action,
    CoachingHubOptions,
    PendingPrompt,
    PromptKind,
)


class AIStrategy(ABC):
    def __init__(
        self,
        player_catalog: PlayerCatalog,
        maneuver_catalog: ManeuverCatalog,
    ):
        self.player_catalog = player_catalog
        self.maneuver_catalog = maneuver_catalog
        #: Where a strategy's own draws come from -- a team out of the
        #: pool, a rank off a d6, a shooter. The engine replaces it
        #: with its own `rng` when it takes the strategy on
        #: (`RulesEngine.__init__`), so one seed fixes the dice and
        #: the AI together and nothing in the model reads the module
        #: `random` (decision 7 of docs/web-app.md).
        self.rng: random.Random = random.Random()

    @abstractmethod
    def choose_team(self, pool: list[Team]) -> Team:
        """
        The AI's team, drawn from what Player 1's pick left it
        (`D12BallGame.ai_team_pool`). Nobody is holding the AI's
        buttons, so the pool it draws from is the only check a solo
        game has -- and the pool is the record's, the same rule the
        picker greys out by, so the AI cannot land on the one matchup
        a coach may not pick.
        """
        ...

    @abstractmethod
    def choose_home_or_visiting(self) -> HomeChoice:
        """Setup's other question to the AI, asked at the coin toss it
        won; not a prompt, since setup is outside the turn driver
        (step 8 of docs/architecture-migration.md). A tutorial does
        not ask: its script is written for a coach with the ball at
        kickoff, so `GameService.flip_coin` seats Dinky visiting."""
        ...

    @abstractmethod
    def choose(
        self,
        prompt: PendingPrompt,
        game,
        match: MatchState,
        side: TeamSide,
    ) -> Action:
        """
        The `Action` this side gives to `prompt`.

        `side` is the side of the board being answered for -- the
        prompt's own where it names one, and one of the two where a
        prompt is put to both (the maneuver pick, the shootout's
        menus). `game` is there for the one answer that names the AI
        (a passed Coaching Choice is worded with the coach's name).
        Reads `prompt.options` for what may be chosen and `match` for
        what to prefer among them; never asked a roll, the tutorial's
        Continue or the finished game.
        """
        ...


class DinkyAI(AIStrategy):
    """
    The original D12 Ball AI opponent: closest-player and higher-skill
    tie-breaks, maneuvering whenever it isn't already at the scoring
    space, and a random die roll for maneuver choice.

    **Dinky makes no judgement.** Everything it declines to do --
    ceding, as it used to; declining a challenge; taking a Smooth;
    pulling the ball; leaving a loose ball alone; a shorter burst to
    save a player's legs; a gambit played for its cost rather than on
    the die -- is a weighing-up with no right answer, and Dinky is a
    dice-roller. The one call that looks like judgement and is not is
    the time out to get an injured player off (the author,
    2026-09-16): an injured player rolls without their skill for the
    rest of the game and never recovers, so there is nothing to weigh;
    it is a fact about the board, which is the only kind of decision
    Dinky makes.
    """

    def choose_team(self, pool: list[Team]) -> Team:
        return self.rng.choice(pool)

    def choose_home_or_visiting(self) -> HomeChoice:
        return self.rng.choice((HomeChoice.HOME, HomeChoice.VISITING))

    def choose(
        self,
        prompt: PendingPrompt,
        game,
        match: MatchState,
        side: TeamSide,
    ) -> Action:
        kind = prompt.kind
        options = prompt.options
        answer = self.ANSWERS.get(kind)
        if answer is None:
            raise ValueError(
                f"{format_ai_name(AIOpponent.DINKY)} is never asked "
                f"{kind.name}."
            )
        return answer(self, prompt, game, match, TeamSide(side), options)

    # -- The turn -------------------------------------------------------

    def _ball_handler(self, prompt, game, match, side, options) -> Action:
        """
        When more than one of its players shares the ball's space,
        the one with the higher offensive skill. A ball carrier is
        never asked -- `turn_handler_candidates` narrows to them.
        """
        return Action(
            prompt.kind,
            "",
            {"player_id": self._best_offense(options.player_ids)},
        )

    def _turn_action(self, prompt, game, match, side, options) -> Action:
        """
        Shoot when the ball is already on the space closest to the
        opponent's goal; call a time out to get an injured player off;
        otherwise maneuver to advance the ball.

        The scoring space is always within shooting range, so this
        never picks a shot the range rule forbids, and both are read
        off what the prompt offers as live -- the position's rules and
        the tutorial's rails, in one list.

        The time out is checked **after** the shot, because a shot on
        is worth more than a substitution and the time out will still
        be there next turn, and **before** the maneuver for the
        opposite reason: a maneuver is what Dinky does when it has
        nothing better to do. Nothing here asks whether there is
        anybody to bring on -- the rules do not gate the window on
        that either (`may_call_time_out`), and a side with both
        benches spent is rare enough that Dinky opening the window,
        finding no swap, and closing it costs one wasted minute in a
        game that will not see the state twice.
        """
        live = options.live
        if "shoot" in live and match.is_ball_at_scoring_space():
            return Action(prompt.kind, "shoot")
        if "time_out" in live and match.injured_field_players(
            match.ball.possession,
        ):
            return Action(prompt.kind, "time_out")
        return Action(prompt.kind, "maneuver")

    def _challenger(self, prompt, game, match, side, options) -> Action:
        """
        Always the player closest to the ball, with ties broken in
        favor of the higher defensive skill, out of the candidates the
        prompt offers -- the defenders already standing on the ball
        wherever there are any, the same pool a coach is offered.

        Dinky always challenges. Sending nobody rather than paying the
        walk-in's exhaustion is legal since 2026-08-12, and it is a
        judgement about a game two turns from now -- the same kind of
        call Dinky does not make when it declines to Smooth the ball or
        to leave a loose ball alone.
        """
        return Action(
            prompt.kind,
            "send",
            {
                "player_id": self._nearest(
                    match, options.player_ids, skill="defense",
                ),
            },
        )

    def _maneuver_pick(self, prompt, game, match, side, options) -> Action:
        """
        Always roll a d6 and take whichever maneuver that die value
        maps to -- then, when the hand holds more than one card on that
        rank, pick between the tiers at random.

        **Dinky makes no judgement here and this does not change
        that.** The die picks a rank, exactly as it always has; the
        second draw only decides whether the card is the basic one or
        its gambit, which is the same coin-flip indifference Dinky
        brings to every other choice it is not maximizing. A gambit
        carries a cost as well as a benefit and weighing the two is
        judgement, which Dinky does not do. The alternative was Dinky
        never playing a gambit at all, which would leave half of
        advanced mode unreachable in a solo game.

        The tutorial names Dinky's card, and the prompt carries it as
        the rail on Dinky's hand; the die is not rolled for a railed
        pick, so a scripted opening spends no randomness on it.
        """
        pick_side = "offense" if side == match.ball.possession else "defense"
        hand = next(
            hand for hand in options.hands if hand.side == pick_side
        )
        if hand.railed is not None:
            key = hand.railed
        else:
            roll = self.rng.randint(1, 6)
            if pick_side == "offense":
                rank = self.maneuver_catalog.offense_for_die(roll).rank
            else:
                rank = self.maneuver_catalog.defense_for_die(roll).rank
            on_rank = [
                key for key in hand.maneuver_keys
                if self.maneuver_catalog.definition(key).rank == rank
            ]
            if not on_rank:
                # A hand that does not cover every rank is not a state
                # the game produces, but picking out of what is
                # actually there is cheaper than a branch that can
                # never be right.
                on_rank = list(hand.maneuver_keys)
            key = self.rng.choice(on_rank)
        return Action(
            prompt.kind, "", {"side": pick_side, "maneuver_key": key},
        )

    # -- The effects ----------------------------------------------------

    def _low_pass(self, prompt, game, match, side, options) -> Action:
        """
        Always the most forward teammate-occupied space available --
        same maximizing spirit as the speed choice -- and, where
        several teammates are standing there, the best attacker: the
        receiver only matters when the passer is a Winger, whose
        ability offers this player the shot, so offense is the skill
        to pick on.
        """
        best = max(options.passes, key=lambda option: option.distance)
        return Action(
            prompt.kind,
            "",
            {
                "distance": best.distance,
                "receiver_id": self._best_offense(best.receiver_ids),
            },
        )

    def _longest_reaching_pass(
        self, prompt, game, match, side, options,
    ) -> Action:
        """
        The longest pass that actually reaches a teammate, and
        otherwise the longest available -- the author, 2026-08-18.
        Distance alone was throwing the ball past everybody: a pass
        landing where the offense has nobody is a loose ball, so
        maximizing it was maximizing how often Dinky gave the ball
        away. Still maximizing within that, and never chasing the
        2-space scoring-opportunity option for its own sake.

        **Setup Pass is answered from here as well** (2026-08-25): a
        Setup Pass that lands on nobody leaves the ball lying there
        for the other side exactly as a High Pass does. Its 0 counts
        as reaching somebody only when a teammate shares the passer's
        space, which is what `high_pass_receivers_at` already says. A
        Setup Pass with nowhere to go at all is the card's one way
        out of play, and the answer then names no distance.
        """
        distances = options.distances
        if not distances:
            return Action(prompt.kind, "")
        if options.railed is not None:
            return Action(prompt.kind, "", {"distance": options.railed})
        reaching = [
            distance
            for distance in distances
            if match.high_pass_receivers_at(match.ball.possession, distance)
        ]
        return Action(
            prompt.kind, "", {"distance": (reaching or list(distances))[-1]},
        )

    def _farthest(self, prompt, game, match, side, options) -> Action:
        """
        Always the full distance on offer: a Playmaker's 2-space
        Dribble Advance, the whole Dribble Burst, the push back as far
        as it goes, the ball as fast as this player can set it.

        The burst is a token a space, so a shorter one is a real option
        and Dinky is deliberately not taking it: weighing field
        position against a player's stamina is judgement, and Dinky
        makes none. The speed choice ignores the tradeoff that a faster
        ball is also harder to keep possession of, in the same spirit.
        """
        return Action(
            prompt.kind,
            "",
            {"distance": self._railed_or_max(options, options.distances)},
        )

    def _speed(self, prompt, game, match, side, options) -> Action:
        return Action(
            prompt.kind,
            "",
            {"target_speed": self._railed_or_max(options, options.targets)},
        )

    def _take_the_shot(self, prompt, game, match, side, options) -> Action:
        """Always take the shot when offered one -- a High Pass's own
        2-space pass, an overshoot, a Winger's Low Pass -- rather than
        letting the maneuver resolve normally."""
        return Action(prompt.kind, options.railed or "take")

    def _shooter(self, prompt, game, match, side, options) -> Action:
        """The candidate with the higher offensive skill."""
        return Action(
            prompt.kind,
            "",
            {"shooter_id": self._best_offense(options.player_ids)},
        )

    def _let_it_pass(self, prompt, game, match, side, options) -> Action:
        """
        **Dinky never takes a Smooth and never pulls.** Taking the
        ball over moves who plays the next turn, and paying a token
        for a one-in-six steal is a judgement call; Dinky makes
        neither, the same call as never ceding and never declining a
        challenge. In a solo game the two abilities are the human's
        alone.
        """
        return Action(
            prompt.kind,
            options.railed or "decline",
            {"player_id": prompt.player_id},
        )

    # -- The turnovers --------------------------------------------------

    def _loose_ball(self, prompt, game, match, side, options) -> Action:
        """
        Always contests -- going out of bounds by choice is never
        obviously right -- with the nearest candidate, ties broken in
        favour of the higher skill of whichever type this side rolls
        with.

        It used to be the higher skill outright, which was a fair read
        of a pool that was the whole of a zone. Since 2026-08-16 the
        pool is the nearest player either side of the ball, so the
        choice is a token or three against a point or two of skill --
        a trade Dinky has no way to price, and the cheap end of it is
        what keeps its side off the Exhausted list.
        """
        return Action(
            prompt.kind,
            "send",
            {
                "player_id": self._nearest(
                    match, options.player_ids, skill=prompt.skill_type,
                ),
                "skill_type": prompt.skill_type,
            },
        )

    def _run_back_player(self, prompt, game, match, side, options) -> Action:
        """
        The freshest of a stack -- running back costs a token a space,
        so the one carrying the fewest is the one who can best afford
        the walk. Ties go to the first, which keeps the pick
        deterministic the way every other Dinky answer is.
        """
        candidates = options.player_ids
        return Action(
            prompt.kind,
            "",
            {
                "player_id": min(
                    candidates,
                    key=lambda player_id: (
                        match.exhaustion.get(player_id, 0),
                        candidates.index(player_id),
                    ),
                ),
            },
        )

    def _run_back_space(self, prompt, game, match, side, options) -> Action:
        return Action(
            prompt.kind,
            "",
            {
                "space_index": min(options.space_indices),
                "player_id": prompt.player_id,
            },
        )

    def _pick_the_ball_up(self, prompt, game, match, side, options) -> Action:
        """Nearest, not best: this walk costs a token per space and wins
        nothing, so the only thing worth optimizing is how much it
        costs."""
        return Action(
            prompt.kind,
            "",
            {"player_id": min(options.player_ids, key=match.distance_to_ball)},
        )

    # -- The windows and the breaks -------------------------------------

    def _coaching_offer(self, prompt, game, match, side, options) -> Action:
        """
        Coach only to get an injured player off; otherwise pass. The
        same swap `_coaching_hub` makes is the only reason to open the
        window, so the offer is answered by asking whether there is
        one to make.
        """
        if self._injured_swap(match, side) is not None:
            return Action(prompt.kind, "declare", {"side": side})
        return Action(prompt.kind, "decline", {"side": side})

    def _coaching_hub(self, prompt, game, match, side, options) -> Action:
        """
        Only ever substitutes to get an injured player off. The rules
        no longer compel that -- an injured player may stay on all
        game -- but it is still the one swap worth making without
        reading the position, and Dinky stays a dice-roller: it never
        spends a declaration on a tactical swap and never rearranges.

        The one move it does make is the kickoff space: every
        arrangement covers its own side's, a coach is refused Done
        until they have (`CoachingHubOptions.finish_refusal`), and
        Dinky is held to the same rule -- it moves the nearest
        midfielder onto it, at no cost, and then says it is done.
        """
        if options.may_substitute:
            swap = self._injured_swap(match, side, options)
            if swap is not None:
                outgoing_player_id, incoming_player_id = swap
                return Action(
                    prompt.kind,
                    "substitute",
                    {
                        "side": side,
                        "outgoing_player_id": outgoing_player_id,
                        "incoming_player_id": incoming_player_id,
                    },
                )
        if options.finish_refusal is not None:
            cover = self._kickoff_cover(match, side, options)
            if cover is not None:
                player_id, space_index = cover
                return Action(
                    prompt.kind,
                    "reposition",
                    {
                        "side": side,
                        "player_id": player_id,
                        "space_index": space_index,
                    },
                )
        return Action(prompt.kind, "done", {"side": side})

    def _halftime_token(self, prompt, game, match, side, options) -> Action:
        """The most tired of them loses the extra token."""
        return Action(
            prompt.kind,
            "",
            {
                "player_id": max(
                    options.player_ids,
                    key=lambda player_id: match.exhaustion.get(player_id, 0),
                ),
                "side": side,
            },
        )

    def _shootout_order(self, prompt, game, match, side, options) -> Action:
        """
        A random order, built one name at a time. Only the first round
        is ordered, and the shootout's early stop means the later cards
        may never be reached, so stacking the top is the stronger play
        -- but who shoots when is a read of the other coach's order,
        which Dinky does not make, the same call as the maneuver die
        and never ceding.
        """
        return Action(
            prompt.kind,
            "send",
            {
                "side": side,
                "player_id": self.rng.choice(options.for_side(side)),
            },
        )

    def _shootout_pick(self, prompt, game, match, side, options) -> Action:
        return Action(
            prompt.kind,
            "",
            {
                "side": side,
                "player_id": self.rng.choice(options.for_side(side)),
            },
        )

    # -- The tie-breaks -------------------------------------------------

    def _profile(self, player_id: str):
        return self.player_catalog.effective_profile(
            self.player_catalog.player_by_id(player_id)
        )

    def _best_offense(self, player_ids) -> str:
        """The highest offensive skill; the first of them on a tie."""
        return min(
            player_ids,
            key=lambda player_id: -self._profile(player_id).offense,
        )

    def _nearest(self, match: MatchState, player_ids, skill: str) -> str:
        """The nearest to the ball, then the higher skill of `skill`."""

        def sort_key(player_id: str) -> tuple[int, int]:
            profile = self._profile(player_id)
            value = profile.offense if skill == "offense" else profile.defense
            return (match.distance_to_ball(player_id), -value)

        return min(player_ids, key=sort_key)

    @staticmethod
    def _railed_or_max(options, offered):
        return options.railed if options.railed is not None else max(offered)

    def _injured_swap(
        self,
        match: MatchState,
        side: TeamSide,
        options: Optional[CoachingHubOptions] = None,
    ) -> Optional[tuple[str, str]]:
        """
        (player going off, player coming on) for the first injured
        player on the field with a bench to draw on, or None. Read
        off the hub's own lists where the hub is open, and off the
        position where the window is only being offered.
        """
        injured = match.injured_field_players(side)
        if options is not None:
            injured = [pid for pid in injured if pid in options.outgoing_ids]
            pool = list(options.incoming_ids)
        else:
            pool = match.substitution_pool(side)
        if not injured or not pool:
            return None
        outgoing_player_id = injured[0]
        return (
            outgoing_player_id,
            self.closest_role_replacement(outgoing_player_id, pool),
        )

    def _kickoff_cover(
        self,
        match: MatchState,
        side: TeamSide,
        options: CoachingHubOptions,
    ) -> Optional[tuple[str, int]]:
        """
        The nearest midfielder and the kickoff space, as a reposition
        the hub offers -- or None where nobody is assigned to midfield,
        which is not a state a basic shape produces (every one puts
        at least two cards there).
        """
        setup = match.setup_for_side(side)
        kickoff_index = match.kickoff_space_for(side)
        kickoff_flat = match.board.flat_index(Zone.MIDFIELD, kickoff_index)

        def distance(player_id: str) -> int:
            position = match.board.meeple_position(player_id)
            if position is None:
                return 10**6
            return abs(match.board.flat_index(*position) - kickoff_flat)

        candidates = [
            option.player_id
            for option in options.repositions
            if setup.assigned_zone(option.player_id) == Zone.MIDFIELD
            and any(
                space.space_index == kickoff_index for space in option.spaces
            )
        ]
        if not candidates:
            return None
        return min(candidates, key=distance), kickoff_index

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

    #: One branch per kind Dinky can be asked. A kind with no row is
    #: one the AI is never asked (a roll, the tutorial's Continue, the
    #: finished game), and `choose` raises on it rather than guessing.
    ANSWERS = {
        PromptKind.BALL_HANDLER_SELECTION: _ball_handler,
        PromptKind.PLAYER_ACTION: _turn_action,
        PromptKind.MANEUVER_CHALLENGE: _challenger,
        PromptKind.MANEUVER_ACTION: _maneuver_pick,
        PromptKind.LOW_PASS_CHOICE: _low_pass,
        PromptKind.HIGH_PASS_CHOICE: _longest_reaching_pass,
        PromptKind.SETUP_PASS_CHOICE: _longest_reaching_pass,
        PromptKind.SETUP_PASS_PUSH_BACK: _farthest,
        PromptKind.DRIBBLE_ADVANCE_CHOICE: _farthest,
        PromptKind.DRIBBLE_BURST_CHOICE: _farthest,
        PromptKind.SPEED_DELTA_CHOICE: _speed,
        PromptKind.SET_UP_ATTEMPT: _take_the_shot,
        PromptKind.SHOOTER_CHOICE: _shooter,
        PromptKind.SMOOTH: _let_it_pass,
        PromptKind.MIND_PULL: _let_it_pass,
        # Dinky never rearranges (the Coaching Choice's reading), so
        # it neither steps Glompex in nor flies Zenith (Law 21).
        PromptKind.JOIN_THE_BALL: _let_it_pass,
        PromptKind.FLY: _let_it_pass,
        PromptKind.LOOSE_BALL_PICK: _loose_ball,
        PromptKind.RUN_BACK_PLAYER: _run_back_player,
        PromptKind.RUN_BACK_SPACE: _run_back_space,
        PromptKind.BALL_RECOVERY: _pick_the_ball_up,
        PromptKind.COACHING_OFFER: _coaching_offer,
        PromptKind.COACHING_HUB: _coaching_hub,
        PromptKind.HALFTIME_EXTRA_TOKEN: _halftime_token,
        PromptKind.SHOOTOUT_ORDER: _shootout_order,
        PromptKind.SHOOTOUT_PICK: _shootout_pick,
    }


def build_ai_strategies(
    player_catalog: PlayerCatalog,
    maneuver_catalog: ManeuverCatalog,
) -> dict[AIOpponent, AIStrategy]:
    return {
        AIOpponent.DINKY: DinkyAI(player_catalog, maneuver_catalog),
    }

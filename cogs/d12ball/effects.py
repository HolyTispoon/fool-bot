"""
What each maneuver does when it wins, one banner per card.

Low Pass, Dribble Advance, High Pass, the loose ball a pass can leave,
Deflect, Steal, Pressure, ball-speed manipulation, and the own goal a
Pressure can risk.
"""

import asyncio
import discord
import random
import time
from typing import Optional

from d12ball.engine import IgnitedRoll, RulesEngine
from d12ball.flow.effects import (
    dribble_advance_step,
    dribble_burst_step,
    low_pass_step,
    steal_step,
)
from d12ball.prompts import loose_ball_pick_prompt
from d12ball.components import (
    EVENT_OWN_GOAL_ROLL,
    MIND_PULL_SUCCESS_FACES,
    MIND_PULL_TOKEN_COST,
    MIN_HIGH_PASS_DISTANCE,
    MatchState,
    PlayerDefinition,
    PlayerRole,
    SETUP_PASS_CLOCK_COST,
    TeamSide,
)
from d12ball.game import (
    D12BallGame,
    Team,
    team_display_name,
)
from d12ball.render import (
    TEAM_COLORS,
    render_mind_pull_die,
    render_own_goal_dice,
)
from gamesaves.d12ball.storage import save_games
from cogs.d12ball_helpers import (
    HIGH_PASS_CONTEST_HEADLINE,
    ball_location_line,
    contest_noun,
    format_goal_time,
    format_player_with_team,
    format_team_side_label,
    send_new_prompt,
)
from cogs.d12ball_views import (
    DribbleAdvanceChoiceView,
    MindPullView,
    DribbleBurstChoiceView,
    HighPassChoiceView,
    LooseBallChoiceView,
    LooseBallSkillTestView,
    LowPassChoiceView,
    OwnGoalRollView,
    ScoreAttemptView,
    SetUpAttemptChoiceView,
    SetupPassChoiceView,
    SetupPassPushBackView,
    ShooterChoiceView,
    SpeedDeltaChoiceView,
)


class ManeuverEffectsMixin:
    """
    What each maneuver does when it wins, one banner per card.
    """

    # -- Low Pass --------------------------------------------------



    async def resolve_skilled_pass(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        Skilled Pass is a Low Pass with the nearest-each-way rule
        taken off, a space more reach, and the speed bonus tripled:
        **any** teammate within `SKILLED_PASS_REACH` rather than the
        nearest each way within two, and +3 instead of +1. Every other
        thing about it -- the receiver pick out of a stack, the
        passer's step forward across a shared space, the Winger's
        set-up -- is a Low Pass's, which is why the two share one
        function.
        """
        await self.resolve_low_pass(
            interaction, game, match, key="skilled_pass",
        )

    async def resolve_low_pass(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        key: str = "low_pass",
        free: bool = False,
    ) -> None:
        """
        `free` marks the unopposed Low Pass **Skilled Pass's cost**
        hands the defense: it is not this side's maneuver, so it
        charges no further clock and cannot be a Skilled Pass.
        """
        candidates = self.engine.pass_candidates(match, key)

        if not candidates:
            # A Low Pass has to reach a different player, so a handler
            # with no teammate within two spaces has won the maneuver
            # and has nowhere to put the ball. The ball goes a space
            # forward and is loose, and its speed still rises by 1
            # (2026-08-07) -- the maneuver's speed bonus doesn't depend
            # on the pass finding anyone.
            offense_side = match.ball.possession
            actual_distance = match.move_ball_relative(offense_side, 1)
            match.ball.speed = min(
                12, match.ball.speed + self.engine.pass_speed_bonus(key)
            )
            self.persist(game, match)

            # Nothing to move onto at the far end of the field: the
            # ball is loose where it already is.
            movement_note = (
                "the ball rolls a space forward"
                if actual_distance
                else "the ball stays where it is"
            )
            # No refresh here: begin_loose_ball draws this same board
            # under its own announcement and brings the persistent
            # message in line with it, so one here would be a second
            # write of an identical board (see "Discord's rate limits"
            # in docs/design/rate-limits.md).
            await self.begin_loose_ball(
                interaction,
                game,
                match,
                distance_moved=1,
                lead_in=(
                    f"**{self.engine.maneuver_name(key)}:** there is "
                    + (
                        "nobody on the field to receive it"
                        if key == "skilled_pass"
                        else "no teammate within two spaces to receive it"
                    )
                    + ", and a pass can't be played to the passer -- "
                    f"{movement_note}. "
                    f"Ball speed is now {match.ball.speed}."
                ),
                # No headline of its own: the ball rolls a space
                # forward and may well roll onto somebody, so what to
                # call it is a question about the space it stopped on
                # rather than about the pass that failed. It used to
                # assert an empty space here and say each side could
                # send -- which was wrong the moment it landed on a
                # defender.
            )
            return

        if self.engine.side_controlled_by_ai(game, match, "offense"):
            strategy = self.engine.get_ai_strategy(game)
            distance = strategy.choose_low_pass(match, candidates)
            await self.apply_low_pass(
                interaction,
                game,
                match,
                distance,
                receiver_id=strategy.choose_low_pass_receiver(
                    match, self.engine.low_pass_receivers(match, distance),
                ),
                key=key,
                free=free,
            )
            return

        mention = format_player_with_team(
            game,
            self.engine.possession_player_number(game, match),
            self.team_emojis,
            mention=True,
        )
        # Over the field: every destination on the menu is counted
        # from where the ball is standing and named by a space code,
        # and who is standing on it decides how it is won. See
        # `send_field_prompt`, which the other four distance prompts
        # share.
        await self.send_field_prompt(
            interaction,
            game,
            match,
            f"{mention}, choose your {self.engine.maneuver_name(key)}:",
            LowPassChoiceView(self, game.game_id, key=key, free=free),
        )

    async def apply_low_pass(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        distance: int,
        receiver_id: Optional[str] = None,
        key: str = "low_pass",
        free: bool = False,
    ) -> None:
        """
        The Discord half of a won Low Pass: run the step, save what it
        did, then post and dispatch what it handed back.

        **The persist is not optional, and it is before the
        dispatch.** `low_pass_step` no longer saves itself -- a step
        mutates and returns, and the caller writes it down (principle
        9 in CLAUDE.md) -- while the spine underneath is still the
        cog's, and a spine step ending in a prompt hands the turn to a
        click that reloads the match out of the save file. Drop this
        line and the pass's own events are gone by the next
        interaction, which is the bug principle 9 exists to fix,
        reintroduced by the move meant to fix it. It is the transition
        rule through Phase 5; Phase 6 collapses it into the driver.

        The wrapper used to rely on `send_low_pass` having saved for
        it, which is why this is an added line rather than a moved
        one.
        """
        result = low_pass_step(
            self.engine,
            match,
            distance,
            receiver_id=receiver_id,
            key=key,
            free=free,
        )
        self.persist(game, match)
        await self.dispatch_step_result(interaction, game, match, result)

    # -- Dribble Advance ---------------------------------------------

    async def resolve_dribble_advance(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        # Role ability -- Playmaker: may advance 2 spaces instead of
        # the usual 1. Everyone else has no choice to make here, so
        # they skip straight to applying the fixed 1-space advance.
        handler = self.engine.get_player_definition(match.active_player_id)
        if handler.role != PlayerRole.PLAYMAKER:
            await self.apply_dribble_advance(interaction, game, match, 1)
            return

        if self.engine.side_controlled_by_ai(game, match, "offense"):
            distance = self.engine.get_ai_strategy(
                game
            ).choose_dribble_advance_distance(match)
            await self.apply_dribble_advance(
                interaction, game, match, distance
            )
            return

        mention = format_player_with_team(
            game,
            self.engine.possession_player_number(game, match),
            self.team_emojis,
            mention=True,
        )
        # 1 or 2 is a question about the two spaces ahead of the
        # handler and who is standing on them, which is why the buttons
        # name the destinations and why the prompt now carries the
        # field they are read off -- see `send_field_prompt`.
        await self.send_field_prompt(
            interaction,
            game,
            match,
            f"{mention}, choose your Dribble Advance distance "
            "(Playmaker ability):",
            DribbleAdvanceChoiceView(self, game.game_id),
        )

    async def apply_dribble_advance(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        distance: int,
    ) -> None:
        """
        Run the advance and hand over to the speed choice every
        dribble ends with.

        Four lines over `dribble_advance_step`, which is where the
        move, the wording and a beaten Clear's cost live -- see
        `apply_low_pass` for the shape and principle 9 in CLAUDE.md
        for why the save is here rather than inside the step.
        """
        result = dribble_advance_step(self.engine, game, match, distance)
        self.persist(game, match)
        await self.dispatch_step_result(interaction, game, match, result)

    async def resolve_dribble_burst(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        Dribble Burst: the handler carries the ball **up to
        `DRIBBLE_BURST_MAX_DISTANCE` spaces forward**, defenders no
        obstacle, at a token a space -- then manipulates ball speed up
        to their offensive skill, exactly as a Dribble Advance does.

        **The distance is the coach's, and it used to be the board's**
        (the author, 2026-08-26). The run was to the last space of the
        goal they attack, which is no choice at all: there was one
        answer and the card simply charged for it. Bounded at 4 the
        pick is a real one, because the exhaustion is a token a space
        -- the first time a maneuver has charged by distance, every
        other per-space charge in the game being a walk somebody was
        sent on. So this is now shaped like a Playmaker's Dribble
        Advance: the AI answers for itself, a human gets a menu, and
        `apply_dribble_burst` is what both of them land in.

        **The Playmaker still pays one token fewer** (the author,
        2026-08-19) rather than going back to the extra space their
        sentence names. That ruling was made when there was no
        distance to add to; it stands with the run bounded, so the
        Playmaker's ability remains the only one that reads
        differently on the two cards of a rank.
        """
        distances = self.engine.dribble_burst_distances(match)

        # From the last space of the field there is nothing to ask --
        # a burst that moves nowhere costs nothing and still gets its
        # speed choice. Applying 0 rather than putting up an empty menu
        # is the same call `resolve_high_pass` makes for a pass with no
        # distance left in it.
        if not distances:
            await self.apply_dribble_burst(interaction, game, match, 0)
            return

        if self.engine.side_controlled_by_ai(game, match, "offense"):
            distance = self.engine.get_ai_strategy(
                game
            ).choose_dribble_burst_distance(match, distances)
            await self.apply_dribble_burst(interaction, game, match, distance)
            return

        mention = format_player_with_team(
            game,
            self.engine.possession_player_number(game, match),
            self.team_emojis,
            mention=True,
        )
        # A run of up to four spaces at a token each: how far is worth
        # paying for depends on where the run ends and who is standing
        # between here and there -- see `send_field_prompt`.
        await self.send_field_prompt(
            interaction,
            game,
            match,
            f"{mention}, choose your Dribble Burst distance "
            "(1 exhaustion token a space):",
            DribbleBurstChoiceView(self, game.game_id),
        )

    async def apply_dribble_burst(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        distance: int,
    ) -> None:
        """
        Run the burst, charge a token a space, and hand over to the
        speed choice every dribble ends with.

        The same four lines as `apply_dribble_advance` over
        `dribble_burst_step`, which is where the run, its exhaustion
        and the Playmaker's discount live.
        """
        result = dribble_burst_step(self.engine, game, match, distance)
        self.persist(game, match)
        await self.dispatch_step_result(interaction, game, match, result)

    # -- High Pass -----------------------------------------------------



    async def resolve_high_pass(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        # There is nothing to choose when even the shortest pass runs
        # out of field -- 2, 3 and 4 all land on the space closest to
        # the goal, so the pass is an overshoot before anyone picks
        # anything (2026-08-10). The prompt is skipped rather than
        # answered: asking would be putting one answer up three times,
        # and a Fullback's 4 is no less moot than the 2. The distance
        # handed on is the minimum, which is what the clock charges
        # once the clamp has had its say.
        distances = self.engine.high_pass_distance_options(match)
        if not distances:
            await self.apply_high_pass(
                interaction, game, match, MIN_HIGH_PASS_DISTANCE,
            )
            return

        if self.engine.side_controlled_by_ai(game, match, "offense"):
            distance = self.engine.get_ai_strategy(game).choose_high_pass_distance(
                match, distances,
            )
            await self.apply_high_pass(interaction, game, match, distance)
            return

        mention = format_player_with_team(
            game,
            self.engine.possession_player_number(game, match),
            self.team_emojis,
            mention=True,
        )
        # How far to throw is a question about which teammate the pass
        # reaches, how much field is left, and who is waiting where it
        # lands -- a long pass is contested there. See
        # `send_field_prompt`.
        await self.send_field_prompt(
            interaction,
            game,
            match,
            f"{mention}, choose your High Pass distance:",
            HighPassChoiceView(self, game.game_id),
        )

    async def resolve_setup_pass(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        Setup Pass, the advanced High Pass: **adjust ball speed up to
        the passer's offensive skill, and then** set up a scoring
        opportunity at 0, 1 or 3 spaces, with the speed benefit
        counting toward the shot.

        The order is the card's and it is the reason this is two
        prompts rather than one. A speed choice has always been the
        *last* human step of an effect, leading straight into
        `finish_maneuver_resolution`; here it is the first, so what
        comes after it is recorded as an effect continuation and picked
        up by `continue_effect`. A restart between the two comes back
        to whichever prompt is up, and the continuation is persisted so
        the pass is not lost with it.
        """
        match.pending_effect_continuation = {"kind": "setup_pass_shot"}
        self.persist(game, match)

        passer = self.engine.get_player_definition(match.active_player_id)
        await self.offer_speed_choice(
            interaction,
            game,
            match,
            player_id=match.active_player_id,
            skill_type="offense",
            distance_moved=SETUP_PASS_CLOCK_COST,
            lead_in=(
                "**Setup Pass:** "
                f"{self.player_label(match, passer)} "
                "sets the ball's speed before picking out the pass."
            ),
        )

    async def offer_setup_pass_distance(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        The second half of Setup Pass: 0, 1 or 3 spaces, and a teammate
        standing where it lands takes a scoring opportunity.

        **Every distance that fits on the field is offered**, whether
        or not anybody of the passing side is standing there -- see
        `RulesEngine.setup_pass_distances`. A pass that lands on nobody
        is a real outcome (the ball settles there like a Deflect's, so
        it is loose or the other side's), not a pass the menu should
        refuse.

        **0 is the exception**: it means a teammate sharing the
        passer's own space, since a passer never receives their own
        pass (2026-08-12), so it is on the menu only while somebody
        else is standing there.
        """
        distances = self.engine.setup_pass_distances(match)

        if not distances:
            # **Setup Pass cannot overshoot**, so the one way it goes
            # out is having nowhere to throw it at all: the passer on
            # the last space of the field, with no teammate beside
            # them. That is the existing out-of-bounds outcome -- a new
            # play, both sides reset, the gaining side sends somebody
            # to pick it up.
            await self.apply_setup_pass_out(interaction, game, match)
            return

        if self.engine.side_controlled_by_ai(game, match, "offense"):
            # The same question a High Pass asks, so the same answer:
            # the longest distance that actually reaches a teammate,
            # and otherwise the longest available. Maximizing outright
            # would have Dinky pick the ball out into empty space and
            # give it away, which is exactly why that policy was
            # written for the High Pass (2026-08-18).
            distance = self.engine.get_ai_strategy(game).choose_high_pass_distance(
                match, distances,
            )
            await self.apply_setup_pass(
                interaction, game, match, distance,
            )
            return

        mention = format_player_with_team(
            game,
            self.engine.possession_player_number(game, match),
            self.team_emojis,
            mention=True,
        )
        # The same question the High Pass asks and the same picture
        # under it -- see `send_field_prompt`. It matters a little more
        # here: this card offers every distance that fits whether or
        # not anybody is standing there, so who *is* standing there is
        # the whole of what separates a set-up from picking the ball
        # out into space.
        await self.send_field_prompt(
            interaction,
            game,
            match,
            f"{mention}, choose where your **Setup Pass** lands:",
            SetupPassChoiceView(self, game.game_id),
        )

    async def apply_setup_pass(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        distance: int,
    ) -> None:
        offense_side = match.ball.possession
        # Applied, so the continuation is spent -- see `continue_effect`
        # for why it survived until now.
        match.pending_effect_continuation = None
        actual_distance = match.move_ball_relative(offense_side, distance)
        receivers = self.engine.high_pass_receiver_candidates(
            match, offense_side,
        )
        if not receivers:
            if actual_distance == 0:
                # Only reachable from a stale click: 0 is offered only
                # while a teammate shares the passer's space, and every
                # other distance is offered only where it fits on the
                # field, so nothing legal clamps to a standing still.
                # A ball that never left the passer is the High Pass's
                # own 0-space case -- nowhere to throw it and nobody to
                # throw it to -- so it goes out rather than settling
                # under the passer's own feet.
                await self.apply_setup_pass_out(interaction, game, match)
                return

            # **A pass that lands on nobody is still a pass**
            # (2026-08-25). The card is a set-up, but missing the
            # set-up does not un-throw the ball: it settles exactly
            # where a Deflect's does, so occupancy is what decides it
            # -- loose on an empty space, the other side's outright
            # where only they are standing. Refusing
            # the distance instead is what used to make this the only
            # pass in the game that could not be thrown badly.
            #
            # No refresh_match_image first: begin_loose_ball posts the
            # board with its announcement, and refreshing here would
            # write the same board twice (see "Discord's rate limits").
            space_word = "space" if actual_distance == 1 else "spaces"
            await self.begin_loose_ball(
                interaction,
                game,
                match,
                SETUP_PASS_CLOCK_COST,
                lead_in=(
                    "**Setup Pass:** the ball is picked out "
                    f"{actual_distance} {space_word} forward, with nobody "
                    "there to set up."
                ),
            )
            return

        receiver_id = receivers[0]
        match.set_ball_carrier(receiver_id)
        self.persist(game, match)

        receiver = self.engine.get_player_definition(receiver_id)
        space_word = "space" if actual_distance == 1 else "spaces"
        movement = (
            "goes to a teammate in the same space"
            if distance == 0
            else f"moves {actual_distance} {space_word} forward"
        )
        await self.refresh_match_image(interaction, game)
        await self.offer_scoring_attempt_choice(
            interaction,
            game,
            match,
            shooter_id=receiver_id,
            distance_moved=SETUP_PASS_CLOCK_COST,
            lead_in=(
                f"**Setup Pass:** the ball {movement} to "
                f"{self.player_label(match, receiver)} "
                f"-- a scoring opportunity! Ball speed is {match.ball.speed}."
            ),
        )

    async def apply_setup_pass_out(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        **Setup Pass cannot overshoot**, so the only way it runs out of
        play is having nowhere to throw it at all: the passer on the
        very last space of the field -- the one position from which
        even 1 space runs off the end -- with no teammate beside them
        to take it at 0. Then the other team gains possession: a new
        play, both sides reset, and the gaining side sends the nearest
        player to fetch the ball -- the out-of-bounds outcome the game
        already has.

        Any other landing space is a pass that happened; see
        `apply_setup_pass`, which leaves the ball lying there.

        That makes this a **fourth** `new_play=True` call site, where
        the other three are the score attempt, a conceded own goal and
        the out-of-bounds loose ball. It is one for the same reason
        those are: the ball went dead rather than being taken off
        anybody.
        """
        match.pending_effect_continuation = None
        match.ball.possession = match.defending_side()
        match.ball.speed = 1
        match.clear_ball_carrier()
        match.pending_ball_recovery = True
        self.persist(game, match)

        gaining = match.setup_for_side(match.ball.possession)
        await self.begin_run_back(
            interaction,
            game,
            match,
            new_play=True,
            distance_moved=SETUP_PASS_CLOCK_COST,
            lead_in=(
                "**Setup Pass:** there is nobody to pick the ball out to, "
                "so it runs out of play. "
                f"{format_team_side_label(gaining)} gain possession."
            ),
        )

    def throw_high_pass(
        self,
        game: D12BallGame,
        match: MatchState,
        offense_side: TeamSide,
        distance: int,
        handler: PlayerDefinition,
    ) -> tuple[bool, int, str]:
        """
        Put the ball in the air and say what that looked like.

        Returns whether the throw overshot, how far the ball actually
        travelled, and the line every branch of the pass opens with.
        The overshoot is read **before** the ball moves, the same way
        Deflect reads its own and by the same test, so a pass that
        could not move the ball at all is an overshoot like any other
        -- which is the whole reason this is one function and not the
        caller's first three statements.
        """
        # Role ability -- Fullback: can choose to pass up to 4 spaces
        # instead of the usual 2-3 max (see HighPassChoiceView).
        fullback_bonus = handler.role == PlayerRole.FULLBACK and distance == 4

        overshot = match.high_pass_overshoots(offense_side, distance)

        actual_distance = match.move_ball_relative(offense_side, distance)
        self.persist(game, match)

        ability_note = " (Fullback ability)" if fullback_bonus else ""
        if actual_distance:
            space_word = "space" if actual_distance == 1 else "spaces"
            content = (
                f"**High Pass:** the ball moves {actual_distance} "
                f"{space_word} forward{ability_note}."
            )
        else:
            # Thrown from the final space, so the clamp leaves the ball
            # exactly where it was. Worth saying in words rather than
            # as "moves 0 spaces forward", which reads as a bug -- and
            # a coach sees it now that the passer cannot shoot off it.
            content = (
                "**High Pass:** the ball is thrown up from the last space "
                "and comes straight back down on it."
            )

        return overshot, actual_distance, content

    async def complete_high_pass_reception(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        receiver_id: str,
        distance_moved: int,
        lead_in: str,
    ) -> None:
        """
        A pass that was caught and settles there: the receiver carries
        it, and the maneuver ends without a contest.

        Two branches reach this -- a 2-space pass out of shooting
        range, and a pass whose contest a beaten Intercept called off.
        They differ in what they say and in nothing else.
        """
        match.set_ball_carrier(receiver_id)
        self.persist(game, match)
        await self.refresh_match_image(interaction, game)
        await self.finish_maneuver_resolution(
            interaction, game, match, distance_moved=distance_moved,
            lead_in=lead_in,
        )

    async def apply_high_pass(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        distance: int,
    ) -> None:
        offense_side = match.ball.possession
        handler = self.engine.get_player_definition(match.active_player_id)

        overshot, actual_distance, content = self.throw_high_pass(
            game, match, offense_side, distance, handler,
        )

        # High Pass's own cost is a flat 2 space minutes regardless of
        # distance (2026-08-16) -- the one maneuver that isn't 1. Kept
        # apart from `actual_distance`, which is what the pass actually
        # did and what the result says.
        distance_moved = 2

        # Who this pass reached, read once now the ball has landed and
        # asked by every branch below -- the passer is not among them,
        # whatever the distance. See high_pass_receiver_candidates.
        receiver_candidates = self.engine.high_pass_receiver_candidates(
            match, offense_side,
        )

        # An overshoot sets up a scoring opportunity whatever distance
        # was asked for (2026-08-10), on the space closest to the goal
        # -- which is where the clamp has just put the ball. The shot
        # is always legal there, as deep into the offense's own
        # shooting range as the field goes, so no range check: it could
        # never fail here, and a branch that cannot be taken reads as
        # if it could. Checked ahead of the ordinary 2-space set-up
        # below, which it subsumes -- the same shot is offered, but
        # with the modifier the other way round and a contest behind
        # it.
        if overshot and receiver_candidates:
            await self.offer_overshoot_set_up(
                interaction,
                game,
                match,
                shooter_id=receiver_candidates[0],
                distance_moved=distance_moved,
                lead_in=content,
            )
            return
        # Nobody the pass could reach on the landing space leaves
        # nothing to set up, so an overshoot falls through to the
        # ordinary paths below: a loose ball, a clean turnover, or --
        # the case the passer exclusion opened (2026-08-12) -- the
        # passer keeping a ball that never left them.

        # A pass of 2 is received cleanly: no contest at all
        # (2026-08-07), and it may set up a scoring opportunity for
        # whoever it lands on -- unlike the old fixed-2 High Pass,
        # this no longer requires overshooting the field. A longer
        # pass never offers it, whether or not it happens to overshoot.
        #
        # A set-up's shot is an ordinary score attempt and obeys the
        # same rule about where a shot may be taken from: what the
        # set-up buys is the shot out of turn, not a shot from
        # anywhere. Out of range the pass is still received, which the
        # branch below settles -- the range rule takes away the shot,
        # not the catch.
        setup_candidates = []
        if distance == 2 and match.can_attempt_score(offense_side):
            setup_candidates = receiver_candidates

        if setup_candidates:
            # Received, so the receiver carries it -- set before the
            # set-up is offered, because declining resolves this as an
            # ordinary completed pass and the carrier has to survive
            # that. Taking the shot makes it moot: a goal or a miss is
            # a new play, which clears the carrier.
            match.set_ball_carrier(setup_candidates[0])
            self.persist(game, match)
            await self.refresh_match_image(interaction, game)
            await self.offer_scoring_attempt_choice(
                interaction,
                game,
                match,
                shooter_id=setup_candidates[0],
                distance_moved=distance_moved,
                lead_in=f"{content} That reaches a teammate -- a scoring "
                "opportunity!",
            )
            return

        # No scoring-opportunity option (or the requested distance
        # wasn't a 2). If the pass reached nobody, this isn't the High
        # Pass "receiver must win a skill test" contest at all -- it's
        # a plain loose ball, exactly like any other maneuver that
        # overshoots into empty territory.

        # A 2-space pass that found its receiver but not shooting range
        # is just a pass: it was received cleanly, and the only thing
        # the range rule takes away is the shot. Falling through would
        # hand it to the long-pass contest below, which a pass of 2 has
        # never had to win.
        if distance == 2 and receiver_candidates:
            # Caught cleanly, just out of shooting range -- the range
            # rule takes away the shot, not the catch, so the receiver
            # still carries it.
            await self.complete_high_pass_reception(
                interaction, game, match, receiver_candidates[0],
                distance_moved, content,
            )
            return

        if not receiver_candidates:
            # **A passer never receives their own pass, and since
            # 2026-08-24 that is no longer a free ride.** The exclusion
            # above can only bite when the field clamped the throw to 0
            # spaces -- a High Pass moves the ball, not the handler, so
            # that is the only way the passer is still standing where
            # it lands. With nobody else there either, this is a throw
            # with nowhere to go: there was no field left to put it on
            # and no teammate to put it to, so it goes out exactly as a
            # Setup Pass with no legal destination does, rather than
            # quietly staying with the passer. `actual_distance` (not
            # `distance`) is the test, because that's what tells the
            # ball genuinely didn't move from a real empty destination
            # elsewhere on the field -- which stays an ordinary loose
            # ball below.
            if actual_distance == 0:
                await self.apply_high_pass_out(
                    interaction, game, match,
                    distance_moved=distance_moved, lead_in=content,
                )
                return
            await self.refresh_match_image(interaction, game)
            await self.finish_maneuver_resolution(
                interaction, game, match, distance_moved=distance_moved,
                lead_in=content,
            )
            return

        # **Intercept's cost**: beaten by a High Pass, the reception is
        # not contested -- the receiver simply keeps it. It is the one
        # of the six costs that can be inert, and this is the only
        # branch it is not: a pass of 2, an overshoot's set-up and a
        # pass reaching nobody have all already returned above, and
        # none of them had a contest to skip.
        if self.engine.advanced_cost(match, "high_pass") == "intercept":
            receiver = self.engine.get_player_definition(
                receiver_candidates[0]
            )
            await self.complete_high_pass_reception(
                interaction, game, match, receiver_candidates[0],
                distance_moved,
                lead_in=(
                    f"{content}\n\n**Intercept** was beaten -- the "
                    "reception is not contested, and "
                    f"{self.player_label(match, receiver)} "
                    "keeps the ball."
                ),
            )
            return

        # A teammate is standing right where the pass landed, and the
        # pass went 3 or more -- a distance of 2 with a teammate there
        # took the set-up branch above, since both branches ask
        # high_pass_receiver_candidates the same question. A long
        # High Pass still forces a skill test to keep the ball, unlike
        # any other maneuver.
        await self.refresh_match_image(interaction, game)
        await self.begin_high_pass_contest(
            interaction, game, match, distance_moved, lead_in=content,
        )

    async def apply_high_pass_out(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        distance_moved: int,
        lead_in: str,
    ) -> None:
        """
        A High Pass thrown with nowhere left to put it: the handler is
        already on the space closest to the opponents' goal, and
        nobody shares it with them. That is the one position a High
        Pass can be thrown from without moving the ball at all, so
        there is no field left to overshoot onto and no teammate to
        land beside -- the same dead end Setup Pass reaches whenever
        none of its own distances find anybody (`apply_setup_pass_out`,
        which this mirrors). The other team gains possession, a new
        play, and the gaining side sends the nearest player to fetch
        it -- the out-of-bounds outcome the game already has, rather
        than the passer quietly keeping a ball that never left them.
        """
        match.ball.possession = match.defending_side()
        match.ball.speed = 1
        match.clear_ball_carrier()
        match.pending_ball_recovery = True
        self.persist(game, match)

        gaining = match.setup_for_side(match.ball.possession)
        await self.begin_run_back(
            interaction,
            game,
            match,
            new_play=True,
            distance_moved=distance_moved,
            lead_in=(
                f"{lead_in} There is nowhere left to throw it and nobody "
                "to receive it there -- the ball goes out of play. "
                f"{format_team_side_label(gaining)} gain possession."
            ),
        )

    async def offer_overshoot_set_up(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        *,
        shooter_id: str,
        distance_moved: int,
        lead_in: str,
    ) -> None:
        """
        The scoring opportunity a High Pass that ran out of field sets
        up (2026-08-10) -- see "High Pass" in the living rules.

        The pass arrived faster than the receiver could settle it, so
        `pending_high_pass_overshoot` turns the ball speed modifier
        around for everything the overshoot leads to: this shot, and
        the long-pass contest behind it. It is set before either is
        offered, and cleared with the rest of the turn by
        reset_maneuver.

        **The two are one choice, not an offer and a fallback.** An
        overshoot is a shot at a disadvantage or a contest to keep the
        ball, both paying the modifier, so declining always lands in
        the contest -- there is no distance here that resolves as a
        settled pass. A distance of 2 could only overshoot from a
        position where no distance was ever offered (see
        resolve_high_pass), so the ordinary "a pass of 2 is received,
        full stop" rule and this one never meet.
        """
        match.pending_high_pass_overshoot = True
        # Received, so the receiver carries it -- set before the
        # set-up is offered, for the same reason the ordinary 2-space
        # set-up does it: declining can resolve this as a completed
        # pass, and the carrier has to survive that.
        match.set_ball_carrier(shooter_id)
        self.persist(game, match)

        penalty = match.ball_speed_modifier()
        speed_note = (
            " The ball comes in too fast to settle -- the ball speed "
            f"modifier counts **against** what follows ({penalty})."
            if penalty
            else ""
        )
        await self.refresh_match_image(interaction, game)
        await self.offer_scoring_attempt_choice(
            interaction,
            game,
            match,
            shooter_id=shooter_id,
            distance_moved=distance_moved,
            contest_on_decline=True,
            lead_in=(
                f"{lead_in} That overshoots the field -- a scoring "
                f"opportunity!{speed_note}"
            ),
        )

    async def begin_high_pass_contest(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        distance_moved: int,
        lead_in: str = "",
    ) -> None:
        """
        The long-pass contest: the receiver standing where the pass
        landed still has to win a skill test to keep the ball.

        Since 2026-08-18 this is a loose ball and nothing else -- the
        receiver contests because they are standing on the ball, which
        is the ordinary rule, and so does a defender sharing the space.
        The one thing still peculiar to a High Pass is the ball speed
        modifier, which `is_high_pass` carries. So there is nothing here
        but the flag: the contestants are read off the position by
        loose_ball_candidates, and the passer is struck out of the
        offense's pool by MatchState.loose_ball_occupants.

        Two paths reach it, and callers of both have already found the
        receiver on the landing space: an unclamped pass of 3 or 4, and
        an overshoot whose set-up the coach declined (2026-08-10). The
        second still carries `pending_high_pass_overshoot`, so the
        contest is rolled with the ball speed modifier against the
        receiver rather than for them -- the same sign the declined
        shot would have paid.
        """
        await self.begin_loose_ball(
            interaction,
            game,
            match,
            distance_moved,
            lead_in=lead_in,
            headline=HIGH_PASS_CONTEST_HEADLINE,
            is_high_pass=True,
        )

    async def offer_scoring_attempt_choice(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        *,
        shooter_id: str,
        distance_moved: int,
        lead_in: str,
        contest_on_decline: bool = False,
    ) -> None:
        """
        Offer the offense a chance to attempt a scoring-opportunity
        shot instead of letting a maneuver resolve normally -- used by
        a High Pass's 2-space pass, a High Pass that overshoots, and a
        Winger's Low Pass.

        Declining nearly always resolves the maneuver as a normal pass;
        a 2-space High Pass stopped forcing a contest instead on
        2026-08-07. `contest_on_decline` is the one exception: an
        overshoot is a shot or a contest, both at the same
        disadvantage, so declining lands in the contest rather than
        settling the ball (2026-08-10). It is passed rather than
        derived because by the time this runs, an overshot pass and an
        ordinary 2-space one have left the match in the same state.
        """
        # **A scoring opportunity is an arrival too**, and one the
        # rules name outright among what a pull pre-empts -- so the
        # offer goes out before the shot is put to anybody.
        if await self.check_for_mind_pull(
            interaction,
            game,
            match,
            {
                "kind": "scoring_attempt",
                "shooter_id": shooter_id,
                "distance_moved": distance_moved,
                "lead_in": lead_in,
                "contest_on_decline": contest_on_decline,
            },
        ):
            return

        if self.engine.side_controlled_by_ai(game, match, "offense"):
            attempt = self.engine.get_ai_strategy(
                game
            ).choose_scoring_opportunity_attempt(match)
            if lead_in:
                await send_new_prompt(interaction, lead_in)
            if attempt:
                await self.start_set_up_shot(
                    interaction, game, match, shooter_id,
                    maneuver_cost=distance_moved,
                )
            else:
                await self.decline_scoring_attempt(
                    interaction, game, match, distance_moved,
                    contest=contest_on_decline,
                )
            return

        shooter = self.engine.get_player_definition(shooter_id)
        prompt_message = await send_new_prompt(
            interaction,
            f"{lead_in}\n\n"
            f"{self.player_label(match, shooter)} can attempt "
            "the scoring opportunity, or let it go:",
            view=SetUpAttemptChoiceView(
                self, game.game_id, shooter_id, distance_moved,
                contest_on_decline=contest_on_decline,
            ),
            allowed_mentions=discord.AllowedMentions(
                users=True, roles=False, everyone=False,
            ),
        )
        game.turn_message_id = prompt_message.id
        save_games(self.games)

    async def decline_scoring_attempt(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        distance_moved: int,
        contest: bool = False,
    ) -> None:
        """
        Let go of a scoring opportunity: the maneuver that offered it
        resolves as it otherwise would have.

        For an overshot High Pass that is the long-pass contest, not a
        settled ball -- the shot and the contest are the two halves of
        one choice. See offer_scoring_attempt_choice.
        """
        if contest:
            await self.begin_high_pass_contest(
                interaction,
                game,
                match,
                distance_moved,
                lead_in="The scoring opportunity is let go -- but the "
                "pass still has to be kept.",
            )
            return
        await self.finish_maneuver_resolution(
            interaction, game, match, distance_moved=distance_moved,
        )



    # -- Loose ball (a pass landing on an empty space) -----------------


    async def check_for_loose_ball(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        distance_moved: int,
        lead_in: str = "",
    ) -> bool:
        """
        The one check every maneuver-effect path runs through, via
        finish_maneuver_resolution: does the possessing team actually
        have a player on the ball's space? If not, this detours into
        the loose ball instead of letting the turn proceed with nobody
        eligible to act -- returns True when it took that detour, so
        the caller stops instead of continuing.

        **There is one detour now, not two.** A ball landing where only
        the *other* side is standing used to be theirs outright: no
        movement, no roll, a clean steal. It is a loose ball like any
        other since 2026-08-18, and the side that lost it may send
        somebody to contest it -- the defender standing there is simply
        a contestant who costs their side nothing. See "The loose ball"
        in docs/living-rules.md.

        A Deflect does not come through here at all: it makes a
        loose ball whoever is standing on the landing space, so its own
        effect calls begin_loose_ball directly rather than answering a
        question whose answer would be "not loose".
        """
        if match.eligible_ball_handlers():
            return False

        await self.begin_loose_ball(
            interaction, game, match, distance_moved, lead_in=lead_in,
        )
        return True






    async def check_for_mind_pull(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        resume: dict,
    ) -> bool:
        """
        **The gate every ball arrival runs through**: did the ball just
        cross an opposing Telekinetic who may pull it in? Returns True
        when it did and the offer has been put, so the caller stops --
        exactly the shape `check_for_loose_ball` has, and for the same
        reason.

        Mind Pull "resolves before the ball settles", so this sits at
        the top of the three functions that settle an arrival:
        `finish_maneuver_resolution` (the tail of every ordinary path,
        receptions included), `begin_loose_ball` (a Deflect, which
        calls it directly, and the High Pass contest, which comes
        through it), and `offer_scoring_attempt_choice` (a set-up).
        Between them they are every one of "a reception, a scoring
        opportunity, a contest, a loose ball".

        A fourth site, `begin_run_back`, gates the same way for a
        turnover that never passed through any of the three -- Steal,
        Intercept, a Defender's pressure steal, and an own goal avoided
        all settle their own turnover and call `begin_run_back`
        directly. Without a gate there, that movement's `last_ball_path`
        would sit unread until run-back had already repositioned
        players, and `mind_pull_candidates` would then be checking who
        a run-back just placed on those spaces rather than who was
        actually standing there when the ball crossed.

        **The path is consumed whether or not anybody may pull.** That
        is what stops the same movement being offered twice when two
        gates run in a row -- `finish_maneuver_resolution` gates and
        then calls `check_for_loose_ball`, which reaches the second
        gate with the path already spent.

        `resume` is the arrival this interrupted, as
        `{"kind": ..., ...}` -- the same shape `pending_injury_resume`
        uses, and for the same reason: a coach may take minutes over
        the offer, and between the interrupt and the answer nothing
        else on the match says what the ball was about to do.
        """
        candidates = self.engine.mind_pull_candidates(game, match)
        # Spent either way, and before the early return: a movement
        # that offered nobody a pull must not offer one at the next
        # arrival point either.
        match.last_ball_path = []
        if not candidates:
            return False

        match.pending_mind_pull = candidates
        match.pending_mind_pull_resume = resume
        self.persist(game, match)

        await self.continue_mind_pull(interaction, game, match)
        return True

    async def continue_mind_pull(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        Put the offer to the next Telekinetic the ball crossed, or --
        when none are left -- do what the arrival this interrupted was
        going to do. **The one exit from the queue**, so a coach who
        declines and a Telekinetic who was never asked leave by the
        same door; this can never be where a turn stops for good.

        **Dinky never pulls**, so an AI side's Telekinetics are skipped
        rather than prompted. Paying a token for a one-in-six steal is
        a judgement call, and Dinky makes none -- the same call as
        never ceding, never declining a challenge and never slipping
        in. In a solo game the ability is the human's alone, which is
        also what keeps this flow free of an AI branch.
        """
        while match.pending_mind_pull:
            player_id = match.pending_mind_pull[0]
            controller = self.engine.controlling_user_id(
                game, match, player_id,
            )
            # Skipped rather than refused: a player who has been
            # injured since the offer was queued cannot pay the token,
            # and an AI's never wanted it.
            if controller is None or player_id in match.injured:
                match.pending_mind_pull.pop(0)
                self.persist(game, match)
                continue

            player = self.engine.get_player_definition(player_id)
            await send_new_prompt(
                interaction,
                f"🔮 **Mind Pull** — the ball crossed "
                f"{self.player_label(match, player)}, who may reach out "
                f"for it: {MIND_PULL_TOKEN_COST} exhaustion token and a "
                f"d12, pulling it in on a "
                f"{'-'.join(str(face) for face in MIND_PULL_SUCCESS_FACES)}.",
                view=MindPullView(self, game.game_id, player_id),
            )
            return

        resume = match.pending_mind_pull_resume
        match.pending_mind_pull_resume = None
        self.persist(game, match)
        await self.dispatch_mind_pull_resume(
            interaction, game, match, resume,
        )

    async def dispatch_mind_pull_resume(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        resume: Optional[dict],
    ) -> None:
        """
        Put the turn back where the pull interrupted it -- the twin of
        `dispatch_injury_resume`, and read the same way: the kind names
        the arrival, and the rest of the dict is the arguments that
        arrival needs.

        An unrecognised kind (or none at all) falls through to the
        ordinary end of a maneuver rather than stranding the turn, the
        same as `continue_effect`'s own fallback.
        """
        resume = resume or {}
        kind = resume.get("kind")

        if kind == "loose_ball":
            await self.begin_loose_ball(
                interaction,
                game,
                match,
                resume.get("distance_moved", 1),
                lead_in=resume.get("lead_in", ""),
                headline=resume.get("headline"),
                is_high_pass=resume.get("is_high_pass", False),
            )
            return

        if kind == "scoring_attempt":
            await self.offer_scoring_attempt_choice(
                interaction,
                game,
                match,
                shooter_id=resume["shooter_id"],
                distance_moved=resume.get("distance_moved", 1),
                lead_in=resume.get("lead_in", ""),
                contest_on_decline=resume.get("contest_on_decline", False),
            )
            return

        if kind == "run_back":
            await self.begin_run_back(
                interaction,
                game,
                match,
                distance_moved=resume.get("distance_moved", 1),
                turnover_occurred=resume.get("turnover_occurred", True),
                new_play=resume.get("new_play", False),
                speed_choice_after=resume.get("speed_choice_after", False),
                speed_reset=resume.get("speed_reset", True),
                lead_in=resume.get("lead_in", ""),
            )
            return

        await self.finish_maneuver_resolution(
            interaction,
            game,
            match,
            distance_moved=resume.get("distance_moved", 1),
            turnover_occurred=resume.get("turnover_occurred", False),
            lead_in=resume.get("lead_in", ""),
        )

    async def run_mind_pull(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        player_id: str,
    ) -> None:
        """
        One Telekinetic's attempt, off the button they were offered:
        pay the token, roll a d12, and either take the ball or hand the
        queue on.

        **The token is paid whether or not the pull lands**, which is
        the rule and is why the charge is above the roll rather than in
        the winning branch.

        **It is not a skill test and owes no injury check** (the
        rules say so outright), so nothing here goes through
        `begin_injury_tests` -- a Telekinetic the token pushes over
        their threshold is Exhausted and simply carries it.
        """
        player = self.engine.get_player_definition(player_id)
        if player_id in match.pending_mind_pull:
            match.pending_mind_pull.remove(player_id)

        # Injured between being queued and answering: they cannot pay
        # the token, and `add_exhaustion` would refuse it silently and
        # hand them a free roll. Skipped rather than refused, the same
        # way `continue_mind_pull` skips them -- this can never be
        # where a turn stops.
        if player_id in match.injured:
            self.persist(game, match)
            await self.continue_mind_pull(interaction, game, match)
            return

        exhaustion_text = self.apply_exhaustion(
            game, match, player_id, MIND_PULL_TOKEN_COST,
        )
        roll = random.randint(1, 12)
        # Volatile is a Fire Demon's and this is a Telekinetic's roll,
        # so nothing ignites here -- asked anyway, through the one
        # funnel, rather than assuming the two can never meet.
        ignite = self.engine.ignite(game, player_id, roll)
        total = roll + ignite.modifier
        pulled = total in MIND_PULL_SUCCESS_FACES

        # The die image draws the natural face, exactly as the injury
        # test's does, so an ignite has to be said in words or the
        # number a coach reads and the verdict they are given would not
        # add up.
        ignite_note = f" ({ignite.detail}, {total})" if ignite.detail else ""
        player_team = match.team_for_player(player_id)
        dice_file = discord.File(
            await asyncio.to_thread(
                render_mind_pull_die,
                roll,
                TEAM_COLORS[player_team],
                team_display_name(player_team),
                player.name,
                pulled,
            ),
            filename="mind_pull_die.png",
        )
        # The offer becomes the die, and what it came to is said in the
        # message after it -- a message's attachments render below its
        # content, so a result written here would be read before the
        # roll that decided it. Same way round as every other roll in
        # the game; see SkillTestView.roll.
        await interaction.edit_original_response(
            content=None,
            attachments=[dice_file],
            view=None,
        )
        # Asked here for the reason the ignite above is asked at all:
        # Volatile is a Fire Demon's and this is a Telekinetic's roll,
        # so this posts nothing today -- and the day a card carries
        # both, the second die is shown here rather than being the one
        # roll in the game that swallows it.
        await self.post_volatile_ignition(
            interaction, match, (player_id, ignite),
        )

        note = "\n".join(filter(None, (
            f"🔮 **Mind Pull** — {self.player_label(match, player)} "
            f"reaches for the ball{ignite_note}.",
            exhaustion_text,
        )))

        if not pulled:
            # The resume is left exactly as it was: the next
            # Telekinetic in the queue is owed the same offer, and the
            # arrival behind them is still the one to fall back to.
            self.persist(game, match)
            await send_new_prompt(
                interaction, f"{note}\nThe ball slips past them."
            )
            await self.continue_mind_pull(interaction, game, match)
            return

        # A pull is a **steal**: possession flips, the ball stops here,
        # and this player is the carrier who does not run back.
        resume = match.pending_mind_pull_resume
        match.pending_mind_pull_resume = None
        match.apply_mind_pull(player_id)
        match.ball.speed = 1
        self.persist(game, match)

        await self.refresh_match_image(interaction, game)
        # The arrival this pre-empted never happens -- "a pull that
        # lands pre-empts whatever the movement would have led to" --
        # so the resume is dropped rather than dispatched. Its clock
        # cost is not: the maneuver that moved the ball still charges
        # its space minute, which is what `distance_moved` carries into
        # the run back.
        await self.begin_run_back(
            interaction,
            game,
            match,
            distance_moved=(resume or {}).get("distance_moved", 1),
            turnover_occurred=True,
            # A landed pull is a turnover and reads like one: the
            # heading is the skill test's own size, because this is a
            # roll that has just taken the ball off the other side and
            # a coach should not have to read a paragraph to find that
            # out. The wording is the author's (2026-09-07) -- what
            # happened is that a player took the ball, not that a
            # mechanic fired.
            lead_in=(
                f"{note}\n\n## {self.player_label(match, player)} grabs "
                "the ball with their telekinetic powers!\n"
                f"**Turnover!** They take it on "
                f"{ball_location_line(match)}."
            ),
        )

    def build_loose_ball_view(
        self,
        game_id: str,
        match: MatchState,
    ) -> Optional[discord.ui.View]:
        """
        The loose-ball pick prompt for the one side currently on the
        clock, as a view -- `d12ball.prompts.loose_ball_pick_prompt`'s
        answer through `view_for_prompt`, so a bot restart mid-pick
        reconstructs it from match state the same way
        `build_run_back_view` does, and None once the contest is
        settled either way.
        """
        prompt = loose_ball_pick_prompt(self.engine, match)
        if prompt is None:
            return None
        return self.view_for_prompt(game_id, match, prompt)


    async def begin_loose_ball(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        distance_moved: int,
        lead_in: str = "",
        headline: Optional[str] = None,
        is_high_pass: bool = False,
    ) -> None:
        """
        `distance_moved` (the pass's own clamped travel) is stashed on
        `match` by begin_loose_ball() -- the pick and, if it comes to
        one, the skill test both span later interactions that can't
        see a Python-level parameter from this call, so everything
        downstream reads it back from match state instead.

        `lead_in` is narration from the pass that hasn't been posted
        yet -- it rides along on this function's own first message.

        `headline` overrides the wording, which is otherwise built from
        the position by build_loose_ball_headline -- the ball may come
        down on an occupied space, so nothing may assume emptiness.

        **Nobody's contestant is forced from here.** A side with
        somebody standing on the ball puts them up, for nothing and
        without being asked, and that is one rule read off the position
        by loose_ball_candidates rather than call sites passing players
        in.

        **Occupancy decides who may be sent, and there is no longer a
        flag for it** (the author, 2026-08-26). A ball is *loose* only
        where it comes down on an empty space, and only then may each
        side send a player after it. Where one side is already standing
        there the ball is simply theirs; where both are, it is a
        contest between the players already on the space. Either way
        nobody walks in, so the side with nobody there is pre-declined
        before either side is put on the clock -- never prompted, and
        never given the chance.

        **A High Pass is the one exemption**, and `is_high_pass` is
        already the flag for it: the ball is high in the air, which
        gives players time to run at it, so a landing space holding
        only one side's players may still be contested by the other.
        That is a property of the pass and not of the space, which is
        why it rides on the same flag that carries the ball speed
        modifier.
        """
        # **Mind Pull pre-empts a contest and a loose ball alike**, so
        # the offer goes out before any of this side's state is set.
        # `finish_maneuver_resolution` has usually gated already and
        # spent the path; the callers that reach here directly -- a
        # Deflect, and the High Pass contest -- have not.
        if await self.check_for_mind_pull(
            interaction,
            game,
            match,
            {
                "kind": "loose_ball",
                "distance_moved": distance_moved,
                "lead_in": lead_in,
                "headline": headline,
                "is_high_pass": is_high_pass,
            },
        ):
            return

        match.begin_loose_ball(distance_moved, is_high_pass=is_high_pass)
        # The ball is free and about to be contested, so nobody is
        # carrying it -- including the long High Pass, where a receiver
        # who has to win a test to keep it is not yet in possession of
        # anything. Whoever comes out of the contest with it is chosen
        # off the ball's space in the ordinary way.
        match.clear_ball_carrier()

        if not is_high_pass:
            offense_side = match.ball.possession
            defense_side = match.defending_side()
            offense_occupied = bool(match.loose_ball_occupants(offense_side))
            defense_occupied = bool(match.loose_ball_occupants(defense_side))
            if offense_occupied != defense_occupied:
                empty_side = (
                    defense_side if offense_occupied else offense_side
                )
                match.decline_loose_ball(empty_side)

        self.engine.auto_resolve_loose_ball_picks(game, match)
        self.persist(game, match)

        if headline is None:
            headline = self.engine.build_loose_ball_headline(match)
        prefix = f"{lead_in}\n\n" if lead_in else ""
        if is_high_pass:
            # A High Pass is not a loose ball: the ball is on a player
            # everyone can already see, and the board it is standing on
            # was posted by the pass itself.
            await send_new_prompt(interaction, f"{prefix}{headline}")
        else:
            # A genuine loose ball is the one position nobody can read
            # off the last thing they were told -- the ball is lying in
            # an empty space some number of spaces from wherever the
            # pass started, and the very next question is who to send
            # after it. So it is named and drawn, together.
            await self.announce_board_update(
                interaction,
                game,
                f"{prefix}{headline}\n{ball_location_line(match)}",
            )

        if self.engine.loose_ball_side_on_the_clock(match) is None:
            await self.resolve_loose_ball(interaction, game, match)
            return

        prompt_message = await send_new_prompt(
            interaction,
            self.engine.build_loose_ball_prompt(game, match),
            view=self.build_loose_ball_view(game.game_id, match),
            allowed_mentions=discord.AllowedMentions(
                users=True, roles=False, everyone=False,
            ),
        )
        game.turn_message_id = prompt_message.id
        save_games(self.games)

    async def send_loose_ball_out_of_bounds(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        distance_moved: int,
    ) -> None:
        """
        Nobody could be sent, or nobody was. The side that last held
        the ball loses it, and the side that just won it owes a player
        on the ball's space -- placed after the run back, not before,
        or the run back would pull that player straight back off the
        ball again.
        """
        winning_side = match.defending_side()
        reason = (
            "Nobody is sent after it"
            if match.loose_ball_offense_declined
            or match.loose_ball_defense_declined
            # Only a side with nobody fielded at all lands here now --
            # distance replaced the zone as the measure on 2026-08-16,
            # so declining is otherwise the whole of how a ball goes
            # out.
            else "Neither side has anyone left to send"
        )
        # Assigned rather than set_possession'd: that insists on a
        # player of the new side already standing on the ball, and out
        # of bounds is precisely the case where nobody is --
        # pending_ball_recovery is the promise that somebody will be,
        # once the run back is done.
        match.ball.possession = winning_side
        match.ball.speed = 1
        match.pending_loose_ball = False
        match.pending_ball_recovery = True
        self.persist(game, match)

        await send_new_prompt(
            interaction,
            f"**Out of bounds!** {reason} -- "
            f"{format_team_side_label(match.setup_for_side(winning_side))} "
            "take over.\n\n# Turnover!\nOnce everyone has run back, "
            "they place a player on the ball."
        )
        await self.refresh_match_image(interaction, game)
        # Out of bounds is the one loose ball that is a new play rather
        # than a steal: nobody took the ball off anyone, it simply went
        # dead and is being brought back in.
        await self.begin_run_back(
            interaction, game, match,
            distance_moved=distance_moved,
            turnover_occurred=True,
            new_play=True,
        )

    async def resolve_unopposed_loose_ball(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        player_id: str,
        turnover: bool,
        distance_moved: int,
    ) -> None:
        """
        One side sent somebody and the other did not, so there is
        nothing to roll: they walk in and take it.

        `turnover` is the whole difference between the two sides
        arriving here. The defending side taking it changes possession
        and resets the ball's speed; the side already in possession
        keeping it changes neither. It is a steal either way -- picked
        off rather than restarted -- so neither opens a substitution
        window.
        """
        player = self.engine.get_player_definition(player_id)
        recovery_distance = match.distance_to_ball(player_id)
        match.move_meeple(
            player_id, match.ball.zone, match.ball.space_index,
        )
        exhaustion_text = self.apply_exhaustion(
            game, match, player_id, recovery_distance,
        )
        if turnover:
            match.ball.possession = match.defending_side()
            match.ball.speed = 1
        match.pending_loose_ball = False
        # They went after it and came away with it, so they are holding
        # it -- the same answer as a contested win, since an unopposed
        # contest is still how they got it.
        match.set_ball_carrier(player_id)
        self.persist(game, match)

        bracket = self.player_label(match, player)
        # Each of these says what happened and stops there. "Recovers
        # the loose ball uncontested" was three faults in five words:
        # it called an arrival loose that the message above it had just
        # said was not, and "uncontested" defined the result by the
        # roll that did not happen -- which no coach was waiting for,
        # since nobody had been offered a send.
        if match.pending_loose_ball_is_high_pass:
            headline = (
                f"{bracket} picks off the high pass."
                if turnover
                else f"{bracket} keeps possession after the high pass."
            )
        else:
            headline = f"{bracket} picks up the ball."

        if turnover:
            content = (
                "# Turnover!\n"
                f"{headline} "
                f"{format_team_side_label(match.setup_for_side(match.ball.possession))} "
                "now has possession."
            )
        else:
            content = headline

        # A move that costs nothing says nothing -- see
        # `describe_exhaustion_gain`, which is why this is a join over
        # what is there rather than an interpolation.
        content = "\n".join(filter(None, [content, exhaustion_text]))

        await send_new_prompt(interaction, content)
        await self.refresh_match_image(interaction, game)
        await self.begin_run_back(
            interaction, game, match,
            distance_moved=distance_moved, turnover_occurred=turnover,
        )

    async def begin_loose_ball_skill_test(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        offense_player_id: str,
        defense_player_id: str,
    ) -> None:
        """
        Both sides have a candidate: move them both in, charge each
        their own recovery distance in exhaustion, and put the skill
        test up.
        """
        offense_recovery_distance = match.distance_to_ball(offense_player_id)
        defense_recovery_distance = match.distance_to_ball(defense_player_id)
        match.move_meeple(
            offense_player_id, match.ball.zone, match.ball.space_index,
        )
        match.move_meeple(
            defense_player_id, match.ball.zone, match.ball.space_index,
        )
        # Filtered: a contestant already standing on the ball is
        # charged nothing and says nothing, and an unfiltered join
        # would leave their blank line in the message.
        exhaustion_text = "\n".join(
            filter(
                None,
                [
                    self.apply_exhaustion(
                        game,
                        match,
                        offense_player_id,
                        offense_recovery_distance,
                    ),
                    self.apply_exhaustion(
                        game,
                        match,
                        defense_player_id,
                        defense_recovery_distance,
                    ),
                ],
            )
        )
        self.persist(game, match)
        await self.refresh_match_image(interaction, game)

        offense_player = self.engine.get_player_definition(offense_player_id)
        defense_player = self.engine.get_player_definition(defense_player_id)
        offense_skill = self.player_catalog.effective_profile(
            offense_player,
        ).offense
        defense_skill = self.player_catalog.effective_profile(
            defense_player,
        ).defense

        # Who is defending what differs between the two: a High Pass's
        # receiver already has the ball and is being challenged for it,
        # where a loose ball belongs to nobody yet and both sides are
        # going for it.
        contest_line = (
            f"{self.player_label(match, defense_player)} "
            f"(defense skill {defense_skill}) challenges "
            f"{self.player_label(match, offense_player)} "
            f"(offense skill {offense_skill}) for the high pass -- the "
            "receiver must win this skill test to keep possession!"
            if match.pending_loose_ball_is_high_pass
            else f"{self.player_label(match, offense_player)} "
            f"(offense skill {offense_skill}) and "
            f"{self.player_label(match, defense_player)} "
            f"(defense skill {defense_skill}) both contest the "
            f"{contest_noun(match)} -- skill test!"
        )
        test_message = await send_new_prompt(
            interaction,
            f"{contest_line}\n{exhaustion_text}\n\nEither "
            "player can roll:",
            view=LooseBallSkillTestView(self, game.game_id),
        )
        game.turn_message_id = test_message.id
        save_games(self.games)

    async def resolve_loose_ball(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        Settle a loose ball (or a long High Pass, which comes through
        the same machinery) once both sides have answered: out of
        bounds when neither sent anybody, an unopposed take when only
        one did, and a skill test when both did.
        """
        offense_player_id = match.loose_ball_offense_player
        defense_player_id = match.loose_ball_defense_player
        distance_moved = match.pending_loose_ball_distance

        if offense_player_id is None and defense_player_id is None:
            await self.send_loose_ball_out_of_bounds(
                interaction, game, match, distance_moved,
            )
            return

        if defense_player_id is None:
            await self.resolve_unopposed_loose_ball(
                interaction, game, match, offense_player_id,
                turnover=False, distance_moved=distance_moved,
            )
            return

        if offense_player_id is None:
            # Only the defending side went for it -- because the side
            # in possession sent nobody. Not out of bounds: that is the
            # branch above, where neither side ends up with a player to
            # send.
            await self.resolve_unopposed_loose_ball(
                interaction, game, match, defense_player_id,
                turnover=True, distance_moved=distance_moved,
            )
            return

        await self.begin_loose_ball_skill_test(
            interaction, game, match, offense_player_id, defense_player_id,
        )

    async def begin_shooter_choice(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        candidates: list[str],
        lead_in: str = "",
    ) -> None:
        """
        `lead_in` is narration from the pass that set this scoring
        opportunity up -- it rides along on the "choose who takes the
        shot" prompt when a human has to pick. When the pick is
        automatic there's no prompt to attach it to, so it's posted on
        its own instead of being dropped.
        """
        if len(candidates) == 1 or self.engine.side_controlled_by_ai(
            game, match, "offense",
        ):
            if len(candidates) == 1:
                shooter_id = candidates[0]
            else:
                shooter_id = self.engine.get_ai_strategy(game).choose_shooter(
                    candidates, match,
                )
            if lead_in:
                await send_new_prompt(interaction, lead_in)
            await self.start_set_up_shot(interaction, game, match, shooter_id)
            return

        mention = format_player_with_team(
            game,
            self.engine.possession_player_number(game, match),
            self.team_emojis,
            mention=True,
        )
        prefix = f"{lead_in}\n\n" if lead_in else ""
        prompt_message = await send_new_prompt(
            interaction,
            f"{prefix}{mention}, choose who takes the shot:",
            view=ShooterChoiceView(self, game.game_id, candidates),
            allowed_mentions=discord.AllowedMentions(
                users=True, roles=False, everyone=False,
            ),
        )
        game.turn_message_id = prompt_message.id
        save_games(self.games)

    async def start_set_up_shot(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        shooter_id: str,
        maneuver_cost: int = 1,
    ) -> None:
        """
        `maneuver_cost` is the flat cost of the maneuver that offered
        this set-up -- 1 for everything but a High Pass, which is why
        it defaults to 1 and only a High Pass call site overrides it.
        Stored so ScoreAttemptView.roll can charge it on top of the
        shot's own extra minute (2026-08-16): the two stack now,
        instead of the shot's cost replacing the maneuver's.
        """
        match.active_player_id = shooter_id
        match.pending_action = "shoot"
        match.pending_shot_is_set_up = True
        match.pending_shot_setup_cost = maneuver_cost
        self.persist(game, match)

        shooter = self.engine.get_player_definition(shooter_id)
        await send_new_prompt(
            interaction,
            f"{self.player_label(match, shooter)} takes the "
            "shot off the set-up."
        )
        await self.begin_score_attempt(interaction, game, match)

    # -- Deflect -------------------------------------------------

    async def resolve_deflect(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        await self.apply_deflection(interaction, game, match, "deflect")

    async def resolve_clear(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        Clear is Deflect at three spaces: the ball goes back 3
        and ball speed drops by 3 rather than 1. Everything else about
        it -- the overshoot set-up, the loose ball it leaves behind --
        is the same, which is why the two share one function.

        **The Fullback's ability is +1 distance, so a Clear it plays
        goes back 4** (the author, 2026-08-19). Its sentence reads
        "Block deflect: ball goes back 2 spaces", which read as a
        number is a *reduction* against a 3-space clearance and read as
        the rule behind the number is the +1 that takes a basic
        deflection from 1 to 2. The rule is what carries.
        """
        await self.apply_deflection(interaction, game, match, "clear")

    def deflection_numbers(
        self,
        defender: PlayerDefinition,
        key: str,
    ) -> tuple[int, int, bool]:
        """
        How far a deflection drives the ball, how much speed it takes
        off, and whether a Fullback's ability is in it.

        **The speed drop is the card's, not the distance's.** A
        Fullback's Deflect has always moved the ball 2 and dropped the
        speed by 1, so the two are separate numbers that happen to
        match on an ordinary deflection -- and a Clear's -3 stays -3
        when the Fullback pushes it to 4 spaces. Derived from the
        distance instead, this read correctly right up until the
        Fullback was let near a Clear, which is why they are returned
        as two numbers rather than one.
        """
        # Role ability -- Fullback: +1 space on a deflection, which
        # takes a Deflect from 1 to 2 and a Clear from 3 to 4.
        fullback_bonus = defender.role == PlayerRole.FULLBACK
        base_distance = 3 if key == "clear" else 1

        return (
            base_distance + (1 if fullback_bonus else 0),
            base_distance,
            fullback_bonus,
        )

    def knock_ball_back(
        self,
        game: D12BallGame,
        match: MatchState,
        offense_side: TeamSide,
        deflect_distance: int,
        speed_drop: int,
    ) -> tuple[bool, int]:
        """
        Drive the ball back toward the offense's own goal and take the
        speed off it. Returns whether it ran out of field and how far
        it actually went.

        The overshoot is read before the ball moves, the way every
        other overshoot in the game is. It no longer risks an own goal
        -- only Pressure does -- it sets up a scoring opportunity for
        the defense instead, who are now the side standing next to the
        goal the ball just reached.
        """
        origin_flat = match.board.flat_index(
            match.ball.zone, match.ball.space_index,
        )
        target_flat = match.relative_flat_index(
            origin_flat, offense_side, -deflect_distance,
        )
        overshot = abs(target_flat - origin_flat) < deflect_distance

        actual_distance = match.move_ball_relative(
            offense_side, -deflect_distance,
        )
        match.ball.speed = max(1, match.ball.speed - speed_drop)
        self.persist(game, match)

        return overshot, actual_distance

    async def apply_deflection(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        key: str,
    ) -> None:
        offense_side = match.ball.possession
        defense_side = match.defending_side()
        defender = self.engine.get_player_definition(match.challenger_id)
        name = self.engine.maneuver_name(key)

        deflect_distance, speed_drop, fullback_bonus = (
            self.deflection_numbers(defender, key)
        )

        overshot, actual_distance = self.knock_ball_back(
            game, match, offense_side, deflect_distance, speed_drop,
        )

        space_word = "space" if actual_distance == 1 else "spaces"
        ability_note = " (Fullback ability)" if fullback_bonus else ""
        content = (
            f"**{name}:** the ball moves {actual_distance} "
            f"{space_word} back{ability_note}. Ball speed is now "
            f"{match.ball.speed}."
        )

        # A shot has to be within shooting range, and this one always
        # is: an overshoot means the ball reached the space closest to
        # the offense's own goal, which is as deep into the deflecting
        # team's range as the field goes. So this asks
        # scoring_opportunity_candidates with no range check over it --
        # the check could never fail here, and a branch that cannot be
        # taken reads as if it could.
        candidates = []
        if overshot:
            candidates = self.engine.scoring_opportunity_candidates(
                match, defense_side,
            )

        if candidates:
            # A defender standing right where the ball ends up gets a
            # shot at the goal it's now next to -- that's a turnover
            # before the shot, same as any other change of possession,
            # so the score attempt reads the correct attacking and
            # defending sides.
            match.ball.possession = defense_side
            match.ball.speed = 1
            self.persist(game, match)

            await self.refresh_match_image(interaction, game)
            await self.begin_shooter_choice(
                interaction,
                game,
                match,
                candidates,
                lead_in=f"{content} That overshoots the field -- a scoring "
                "opportunity!",
            )
            return

        # **Setup Pass's cost**: beaten by a deflection, the defending
        # coach drives the ball back a further 1, 2 or 3 spaces and it
        # is loose where it stops. It is asked here rather than as a
        # step after the maneuver because a deflection already ends in
        # a loose ball -- the cost only decides where it lies. Not
        # asked when the deflection overshot into a shot above: the
        # ball is already as far back as the field goes and the shot is
        # the bigger thing happening.
        if self.engine.advanced_cost(match, key) == "setup_pass":
            await self.offer_setup_pass_push_back(
                interaction, game, match, lead_in=content,
            )
            return

        # A deflection knocks the ball out of anybody's possession, so
        # it does not go through finish_maneuver_resolution's ordinary
        # loose-ball check: that check asks whether the possessing team
        # has somebody on the ball, and here the answer does not
        # matter -- either side's occupant is equally dispossessed.
        #
        # **Occupancy decides how it is won**, which since 2026-08-26
        # is the rule everywhere rather than this card's own: an empty
        # landing space is a loose ball (each side may send someone); a
        # space only one side occupies is theirs outright, with no send
        # offered to the other; a space both occupy is a contest
        # between the players already there. See begin_loose_ball.
        #
        # No refresh_match_image first: begin_loose_ball posts the
        # board with the announcement, and refreshing here would write
        # the same board twice (see "Discord's rate limits").
        #
        # A deflection's time cost is a fixed 1 space minute per the
        # rules table, not "distance traveled" like Low/High Pass, so
        # this doesn't shrink if the move was clamped at the edge (or
        # grow with the Fullback's extra distance, or Clear's).
        await self.begin_loose_ball(
            interaction, game, match, 1, lead_in=content,
        )

    async def offer_setup_pass_push_back(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        lead_in: str,
    ) -> None:
        """
        Setup Pass's cost: the coach who beat it chooses 1, 2 or 3
        further spaces to drive the ball back, where it is a loose
        ball.

        Distances that would run off the end of the field are not
        offered, for the reason `high_pass_distances` does not offer
        them: a longer push landing where a shorter one already would
        is the same push described twice. If none of the three fits,
        the ball is already at the end and the cost is spent -- the
        loose ball happens where the deflection left it.
        """
        defense_side = match.defending_side()
        offense_side = match.ball.possession
        origin_flat = match.board.flat_index(
            match.ball.zone, match.ball.space_index,
        )
        distances = [
            distance
            for distance in (1, 2, 3)
            if abs(
                match.relative_flat_index(origin_flat, offense_side, -distance)
                - origin_flat
            )
            == distance
        ]

        if not distances:
            await self.begin_loose_ball(
                interaction, game, match, 1, lead_in=lead_in,
            )
            return

        if self.engine.side_controlled_by_ai(game, match, "defense"):
            # Dinky drives it as far back as it can, the same
            # maximizing it brings to a speed choice.
            await self.apply_setup_pass_push_back(
                interaction, game, match, max(distances), lead_in=lead_in,
            )
            return

        mention = format_player_with_team(
            game,
            self.engine.defending_player_number(game, match),
            self.team_emojis,
            mention=True,
        )
        prompt_view = SetupPassPushBackView(self, game.game_id)
        prompt_message = await send_new_prompt(
            interaction,
            f"{lead_in}\n\n{mention}, **Setup Pass** was beaten -- how far "
            "back does the ball go? It will be loose where it stops.",
            view=prompt_view,
            allowed_mentions=discord.AllowedMentions(
                users=True, roles=False, everyone=False,
            ),
        )
        game.turn_message_id = prompt_message.id
        save_games(self.games)

    async def apply_setup_pass_push_back(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        distance: int,
        lead_in: str = "",
    ) -> None:
        offense_side = match.ball.possession
        actual_distance = match.move_ball_relative(offense_side, -distance)
        self.persist(game, match)

        space_word = "space" if actual_distance == 1 else "spaces"
        prefix = f"{lead_in}\n\n" if lead_in else ""
        await self.begin_loose_ball(
            interaction,
            game,
            match,
            1,
            lead_in=(
                f"{prefix}**Setup Pass** was beaten: the ball is driven a "
                f"further {actual_distance} {space_word} back."
            ),
        )

    # -- Steal ----------------------------------------------------------

    async def resolve_steal(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        await self.apply_steal(interaction, game, match, "steal")

    async def resolve_intercept(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        Intercept is the basic Steal with the sign flipped: the
        interceptor carries the ball **forward**, toward the goal they
        now attack, rather than falling back toward their own. It is
        the only card in the game that moves the ball against the way
        the offense was going.
        """
        await self.apply_steal(interaction, game, match, "intercept")

    async def apply_steal(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        key: str,
    ) -> None:
        """
        The Discord half of a won Steal or Intercept: run the step,
        save what it did, then post and dispatch what it handed back.

        Four lines over `steal_step`, which is where the turnover, the
        carry, the wording and a beaten Skilled Pass's cost live -- see
        `apply_low_pass` for the shape and principle 9 in CLAUDE.md for
        why the save is here rather than inside the step.

        **Two saves became this one.** `take_ball_by_steal` persisted
        inside itself and the Skilled Pass branch persisted again on
        top of it, so a steal that collected that cost wrote the file
        twice and one that did not wrote it once. The step no longer
        saves at all and the wrapper always does, which is the same
        state written the same number of times on either branch.
        """
        result = steal_step(self.engine, match, key)
        self.persist(game, match)
        await self.dispatch_step_result(interaction, game, match, result)

    # -- Pressure --------------------------------------------------------

    async def resolve_pressure(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        await self.apply_pressure(interaction, game, match, "pressure")

    async def resolve_double_team(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        Double Team is Pressure at two spaces, with a second defender
        brought in free of exhaustion -- and it is the one card whose
        effect lands on the *following* maneuver: so long as no new
        play intervenes, both defenders challenge the ball holder and
        both add their defensive skill.
        """
        await self.apply_pressure(interaction, game, match, "double_team")

    def shove_pressured_handler(
        self,
        match: MatchState,
        push: int,
        partner_id: Optional[str],
    ) -> int:
        """
        Drive the handler and the ball back, and bring the challenger
        (and a Double Team's partner) onto the space they left.

        Returns how far the handler actually moved, which is less than
        `push` only when they were already against their own goal --
        the caller reads that as the overshoot.
        """
        offense_side = match.ball.possession

        actual_distance = match.move_player_relative(
            match.active_player_id, offense_side, -push,
        )
        match.set_ball_space(
            *match.board.meeple_position(match.active_player_id)
        )

        # The challenger advances onto the handler's space. A Double
        # Team brings that teammate onto it as well, free of
        # exhaustion -- so they are *placed* rather than run, which is
        # what "no exhaustion cost" means in a game where every other
        # way to reach a space charges a token a space.
        handler_zone, handler_space = match.board.meeple_position(
            match.active_player_id
        )
        match.move_meeple(match.challenger_id, handler_zone, handler_space)
        if partner_id is not None:
            match.move_meeple(partner_id, handler_zone, handler_space)

        # Losing to a pressure does not lose the ball: the handler was
        # shoved back still holding it, so they take the next turn.
        # Set before the caller's overshoot branch, because an own goal
        # avoided is the same thing -- pressured, and still holding it.
        # The Defender's steal moves the carry to the Defender, and a
        # conceded own goal is a new play, which clears it.
        match.set_ball_carrier(match.active_player_id)

        return actual_distance

    def pressure_result_text(
        self,
        match: MatchState,
        key: str,
        name: str,
        actual_distance: int,
        partner_id: Optional[str],
    ) -> str:
        """
        What the shove reads as, and -- for a Double Team -- the record
        of who is left challenging the next maneuver.
        """
        handler = self.engine.get_player_definition(match.active_player_id)
        defender = self.engine.get_player_definition(match.challenger_id)
        space_word = "space" if actual_distance == 1 else "spaces"
        content = (
            f"**{name}:** "
            f"{self.player_label(match, handler)} and the "
            f"ball go back {actual_distance} {space_word}. "
            f"{self.player_label(match, defender)} moves "
            "forward."
        )

        if key == "double_team" and partner_id is not None:
            partner = self.engine.get_player_definition(partner_id)
            # **The pair is recorded, not the fact that a Double Team
            # happened.** What the next maneuver needs is who
            # challenges it, and that is two named cards; a flag would
            # leave the following turn re-deriving "the nearest
            # teammate" off a board that has moved since.
            match.pending_double_team = [match.challenger_id, partner_id]
            content += (
                f" {self.player_label(match, partner)} "
                "joins them -- and **both** will challenge on the next "
                "maneuver, each adding their defensive skill."
            )

        return content

    def apply_pressure_turnover(
        self,
        match: MatchState,
        key: str,
        defense_side: TeamSide,
    ) -> tuple[str, bool, bool]:
        """
        Whether the pressure also took the ball, and what to say about
        it. Returns the text to append, and the two facts the caller
        dispatches on: a Dribble Burst cost paid, and a Defender's
        steal.

        The two are exclusive and in that order -- a burst cost already
        turns the ball over, so the Defender's ability has nothing left
        to take.
        """
        defender = self.engine.get_player_definition(match.challenger_id)
        content = ""

        # **Dribble Burst's cost**: beaten by a pressure, the offense
        # loses possession *and* the ball keeps whatever speed it was
        # carrying while the defense manipulates it. Neither of those
        # is something a pressure does on its own -- a turnover is the
        # steal's and so is the speed step -- which is what the matrix
        # means by the cost borrowing machinery its defeaters do not
        # have. It is also **the first exception to "every turnover
        # resets ball speed to 1"**, and the reason nothing here sets
        # `match.ball.speed = 1`.
        burst_cost = self.engine.advanced_cost(match, key) == "dribble_burst"
        if burst_cost:
            match.ball.possession = defense_side
            match.set_ball_carrier(match.challenger_id)
            content += (
                "\n\n# Turnover!\n"
                "**Dribble Burst** was beaten -- "
                f"{format_team_side_label(match.setup_for_side(defense_side))} "
                "take the ball, and it keeps the speed the burst put into "
                f"it ({match.ball.speed})."
            )

        # Role ability -- Defender: also steals the ball on a won
        # pressure, on top of the normal effect above.
        stolen = defender.role == PlayerRole.DEFENDER
        if stolen and not burst_cost:
            match.ball.possession = defense_side
            match.ball.speed = 1
            match.set_ball_carrier(match.challenger_id)
            content += (
                "\n\n# Turnover!\n"
                f"{self.player_label(match, defender)} "
                "steals the ball (Defender ability)! "
                f"{format_team_side_label(match.setup_for_side(defense_side))} "
                "now has possession."
            )

        return content, burst_cost, stolen

    async def apply_pressure(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        key: str,
    ) -> None:
        offense_side = match.ball.possession
        defense_side = match.defending_side()
        name = self.engine.maneuver_name(key)
        push = 2 if key == "double_team" else 1

        # Own-goal risk: a pressure is the only thing that threatens
        # one, and only when the ball-holder is already at the space
        # closest to their own goal, i.e. pushing them back further
        # isn't possible.
        origin_flat = match.board.flat_index(
            match.ball.zone, match.ball.space_index,
        )
        target_flat = match.relative_flat_index(
            origin_flat, offense_side, -push,
        )
        overshot = abs(target_flat - origin_flat) < push

        # **Read before anything moves.** The card says "the teammate
        # closest to the space where the play started", and the play
        # started where the ball is standing now -- a moment later the
        # handler has been shoved back two and the ball with them, and
        # the nearest defender to *that* space can be somebody else
        # entirely. Asked here, so the answer is the one the card
        # describes.
        partner_id = (
            self.engine.double_team_partner(match)
            if key == "double_team"
            else None
        )

        actual_distance = self.shove_pressured_handler(
            match, push, partner_id,
        )
        content = self.pressure_result_text(
            match, key, name, actual_distance, partner_id,
        )

        if overshot:
            self.persist(game, match)
            await send_new_prompt(
                interaction,
                f"{content}\n\nThat overshoots toward their own goal!",
            )
            await self.refresh_match_image(interaction, game)
            # An own goal takes priority over the Defender's steal
            # ability: if it's conceded, the point is already over, and
            # stealing a ball that was just kicked off from the restart
            # wouldn't mean anything.
            await self.begin_own_goal_roll(
                interaction, game, match, distance_moved=1,
            )
            return

        turnover_text, burst_cost, stolen = self.apply_pressure_turnover(
            match, key, defense_side,
        )
        content += turnover_text

        self.persist(game, match)

        await self.refresh_match_image(interaction, game)

        # Fixed 1 space minute per the rules table, independent of
        # clamping, same reasoning as a deflection.
        if burst_cost:
            # The defense has the ball and the speed step the cost
            # granted them, which is the steal's shape: run everyone
            # back first, then let them set the speed.
            await self.begin_run_back(
                interaction,
                game,
                match,
                speed_choice_after=True,
                speed_reset=False,
                lead_in=content,
            )
        elif stolen:
            # The stealing player keeps the ball and stays put --
            # everyone else who's out of position runs back. Read off
            # the carrier set in the shove, not passed in.
            await self.begin_run_back(
                interaction,
                game,
                match,
                lead_in=content,
            )
        else:
            await self.finish_maneuver_resolution(
                interaction, game, match, distance_moved=1, lead_in=content,
            )

    # -- Ball-speed manipulation (Dribble Advance / Steal) --

    async def offer_speed_choice(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        player_id: str,
        skill_type: str,
        turnover_occurred: bool = False,
        distance_moved: int = 1,
        lead_in: str = "",
    ) -> None:
        """
        Always the last human choice in a maneuver's effect -- speed is
        manipulated after any run-back it caused (Steal), so
        this leads straight into finish_maneuver_resolution once
        chosen. `turnover_occurred`/`distance_moved` are just carried
        through to that call.

        `lead_in` is narration from the maneuver that led here -- it
        rides along on the speed-choice prompt when a human picks, or
        gets forwarded to apply_speed_choice to ride along on its own
        message when the pick is automatic.
        """
        skill = self.player_catalog.effective_profile(
            self.engine.get_player_definition(player_id),
        )
        skill_value = skill.offense if skill_type == "offense" else skill.defense

        controller_id = self.engine.controlling_user_id(game, match, player_id)
        is_ai = game.is_solo_game and controller_id == game.player_2_id

        if is_ai:
            delta = self.engine.get_ai_strategy(game).choose_speed_delta(skill_value)
            target_speed = max(1, min(12, match.ball.speed + delta))
            await self.apply_speed_choice(
                interaction,
                game,
                match,
                target_speed,
                turnover_occurred=turnover_occurred,
                distance_moved=distance_moved,
                lead_in=lead_in,
            )
            return

        mention = f"<@{controller_id}>" if controller_id else "Someone"
        prefix = f"{lead_in}\n\n" if lead_in else ""

        async def show_prompt(inner_interaction: discord.Interaction) -> None:
            prompt_message = await send_new_prompt(
                inner_interaction,
                f"{prefix}{mention}, manipulate the ball's speed (up to "
                f"{skill_value}):",
                view=SpeedDeltaChoiceView(
                    self, game.game_id, player_id, skill_type,
                ),
                allowed_mentions=discord.AllowedMentions(
                    users=True, roles=False, everyone=False,
                ),
            )
            game.turn_message_id = prompt_message.id
            save_games(self.games)

        # The note goes with the choice itself, the same way a
        # maneuver's own note goes in front of its menu rather than
        # with the lesson two messages up -- see the maneuver_note
        # call site. It is held behind Continue rather than posted
        # alongside the maneuver's own reveal message just above it,
        # which the coach has had no click to acknowledge -- see
        # post_tutorial_note.
        tutorial_beat = self.tutorial_beat(game)
        if tutorial_beat is not None and tutorial_beat.speed_note:
            await self.post_tutorial_note(
                interaction, game, tutorial_beat.speed_note, show_prompt,
            )
            return

        await show_prompt(interaction)

    async def apply_speed_choice(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        target_speed: int,
        turnover_occurred: bool = False,
        distance_moved: int = 1,
        lead_in: str = "",
    ) -> None:
        match.ball.speed = target_speed
        self.persist(game, match)

        prefix = f"{lead_in}\n\n" if lead_in else ""
        await send_new_prompt(
            interaction, f"{prefix}Ball speed is now **{target_speed}**."
        )
        await self.refresh_match_image(interaction, game)

        # An advanced effect can reach past its own maneuver, and a
        # speed choice is the last human step of the two that do -- see
        # `MatchState.pending_effect_continuation`.
        if match.pending_effect_continuation is not None:
            await self.continue_effect(
                interaction,
                game,
                match,
                distance_moved=distance_moved,
                turnover_occurred=turnover_occurred,
            )
            return

        await self.finish_maneuver_resolution(
            interaction,
            game,
            match,
            distance_moved=distance_moved,
            turnover_occurred=turnover_occurred,
        )

    async def continue_effect(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        distance_moved: int = 1,
        turnover_occurred: bool = False,
    ) -> None:
        """
        Run whatever an advanced effect still owes once its last prompt
        has been answered.

        **The record is cleared by whatever applies the step, not
        here.** A continuation is one more prompt, and a coach may take
        hours over it -- so between dispatching and the click that
        answers, the only thing on the match saying what is owed is
        this field. Clearing it at dispatch (which is what
        `finish_time_out` does with `pending_time_out`, for a flow with no
        prompt left in it) would leave a restart in that window
        reading the maneuver's winner instead and re-offering the
        speed choice a coach had already answered.
        `build_effect_choice_view` reads this first for the same
        reason.

        An unrecognised kind falls through to the ordinary end of a
        maneuver rather than stranding the turn: a continuation written
        by a version of the bot this one does not have is a game to
        finish, not a game to lose. That branch *does* clear it, or the
        next speed choice in the game would find it still set.
        """
        continuation = match.pending_effect_continuation or {}

        if continuation.get("kind") == "free_low_pass":
            # **Skilled Pass's cost.** The defense stole the ball and
            # now plays a Low Pass with it, unopposed. The passer is
            # whoever took it -- named when the cost was recorded, and
            # re-derived from the ball if a run back has moved things
            # since.
            passer_id = continuation.get("player_id")
            holders = match.eligible_ball_handlers()
            if passer_id not in holders:
                passer_id = holders[0] if holders else None
            if passer_id is not None:
                match.active_player_id = passer_id
                self.persist(game, match)
                await self.resolve_low_pass(
                    interaction, game, match, key="low_pass", free=True,
                )
                return

        if continuation.get("kind") == "setup_pass_shot":
            # **Setup Pass's benefit**, second half: the speed is set,
            # and now the scoring opportunity is set up.
            await self.offer_setup_pass_distance(interaction, game, match)
            return

        match.pending_effect_continuation = None
        self.persist(game, match)
        await self.finish_maneuver_resolution(
            interaction,
            game,
            match,
            distance_moved=distance_moved,
            turnover_occurred=turnover_occurred,
        )

    # -- Own goal ----------------------------------------------------

    async def begin_own_goal_roll(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        distance_moved: int,
    ) -> None:
        """
        Put the own-goal roll behind a button, the way a score attempt
        is: the coach whose player is about to concede rolls it
        themselves rather than reading what the bot already rolled for
        them.

        Nothing is decided here, so everything the roll needs is
        persisted first -- `pending_own_goal` says one is owed and
        `pending_own_goal_distance` carries the clock cost of the
        maneuver that risked it, which the resolution spends whichever
        way the roll goes. A restart between the two comes back to this
        prompt through `pending_turn_view`.
        """
        match.pending_own_goal = True
        match.pending_own_goal_distance = distance_moved
        self.persist(game, match)

        offense_player = self.engine.get_player_definition(match.active_player_id)
        offense_skill = self.player_catalog.effective_profile(
            offense_player,
        ).offense
        controller_id = self.engine.controlling_user_id(
            game, match, offense_player.player_id,
        )
        mention = f"<@{controller_id}>" if controller_id else "Someone"

        prompt_message = await send_new_prompt(
            interaction,
            f"**Own goal risk!** {mention}, "
            f"{self.player_label(match, offense_player)} "
            "rolls two d12 at an advantage — the higher of the two, plus "
            f"their offensive skill ({offense_skill}). A total of 7 or "
            "more and the own goal is avoided.",
            view=OwnGoalRollView(self, game.game_id),
            allowed_mentions=discord.AllowedMentions(
                users=True, roles=False, everyone=False,
            ),
        )
        game.turn_message_id = prompt_message.id
        save_games(self.games)

    async def own_goal_roll_message(
        self,
        match: MatchState,
        offense_player: PlayerDefinition,
        rolls: tuple[int, int],
        offense_skill: int,
        safe: bool,
        ignite: Optional[IgnitedRoll] = None,
        overdrive: int = 0,
    ) -> tuple[discord.File, str]:
        """
        The dice image and the arithmetic that produced it, which is
        posted above it because it is what built it.

        `ignite` is Volatile on the **kept** die -- an own goal is
        rolled at an advantage and the rules name "the die kept", so
        the discarded one never ignites even when it is a 6 or a 7.
        """
        offense_setup = match.setup_for_side(match.ball.possession)
        dice_file = discord.File(
            await asyncio.to_thread(
                render_own_goal_dice,
                list(rolls),
                TEAM_COLORS[offense_setup.team],
                safe,
                bool(overdrive),
            ),
            filename="own_goal_dice.png",
        )

        taken = max(rolls)
        modifier = ignite.modifier if ignite else 0
        breakdown = (
            f"**Own goal risk!** "
            f"{self.player_label(match, offense_player)} "
            f"rolls at an advantage: higher of {rolls[0]}/{rolls[1]} "
            f"is {taken}, + {offense_skill} (offensive skill)"
        )
        if ignite and ignite.detail:
            breakdown += f", {ignite.detail}"
        if overdrive:
            breakdown += f", +{overdrive} Overdrive"
        breakdown += f" = {taken + offense_skill + modifier + overdrive}"

        return dice_file, breakdown

    def apply_own_goal_outcome(
        self,
        game: D12BallGame,
        match: MatchState,
        offense_player: PlayerDefinition,
        distance_moved: int,
        safe: bool,
        exhaustion_text: str,
    ) -> str:
        """
        Settle the roll and word it. Both outcomes restart play, which
        is why the caller's dispatch is the same either way -- what
        differs is whether a goal went on the board.
        """
        if safe:
            # A new play resets speed same as any other -- see
            # begin_run_back -- and nothing else on this path would,
            # since Pressure's overshoot branch never touches it.
            match.ball.speed = 1
            # The ball stays exactly where the overshot Pressure left
            # it, with no coverage guarantee at all -- not even the
            # standard deal's, since that position is wherever the play
            # happened to reach. So, since 2026-08-24, this owes the
            # same pickup an out-of-bounds ball does rather than a
            # two-sided loose ball: begin_ball_recovery checks
            # eligible_ball_handlers() first and asks nobody when the
            # reset already covers it.
            match.pending_ball_recovery = True
            return f"## Own goal avoided!\n\n{exhaustion_text}"

        conceding_side = match.ball.possession
        # The goal is the other side's; the kick is this player's,
        # and the log says both -- see concede_own_goal.
        match.concede_own_goal(offense_player.player_id)
        match.restart_after_goal(conceding_side)
        match.pending_run_back = True
        match.pending_run_back_distance = distance_moved
        match.pending_run_back_turnover = True
        self.persist(game, match)
        return (
            f"# Own goal!\n"
            f"{self.player_label(match, offense_player)} "
            "puts it in their own net on "
            f"**{format_goal_time(match.goals[-1])}**.\n"
            f"{team_display_name(match.home.team)} {match.scoreboard.home_score}:"
            f"{match.scoreboard.visiting_score} "
            f"{team_display_name(match.visiting.team)}\n\n"
            f"{exhaustion_text}"
        )

    async def run_own_goal_roll(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        The roll itself, off the button `begin_own_goal_roll` posted:
        2d12 at an advantage (take the higher), plus the ball-handler's
        offensive skill, safe on 7+.

        Making the attempt costs the rolling player 1 exhaust token,
        win or lose, on top of whatever the maneuver that triggered the
        risk already charged. It is not a skill test, so it owes no
        injury check.
        """
        distance_moved = match.pending_own_goal_distance
        match.pending_own_goal = False

        offense_player = self.engine.get_player_definition(match.active_player_id)
        offense_skill = self.player_catalog.effective_profile(
            offense_player,
        ).offense

        rolls = (random.randint(1, 12), random.randint(1, 12))
        # Volatile reads the die that is **kept**, not both: an own
        # goal is rolled at an advantage, and the rules name "the die
        # kept in an own-goal roll".
        ignite = self.engine.ignite(
            game, offense_player.player_id, max(rolls),
        )
        overdrive = match.overdrive_modifier(offense_player.player_id)
        match.consume_overdrive()
        safe = (
            max(rolls) + offense_skill + ignite.modifier + overdrive >= 7
        )

        # Logged ahead of `apply_own_goal_outcome`, which is what
        # concedes the goal, so the risk sits above the goal it
        # sometimes produced. Both outcomes, for the reason the injury
        # test logs both: the interesting number is how often a
        # Pressure that risks an own goal actually costs one, and that
        # needs the attempts as well as the concessions.
        match.record_event(
            EVENT_OWN_GOAL_ROLL,
            side=match.ball.possession,
            player_id=offense_player.player_id,
            conceded=not safe,
            rolls=list(rolls),
            offense_skill=offense_skill,
        )

        # Charged before either branch saves the match, so the token
        # and any Exhausted flag it sets are written out with the rest
        # of the roll's outcome -- see apply_exhaustion.
        exhaustion_text = self.apply_exhaustion(
            game, match, offense_player.player_id, 1,
        )

        dice_file, breakdown = await self.own_goal_roll_message(
            match, offense_player, rolls, offense_skill, safe, ignite,
            overdrive,
        )
        verdict = self.apply_own_goal_outcome(
            game, match, offense_player, distance_moved, safe,
            exhaustion_text,
        )

        # The prompt becomes the dice, taking its own explanation with
        # it once the roll it was asking for has happened -- the same
        # trade a score attempt makes. The arithmetic rides above the
        # image because it is what built it; the verdict follows in a
        # message of its own, since a message's attachments render
        # below its content and a verdict written here would be read
        # before the roll that decided it. See SkillTestView.roll.
        await interaction.edit_original_response(
            content=breakdown,
            attachments=[dice_file],
            view=None,
        )
        # The die kept is the only one of the two that can ignite, and
        # its second die goes up between the roll and the verdict like
        # every other -- see post_volatile_ignition.
        await self.post_volatile_ignition(
            interaction, match, (offense_player.player_id, ignite),
        )
        await send_new_prompt(interaction, verdict)
        await self.refresh_match_image(interaction, game)

        if safe:
            self.persist(game, match)

        # **Both outcomes are new plays.** A conceded own goal restarts
        # from the kickoff space as any other goal does; avoiding one
        # is a stoppage too, not a play that carries on -- both sides
        # reset to their saved arrangement and the side with the ball
        # may declare. If this closes out last possession,
        # begin_run_back's own check ends the period here instead. See
        # "Own goal" in docs/living-rules.md.
        await self.begin_run_back(
            interaction,
            game,
            match,
            distance_moved=distance_moved,
            turnover_occurred=True,
            new_play=True,
        )

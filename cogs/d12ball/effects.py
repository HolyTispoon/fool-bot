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
    apply_own_goal_outcome,
    deflection_step,
    dribble_advance_step,
    dribble_burst_step,
    high_pass_step,
    low_pass_step,
    pressure_step,
    setup_pass_out_step,
    setup_pass_speed_step,
    setup_pass_step,
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
    SPECIES_TELEKINETIC,
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
    ball_space_phrase,
    contest_noun,
    format_goal_time,
    format_player_with_team,
    format_team_side_label,
    get_species_ability_emoji,
    send_new_prompt,
)
from cogs.d12ball_views import (
    DribbleAdvanceChoiceView,
    MindPullView,
    SmoothView,
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
        obstacle, at a token a space -- and the ball is left at 12,
        with nobody asked (the author, 2026-09-20), where a Dribble
        Advance offers a change of up to oSkill.

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
        Setup Pass, the High Pass gambit: **adjust ball speed up to
        the passer's offensive skill, and then** set up a scoring
        opportunity at 0, 1 or 3 spaces, with the speed benefit
        counting toward the shot.

        The card's own order, the continuation it leaves behind and
        what it says are `setup_pass_speed_step`'s; this is the save
        between the step and the prompt it hands to, which a restart
        between the two depends on.
        """
        result = setup_pass_speed_step(self.engine, match)
        self.persist(game, match)
        await self.dispatch_step_result(interaction, game, match, result)

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
        """
        The second half of the card: the ball goes where the coach
        picked, and what is standing there settles it --
        `setup_pass_step`.
        """
        result = setup_pass_step(self.engine, match, distance)
        self.persist(game, match)
        await self.dispatch_step_result(interaction, game, match, result)

    async def apply_setup_pass_out(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        The dead end a Setup Pass with nowhere to throw it reaches --
        `setup_pass_out_step`. Kept as a method because
        `offer_setup_pass_distance` reaches it directly when the menu
        has no distance to offer at all, which is the other half of
        the branch the pass itself can only meet from a stale click.
        """
        result = setup_pass_out_step(match)
        self.persist(game, match)
        await self.dispatch_step_result(interaction, game, match, result)

    async def apply_high_pass(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        distance: int,
    ) -> None:
        """
        Play the throw out -- `high_pass_step` -- and let the
        dispatcher settle what it found where the ball came down.

        Six endings, and the one thing this half decides about them is
        whether the board is written before the next step draws its
        own; see `follow_on_draws_the_board`.
        """
        result = high_pass_step(self.engine, match, distance)
        self.persist(game, match)
        await self.dispatch_step_result(interaction, game, match, result)

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
        if await self.check_for_ball_arrival(
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






    async def check_for_ball_arrival(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        resume: dict,
    ) -> bool:
        """
        **The one gate every ball arrival runs through.** Smooth first,
        then Mind Pull; True when either took over, so a caller is one
        `if ...: return` exactly as it was when Mind Pull was the whole
        of it.

        **Smooth is asked first, and that is a rule rather than an
        ordering convenience.** Both read the same `last_ball_path`,
        and a Smooth that is taken stops the ball short of where the
        movement was going -- so whichever is asked first decides
        whether the other is asked at all. Asking the possessing side
        first means their own Telekinetic can take the ball off a
        movement before an opponent's gets to reach for it -- the
        author, 2026-09-20, asked directly because the sheet settles
        what each half does and says nothing about the race.

        **The path is spent by `check_for_mind_pull`, which is the last
        reader**, so Smooth deliberately does not clear it -- a Smooth
        that nobody wanted must still leave the pull its movement.
        """
        if await self.check_for_smooth(interaction, game, match, resume):
            return True
        return await self.check_for_mind_pull(
            interaction, game, match, resume,
        )

    async def check_for_smooth(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        resume: dict,
    ) -> bool:
        """
        Did the ball just move to or through one of its **own** side's
        Telekinetics, who may take it over? The twin of
        `check_for_mind_pull`, and the same contract: True when the
        offer has been put and the caller should stop.

        **It does not spend the path.** `check_for_mind_pull` runs
        after it on the same movement and needs it -- see
        `check_for_ball_arrival`. That is the one way the two gates
        differ mechanically, and it is why they are not the same
        function with a side argument.
        """
        candidates = self.engine.smooth_candidates(game, match)
        if not candidates:
            return False

        match.pending_smooth = candidates
        match.pending_smooth_resume = resume
        self.persist(game, match)

        await self.continue_smooth(interaction, game, match)
        return True

    async def continue_smooth(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        Put the offer to the next Telekinetic the ball reached, or --
        when none are left -- hand the movement on to the pull, and
        then to the arrival this interrupted. **The one exit from the
        queue**, so a coach who declines and a Telekinetic who was
        never asked leave by the same door.

        **Dinky never takes a Smooth**, so an AI side's Telekinetics
        are skipped rather than prompted -- the same call as never
        ceding and never pulling. Taking the ball over moves who plays
        the next turn, which is a judgement, and Dinky makes none.

        Injured players are **not** skipped, unlike the pull's queue: a
        Smooth costs nothing, so there is no charge for an injured
        player to fail to pay.
        """
        while match.pending_smooth:
            player_id = match.pending_smooth[0]
            controller = self.engine.controlling_user_id(
                game, match, player_id,
            )
            if controller is None:
                match.pending_smooth.pop(0)
                self.persist(game, match)
                continue

            player = self.engine.get_player_definition(player_id)
            smooth_emoji = get_species_ability_emoji(
                self.species_ability_emojis, SPECIES_TELEKINETIC,
            )
            await send_new_prompt(
                interaction,
                f"{smooth_emoji} **Smooth** — the ball runs through "
                f"{self.player_label(match, player)}, who may take it "
                "over.",
                view=SmoothView(self, game.game_id, player_id),
            )
            return

        resume = match.pending_smooth_resume
        match.pending_smooth_resume = None
        self.persist(game, match)

        # Nobody took it, so the movement carries on to the opposing
        # side's pull -- the second half of `check_for_ball_arrival`,
        # reached here rather than there because the queue above may
        # have taken minutes to drain.
        if await self.check_for_mind_pull(
            interaction, game, match, resume or {},
        ):
            return
        await self.dispatch_arrival_resume(
            interaction, game, match, resume,
        )

    async def run_smooth(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        player_id: str,
    ) -> None:
        """
        One Telekinetic taking the ball over, off the button they were
        offered. There is no roll and nothing to charge, so this is the
        whole of it: stop the ball on them, and finish the maneuver.

        **A Smooth is not a turnover**, which is the one place it parts
        company with a landed pull. Possession never changed hands, so
        nobody runs back and the ball keeps the speed the maneuver gave
        it -- the turn simply ends with a different player holding it.

        **The arrival it pre-empted does not happen.** That is the rule
        the pull already follows -- what the movement was going to lead
        to is exactly what taking the ball early takes away -- and it
        is what makes an overshot Double Team safe: the own-goal roll
        the shove was about to ask for is never asked, because the ball
        is no longer sitting on the handler who would have rolled it
        (the author, 2026-09-20). What it does not drop is the clock:
        the maneuver that moved the ball still costs its space minute,
        which rides out in `distance_moved`.
        """
        player = self.engine.get_player_definition(player_id)
        if player_id in match.pending_smooth:
            match.pending_smooth.remove(player_id)

        resume = match.pending_smooth_resume
        match.pending_smooth_resume = None
        match.apply_smooth(player_id)
        self.persist(game, match)

        # **No refresh here.** Both branches below end in one of their
        # own -- `finish_maneuver_resolution` redraws the board as its
        # last act, and the run-back cascade batches to one refresh at
        # the end -- so drawing it now would be a second write to the
        # same five-in-five bucket for one click. See
        # docs/design/rate-limits.md.
        smooth_emoji = get_species_ability_emoji(
            self.species_ability_emojis, SPECIES_TELEKINETIC,
        )
        lead_in = (
            f"{smooth_emoji} **Smooth** — "
            f"{self.player_label(match, player)} takes the ball over on "
            f"{ball_space_phrase(match)}."
        )

        # **A turnover-driven arrival is the exception**, and the only
        # one. `begin_run_back` is not a question about where the ball
        # settles -- it is the consequence of a turnover that has
        # already happened -- so a Smooth cannot pre-empt it, it only
        # changes who is standing on the ball when everyone runs back.
        # The carrier this just set is the one who does not run back,
        # exactly as a landed pull arranges it.
        if (resume or {}).get("kind") == "run_back":
            await self.begin_run_back(
                interaction,
                game,
                match,
                distance_moved=resume.get("distance_moved", 1),
                turnover_occurred=resume.get("turnover_occurred", True),
                new_play=resume.get("new_play", False),
                speed_choice_after=resume.get("speed_choice_after", False),
                speed_reset=resume.get("speed_reset", True),
                lead_in=lead_in,
            )
            return

        await self.finish_maneuver_resolution(
            interaction,
            game,
            match,
            distance_moved=(resume or {}).get("distance_moved", 1),
            turnover_occurred=False,
            lead_in=lead_in,
        )

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

        A fifth, `apply_pressure`'s overshoot branch, is the one
        arrival that is neither a settling nor a turnover: the shove
        moved the ball and what it led to is an own-goal roll, so the
        pull has to be offered before the roll rather than after it --
        see the comment there for why `begin_run_back`'s gate is not
        enough on its own.

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
        # arrival point either. The movers go with it -- they are only
        # disqualified from the movement that moved them, so a second
        # movement in the same turn must find them eligible again.
        match.last_ball_path = []
        match.last_ball_movers = []
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
        never ceding, never declining a challenge and never taking a
        Smooth. In a solo game the ability is the human's alone, which is
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
            mind_pull_emoji = get_species_ability_emoji(
                self.species_ability_emojis, SPECIES_TELEKINETIC,
            )
            await send_new_prompt(
                interaction,
                f"{mind_pull_emoji} **Mind Pull** — the ball crossed "
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
        await self.dispatch_arrival_resume(
            interaction, game, match, resume,
        )

    async def dispatch_arrival_resume(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        resume: Optional[dict],
    ) -> None:
        """
        Put the turn back where the interrupt found it -- the twin of
        `dispatch_injury_resume`, and read the same way: the kind names
        the arrival, and the rest of the dict is the arguments that
        arrival needs.

        Named for the arrival rather than for Mind Pull because both
        gates now end here: a Smooth queue that drains hands on to the
        pull, and a pull queue that drains hands on to this.

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

        if kind == "own_goal":
            await self.begin_own_goal_roll(
                interaction,
                game,
                match,
                distance_moved=resume.get("distance_moved", 1),
                lead_in=resume.get("lead_in", ""),
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

        mind_pull_emoji = get_species_ability_emoji(
            self.species_ability_emojis, SPECIES_TELEKINETIC,
        )
        note = "\n".join(filter(None, (
            f"{mind_pull_emoji} **Mind Pull** — "
            f"{self.player_label(match, player)} reaches for the "
            f"ball{ignite_note}.",
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
                f"{ball_space_phrase(match)}."
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
        if await self.check_for_ball_arrival(
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

    async def apply_deflection(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        key: str,
    ) -> None:
        """
        The Discord half of a won Deflect or Clear: run the step, save
        what it did, then post and dispatch what it handed back.

        Four lines over `deflection_step`, which is where the distance,
        the speed drop, the Fullback's extra space, the overshoot that
        becomes a shot and a beaten Setup Pass's cost live -- see
        `apply_low_pass` for the shape and principle 9 in CLAUDE.md for
        why the save is here rather than inside the step.

        **Two saves became this one**, and neither was losing anything:
        `knock_ball_back` persisted the moved ball and the shot branch
        persisted again over the turnover it then applied, with nothing
        between them that could fail. The step no longer saves at all
        and the wrapper always does, which is the same state written
        the same number of times on every branch -- the rule, not rank
        O2's fix.

        **The board is not refreshed on two of the three branches**,
        and it was not before either: `begin_loose_ball` draws it under
        its own announcement. The step reports `board_changed=True`
        regardless, because the ball really did move; the write is
        suppressed by `FOLLOW_ONS_THAT_DRAW_THE_BOARD` in
        `dispatch_step_result`, which is where a rate-limit economy
        belongs -- see "Discord's rate limits" in
        docs/design/rate-limits.md.
        """
        result = deflection_step(self.engine, match, key)
        self.persist(game, match)
        await self.dispatch_step_result(interaction, game, match, result)

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

    async def apply_pressure(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        key: str,
    ) -> None:
        """
        The Discord half of a won Pressure or Double Team: run the
        step, save what it did, then post and dispatch what it handed
        back.

        Four lines over `pressure_step`, which is where the shove, the
        wording, the pair a Double Team leaves behind, the own-goal
        overshoot and a beaten Dribble Burst's cost live -- see
        `apply_low_pass` for the shape and principle 9 in CLAUDE.md
        for why the save is here rather than inside the step.

        **Two saves became this one**, and the overshoot branch lost a
        message with them. It used to persist, post the shove, refresh
        the board and only then ask for the own-goal roll; the
        narration is the result's now, so it opens that prompt instead
        and the branch costs one message where every other resolved
        maneuver already cost one -- see "Discord's rate limits" in
        docs/design/rate-limits.md.
        """
        result = pressure_step(self.engine, match, key)
        self.persist(game, match)
        await self.dispatch_step_result(interaction, game, match, result)

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

        # A gambit's effect can reach past its own maneuver, and a
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
        Run whatever a gambit's effect still owes once its last prompt
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
        lead_in: str = "",
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

        `lead_in` is the shove that overshot, which `pressure_step`
        hands over rather than posting: the effect has nothing further
        to say and this is where the turn stops, so the two are one
        message. It rides above the prompt with a blank line between,
        the way `begin_loose_ball` carries the pass that made the ball
        loose.

        **It gates the shove's own arrival first**, which is the one
        arrival no other gate reaches. `shove_pressured_handler` drove
        the ball back through `set_ball_space`, so the shove has a
        recorded path like any other ball movement, and what that
        movement led to is this roll -- so a Smooth or a pull is owed
        *before* it, since "a pull that lands pre-empts whatever the
        movement would have led to". Left to `begin_run_back`'s gate at
        the far end it was both too late to pre-empt the roll and, when
        the own goal is conceded, never reached with the path intact at
        all: `restart_after_goal` clears it on the way to the kickoff.

        It sits here rather than in `apply_pressure` because
        `pressure_step` is the model's now and cannot ask a gate -- so
        the arrival gates itself, the way the other four do, and any
        later caller gets it for free. **Above `pending_own_goal`**, so
        a restart mid-offer reads the offer rather than the roll; a
        decline comes back through the `"own_goal"` resume kind and
        finds the path spent, so this reading is a no-op the second
        time. A Smooth that is taken never returns here at all, which
        is the whole of "there is no own goal risk" (the author,
        2026-09-20).

        **Only a Double Team can arrive with a path.** A plain Pressure
        overshoots only from the space closest to the offense's own
        goal, where the handler does not move and `ball_path_to`
        answers empty for a move that goes nowhere.
        """
        if await self.check_for_ball_arrival(
            interaction,
            game,
            match,
            {
                "kind": "own_goal",
                "distance_moved": distance_moved,
                "lead_in": lead_in,
            },
        ):
            return

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

        prefix = f"{lead_in}\n\n" if lead_in else ""
        prompt_message = await send_new_prompt(
            interaction,
            f"{prefix}**Own goal risk!** {mention}, "
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
        verdict = apply_own_goal_outcome(
            self.engine, match, offense_player, distance_moved, safe,
            exhaustion_text,
        )
        # The step settled it; this writes it down, on both branches
        # and before anything is posted. The conceded branch used to
        # save inside the step and the avoided one two messages later,
        # which is the shape principle 9 exists to collapse.
        self.persist(game, match)

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

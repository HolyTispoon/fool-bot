"""
The entry points into a maneuver's effect, and the dice a coach is
shown.

**Nothing here decides anything.** Every method below is one of two
shapes: it calls one flow step in `d12ball/flow/` and hands the result
to the dispatcher, or it names one step by its `FollowOnStep` and hands
*that* to the dispatcher -- `D12Ball.run_step`. The decisions those
steps used to be interleaved with (does anybody choose, what Dinky
picks, what a card with nowhere to go does) are the `offer_*` steps in
`d12ball/flow/effects.py` since Phase 6 of docs/model-discord-split.md.

What is left that is genuinely Discord's: the two dice images the
own-goal roll and the Mind Pull put between their two sentences.
"""

import asyncio
import discord
from typing import Optional

from d12ball.flow import FollowOnStep, StepResult
from d12ball.flow.arrivals import (
    attempt_mind_pull_step,
    begin_shooter_choice,
    continue_mind_pull,
    continue_smooth,
    decline_scoring_attempt,
    dispatch_arrival_resume,
    offer_scoring_attempt_choice,
)
from d12ball.flow.effects import (
    deflection_step,
    dribble_advance_step,
    dribble_burst_step,
    high_pass_step,
    low_pass_step,
    offer_dribble_advance,
    offer_dribble_burst,
    offer_high_pass,
    offer_low_pass,
    offer_setup_pass_distance,
    own_goal_roll_step,
    pressure_step,
    setup_pass_out_step,
    setup_pass_push_back_step,
    setup_pass_speed_step,
    setup_pass_step,
    speed_choice_step,
    steal_step,
    take_smooth_step,
)
from d12ball.prompts import loose_ball_pick_prompt
from d12ball.components import MatchState
from d12ball.game import D12BallGame, team_display_name
from d12ball.render import (
    TEAM_COLORS,
    render_mind_pull_die,
    render_own_goal_dice,
)
from cogs.d12ball_helpers import send_new_prompt


class ManeuverEffectsMixin:
    """
    The entry points into a maneuver's effect, and the dice a coach is
    shown.
    """

    # -- Low Pass --------------------------------------------------

    async def resolve_skilled_pass(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """A won Skilled Pass -- `offer_low_pass` with the gambit's key."""
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
        """A won Low Pass -- `d12ball.flow.effects.offer_low_pass`."""
        await self.dispatch_step_result(
            interaction,
            game,
            match,
            offer_low_pass(self.engine, game, match, key=key, free=free),
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
        The Discord half of a won Low Pass: run the step and dispatch
        what it handed back. The shape every entry point here takes --
        the dispatcher saves once, after the run (principle 9).
        """
        result = low_pass_step(
            self.engine,
            match,
            distance,
            receiver_id=receiver_id,
            key=key,
            free=free,
        )
        await self.dispatch_step_result(interaction, game, match, result)

    # -- Dribble Advance ---------------------------------------------

    async def resolve_dribble_advance(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        await self.dispatch_step_result(
            interaction, game, match,
            offer_dribble_advance(self.engine, game, match),
        )

    async def apply_dribble_advance(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        distance: int,
    ) -> None:
        result = dribble_advance_step(self.engine, game, match, distance)
        await self.dispatch_step_result(interaction, game, match, result)

    async def resolve_dribble_burst(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        await self.dispatch_step_result(
            interaction, game, match,
            offer_dribble_burst(self.engine, game, match),
        )

    async def apply_dribble_burst(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        distance: int,
    ) -> None:
        result = dribble_burst_step(self.engine, game, match, distance)
        await self.dispatch_step_result(interaction, game, match, result)

    # -- High Pass -----------------------------------------------------

    async def resolve_high_pass(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        await self.dispatch_step_result(
            interaction, game, match,
            offer_high_pass(self.engine, game, match),
        )

    async def resolve_setup_pass(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """Setup Pass, the High Pass gambit -- its speed step first."""
        result = setup_pass_speed_step(self.engine, match)
        await self.dispatch_step_result(interaction, game, match, result)

    async def offer_setup_pass_distance(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        await self.dispatch_step_result(
            interaction, game, match,
            offer_setup_pass_distance(self.engine, game, match),
        )

    async def apply_setup_pass(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        distance: int,
    ) -> None:
        result = setup_pass_step(self.engine, match, distance)
        await self.dispatch_step_result(interaction, game, match, result)

    async def apply_setup_pass_out(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        result = setup_pass_out_step(match)
        await self.dispatch_step_result(interaction, game, match, result)

    async def apply_high_pass(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        distance: int,
    ) -> None:
        result = high_pass_step(self.engine, match, distance)
        await self.dispatch_step_result(interaction, game, match, result)

    async def begin_high_pass_contest(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        distance_moved: int,
        lead_in: str = "",
    ) -> None:
        await self.run_step(
            interaction,
            game,
            match,
            FollowOnStep.BEGIN_HIGH_PASS_CONTEST,
            lead_in=lead_in,
            distance_moved=distance_moved,
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
        result = offer_scoring_attempt_choice(
            self.engine,
            game,
            match,
            shooter_id=shooter_id,
            distance_moved=distance_moved,
            lead_in=lead_in,
            contest_on_decline=contest_on_decline,
        )
        await self.dispatch_step_result(interaction, game, match, result)

    async def decline_scoring_attempt(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        distance_moved: int,
        contest: bool = False,
    ) -> None:
        result = decline_scoring_attempt(
            self.engine, game, match, distance_moved, contest=contest,
        )
        await self.dispatch_step_result(interaction, game, match, result)

    # -- The arrival gates' exits -------------------------------------

    async def continue_smooth(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        result = continue_smooth(self.engine, game, match)
        await self.dispatch_step_result(interaction, game, match, result)

    async def continue_mind_pull(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        result = continue_mind_pull(self.engine, game, match)
        await self.dispatch_step_result(interaction, game, match, result)

    async def run_smooth(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        player_id: str,
    ) -> None:
        result = take_smooth_step(
            self.engine, game, match, player_id=player_id,
        )
        await self.dispatch_step_result(interaction, game, match, result)

    async def dispatch_arrival_resume(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        resume: Optional[dict],
    ) -> None:
        result = dispatch_arrival_resume(self.engine, game, match, resume)
        await self.dispatch_step_result(interaction, game, match, result)

    async def post_mind_pull_die(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        roll,
        result: StepResult,
    ) -> None:
        """
        The die a Mind Pull rolled, where the offer was, and then what
        it came to.

        **The die goes between the offer and the result.** A message's
        attachments render below its content, so a result written on
        the same message would be read before the roll that decided
        it. The offer becomes the die and what it came to is said in
        the message after -- the same way round as every other roll in
        the game; see `SkillTestView.roll`. A player injured between
        being queued and answering rolls nothing (`roll` is None), and
        the queue simply carries on.

        The match is already written: the caller saved after the
        roll, and the dispatcher below saves once more after the run,
        which is the same state.
        """
        if roll is None:
            await self.dispatch_step_result(interaction, game, match, result)
            return

        player = self.engine.get_player_definition(roll.player_id)
        player_team = match.team_for_player(roll.player_id)
        dice_file = discord.File(
            await asyncio.to_thread(
                render_mind_pull_die,
                roll.roll,
                TEAM_COLORS[player_team],
                team_display_name(player_team),
                player.name,
                roll.pulled,
            ),
            filename="mind_pull_die.png",
        )
        await interaction.edit_original_response(
            content=None,
            attachments=[dice_file],
            view=None,
        )
        # Asked for the reason the ignite is asked at all: Volatile is
        # a Fire Demon's and this is a Telekinetic's roll, so this
        # posts nothing today -- and the day a card carries both, the
        # second die is shown here rather than being the one roll in
        # the game that swallows it.
        await self.post_volatile_ignition(
            interaction, match, (roll.player_id, roll.ignite),
        )

        if not roll.pulled:
            await send_new_prompt(interaction, result.narration[0])
            await self.dispatch_step_result(
                interaction,
                game,
                match,
                StepResult(
                    narration=result.narration[1:],
                    board_changed=result.board_changed,
                    next=result.next,
                ),
            )
            return

        # A landed pull reads like the turnover it is, and its lines
        # open the run back's own message rather than standing above
        # it -- one message and one board refresh, which is the
        # batching every resolved maneuver already gets.
        await self.dispatch_step_result(
            interaction,
            game,
            match,
            StepResult(
                narration=result.narration,
                board_changed=result.board_changed,
                next=result.next,
            ),
        )

    async def run_mind_pull(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        player_id: str,
    ) -> None:
        """
        One Telekinetic's attempt, as an entry point --
        `d12ball.flow.arrivals.attempt_mind_pull_step` and the die.
        """
        roll, result = attempt_mind_pull_step(
            self.engine, game, match, player_id=player_id,
        )
        self.persist(game, match)
        await self.post_mind_pull_die(interaction, game, match, roll, result)

    # -- Loose ball ----------------------------------------------------

    def build_loose_ball_view(
        self,
        game_id: str,
        match: MatchState,
    ) -> Optional[discord.ui.View]:
        """
        The loose-ball pick prompt for the one side currently on the
        clock, as a view -- `d12ball.prompts.loose_ball_pick_prompt`'s
        answer through `view_for_prompt`, and None once the contest is
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
        The loose ball, as an entry point. The step is
        `d12ball.flow.arrivals.begin_loose_ball`, and the dispatcher
        stops on it to name and draw the position together
        (`D12Ball.post_stop`).
        """
        await self.run_step(
            interaction,
            game,
            match,
            FollowOnStep.BEGIN_LOOSE_BALL,
            lead_in=lead_in,
            distance_moved=distance_moved,
            headline=headline,
            is_high_pass=is_high_pass,
        )

    async def resolve_loose_ball(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        lead_in: str = "",
    ) -> None:
        await self.run_step(
            interaction,
            game,
            match,
            FollowOnStep.RESOLVE_LOOSE_BALL,
            lead_in=lead_in,
        )

    async def begin_shooter_choice(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        candidates: list[str],
        lead_in: str = "",
    ) -> None:
        result = begin_shooter_choice(
            self.engine, game, match, candidates, lead_in=lead_in,
        )
        await self.dispatch_step_result(interaction, game, match, result)

    async def start_set_up_shot(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        shooter_id: str,
        maneuver_cost: int = 1,
    ) -> None:
        """
        Take a scoring opportunity, as an entry point --
        `d12ball.flow.arrivals.take_scoring_opportunity` under the
        name the automatic routes reach it by.
        """
        await self.run_step(
            interaction,
            game,
            match,
            FollowOnStep.START_SET_UP_SHOT,
            shooter_id=shooter_id,
            maneuver_cost=maneuver_cost,
        )

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
        await self.apply_deflection(interaction, game, match, "clear")

    async def apply_deflection(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        key: str,
    ) -> None:
        result = deflection_step(self.engine, match, key)
        await self.dispatch_step_result(interaction, game, match, result)

    async def offer_setup_pass_push_back(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        lead_in: str = "",
    ) -> None:
        await self.run_step(
            interaction,
            game,
            match,
            FollowOnStep.OFFER_SETUP_PASS_PUSH_BACK,
            lead_in=lead_in,
        )

    async def apply_setup_pass_push_back(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        distance: int,
        lead_in: str = "",
    ) -> None:
        result = setup_pass_push_back_step(
            self.engine, game, match, distance=distance,
        )
        if lead_in:
            result.narration[0] = f"{lead_in}\n\n{result.narration[0]}"
        await self.dispatch_step_result(interaction, game, match, result)

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
        await self.apply_steal(interaction, game, match, "intercept")

    async def apply_steal(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        key: str,
    ) -> None:
        result = steal_step(self.engine, match, key)
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
        await self.apply_pressure(interaction, game, match, "double_team")

    async def apply_pressure(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        key: str,
    ) -> None:
        result = pressure_step(self.engine, match, key)
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
        await self.run_step(
            interaction,
            game,
            match,
            FollowOnStep.OFFER_SPEED_CHOICE,
            lead_in=lead_in,
            player_id=player_id,
            skill_type=skill_type,
            turnover_occurred=turnover_occurred,
            distance_moved=distance_moved,
        )

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
        result = speed_choice_step(
            self.engine,
            game,
            match,
            target_speed=target_speed,
            turnover_occurred=turnover_occurred,
            distance_moved=distance_moved,
        )
        if lead_in:
            result.narration[0] = f"{lead_in}\n\n{result.narration[0]}"
        # Its own message: the new speed is the answer to the question
        # this click was, and what follows it is the next event.
        await self.post_then_dispatch(interaction, game, match, result)

    async def continue_effect(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        distance_moved: int = 1,
        turnover_occurred: bool = False,
    ) -> None:
        await self.run_step(
            interaction,
            game,
            match,
            FollowOnStep.CONTINUE_EFFECT,
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
        await self.run_step(
            interaction,
            game,
            match,
            FollowOnStep.BEGIN_OWN_GOAL_ROLL,
            lead_in=lead_in,
            distance_moved=distance_moved,
        )

    async def own_goal_roll_file(
        self,
        match: MatchState,
        rolls: tuple[int, int],
        safe: bool,
        overdrive: int = 0,
    ) -> discord.File:
        """
        The two dice an own-goal roll produced, drawn.

        **The arithmetic that produced them is not here any more**: it
        is `own_goal_roll_step`'s narration, because it is a sentence
        about the position and the wording rules are rules (principle
        5). This is the picture alone, which is the one half a web app
        would not want.

        Drawn in a worker thread for the same reason the board is.
        """
        offense_setup = match.setup_for_side(match.ball.possession)
        return discord.File(
            await asyncio.to_thread(
                render_own_goal_dice,
                list(rolls),
                TEAM_COLORS[offense_setup.team],
                safe,
                bool(overdrive),
            ),
            filename="own_goal_dice.png",
        )

    async def post_own_goal_dice(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        roll,
        result: StepResult,
    ) -> None:
        """
        The own-goal roll's dice, between its two lines.

        **Bespoke, because the image goes between the two lines.** The
        step hands back its arithmetic and its verdict in order; a
        message's attachments render below its content, so a verdict
        written above the roll would be read before it. The prompt
        becomes the dice, taking its own explanation with it once the
        roll it was asking for has happened -- the same trade a score
        attempt makes. See `SkillTestView.roll`.
        """
        offense_player = self.engine.get_player_definition(
            match.active_player_id,
        )
        dice_file = await self.own_goal_roll_file(
            match, roll.rolls, roll.safe, roll.overdrive,
        )
        breakdown, verdict = result.narration

        await interaction.edit_original_response(
            content=breakdown,
            attachments=[dice_file],
            view=None,
        )
        # The die kept is the only one of the two that can ignite, and
        # its second die goes up between the roll and the verdict like
        # every other -- see post_volatile_ignition.
        await self.post_volatile_ignition(
            interaction, match, (offense_player.player_id, roll.ignite),
        )
        await send_new_prompt(interaction, verdict)
        await self.dispatch_step_result(
            interaction,
            game,
            match,
            StepResult(board_changed=result.board_changed, next=result.next),
        )

    async def run_own_goal_roll(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        The own-goal roll, as an entry point --
        `d12ball.flow.effects.own_goal_roll_step`, which rolls, charges
        the token, logs the attempt and settles the outcome.

        **Saved before the dice are drawn, deliberately.** A render or
        an upload sits between this save and the dispatcher's, and
        either can fail; the roll is settled, and a failed post must
        not let the next click roll it again.
        """
        roll, result = own_goal_roll_step(self.engine, game, match)
        self.persist(game, match)
        await self.post_own_goal_dice(interaction, game, match, roll, result)

"""
The three ways possession changes hands: the run back after a steal,
the time out that buys both coaches a Coaching Choice, and the pickup
after a ball has gone out. See "Turnovers: steals and new plays" and
"The time out" in docs/design/time-out.md.
"""

import asyncio
import discord
import io
from typing import Optional

from d12ball.components import (
    CoachingOccasion,
    MatchState,
    TeamSide,
)
from d12ball.flow import FollowOnStep
from d12ball.flow.windows import (
    apply_position_swap,
    apply_reposition,
    apply_substitution,
    begin_time_out,
    coaching_summary,
    coaching_window_note,
    cover_kickoff_space,
    finish_time_out,
    run_ai_substitution_window,
)
from d12ball.flow.turnovers import (
    begin_ball_recovery,
    run_back_space_ask,
)
from d12ball.game import (
    D12BallGame,
    Formation,
)
from d12ball.render import render_coaching_image
from gamesaves.d12ball.storage import save_games
from cogs.d12ball_helpers import (
    LOGGER,
    send_new_prompt,
)
from cogs.d12ball_views import (
    CoachingHubView,
    CoachingOfferView,
)


class TurnoverMixin:
    """
    The three ways possession changes hands: the run back after a steal,
    """

    # -- Run-back (after a turnover) ----------------------------------




    def apply_substitution(
        self,
        game: D12BallGame,
        match: MatchState,
        side: TeamSide,
        outgoing_player_id: str,
        incoming_player_id: str,
    ) -> str:
        """
        Make one swap and describe it -- a forwarding method over
        `d12ball.flow.windows.apply_substitution`, kept because
        `CoachingSubstitutionInView` calls it directly.
        """
        return apply_substitution(
            self.engine,
            game,
            match,
            side,
            outgoing_player_id,
            incoming_player_id,
        )

    def apply_position_swap(
        self,
        match: MatchState,
        side: TeamSide,
        player_id: str,
        other_player_id: str,
    ) -> str:
        """
        A forwarding method over
        `d12ball.flow.windows.apply_position_swap`, which is where the
        Coaching Choice's zone assignment went in Phase 6. Kept so no
        call site moved -- the shape `team_emojis` took in Phase 1a.
        """
        return apply_position_swap(
            self.engine, match, side, player_id, other_player_id,
        )

    def apply_reposition(
        self,
        match: MatchState,
        side: TeamSide,
        player_id: str,
        space_index: int,
        swap_with: Optional[str] = None,
    ) -> str:
        """
        A forwarding method over
        `d12ball.flow.windows.apply_reposition`, the Coaching Choice's
        space positioning. `apply_position_swap` above for why it is
        still here.
        """
        return apply_reposition(
            self.engine, match, side, player_id, space_index, swap_with,
        )

    async def coaching_file(
        self,
        game: D12BallGame,
        match: MatchState,
        side: TeamSide,
    ) -> discord.File:
        """
        The coach's own half of the field, as an attachment for their
        Coaching Choice message. Rendered in a worker thread like every
        other image: Pillow is pure CPU and the event loop is shared by
        every game at once.

        **This is the Coaching Choice's picture and nothing else's.**
        It shows one side's row and leaves the ball off, which is right
        for arranging your own team with play stopped and wrong for
        reading a live position -- the prompts that ask about one carry
        the field strip instead, through `send_field_prompt`.
        """
        png = await asyncio.to_thread(
            render_coaching_image,
            match,
            self.player_catalog,
            side,
            self.engine.coaching_title(match, side),
            species_icons=self.engine.species_abilities_apply(game),
            cyborg_ids=self.cyborg_condition_ids(game, match),
        )
        return discord.File(
            io.BytesIO(png.getvalue()),
            filename=f"d12ball-coaching-{game.game_number}.png",
        )

    def coaching_window_note(
        self,
        match: MatchState,
        side: TeamSide,
        occasion: CoachingOccasion,
        is_response: bool,
        restored: bool,
    ) -> str:
        """
        The line under a coaching prompt -- a forwarding method over
        `d12ball.flow.windows.coaching_window_note`.
        """
        return coaching_window_note(
            self.engine, match, side, occasion, is_response, restored,
        )

    async def begin_substitution_window(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        side: TeamSide,
        occasion: CoachingOccasion = CoachingOccasion.NEW_PLAY,
        is_response: bool = False,
        lead_in: str = "",
    ) -> None:
        """
        Open a coaching window, as an entry point. The step is
        `d12ball.flow.windows.begin_substitution_window` -- the
        tutorial's explainer and its gate, the arrangement restore,
        the window itself, and either the coach's prompt or an AI
        side's whole routine. The picture on the prompt is
        `render_prompt`'s, keyed on the kind.

        `lead_in` here is the window's own opening line and goes
        *inside* the prompt (`RulesEngine.coaching_prompt` puts it
        above the allowance), which is why it is passed as `heading`.
        """
        await self.run_step(
            interaction,
            game,
            match,
            FollowOnStep.BEGIN_SUBSTITUTION_WINDOW,
            side=TeamSide(side),
            occasion=CoachingOccasion(occasion),
            is_response=is_response,
            heading=lead_in,
        )

    async def repost_coaching_prompt(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> str:
        """
        Put an already-open Coaching Choice back in front of its coach,
        image and all, without touching the window itself.

        Deliberately not `begin_substitution_window`, which is the
        *opening* of a window: that calls `open_coaching_window` and
        resets the substitution counter, so resuming through it would
        hand a coach back the swaps they had already spent. Everything
        here reads the window as saved.

        The image is re-sent because a Coaching Choice is unreadable
        without it -- exhaustion counts, the Exhausted and Injured
        badges and which bench a player sits on are drawn nowhere else
        (see "Working on the board image" in docs/design/board-image.md).
        """
        side = TeamSide(match.pending_coaching_side)

        if self.engine.side_is_ai(game, side):
            # No menu to put back up: the AI's window is a routine that
            # runs to completion, and a restart in the middle of one
            # leaves nobody to click anything. Run it, as
            # begin_substitution_window would have.
            await self.run_ai_substitution_window(interaction, game, match)
            return "the AI's Coaching Choice"

        view = (
            CoachingHubView(self, game.game_id)
            if match.pending_coaching_declared
            else CoachingOfferView(self, game.game_id)
        )
        prompt = await send_new_prompt(
            interaction,
            self.engine.coaching_prompt(
                game,
                match,
                side,
                "Picking this up where it left off. Nothing you "
                "had already done has been undone.",
            ),
            file=await self.coaching_file(game, match, side),
            view=view,
            allowed_mentions=discord.AllowedMentions(
                users=True, roles=False, everyone=False,
            ),
        )
        game.turn_message_id = prompt.id
        save_games(self.games)
        return "the open Coaching Choice"

    async def resume_pending_prompt(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> str:
        """
        Put the game back in front of whoever it is waiting on, and say
        what that was. See `/d12ball resume`.

        A restart only ever re-arms **one** message per game, the one
        recorded in `turn_message_id`, so a game that lost that message
        -- deleted by `close_maneuver_prompt` once both sides had
        picked, or never recorded because the process died before the
        prompt was sent -- comes back with nothing live in its channel
        at all. This posts a new one.

        The states worth separating out are the ones whose next step
        was **the bot's**, not a coach's. A restart mid-cascade is what
        strands a game hardest: `continue_run_back`, the halftime
        sequence and the setup sequence are all driven from a live
        interaction, so a process that dies between two of their steps
        leaves state that nothing will ever pick up and no button to
        press. Each is handed back to the routine that drives it, which
        picks up exactly where it stopped. Everything else owes a
        click, and gets `pending_turn_view` on a fresh message -- the
        same view a restart would have re-attached.

        Nothing here changes the match. That is what `force` is for.
        """
        if game.tutorial_gate:
            # A note held behind Continue outranks every state below:
            # the position underneath is exactly what it was before
            # the note went up, and re-driving it would run the thing
            # the note is explaining without the note. The gate is a
            # prompt (`PromptKind.TUTORIAL_CONTINUE`), so it comes back
            # the way every other click does.
            view, ask = self.pending_turn_view(game.game_id, match)
            prompt = await send_new_prompt(interaction, ask, view=view)
            game.turn_message_id = prompt.id
            save_games(self.games)
            return "a tutorial note, re-posted above"

        if match.pending_shootout and not match.pending_injury_tests:
            # Two of the shootout's four steps are the bot's own -- the
            # reveal, and setting the next test up -- so a process that
            # died between them leaves nothing to click. advance_shootout
            # picks up whichever it stopped on. An owed injury check is
            # the exception: that is a button, and it comes first.
            await self.advance_shootout(interaction, game, match)
            return "the extreme shootout"

        if match.pending_coaching_side is not None:
            # Ahead of the three stage checks below: setup, halftime
            # and full time all run their coaching through this same
            # window, and their own routines would re-open it.
            return await self.repost_coaching_prompt(interaction, game, match)

        if match.pending_setup_stage is not None:
            await self.advance_setup_stage(interaction, game, match)
            return "the pre-kickoff Coaching Choice"

        if match.pending_halftime_stage is not None:
            await self.advance_halftime_stage(interaction, game, match)
            return "halftime"

        if match.pending_full_time_stage is not None:
            # The other side's window, or the shootout itself: either
            # way the next step was the bot's, and a process that died
            # between the two coaches left nothing to click.
            await self.advance_full_time_stage(interaction, game, match)
            return "the Coaching Choice before the shootout"

        if match.pending_time_out:
            # Both windows have closed -- the branch above would have
            # caught one still open -- so what is left is the tail, and
            # that was the bot's own next step.
            await self.finish_time_out(interaction, game, match)
            return "the time out"

        if match.pending_run_back:
            await self.continue_run_back(interaction, game, match)
            return "the run back"

        if match.pending_ball_recovery:
            await self.begin_ball_recovery(interaction, game, match)
            return "the out-of-bounds pickup"

        view, ask = self.pending_turn_view(game.game_id, match)
        prompt = await send_new_prompt(
            interaction,
            ask,
            view=view,
            allowed_mentions=discord.AllowedMentions(
                users=True, roles=False, everyone=False,
            ),
        )
        game.turn_message_id = prompt.id
        save_games(self.games)
        return "a choice, re-posted above"




    def coaching_summary(
        self,
        match: MatchState,
        side: TeamSide,
    ) -> list[str]:
        """
        What the open window changed, a line each -- a forwarding
        method over `d12ball.flow.windows.coaching_summary`, kept
        because `CoachingHubView` builds its closing message from it.
        """
        return coaching_summary(self.engine, match, side)

    async def run_ai_substitution_window(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        lead_in: str = "",
    ) -> None:
        """
        An AI side's whole window, start to finish --
        `d12ball.flow.windows.run_ai_substitution_window`. A second
        caller is `repost_coaching_prompt`: there is no menu to put
        back up after a restart, so the routine is simply run.
        """
        result = run_ai_substitution_window(
            self.engine, game, match, lead_in,
        )
        await self.post_blocks_then_dispatch(
            interaction, game, match, result,
        )

    def cover_kickoff_space(
        self,
        match: MatchState,
        side: TeamSide,
    ) -> Optional[str]:
        """
        Put one of an AI side's meeples on their own kickoff space --
        a forwarding method over
        `d12ball.flow.windows.cover_kickoff_space`.
        """
        return cover_kickoff_space(self.engine, match, side)

    async def finish_substitution_window(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        Hand the window on, or give up on it and let the run back go
        ahead -- `d12ball.flow.windows.finish_substitution_window`,
        which is the junction all five occasions come back through.
        """
        await self.run_step(
            interaction, game, match, FollowOnStep.FINISH_SUBSTITUTION_WINDOW,
        )

    # -- Ceding the ball to coach --------------------------------------

    async def begin_time_out(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        The side in possession stops play to coach -- the step is
        `d12ball.flow.windows.begin_time_out`. The caller has
        acknowledged the interaction and is responsible for the prompt
        the click came from, which is what `drop_turn_prompt` here
        settles.
        """
        result = begin_time_out(self.engine, game, match)
        self.persist(game, match)

        await self.drop_turn_prompt(interaction, game)
        await self.dispatch_step_result(interaction, game, match, result)

    async def finish_time_out(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        The tail of a time out, once both coaches have closed their
        windows -- `d12ball.flow.windows.finish_time_out`. Also what
        `/d12ball resume` hands a stranded one back to.
        """
        result = finish_time_out(self.engine, game, match)
        await self.dispatch_step_result(interaction, game, match, result)

    async def begin_run_back(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        distance_moved: int = 1,
        turnover_occurred: bool = True,
        new_play: bool = False,
        speed_choice_after: bool = False,
        speed_reset: bool = True,
        lead_in: str = "",
    ) -> None:
        """
        A turnover's run back, as an entry point. The step is
        `d12ball.flow.turnovers.begin_run_back`; a new play's board is
        posted and pinned by the dispatcher (`D12Ball.post_stop`) off
        the result's `new_play`.
        """
        await self.run_step(
            interaction,
            game,
            match,
            FollowOnStep.BEGIN_RUN_BACK,
            lead_in=lead_in,
            distance_moved=distance_moved,
            turnover_occurred=turnover_occurred,
            new_play=new_play,
            speed_choice_after=speed_choice_after,
            speed_reset=speed_reset,
        )

    async def announce_run_back(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        lead_in: str = "",
        speed_reset: bool = True,
    ) -> None:
        """The "Players run back!" note and the cascade behind it."""
        await self.run_step(
            interaction,
            game,
            match,
            FollowOnStep.ANNOUNCE_RUN_BACK,
            lead_in=lead_in,
            speed_reset=speed_reset,
        )

    def run_back_space_prompt(
        self,
        game: D12BallGame,
        match: MatchState,
        side: TeamSide,
        player_id: str,
        mention: str,
    ) -> str:
        """
        Where does this player run back to, worded -- a forwarding
        method over `d12ball.flow.turnovers.run_back_space_ask`.
        """
        return run_back_space_ask(
            self.engine, game, match, side, player_id, mention,
        )

    async def finish_run_back(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        lead_in: str = "",
    ) -> None:
        """
        Nobody is displaced on either side: clear the run back and
        hand the turn on to whatever it was still holding up --
        `d12ball.flow.turnovers.finish_run_back`.
        """
        await self.run_step(
            interaction, game, match, FollowOnStep.FINISH_RUN_BACK,
            lead_in=lead_in,
        )

    async def continue_run_back(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        lead_in: str = "",
    ) -> None:
        """
        Drive the cascade -- `d12ball.flow.turnovers.continue_run_back`,
        which batches the automatic placements into one block. What
        used to be here, the batching and the per-pass persist, is
        the driver's: one message, one board, one save.
        """
        await self.run_step(
            interaction, game, match, FollowOnStep.CONTINUE_RUN_BACK,
            lead_in=lead_in,
        )

    # -- Out-of-bounds recovery (after the run back) ------------------

    async def begin_ball_recovery(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        lead_in: str = "",
    ) -> None:
        """
        The pickup an out-of-bounds ball, or a time out, still owes --
        `d12ball.flow.turnovers.begin_ball_recovery`.
        """
        result = begin_ball_recovery(self.engine, game, match, lead_in=lead_in)
        await self.dispatch_step_result(interaction, game, match, result)

    async def apply_ball_recovery(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        player_id: str,
        lead_in: str = "",
    ) -> None:
        """
        Send somebody after an out-of-bounds ball --
        `d12ball.flow.turnovers.recover_ball_step`, its own message.
        """
        await self.run_step(
            interaction,
            game,
            match,
            FollowOnStep.APPLY_BALL_RECOVERY,
            lead_in=lead_in,
            player_id=player_id,
        )

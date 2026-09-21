"""
The clock and everything hanging off the end of it: the tail of a
maneuver, the period whistle, halftime, the window before the
shootout, and the shootout itself.
"""

import discord

from d12ball.components import (
    MatchState,
    TeamSide,
)
from d12ball.flow import FollowOn, FollowOnStep
from d12ball.flow.arrivals import finish_maneuver_resolution
from d12ball.flow.periods import (
    advance_full_time_stage,
    advance_halftime_stage,
    advance_setup_stage,
    advance_shootout,
    begin_full_time_coaching,
    begin_halftime,
    begin_halftime_extra_token,
    begin_halftime_substitutions,
    begin_setup_coaching,
    begin_shootout,
    continue_shootout,
    end_period,
    finish_full_time_coaching,
    finish_halftime,
    finish_setup_coaching,
    goal_log,
    shootout_order_text,
)
from d12ball.game import D12BallGame
from d12ball import tutorial
from gamesaves.d12ball.storage import save_games
from cogs.d12ball_helpers import (
    add_full_image_button,
    send_new_prompt,
)
from cogs.d12ball_views import RematchView


class PeriodMixin:
    """
    The clock and everything hanging off the end of it: the tail of a
    """

    # -- Clock, period transitions, and the turn loop -----------------

    async def finish_maneuver_resolution(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        distance_moved: int = 1,
        turnover_occurred: bool = False,
        lead_in: str = "",
    ) -> None:
        """
        The Discord half of the tail of every maneuver-effect path.

        The step is `d12ball.flow.arrivals.finish_maneuver_resolution`
        -- the clock, the period, the two gates it opens with and the
        line that says where the ball ended up. What is left here is
        the persist, the board, and the snapshot the offensive choice
        is handed back under.

        **The snapshot is the one bespoke piece.** The board is drawn
        once and uploaded twice -- onto the persistent message and onto
        the snapshot under the closing line -- which is a request the
        rate-limit gate counts, so it is decided here rather than
        through `dispatch_step_result`'s ordinary redraw. See
        "Discord's rate limits" in docs/design/rate-limits.md.
        """
        result = finish_maneuver_resolution(
            self.engine,
            game,
            match,
            distance_moved=distance_moved,
            turnover_occurred=turnover_occurred,
            lead_in=lead_in,
        )
        self.persist(game, match)

        following = result.next
        if not (
            isinstance(following, FollowOn)
            and following.step is FollowOnStep.SEND_TURN_PROMPT
        ):
            await self.dispatch_step_result(
                interaction, game, match, result,
            )
            return

        # One last board refresh with everything settled (run-back,
        # speed choice, own-goal, etc. may have landed after the last
        # refresh inside the effect itself), right before the offensive
        # choice comes back up. The snapshot below is that same board,
        # so it is drawn once and uploaded twice.
        png = await self.render_match_png(game)
        await self.refresh_match_image(interaction, game, png=png)
        # **Two messages, not one.** The step hands back its lines in
        # the order they were said, and the last of them is the one
        # that goes under the board -- an earlier line is the
        # last-possession announcement, which is its own beat and was
        # its own message before the lift. How lines go together is the
        # frontend's (principle 8), and this is that decision.
        if len(result.narration) > 1:
            await send_new_prompt(
                interaction, " ".join(result.narration[:-1]),
            )
        snapshot = await send_new_prompt(
            interaction,
            result.narration[-1],
            file=self.match_file_from_png(game, png),
        )
        await add_full_image_button(snapshot)

        try:
            await self.send_turn_prompt(interaction, game)
        except ValueError as error:
            await interaction.followup.send(str(error), ephemeral=True)

    async def end_period(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        lead_in: str = "",
    ) -> None:
        """
        The Discord half of the whistle. The step is
        `d12ball.flow.periods.end_period`, and with it the second
        half's reset, halftime's own cleanup and the window before the
        shootout -- the whole cascade, which is why this hands back a
        list of narration blocks rather than a line.

        **One message per block**, through `post_blocks_then_dispatch`.
        The whistle, the halftime recovery and an AI side's extra token
        were three messages before the lift and a coach reads them as
        the three events they are; the ordinary dispatcher would join
        them into one paragraph. Batching is the frontend's -- see
        principle 8 in CLAUDE.md.
        """
        result = end_period(self.engine, game, match, lead_in=lead_in)
        await self.post_blocks_then_dispatch(
            interaction, game, match, result,
        )

    def build_goal_log(self, match: MatchState) -> str:
        """
        The scoresheet, with this cog's roster and emoji behind it.

        A forwarding method over `d12ball.flow.periods.goal_log`, kept
        because `/debug` and the archive export read it from here. The
        two callers that matter are inside the flow now: the whistle
        and the shootout each build it into the content
        `announce_game_over` is handed.
        """
        return goal_log(self.engine, match)

    async def announce_game_over(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        content: str,
    ) -> None:
        """
        The last message of a game: the result, the board the game
        ended on, and the rematch and archive buttons under it. Both
        endings post it -- the whistle when full time settles the game,
        and the shootout when it does not.

        The final board rides on this message rather than being left to
        the persistent one, for the reason a loose ball's does (see
        announce_board_update): by full time the persistent message has
        scrolled hours up the channel, and the result is exactly the
        thing nobody should have to go looking for the position of. It
        is the same render-once-upload-twice -- the persistent message
        is settled from these bytes -- so the callers no longer refresh
        it themselves. It is deliberately *not* pinned: pinning stays
        the new play's alone, and a pin here would be the one at the
        very bottom of a channel nobody is playing in any more.
        """
        view = RematchView(self, game.game_id)
        png = await self.render_match_png(game)
        final = await send_new_prompt(
            interaction,
            content,
            file=self.match_file_from_png(game, png),
            view=view,
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False,
            ),
        )
        # Handed the view, or the edit that adds the link drops the two
        # buttons this message exists for.
        await add_full_image_button(final, view)
        # Remembered so the buttons come back after a restart: the
        # channel stays where it is until someone clicks one, which can
        # be days later.
        game.rematch_message_id = final.id
        save_games(self.games)
        await self.refresh_match_image(interaction, game, png=png)

    # -- Halftime ------------------------------------------------------

    async def begin_halftime(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        The Discord half of halftime: the step is
        `d12ball.flow.periods.begin_halftime` -- the automatic
        exhaustion recovery, and the stage sequence behind it.

        One message per narration block, for `end_period`'s reason:
        the recovery list and an AI side's extra token are two events.
        """
        result = begin_halftime(self.engine, game, match)
        await self.post_blocks_then_dispatch(
            interaction, game, match, result,
        )

    async def begin_setup_coaching(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
    ) -> None:
        """
        The Discord half of the pre-kickoff Coaching Choice --
        `d12ball.flow.periods.begin_setup_coaching`, which decides
        whether the window is offered at all (a tutorial kicks off on
        the standard deal) and opens the sequence if it is.

        It loads the match itself because both of its callers are
        setup views holding only the game.
        """
        match = self.engine.load_match_state(game)
        result = begin_setup_coaching(self.engine, game, match)
        await self.post_blocks_then_dispatch(
            interaction, game, match, result,
        )

    async def advance_setup_stage(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """Hand the next coach their pre-kickoff Coaching Choice, or
        kick off -- `d12ball.flow.periods.advance_setup_stage`. Also
        what `/d12ball resume` hands a stranded setup back to."""
        result = advance_setup_stage(self.engine, game, match)
        await self.post_blocks_then_dispatch(
            interaction, game, match, result,
        )

    async def finish_setup_coaching(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        lead_in: str = "",
    ) -> None:
        """
        Both coaches are done, so the game can start -- and this is
        where the board first goes up. The step is
        `d12ball.flow.periods.finish_setup_coaching`; what is here is
        the board, the pin and the tutorial's script.

        Nothing has been played yet, so a board posted before the
        windows would show a deal neither coach had finished with, and
        be redrawn twice over before anyone acted on it; the one worth
        looking at is the line-up the game actually kicks off from.

        A kickoff is a new play, so it posts its board the way every
        other one does: as its own message, under the coaching it came
        out of. It used to attach the board to the persistent message
        instead, which is a message near the top of the channel -- and
        Discord leaves an edited message where it was, so the board a
        coach had just finished setting appeared *above* the windows
        that set it, looking for all the world like the board had gone
        up before kickoff coaching rather than after it.
        """
        if lead_in:
            await send_new_prompt(interaction, lead_in)

        result = finish_setup_coaching(self.engine, game, match)
        self.persist(game, match)
        await self.post_new_play_board(
            interaction, game, " ".join(result.narration),
        )

        # The script arms here rather than at creation, so everything
        # up to the kickoff -- teams, the toss, home or visiting -- is
        # played exactly as an ordinary game plays it. The welcome goes
        # under the board it describes; the first beat is staged by the
        # send_turn_prompt below.
        async def begin_play(inner_interaction: discord.Interaction) -> None:
            try:
                await self.send_turn_prompt(inner_interaction, game)
            except ValueError as error:
                await inner_interaction.followup.send(
                    str(error), ephemeral=True,
                )

        if game.tutorial:
            game.tutorial_step = tutorial.FIRST_STEP
            game.tutorial_staged = False
            save_games(self.games)
            # The welcome and beat 1's own lesson are two narration
            # messages with nothing for the coach to click between
            # them, so the first is held behind Continue rather than
            # posted alongside it -- see post_tutorial_note.
            await self.post_tutorial_note(
                interaction, game, tutorial.WELCOME, begin_play,
            )
            return

        await begin_play(interaction)

    async def advance_halftime_stage(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """Dispatch to whichever halftime stage comes next, or finish
        -- `d12ball.flow.periods.advance_halftime_stage`. Also what
        `/d12ball resume` hands a stranded halftime back to."""
        result = advance_halftime_stage(self.engine, game, match)
        await self.post_blocks_then_dispatch(
            interaction, game, match, result,
        )

    async def begin_halftime_extra_token(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        side: TeamSide,
    ) -> None:
        """
        The coach's choice of one fielded player to lose an extra
        exhaustion token, on top of the automatic recovery every
        fielded player already got in begin_halftime --
        `d12ball.flow.periods.begin_halftime_extra_token`.
        """
        result = begin_halftime_extra_token(self.engine, game, match, side)
        await self.post_blocks_then_dispatch(
            interaction, game, match, result,
        )

    async def begin_halftime_substitutions(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        side: TeamSide,
    ) -> None:
        """
        Give `side` a full substitution window --
        `d12ball.flow.periods.begin_halftime_substitutions`, which
        answers with the window rather than opening one, since the
        window's own prompt carries a picture.
        """
        result = begin_halftime_substitutions(self.engine, game, match, side)
        await self.post_blocks_then_dispatch(
            interaction, game, match, result,
        )

    async def finish_halftime(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        lead_in: str = "",
    ) -> None:
        """
        The last step of halftime -- `d12ball.flow.periods.
        finish_halftime`. A half begins the way any other new play
        does: with the board everyone is about to play from, posted and
        pinned, which is what is left here.
        """
        if lead_in:
            await send_new_prompt(interaction, lead_in)

        result = finish_halftime(self.engine, game, match)
        self.persist(game, match)
        await self.post_new_play_board(
            interaction, game, " ".join(result.narration),
        )

        try:
            await self.send_turn_prompt(interaction, game)
        except ValueError as error:
            await interaction.followup.send(str(error), ephemeral=True)

    # -- The window before the shootout --------------------------------

    async def begin_full_time_coaching(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        The last Coaching Choice of a level game, one to each coach
        before the shootout opens --
        `d12ball.flow.periods.begin_full_time_coaching`.
        """
        result = begin_full_time_coaching(self.engine, game, match)
        await self.post_blocks_then_dispatch(
            interaction, game, match, result,
        )

    async def advance_full_time_stage(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """Hand the next coach their one substitution, or shoot out --
        `d12ball.flow.periods.advance_full_time_stage`. Also what
        `/d12ball resume` hands a stranded full-time window back to."""
        result = advance_full_time_stage(self.engine, game, match)
        await self.post_blocks_then_dispatch(
            interaction, game, match, result,
        )

    async def finish_full_time_coaching(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """Both coaches are done, so the shooting can start --
        `d12ball.flow.periods.finish_full_time_coaching`."""
        result = finish_full_time_coaching(self.engine, game, match)
        await self.post_blocks_then_dispatch(
            interaction, game, match, result,
        )

    # -- The extreme shootout ------------------------------------------

    async def begin_shootout(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        Open the shootout that settles a game level at full time --
        `d12ball.flow.periods.begin_shootout`, which explains what a
        shootout is and then asks the first question of one. Two
        messages, so one per block.
        """
        result = begin_shootout(self.engine, game, match)
        await self.post_blocks_then_dispatch(
            interaction, game, match, result,
        )

    async def advance_shootout(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        Put the shootout's next step in front of whoever owes it --
        `d12ball.flow.periods.advance_shootout`, which is still the
        one reading of "what is this shootout waiting on?".

        Everything routes through here: opening the shootout, the end
        of a skill test, and `/d12ball resume`. Two of the four steps
        are the bot's own, so a restart between them has no button
        anywhere to press and the resume has to be able to ask.
        """
        result = advance_shootout(self.engine, game, match)
        await self.post_blocks_then_dispatch(
            interaction, game, match, result,
        )

    def shootout_order_text(
        self,
        game: D12BallGame,
        match: MatchState,
        side: TeamSide,
    ) -> str:
        """
        The order a coach has built so far, on their own menu -- a
        forwarding method over
        `d12ball.flow.periods.shootout_order_text`, kept because the
        two ephemeral menus and the roll prompt's "Your Order" all read
        it from here.
        """
        return shootout_order_text(self.engine, game, match, side)

    async def close_shootout_prompt(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
    ) -> None:
        """
        Drop the "set your order" or "choose your shooter" prompt once
        both sides have answered it. Its button has nothing left to
        open, and the reveal posted underneath it is what the channel
        should end on -- the same reasoning as close_maneuver_prompt,
        including clearing `turn_message_id` so nothing re-attaches a
        view to a message that is gone.
        """
        if game.turn_message_id is None or interaction.channel is None:
            return

        try:
            await interaction.channel.get_partial_message(
                game.turn_message_id,
            ).delete()
        except (discord.NotFound, discord.HTTPException):
            pass

        game.turn_message_id = None
        save_games(self.games)

    async def continue_shootout(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        What a settled skill test hands back to: end the shootout, or
        set the next test up -- `d12ball.flow.periods.
        continue_shootout`.
        """
        result = continue_shootout(self.engine, game, match)
        await self.post_blocks_then_dispatch(
            interaction, game, match, result,
        )

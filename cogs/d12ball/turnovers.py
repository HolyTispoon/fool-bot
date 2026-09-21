"""
The three ways possession changes hands: the run back after a steal,
the time out that buys both coaches a Coaching Choice, and the pickup
after a ball has gone out. See "Turnovers: steals and new plays" and
"The time out" in docs/design/time-out.md.
"""

import asyncio
import discord
import io
import time
from typing import Awaitable, Callable, Optional

from d12ball.components import (
    CoachingOccasion,
    MatchState,
    TeamSide,
)
from d12ball.flow import FollowOnStep, StepResult
from d12ball.prompts import PendingPrompt
from d12ball.flow.windows import (
    apply_substitution,
    begin_time_out,
    coaching_summary,
    coaching_window_note,
    cover_kickoff_space,
    finish_substitution_window,
    finish_time_out,
    open_substitution_window,
    run_ai_substitution_window,
)
from d12ball.flow.turnovers import (
    announce_run_back,
    begin_ball_recovery,
    begin_run_back,
    finish_run_back,
    run_back_passes,
    run_back_player_ask,
    run_back_space_ask,
)
from d12ball.game import (
    D12BallGame,
    Formation,
)
from d12ball import tutorial
from d12ball.render import render_coaching_image
from gamesaves.d12ball.storage import save_games
from cogs.d12ball_helpers import (
    LOGGER,
    add_full_image_button,
    destination_display_name,
    format_player_with_team,
    format_team_side_label,
    send_new_prompt,
    space_label,
)
from cogs.d12ball_views import (
    BallRecoveryView,
    CoachingHubView,
    CoachingOfferView,
    RunBackChoiceView,
    RunBackPlayerChoiceView,
)

from cogs.d12ball.core import COACHING_PROMPT_KINDS
from cogs.d12ball.constants import MAX_RUN_BACK_PASSES


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
        The Coaching Choice's zone assignment: trade two players'
        zones, meeples included, and describe it.
        """
        match.exchange_field_players(side, player_id, other_player_id)

        setup = match.setup_for_side(side)
        board_size = match.board.layout.board_size
        first = self.engine.get_player_definition(player_id)
        second = self.engine.get_player_definition(other_player_id)
        return (
            f"{self.player_label(match, first)} and "
            f"{self.player_label(match, second)} change "
            "places: "
            f"{self.player_label(match, first)} to "
            f"{destination_display_name(setup.assigned_zone(player_id).value, board_size)}"
            f", {self.player_label(match, second)} to "
            f"{destination_display_name(setup.assigned_zone(other_player_id).value, board_size)}"
            ". No exhaustion cost."
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
        The Coaching Choice's space positioning: move one meeple within
        its own zone, trading with whoever is already there when the
        rule says so, and describe what happened.
        """
        setup = match.setup_for_side(side)
        zone = setup.assigned_zone(player_id)
        partner = match.position_meeple(
            side, player_id, space_index, swap_with=swap_with,
        )

        player = self.engine.get_player_definition(player_id)
        if partner is None:
            return (
                f"{self.player_label(match, player)} moves "
                f"to {space_label(zone, space_index)}. No exhaustion cost."
            )
        other = self.engine.get_player_definition(partner)
        return (
            f"{self.player_label(match, player)} moves to "
            f"{space_label(zone, space_index)} and "
            f"{self.player_label(match, other)} takes their "
            "place. No exhaustion cost."
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

    async def post_tutorial_coaching_note(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        side: TeamSide,
        then: Callable[[discord.Interaction], Awaitable[None]],
    ) -> bool:
        """
        The tutorial's last lesson, and the one it cannot schedule: a
        new play offers the window to the side *restarting* play, which
        after the coach's goal is Dinky. So the note fires at the first
        window this coach is ever offered, whenever the game gets round
        to it -- which is why it reads `tutorial` rather than
        `in_tutorial`, and usually lands a few turns after the script
        has finished. `skip_tutorial` sets the flag so a coach who
        opted out is not taught anyway.

        Held behind a Continue button like every other tutorial note
        with something after it -- `then`, the window-opening tail, is
        the interactive menu this note explains, and an ungated note
        sitting directly above it is exactly what gets scrolled past.
        Returns True when it has taken over: the caller returns without
        opening the window itself, and `then` runs on the button click.
        """
        if (
            not game.tutorial
            or game.tutorial_coaching_explained
            or side != self.tutorial_player_side(game)
        ):
            return False

        game.tutorial_coaching_explained = True
        save_games(self.games)
        await self.post_tutorial_note(
            interaction, game, tutorial.COACHING_NOTE, then,
        )
        return True

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
        The Discord half of opening a coaching window. The step is
        `d12ball.flow.windows.open_substitution_window` -- the
        arrangement restore, the window itself, and either the coach's
        prompt or an AI side's whole routine.

        **What is left here is the picture and the gate.** The window's
        prompt is the one in the game that carries the coach's own
        half-field (`coaching_file`), so it is posted here rather than
        through `dispatch_step_result`, which attaches nothing; and the
        tutorial's coaching explainer gates the whole tail behind a
        Continue button, the same as every other note with an
        interactive prompt after it -- see post_tutorial_note.

        `lead_in` is the window's own opening line and goes *inside*
        the prompt (`RulesEngine.coaching_prompt` puts it above the
        allowance), which is why the follow-on carries it as `heading`
        rather than as narration.
        """
        side = TeamSide(side)
        occasion = CoachingOccasion(occasion)

        async def open_the_window(
            inner_interaction: discord.Interaction,
        ) -> None:
            result = open_substitution_window(
                self.engine,
                game,
                match,
                side,
                occasion,
                is_response=is_response,
                heading=lead_in,
            )
            self.persist(game, match)

            following = result.next
            if not (
                isinstance(following, PendingPrompt)
                and following.kind in COACHING_PROMPT_KINDS
            ):
                await self.post_blocks_then_dispatch(
                    inner_interaction, game, match, result,
                )
                return

            # Only when the restore actually moved somebody, so the
            # common case -- setup, and a new play that has just reset
            # both sides -- costs nothing. Halftime does move them, and
            # a coach whose half-field disagrees with the board above it
            # has no way to tell which one the game thinks is true.
            if result.board_changed:
                await self.refresh_match_image(inner_interaction, game)

            prompt = await send_new_prompt(
                inner_interaction,
                following.ask,
                file=await self.coaching_file(game, match, side),
                view=self.view_for_prompt(game.game_id, match, following),
                allowed_mentions=discord.AllowedMentions(
                    users=True, roles=False, everyone=False,
                ),
            )
            game.turn_message_id = prompt.id
            save_games(self.games)

        if await self.post_tutorial_coaching_note(
            interaction, game, side, open_the_window,
        ):
            return

        await open_the_window(interaction)

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
        result = finish_substitution_window(self.engine, game, match)
        await self.post_blocks_then_dispatch(
            interaction, game, match, result,
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
        await self.post_blocks_then_dispatch(
            interaction, game, match, result,
        )

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
        The Discord half of a turnover's run back. The step is
        `d12ball.flow.turnovers.begin_run_back`, and with it the
        arrival gate it opens with, the new play's reset, and the
        "Players run back!" note.

        **A new play's board is pinned, and that is the one thing that
        stayed.** `post_new_play_board` is the only pinning site in the
        game (see "Discord's rate limits" in
        docs/design/rate-limits.md), and which message gets a pin is
        not something the model may know.
        """
        result = begin_run_back(
            self.engine,
            game,
            match,
            distance_moved=distance_moved,
            turnover_occurred=turnover_occurred,
            new_play=new_play,
            speed_choice_after=speed_choice_after,
            speed_reset=speed_reset,
            lead_in=lead_in,
        )
        self.persist(game, match)

        if not new_play or result.next is None:
            await self.dispatch_step_result(
                interaction, game, match, result,
            )
            return

        # A new play says its reset on the pinned board, and nothing
        # after it rides along: the window or the run-back note that
        # follows is its own message.
        await self.post_new_play_board(
            interaction, game, " ".join(result.narration),
        )
        await self.dispatch_step_result(
            interaction, game, match, StepResult(next=result.next),
        )

    async def announce_run_back(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        lead_in: str = "",
        speed_reset: bool = True,
    ) -> None:
        """
        The run back proper, split out of `begin_run_back` because a
        new play's substitution window sits in between and has to
        resolve before this can start -- which is why
        `finish_substitution_window` is its second caller and why this
        wrapper stayed after the step moved.

        The note itself is
        `d12ball.flow.turnovers.announce_run_back`.
        """
        result = announce_run_back(
            self.engine, game, match,
            lead_in=lead_in, speed_reset=speed_reset,
        )
        self.persist(game, match)
        # Its own message: "Players run back!" announces the cascade,
        # and the cascade's own batched placements are the next one.
        await self.post_then_dispatch(interaction, game, match, result)

    def run_back_space_prompt(
        self,
        game: D12BallGame,
        match: MatchState,
        side: TeamSide,
        player_id: str,
        mention: str,
    ) -> str:
        """
        Where does this player run back to, worded.

        A forwarding method over
        `d12ball.flow.turnovers.run_back_space_ask`, kept because
        `RunBackPlayerChoiceView` asks the question again over the top
        of its own answer and the two have to word it identically --
        the same reason it was a function rather than a string at the
        call site before the lift.
        """
        return run_back_space_ask(
            self.engine, game, match, side, player_id, mention,
        )

    async def send_run_back_prompt(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        *,
        side: TeamSide,
        candidates: list[str],
        prompt: Optional[PendingPrompt],
        lead_in: str = "",
    ) -> None:
        """
        Put a coach's run-back choice up, over **the field strip**.

        Both questions a run back asks -- which of these players goes,
        and which space they go to -- are questions about where
        everybody is standing and how far each space is, and the
        persistent message has scrolled away up the channel by the time
        a turn has resolved.

        **The strip rather than the whole match image.** The
        jumbotron, the assignment cards, the team boards and the
        benches are not what either question turns on, and dropping
        them is what makes the field itself legible inline. It is a
        crop of that same board (`render_field_image`), so it cannot
        show a different position from the one the persistent message
        settles on -- and it is the same picture the five distance
        prompts carry.

        It costs a second render rather than a second upload: the
        cascade's own board settles the persistent message, and this
        draws the strip beside it. The picture goes with the prompt:
        the click edits both away together, so the field a coach is
        reading is never one of a position that has moved on.

        **Which of the two questions this is, and how it is worded, is
        the model's**: `d12ball.prompts.run_back_prompt` reads it off
        the position, which is the same chain a restart comes back
        through. What is decided here is the picture and the view.
        """
        controller_id = self.engine.side_controller_id(game, side)
        mention = f"<@{controller_id}>" if controller_id else "Someone"
        prefix = f"{lead_in}\n\n" if lead_in else ""

        # A stack asks who before it asks where, and the two share one
        # message: the second question is an edit of the first, which
        # keeps the field that was uploaded for it rather than paying
        # for a second one. See RunBackPlayerChoiceView.
        if len(candidates) == 1:
            prompt_view = RunBackChoiceView(self, game.game_id, candidates[0])
            body = run_back_space_ask(
                self.engine, game, match, side, candidates[0], mention,
            )
        else:
            prompt_view = RunBackPlayerChoiceView(
                self, game.game_id, candidates,
            )
            body = run_back_player_ask(
                self.engine, match, side, candidates, mention,
            )

        prompt_message = await send_new_prompt(
            interaction,
            f"{prefix}{body}",
            file=await self.build_field_file(game),
            view=prompt_view,
            allowed_mentions=discord.AllowedMentions(
                users=True, roles=False, everyone=False,
            ),
        )
        # The view has to be handed over with the link, or the edit
        # that adds it drops the buttons this prompt is for -- see
        # add_full_image_button. Both go when the choice is made.
        await add_full_image_button(prompt_message, prompt_view)
        game.turn_message_id = prompt_message.id
        save_games(self.games)

    async def finish_run_back(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        lead_in: str = "",
    ) -> None:
        """
        Nobody is displaced on either side: clear the run back and hand
        the turn on to whatever it was still holding up. The Discord
        half of `d12ball.flow.turnovers.finish_run_back`, which is
        where the charge-up and the three ways out live.
        """
        result = finish_run_back(self.engine, game, match, lead_in=lead_in)
        await self.dispatch_step_result(interaction, game, match, result)

    async def continue_run_back(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        lead_in: str = "",
    ) -> None:
        """
        Drive the cascade and **batch what it says**.

        The loop is `d12ball.flow.turnovers.run_back_passes`, which
        yields one `StepResult` per pass. What is here is the two
        things principle 8 and principle 9's named exception put here:

        - **the batching.** Every placement made without asking anyone
          -- the forced ones, the AI's choices, the drop back that
          fills an empty kickoff -- collects into one message and one
          board refresh, flushed when the cascade reaches a coach's
          choice or runs out. It used to post a message and re-upload
          the board per player, which after a steal that scatters a
          4-1-1 side is a dozen-odd REST calls into one channel with
          nothing between them, and enough to be rate limited for it.
          Nobody is reading the intermediate boards anyway.
        - **the per-pass persist.** A pass that ends on a question
          leaves the turn waiting on a click that reloads the match off
          disk, so that pass's placements have to be written before the
          prompt goes out. This is the one place a step's caller saves
          inside a loop rather than once after it, and collapsing it
          loses placements on every cascade that stops to ask.

        `lead_in` only ever applies to the first message this call (or
        the resumption in `RunBackChoiceView`) sends -- every call site
        that already consumed it passes none.
        """
        # Lines describing placements already applied and saved, and
        # not yet posted. `lead_in` is consumed by whichever message
        # goes out first, which may be this one or the prompt below.
        notes: list[str] = []

        async def flush(png: Optional[bytes] = None) -> bool:
            """
            Post the automatic placements so far, with the board they
            produced. True when there was something to post.

            `png` is an already-rendered board, for the caller that is
            about to upload the same one onto the prompt below.
            """
            nonlocal lead_in, notes

            if not notes:
                return False

            prefix = f"{lead_in}\n\n" if lead_in else ""
            body = "\n".join(notes)
            notes = []
            lead_in = ""
            await send_new_prompt(interaction, f"{prefix}{body}")
            await self.refresh_match_image(interaction, game, png=png)
            return True

        for result in run_back_passes(self.engine, game, match):
            self.persist(game, match)
            notes.extend(result.narration)

            following = result.next
            if following is None:
                continue

            if following.step is FollowOnStep.SEND_RUN_BACK_PROMPT:
                # A coach's choice ends the cascade here: say what has
                # happened so far, settle the board it left, and ask.
                #
                # The board goes on the persistent message; the prompt
                # draws its own field strip (see send_run_back_prompt).
                # Two renders, two uploads -- the requests are what the
                # gate counts, and they are unchanged.
                png = await self.render_match_png(game)
                if not await flush(png):
                    await self.refresh_match_image(
                        interaction, game, png=png,
                    )
                await self.send_run_back_prompt(
                    interaction,
                    game,
                    match,
                    lead_in=lead_in,
                    **following.kwargs,
                )
                return

            # The cascade is done. Flush, then finish -- the ordering
            # is why the generator names the step rather than the model
            # simply running it.
            await flush()
            await self.finish_run_back(
                interaction, game, match, lead_in=lead_in,
            )
            return

    # -- Out-of-bounds recovery (after the run back) ------------------

    async def begin_ball_recovery(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        lead_in: str = "",
    ) -> None:
        """
        The Discord half of the pickup an out-of-bounds ball, or a time
        out, still owes -- `d12ball.flow.turnovers.begin_ball_recovery`.
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
        player = self.engine.get_player_definition(player_id)
        # The triggering maneuver's own travel, for the clock. It
        # outlives the run back that just finished (only
        # reset_maneuver clears it) precisely so this step, which can
        # span a restart, can still read it back.
        distance_moved = match.pending_run_back_distance
        # Read before the pickup clears it. A time out's is the one
        # walk to the ball that charges nothing, and it is not a
        # turnover either -- the side fetching the ball is the side
        # that has had it all along, so nothing resets and nothing
        # ends. See finish_time_out.
        from_time_out = match.pending_recovery_from_time_out
        distance = match.recover_out_of_bounds_ball(player_id)
        exhaustion_text = (
            "" if from_time_out
            else self.apply_exhaustion(game, match, player_id, distance)
        )
        self.persist(game, match)

        prefix = f"{lead_in}\n\n" if lead_in else ""
        # Joined rather than interpolated: a free pickup has no
        # exhaustion line at all, and interpolating one would leave a
        # blank line under the sentence. See "What a message says".
        await send_new_prompt(
            interaction,
            "\n".join(
                part for part in (
                    f"{prefix}"
                    f"{self.player_label(match, player)} picks the "
                    f"ball up at "
                    f"{space_label(match.ball.zone, match.ball.space_index)}.",
                    exhaustion_text,
                ) if part
            )
        )
        await self.refresh_match_image(interaction, game)
        await self.finish_maneuver_resolution(
            interaction,
            game,
            match,
            distance_moved=distance_moved,
            turnover_occurred=not from_time_out,
        )

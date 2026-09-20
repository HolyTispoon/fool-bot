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
    EVENT_TIME_OUT,
    CoachingOccasion,
    MatchState,
    SPECIES_CYBORG,
    TeamSide,
    Zone,
)
from d12ball.game import (
    D12BallGame,
    Formation,
)
from d12ball import tutorial
from d12ball.flow.turnovers import ball_recovery_step
from d12ball.render import render_coaching_image
from gamesaves.d12ball.storage import save_games
from cogs.d12ball_helpers import (
    LOGGER,
    add_full_image_button,
    destination_display_name,
    format_player_with_team,
    format_team_side_label,
    get_exhaust_emoji,
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
        Make one swap and describe it. Raises ValueError with the
        rule that refused it if the swap is not allowed.
        """
        was_injured = outgoing_player_id in match.injured
        from_back_bench = (
            incoming_player_id
            in match.setup_for_side(side).team_board.back_bench
        )
        occasion = match.coaching_occasion or CoachingOccasion.NEW_PLAY

        match.substitute(
            side,
            outgoing_player_id,
            incoming_player_id,
            retire_outgoing=occasion.retires_outgoing_players,
        )
        match.record_substitution(outgoing_player_id, incoming_player_id)

        outgoing = self.engine.get_player_definition(outgoing_player_id)
        incoming = self.engine.get_player_definition(incoming_player_id)
        outgoing_drain = self.engine.has_species_ability(
            game, outgoing_player_id, SPECIES_CYBORG,
        )
        was_damaged = was_injured and outgoing_drain
        text = (
            f"{self.player_label(match, incoming)} comes on "
            f"for {self.player_label(match, outgoing)}"
            f"{' (damaged)' if was_damaged else ''}"
            f"{' (injured)' if was_injured and not outgoing_drain else ''}."
        )

        if from_back_bench:
            # Half the tokens, rounded up, come off a returning
            # player -- but Exhausted is whatever the remainder says,
            # so it has to be re-tested rather than assumed cleared.
            #
            # Against their own threshold, which for a Cyborg is the
            # flat Drained line rather than their defensive skill: a
            # Cyborg is exactly the player this re-test would get
            # wrong, since half of a big drain total is still well
            # over a striker's defence of 2 and nowhere near 7.
            threshold = self.engine.exhaustion_threshold(
                game, incoming_player_id,
            )
            incoming_drain = self.engine.has_species_ability(
                game, incoming_player_id, SPECIES_CYBORG,
            )
            noun = "drain" if incoming_drain else "exhaustion"
            remaining = match.exhaustion.get(incoming_player_id, 0)
            exhaust_emoji = get_exhaust_emoji(self.condition_emojis)
            text += (
                f"\nBack on from the back bench, down to {remaining} "
                f"{noun} {'token' if remaining == 1 else 'tokens'} "
                f"{exhaust_emoji * remaining}."
            )
            if match.mark_exhausted_if_needed(
                incoming_player_id, threshold,
            ):
                condition = "Drained" if incoming_drain else "Exhausted"
                text += (
                    f" Still **{condition}** -- {remaining} is over "
                    f"{threshold}."
                )

        text += f"\n{self.engine.substitution_allowance_label(match)}."
        return text


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
        The line under a coaching prompt: what this window costs, what
        moved on the way in, and who is hurt.

        The three answer separately -- the question, if there is one,
        then a restore only where it actually moved somebody, then an
        injured player as a nudge rather than a requirement. Any of
        them may have nothing to say, so the parts that are there are
        joined rather than interpolated; see "What a message says".

        **Almost all of it is gone, and what is left is the question
        and the reason** (the author, 2026-09-16). Every branch used to
        explain what the window cost and what it left unspent -- a
        paragraph of rules recited above a menu that answers the same
        questions by what it offers, and the header above it already
        carries the substitution allowance.

        - A new play asks **"Coach?"**, because the two buttons under it
          are Coach and Pass and the question is the whole of the note.
        - A time out's own coach is told nothing: they pressed the
          button, so there is nothing a note can add.
        - The **one reply that says anything** is a time out's, and it
          says only what the coach could not otherwise know: the other
          team called one. A new play's reply is silent, since the
          restart they are answering is in the channel above them.

        What it cost and what it left unspent were both worth saying
        while a window was once a half and shared between the two
        occasions. It no longer is -- a new play's is free and
        unlimited -- so the reassurance was answering a question
        nobody had.
        """
        lines: list[str] = []
        if occasion.asks_declaration and not is_response:
            lines.append("Coach?")
        elif occasion == CoachingOccasion.TIME_OUT and is_response:
            lines.append("The other team called a time out.")

        # Said only when it actually moved somebody, which is halftime
        # and nowhere else: a coach who left the first half with their
        # side scattered is looking at their own shape again and
        # should be told why.
        if restored:
            lines.append("Your side is back on the arrangement you last set.")

        # An injured player is worth pointing out, but only as a
        # nudge: nothing compels a side to get them off, and a coach
        # may leave them on, disadvantaged, all game.
        injured_ids = match.injured_field_players(side)
        if injured_ids:
            injured = ", ".join(
                self.player_id_label(match, player_id)
                for player_id in injured_ids
            )
            verb = "is" if len(injured_ids) == 1 else "are"
            lines.append(f"{injured} {verb} injured and still on the field.")

        return "\n".join(lines)

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
        Offer `side` the window. A declaration is once a half, so a
        side that has already spent theirs is never offered one. An
        injured player on the field is named in the heading but
        compels nothing -- leaving them on is the coach's call.

        `occasion` carries every difference between the five -- the
        substitution allowance, whether the declare-or-pass offer is
        put at all, where a player taken off goes, and whether the
        three positional actions are offered at all. Setup, halftime
        and full time are given rather than declared, so all three skip
        the offer and open the menu directly; a time out skips it for
        the opposite reason, having already been paid for.

        **A window opens on the arrangement its coach last settled**,
        never on the scramble a run back left behind -- see
        MatchState.restore_assigned_positions. A new play resets both
        sides before offering the window, so this only ever does
        anything at halftime, where the first half ended wherever it
        ended; but it is the guarantee for every occasion rather than
        a halftime step, because a coach reading their half-field is
        reading the shape they set either way.

        Except full time, which has no positioning in it: nothing is
        played from a position after it, so restoring would rearrange
        the last board of the game to no purpose.
        """
        side = TeamSide(side)
        occasion = CoachingOccasion(occasion)

        async def open_the_window(
            inner_interaction: discord.Interaction,
        ) -> None:
            restored = (
                match.restore_assigned_positions(side)
                if occasion.offers_positioning
                else False
            )
            shape = self.engine.current_formation(match, side)
            match.open_coaching_window(
                side,
                occasion,
                is_response=is_response,
                formation=shape.value if shape else None,
            )
            self.persist(game, match)

            # Only when the restore actually moved somebody, so the
            # common case -- setup, and a new play that has just reset
            # both sides -- costs nothing. Halftime does move them, and
            # a coach whose half-field disagrees with the board above it
            # has no way to tell which one the game thinks is true.
            if restored:
                await self.refresh_match_image(inner_interaction, game)

            if self.engine.side_is_ai(game, side):
                await self.run_ai_substitution_window(
                    inner_interaction, game, match, lead_in=lead_in,
                )
                return

            note = self.coaching_window_note(
                match, side, occasion, is_response, restored,
            )

            prompt = await send_new_prompt(
                inner_interaction,
                self.engine.coaching_prompt(
                    game, match, side, note, lead_in=lead_in,
                ),
                file=await self.coaching_file(game, match, side),
                view=(
                    CoachingOfferView(self, game.game_id)
                    if occasion.asks_declaration
                    else CoachingHubView(self, game.game_id)
                ),
                allowed_mentions=discord.AllowedMentions(
                    users=True, roles=False, everyone=False,
                ),
            )
            game.turn_message_id = prompt.id
            save_games(self.games)

        # The tutorial's one-off coaching explainer gates the whole tail
        # above behind a Continue button, the same as every other note
        # with an interactive prompt after it -- see post_tutorial_note.
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
        What the open window changed, a line each, for the message it
        closes with. Asked while the window is still open -- closing
        it clears what this reads.

        **Only the shape and the swaps.** Zone assignment and space
        positioning are on the board everyone can see, and the board
        is posted the moment coaching is over; a substitution changes
        who is playing, and a formation change is the shape those
        positions are read against, so both are worth saying in words.
        The substitution notes especially: each one is written over by
        the next step of the flow, so without this they are gone by
        the time the coach clicks Done.
        """
        side = TeamSide(side)
        lines: list[str] = []

        was = match.pending_coaching_formation
        now = self.engine.current_formation(match, side)
        if now is not None and now.value != was:
            lines.append(
                f"Formation: **{was} → {now.value}**."
                if was
                else f"Formation: **{now.value}**."
            )

        for outgoing_player_id, incoming_player_id in (
            match.pending_coaching_swaps
        ):
            outgoing = self.engine.get_player_definition(outgoing_player_id)
            incoming = self.engine.get_player_definition(incoming_player_id)
            lines.append(
                f"{self.player_label(match, incoming)} came "
                f"on for {self.player_label(match, outgoing)}."
            )

        return lines

    async def run_ai_substitution_window(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        lead_in: str = "",
    ) -> None:
        side = TeamSide(match.pending_coaching_side)
        occasion = match.coaching_occasion or CoachingOccasion.NEW_PLAY
        strategy = self.engine.get_ai_strategy(game)
        lines: list[str] = []

        while match.may_substitute():
            choice = strategy.choose_substitution(match, side)
            if choice is None:
                break
            if not match.pending_coaching_declared:
                match.declare_coaching()
            outgoing_player_id, incoming_player_id = choice
            try:
                lines.append(
                    self.apply_substitution(
                        game,
                        match,
                        side,
                        outgoing_player_id,
                        incoming_player_id,
                    )
                )
            except ValueError as error:
                LOGGER.error(
                    "AI substitution refused in game %s: %s",
                    game.game_id, error,
                )
                break

        covered = self.cover_kickoff_space(match, side)
        if covered:
            lines.append(covered)

        self.persist(game, match)

        setup = match.setup_for_side(side)
        prefix = f"{lead_in}\n\n" if lead_in else ""
        if lines:
            body = "\n".join(lines)
            await send_new_prompt(
                interaction,
                f"{prefix}# Coaching Choice\n"
                f"{format_team_side_label(setup)}:\n{body}"
            )
            # Before kickoff there is no board up yet, deliberately --
            # finish_setup_coaching posts it once both coaches are
            # done, and an AI window is not the moment to break that.
            if match.pending_setup_stage is None:
                await self.refresh_match_image(interaction, game)
        elif lead_in and occasion.spends_time_out:
            # A new play's lead-in is the announcement that opened the
            # window -- the goal, the miss -- and has to be posted
            # whatever the AI decided. Setup's and halftime's are
            # instructions to a coach, so an AI that changed nothing
            # says nothing rather than posting a menu heading with no
            # menu under it.
            await send_new_prompt(interaction, lead_in)

        await self.finish_substitution_window(interaction, game, match)

    def cover_kickoff_space(
        self,
        match: MatchState,
        side: TeamSide,
    ) -> Optional[str]:
        """
        Put one of an AI side's meeples on their own kickoff space when
        nobody is standing on it, and describe the move -- or None when
        there is nothing to do.

        A human coach is refused the Done button until they have
        covered it (see coaching_finish_refusal); the AI has no menu to
        be held in, so it does the same thing here. The kickoff space
        is always in midfield and every basic shape puts at least two
        cards there, so the mover is always somebody whose own zone it
        is.
        """
        side = TeamSide(side)
        if self.engine.coaching_finish_refusal(match, side) is None:
            return None

        setup = match.setup_for_side(side)
        kickoff_index = match.kickoff_space_for(side)
        kickoff_flat = match.board.flat_index(Zone.MIDFIELD, kickoff_index)
        candidates = [
            player_id
            for player_id in setup.field_players
            if setup.assigned_zone(player_id) == Zone.MIDFIELD
        ]
        if not candidates:
            LOGGER.error(
                "No %s card is assigned to midfield, so nobody can take "
                "the kickoff space.",
                side.value,
            )
            return None

        def distance(player_id: str) -> int:
            position = match.board.meeple_position(player_id)
            if position is None:
                return 10**6
            return abs(match.board.flat_index(*position) - kickoff_flat)

        nearest = min(candidates, key=distance)
        match.position_meeple(side, nearest, kickoff_index)
        player = self.engine.get_player_definition(nearest)
        return (
            f"{self.player_label(match, player)} takes the "
            f"kickoff spot at {space_label(Zone.MIDFIELD, kickoff_index)}."
        )

    async def finish_substitution_window(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        Hand the window on, or give up on it and let the run back go
        ahead. The other team only gets its single answering
        substitution because a declaration actually happened -- a side
        that passes takes the opposing reply down with it.

        A side that used its window comes out of it standing where its
        coach put them, and that becomes the arrangement the next new
        play restores. A side that passed changed nothing, so their
        existing arrangement stands untouched.
        """
        declared = match.pending_coaching_declared
        was_response = match.pending_coaching_is_response
        occasion = match.coaching_occasion
        side = (
            TeamSide(match.pending_coaching_side)
            if match.pending_coaching_side
            else None
        )
        match.close_coaching_window()
        # Full time records nothing: the window it closes had no
        # positioning in it, and nothing is played from a position
        # again, so writing where the second half left the side would
        # overwrite the coach's arrangement with a scramble no new play
        # will ever restore.
        if (
            declared
            and side is not None
            and (occasion is None or occasion.offers_positioning)
        ):
            match.set_assigned_positions(side)
        self.persist(game, match)

        # Setup, halftime and full time give each side its own window
        # rather than a turnover's declare-then-respond pairing, so all
        # three move on to the next stage of their own sequence instead
        # of offering the other side a response.
        if match.pending_full_time_stage is not None:
            self.engine.next_full_time_stage(match)
            self.persist(game, match)
            await self.advance_full_time_stage(interaction, game, match)
            return

        if match.pending_setup_stage is not None:
            self.engine.next_setup_stage(match)
            self.persist(game, match)
            await self.advance_setup_stage(interaction, game, match)
            return

        if self.engine.halftime_stage(match) in (
            "coaching_home", "coaching_visiting",
        ):
            self.engine.next_halftime_stage(match)
            self.persist(game, match)
            await self.advance_halftime_stage(interaction, game, match)
            return

        if declared and not was_response and side is not None:
            other_side = (
                TeamSide.VISITING
                if side == TeamSide.HOME
                else TeamSide.HOME
            )
            # The reply is the same occasion as the declaration it
            # answers -- a time out opens the other coach's window
            # already declared too, since there is nothing for them to
            # pass on: they have been handed the ball and the window
            # both, and neither costs them anything.
            await self.begin_substitution_window(
                interaction,
                game,
                match,
                other_side,
                occasion=occasion or CoachingOccasion.NEW_PLAY,
                is_response=True,
            )
            return

        if match.pending_time_out:
            # Nobody ran anywhere and nothing is displaced: both sides
            # took the field on their own arrangement as their windows
            # opened. So this skips the run back entirely rather than
            # letting it charge for a scramble that never happened.
            await self.finish_time_out(interaction, game, match)
            return

        await self.announce_run_back(interaction, game, match)

    # -- Ceding the ball to coach --------------------------------------


    async def begin_time_out(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        The side in possession stops play to coach -- see "Time out" in
        docs/living-rules.md, and `MatchState.may_call_time_out` for
        when it is on offer at all. The caller has acknowledged the
        interaction and is responsible for the prompt the click came
        from.

        **It is not a turnover.** The ball does not move, possession
        does not change, ball speed is left alone and nobody runs back.
        What it costs is the flat space minute every action costs
        (2026-08-16), charged in `finish_time_out` once its tail (a
        pickup may span a restart) is settled.

        Both coaches then coach: the caller's window opens at once, and
        `finish_substitution_window` hands the other theirs exactly as
        a declaration's reply -- which is what it is.

        **There is no last-possession branch here any more, because the
        button is never built then.** Ceding was a turnover, so under
        last possession it ended the period; a time out turns nothing
        over, and the author refused it outright there instead
        (2026-09-16). `may_call_time_out` is the whole of that, and
        `PlayerActionView` and `choose_action` both read it -- so this
        is only ever reached in a position where play goes on.
        """
        # **Its own event kind, not a turn action** (the author,
        # 2026-09-16). A possession is a run of consecutive
        # `turn_action`s by one side and every event in a turn belongs
        # to the last one before it, so logging a pause as a turn would
        # invent a turn nobody played and hang the rest of the real
        # turn's events off it. It is still recorded -- a coach wants
        # to know how often these get called -- on a row of its own in
        # the statistics.
        #
        # **Recorded here rather than on the confirm prompt**, which is
        # where the two real turn actions are recorded. A time out is
        # the one of the three that asks first, and a coach who opens
        # the confirm and presses Back has not called one.
        #
        # Read before `call_time_out`, which resets the turn: the side
        # is the side in possession, and that is what the record is of.
        match.record_event(
            EVENT_TIME_OUT,
            side=match.ball.possession,
            player_id=match.active_player_id,
        )

        side = match.call_time_out()
        label = format_team_side_label(match.setup_for_side(side))
        self.persist(game, match)

        await self.drop_turn_prompt(interaction, game)

        lead_in = (
            f"# {label} call a time out\n"
            "Both coaches get a Coaching Choice. The ball stays with "
            f"{label} on "
            f"{space_label(match.ball.zone, match.ball.space_index)}."
        )

        await self.refresh_match_image(interaction, game)
        await self.begin_substitution_window(
            interaction,
            game,
            match,
            side,
            occasion=CoachingOccasion.TIME_OUT,
            lead_in=lead_in,
        )

    async def finish_time_out(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        The tail of a time out, once both coaches have closed their
        windows. There is no run back to run and none is owed: each
        window opened on its own coach's arrangement, so by here both
        sides are standing where their own coach left them.

        What is left is whether the side that called it still has
        anybody on their own ball. A Coaching Choice can re-deal a
        whole side, so a coach can rearrange their handler off the
        space the ball is lying on. Possession is the team's and stays
        with them either way (the author, 2026-09-16); they send the
        nearest player either side of it to pick it back up.

        **That pickup is free**, which is the one walk to the ball in
        the game that charges nothing. A time out costs a minute and no
        exhaustion, and a coach should not be billed for putting
        somebody back on a ball their side never lost.
        `pending_recovery_from_time_out` is what says so, and it says
        the other half too: the pickup is not a turnover, because the
        side doing it is the side that had the ball all along.

        **`turnover_occurred` is False**, unlike a cede's, and that is
        the whole of what stopped being a turnover: nothing resets ball
        speed, and last possession is not ended by a side keeping the
        ball it already had. The button is not built under last
        possession at all -- see `MatchState.may_call_time_out`.

        `pending_time_out` is cleared before either branch: from here on
        the state says what is owed on its own, and leaving it set
        would have `pending_turn_view` answering for a window that has
        closed.
        """
        match.pending_time_out = False
        needs_recovery = not match.eligible_ball_handlers()
        match.pending_ball_recovery = needs_recovery
        match.pending_recovery_from_time_out = needs_recovery
        self.persist(game, match)

        if needs_recovery:
            await self.begin_ball_recovery(interaction, game, match)
            return

        # A time out costs the flat space minute every action costs
        # (2026-08-16), and nothing else: no turnover, so no speed
        # reset and no last-possession end.
        await self.finish_maneuver_resolution(
            interaction,
            game,
            match,
            distance_moved=1,
            turnover_occurred=False,
        )

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
        `distance_moved`/`turnover_occurred` describe the maneuver that
        triggered this run-back, stashed on `match` so they survive the
        multi-turn choice flow and reach finish_maneuver_resolution
        correctly once run-back itself (which only ever costs
        exhaustion, never time) is done.

        `speed_reset` is announce_run_back's own note, and only ever
        False for Dribble Burst's cost: every caller here has already
        set `match.ball.speed` to whatever it should read by the time
        this runs, so this is wording, not state -- it says whether
        that was a reset to 1 (every other turnover) or the burst's
        speed carrying over (see the comment on `gambit_cost`).

        `new_play` says the ball changed hands because play stopped and
        is restarting -- a goal, an own goal, a missed attempt, a ball
        out of bounds -- rather than because the other team took it off
        them. Only a new play opens a substitution window; a steal
        (Steal, a Defender's Pressure steal, a loose ball or
        a long High Pass the other side wins) runs everyone back and
        plays straight on. See "Steals and new plays",
        docs/living-rules.md. It is not persisted: it is consumed here,
        and by the time anything is saved the state already says which
        of the two happened -- a window open, or a run back pending.

        **The player holding the ball does not run back**, whoever they
        are -- see "Choosing the handler" and "Running back after a
        steal"
        in docs/living-rules.md. The exemption is read off
        `ball_carrier_id` rather than passed in, because the two are
        the same fact: a run back that moved the ball's holder would
        run them off the ball and charge them for it. It used to be a
        `stays_player_id` argument that only Steal and a
        Defender's Pressure steal passed, which left a loose-ball or
        High Pass winner -- equally the holder -- being run back off
        the ball they had just won.

        A new play exempts nobody: the ball went dead, so nobody is
        carrying it, and the reset that follows moves both sides
        whatever they were doing.

        `speed_choice_after` is set only for Steal -- once
        run-back finishes, its defender still gets to manipulate the
        ball's speed, offered only after players are back in position
        rather than before (see continue_run_back).

        `lead_in` is narration from the triggering effect that hasn't
        been posted yet -- it rides along on whichever message this
        run-back sends first (see continue_run_back).

        A turnover that happens while last possession is already in
        force ends the period immediately instead: no run-back, no
        substitution window, and (for a steal) no run-back or
        speed-manipulation follow-up either -- the triggering effect's
        own state change (e.g. Steal's turnover and 1-space
        fallback) has already been applied and saved by the caller,
        this just skips everything downstream of that. The maneuver
        that *declares* last possession is not that turnover and isn't
        caught here: its own clock advance happens later, in
        finish_maneuver_resolution, so it runs back like any other.

        A resolution that left possession where it was doesn't run a
        run-back at all: "every time there's a turnover for any
        reason (steal, goal etc.) players have to run back" is the
        whole of when one happens ("Turnovers, resets, and running back",
        docs/living-rules.md).
        Keeping the ball -- a receiver winning their High Pass, a
        loose ball the possessing side recovers -- leaves whoever is
        out of position out of position, and charges nobody, until a
        turnover does come. This is called with turnover_occurred
        False anyway so the tail of the flow (the clock, the next
        offensive choice) stays in one place.
        """
        if turnover_occurred and match.scoreboard.last_possession:
            await self.end_period(interaction, game, match, lead_in=lead_in)
            return

        if not turnover_occurred:
            await self.finish_maneuver_resolution(
                interaction,
                game,
                match,
                distance_moved=distance_moved,
                turnover_occurred=False,
                lead_in=lead_in,
            )
            return

        # **Mind Pull, before anyone runs back.** `mind_pull_candidates`
        # reads current board occupancy of `last_ball_path`, so a
        # Telekinetic who merely runs back onto a space the ball crossed
        # must never be offered a pull meant for whoever actually stood
        # there when it moved. A maneuver that settles its own turnover
        # and calls this directly (Steal, Intercept, a Defender's
        # pressure steal, an own goal avoided) never passes through the
        # three ordinary arrival gates, so this is the one place
        # guaranteed to run before positions change.
        if await self.check_for_ball_arrival(
            interaction,
            game,
            match,
            {
                "kind": "run_back",
                "distance_moved": distance_moved,
                "turnover_occurred": turnover_occurred,
                "new_play": new_play,
                "speed_choice_after": speed_choice_after,
                "speed_reset": speed_reset,
                "lead_in": lead_in,
            },
        ):
            return

        if new_play:
            # The ball is dead. Clearing here as well as in
            # announce_new_play_reset is what keeps the exemption below
            # honest: a goal scored off a High Pass set-up leaves the
            # receiver still recorded as carrying it, and they are not
            # -- the ball is on its way back to the kickoff space.
            match.clear_ball_carrier()

        match.pending_run_back = True
        match.pending_run_back_distance = distance_moved
        match.pending_run_back_turnover = turnover_occurred
        match.pending_run_back_stays_player_id = match.ball_carrier_id
        match.pending_run_back_speed_choice = speed_choice_after
        # **Charge-up is armed here and awarded at the end**, because
        # who actually moved is only known once the cascade has run --
        # a stack is a real decision (see `charge_up_players`). A new
        # play is not a run back and triggers none, and this flag is
        # what remembers that: `new_play` is not persisted, and by the
        # time the reset leaves nobody displaced the cascade can no
        # longer tell the two apart.
        match.run_back_moved = []
        match.pending_run_back_charge_up = not new_play
        self.persist(game, match)

        # A new play resets both sides to the shape their coaches set,
        # free of exhaustion, and only then opens the substitution
        # window -- a coach who declares rearranges from their own
        # formation rather than from wherever open play scattered them,
        # and a coach who passes has already got what passing gives
        # them. It also leaves nobody displaced, so the run back that
        # follows finds nothing to do and falls through to whatever the
        # restart still owes (the kickoff space, an out-of-bounds
        # pickup).
        #
        # A steal does none of this: the ball is still live, so the
        # coaches get no pause and the ordinary run back stands.
        if new_play:
            await self.announce_new_play_reset(interaction, game, match, lead_in)
            lead_in = ""
            winning_side = match.ball.possession
            if match.may_take_time_out(winning_side):
                await self.begin_substitution_window(
                    interaction, game, match, winning_side,
                )
                return
        await self.announce_run_back(
            interaction, game, match, lead_in, speed_reset=speed_reset,
        )

    def apply_charge_up(
        self, game: D12BallGame, match: MatchState,
    ) -> str:
        """
        Take a drain token off every Cyborg this run back leaves where
        they are, and word it -- or "" when there is nobody to charge
        up, which is every game not playing the species abilities and
        most turns of the ones that are.

        Who qualifies is `RulesEngine.charge_up_players`; this is the
        removal and the sentence. The re-test matters: a Cyborg sitting
        on exactly 7 is Drained, and dropping to 6 clears it, so this
        goes through `recover_exhaustion` rather than decrementing the
        count by hand.
        """
        charged = self.engine.charge_up_players(game, match)
        if not charged:
            return ""

        lines = []
        for player_id in charged:
            player = self.engine.get_player_definition(player_id)
            removed = match.recover_exhaustion(
                player_id, 1, self.engine.exhaustion_threshold(
                    game, player_id,
                ),
            )
            if not removed:
                continue
            remaining = match.exhaustion.get(player_id, 0)
            lines.append(
                f"{self.player_label(match, player)} holds position — "
                f"**Charge-up** removes 1 drain "
                f"(now {remaining})."
            )
        return "\n".join(lines)

    async def announce_new_play_reset(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        lead_in: str = "",
    ) -> None:
        """
        Put both sides back on the arrangement their coaches last set
        and say so. Nobody pays a token for it -- see
        MatchState.restore_assigned_positions.

        This is where a new play's board goes out and gets pinned: the
        reset is the arrangement the play starts from, and it is the
        one moment in the restart where nothing is still moving. What
        the restart still owes (a kickoff fill, an out-of-bounds
        pickup) lands on the persistent board afterwards.
        """
        # The ball went dead and is being brought back into play, so
        # nobody is carrying it -- whoever ends up on it chooses.
        match.clear_ball_carrier()
        # **A new play is the one thing that ends a Double Team**, and
        # the card says so outright: "so long as it's not a new play,
        # on their next maneuver, both defending players challenge".
        # Cleared here rather than in `reset_maneuver`, which runs at
        # the end of every turn -- including the turn that set it.
        match.pending_double_team = []
        moved: list[str] = []
        for side in (TeamSide.HOME, TeamSide.VISITING):
            for player_id, zone, space_index in (
                match.restore_assigned_positions(side)
            ):
                player = self.engine.get_player_definition(player_id)
                moved.append(
                    f"{self.player_label(match, player)} to "
                    f"{space_label(zone, space_index)}"
                )
        self.persist(game, match)

        prefix = f"{lead_in}\n\n" if lead_in else ""
        body = (
            "Both teams reset to the positions their coaches last "
            "set:\n" + "\n".join(moved)
            if moved
            else "Players return to positions assigned by their coach."
        )
        await self.post_new_play_board(
            interaction, game, f"{prefix}# New play\n{body}",
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
        The run back proper, split out of begin_run_back because a new
        play's substitution window sits in between and has to resolve
        before this can start.

        With nobody displaced there is nothing to explain, and heading
        an empty run back "Players run back!" reads as a bug. That is
        every new play: the reset put both sides back on their own
        arrangement, so only the speed note is left to say.
        """
        turnover_occurred = match.pending_run_back_turnover
        prefix = f"{lead_in}\n\n" if lead_in else ""
        # Speed manipulation (Steal) always happens after
        # run-back now, so a turnover's ball speed is still at its
        # reset value of 1 here -- except Dribble Burst's cost, whose
        # caller passes speed_reset=False because the ball kept the
        # burst's own speed instead, and that is already said in the
        # lead-in this note would otherwise contradict.
        speed_note = (
            "The ball speed goes down to **1**."
            if turnover_occurred and speed_reset
            else ""
        )
        displaced = any(
            self.engine.run_back_movers(game, match, side)
            for side in (TeamSide.HOME, TeamSide.VISITING)
        )
        if displaced:
            await send_new_prompt(
                interaction,
                f"{prefix}# Players run back!\n"
                "Players return to an open space in their assigned zone and "
                "gain 1 exhaustion token for every space traveled. "
                f"{speed_note}".rstrip()
            )
        elif prefix or speed_note:
            await send_new_prompt(interaction, f"{prefix}{speed_note}".strip())
        await self.continue_run_back(interaction, game, match)





    def run_back_space_prompt(
        self,
        game: D12BallGame,
        match: MatchState,
        side: TeamSide,
        player_id: str,
        mention: str,
    ) -> str:
        """
        Where does this player run back to -- the question every run
        back ends on, whether the player was displaced or has just been
        picked out of a stack. It is a function rather than a string at
        the call site because those are two different places now: the
        cascade asks it directly, and RunBackPlayerChoiceView asks it
        again over the top of its own answer, and the two have to word
        it identically.
        """
        player = self.engine.get_player_definition(player_id)
        return (
            f"{mention}, choose where "
            f"{self.player_label(match, player)} runs back "
            "to:\n"
            f"{self.engine.describe_run_back_options(game, match, side, player_id)}"
        )

    def run_back_player_prompt(
        self,
        match: MatchState,
        side: TeamSide,
        candidates: list[str],
        mention: str,
    ) -> str:
        """
        Which of a stack runs back, and where each of them is standing
        -- a coach choosing between two teammates on one space is
        choosing which of them pays for the walk, so the prompt says
        who they are rather than leaving it to the buttons alone.
        """
        lines = []
        for player_id in candidates:
            player = self.engine.get_player_definition(player_id)
            position = match.board.meeple_position(player_id)
            lines.append(
                f"{self.player_label(match, player)} on "
                f"{space_label(*position)}"
                if position is not None
                else self.player_label(match, player)
            )
        return (
            f"{mention}, your players are doubled up while their zone "
            "still has a space with nobody on it — choose which of them "
            "runs back:\n" + "\n".join(lines)
        )



    def run_back_ai_placement(
        self,
        game: D12BallGame,
        match: MatchState,
        side: TeamSide,
        candidates: list[str],
    ) -> str:
        """
        Place one of an AI side's run-backs and describe it, without
        posting anything: the line comes back for the cascade in
        continue_run_back to batch with every other automatic
        placement. See "Discord's rate limits" in docs/design/rate-limits.md.
        """
        # One candidate is a settled player and only the space is
        # open; several is a stack Dinky picks out of, the same call a
        # coach is given in send_run_back_prompt.
        player_id = (
            candidates[0]
            if len(candidates) == 1
            else self.engine.get_ai_strategy(game).choose_run_back_player(
                match, candidates,
            )
        )
        zone = match.setup_for_side(side).assigned_zone(player_id)
        player = self.engine.get_player_definition(player_id)
        exempt_ids = self.engine.spread_exempt_ids(game, match, side)
        space_index = self.engine.get_ai_strategy(game).choose_run_back_space(
            match.placement_spaces_in_zone(side, zone, player_id, exempt_ids)
        )
        distance = match.run_back_player(
            player_id, zone, space_index, exempt_ids,
        )
        exhaustion_text = self.apply_exhaustion(
            game, match, player_id, distance,
        )
        self.persist(game, match)

        return (
            f"{self.player_label(match, player)} "
            f"runs back to {space_label(zone, space_index)}."
            f"\n{exhaustion_text}"
        )

    def run_back_kickoff_fill(
        self,
        game: D12BallGame,
        match: MatchState,
    ) -> tuple[bool, Optional[str]]:
        """
        Settle a pending kickoff fill, and say whether the cascade goes
        round again -- with the line describing the drop back, when
        somebody actually moved.

        A goal (or own goal) restarts play with nobody necessarily
        standing on the kickoff space -- the conceding side's two
        midfield players could easily both be elsewhere in the zone
        from open play. Whoever's closest drops back to start the
        kickoff, at the usual run-back cost, once every other run-back
        is settled.

        Asked here rather than back in restart_after_goal because
        everyone has moved since: the new play's reset, and any
        placement its substitution window made. Somebody standing on
        the space already settles it for nothing.
        """
        if match.eligible_ball_handlers():
            match.pending_kickoff_fill = False
            self.persist(game, match)
            return True, None

        candidates = match.kickoff_fill_candidates()
        if candidates:
            player_id = candidates[0]
            player = self.engine.get_player_definition(player_id)
            distance = match.fill_kickoff(player_id)
            exhaustion_text = self.apply_exhaustion(
                game, match, player_id, distance,
            )
            self.persist(game, match)

            return True, (
                f"{self.player_label(match, player)} "
                "drops back to "
                f"{space_label(match.ball.zone, match.ball.space_index)} "
                f"to start the kickoff.\n{exhaustion_text}"
            )

        # Nobody fielded in midfield at all (both benched or injured)
        # -- nothing to place. Clear the flag and let the loose-ball
        # check downstream handle the empty kickoff. The save is the
        # caller's, which is about to write the settled run back out
        # anyway.
        match.pending_kickoff_fill = False
        return False, None

    async def send_run_back_prompt(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        side: TeamSide,
        candidates: list[str],
        lead_in: str = "",
    ) -> None:
        """
        Put a coach's run-back choice up, over **the field strip**.
        Both questions a run back asks -- which of these players goes,
        and which space they go to -- are questions about where
        everybody is standing and how far each space is, and the
        persistent message has scrolled away up the channel by the time
        a turn has resolved.

        **The strip rather than the whole match image**, which is what
        this carried before: the jumbotron, the assignment cards, the
        team boards and the benches are not what either question turns
        on, and dropping them is what makes the field itself legible
        inline. It is a crop of that same board (`render_field_image`),
        so it cannot show a different position from the one the
        persistent message settles on -- and it is the same picture the
        five distance prompts carry, for the same reason.

        It costs a second render rather than a second upload: the
        cascade's own board settles the persistent message, and this
        draws the strip beside it. Both are `asyncio.to_thread` like
        every other render, and the request count is unchanged -- see
        "Discord's rate limits". The picture goes with the prompt: the
        click edits both away together, so the field a coach is reading
        is never one of a position that has moved on.
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
            body = self.run_back_space_prompt(
                game, match, side, candidates[0], mention,
            )
        else:
            prompt_view = RunBackPlayerChoiceView(self, game.game_id, candidates)
            body = self.run_back_player_prompt(
                match, side, candidates, mention,
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
        the turn on to whatever it was still holding up.
        """
        match.pending_run_back = False
        distance_moved = match.pending_run_back_distance
        turnover_occurred = match.pending_run_back_turnover
        speed_choice_after = match.pending_run_back_speed_choice
        stays_player_id = match.pending_run_back_stays_player_id
        match.pending_run_back_speed_choice = False

        # **Charge-up, now that everybody who was going to move has.**
        # It rides on `lead_in` rather than being sent on its own: this
        # is the tail of a cascade that has been batching its messages
        # all the way down, and a line about drain tokens does not earn
        # a message of its own -- see "Discord's rate limits".
        if match.pending_run_back_charge_up:
            match.pending_run_back_charge_up = False
            charge_up = self.apply_charge_up(game, match)
            if charge_up:
                lead_in = "\n\n".join(filter(None, (lead_in, charge_up)))
        match.run_back_moved = []
        self.persist(game, match)

        if match.pending_ball_recovery:
            # An out-of-bounds ball is still lying there with nobody
            # on it. Now that everyone is back in position, the side
            # that won it sends the nearest player either side of it,
            # at the usual per-space cost.
            await self.begin_ball_recovery(
                interaction, game, match, lead_in=lead_in,
            )
            return

        if speed_choice_after:
            # Steal: the defender who stole the ball still
            # gets to manipulate its speed, now that everyone is back
            # in position.
            await self.offer_speed_choice(
                interaction,
                game,
                match,
                player_id=stays_player_id,
                skill_type="defense",
                turnover_occurred=turnover_occurred,
                distance_moved=distance_moved,
                lead_in=lead_in,
            )
            return

        # Run-back itself only ever costs exhaustion, not time -- the
        # time cost is whatever the triggering maneuver's own ball
        # movement was, stashed by begin_run_back.
        await self.finish_maneuver_resolution(
            interaction,
            game,
            match,
            distance_moved=distance_moved,
            turnover_occurred=turnover_occurred,
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
        Auto-place every forced run-back (no real choice: the open
        spaces in a zone exactly match the players who need one) right
        away, then either present a choice for the next player who has
        a real one, or finish once nobody is displaced.

        `lead_in` only ever applies to the first message this call (or
        the resumption in RunBackChoiceView) sends -- every call site
        that already consumed it passes none.

        Every placement made without asking anyone -- the forced ones,
        the AI's choices, the drop back that fills an empty kickoff --
        collects into one message and one board refresh, flushed when
        the cascade reaches a coach's choice or runs out. It used to
        post a message and re-upload the board per player, which after
        a steal that scatters a 4-1-1 side is a dozen-odd REST calls
        into one channel with nothing between them, and enough to be
        rate limited for it. Nobody is reading the intermediate boards
        anyway: the one worth looking at is the one where everyone has
        finished moving.
        """
        # Lines describing placements already applied and saved, and
        # not yet posted. `lead_in` is consumed by whichever message
        # goes out first, which may be this one or the prompt below.
        notes: list[str] = []

        # Every pass either places somebody or ends the cascade, so
        # this can only be reached if a placement left the player it
        # moved still owed one. That should not be possible -- see
        # placement_spaces_in_zone -- but as a recursion it was bounded
        # by the interpreter and as a loop it is not, and a spin here
        # hangs the event loop for every game at once. An ERROR,
        # because a run back that will not settle needs someone to
        # look at it.
        remaining_passes = MAX_RUN_BACK_PASSES

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

        while True:
            remaining_passes -= 1
            if remaining_passes < 0:
                LOGGER.error(
                    "Giving up on the run back for D12 Ball game %s after "
                    "%d placements: it is not settling. The match is saved "
                    "as it stands.",
                    game.game_id,
                    MAX_RUN_BACK_PASSES,
                )
                break

            self.engine.apply_forced_run_backs(game, match)
            self.persist(game, match)

            step = self.engine.next_run_back_step(game, match)

            if step is not None:
                side, candidates = step

                if self.engine.side_is_ai(game, side):
                    notes.append(
                        self.run_back_ai_placement(
                            game, match, side, candidates,
                        )
                    )
                    continue

                # A coach's choice ends the cascade here: say what has
                # happened so far, settle the board it left, and ask.
                #
                # The board goes on the persistent message; the prompt
                # draws its own field strip (see send_run_back_prompt).
                # Two renders, two uploads -- the requests are what the
                # gate counts, and they are unchanged. See "Discord's
                # rate limits" in docs/design/rate-limits.md.
                png = await self.render_match_png(game)
                if not await flush(png):
                    await self.refresh_match_image(interaction, game, png=png)

                await self.send_run_back_prompt(
                    interaction,
                    game,
                    match,
                    side,
                    candidates,
                    lead_in=lead_in,
                )
                return

            if match.pending_kickoff_fill:
                keep_going, note = self.run_back_kickoff_fill(game, match)
                if note is not None:
                    notes.append(note)
                if keep_going:
                    continue

            break

        await flush()
        await self.finish_run_back(interaction, game, match, lead_in=lead_in)

    # -- Out-of-bounds recovery (after the run back) ------------------

    async def begin_ball_recovery(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        lead_in: str = "",
    ) -> None:
        """
        The Discord half of the out-of-bounds pickup --
        `ball_recovery_step` in `d12ball/flow/turnovers.py`, which is
        where the reasoning now lives.

        All three of its branches carry `lead_in` on into whatever
        comes next, which is why it goes in at the front of the
        result's narration rather than being handed to the step: how
        the line before a question joins the question is the
        frontend's (principle 8), and `dispatch_step_result` is where
        that is decided for every step at once.

        **The persist is the transition rule** (principle 9): the step
        no longer saves, the spine under it is still the cog's, and
        two of the three branches hand the turn to a click that
        reloads the match out of the save file.
        """
        result = ball_recovery_step(self.engine, game, match)
        if lead_in:
            result.narration.insert(0, lead_in)
        self.persist(game, match)
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

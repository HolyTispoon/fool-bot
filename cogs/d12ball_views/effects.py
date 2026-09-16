"""
The choices a won maneuver puts to its winner: pass distances and
receivers, dribble distances, ball speed. Plus the tutorial's Continue
gate and the shooter pick a set-up hands on, which sit here because
they are the same shape -- one prompt answering one question.
"""

import discord
from typing import Awaitable, Callable, TYPE_CHECKING

from d12ball import tutorial
from d12ball.components import PlayerRole
from d12ball.game import team_display_name
from cogs.d12ball_helpers import (
    ROLE_INITIALS,
    build_full_image_button,
    space_label,
)

from cogs.d12ball_views.base import SafeView
from cogs.d12ball_views.runback import RunBackChoiceView

if TYPE_CHECKING:
    from cogs.d12ball import D12Ball


class LowPassChoiceView(SafeView):
    """
    Which teammate-occupied space to pass to -- Low Pass has no fixed
    distance anymore, only the nearest teammate each way within 2
    spaces and one sharing the ball's space, each of which must be a
    *different* player, so the destination is usually the whole choice.
    Where the space picked holds more than one teammate -- ordinary
    under a formation that stacks -- LowPassReceiverView asks which of
    them takes it. A handler with nobody in reach never sees either
    view: resolve_low_pass settles that case without a prompt.

    **The prompt carries the passer's own half-field, with the ball on
    it** -- every destination here is counted from where the ball is
    standing, and the persistent board has usually scrolled away by
    the time a maneuver resolves. Both views edit that one message, so
    the picture is uploaded once and taken away by whichever of them
    answers the question (`attachments=[]`); a restart re-posts the
    prompt without it, the same as every other image a resume loses.

    Reconstructible on restart purely from match state (see
    D12Ball.build_effect_choice_view), the same pattern every other
    persistent view in this cog follows.
    """

    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
        key: str = "low_pass",
        free: bool = False,
    ):
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id
        # Which card is being resolved, so the destinations offered are
        # the ones that card actually reaches -- a Skilled Pass reaches
        # any teammate within 3 spaces, ahead or behind. `free` is the
        # unopposed pass Skilled Pass's cost hands the defense, which
        # charges no clock.
        self.key = key
        self.free = free

        game, match = self.load_match()
        if game is None:
            return

        for distance, teammate_id in cog.engine.pass_candidates(match, key):
            teammate = cog.engine.get_player_definition(teammate_id)
            origin_flat = match.board.flat_index(
                match.ball.zone, match.ball.space_index,
            )
            target_flat = match.relative_flat_index(
                origin_flat, match.ball.possession, distance,
            )
            zone, space_index = match.board.position_at_flat_index(
                target_flat,
            )
            receivers = cog.engine.low_pass_receivers(match, distance)
            role_initial = ROLE_INITIALS[teammate.role.value]
            if len(receivers) > 1:
                # Naming one of several would misread the choice: the
                # space is what is being picked here, and who receives
                # comes next.
                label = (
                    f"{len(receivers)} players -- "
                    f"{space_label(zone, space_index)}"
                )
            else:
                label = (
                    f"{teammate.name} [{role_initial}] -- "
                    f"{space_label(zone, space_index)}"
                )
            button = discord.ui.Button(
                label=label,
                style=discord.ButtonStyle.primary,
                custom_id=f"d12ball:low_pass:{game_id}:{distance}",
            )

            async def callback(
                interaction: discord.Interaction,
                chosen_distance: int = distance,
            ) -> None:
                await self.choose(interaction, chosen_distance)

            button.callback = callback
            self.add_item(button)

    async def choose(
        self,
        interaction: discord.Interaction,
        distance: int,
    ) -> None:
        game, match = await self.require_match(interaction)
        if game is None:
            return

        if not self.cog.engine.user_controls_possession(
            interaction.user.id, game, match,
        ):
            await interaction.response.send_message(
                "Only the player resolving this effect can choose.",
                ephemeral=True,
            )
            return

        offense_side = match.ball.possession
        receivers = self.cog.engine.low_pass_receivers(match, distance)
        origin_flat = match.board.flat_index(
            match.ball.zone, match.ball.space_index,
        )
        target_flat = match.relative_flat_index(
            origin_flat, offense_side, distance,
        )
        zone, space_index = match.board.position_at_flat_index(target_flat)
        team_name = team_display_name(match.setup_for_side(offense_side).team)

        if len(receivers) > 1:
            # Which of them takes it is read off the same half-field
            # the space was picked off, so the attachment stays put --
            # this edit passes no `attachments`, which leaves the one
            # already on the message alone. Editing a view replaces it
            # wholesale, though, so the full-image link has to be
            # rebuilt onto the new one by hand (see
            # RunBackPlayerChoiceView, which shares a board the same
            # way).
            receiver_view = LowPassReceiverView(
                self.cog, self.game_id, distance,
                key=self.key, free=self.free,
            )
            link = build_full_image_button(interaction.message)
            if link is not None:
                receiver_view.add_item(link)
            await interaction.response.edit_message(
                content=(
                    f"**{interaction.user.display_name} ({team_name})** is "
                    f"passing to {space_label(zone, space_index)}. Which "
                    "player receives it?"
                ),
                view=receiver_view,
            )
            return

        teammate = self.cog.engine.get_player_definition(receivers[0])
        await interaction.response.edit_message(
            content=(
                f"**{interaction.user.display_name} ({team_name})** chose "
                "to pass the ball to "
                f"{self.cog.player_label(match, teammate)} at "
                f"{space_label(zone, space_index)}."
            ),
            view=None,
            # The half-field this was asked over shows the ball where
            # it was *before* the pass, so it goes with the question
            # rather than standing under the answer -- the same call
            # the run back's board makes.
            attachments=[],
        )
        await self.cog.apply_low_pass(
            interaction, game, match, distance, receiver_id=receivers[0],
            key=self.key, free=self.free,
        )


class LowPassReceiverView(SafeView):
    """
    Which of the teammates on the destination space takes the pass.
    Only shown when more than one is standing there, which a formation
    that stacks makes ordinary; the pick decides who a Winger's set-up
    offers the shot to.

    Unlike LowPassChoiceView this cannot be rebuilt from match state
    alone -- the destination it belongs to is not written anywhere
    until the pass is applied -- so a restart mid-choice drops back to
    the destination prompt (see D12Ball.build_effect_choice_view).
    Nothing has been committed at that point.
    """

    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
        distance: int,
        key: str = "low_pass",
        free: bool = False,
    ):
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id
        self.distance = distance
        self.key = key
        self.free = free

        game, match = self.load_match()
        if game is None:
            return

        for player_id in cog.engine.low_pass_receivers(match, distance):
            player = cog.engine.get_player_definition(player_id)
            button = discord.ui.Button(
                label=(
                    f"{player.name} [{ROLE_INITIALS[player.role.value]}]"
                )[:80],
                style=discord.ButtonStyle.primary,
                custom_id=(
                    f"d12ball:low_pass_receiver:{game_id}:"
                    f"{distance}:{player_id}"
                ),
            )

            async def callback(
                interaction: discord.Interaction,
                chosen: str = player_id,
            ) -> None:
                await self.choose(interaction, chosen)

            button.callback = callback
            self.add_item(button)

    async def choose(
        self,
        interaction: discord.Interaction,
        receiver_id: str,
    ) -> None:
        game, match = await self.require_match(interaction)
        if game is None:
            return

        if not self.cog.engine.user_controls_possession(
            interaction.user.id, game, match,
        ):
            await interaction.response.send_message(
                "Only the player resolving this effect can choose.",
                ephemeral=True,
            )
            return

        if receiver_id not in self.cog.engine.low_pass_receivers(
            match, self.distance,
        ):
            await interaction.response.send_message(
                "That player is no longer standing there.",
                ephemeral=True,
            )
            return

        offense_side = match.ball.possession
        receiver = self.cog.engine.get_player_definition(receiver_id)
        origin_flat = match.board.flat_index(
            match.ball.zone, match.ball.space_index,
        )
        zone, space_index = match.board.position_at_flat_index(
            match.relative_flat_index(origin_flat, offense_side, self.distance)
        )
        team_name = team_display_name(match.setup_for_side(offense_side).team)

        await interaction.response.edit_message(
            content=(
                f"**{interaction.user.display_name} ({team_name})** chose "
                "to pass the ball to "
                f"{self.cog.player_label(match, receiver)} at "
                f"{space_label(zone, space_index)}."
            ),
            view=None,
            # The ball on it has not moved yet, so the picture goes
            # with the question -- see LowPassChoiceView.choose.
            attachments=[],
        )
        await self.cog.apply_low_pass(
            interaction, game, match, self.distance, receiver_id=receiver_id,
            key=self.key, free=self.free,
        )


class SetupPassChoiceView(SafeView):
    """
    Where a won **Setup Pass** lands: 0, 1 or 3 spaces, and the
    teammate standing there takes a scoring opportunity.

    Reconstructible on restart from match state, the same as every
    other persistent view here -- but only reached at all while
    `pending_effect_continuation` says the speed half of the card is
    already done, which is what `build_effect_choice_view` reads.

    **Every distance that fits on the field is offered**, whether or
    not a teammate is standing there (the author, 2026-08-25) -- the
    button says which, and picking one out into empty space leaves the
    ball lying there rather than being refused. `0` is the one
    exception: it means a teammate sharing the passer's own space, so
    it is on the menu only while somebody else is standing there. With
    nothing at all on the menu -- the passer on the last space of the
    field with nobody beside them -- the view is not shown and the pass
    goes out (see `D12Ball.apply_setup_pass_out`).
    """

    def __init__(self, cog: "D12Ball", game_id: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id

        game, match = self.load_match()
        if game is None:
            return

        for distance in cog.engine.setup_pass_distances(match):
            note = (
                "same space"
                if distance == 0
                else cog.engine.high_pass_destination_note(match, distance)
            )
            # 1 is a distance this card offers and the High Pass does
            # not, so this is the one pass menu that can read "1
            # spaces" if nothing here says otherwise.
            space_word = "space" if distance == 1 else "spaces"
            button = discord.ui.Button(
                label=f"{distance} {space_word} ({note})",
                style=discord.ButtonStyle.primary,
                custom_id=f"d12ball:setup_pass:{game_id}:{distance}",
            )

            async def callback(
                interaction: discord.Interaction,
                chosen_distance: int = distance,
            ) -> None:
                await self.choose(interaction, chosen_distance)

            button.callback = callback
            self.add_item(button)

    async def choose(
        self,
        interaction: discord.Interaction,
        distance: int,
    ) -> None:
        game, match = await self.require_match(interaction)
        if game is None:
            return

        if not self.cog.engine.user_controls_possession(
            interaction.user.id, game, match,
        ):
            await interaction.response.send_message(
                "Only the player resolving this effect can choose.",
                ephemeral=True,
            )
            return

        # Re-read rather than trusted: this prompt carries no message
        # id, so an older one still in the channel dispatches here too.
        if distance not in self.cog.engine.setup_pass_distances(match):
            await interaction.response.edit_message(
                content=(
                    "That distance is not on offer any more -- 0 spaces "
                    "needs a teammate in your own space, and every other "
                    "distance has to fit on the field. Use "
                    "`/d12ball resume` to put the choice back up."
                ),
                view=None,
                attachments=[],
            )
            return

        team_name = team_display_name(
            match.setup_for_side(match.ball.possession).team
        )
        # The field strip goes with the question: it shows the ball
        # where it was before the pass, so leaving it under the answer
        # would put a stale position in the channel.
        await interaction.response.edit_message(
            content=(
                f"**{interaction.user.display_name} ({team_name})** picks "
                f"out a **Setup Pass** of {distance}."
            ),
            view=None,
            attachments=[],
        )
        await self.cog.apply_setup_pass(interaction, game, match, distance)


class SetupPassPushBackView(SafeView):
    """
    **Setup Pass's cost**, put to the coach who beat it: how far back
    the ball is driven -- 1, 2 or 3 spaces -- before it is left loose.

    The choice belongs to the *defending* side, which is the side that
    won the maneuver, so this is the one prompt in a maneuver's effect
    that the defense answers and the offense watches.

    Not reconstructible from match state: by the time it is up, the
    deflection has already landed and nothing on the match says a
    push-back is owed. A restart mid-choice comes back to whatever
    `pending_turn_view` makes of the position, which is the same gap
    `SetUpAttemptChoiceView` has and for the same reason -- nothing has
    been applied yet.
    """

    def __init__(self, cog: "D12Ball", game_id: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id

        game, match = self.load_match()
        if game is None:
            return

        offense_side = match.ball.possession
        origin_flat = match.board.flat_index(
            match.ball.zone, match.ball.space_index,
        )
        for distance in (1, 2, 3):
            target_flat = match.relative_flat_index(
                origin_flat, offense_side, -distance,
            )
            if abs(target_flat - origin_flat) != distance:
                continue
            zone, space_index = match.board.position_at_flat_index(target_flat)
            button = discord.ui.Button(
                label=(
                    f"{distance} back ({space_label(zone, space_index)})"
                ),
                style=discord.ButtonStyle.primary,
                custom_id=f"d12ball:setup_pass_push:{game_id}:{distance}",
            )

            async def callback(
                interaction: discord.Interaction,
                chosen_distance: int = distance,
            ) -> None:
                await self.choose(interaction, chosen_distance)

            button.callback = callback
            self.add_item(button)

    async def choose(
        self,
        interaction: discord.Interaction,
        distance: int,
    ) -> None:
        game, match = await self.require_match(interaction)
        if game is None:
            return

        if not self.cog.engine.user_controls_defense(
            interaction.user.id, game, match,
        ):
            await interaction.response.send_message(
                "Only the coach who beat the Setup Pass can choose.",
                ephemeral=True,
            )
            return

        await interaction.response.edit_message(view=None)
        await self.cog.apply_setup_pass_push_back(
            interaction, game, match, distance,
        )


class HighPassChoiceView(SafeView):
    """
    Distance for a won High Pass -- 2 or 3 spaces, or up to 4 for a
    Fullback (their ability extends the max, not the min).
    Reconstructible on restart purely from match state, the same
    pattern every other persistent view in this cog follows.

    **Only distances that fit on the field are offered** (2026-08-10),
    from D12Ball.high_pass_distance_options: a longer pass that lands
    where a shorter one already would is the same pass at a
    disadvantage, so a Fullback near the end is not offered 4 and
    nobody is offered 3 when a 2 fits. When nothing fits the view is
    not shown at all -- resolve_high_pass sends the pass straight to
    its overshoot rather than putting up one answer three times.

    **The prompt carries the field strip**, for the reason the maneuver
    cards do: which distance to throw is a question about where
    everybody is standing and how far the end of the field is, and the
    persistent board has scrolled away by this point in a turn. It is
    an attachment on the prompt rather than a message of its own --
    unlike the field under the cards, which shares its message with the
    hand and would be laid out beside it -- so `choose` can strip it
    with `attachments=[]` in the edit it was already making. Leaving it
    under the answer would show the ball where it was before the pass.
    """

    def __init__(self, cog: "D12Ball", game_id: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id

        game, match = self.load_match()
        if game is None:
            return

        distances = cog.engine.high_pass_distance_options(match)
        railed = cog.tutorial_railed_option(game, "high_pass", distances)

        for distance in distances:
            ability_note = " (Fullback ability)" if distance == 4 else ""
            destination_note = cog.engine.high_pass_destination_note(match, distance)
            button = discord.ui.Button(
                label=(
                    f"{distance} spaces{ability_note} ({destination_note})"
                ),
                style=discord.ButtonStyle.primary,
                custom_id=f"d12ball:high_pass:{game_id}:{distance}",
                disabled=railed is not None and distance != railed,
            )

            async def callback(
                interaction: discord.Interaction,
                chosen_distance: int = distance,
            ) -> None:
                await self.choose(interaction, chosen_distance)

            button.callback = callback
            self.add_item(button)

    async def choose(
        self,
        interaction: discord.Interaction,
        distance: int,
    ) -> None:
        game, match = await self.require_match(interaction)
        if game is None:
            return

        if not self.cog.engine.user_controls_possession(
            interaction.user.id, game, match,
        ):
            await interaction.response.send_message(
                "Only the player resolving this effect can choose.",
                ephemeral=True,
            )
            return

        # A click on a menu the ball has since moved out from under --
        # an older prompt still sitting in the channel, since these
        # buttons carry no message id. The distances are read off the
        # match rather than off the view for exactly that reason.
        if distance not in self.cog.engine.high_pass_distance_options(match):
            await interaction.response.send_message(
                f"A {distance}-space pass runs off the end of the field "
                "from where the ball is now.",
                ephemeral=True,
            )
            return

        railed = self.cog.tutorial_railed_option(
            game, "high_pass",
            self.cog.engine.high_pass_distance_options(match),
        )
        if railed is not None and distance != railed:
            await interaction.response.send_message(
                "The tutorial is on one step of a single continuous game, "
                "so this choice is fixed. Use the prompt at the "
                "bottom of the channel.",
                ephemeral=True,
            )
            return

        # `attachments=[]` takes the field strip with the question it
        # answered. It shows the ball where it was *before* the pass, so
        # leaving it under the answer would put a stale position in the
        # channel for the rest of the game -- the same reason the run
        # back drops its snapshot on the click.
        await interaction.response.edit_message(
            content=f"Chose **{distance} spaces**.",
            view=None,
            attachments=[],
        )
        await self.cog.apply_high_pass(interaction, game, match, distance)


class SetUpAttemptChoiceView(SafeView):
    """
    Whether to take an offered scoring-opportunity shot -- a High
    Pass's own 2-space pass, a High Pass that overshoots the field, or
    a Winger's Low Pass ability -- or let the maneuver resolve as a
    normal pass instead. Declining meant the same thing everywhere
    between 2026-08-07, when a 2-space High Pass stopped forcing a
    contest for the ball it had just delivered, and 2026-08-10, when an
    overshoot started offering a shot *or* a contest, both at the same
    disadvantage: `contest_on_decline` is that one case, and the button
    says so rather than promising a normal pass it will not deliver.

    Not reconstructible on restart the way the rest of this cog's
    views are -- match state doesn't record which maneuver offered
    this choice or who the shooter is, the same narrow crash-window
    gap D12Ball.build_effect_choice_view already accepts for a
    Playmaker's Dribble Advance.
    """

    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
        shooter_id: str,
        distance_moved: int,
        contest_on_decline: bool = False,
    ):
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id
        self.shooter_id = shooter_id
        self.distance_moved = distance_moved
        self.contest_on_decline = contest_on_decline

        shooter = cog.engine.get_player_definition(shooter_id)
        attempt_button = discord.ui.Button(
            label=f"{shooter.name} takes the shot",
            style=discord.ButtonStyle.danger,
            custom_id=f"d12ball:setup_attempt:{game_id}:attempt",
        )
        attempt_button.callback = self.attempt
        self.add_item(attempt_button)

        decline_button = discord.ui.Button(
            label=(
                "Decline -- contest for the ball"
                if contest_on_decline
                else "Decline -- resolve as a normal pass"
            ),
            style=discord.ButtonStyle.secondary,
            custom_id=f"d12ball:setup_attempt:{game_id}:decline",
            # The tutorial ends on this shot, so declining it would end
            # the script on a pass and no goal.
            disabled=cog.tutorial_railed_option(
                cog.games.get(game_id),
                "setup_attempt",
                ("attempt", "decline"),
            ) == "attempt",
        )
        decline_button.callback = self.decline
        self.add_item(decline_button)

    async def attempt(self, interaction: discord.Interaction) -> None:
        game, match = await self.require_match(interaction)
        if game is None:
            return

        if not self.cog.engine.user_controls_possession(
            interaction.user.id, game, match,
        ):
            await interaction.response.send_message(
                "Only the player resolving this effect can choose.",
                ephemeral=True,
            )
            return

        shooter = self.cog.engine.get_player_definition(self.shooter_id)
        await interaction.response.edit_message(
            content=(
                f"{self.cog.player_label(match, shooter)} "
                "takes the shot."
            ),
            view=None,
        )
        await self.cog.start_set_up_shot(
            interaction, game, match, self.shooter_id,
            maneuver_cost=self.distance_moved,
        )

    async def decline(self, interaction: discord.Interaction) -> None:
        game, match = await self.require_match(interaction)
        if game is None:
            return

        if not self.cog.engine.user_controls_possession(
            interaction.user.id, game, match,
        ):
            await interaction.response.send_message(
                "Only the player resolving this effect can choose.",
                ephemeral=True,
            )
            return

        await interaction.response.edit_message(
            content="Declined the scoring opportunity.",
            view=None,
        )
        await self.cog.decline_scoring_attempt(
            interaction, game, match, self.distance_moved,
            contest=self.contest_on_decline,
        )


class DribbleAdvanceChoiceView(SafeView):
    """
    Playmaker-only: may advance 1 or 2 spaces on a won Dribble
    Advance. Every other role has no choice to make, so
    D12Ball.resolve_dribble_advance never even shows this.
    """

    def __init__(self, cog: "D12Ball", game_id: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id

        # The two distances are two spaces, and which they are depends
        # on where the handler is standing and which way their side
        # attacks -- neither of which "1 or 2" tells a coach. Naming
        # the destination also shows when the longer dribble buys
        # nothing, because the field ran out and both clamp to the same
        # space.
        game = cog.games.get(game_id)
        match = (
            cog.engine.load_match_state(game)
            if game is not None and game.match_state is not None
            else None
        )

        railed = cog.tutorial_railed_option(game, "dribble_advance", (1, 2))

        for distance in (1, 2):
            space_word = "space" if distance == 1 else "spaces"
            destination = (
                match.relative_move_destination(
                    match.active_player_id, match.ball.possession, distance,
                )
                if match is not None and match.active_player_id is not None
                else None
            )
            destination_note = (
                f" ({space_label(*destination)})"
                if destination is not None
                else ""
            )
            button = discord.ui.Button(
                label=f"Advance {distance} {space_word}{destination_note}",
                style=discord.ButtonStyle.primary,
                custom_id=f"d12ball:dribble_advance:{game_id}:{distance}",
                # Railed during the tutorial: where the ball ends up is
                # what the next beat is written against.
                disabled=railed is not None and distance != railed,
            )

            async def callback(
                interaction: discord.Interaction,
                chosen_distance: int = distance,
            ) -> None:
                await self.choose(interaction, chosen_distance)

            button.callback = callback
            self.add_item(button)

    async def choose(
        self,
        interaction: discord.Interaction,
        distance: int,
    ) -> None:
        game, match = await self.require_match(interaction)
        if game is None:
            return

        if not self.cog.engine.user_controls_possession(
            interaction.user.id, game, match,
        ):
            await interaction.response.send_message(
                "Only the player resolving this effect can choose.",
                ephemeral=True,
            )
            return

        railed = self.cog.tutorial_railed_option(
            game, "dribble_advance", (1, 2),
        )
        if railed is not None and distance != railed:
            await interaction.response.send_message(
                "The tutorial is on one step of a single continuous game, "
                "so this choice is fixed. Use the prompt at the "
                "bottom of the channel.",
                ephemeral=True,
            )
            return

        space_word = "space" if distance == 1 else "spaces"
        await interaction.response.edit_message(
            content=f"Chose **{distance} {space_word}**.",
            view=None,
        )
        await self.cog.apply_dribble_advance(interaction, game, match, distance)


class DribbleBurstChoiceView(SafeView):
    """
    How far a won Dribble Burst runs: 1 up to
    `DRIBBLE_BURST_MAX_DISTANCE`, less anything the end of the field
    takes away. Shaped like DribbleAdvanceChoiceView, which is the
    other dribble that asks a distance, and reconstructible on restart
    from match state alone (see D12Ball.build_effect_choice_view).

    **Every button carries its price**, because the exhaustion is a
    token a space and that is the whole of what makes the shorter runs
    worth offering -- the same reasoning as RunBackChoiceView's
    `M2 (4 spaces)` labels, where the distance *is* the cost. The
    Playmaker's token off comes out of the total rather than off each
    space, so it is named once beside the run it discounts rather than
    subtracted from every label.

    A handler already on the last space of the field never sees this:
    resolve_dribble_burst applies a run of 0 without a prompt.
    """

    def __init__(self, cog: "D12Ball", game_id: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id

        game, match = self.load_match()
        if game is None or match.active_player_id is None:
            # No handler means no run to price. Only reachable in the
            # same narrow crash window every other reconstructed view
            # has; the empty view falls back to PlayerActionView.
            return

        handler_id = match.active_player_id
        playmaker = (
            cog.engine.get_player_definition(handler_id).role
            == PlayerRole.PLAYMAKER
        )

        for distance in cog.engine.dribble_burst_distances(match):
            space_word = "space" if distance == 1 else "spaces"
            # Naming the destination is what "3 spaces" does not say:
            # which way this side attacks and where that lands is read
            # off the board, and the board has usually scrolled away.
            destination = match.relative_move_destination(
                handler_id, match.ball.possession, distance,
            )
            tokens = max(0, distance - (1 if playmaker else 0))
            token_word = "token" if tokens == 1 else "tokens"
            button = discord.ui.Button(
                label=(
                    f"{distance} {space_word} "
                    f"({space_label(*destination)}, {tokens} {token_word})"
                ),
                style=discord.ButtonStyle.primary,
                custom_id=f"d12ball:dribble_burst:{game_id}:{distance}",
            )

            async def callback(
                interaction: discord.Interaction,
                chosen_distance: int = distance,
            ) -> None:
                await self.choose(interaction, chosen_distance)

            button.callback = callback
            self.add_item(button)

    async def choose(
        self,
        interaction: discord.Interaction,
        distance: int,
    ) -> None:
        game, match = await self.require_match(interaction)
        if game is None:
            return

        if not self.cog.engine.user_controls_possession(
            interaction.user.id, game, match,
        ):
            await interaction.response.send_message(
                "Only the player resolving this effect can choose.",
                ephemeral=True,
            )
            return

        # A stale click: an older prompt in the channel, or one the
        # handler has since been moved out from under. The menu carries
        # no message id, so this is the check that catches it -- the
        # same refusal HighPassChoiceView makes for the same reason.
        if distance not in self.cog.engine.dribble_burst_distances(match):
            await interaction.response.send_message(
                "That distance is no longer available.",
                ephemeral=True,
            )
            return

        space_word = "space" if distance == 1 else "spaces"
        await interaction.response.edit_message(
            content=f"Chose **{distance} {space_word}**.",
            view=None,
        )
        await self.cog.apply_dribble_burst(interaction, game, match, distance)


class SpeedDeltaChoiceView(SafeView):
    """
    Ball-speed manipulation for Dribble Advance (offense skill) or
    Steal Intercept (defense skill, chosen by the intercepting player
    even though possession has already flipped to their side by the
    time this is shown -- `player_id` pins down whose skill and whose
    controller apply, sidestepping that ambiguity entirely).
    """

    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
        player_id: str,
        skill_type: str,
    ):
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id
        self.player_id = player_id
        self.skill_type = skill_type

        game, match = self.load_match()
        if game is None:
            return
        profile = cog.player_catalog.effective_profile(
            cog.engine.get_player_definition(player_id),
        )
        skill = profile.offense if skill_type == "offense" else profile.defense
        current = match.ball.speed

        # The targets are collected before any button is built, because
        # the tutorial's speed rail is "take the highest offered" -- the
        # cap is the stealer's own defensive skill, so the script cannot
        # name a number. See D12Ball.tutorial_railed_option.
        targets: list[int] = []
        for delta in range(-skill, skill + 1):
            target = max(1, min(12, current + delta))
            if target not in targets:
                targets.append(target)
        railed = cog.tutorial_railed_option(game, "speed", targets)

        for target in targets:
            actual_delta = target - current
            if actual_delta == 0:
                label = f"{target} (no change)"
            else:
                sign = "+" if actual_delta > 0 else ""
                label = f"{target} ({sign}{actual_delta})"

            button = discord.ui.Button(
                label=label,
                style=discord.ButtonStyle.primary,
                custom_id=f"d12ball:speed:{game_id}:{target}",
                # Railed during the tutorial -- the ball speed a steal
                # leaves behind is still on the ball when the striker
                # shoots two beats later.
                disabled=railed is not None and target != railed,
            )

            async def callback(
                interaction: discord.Interaction,
                chosen_target: int = target,
            ) -> None:
                await self.choose(interaction, chosen_target)

            button.callback = callback
            self.add_item(button)

    async def choose(
        self,
        interaction: discord.Interaction,
        target_speed: int,
    ) -> None:
        game, match = await self.require_match(interaction)
        if game is None:
            return

        controller_id = self.cog.engine.controlling_user_id(
            game, match, self.player_id,
        )
        if interaction.user.id != controller_id:
            await interaction.response.send_message(
                "Only the player resolving this effect can choose.",
                ephemeral=True,
            )
            return

        # A steal -- basic or Intercept -- has already flipped possession
        # (and run the defense back) by the time this view is shown; a
        # dribble never triggers a turnover at all.
        turnover_occurred = match.defense_maneuver in ("steal", "intercept") and (
            self.skill_type == "defense"
        )

        # No separate "chose speed N" confirmation -- apply_speed_choice's
        # own "Ball speed is now N" message says the same thing, so just
        # drop the buttons and let that be the one message.
        await interaction.response.edit_message(view=None)
        await self.cog.apply_speed_choice(
            interaction, game, match, target_speed,
            turnover_occurred=turnover_occurred,
        )


class TutorialContinueView(SafeView):
    """
    A single "Continue" button gating whatever comes next in a run of
    tutorial narration -- see D12Ball.post_tutorial_note. Two or more
    plain-text messages posted back to back with no click between them
    are exactly what gets scrolled past in Discord, so a note that has
    something following it is held here until the coach presses on,
    rather than dumped alongside the rest of the burst.

    Not restart-safe, the same tradeoff the rest of the tutorial makes
    -- see the module docstring in d12ball/tutorial.py: what a restart
    loses is a lesson's text, and a dead Continue button here is the
    same kind of loss. It is never registered with `bot.add_view`, so
    a restart while one is up leaves it unclickable; the game itself
    is unaffected; the coach's own next real action still works.
    """

    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
        on_continue: Callable[[discord.Interaction], Awaitable[None]],
    ):
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id
        self._on_continue = on_continue

        button = discord.ui.Button(
            label="Continue",
            style=discord.ButtonStyle.primary,
            custom_id=f"d12ball:tutorial_continue:{game_id}",
        )
        button.callback = self._continue
        self.add_item(button)

    async def _continue(self, interaction: discord.Interaction) -> None:
        game, _ = self.load_match()
        if game is None or not self.is_game_participant(
            game, interaction.user.id,
        ):
            await interaction.response.send_message(
                "Only a coach in this game can continue.",
                ephemeral=True,
            )
            return

        await interaction.response.edit_message(view=None)
        await self._on_continue(interaction)


class ShooterChoiceView(SafeView):
    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
        candidates: list[str],
    ):
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id

        for player_id in candidates:
            player = cog.engine.get_player_definition(player_id)
            initials = ROLE_INITIALS[player.role.value]
            button = discord.ui.Button(
                label=f"{player.name} [{initials}]",
                style=discord.ButtonStyle.danger,
                custom_id=f"d12ball:shooter:{game_id}:{player_id}",
            )

            async def callback(
                interaction: discord.Interaction,
                chosen_player_id: str = player_id,
            ) -> None:
                await self.choose(interaction, chosen_player_id)

            button.callback = callback
            self.add_item(button)

    async def choose(
        self,
        interaction: discord.Interaction,
        shooter_id: str,
    ) -> None:
        game, match = await self.require_match(interaction)
        if game is None:
            return

        if not self.cog.engine.user_controls_possession(
            interaction.user.id, game, match,
        ):
            await interaction.response.send_message(
                "Only the player resolving this effect can choose.",
                ephemeral=True,
            )
            return

        shooter = self.cog.engine.get_player_definition(shooter_id)
        await interaction.response.edit_message(
            content=(
                f"{self.cog.player_label(match, shooter)} "
                "takes the shot."
            ),
            view=None,
        )
        await self.cog.start_set_up_shot(interaction, game, match, shooter_id)


class MindPullView(SafeView):
    """
    Whether a Telekinetic the ball has just crossed reaches out for it
    -- Slimey's opposite number, and the one ability that interrupts a
    maneuver rather than modifying it. See "Mind Pull (Telekinetic)" in
    docs/living-rules.md.

    **Only that player's own coach may answer**, unlike the roll
    buttons either coach may press: the token is theirs to spend and
    the pull is theirs to decline. Same reasoning as Overdrive's
    declaration.

    The player is in both custom_ids as well as in
    `match.pending_mind_pull`, so a coach who scrolls back to an
    earlier offer in the same turn cannot answer it for somebody else.
    A restart while one of these is up leaves the queue on the match,
    which `pending_turn_view` puts back -- unlike
    `SetUpAttemptChoiceView`, this one *is* reconstructible.
    """

    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
        player_id: str,
    ):
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id
        self.player_id = player_id

        player = cog.engine.get_player_definition(player_id)
        pull = discord.ui.Button(
            label=f"{player.name} reaches for it",
            style=discord.ButtonStyle.primary,
            custom_id=f"d12ball:mind_pull:{game_id}:{player_id}",
        )
        pull.callback = self.pull
        self.add_item(pull)

        let_go = discord.ui.Button(
            label="Let it go",
            style=discord.ButtonStyle.secondary,
            custom_id=f"d12ball:mind_pull_decline:{game_id}:{player_id}",
        )
        let_go.callback = self.decline
        self.add_item(let_go)

    async def claim(self, interaction: discord.Interaction):
        """
        The game and match if this click may answer this offer, or
        `(None, None)` after replying with why it may not.
        """
        game, match = await self.require_match(interaction)
        if game is None:
            return None, None

        # The queue is the whole of "is this offer still live" -- a
        # restart re-arms the prompt off it, and answering removes the
        # player from it, so a second click on the same message finds
        # them gone.
        if self.player_id not in match.pending_mind_pull:
            await interaction.response.send_message(
                "That Mind Pull has already been answered.",
                ephemeral=True,
            )
            return None, None

        if self.cog.engine.controlling_user_id(
            game, match, self.player_id,
        ) != interaction.user.id:
            await interaction.response.send_message(
                "Only the coach whose player that is can answer this.",
                ephemeral=True,
            )
            return None, None
        return game, match

    async def pull(self, interaction: discord.Interaction) -> None:
        game, match = await self.claim(interaction)
        if game is None:
            return

        # Deferred before the roll for the reason SkillTestView.roll
        # spells out: what follows can be a whole turnover, and the
        # three-second window is not enough for it.
        await interaction.response.edit_message(view=None)
        await self.cog.run_mind_pull(
            interaction, game, match, self.player_id,
        )

    async def decline(self, interaction: discord.Interaction) -> None:
        game, match = await self.claim(interaction)
        if game is None:
            return

        player = self.cog.engine.get_player_definition(self.player_id)
        match.pending_mind_pull.remove(self.player_id)
        self.cog.persist(game, match)

        # Nothing is charged for letting it go -- the token is the
        # price of *trying* -- so this says only that they did, and
        # hands the queue on.
        await interaction.response.edit_message(
            content=(
                f"{self.cog.player_label(match, player)} lets the ball "
                "go past."
            ),
            view=None,
        )
        await self.cog.continue_mind_pull(interaction, game, match)

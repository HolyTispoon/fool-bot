"""
The choices a won maneuver puts to its winner: pass distances and
receivers, dribble distances, ball speed. Plus the tutorial's Continue
gate and the shooter pick a set-up hands on, which sit here because
they are the same shape -- one prompt answering one question.
"""

import discord
from typing import TYPE_CHECKING

from d12ball.flow.driver import Action
from d12ball.prompts import PromptKind
from cogs.d12ball_helpers import (
    send_new_prompt,
    build_full_image_button,
    get_team_emoji,
    player_with_role,
    space_label,
)

from cogs.d12ball_views.base import SafeView

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

    **The prompt carries the field strip** -- every destination here
    is counted from where the ball is standing, and who is standing on
    the space it lands on decides how the pass is won; the persistent
    board has usually scrolled away by the time a maneuver resolves.
    Both views edit that one message, so the picture is uploaded once
    and taken away by whichever of them answers the question
    (`attachments=[]`); a restart re-posts the prompt without it, the
    same as every other image a resume loses. See
    `D12Ball.send_field_prompt`.

    Reconstructible on restart purely from match state (see
    D12Ball.build_effect_choice_view), the same pattern every other
    persistent view in this cog follows.
    """

    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
    ):
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id

        # Which card is being resolved -- a Skilled Pass reaches any
        # teammate within 3 spaces, ahead or behind -- and whether the
        # pass is the free one Skilled Pass's cost hands the defense
        # are the prompt's: the destinations offered already account
        # for both, and the driver reads them back off the position.
        game, match = self.load_match()

        options = self.prompt_options(game, match, PromptKind.LOW_PASS_CHOICE)
        if options is None:
            return

        for option in options.passes:
            distance, receivers = option.distance, option.receiver_ids
            zone, space_index = match.ball_destination(
                match.ball.possession, distance,
            )
            if len(receivers) > 1:

                # Naming one of several would misread the choice: the
                # space is what is being picked here, and who receives
                # comes next.
                label = (
                    f"{len(receivers)} players -- "
                    f"{space_label(zone, space_index)}"
                )
            else:
                teammate = cog.engine.get_player_definition(receivers[0])
                label = (
                    f"{player_with_role(teammate)} -- "
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

        if not self.may_act_for_possession(interaction, game, match):
            await interaction.response.send_message(
                "Only the player resolving this effect can choose.",
                ephemeral=True,
            )
            return

        offense_side = match.ball.possession
        # Who is standing where the pass lands is the prompt's, off the
        # same list the buttons were built from. A distance no longer
        # offered -- an older prompt still in the channel -- has no
        # receivers here, and the driver refuses it against the
        # position below.
        options = self.prompt_options(game, match, PromptKind.LOW_PASS_CHOICE)
        receivers = next(
            (
                option.receiver_ids
                for option in (options.passes if options else ())
                if option.distance == distance
            ),
            (),
        )
        zone, space_index = match.ball_destination(offense_side, distance)
        # The clicking coach, named as every message names one: their
        # side's emoji in front (see format_player_with_team).
        team_emoji = get_team_emoji(
            self.cog.team_emojis, match.setup_for_side(offense_side).team,
        )
        coach = f"{team_emoji} {interaction.user.display_name}"

        if len(receivers) > 1:

            # Which of them takes it is read off the same field the
            # space was picked off, so the attachment stays put --
            # this edit passes no `attachments`, which leaves the one
            # already on the message alone. Editing a view replaces it
            # wholesale, though, so the full-image link has to be
            # rebuilt onto the new one by hand (see
            # RunBackPlayerChoiceView, which shares a board the same
            # way).
            receiver_view = LowPassReceiverView(
                self.cog, self.game_id, distance,
            )

            link = build_full_image_button(interaction.message)
            if link is not None:
                receiver_view.add_item(link)
            await interaction.response.edit_message(
                content=(
                    f"**{coach}** is "
                    f"passing to {space_label(zone, space_index)}. Which "
                    "player receives it?"
                ),
                view=receiver_view,
            )
            return

        # Which card and whether it is free are the prompt's, read back
        # off the position by the driver -- not this view's. A
        # distance with nobody under it is refused there too.
        receiver_id = receivers[0] if receivers else None
        result = await self.apply(
            interaction,
            game,
            Action(
                PromptKind.LOW_PASS_CHOICE,
                "",
                {"distance": distance, "receiver_id": receiver_id},
            ),
            carry_from=0,
        )
        if result is None:
            return
        teammate = self.cog.engine.get_player_definition(receiver_id)
        await interaction.response.edit_message(
            content=(
                f"**{coach}** chose "
                "to pass the ball to "
                f"{self.cog.player_label(match, teammate)} at "

                f"{space_label(zone, space_index)}."
            ),
            view=None,
            # The strip this was asked over shows the ball where it
            # was *before* the pass, so it goes with the question rather
            # than standing under the answer -- the same call the run
            # back's own makes.
            attachments=[],
        )
        await self.cog.present(interaction, game, result)


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
    ):
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id
        self.distance = distance

        game, match = self.load_match()

        options = self.prompt_options(game, match, PromptKind.LOW_PASS_CHOICE)
        if options is None:
            return
        receivers = next(
            (
                option.receiver_ids for option in options.passes
                if option.distance == distance
            ),
            (),
        )

        for player_id in receivers:
            player = cog.engine.get_player_definition(player_id)
            button = discord.ui.Button(
                label=player_with_role(player)[:80],
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

        if not self.may_act_for_possession(interaction, game, match):
            await interaction.response.send_message(
                "Only the player resolving this effect can choose.",
                ephemeral=True,
            )
            return

        offense_side = match.ball.possession
        receiver = self.cog.engine.get_player_definition(receiver_id)
        zone, space_index = match.ball_destination(offense_side, self.distance)

        # The clicking coach, named as every message names one: their
        # side's emoji in front (see format_player_with_team).
        team_emoji = get_team_emoji(
            self.cog.team_emojis, match.setup_for_side(offense_side).team,
        )
        coach = f"{team_emoji} {interaction.user.display_name}"

        # The distance is this view's and the receiver is the click's;
        # both go with the action, and a receiver no longer standing
        # there is the driver's to refuse.
        result = await self.apply(
            interaction,
            game,
            Action(
                PromptKind.LOW_PASS_CHOICE,
                "",
                {"distance": self.distance, "receiver_id": receiver_id},
            ),
            carry_from=0,
        )
        if result is None:
            return
        await interaction.response.edit_message(
            content=(
                f"**{coach}** chose "
                "to pass the ball to "
                f"{self.cog.player_label(match, receiver)} at "
                f"{space_label(zone, space_index)}."
            ),
            view=None,
            # The ball on it has not moved yet, so the picture goes
            # with the question -- see LowPassChoiceView.choose.
            attachments=[],
        )
        await self.cog.present(interaction, game, result)


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
        options = self.prompt_options(
            game, match, PromptKind.SETUP_PASS_CHOICE,
        )
        if options is None:
            return

        for distance in options.distances:
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

        if not self.may_act_for_possession(interaction, game, match):
            await interaction.response.send_message(
                "Only the player resolving this effect can choose.",
                ephemeral=True,
            )
            return

        team_emoji = get_team_emoji(
            self.cog.team_emojis,
            match.setup_for_side(match.ball.possession).team,
        )
        coach = f"{team_emoji} {interaction.user.display_name}"
        # A distance no longer on offer -- an older prompt still in the
        # channel -- is the driver's to refuse against the position.
        result = await self.apply(
            interaction,
            game,
            Action(PromptKind.SETUP_PASS_CHOICE, "", {"distance": distance}),
            carry_from=0,
        )
        if result is None:
            return
        # The strip goes with the question: it shows the ball where
        # it was before the pass, so leaving it under the answer would
        # put a stale position in the channel.
        await interaction.response.edit_message(
            content=(
                f"**{coach}** picks "
                f"out a **Setup Pass** of {distance}."
            ),
            view=None,
            attachments=[],
        )
        await self.cog.present(interaction, game, result)


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
        options = self.prompt_options(
            game, match, PromptKind.SETUP_PASS_PUSH_BACK,
        )
        if options is None:
            return

        offense_side = match.ball.possession
        # The prompt's distances: 1, 2 or 3, less any that run off
        # the end of the field (`RulesEngine.setup_pass_push_back_distances`).
        for distance in options.distances:
            zone, space_index = match.ball_destination(offense_side, -distance)
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

        if not self.may_act_for_defense(interaction, game, match):
            await interaction.response.send_message(
                "Only the coach who beat the Setup Pass can choose.",
                ephemeral=True,
            )
            return

        result = await self.apply(
            interaction,
            game,
            Action(PromptKind.SETUP_PASS_PUSH_BACK, "", {"distance": distance}),
            carry_from=0,
        )
        if result is None:
            return
        await interaction.response.edit_message(view=None)
        await self.cog.present(interaction, game, result)


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

    **The prompt carries the field strip**, for the reason the
    maneuver cards do: which distance to throw is a question about
    which teammate the pass reaches, how much field is left, and who is
    waiting where it lands -- a long pass is contested there -- and the
    persistent board has scrolled away by this point in a turn. It is
    an attachment on the prompt rather than a message of its own --
    unlike the field under the cards, which shares its message with the
    hand and would be laid out beside it -- so `choose` can strip it
    with `attachments=[]` in the edit it was already making. Leaving it
    under the answer would show the ball where it was before the pass.
    See `D12Ball.send_field_prompt`.
    """

    def __init__(self, cog: "D12Ball", game_id: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id

        game, match = self.load_match()
        options = self.prompt_options(game, match, PromptKind.HIGH_PASS_CHOICE)
        if options is None:
            return
        railed = options.railed

        for distance in options.distances:
            ability_note = cog.engine.pass_ability_note(distance)
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

        if not self.may_act_for_possession(interaction, game, match):
            await interaction.response.send_message(
                "Only the player resolving this effect can choose.",
                ephemeral=True,
            )
            return

        # A click on a menu the ball has since moved out from under,
        # and a distance the tutorial's rail does not want, are both
        # the driver's to refuse against the position.
        result = await self.apply(
            interaction,
            game,
            Action(PromptKind.HIGH_PASS_CHOICE, "", {"distance": distance}),
            carry_from=0,
        )
        if result is None:
            return
        # `attachments=[]` takes the strip with the question it
        # answered. It shows the ball where it was *before* the pass, so
        # leaving it under the answer would put a stale position in the
        # channel for the rest of the game -- the same reason the run
        # back drops its snapshot on the click.
        await interaction.response.edit_message(
            content=f"Chose **{distance} spaces**.",
            view=None,
            attachments=[],
        )
        await self.cog.present(interaction, game, result)


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
        contest_on_decline: bool = False,
    ):
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id
        self.shooter_id = shooter_id

        shooter = cog.engine.get_player_definition(shooter_id)

        attempt_button = discord.ui.Button(
            label=f"{player_with_role(shooter)} takes the shot"[:80],
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
            # the script on a pass and no goal -- the prompt's options
            # say so (`railed`), and the driver refuses off the same.
            disabled=self._decline_railed(),
        )
        decline_button.callback = self.decline
        self.add_item(decline_button)

    def _decline_railed(self) -> bool:
        """Whether the tutorial has railed this offer to the shot."""
        game, match = self.load_match()
        options = self.prompt_options(game, match, PromptKind.SET_UP_ATTEMPT)
        return options is not None and options.railed == "take"

    async def attempt(self, interaction: discord.Interaction) -> None:
        game, match = await self.require_match(interaction)
        if game is None:
            return

        if not self.may_act_for_possession(interaction, game, match):
            await interaction.response.send_message(
                "Only the player resolving this effect can choose.",
                ephemeral=True,
            )
            return

        # The shooter and the offer's two numbers are the prompt's,
        # read back off the match by the driver (see
        # `MatchState.pending_scoring_opportunity`), not this view's.
        result = await self.apply(
            interaction, game, Action(PromptKind.SET_UP_ATTEMPT, "take"),
            carry_from=0,
        )
        if result is None:
            return
        shooter = self.cog.engine.get_player_definition(self.shooter_id)
        await interaction.response.edit_message(
            content=(
                f"{self.cog.player_label(match, shooter)} "
                "takes the shot."
            ),
            view=None,
        )
        # The step's own line goes above the composition, as it did.
        await self.cog.present(interaction, game, result)

    async def decline(self, interaction: discord.Interaction) -> None:
        game, match = await self.require_match(interaction)
        if game is None:
            return

        if not self.may_act_for_possession(interaction, game, match):
            await interaction.response.send_message(
                "Only the player resolving this effect can choose.",
                ephemeral=True,
            )
            return

        result = await self.apply(
            interaction, game, Action(PromptKind.SET_UP_ATTEMPT, "decline"),
            carry_from=0,
        )
        if result is None:
            return
        await interaction.response.edit_message(
            content="Declined the scoring opportunity.",
            view=None,
        )
        await self.cog.present(interaction, game, result)


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
        game, match = self.load_match()
        options = self.prompt_options(
            game, match, PromptKind.DRIBBLE_ADVANCE_CHOICE,
        )
        distances = options.distances if options is not None else (1, 2)
        railed = options.railed if options is not None else None

        for distance in distances:
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

        if not self.may_act_for_possession(interaction, game, match):
            await interaction.response.send_message(
                "Only the player resolving this effect can choose.",
                ephemeral=True,
            )
            return

        result = await self.apply(
            interaction,
            game,
            Action(PromptKind.DRIBBLE_ADVANCE_CHOICE, "", {"distance": distance}),
            carry_from=0,
        )
        if result is None:
            return
        space_word = "space" if distance == 1 else "spaces"
        await interaction.response.edit_message(
            content=f"Chose **{distance} {space_word}**.",
            view=None,
            # The strip goes with the question: it shows the handler
            # where they were *before* the dribble, so leaving it under
            # the answer would put a stale position in the channel --
            # see D12Ball.send_field_prompt.
            attachments=[],
        )
        await self.cog.present(interaction, game, result)


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
        options = self.prompt_options(
            game, match, PromptKind.DRIBBLE_BURST_CHOICE,
        )
        if options is None or match.active_player_id is None:
            # No handler means no run to price. Only reachable in the
            # same narrow crash window every other reconstructed view
            # has; the empty view falls back to PlayerActionView.
            return

        for distance in options.distances:
            space_word = "space" if distance == 1 else "spaces"
            # The destination and the price are the engine's: where a
            # run lands and what a Playmaker saves are rules.
            button = discord.ui.Button(
                label=(
                    f"{distance} {space_word} "
                    f"({cog.engine.dribble_burst_note(match, distance)})"
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

        if not self.may_act_for_possession(interaction, game, match):
            await interaction.response.send_message(
                "Only the player resolving this effect can choose.",
                ephemeral=True,
            )
            return

        result = await self.apply(
            interaction,
            game,
            Action(PromptKind.DRIBBLE_BURST_CHOICE, "", {"distance": distance}),
            carry_from=0,
        )
        if result is None:
            return
        space_word = "space" if distance == 1 else "spaces"
        await interaction.response.edit_message(
            content=f"Chose **{distance} {space_word}**.",
            view=None,
            # It shows the position the run was priced against, which
            # the run has just moved -- see DribbleAdvanceChoiceView.
            attachments=[],
        )
        await self.cog.present(interaction, game, result)


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
    ):
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id
        self.player_id = player_id

        game, match = self.load_match()

        options = self.prompt_options(
            game, match, PromptKind.SPEED_DELTA_CHOICE,
        )
        if options is None:
            return
        current = match.ball.speed
        # The prompt's targets (`RulesEngine.speed_targets`), and the
        # one the tutorial rails to -- "take the highest offered",
        # since the cap is the stealer's own defensive skill and the
        # script cannot name a number.
        railed = options.railed

        for target in options.targets:
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
        if not self.may_act_for(interaction, controller_id):
            await interaction.response.send_message(
                "Only the player resolving this effect can choose.",
                ephemeral=True,
            )
            return

        # Whether a turnover happened is the driver's reading off the
        # position (`_answer_speed_delta_choice`), not this view's.
        result = await self.apply(
            interaction,
            game,
            Action(
                PromptKind.SPEED_DELTA_CHOICE, "", {"target_speed": target_speed},
            ),
        )
        if result is None:
            return

        # No separate "chose speed N" confirmation -- the step's own
        # "Ball speed is now N" message says the same thing, so just
        # drop the buttons and let that be the one message. Its own
        # message: the new speed is the answer to the question this
        # click was, and what follows it is the next event.
        await interaction.response.edit_message(view=None)
        lines = " ".join(result.answer)
        if lines:
            await send_new_prompt(interaction, lines)
        await self.cog.present(interaction, game, result)


class TutorialContinueView(SafeView):
    """
    A single "Continue" button gating whatever comes next in a run of
    tutorial narration -- see `d12ball/flow/gates.py`. Two or more
    plain-text messages posted back to back with no click between them
    are exactly what gets scrolled past in Discord, so a note that has
    something following it is held here until the coach presses on,
    rather than dumped alongside the rest of the burst.

    **Restart-safe since Phase 6**: the gate is `PromptKind.TUTORIAL_CONTINUE`,
    read off `D12BallGame.tutorial_gate`, so the view is built from
    the cog and the game id alone and a restart re-arms it like any
    other prompt. What the click runs is the gate's to say.
    """

    def __init__(self, cog: "D12Ball", game_id: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id

        button = discord.ui.Button(
            label="Continue",
            style=discord.ButtonStyle.primary,
            custom_id=f"d12ball:tutorial_continue:{game_id}",
        )
        button.callback = self._continue
        self.add_item(button)

    async def _continue(self, interaction: discord.Interaction) -> None:
        game, match = await self.require_match(interaction)
        if game is None or not self.may_act_in_game(interaction, game):
            await self.refuse(
                interaction, "Only a coach in this game can continue.",
            )
            return

        result = await self.apply(
            interaction, game, Action(PromptKind.TUTORIAL_CONTINUE),
        )
        if result is None:
            return

        await interaction.response.edit_message(view=None)
        await self.cog.present(interaction, game, result)


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
            button = discord.ui.Button(
                label=player_with_role(player)[:80],
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

        if not self.may_act_for_possession(interaction, game, match):
            await interaction.response.send_message(
                "Only the player resolving this effect can choose.",
                ephemeral=True,
            )
            return

        result = await self.apply(
            interaction,
            game,
            Action(PromptKind.SHOOTER_CHOICE, "", {"shooter_id": shooter_id}),
            carry_from=0,
        )
        if result is None:
            return
        shooter = self.cog.engine.get_player_definition(shooter_id)
        await interaction.response.edit_message(
            content=(
                f"{self.cog.player_label(match, shooter)} "
                "takes the shot."
            ),
            view=None,
        )
        await self.cog.present(interaction, game, result)


class SmoothView(SafeView):
    """
    Whether a Telekinetic their **own** side's ball has just moved to
    or through takes it over -- Mind Pull's other half, and the same
    interrupt with the price taken off. See "Mind Pull (Telekinetic)"
    in docs/living-rules.md.

    **One button, not two.** A pull is a decision worth two (the token
    is spent whether or not it lands, so "Let it go" is declining a
    cost); a Smooth costs nothing and cannot fail, so the only reason
    to decline is not wanting the ball on that space. That is still a
    real choice -- it moves who takes the next turn, and it stops the
    ball short of where the pass was going -- so it is still asked,
    and "Leave it" is the decline.

    **Only that player's own coach may answer.** The same rule the
    pull has, for a simpler reason: it is their player and their turn
    it changes.

    The player is in both custom_ids as well as in
    `match.pending_smooth`, so a coach who scrolls back to an earlier
    offer in the same turn cannot answer it for somebody else. A
    restart while one of these is up leaves the queue on the match,
    which `pending_turn_view` puts back.
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
        take = discord.ui.Button(
            label=f"{player_with_role(player)} takes it over"[:80],
            style=discord.ButtonStyle.primary,
            custom_id=f"d12ball:smooth:{game_id}:{player_id}",
        )
        take.callback = self.take
        self.add_item(take)

        leave = discord.ui.Button(
            label="Leave it",
            style=discord.ButtonStyle.secondary,
            custom_id=f"d12ball:smooth_decline:{game_id}:{player_id}",
        )
        leave.callback = self.decline
        self.add_item(leave)

    async def claim(self, interaction: discord.Interaction):
        """
        The game and match if this click may answer this offer, or
        `(None, None)` after replying with why it may not -- the twin
        of `MindPullView.claim`, reading its own queue.
        """
        game, match = await self.require_match(interaction)
        if game is None:
            return None, None

        if not self.may_act_for(
            interaction,
            self.cog.engine.controlling_user_id(game, match, self.player_id),
        ):
            await interaction.response.send_message(
                "Only the coach whose player that is can answer this.",
                ephemeral=True,
            )
            return None, None
        return game, match

    async def take(self, interaction: discord.Interaction) -> None:
        game, match = await self.claim(interaction)
        if game is None:
            return

        # An offer already answered is a stale click the driver refuses
        # by kind; the player asked is the prompt's, and this view's
        # goes with the action so a click on an earlier offer in the
        # same turn cannot answer for somebody else.
        result = await self.apply(
            interaction,
            game,
            Action(PromptKind.SMOOTH, "take", {"player_id": self.player_id}),
            carry_from=0,
        )
        if result is None:
            return
        # Taking the ball over ends the maneuver and everything that
        # follows it, so the buttons go first.
        await interaction.response.edit_message(view=None)
        await self.cog.present(interaction, game, result)

    async def decline(self, interaction: discord.Interaction) -> None:
        game, match = await self.claim(interaction)
        if game is None:
            return

        # **The rule is `d12ball.flow.arrivals.decline_smooth_step`**
        # since Phase 6: popping the queue and wording the line are
        # both the model's. What is left is that the decline
        # *replaces* the offer it answers -- an edit rather than a
        # message of its own -- so the step's first block is this
        # message and the rest is whatever the queue had to say next.
        result = await self.apply(
            interaction,
            game,
            Action(PromptKind.SMOOTH, "decline", {"player_id": self.player_id}),
            carry_from=1,
        )
        if result is None:
            return

        await interaction.response.edit_message(
            content=result.answer[0], view=None,
        )
        await self.cog.present(interaction, game, result)


class MindPullView(SafeView):
    """
    Whether a Telekinetic the ball has just crossed reaches out for it
    -- Smooth's opposite number, and half of the one ability that
    interrupts a maneuver rather than modifying it. See "Mind Pull
    (Telekinetic)" in docs/living-rules.md.

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
            label=f"{player_with_role(player)} reaches for it"[:80],
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

        if not self.may_act_for(
            interaction,
            self.cog.engine.controlling_user_id(game, match, self.player_id),
        ):
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

        # **The rule is `d12ball.flow.arrivals.attempt_mind_pull_step`**:
        # the token, the roll, whether it landed and what a landed pull
        # does to possession. The queue is the whole of "is this offer
        # still live", and the driver reads it.
        result = await self.apply(
            interaction,
            game,
            Action(PromptKind.MIND_PULL, "take", {"player_id": self.player_id}),
            carry_from=lambda answered: (
                1 if answered.detail is not None and not answered.detail.pulled
                else 0
            ),
        )
        if result is None:
            return
        # The buttons go before the die is drawn: what follows can be
        # a whole turnover, and the three-second window is not enough
        # for it.
        await interaction.response.edit_message(view=None)
        await self.cog.post_mind_pull_die(interaction, game, match, result)

    async def decline(self, interaction: discord.Interaction) -> None:
        game, match = await self.claim(interaction)
        if game is None:
            return

        # **The rule is
        # `d12ball.flow.arrivals.decline_mind_pull_step`** since Phase
        # 6, the same as Smooth's decline: popping the queue and
        # wording the line are the model's. Nothing is charged for
        # letting it go -- the token is the price of *trying* -- so
        # what is left here is that the answer replaces the offer.
        result = await self.apply(
            interaction,
            game,
            Action(PromptKind.MIND_PULL, "decline", {"player_id": self.player_id}),
            carry_from=1,
        )
        if result is None:
            return

        await interaction.response.edit_message(
            content=result.answer[0], view=None,
        )
        await self.cog.present(interaction, game, result)

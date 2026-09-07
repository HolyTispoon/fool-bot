"""
Where a displaced player runs back to, and which of a stack goes --
the two questions `next_run_back_step` answers, sharing one message.
"""

import discord
from typing import TYPE_CHECKING

from d12ball.components import TeamSide
from cogs.d12ball_helpers import (
    add_full_image_button,
    build_full_image_button,
    space_label,
    travel_space_label,
)

from cogs.d12ball_views.base import SafeView

if TYPE_CHECKING:
    from cogs.d12ball import D12Ball


class RunBackPlayerChoiceView(SafeView):
    """
    Which of two teammates sharing a space runs back out of it -- the
    author's call, 2026-08-17; see "Running back after a steal" in
    docs/living-rules.md. The pair only differ in who they are, so the
    code has no business preferring one, and it used to keep whichever
    the space's occupant list started with.

    **It is only ever built where the choice is real.** A stack the
    ball's holder is standing in has one player to spare and no
    question to ask, and `next_run_back_step` hands that straight to
    the space prompt below.

    The answer is an edit of this same message rather than a new one:
    the board was uploaded for the "who" and is just as much the
    picture the "where" is read off, so re-posting would pay for the
    same render twice. That means carrying the full-image link across
    by hand -- editing a view replaces it wholesale, so the link has to
    be rebuilt onto the new one from the attachment already there (see
    add_full_image_button).
    """

    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
        candidates: list[str],
    ):
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id
        self.candidates = list(candidates)

        game = cog.games.get(game_id)
        match = (
            cog.engine.load_match_state(game)
            if game is not None and game.match_state is not None
            else None
        )

        for player_id in self.candidates:
            player = cog.engine.get_player_definition(player_id)
            position = (
                match.board.meeple_position(player_id)
                if match is not None
                else None
            )
            button = discord.ui.Button(
                # The space is on the label because a stack can span
                # more than one of them: two pairs in a three-space
                # zone with one space free is four candidates, and
                # which pair they come from is the whole difference.
                label=(
                    f"{player.name} — {space_label(*position)}"
                    if position is not None
                    else player.name
                ),
                style=discord.ButtonStyle.primary,
                custom_id=(
                    f"d12ball:run_back_who:{game_id}:{player_id}"
                ),
            )

            async def callback(
                interaction: discord.Interaction,
                chosen_player: str = player_id,
            ) -> None:
                await self.choose(interaction, chosen_player)

            button.callback = callback
            self.add_item(button)

    async def choose(
        self,
        interaction: discord.Interaction,
        player_id: str,
    ) -> None:
        game, match = await self.require_match(interaction)
        if game is None:
            return

        controller_id = self.cog.engine.controlling_user_id(game, match, player_id)
        if interaction.user.id != controller_id:
            await interaction.response.send_message(
                "Only that team's coach can choose this.",
                ephemeral=True,
            )
            return

        side = (
            TeamSide.HOME
            if player_id in match.home.field_players
            else TeamSide.VISITING
        )
        # Nothing is written until the space is picked, so a click on a
        # prompt the board has moved out from under is caught by asking
        # the position again rather than by a saved flag.
        if player_id not in self.cog.engine.run_back_crowded(match, side):
            await interaction.response.send_message(
                "They no longer have to run back.", ephemeral=True,
            )
            return

        space_view = RunBackChoiceView(self.cog, self.game_id, player_id)
        link = build_full_image_button(interaction.message)
        if link is not None:
            space_view.add_item(link)

        await interaction.response.edit_message(
            content=self.cog.run_back_space_prompt(
                match, side, player_id, f"<@{controller_id}>",
            ),
            view=space_view,
        )


class RunBackChoiceView(SafeView):
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
        if game is None:
            return
        side = (
            TeamSide.HOME
            if player_id in match.home.field_players
            else TeamSide.VISITING
        )
        zone = match.setup_for_side(side).assigned_zone(player_id)

        for space_index in match.placement_spaces_in_zone(
            side, zone, player_id,
        ):
            button = discord.ui.Button(
                # The distance is on the label because it is the price:
                # a run back costs a token a space, so the two spaces of
                # a zone are rarely the same offer. See
                # travel_space_label.
                label=travel_space_label(
                    zone,
                    space_index,
                    match.run_back_distance(player_id, zone, space_index),
                ),
                style=discord.ButtonStyle.primary,
                custom_id=(
                    f"d12ball:run_back:{game_id}:{player_id}:{space_index}"
                ),
            )

            async def callback(
                interaction: discord.Interaction,
                chosen_space: int = space_index,
            ) -> None:
                await self.choose(interaction, chosen_space)

            button.callback = callback
            self.add_item(button)

    async def choose(
        self,
        interaction: discord.Interaction,
        space_index: int,
    ) -> None:
        game, match = await self.require_match(interaction)
        if game is None:
            return

        controller_id = self.cog.engine.controlling_user_id(
            game, match, self.player_id,
        )
        if interaction.user.id != controller_id:
            await interaction.response.send_message(
                "Only that team's coach can choose this.",
                ephemeral=True,
            )
            return

        side = (
            TeamSide.HOME
            if self.player_id in match.home.field_players
            else TeamSide.VISITING
        )
        zone = match.setup_for_side(side).assigned_zone(self.player_id)

        try:
            distance = match.run_back_player(
                self.player_id, zone, space_index,
            )
        except ValueError as error:
            await interaction.response.send_message(
                str(error), ephemeral=True,
            )
            return

        exhaustion_text = self.cog.apply_exhaustion(
            game, match, self.player_id, distance,
        )
        self.cog.persist(game, match)

        player = self.cog.engine.get_player_definition(self.player_id)
        await interaction.response.edit_message(
            content=(
                f"{self.cog.player_label(match, player)} "
                f"runs back to {space_label(zone, space_index)}."
                f"\n{exhaustion_text}"
            ),
            view=None,
            # The board this prompt was asked over shows the player
            # still displaced, so it goes with the question rather than
            # standing under the answer. The refresh below puts the
            # board they moved to on the persistent message.
            attachments=[],
        )
        await self.cog.refresh_match_image(interaction, game)
        await self.cog.continue_run_back(interaction, game, match)

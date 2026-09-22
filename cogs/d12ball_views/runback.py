"""
Where a displaced player runs back to, and which of a stack goes --
the two questions `next_run_back_step` answers, sharing one message.
"""

import discord
from typing import TYPE_CHECKING

from d12ball.flow.driver import Action
from d12ball.prompts import PromptKind
from cogs.d12ball_helpers import (
    build_full_image_button,
    player_with_role,
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
            # The role is on the label because every label naming a
            # card in this game carries it -- this was the one that did
            # not. The space is there because a stack can span more
            # than one of them: two pairs in a three-space zone with
            # one space free is four candidates, and which pair they
            # come from is the whole difference.
            name = player_with_role(player)
            button = discord.ui.Button(
                label=(
                    f"{name} — {space_label(*position)}"
                    if position is not None
                    else name
                )[:80],
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
        if not self.may_act_for(interaction, controller_id):
            await interaction.response.send_message(
                "Only that team's coach can choose this.",
                ephemeral=True,
            )
            return

        # **The question is the model's**, and asking it is this
        # view's: `run_back_player_step` narrows the run back's first
        # question into its second and words it, and the strip the
        # question is asked over is re-linked here because the picture
        # is the frontend's (principle 8 in CLAUDE.md). A click on a
        # prompt the board has moved out from under is the driver's to
        # refuse, and the pick it records is written down:
        # `MatchState.run_back_pick` is what lets the space step that
        # follows be checked against the position.
        result = await self.apply(
            interaction,
            game,
            Action(PromptKind.RUN_BACK_PLAYER, "", {"player_id": player_id}),
        )
        if result is None:
            return
        prompt = result.prompt

        space_view = self.cog.view_for_prompt(self.game_id, result.match, prompt)
        link = build_full_image_button(interaction.message)
        if link is not None:
            space_view.add_item(link)

        await interaction.response.edit_message(
            content=prompt.ask,
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
        options = self.prompt_options(game, match, PromptKind.RUN_BACK_SPACE)
        if options is None:
            return

        for space_index, distance in zip(options.space_indices, options.distances):
            button = discord.ui.Button(
                # The distance is on the label because it is the price:
                # a run back costs a token a space, so the two spaces of
                # a zone are rarely the same offer. Both are the
                # prompt's (`SpaceOptions`). See travel_space_label.
                label=travel_space_label(options.zone, space_index, distance),

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
        if not self.may_act_for(interaction, controller_id):
            await interaction.response.send_message(
                "Only that team's coach can choose this.",
                ephemeral=True,
            )
            return

        # Who is running is the prompt's; this view's player goes with
        # the action so a prompt for an earlier player, still in the
        # channel, cannot move this one. A space they may not take is
        # `MatchState.run_back_player`'s refusal, through the driver.
        result = await self.apply(
            interaction,
            game,
            Action(
                PromptKind.RUN_BACK_SPACE,
                "",
                {"player_id": self.player_id, "space_index": space_index},
            ),
        )
        if result is None:
            return

        await interaction.response.edit_message(
            content=" ".join(result.answer),
            view=None,
            # The board this prompt was asked over shows the player
            # still displaced, so it goes with the question rather than
            # standing under the answer. The presenter puts the board
            # they moved to on the persistent message.
            attachments=[],
        )
        await self.cog.present(interaction, game, result)

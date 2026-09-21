"""
Halftime's own two prompts, over the coaching flow.
"""

import discord
from typing import Optional, TYPE_CHECKING

from d12ball.components import (
    MatchState,
    TeamSide,
)
from d12ball.flow.periods import halftime_extra_token_step
from d12ball.game import D12BallGame

from cogs.d12ball_views.base import SafeView

if TYPE_CHECKING:
    from cogs.d12ball import D12Ball


class HalftimeView(SafeView):
    """
    Shared plumbing for the halftime flow's per-side prompts: they
    only accept a click from the side currently on the clock, at
    the stage that offered them -- see D12Ball.advance_halftime_stage.
    """

    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
        side: TeamSide,
        stage: str,
    ):
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id
        self.side = side
        self.stage = stage

    def load(self) -> tuple[Optional[D12BallGame], Optional[MatchState]]:
        return self.load_match()

    async def claim(
        self,
        interaction: discord.Interaction,
    ) -> tuple[Optional[D12BallGame], Optional[MatchState]]:
        game, match = self.load()
        if game is None or match is None:
            await interaction.response.send_message(
                "I could not find the saved data for this game.",
                ephemeral=True,
            )
            return None, None
        if match.pending_halftime_stage != self.stage:
            await interaction.response.send_message(
                "That halftime step has already finished.",
                ephemeral=True,
            )
            return None, None
        if not self.may_act_for(
            interaction, self.cog.engine.side_controller_id(game, self.side),
        ):
            await interaction.response.send_message(
                "Only that team's coach can choose this.",
                ephemeral=True,
            )
            return None, None
        return game, match


class HalftimeExtraTokenView(HalftimeView):
    """
    Halftime: each side picks one of their own fielded players to lose
    an extra exhaustion token, on top of the automatic recovery every
    fielded player already got in begin_halftime.
    """

    def __init__(self, cog: "D12Ball", game_id: str, side: TeamSide):
        super().__init__(cog, game_id, side, f"extra_token_{side.value}")

        game, match = self.load()
        if match is None or match.pending_halftime_stage != self.stage:
            return
        setup = match.setup_for_side(side)

        for player_id in setup.field_players:
            if player_id in match.injured:
                continue
            tokens = match.exhaustion.get(player_id, 0)
            label = f"{cog.engine.format_roster_player(player_id)} ({tokens})"
            button = discord.ui.Button(
                label=label[:80],
                style=discord.ButtonStyle.secondary,
                custom_id=(
                    f"d12ball:halftime_extra_token:{game_id}:{player_id}"
                ),
            )

            async def callback(
                interaction: discord.Interaction,
                picked: str = player_id,
            ) -> None:
                await self.choose(interaction, picked)

            button.callback = callback
            self.add_item(button)

    async def choose(
        self,
        interaction: discord.Interaction,
        player_id: str,
    ) -> None:
        game, match = await self.claim(interaction)
        if game is None or match is None:
            return

        # **The rule is
        # `d12ball.flow.periods.halftime_extra_token_step`** since
        # Phase 6 -- taking the token off, moving the stage on and
        # saying what happened. The AI's branch of
        # `begin_halftime_extra_token` is the same three lines, which
        # is why this is a step and not a view body.
        result = halftime_extra_token_step(
            self.cog.engine, game, match, player_id=player_id,
        )
        self.cog.persist(game, match)

        await interaction.response.edit_message(
            content=result.narration[0], view=None,
        )
        await self.cog.refresh_match_image(interaction, game)
        await self.cog.advance_halftime_stage(interaction, game, match)

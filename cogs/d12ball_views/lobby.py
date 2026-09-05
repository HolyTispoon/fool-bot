"""
The game-creation hub and the pre-game lobby.

`NewGameHubView` is the one button on the locked hub channel's single
message; clicking it asks the cog to open a lobby. `LobbyView` is the
lobby channel's message -- Join / Leave / Test game / Start Game plus
the mode, board-size and opponent settings -- and hands each click back
to the cog so the game-record and channel-permission changes live next
to `open_new_game`.

Imports from `base` only, which is what keeps `cogs/d12ball_views` a DAG
(see `tests/test_d12ball_package_shape.py`). It binds `save_games`
directly, like `setup.py`, so it is listed in `SAVING_VIEW_MODULES` in
`tests/save_patches.py`.
"""

import discord
from typing import TYPE_CHECKING

from d12ball.game import AIOpponent, GameMode
from gamesaves.d12ball.storage import save_games
from cogs.d12ball_helpers import (
    AI_OPPONENT_NAMES,
    build_lobby_message,
)

from cogs.d12ball_views.base import SafeView

if TYPE_CHECKING:
    from cogs.d12ball import D12Ball


class NewGameHubView(SafeView):
    """
    The persistent view on the hub channel's message. One button today
    -- "D12 Ball" -- with room for more (a role picker is a planned
    follow-up), so its custom_id names no game and no guild: the
    interaction carries the guild, and a lobby does not exist yet.
    """

    def __init__(self, cog: "D12Ball"):
        super().__init__(timeout=None)
        self.cog = cog

        button = discord.ui.Button(
            label="D12 Ball",
            emoji="🏈",
            style=discord.ButtonStyle.primary,
            custom_id="d12ball:hub:new_game",
        )
        button.callback = self.open_lobby
        self.add_item(button)

    async def open_lobby(self, interaction: discord.Interaction) -> None:
        await self.cog.open_lobby(interaction)


class LobbyView(SafeView):
    """
    The lobby channel's message, rebuilt fresh on every interaction the
    way every other setup view is. Join / Leave / Test game / Start Game
    on the top row, then the settings: mode, board size, and -- only
    while Player 2 is still open and it is not a test game -- the AI
    opponent.
    """

    def __init__(self, cog: "D12Ball", game_id: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id

        game = self.cog.games.get(game_id)
        started = game is None or not game.in_lobby
        test_game = bool(game and game.test_game)
        has_opponent = bool(game and game.player_2_id is not None)

        self._add_button(
            "Join", discord.ButtonStyle.success, "join",
            row=0, disabled=started or test_game,
        )
        self._add_button(
            "Leave", discord.ButtonStyle.secondary, "leave",
            row=0, disabled=started,
        )
        self._add_button(
            "Test game: on" if test_game else "Test game: off",
            (
                discord.ButtonStyle.success
                if test_game
                else discord.ButtonStyle.secondary
            ),
            "test",
            row=0,
            # Can't switch to one-person-both-sides once someone else
            # has joined the lobby.
            disabled=started or has_opponent,
        )
        self._add_button(
            "Start Game", discord.ButtonStyle.primary, "start",
            row=0, disabled=started,
        )

        selected_mode = game.mode if game else GameMode.BASIC
        for label, mode in (
            ("Basic", GameMode.BASIC),
            ("Advanced", GameMode.ADVANCED),
        ):
            self._add_button(
                label,
                (
                    discord.ButtonStyle.secondary
                    if mode == selected_mode
                    else discord.ButtonStyle.primary
                ),
                f"mode:{mode.value}",
                row=1,
                disabled=started or mode == selected_mode,
            )

        selected_board = game.board_size if game else 7
        for board_size in (6, 7, 9):
            self._add_button(
                str(board_size),
                (
                    discord.ButtonStyle.secondary
                    if board_size == selected_board
                    else discord.ButtonStyle.primary
                ),
                f"board:{board_size}",
                row=2,
                disabled=started or board_size == selected_board,
            )

        # The opponent row is only meaningful while nobody has joined and
        # it is not a test game -- a second human, or one person taking
        # both sides, settles who the opponent is. Decent AI is offered
        # and refused in its callback, matching CoinFlipView's settings.
        if game is not None and game.player_2_id is None and not test_game:
            selected_ai = game.ai_opponent or AIOpponent.DINKY
            for ai_type, label in AI_OPPONENT_NAMES.items():
                self._add_button(
                    label,
                    (
                        discord.ButtonStyle.secondary
                        if ai_type == selected_ai
                        else discord.ButtonStyle.primary
                    ),
                    f"ai:{ai_type.value}",
                    row=3,
                    disabled=started or ai_type == selected_ai,
                )

    def _add_button(
        self,
        label: str,
        style: discord.ButtonStyle,
        action: str,
        row: int,
        disabled: bool = False,
    ) -> None:
        button = discord.ui.Button(
            label=label,
            style=style,
            custom_id=f"d12ball:lobby:{action}:{self.game_id}",
            row=row,
            disabled=disabled,
        )

        async def callback(
            interaction: discord.Interaction,
            action: str = action,
        ) -> None:
            await self.dispatch(interaction, action)

        button.callback = callback
        self.add_item(button)

    async def dispatch(
        self,
        interaction: discord.Interaction,
        action: str,
    ) -> None:
        game = self.cog.games.get(self.game_id)
        if game is None or not game.in_lobby:
            await interaction.response.send_message(
                "This lobby is no longer open.",
                ephemeral=True,
            )
            return

        if action == "join":
            await self.cog.lobby_join(interaction, game)
            return
        if action == "leave":
            await self.cog.lobby_leave(interaction, game)
            return
        if action == "start":
            await self.cog.lobby_start(interaction, game)
            return

        setting, _, value = action.partition(":")
        await self.change_setting(interaction, game, setting, value)

    async def change_setting(
        self,
        interaction: discord.Interaction,
        game,
        setting: str,
        value: str,
    ) -> None:
        participant_ids = {game.player_1_id}
        if game.player_2_id is not None:
            participant_ids.add(game.player_2_id)
        if interaction.user.id not in participant_ids:
            await interaction.response.send_message(
                "Only a player in this lobby can change its settings.",
                ephemeral=True,
            )
            return

        if setting == "test":
            if game.player_2_id is not None:
                await interaction.response.send_message(
                    "Someone has already joined -- they would have to "
                    "leave before this can become a test game.",
                    ephemeral=True,
                )
                return
            game.test_game = not game.test_game
        elif setting == "mode":
            game.mode = GameMode(value)
            # Advanced mode's extra maneuvers want the room a 9-space
            # board gives them -- default to it, the coach may still pick
            # 6 or 7. Same choice CoinFlipView's settings make.
            if game.mode == GameMode.ADVANCED:
                game.board_size = 9
        elif setting == "board":
            game.board_size = int(value)
        elif setting == "ai":
            ai_type = AIOpponent(value)
            if ai_type == AIOpponent.DECENT:
                await interaction.response.send_message(
                    "Decent AI is not ready yet -- play against Dinky AI.",
                    ephemeral=True,
                )
                return
            game.ai_opponent = ai_type
        else:
            await interaction.response.send_message(
                "I did not understand that button.",
                ephemeral=True,
            )
            return

        save_games(self.cog.games)
        await interaction.response.edit_message(
            content=build_lobby_message(game),
            view=LobbyView(self.cog, self.game_id),
        )

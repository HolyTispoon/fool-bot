"""
The game-creation hub and the pre-game lobby.

`NewGameHubView` is the one button on the locked hub channel's games
message; clicking it asks the cog to open a lobby. `HubRolesView` is
the toggle button per role on the hub's second message, built off
`HUB_ROLES`. `LobbyView` is the
lobby channel's message -- Join / Observe / Leave / Start Game, the Test
game and Tutorial toggles, a Name button (opening `LobbyNameModal`), and
the mode (with its two module toggles), board-size and opponent
settings -- and hands Join, Observe, Leave and Start back to the cog,
where the channel-permission changes live next to `open_lobby`. A
setting changed here goes through `GameService.configure`: the record
rules on it (`D12BallGame.configure`), the service saves, the view
redraws. Nothing in this module saves.

Imports from `base` only, which is what keeps `cogs/d12ball_views` a DAG
(see `tests/test_d12ball_package_shape.py`).
"""

import discord
from typing import TYPE_CHECKING

from d12ball.components import RuleRefusal
from d12ball.game import (
    ADVANCED_MODULES,
    AIOpponent,
    GameMode,
    VALID_BOARD_SIZES,
)
from cogs.d12ball_helpers import (
    AI_OPPONENT_NAMES,
    HUB_ROLE_CUSTOM_ID_PREFIX,
    HUB_ROLES,
    advanced_module_label,
    build_lobby_message,
    may_act_in_game,
)

from cogs.d12ball_views.base import SafeView

if TYPE_CHECKING:
    from cogs.d12ball import D12Ball


def hub_button_emoji(cog: "D12Ball"):
    """
    The d12 for a hub button: the lighter `d12dicecream` cut, or nothing
    -- never the plain `d12dice`, which a button's coloured fill
    swallows (see `load_d12_button_emoji`). Loaded in `cog_load`,
    refreshed by `/d12ball setup_hub`. The rendered message keeps
    whatever emoji it was last posted/edited with, so a restart before
    `cog_load` does not blank it.
    """
    return getattr(cog, "d12_button_emoji", None) or None


class NewGameHubView(SafeView):
    """
    The persistent view on the hub channel's games message. One button
    today -- "D12 Ball" -- with room for more games, so its custom_id
    names no game and no guild: the interaction carries the guild, and
    a lobby does not exist yet. The roles live on a message of their own
    (`HubRolesView`), so a game added here never reflows the roles.
    """

    def __init__(self, cog: "D12Ball"):
        super().__init__(timeout=None)
        self.cog = cog

        button = discord.ui.Button(
            label="D12 Ball",
            emoji=hub_button_emoji(cog),
            style=discord.ButtonStyle.success,
            custom_id="d12ball:hub:new_game",
        )
        button.callback = self.open_lobby
        self.add_item(button)

    async def open_lobby(self, interaction: discord.Interaction) -> None:
        await self.cog.open_lobby(interaction)


class HubRolesView(SafeView):
    """
    The persistent view on the hub channel's roles message: one toggle
    button per `HUB_ROLES` entry, each carrying its role's key in the
    custom_id and nothing else -- the interaction carries the guild and
    the member, which is everything `toggle_hub_role` needs. Built off
    the table rather than by hand so a role added there gets its button
    without this class changing.
    """

    def __init__(self, cog: "D12Ball"):
        super().__init__(timeout=None)
        self.cog = cog
        for hub_role in HUB_ROLES:
            button = discord.ui.Button(
                label=hub_role.label,
                emoji=hub_button_emoji(cog) if hub_role.d12_emoji else None,
                style=discord.ButtonStyle.success,
                custom_id=f"{HUB_ROLE_CUSTOM_ID_PREFIX}{hub_role.key}",
            )
            button.callback = self.make_toggle(hub_role.key)
            self.add_item(button)

    def make_toggle(self, key: str):
        async def toggle(interaction: discord.Interaction) -> None:
            await self.cog.toggle_hub_role(interaction, key)
        return toggle


class LobbyNameModal(discord.ui.Modal, title="Name this game"):
    """
    The one text field in the lobby -- a fun name for the game, the same
    thing `/d12ball create_game`'s `game_name` sets. It decides only what
    the channel is called once the game starts (see `lobby_start`).
    Opened fresh from the Name button each time, so it needs no
    persistence.
    """

    game_name = discord.ui.TextInput(
        label="Fun game name",
        placeholder="e.g. The Cup Final -- leave blank to name it after the players",
        required=False,
        max_length=80,
    )

    def __init__(self, cog: "D12Ball", game_id: str):
        super().__init__()
        self.cog = cog
        self.game_id = game_id
        game = cog.games.get(game_id)
        if game is not None and game.game_name:
            self.game_name.default = game.game_name

    async def on_submit(self, interaction: discord.Interaction) -> None:
        game = self.cog.games.get(self.game_id)
        if game is None or not game.in_lobby:
            await interaction.response.send_message(
                "This lobby is no longer open.", ephemeral=True,
            )
            return

        if not may_act_in_game(interaction.user, game):
            await interaction.response.send_message(
                "Only a player in this lobby can name the game.",
                ephemeral=True,
            )
            return

        try:
            self.cog.service.configure(
                self.game_id, "name", str(self.game_name.value),
            )
        except RuleRefusal as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return
        await interaction.response.edit_message(
            content=build_lobby_message(game, self.cog.d12_emoji),
            view=LobbyView(self.cog, self.game_id),
            allowed_mentions=discord.AllowedMentions.none(),
        )


class LobbyView(SafeView):
    """
    The lobby channel's message, rebuilt fresh on every interaction the
    way every other setup view is. Join / Observe / Leave / Start Game,
    then the two game-type toggles (Test game, Tutorial), then the
    settings: mode, board size, and -- only for an open solo game -- the
    AI opponent.

    Test game, Tutorial and a second human are mutually exclusive: each
    is a different answer to "who plays the other side", and a lobby
    holds exactly one. Tutorial also pins Basic mode on a 7-space board,
    which is the only shape `d12ball/tutorial.py`'s script is written
    for.

    A lobby channel is visible to the whole server, so **Observe** is
    only about what happens at kickoff: `lobby_start` locks the channel
    to the two players, and observers keep read-only access.

    A game helper's click here is **not** put behind a confirmation,
    unlike everywhere past the lobby: somebody walking a new player
    through their first game turns Tutorial on and presses Start for
    them, and asking "are you sure?" of each of those is asking about
    the thing the gate was widened for. Nothing in a lobby has been
    played yet, so nothing here is a move made for a coach.
    """

    confirms_helper_clicks = False

    def __init__(self, cog: "D12Ball", game_id: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id

        game = self.cog.games.get(game_id)
        started = game is None or not game.in_lobby
        test_game = bool(game and game.test_game)
        tutorial = bool(game and game.tutorial)
        has_opponent = bool(game and game.player_2_id is not None)
        solo = test_game or tutorial

        self._add_button(
            "Join", discord.ButtonStyle.success, "join",
            row=0, disabled=started or solo,
        )
        self._add_button(
            "Observe", discord.ButtonStyle.secondary, "observe",
            row=0, disabled=started,
        )
        self._add_button(
            "Leave", discord.ButtonStyle.secondary, "leave",
            row=0, disabled=started,
        )
        self._add_button(
            "Start Game", discord.ButtonStyle.primary, "start",
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
            row=1,
            # Not once someone else is in, and not alongside the
            # tutorial -- both answer "who takes the other side".
            disabled=started or has_opponent or tutorial,
        )
        self._add_button(
            "Tutorial: on" if tutorial else "Tutorial: off",
            (
                discord.ButtonStyle.success
                if tutorial
                else discord.ButtonStyle.secondary
            ),
            "tutorial",
            row=1,
            disabled=started or has_opponent or test_game,
        )
        self._add_button(
            "Name",
            discord.ButtonStyle.secondary,
            "name",
            row=1,
            disabled=started,
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
                row=2,
                # The tutorial is a Basic-mode script -- see the class
                # docstring.
                disabled=started or tutorial or mode == selected_mode,
            )

        # The two halves of advanced mode, on the mode row and only
        # while it is on -- the same offer the setup settings block
        # makes, out of the same table. See "Species abilities in the
        # bot"; a coach who wants neither picks Basic.
        if selected_mode == GameMode.ADVANCED:
            for module_key in ADVANCED_MODULES:
                field, _ = ADVANCED_MODULES[module_key]
                self._add_button(
                    advanced_module_label(game, module_key),
                    (
                        discord.ButtonStyle.success
                        if getattr(game, field)
                        else discord.ButtonStyle.secondary
                    ),
                    f"module:{module_key}",
                    row=2,
                    disabled=started,
                )

        selected_board = game.board_size if game else 7
        for board_size in sorted(VALID_BOARD_SIZES):
            self._add_button(
                str(board_size),
                (
                    discord.ButtonStyle.secondary
                    if board_size == selected_board
                    else discord.ButtonStyle.primary
                ),
                f"board:{board_size}",
                row=3,
                disabled=started or tutorial or board_size == selected_board,
            )

        # The opponent row is only meaningful for an open solo game -- a
        # second human, one person on both sides, or the tutorial (always
        # Dinky) all settle it. Decent AI is offered and refused in its
        # callback, matching CoinFlipView's settings.
        if (
            game is not None
            and game.player_2_id is None
            and not test_game
            and not tutorial
        ):
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
                    row=4,
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

        if action == "name":
            await interaction.response.send_modal(
                LobbyNameModal(self.cog, self.game_id)
            )
            return
        if action == "join":
            await self.cog.lobby_join(interaction, game)
            return
        if action == "observe":
            await self.cog.lobby_observe(interaction, game)
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
        # Either player, or a game helper -- see "Who may act on a
        # game" in docs/design/permissions.md. This is the gate somebody walking a new
        # player through their first game meets: turning Tutorial on for
        # a lobby they are not playing in is the whole point of it.
        if not self.may_act_in_game(interaction, game):
            await interaction.response.send_message(
                "Only a player in this lobby can change its settings.",
                ephemeral=True,
            )
            return

        # Which setting, and what may be done with it in this lobby --
        # the tutorial pinning Basic on a 7-space board, a joined lobby
        # having no Test game toggle, the last module on staying on --
        # is the record's; the view only carries the click.
        try:
            self.cog.service.configure(game.game_id, setting, value)
        except RuleRefusal as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return

        await interaction.response.edit_message(
            content=build_lobby_message(game, self.cog.d12_emoji),
            view=LobbyView(self.cog, self.game_id),
            allowed_mentions=discord.AllowedMentions.none(),
        )

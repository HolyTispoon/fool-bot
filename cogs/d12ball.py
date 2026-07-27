import random
import re
import uuid
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from d12ball.game import (
    D12BallGame,
    GameMode,
    GameStatus,
    Team,
)

from gamesaves.d12ball.storage import (
    load_games,
    save_games,
)


CHANNEL_NAME_PATTERN = re.compile(r"^d12ball-pbd(\d+)$")


def build_setup_message(game: D12BallGame) -> str:
    player_1_team = (
        game.player_1_team.value.title()
        if game.player_1_team
        else "Not selected"
    )

    player_2_team = (
        game.player_2_team.value.title()
        if game.player_2_team
        else "Not selected"
    )

    if game.player_2_id is None:
        player_2_name = "AI opponent"
    else:
        player_2_name = f"<@{game.player_2_id}>"

    text = (
        "## D12 Ball game setup\n\n"
        "### Choose your teams\n\n"
        f"**Player 1:** <@{game.player_1_id}>\n"
        f"**Team:** {player_1_team}\n\n"
        f"**Player 2:** {player_2_name}\n"
        f"**Team:** {player_2_team}\n\n"
        "### Game settings\n\n"
        f"Game Mode: {game.mode.value.title()}\n"
        f"Board size: {game.board_size}\n\n"
    )

    if game.teams_selected:
        text += (
            "Both teams have been selected.\n"
            "Click below to determine who chooses whether they are home team."
        )
    elif game.is_solo_game:
        text += (
            "Choose a team using the buttons. After you chose your team, "
            "a random team will be assigned to the AI opponent of the "
            "remaining teams."
        )
    else:
        text += "Each player should choose a team below."

    return text


class GameConfigurationView(discord.ui.View):
    def add_configuration_buttons(self) -> None:
        game = self.cog.games.get(self.game_id)
        selected_mode = game.mode if game else GameMode.BASIC
        selected_board_size = game.board_size if game else 7
        configuration_closed = bool(
            game and game.status != GameStatus.SETUP
        )

        for label, mode in (
            ("Basic", GameMode.BASIC),
            ("Advanced", GameMode.ADVANCED),
        ):
            button = discord.ui.Button(
                label=label,
                style=(
                    discord.ButtonStyle.secondary
                    if mode == selected_mode
                    else discord.ButtonStyle.primary
                ),
                custom_id=f"d12ball:mode:{self.game_id}:{mode.value}",
                disabled=configuration_closed or mode == selected_mode,
                row=1,
            )

            async def mode_callback(
                interaction: discord.Interaction,
                selected_mode: GameMode = mode,
            ) -> None:
                await self.select_mode(interaction, selected_mode)

            button.callback = mode_callback
            self.add_item(button)

        for board_size in (6, 7, 9):
            button = discord.ui.Button(
                label=str(board_size),
                style=(
                    discord.ButtonStyle.secondary
                    if board_size == selected_board_size
                    else discord.ButtonStyle.primary
                ),
                custom_id=(
                    f"d12ball:board_size:{self.game_id}:{board_size}"
                ),
                disabled=(
                    configuration_closed
                    or board_size == selected_board_size
                ),
                row=2,
            )

            async def board_size_callback(
                interaction: discord.Interaction,
                selected_board_size: int = board_size,
            ) -> None:
                await self.select_board_size(
                    interaction,
                    selected_board_size,
                )

            button.callback = board_size_callback
            self.add_item(button)

    async def validate_configuration_change(
        self,
        interaction: discord.Interaction,
    ) -> Optional[D12BallGame]:
        game = self.cog.games.get(self.game_id)

        if game is None:
            await interaction.response.send_message(
                "I could not find this game.",
                ephemeral=True,
            )
            return None

        if game.status != GameStatus.SETUP:
            await interaction.response.send_message(
                "Game settings can only be changed during setup.",
                ephemeral=True,
            )
            return None

        player_ids = {game.player_1_id}
        if game.player_2_id is not None:
            player_ids.add(game.player_2_id)

        if interaction.user.id not in player_ids:
            await interaction.response.send_message(
                "Only the players in this game can change its settings.",
                ephemeral=True,
            )
            return None

        return game

    async def select_mode(
        self,
        interaction: discord.Interaction,
        selected_mode: GameMode,
    ) -> None:
        game = await self.validate_configuration_change(interaction)
        if game is None:
            return

        if selected_mode == GameMode.ADVANCED:
            await interaction.response.send_message(
                "advanced mode is not yet ready, please play in basic mode",
                ephemeral=True,
            )
            return

        game.mode = GameMode.BASIC
        save_games(self.cog.games)

        refreshed_view = type(self)(
            cog=self.cog,
            game_id=self.game_id,
        )
        await interaction.response.edit_message(
            content=build_setup_message(game),
            view=refreshed_view,
        )

    async def select_board_size(
        self,
        interaction: discord.Interaction,
        selected_board_size: int,
    ) -> None:
        game = await self.validate_configuration_change(interaction)
        if game is None:
            return

        game.board_size = selected_board_size
        save_games(self.cog.games)

        refreshed_view = type(self)(
            cog=self.cog,
            game_id=self.game_id,
        )
        await interaction.response.edit_message(
            content=build_setup_message(game),
            view=refreshed_view,
        )


class TeamSelectionView(GameConfigurationView):
    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
    ):
        super().__init__(timeout=None)

        self.cog = cog
        self.game_id = game_id

        game = self.cog.games.get(game_id)
        selected_teams = (
            {game.player_1_team, game.player_2_team}
            if game
            else set()
        )

        teams = [
            ("Orange", Team.ORANGE, discord.ButtonStyle.primary),
            ("Teal", Team.TEAL, discord.ButtonStyle.primary),
            ("Purple", Team.PURPLE, discord.ButtonStyle.primary),
            ("Slime", Team.SLIME, discord.ButtonStyle.primary),
        ]

        for label, team, style in teams:
            button = discord.ui.Button(
                label=label,
                style=(
                    discord.ButtonStyle.secondary
                    if team in selected_teams
                    else style
                ),
                custom_id=f"d12ball:team:{game_id}:{team.value}",
                disabled=team in selected_teams,
            )

            async def callback(
                interaction: discord.Interaction,
                selected_team: Team = team,
            ) -> None:
                await self.select_team(
                    interaction,
                    selected_team,
                )

            button.callback = callback
            self.add_item(button)

        self.add_configuration_buttons()

    async def select_team(
        self,
        interaction: discord.Interaction,
        selected_team: Team,
    ) -> None:
        game = self.cog.games.get(self.game_id)

        if game is None:
            await interaction.response.send_message(
                "I could not find this game.",
                ephemeral=True,
            )
            return

        if game.status != GameStatus.SETUP:
            await interaction.response.send_message(
                "Team selection is already closed.",
                ephemeral=True,
            )
            return

        is_player_1 = interaction.user.id == game.player_1_id
        is_player_2 = (
            game.player_2_id is not None
            and interaction.user.id == game.player_2_id
        )

        if not is_player_1 and not is_player_2:
            await interaction.response.send_message(
                "Only the players in this game can choose teams.",
                ephemeral=True,
            )
            return

        if is_player_1:
            if game.player_2_team == selected_team:
                await interaction.response.send_message(
                    "Player 2 has already selected that team.",
                    ephemeral=True,
                )
                return

            game.player_1_team = selected_team
            if game.player_2_id is None:
                available_ai_teams = [
                    team
                    for team in Team
                    if team != selected_team
                ]

                game.player_2_team = random.choice(
                    available_ai_teams
                )

        else:
            if game.player_1_team == selected_team:
                await interaction.response.send_message(
                    "Player 1 has already selected that team.",
                    ephemeral=True,
                )
                return

            game.player_2_team = selected_team

        save_games(self.cog.games)

        message = build_setup_message(game)

        if game.teams_selected:
            coin_view = CoinFlipView(
                cog=self.cog,
                game_id=self.game_id,
            )

            await interaction.response.edit_message(
                content=message,
                view=coin_view,
            )
        else:
            refreshed_view = TeamSelectionView(
                cog=self.cog,
                game_id=self.game_id,
            )
            await interaction.response.edit_message(
                content=message,
                view=refreshed_view,
            )

    def build_team_message(
        self,
        game: D12BallGame,
    ) -> str:
        return build_setup_message(game)


class CoinFlipView(GameConfigurationView):
    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
    ):
        super().__init__(timeout=None)

        self.cog = cog
        self.game_id = game_id

        game = self.cog.games.get(game_id)

        self.flip_button = discord.ui.Button(
            label="Flip a Coin! (this would start the game)",
            style=discord.ButtonStyle.primary,
            emoji="🪙",
            custom_id=f"d12ball:flip_coin:{game_id}",
            disabled=game.coin_flipped if game else False,
            row=3,
        )

        self.flip_button.callback = self.flip_coin
        self.add_item(self.flip_button)
        self.add_configuration_buttons()

    async def flip_coin(
        self,
        interaction: discord.Interaction,
    ) -> None:
        game = self.cog.games.get(self.game_id)

        if game is None:
            await interaction.response.send_message(
                "I could not find the saved data for this game.",
                ephemeral=True,
            )
            return

        allowed_player_ids = {game.player_1_id}

        if game.player_2_id is not None:
            allowed_player_ids.add(game.player_2_id)

        if interaction.user.id not in allowed_player_ids:
            await interaction.response.send_message(
                "Only a player in this game can flip the coin.",
                ephemeral=True,
            )
            return

        if game.coin_flipped:
            self.flip_button.disabled = True

            await interaction.response.edit_message(view=self)

            await interaction.followup.send(
                "The coin has already been flipped.",
                ephemeral=True,
            )
            return

        player_1_text = f"<@{game.player_1_id}>"

        if game.player_2_id is None:
            competitors = [
                player_1_text,
                "the AI opponent",
            ]
        else:
            competitors = [
                player_1_text,
                f"<@{game.player_2_id}>",
            ]

        winner = random.choice(competitors)

        game.coin_flipped = True
        game.coin_winner = winner
        game.start_game()

        save_games(self.cog.games)

        refreshed_view = CoinFlipView(
            cog=self.cog,
            game_id=self.game_id,
        )

        await interaction.response.edit_message(view=refreshed_view)

        await interaction.followup.send(
            f"🪙 The coin has been flipped!\n\n"
            f"**{winner} wins the coin toss.**"
        )


class D12Ball(commands.GroupCog, group_name="d12ball"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.games = load_games()

        restored_views = 0

        for game in self.games.values():
            if game.message_id is None:
                continue

            if game.teams_selected:
                view = CoinFlipView(
                cog=self,
                game_id=game.game_id,
            )
            else:
                view = TeamSelectionView(
                cog=self,
                game_id=game.game_id,
            )

            self.bot.add_view(
                view,
                message_id=game.message_id,
            )

            restored_views += 1

        print(
            f"Loaded {len(self.games)} saved D12 Ball games "
            f"and restored {restored_views} button views."
        )

    def get_next_game_number(
        self,
        guild: discord.Guild,
    ) -> int:
        existing_numbers = [
            game.game_number
            for game in self.games.values()
            if game.guild_id == guild.id
        ]

        if not existing_numbers:
            return 1

        return max(existing_numbers) + 1

    @app_commands.command(
        name="create_game",
        description="Create a new D12 Ball game.",
    )
    @app_commands.describe(
        p1="Player 1. Leave blank to make yourself Player 1.",
        p2="Player 2. Leave blank to play against the AI.",
    )
    @app_commands.guild_only()
    async def create_game(
        self,
        interaction: discord.Interaction,
        p1: Optional[discord.Member] = None,
        p2: Optional[discord.Member] = None,
    ) -> None:
        guild = interaction.guild

        if guild is None:
            await interaction.response.send_message(
                "This command can only be used inside a server.",
                ephemeral=True,
            )
            return

        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "I could not identify the person creating the game.",
                ephemeral=True,
            )
            return

        # Work out which members are Player 1 and Player 2.
        if p1 is None and p2 is None:
            player_1 = interaction.user
            player_2 = None

        elif p1 is not None and p2 is None:
            player_1 = interaction.user
            player_2 = p1

        elif p1 is None and p2 is not None:
            player_1 = interaction.user
            player_2 = p2

        else:
            player_1 = p1
            player_2 = p2

        if player_1 is None:
            await interaction.response.send_message(
                "Player 1 could not be identified.",
                ephemeral=True,
            )
            return

        if player_1.bot:
            await interaction.response.send_message(
                "Player 1 cannot be a bot.",
                ephemeral=True,
            )
            return

        if player_2 is not None and player_2.bot:
            await interaction.response.send_message(
                "Player 2 cannot be a bot.",
                ephemeral=True,
            )
            return

        if player_2 is not None and player_1.id == player_2.id:
            await interaction.response.send_message(
                "Player 1 and Player 2 must be different people.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        game_number = self.get_next_game_number(guild)
        channel_name = f"d12ball-pbd{game_number}"

        bot_member = guild.me

        if bot_member is None:
            await interaction.followup.send(
                "I could not find my server account.",
                ephemeral=True,
            )
            return

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=False,
            ),
            player_1: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
            ),
            bot_member: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_channels=True,
            ),
        }

        if player_2 is not None:
            overwrites[player_2] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
            )

        category = None

        if isinstance(interaction.channel, discord.TextChannel):
            category = interaction.channel.category

        try:
            game_channel = await guild.create_text_channel(
                name=channel_name,
                overwrites=overwrites,
                category=category,
                reason=f"D12 Ball game created by {interaction.user}",
            )

        except discord.Forbidden:
            await interaction.followup.send(
                "I do not have permission to create channels.",
                ephemeral=True,
            )
            return

        except discord.HTTPException as error:
            await interaction.followup.send(
                f"Discord could not create the channel: {error}",
                ephemeral=True,
            )
            return

        game_id = uuid.uuid4().hex

        game = D12BallGame(
            game_id=game_id,
            game_number=game_number,
            guild_id=guild.id,
            channel_id=game_channel.id,
            message_id=None,
            player_1_id=player_1.id,
            player_2_id=player_2.id if player_2 else None,
            mode=GameMode.BASIC,
            status=GameStatus.SETUP,
            board_size=7,
        )

        self.games[game_id] = game

        view = TeamSelectionView(
            cog=self,
            game_id=game_id,
        )

        message_text = view.build_team_message(game)

        if player_2 is None:
            message_text = (
                f"{player_1.mention}, start playing in this channel.\n\n"
                f"{message_text}"
            )
        else:
            message_text = (
                f"{player_1.mention} {player_2.mention}, "
                f"start playing in this channel.\n\n"
                f"{message_text}"
            )

        try:
            game_message = await game_channel.send(
                message_text,
                view=view,
                allowed_mentions=discord.AllowedMentions(
                    users=True,
                    roles=False,
                    everyone=False,
                ),
            )

        except discord.HTTPException as error:
            self.games.pop(game_id, None)

            await interaction.followup.send(
                f"The channel was created, but I could not send "
                f"the game message: {error}",
                ephemeral=True,
            )
            return

        game.message_id = game_message.id
        save_games(self.games)

        await interaction.followup.send(
            f"Game created: {game_channel.mention}",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(D12Ball(bot))

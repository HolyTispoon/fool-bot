import random
import re
import uuid
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from d12ball.components import (
    MatchState,
    PlayerDefinition,
    TeamSide,
    load_basic_ruleset,
    load_player_catalog,
)
from d12ball.game import (
    D12BallGame,
    GameMode,
    GameStatus,
    HomeChoice,
    Team,
)
from d12ball.render import render_match_image

from gamesaves.d12ball.storage import (
    load_games,
    save_games,
)


CHANNEL_NAME_PATTERN = re.compile(r"^d12ball-pbd(\d+)$")
PBD_GAMES_CATEGORY_NAME = "PBD Games"
PBD_ARCHIVE_CATEGORY_NAME = "PBD Archive"
ROLE_INITIALS = {
    "fullback": "FB",
    "defender": "DD",
    "midfielder": "MF",
    "playmaker": "PM",
    "winger": "WG",
    "striker": "SK",
}


async def get_or_create_category(
    guild: discord.Guild,
    name: str,
    reason: str,
) -> discord.CategoryChannel:
    for category in guild.categories:
        if category.name.casefold() == name.casefold():
            return category

    return await guild.create_category(name=name, reason=reason)


def build_setup_message(
    game: D12BallGame,
    mention_players: bool = True,
) -> str:
    player_1 = format_player_with_team(
        game,
        1,
        mention=mention_players,
    )
    player_2 = format_player_with_team(
        game,
        2,
        mention=mention_players,
    )

    text = (
        "## D12 Ball game setup\n\n"
        "### Choose your teams\n\n"
        f"**Player 1:** {player_1}\n\n"
        f"**Player 2:** {player_2}\n\n"
        "### Game settings\n\n"
        f"Game Mode: {game.mode.value.title()}\n"
        f"Board size: {game.board_size}\n\n"
    )

    if game.coin_flipped:
        text += (
            "The coin has been flipped. See the result and the "
            "Home/Visiting selection below."
        )
    elif game.teams_selected:
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


def format_player(
    game: D12BallGame,
    player_number: Optional[int],
    mention: bool = False,
) -> str:
    if player_number == 1:
        if mention:
            return f"<@{game.player_1_id}>"
        return game.player_1_name or "Player 1"

    if player_number == 2:
        if game.player_2_id is None:
            return "AI opponent"
        if mention:
            return f"<@{game.player_2_id}>"
        return game.player_2_name or "Player 2"

    return "Unknown player"


def format_player_with_team(
    game: D12BallGame,
    player_number: Optional[int],
    mention: bool = False,
) -> str:
    player = format_player(game, player_number, mention=mention)
    team = (
        game.player_1_team
        if player_number == 1
        else game.player_2_team
    )
    team_name = team.value.title() if team else "Unknown team"
    return f"{player} ({team_name})"


def refresh_player_names(
    game: D12BallGame,
    guild: Optional[discord.Guild],
) -> None:
    if guild is None:
        return

    player_1 = guild.get_member(game.player_1_id)
    if player_1 is not None:
        game.player_1_name = player_1.display_name

    if game.player_2_id is not None:
        player_2 = guild.get_member(game.player_2_id)
        if player_2 is not None:
            game.player_2_name = player_2.display_name


def build_home_choice_message(game: D12BallGame) -> str:
    winner = format_player_with_team(
        game,
        game.coin_winner_player_number,
    )
    text = (
        "🪙 The coin has been flipped!\n\n"
        f"**{winner} wins the coin toss!**"
    )

    if game.home_and_visiting_selected:
        home_player = format_player_with_team(
            game,
            game.home_player_number,
        )
        visiting_player = format_player_with_team(
            game,
            game.visiting_player_number,
        )
        text += (
            f"\n\n**Home:** {home_player}\n"
            f"**Visiting:** {visiting_player}"
        )
    else:
        winner_mention = format_player_with_team(
            game,
            game.coin_winner_player_number,
            mention=True,
        )
        text += (
            f"\n\n{winner_mention}, choose whether you want to play "
            "as Home or Visiting."
        )

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
            refreshed_view = HomeAwaySelectionView(
                cog=self.cog,
                game_id=self.game_id,
            )

            await interaction.response.edit_message(
                content=build_home_choice_message(game),
                view=refreshed_view,
            )

            await interaction.followup.send(
                "The coin has already been flipped.",
                ephemeral=True,
            )
            return

        winner_player_number = random.choice((1, 2))
        refresh_player_names(game, interaction.guild)
        winner = format_player(game, winner_player_number)

        game.coin_flipped = True
        game.coin_winner = winner
        game.coin_winner_player_number = winner_player_number
        game.start_game()

        if game.is_solo_game and winner_player_number == 2:
            ai_choice = random.choice(
                (HomeChoice.HOME, HomeChoice.VISITING)
            )
            game.choose_home_or_visiting(2, ai_choice)
            self.cog.initialize_standard_match(game)

        refreshed_view = HomeAwaySelectionView(
            cog=self.cog,
            game_id=self.game_id,
        )

        await interaction.response.edit_message(
            content=build_setup_message(
                game,
                mention_players=False,
            ),
            view=None,
        )

        followup_arguments = {
            "view": refreshed_view,
            "wait": True,
        }
        if game.match_state is not None:
            followup_arguments["file"] = self.cog.build_match_file(game)

        choice_message = await interaction.followup.send(
            build_home_choice_message(game),
            **followup_arguments,
        )
        game.message_id = choice_message.id
        save_games(self.cog.games)

        if game.match_state is not None:
            await self.cog.send_turn_prompt(interaction, game)


class HomeAwaySelectionView(discord.ui.View):
    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
    ):
        super().__init__(timeout=None)

        self.cog = cog
        self.game_id = game_id

        game = self.cog.games.get(game_id)
        selected_choice = None
        assignment_complete = bool(
            game and game.home_and_visiting_selected
        )

        if assignment_complete and game is not None:
            selected_choice = (
                HomeChoice.HOME
                if (
                    game.home_player_number
                    == game.coin_winner_player_number
                )
                else HomeChoice.VISITING
            )

        for label, choice in (
            ("Home", HomeChoice.HOME),
            ("Visiting", HomeChoice.VISITING),
        ):
            button = discord.ui.Button(
                label=label,
                style=(
                    discord.ButtonStyle.success
                    if choice == selected_choice
                    else (
                        discord.ButtonStyle.secondary
                        if assignment_complete
                        else discord.ButtonStyle.primary
                    )
                ),
                custom_id=(
                    f"d12ball:home_choice:{game_id}:{choice.value}"
                ),
                disabled=assignment_complete,
            )

            async def callback(
                interaction: discord.Interaction,
                selected_choice: HomeChoice = choice,
            ) -> None:
                await self.select_home_or_visiting(
                    interaction,
                    selected_choice,
                )

            button.callback = callback
            self.add_item(button)

    async def select_home_or_visiting(
        self,
        interaction: discord.Interaction,
        choice: HomeChoice,
    ) -> None:
        game = self.cog.games.get(self.game_id)

        if game is None:
            await interaction.response.send_message(
                "I could not find the saved data for this game.",
                ephemeral=True,
            )
            return

        if game.home_and_visiting_selected:
            await interaction.response.send_message(
                "Home and visiting teams have already been assigned.",
                ephemeral=True,
            )
            return

        winner_player_number = game.coin_winner_player_number
        refresh_player_names(game, interaction.guild)
        winner_user_id = (
            game.player_1_id
            if winner_player_number == 1
            else game.player_2_id
        )

        if interaction.user.id != winner_user_id:
            await interaction.response.send_message(
                "Only the player who won the coin toss can make this choice.",
                ephemeral=True,
            )
            return

        game.choose_home_or_visiting(winner_player_number, choice)
        self.cog.initialize_standard_match(game)
        save_games(self.cog.games)

        refreshed_view = HomeAwaySelectionView(
            cog=self.cog,
            game_id=self.game_id,
        )
        await interaction.response.edit_message(
            content=build_home_choice_message(game),
            view=refreshed_view,
            attachments=[self.cog.build_match_file(game)],
        )

        await interaction.followup.send(
            f"{format_player_with_team(game, winner_player_number)} chose "
            f"**{choice.value.title()}**."
        )
        await self.cog.send_turn_prompt(interaction, game)


class BallHandlerSelectionView(discord.ui.View):
    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
    ):
        super().__init__(timeout=None)

        self.cog = cog
        self.game_id = game_id
        game = self.cog.games.get(game_id)
        if game is None or game.match_state is None:
            return

        match = self.cog.load_match_state(game)
        for player_id in match.eligible_ball_handlers():
            player = self.cog.get_player_definition(player_id)
            button = discord.ui.Button(
                label=player.name,
                style=discord.ButtonStyle.primary,
                custom_id=(
                    f"d12ball:ball_handler:{game_id}:{player_id}"
                ),
            )

            async def callback(
                interaction: discord.Interaction,
                selected_player_id: str = player_id,
            ) -> None:
                await self.select_handler(
                    interaction,
                    selected_player_id,
                )

            button.callback = callback
            self.add_item(button)

    async def select_handler(
        self,
        interaction: discord.Interaction,
        player_id: str,
    ) -> None:
        game = self.cog.games.get(self.game_id)
        if game is None or game.match_state is None:
            await interaction.response.send_message(
                "I could not find the saved data for this game.",
                ephemeral=True,
            )
            return

        match = self.cog.load_match_state(game)
        if match.active_player_id is not None:
            await interaction.response.edit_message(
                content=self.cog.build_turn_prompt(game, match),
                view=PlayerActionView(self.cog, self.game_id),
            )
            await interaction.followup.send(
                "A player has already been selected.",
                ephemeral=True,
            )
            return

        if not self.cog.user_controls_possession(
            interaction.user.id,
            game,
            match,
        ):
            await interaction.response.send_message(
                "Only the player whose team has possession can "
                "choose the ball handler.",
                ephemeral=True,
            )
            return

        try:
            match.select_ball_handler(player_id)
        except ValueError as error:
            await interaction.response.send_message(
                str(error),
                ephemeral=True,
            )
            return

        game.match_state = match.to_dict()
        save_games(self.cog.games)
        await interaction.response.edit_message(
            content=self.cog.build_turn_prompt(game, match),
            view=PlayerActionView(self.cog, self.game_id),
        )


class PlayerActionView(discord.ui.View):
    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
    ):
        super().__init__(timeout=None)

        self.cog = cog
        self.game_id = game_id

        for label, action, style in (
            (
                "Shoot to score",
                "shoot",
                discord.ButtonStyle.danger,
            ),
            (
                "Maneuver",
                "maneuver",
                discord.ButtonStyle.primary,
            ),
        ):
            button = discord.ui.Button(
                label=label,
                style=style,
                custom_id=f"d12ball:action:{game_id}:{action}",
            )

            async def callback(
                interaction: discord.Interaction,
                selected_action: str = action,
                action_label: str = label,
            ) -> None:
                await self.choose_action(
                    interaction,
                    selected_action,
                    action_label,
                )

            button.callback = callback
            self.add_item(button)

    async def choose_action(
        self,
        interaction: discord.Interaction,
        action: str,
        action_label: str,
    ) -> None:
        game = self.cog.games.get(self.game_id)
        if game is None or game.match_state is None:
            await interaction.response.send_message(
                "I could not find the saved data for this game.",
                ephemeral=True,
            )
            return

        match = self.cog.load_match_state(game)
        if match.active_player_id is None:
            await interaction.response.send_message(
                "Choose a player to handle the ball first.",
                ephemeral=True,
            )
            return

        if not self.cog.user_controls_possession(
            interaction.user.id,
            game,
            match,
        ):
            await interaction.response.send_message(
                "Only the player whose team has possession can "
                "choose this action.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"{action_label} is not implemented yet.",
            ephemeral=True,
        )


class D12Ball(commands.GroupCog, group_name="d12ball"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.games = load_games()
        self.player_catalog = load_player_catalog()
        self.basic_ruleset = load_basic_ruleset()

        restored_views = 0

        for game in self.games.values():
            setup_view = None
            if game.coin_flipped and not game.home_and_visiting_selected:
                setup_view = HomeAwaySelectionView(
                    cog=self,
                    game_id=game.game_id,
                )
            elif game.teams_selected and not game.coin_flipped:
                setup_view = CoinFlipView(
                    cog=self,
                    game_id=game.game_id,
                )
            elif not game.teams_selected:
                setup_view = TeamSelectionView(
                    cog=self,
                    game_id=game.game_id,
                )

            if setup_view is not None and game.message_id is not None:
                self.bot.add_view(
                    setup_view,
                    message_id=game.message_id,
                )
                restored_views += 1

            if (
                game.turn_message_id is not None
                and game.match_state is not None
            ):
                match = self.load_match_state(game)
                turn_view = (
                    PlayerActionView(self, game.game_id)
                    if match.active_player_id is not None
                    else BallHandlerSelectionView(self, game.game_id)
                )
                self.bot.add_view(
                    turn_view,
                    message_id=game.turn_message_id,
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

    def initialize_standard_match(
        self,
        game: D12BallGame,
    ) -> MatchState:
        if not game.home_and_visiting_selected:
            raise ValueError(
                "Home and visiting teams must be selected first."
            )
        if game.player_1_team is None or game.player_2_team is None:
            raise ValueError("Both teams must be selected first.")

        home_team = (
            game.player_1_team
            if game.home_player_number == 1
            else game.player_2_team
        )
        visiting_team = (
            game.player_1_team
            if game.visiting_player_number == 1
            else game.player_2_team
        )
        match = MatchState.standard(
            catalog=self.player_catalog,
            ruleset=self.basic_ruleset,
            board_size=game.board_size,
            home_team=home_team,
            visiting_team=visiting_team,
        )
        game.ruleset_id = match.ruleset_id
        game.player_data_version = match.player_data_version
        game.match_state = match.to_dict()
        return match

    def load_match_state(self, game: D12BallGame) -> MatchState:
        if game.match_state is None:
            raise ValueError("This game does not have initialized match state.")
        match = MatchState.from_dict(
            game.match_state,
            self.basic_ruleset,
        )
        match.validate(self.player_catalog)
        return match

    def get_player_definition(
        self,
        player_id: str,
    ) -> PlayerDefinition:
        for roster in self.player_catalog.teams.values():
            for player in roster.players:
                if player.player_id == player_id:
                    return player
        raise ValueError(f"Unknown player: {player_id}")

    def possession_player_number(
        self,
        game: D12BallGame,
        match: MatchState,
    ) -> Optional[int]:
        if match.ball.possession == TeamSide.HOME:
            return game.home_player_number
        return game.visiting_player_number

    def possession_user_id(
        self,
        game: D12BallGame,
        match: MatchState,
    ) -> Optional[int]:
        player_number = self.possession_player_number(game, match)
        if player_number == 1:
            return game.player_1_id
        if player_number == 2:
            return game.player_2_id
        return None

    def user_controls_possession(
        self,
        user_id: int,
        game: D12BallGame,
        match: MatchState,
    ) -> bool:
        return self.possession_user_id(game, match) == user_id

    def format_roster_player(self, player_id: str) -> str:
        player = self.get_player_definition(player_id)
        initials = ROLE_INITIALS[player.role.value]
        return f"{player.name} ({initials})"

    def build_turn_prompt(
        self,
        game: D12BallGame,
        match: MatchState,
    ) -> str:
        player_number = self.possession_player_number(game, match)
        controller = format_player_with_team(
            game,
            player_number,
            mention=player_number is not None,
        )

        if match.active_player_id is None:
            return (
                f"{controller}, it is your turn.\n\n"
                "Choose which player in the ball's space will take "
                "an action."
            )

        handler = self.format_roster_player(match.active_player_id)
        return (
            f"{controller}, it is your turn.\n\n"
            f"{handler} will be handling the ball.\n\n"
            "Choose an action:"
        )

    async def send_turn_prompt(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
    ) -> None:
        refresh_player_names(game, interaction.guild)
        match = self.load_match_state(game)
        eligible_handlers = match.eligible_ball_handlers()
        if not eligible_handlers:
            raise ValueError(
                "The team in possession has no player in the ball's space."
            )

        if len(eligible_handlers) == 1:
            match.select_ball_handler(eligible_handlers[0])
            game.match_state = match.to_dict()
            view: discord.ui.View = PlayerActionView(
                self,
                game.game_id,
            )
        else:
            view = BallHandlerSelectionView(
                self,
                game.game_id,
            )

        turn_message = await interaction.followup.send(
            self.build_turn_prompt(game, match),
            view=view,
            wait=True,
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False,
            ),
        )
        game.turn_message_id = turn_message.id
        save_games(self.games)

    def build_match_file(self, game: D12BallGame) -> discord.File:
        match = self.load_match_state(game)
        home_player = format_player_with_team(
            game,
            game.home_player_number,
        )
        visiting_player = format_player_with_team(
            game,
            game.visiting_player_number,
        )
        period = (
            "First Half"
            if match.scoreboard.period.value == "first_half"
            else "Second Half"
        )
        title = (
            f"PBD{game.game_number} - {home_player} vs. "
            f"{visiting_player}, {period}"
        )
        image = render_match_image(
            match,
            self.player_catalog,
            title=title,
        )
        return discord.File(
            image,
            filename=f"d12ball-pbd{game.game_number}.png",
        )

    async def archive_game_channel(
        self,
        game: D12BallGame,
    ) -> None:
        guild = self.bot.get_guild(game.guild_id)
        if guild is None:
            raise ValueError("The server for this game is not available.")

        channel = guild.get_channel(game.channel_id)
        if channel is None:
            channel = await guild.fetch_channel(game.channel_id)

        if not isinstance(channel, discord.TextChannel):
            raise ValueError("The channel for this game is not a text channel.")

        if (
            channel.category is not None
            and channel.category.name.casefold()
            == PBD_ARCHIVE_CATEGORY_NAME.casefold()
        ):
            return

        archive_category = await get_or_create_category(
            guild,
            PBD_ARCHIVE_CATEGORY_NAME,
            "Create the category for finished PBD games.",
        )
        await channel.edit(
            category=archive_category,
            reason="Move a finished D12 Ball game to the PBD archive.",
        )

    async def finish_and_archive_game(
        self,
        game_id: str,
    ) -> D12BallGame:
        game = self.games.get(game_id)
        if game is None:
            raise ValueError("The D12 Ball game could not be found.")

        if game.status != GameStatus.IN_PROGRESS:
            raise ValueError("Only a game in progress can be finished.")

        await self.archive_game_channel(game)
        game.finish_game()
        save_games(self.games)
        return game

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        for game in self.games.values():
            if game.status != GameStatus.FINISHED:
                continue

            try:
                await self.archive_game_channel(game)
            except (ValueError, discord.Forbidden, discord.HTTPException) as error:
                print(
                    f"Could not archive finished D12 Ball game "
                    f"{game.game_id}: {error}"
                )

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

        try:
            category = await get_or_create_category(
                guild,
                PBD_GAMES_CATEGORY_NAME,
                "Create the category for active PBD games.",
            )
            game_channel = await guild.create_text_channel(
                name=channel_name,
                overwrites=overwrites,
                category=category,
                reason=f"D12 Ball game created by {interaction.user}",
            )

        except discord.Forbidden:
            await interaction.followup.send(
                "I do not have permission to create the PBD Games category "
                "or its game channels.",
                ephemeral=True,
            )
            return

        except discord.HTTPException as error:
            await interaction.followup.send(
                f"Discord could not create the channel: {error}",
                ephemeral=True,
            )
            return

        try:
            await game_channel.set_permissions(
                bot_member,
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_channels=True,
                reason="Ensure the bot can manage its private game channel.",
            )
        except (discord.Forbidden, discord.HTTPException) as error:
            bot_permissions = game_channel.permissions_for(bot_member)

            if (
                not bot_permissions.view_channel
                or not bot_permissions.manage_channels
            ):
                await interaction.followup.send(
                    "The private channel was created, but I could not add "
                    f"myself with permission to manage it: {error}",
                    ephemeral=True,
                )
                return

        bot_permissions = game_channel.permissions_for(bot_member)
        if (
            not bot_permissions.view_channel
            or not bot_permissions.manage_channels
        ):
            await interaction.followup.send(
                "The private channel was created, but Discord did not grant "
                "me View Channel and Manage Channels permissions.",
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
            player_1_name=player_1.display_name,
            player_2_name=player_2.display_name if player_2 else None,
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

        message_text = (
            "Start playing in this channel.\n\n"
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

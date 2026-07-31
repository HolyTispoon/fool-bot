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
    load_maneuver_catalog,
    load_player_catalog,
)
from d12ball.game import (
    CoinFace,
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
COIN_EMOJI_NAMES = {
    CoinFace.FORTUNE: "3_gold_fortune",
    CoinFace.DOOM: "3_gold_doom",
}
COIN_EMOJI_FALLBACK = "🪙"

# The exhaustion token emoji is uploaded to Discord (as an application or
# guild emoji) from images/emoji/exhaust.png and looked up here by name.
EXHAUST_EMOJI_NAME = "exhaust"
EXHAUST_EMOJI_FALLBACK = "😮\u200d💨"


def get_exhaust_emoji(client: discord.Client) -> str:
    emoji = discord.utils.get(client.emojis, name=EXHAUST_EMOJI_NAME)
    if emoji is not None:
        return str(emoji)
    return EXHAUST_EMOJI_FALLBACK


def format_role_bracket(player: PlayerDefinition) -> str:
    initials = ROLE_INITIALS[player.role.value]
    return f"{player.name} [{initials}]"


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
            "Flip the coin below to determine who chooses whether they "
            "are home team. A fortune side wins the toss for whoever "
            "flipped it, a doom side hands it to their opponent."
        )
    elif game.is_solo_game:
        text += (
            "Choose a team using the buttons. After you chose your team, "
            "a random team will be assigned to the Dinky AI of the "
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
            return "Dinky AI"
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


async def load_coin_emojis(
    bot: commands.Bot,
) -> dict[CoinFace, str]:
    """
    Look up the coin emoji uploaded to the application.

    Application emoji work in every server the bot is in, but
    discord.py does not cache them, so they are fetched once and kept
    as ready-to-post <:name:id> strings.

    Anything that goes wrong here leaves a face out of the mapping and
    the coin toss falls back to a plain coin. An app that has not had
    the emoji uploaded yet is the expected case, not an error.
    """
    try:
        emojis = await bot.fetch_application_emojis()
    except Exception as error:
        # Deliberately broad: the emoji is decoration, and no failure
        # to fetch it should stop anyone from flipping a coin.
        print(f"Could not load the D12 Ball coin emoji: {error}")
        return {}

    emojis_by_name = {emoji.name: emoji for emoji in emojis}
    coin_emojis: dict[CoinFace, str] = {}
    missing: list[str] = []

    for face, name in COIN_EMOJI_NAMES.items():
        emoji = emojis_by_name.get(name)

        if emoji is None:
            missing.append(name)
        else:
            coin_emojis[face] = str(emoji)

    if missing:
        print(
            "This application has no coin emoji named "
            f"{', '.join(missing)}; coin tosses will show "
            f"{COIN_EMOJI_FALLBACK} instead."
        )

    return coin_emojis


def format_coin_emoji(
    coin_emojis: Optional[dict[CoinFace, str]],
    face: Optional[CoinFace],
) -> str:
    """
    The emoji for a coin face, or a plain coin when it is unavailable.
    """
    if not coin_emojis or face is None:
        return COIN_EMOJI_FALLBACK

    return coin_emojis.get(CoinFace(face), COIN_EMOJI_FALLBACK)


def build_home_choice_message(game: D12BallGame) -> str:
    winner = format_player_with_team(
        game,
        game.coin_winner_player_number,
    )

    if (
        game.coin_face is not None
        and game.coin_flipped_by_player_number is not None
    ):
        flipper = format_player_with_team(
            game,
            game.coin_flipped_by_player_number,
        )
        # The coin itself goes out as its own message, so that Discord
        # renders it large; this text does not repeat it.
        text = (
            f"{flipper} flipped "
            f"**{game.coin_face.value.title()}**!\n\n"
            f"**{winner} wins the coin toss!**"
        )
    else:
        # Games flipped before coin faces were recorded.
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
            # Resolved before the view is built, because the flip
            # button carries the fortune coin.
            await self.cog.ensure_coin_emojis()
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
            label=(
                "Flip a Coin! Fortune wins it, doom loses it "
                "(this would start the game)"
            ),
            style=discord.ButtonStyle.primary,
            emoji=format_coin_emoji(
                self.cog.coin_emojis,
                CoinFace.FORTUNE,
            ),
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

        flipping_player_number = (
            1 if interaction.user.id == game.player_1_id else 2
        )
        face = random.choice((CoinFace.FORTUNE, CoinFace.DOOM))

        refresh_player_names(game, interaction.guild)
        winner_player_number = game.resolve_coin_toss(
            flipping_player_number,
            face,
        )

        game.coin_winner = format_player(game, winner_player_number)
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

        # The coin goes out on its own, with nothing else in the
        # message, which is what makes Discord render it large.
        await interaction.followup.send(
            format_coin_emoji(
                await self.cog.ensure_coin_emojis(),
                game.coin_face,
            ),
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

        if action != "maneuver":
            await interaction.response.send_message(
                f"{action_label} is not implemented yet.",
                ephemeral=True,
            )
            return

        eligible_challengers = match.eligible_challengers()
        if not eligible_challengers:
            await interaction.response.send_message(
                "The defending team has no player in the ball's zone "
                "to challenge.",
                ephemeral=True,
            )
            return

        match.pending_action = "maneuver"
        handler = self.cog.get_player_definition(match.active_player_id)
        defender_number = self.cog.defending_player_number(game, match)

        if game.is_solo_game and defender_number == 2:
            challenger_id = self.cog.choose_ai_challenger(match)
            distance = match.choose_challenger(challenger_id)
            game.match_state = match.to_dict()
            save_games(self.cog.games)

            refresh_player_names(game, interaction.guild)

            await interaction.response.edit_message(
                content=(
                    f"**{action_label}** was chosen for "
                    f"{format_role_bracket(handler)}."
                ),
                view=None,
            )
            await interaction.followup.send(
                self.cog.build_challenge_announcement(
                    interaction.client,
                    game,
                    match,
                    challenger_id,
                    distance,
                ),
                allowed_mentions=discord.AllowedMentions(
                    users=False,
                    roles=False,
                    everyone=False,
                ),
            )
            await self.cog.refresh_match_image(interaction, game)
            await self.cog.begin_maneuver_action_selection(
                interaction,
                game,
                match,
            )
            return

        game.match_state = match.to_dict()
        save_games(self.cog.games)

        refresh_player_names(game, interaction.guild)
        defender_mention = format_player_with_team(
            game,
            defender_number,
            mention=True,
        )

        await interaction.response.edit_message(
            content=(
                f"**{action_label}** was chosen for "
                f"{format_role_bracket(handler)}.\n\n"
                "Waiting for the defense to choose a challenger..."
            ),
            view=None,
        )

        challenge_view = ManeuverChallengeView(self.cog, self.game_id)
        challenge_message = await interaction.followup.send(
            f"{defender_mention}, choose which player will maneuver "
            "to challenge for the ball.",
            view=challenge_view,
            wait=True,
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False,
            ),
        )
        game.turn_message_id = challenge_message.id
        save_games(self.cog.games)


class ManeuverChallengeView(discord.ui.View):
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
        for player_id in match.eligible_challengers():
            player = self.cog.get_player_definition(player_id)
            distance = match.distance_to_ball(player_id)
            initials = ROLE_INITIALS[player.role.value]
            button = discord.ui.Button(
                label=f"{player.name} [{initials}] ({distance})",
                style=discord.ButtonStyle.primary,
                custom_id=(
                    f"d12ball:challenger:{game_id}:{player_id}"
                ),
            )

            async def callback(
                interaction: discord.Interaction,
                selected_player_id: str = player_id,
            ) -> None:
                await self.select_challenger(
                    interaction,
                    selected_player_id,
                )

            button.callback = callback
            self.add_item(button)

    async def select_challenger(
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

        if match.challenger_id is not None:
            await interaction.response.edit_message(
                content=self.cog.build_turn_prompt(game, match),
                view=PlayerActionView(self.cog, self.game_id),
            )
            await interaction.followup.send(
                "A defender has already been chosen.",
                ephemeral=True,
            )
            return

        if not self.cog.user_controls_defense(
            interaction.user.id,
            game,
            match,
        ):
            await interaction.response.send_message(
                "Only the player whose team is defending can make "
                "this choice.",
                ephemeral=True,
            )
            return

        try:
            distance = match.choose_challenger(player_id)
        except ValueError as error:
            await interaction.response.send_message(
                str(error),
                ephemeral=True,
            )
            return

        game.match_state = match.to_dict()
        save_games(self.cog.games)

        refresh_player_names(game, interaction.guild)
        defender_number = self.cog.defending_player_number(game, match)
        defender_display = format_player_with_team(game, defender_number)

        announcement = self.cog.build_challenge_announcement(
            interaction.client,
            game,
            match,
            player_id,
            distance,
        )

        await interaction.response.edit_message(
            content=f"{defender_display} has chosen their challenger.",
            view=None,
        )
        await interaction.followup.send(
            announcement,
            allowed_mentions=discord.AllowedMentions(
                users=False,
                roles=False,
                everyone=False,
            ),
        )

        await self.cog.refresh_match_image(interaction, game)
        await self.cog.begin_maneuver_action_selection(
            interaction,
            game,
            match,
        )


class ManeuverActionPromptView(discord.ui.View):
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

        sides: list[tuple[str, str]] = []
        if match.offense_maneuver is None and not (
            game.is_solo_game
            and self.cog.possession_player_number(game, match) == 2
        ):
            sides.append(("offense", "Offense: Choose Maneuver"))
        if match.defense_maneuver is None and not (
            game.is_solo_game
            and self.cog.defending_player_number(game, match) == 2
        ):
            sides.append(("defense", "Defense: Choose Maneuver"))

        for side, label in sides:
            button = discord.ui.Button(
                label=label,
                style=discord.ButtonStyle.primary,
                custom_id=f"d12ball:maneuver_prompt:{game_id}:{side}",
            )

            async def callback(
                interaction: discord.Interaction,
                chosen_side: str = side,
            ) -> None:
                await self.open_action_menu(interaction, chosen_side)

            button.callback = callback
            self.add_item(button)

    async def open_action_menu(
        self,
        interaction: discord.Interaction,
        side: str,
    ) -> None:
        game = self.cog.games.get(self.game_id)
        if game is None or game.match_state is None:
            await interaction.response.send_message(
                "I could not find the saved data for this game.",
                ephemeral=True,
            )
            return

        match = self.cog.load_match_state(game)

        if side == "offense":
            authorized = self.cog.user_controls_possession(
                interaction.user.id,
                game,
                match,
            )
            already_chosen = match.offense_maneuver is not None
        else:
            authorized = self.cog.user_controls_defense(
                interaction.user.id,
                game,
                match,
            )
            already_chosen = match.defense_maneuver is not None

        if already_chosen:
            await interaction.response.send_message(
                "A maneuver has already been chosen for that side.",
                ephemeral=True,
            )
            return

        if not authorized:
            await interaction.response.send_message(
                "Only the player on that side can choose this maneuver.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            content=self.cog.build_maneuver_reference_text(),
            view=ManeuverActionSelectView(self.cog, self.game_id, side),
            ephemeral=True,
        )


class ManeuverActionSelectView(discord.ui.View):
    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
        side: str,
    ):
        super().__init__(timeout=180)

        self.cog = cog
        self.game_id = game_id
        self.side = side

        maneuvers = (
            cog.maneuver_catalog.offense
            if side == "offense"
            else cog.maneuver_catalog.defense
        )
        for maneuver in sorted(maneuvers, key=lambda item: item.rank):
            button = discord.ui.Button(
                label=maneuver.name,
                style=discord.ButtonStyle.primary,
                custom_id=(
                    f"d12ball:maneuver_pick:{game_id}:{side}:"
                    f"{maneuver.name}"
                ),
            )

            async def callback(
                interaction: discord.Interaction,
                chosen_name: str = maneuver.name,
            ) -> None:
                await self.pick(interaction, chosen_name)

            button.callback = callback
            self.add_item(button)

    async def pick(
        self,
        interaction: discord.Interaction,
        maneuver_name: str,
    ) -> None:
        game = self.cog.games.get(self.game_id)
        if game is None or game.match_state is None:
            await interaction.response.send_message(
                "I could not find the saved data for this game.",
                ephemeral=True,
            )
            return

        match = self.cog.load_match_state(game)

        if self.side == "offense":
            authorized = self.cog.user_controls_possession(
                interaction.user.id,
                game,
                match,
            )
            already_chosen = match.offense_maneuver is not None
        else:
            authorized = self.cog.user_controls_defense(
                interaction.user.id,
                game,
                match,
            )
            already_chosen = match.defense_maneuver is not None

        if already_chosen:
            await interaction.response.edit_message(
                content="A maneuver has already been chosen for that side.",
                view=None,
            )
            return

        if not authorized:
            await interaction.response.send_message(
                "Only the player on that side can choose this maneuver.",
                ephemeral=True,
            )
            return

        if self.side == "offense":
            match.choose_offense_maneuver(maneuver_name)
        else:
            match.choose_defense_maneuver(maneuver_name)

        game.match_state = match.to_dict()
        save_games(self.cog.games)

        await interaction.response.edit_message(
            content=f"You chose **{maneuver_name}**.",
            view=None,
        )

        side_number = (
            self.cog.possession_player_number(game, match)
            if self.side == "offense"
            else self.cog.defending_player_number(game, match)
        )
        side_display = format_player_with_team(game, side_number)
        await interaction.followup.send(
            f"{side_display} has picked their maneuver.",
        )

        await self.cog.refresh_maneuver_prompt(interaction, game)

        if (
            match.offense_maneuver is not None
            and match.defense_maneuver is not None
        ):
            await self.cog.resolve_maneuver_clash(interaction, game, match)


class SkillTestView(discord.ui.View):
    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
    ):
        super().__init__(timeout=None)

        self.cog = cog
        self.game_id = game_id

        button = discord.ui.Button(
            label="Roll the skill test",
            style=discord.ButtonStyle.primary,
            custom_id=f"d12ball:skill_test:{game_id}",
        )
        button.callback = self.roll
        self.add_item(button)

    async def roll(self, interaction: discord.Interaction) -> None:
        game = self.cog.games.get(self.game_id)
        if game is None or game.match_state is None:
            await interaction.response.send_message(
                "I could not find the saved data for this game.",
                ephemeral=True,
            )
            return

        match = self.cog.load_match_state(game)
        if match.offense_maneuver is None or match.defense_maneuver is None:
            await interaction.response.send_message(
                "This skill test is no longer active.",
                ephemeral=True,
            )
            return

        participant_ids = {game.player_1_id}
        if game.player_2_id is not None:
            participant_ids.add(game.player_2_id)

        if interaction.user.id not in participant_ids:
            await interaction.response.send_message(
                "Only a player in this game can roll the skill test.",
                ephemeral=True,
            )
            return

        offense_player = self.cog.get_player_definition(
            match.active_player_id,
        )
        defense_player = self.cog.get_player_definition(
            match.challenger_id,
        )
        offense_skill = self.cog.player_catalog.effective_profile(
            offense_player,
        ).offense
        defense_skill = self.cog.player_catalog.effective_profile(
            defense_player,
        ).defense

        offense_roll = random.randint(1, 12)
        defense_roll = random.randint(1, 12)
        offense_total = offense_roll + offense_skill
        defense_total = defense_roll + defense_skill

        modifier_note = ""
        if match.defense_maneuver == "Steal Intercept":
            modifier = match.ball.speed // 2
            defense_total += modifier
            modifier_note = f" + {modifier} ball speed"

        breakdown = (
            f"**{format_role_bracket(offense_player)}** (offense): "
            f"d12 {offense_roll} + skill {offense_skill} = "
            f"{offense_total}\n"
            f"**{format_role_bracket(defense_player)}** (defense): "
            f"d12 {defense_roll} + skill {defense_skill}"
            f"{modifier_note} = {defense_total}"
        )

        if offense_total == defense_total:
            match.add_exhaustion(match.active_player_id, 1)
            match.add_exhaustion(match.challenger_id, 1)
            game.match_state = match.to_dict()
            save_games(self.cog.games)

            exhaust_emoji = get_exhaust_emoji(interaction.client)
            await interaction.response.edit_message(
                content=(
                    f"{breakdown}\n\n"
                    "Another tie! Both players gain an exhaustion "
                    f"token {exhaust_emoji}. Roll again:"
                ),
                view=SkillTestView(self.cog, self.game_id),
            )
            await self.cog.refresh_match_image(interaction, game)
            return

        outcome = "offense" if offense_total > defense_total else "defense"
        winner_name = (
            match.offense_maneuver
            if outcome == "offense"
            else match.defense_maneuver
        )
        catalog = self.cog.maneuver_catalog
        winner_definition = (
            catalog.offense_by_name()
            if outcome == "offense"
            else catalog.defense_by_name()
        )[winner_name]
        winner_number = (
            self.cog.possession_player_number(game, match)
            if outcome == "offense"
            else self.cog.defending_player_number(game, match)
        )
        winner_mention = format_player_with_team(
            game,
            winner_number,
            mention=True,
        )

        match.reset_maneuver()
        game.match_state = match.to_dict()
        save_games(self.cog.games)

        await interaction.response.edit_message(
            content=(
                f"{breakdown}\n\n"
                f"**{winner_name}** wins the skill test! {winner_mention}, "
                f"resolve the effect:\n{winner_definition.effect}"
            ),
            view=None,
        )
        await self.cog.refresh_match_image(interaction, game)


class D12Ball(commands.GroupCog, group_name="d12ball"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.games = load_games()
        self.player_catalog = load_player_catalog()
        self.basic_ruleset = load_basic_ruleset()
        self.maneuver_catalog = load_maneuver_catalog()
        self.coin_emojis: dict[CoinFace, str] = {}

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
                if match.active_player_id is None:
                    turn_view = BallHandlerSelectionView(self, game.game_id)
                elif (
                    match.pending_action == "maneuver"
                    and match.challenger_id is None
                ):
                    turn_view = ManeuverChallengeView(self, game.game_id)
                elif (
                    match.pending_action == "maneuver"
                    and match.challenger_id is not None
                    and (
                        match.offense_maneuver is None
                        or match.defense_maneuver is None
                    )
                ):
                    turn_view = ManeuverActionPromptView(self, game.game_id)
                elif (
                    match.pending_action == "maneuver"
                    and match.challenger_id is not None
                    and match.offense_maneuver is not None
                    and match.defense_maneuver is not None
                ):
                    turn_view = SkillTestView(self, game.game_id)
                else:
                    turn_view = PlayerActionView(self, game.game_id)
                self.bot.add_view(
                    turn_view,
                    message_id=game.turn_message_id,
                )
                restored_views += 1

        print(
            f"Loaded {len(self.games)} saved D12 Ball games "
            f"and restored {restored_views} button views."
        )

    async def cog_load(self) -> None:
        self.coin_emojis = await load_coin_emojis(self.bot)

    async def ensure_coin_emojis(self) -> dict[CoinFace, str]:
        """
        The coin emoji, retrying the lookup while any are missing.

        Uploading the emoji to the application therefore takes effect
        on the next coin toss instead of needing a restart.
        """
        if len(self.coin_emojis) < len(COIN_EMOJI_NAMES):
            self.coin_emojis = await load_coin_emojis(self.bot)

        return self.coin_emojis

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

    def defending_player_number(
        self,
        game: D12BallGame,
        match: MatchState,
    ) -> Optional[int]:
        offense_number = self.possession_player_number(game, match)
        if offense_number == 1:
            return 2
        if offense_number == 2:
            return 1
        return None

    def defending_user_id(
        self,
        game: D12BallGame,
        match: MatchState,
    ) -> Optional[int]:
        player_number = self.defending_player_number(game, match)
        if player_number == 1:
            return game.player_1_id
        if player_number == 2:
            return game.player_2_id
        return None

    def user_controls_defense(
        self,
        user_id: int,
        game: D12BallGame,
        match: MatchState,
    ) -> bool:
        return self.defending_user_id(game, match) == user_id

    def choose_ai_challenger(self, match: MatchState) -> str:
        """
        Dinky AI's rule for picking a challenger: always the
        player closest to the ball, with ties broken in favor of the
        higher defensive skill.
        """
        candidates = match.eligible_challengers()
        if not candidates:
            raise ValueError(
                "There are no eligible challengers to choose from."
            )

        def sort_key(player_id: str) -> tuple[int, int]:
            distance = match.distance_to_ball(player_id)
            defense = self.player_catalog.effective_profile(
                self.get_player_definition(player_id)
            ).defense
            return (distance, -defense)

        return min(candidates, key=sort_key)

    def choose_ai_ball_handler(self, match: MatchState) -> str:
        """
        Dinky AI's rule for picking which fielded player handles the
        ball when more than one of its players shares the ball's space:
        the one with the higher offensive skill.
        """
        candidates = match.eligible_ball_handlers()
        if not candidates:
            raise ValueError(
                "There are no eligible ball handlers to choose from."
            )

        def sort_key(player_id: str) -> int:
            return -self.player_catalog.effective_profile(
                self.get_player_definition(player_id)
            ).offense

        return min(candidates, key=sort_key)

    def choose_ai_action(self, match: MatchState) -> str:
        """
        Dinky AI's rule for choosing an offensive action: shoot when the
        ball is already on the space closest to the opponent's goal,
        otherwise always maneuver to advance it.
        """
        if match.is_ball_at_scoring_space():
            return "shoot"
        return "maneuver"

    def choose_ai_maneuver_action(self, side: str) -> str:
        """
        Dinky AI's rule for a maneuver clash: always roll a d6 and take
        whichever maneuver that die value maps to.
        """
        roll = random.randint(1, 6)
        if side == "offense":
            return self.maneuver_catalog.offense_for_die(roll).name
        return self.maneuver_catalog.defense_for_die(roll).name

    def build_maneuver_reference_text(self) -> str:
        lines = ["**Offense maneuvers**"]
        for maneuver in sorted(
            self.maneuver_catalog.offense,
            key=lambda item: item.rank,
        ):
            lines.append(
                f"- **{maneuver.name}** (defeats {maneuver.defeats}): "
                f"{maneuver.effect}"
            )
        lines.append("")
        lines.append("**Defense maneuvers**")
        for maneuver in sorted(
            self.maneuver_catalog.defense,
            key=lambda item: item.rank,
        ):
            lines.append(
                f"- **{maneuver.name}** (defeats {maneuver.defeats}): "
                f"{maneuver.effect}"
            )
        return "\n".join(lines)

    async def begin_maneuver_action_selection(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        Kick off the simultaneous maneuver-action clash once a
        challenger has been chosen: Dinky AI rolls immediately, and any
        human side gets a prompt to open their private maneuver menu.
        """
        if (
            game.is_solo_game
            and self.possession_player_number(game, match) == 2
        ):
            match.choose_offense_maneuver(
                self.choose_ai_maneuver_action("offense")
            )
        if (
            game.is_solo_game
            and self.defending_player_number(game, match) == 2
        ):
            match.choose_defense_maneuver(
                self.choose_ai_maneuver_action("defense")
            )

        game.match_state = match.to_dict()
        save_games(self.games)

        if (
            match.offense_maneuver is not None
            and match.defense_maneuver is not None
        ):
            await self.resolve_maneuver_clash(interaction, game, match)
            return

        waiting_on = []
        if match.offense_maneuver is None:
            waiting_on.append(
                format_player_with_team(
                    game,
                    self.possession_player_number(game, match),
                    mention=True,
                )
            )
        if match.defense_maneuver is None:
            waiting_on.append(
                format_player_with_team(
                    game,
                    self.defending_player_number(game, match),
                    mention=True,
                )
            )

        prompt_message = await interaction.followup.send(
            f"{' and '.join(waiting_on)}, choose your maneuver using the "
            "button below. Your options will be shown privately.",
            view=ManeuverActionPromptView(self, game.game_id),
            wait=True,
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False,
            ),
        )
        game.turn_message_id = prompt_message.id
        save_games(self.games)

    async def resolve_maneuver_clash(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        offense_name = match.offense_maneuver
        defense_name = match.defense_maneuver
        offense_number = self.possession_player_number(game, match)
        defense_number = self.defending_player_number(game, match)
        offense_display = format_player_with_team(game, offense_number)
        defense_display = format_player_with_team(game, defense_number)

        reveal = (
            f"{offense_display} chose **{offense_name}**.\n"
            f"{defense_display} chose **{defense_name}**."
        )

        outcome = self.maneuver_catalog.resolve(offense_name, defense_name)

        if outcome != "tie":
            winner_name = (
                offense_name if outcome == "offense" else defense_name
            )
            winner_number = (
                offense_number if outcome == "offense" else defense_number
            )
            winner_mention = format_player_with_team(
                game,
                winner_number,
                mention=True,
            )
            catalog_by_name = (
                self.maneuver_catalog.offense_by_name()
                if outcome == "offense"
                else self.maneuver_catalog.defense_by_name()
            )
            winner_definition = catalog_by_name[winner_name]

            match.reset_maneuver()
            game.match_state = match.to_dict()
            save_games(self.games)

            await interaction.followup.send(
                f"{reveal}\n\n"
                f"**{winner_name}** wins! {winner_mention}, resolve the "
                f"effect:\n{winner_definition.effect}",
                allowed_mentions=discord.AllowedMentions(
                    users=True,
                    roles=False,
                    everyone=False,
                ),
            )
            await self.refresh_match_image(interaction, game)
            return

        match.add_exhaustion(match.active_player_id, 1)
        match.add_exhaustion(match.challenger_id, 1)
        game.match_state = match.to_dict()
        save_games(self.games)

        offense_player = self.get_player_definition(match.active_player_id)
        defense_player = self.get_player_definition(match.challenger_id)
        offense_skill = self.player_catalog.effective_profile(
            offense_player,
        ).offense
        defense_skill = self.player_catalog.effective_profile(
            defense_player,
        ).defense
        exhaust_emoji = get_exhaust_emoji(interaction.client)

        content = (
            f"{reveal}\n\n"
            f"**{offense_name}** ties with **{defense_name}** — skill "
            "test!\n\n"
            f"{format_role_bracket(offense_player)}: offense skill "
            f"{offense_skill}\n"
            f"{format_role_bracket(defense_player)}: defense skill "
            f"{defense_skill}\n\n"
            f"Both players gain an exhaustion token {exhaust_emoji}.\n\n"
            "Either player can roll:"
        )
        test_message = await interaction.followup.send(
            content,
            view=SkillTestView(self, game.game_id),
            wait=True,
        )
        game.turn_message_id = test_message.id
        save_games(self.games)
        await self.refresh_match_image(interaction, game)

    async def refresh_maneuver_prompt(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
    ) -> None:
        """
        Re-render the public "choose your maneuver" prompt after one
        side picks, so the button for the side that already chose
        disappears.
        """
        if game.turn_message_id is None or interaction.channel is None:
            return

        refreshed_view = ManeuverActionPromptView(self, game.game_id)

        try:
            prompt_message = interaction.channel.get_partial_message(
                game.turn_message_id,
            )
            if refreshed_view.children:
                await prompt_message.edit(view=refreshed_view)
            else:
                await prompt_message.edit(
                    content="Both sides have chosen their maneuvers.",
                    view=None,
                )
        except (discord.NotFound, discord.HTTPException):
            pass

    def build_challenge_announcement(
        self,
        client: discord.Client,
        game: D12BallGame,
        match: MatchState,
        defender_id: str,
        distance: int,
    ) -> str:
        defender = self.get_player_definition(defender_id)
        handler = self.get_player_definition(match.active_player_id)
        defender_number = self.defending_player_number(game, match)
        defender_display = format_player_with_team(game, defender_number)

        announcement = (
            f"{defender_display} has chosen "
            f"{format_role_bracket(defender)} to challenge "
            f"{format_role_bracket(handler)} from the other team "
            "who is handling the ball."
        )

        if distance > 0:
            exhaust_emoji = get_exhaust_emoji(client)
            space_word = "space" if distance == 1 else "spaces"
            token_word = "token" if distance == 1 else "tokens"
            announcement += (
                f"\n\n{defender.name} has moved {distance} {space_word} "
                f"and will gain {distance} exhaustion {token_word} "
                f"{exhaust_emoji * distance}"
            )

        return announcement

    async def refresh_match_image(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
    ) -> None:
        """
        Re-render the persistent board image after the match state
        changes outside of the interaction that owns that message.
        """
        if game.message_id is None or interaction.channel is None:
            return

        try:
            board_message = interaction.channel.get_partial_message(
                game.message_id,
            )
            await board_message.edit(
                attachments=[self.build_match_file(game)],
            )
        except (discord.NotFound, discord.HTTPException):
            pass

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

    async def play_ai_turn(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        Play out Dinky AI's turn with possession: pick a ball handler,
        then shoot if the ball is already on the space closest to the
        opponent's goal, otherwise always maneuver.
        """
        handler_id = self.choose_ai_ball_handler(match)
        match.select_ball_handler(handler_id)
        handler = self.get_player_definition(handler_id)
        action = self.choose_ai_action(match)

        if action == "shoot":
            match.pending_action = "shoot"
            game.match_state = match.to_dict()
            save_games(self.games)

            turn_message = await interaction.followup.send(
                f"Dinky AI has {format_role_bracket(handler)} shoot "
                "to score.",
                wait=True,
            )
            game.turn_message_id = turn_message.id
            save_games(self.games)
            return

        eligible_challengers = match.eligible_challengers()
        if not eligible_challengers:
            game.match_state = match.to_dict()
            save_games(self.games)

            turn_message = await interaction.followup.send(
                f"Dinky AI has {format_role_bracket(handler)} maneuver, "
                "but the defending team has no player in the ball's "
                "zone to challenge.",
                wait=True,
            )
            game.turn_message_id = turn_message.id
            save_games(self.games)
            return

        match.pending_action = "maneuver"
        game.match_state = match.to_dict()
        save_games(self.games)

        defender_number = self.defending_player_number(game, match)
        defender_mention = format_player_with_team(
            game,
            defender_number,
            mention=True,
        )

        challenge_view = ManeuverChallengeView(self, game.game_id)
        challenge_message = await interaction.followup.send(
            f"Dinky AI has {format_role_bracket(handler)} maneuver to "
            "keep possession.\n\n"
            f"{defender_mention}, choose which player will maneuver "
            "to challenge for the ball.",
            view=challenge_view,
            wait=True,
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False,
            ),
        )
        game.turn_message_id = challenge_message.id
        save_games(self.games)

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

        offense_number = self.possession_player_number(game, match)
        if game.is_solo_game and offense_number == 2:
            await self.play_ai_turn(interaction, game, match)
            return

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
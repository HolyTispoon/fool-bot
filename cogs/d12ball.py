import io
import random
import re
import traceback
import uuid
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from d12ball.ai import build_ai_strategies, AIStrategy
from d12ball.components import (
    MatchPeriod,
    MatchState,
    PlayerDefinition,
    TeamSetup,
    TeamSide,
    Zone,
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
)
from d12ball.game import (
    AIOpponent,
    CoinFace,
    D12BallGame,
    GameMode,
    GameStatus,
    HomeChoice,
    Team,
)
from d12ball.render import (
    TEAM_COLORS,
    render_dice_row,
    render_maneuver_reference_image,
    render_match_image,
)

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
# Matches the H1/M1/V1-style space labels drawn on the board in render.py.
ZONE_LETTERS = {
    Zone.HOME_GOAL: "H",
    Zone.MIDFIELD: "M",
    Zone.VISITORS_GOAL: "V",
}
BENCH_DESTINATIONS = ("bench", "back_bench")
COIN_EMOJI_NAMES = {
    CoinFace.FORTUNE: "3_gold_fortune",
    CoinFace.DOOM: "3_gold_doom",
}
COIN_EMOJI_FALLBACK = "🪙"

AI_OPPONENT_NAMES = {
    AIOpponent.DINKY: "Dinky AI",
    AIOpponent.DECENT: "Decent AI",
}

# The exhaustion token emoji is uploaded to the application (via the
# Developer Portal's "Emojis" tab, from images/emoji/exhaust.png) and
# looked up here by name using load_condition_emojis below.
EXHAUST_EMOJI_NAME = "exhaust"
# Same deal for the "exhausted" condition; "injured" has no upload yet so
# it just gets a plain fallback emoji.
EXHAUSTED_EMOJI_NAME = "exhausted"
EXHAUSTED_EMOJI_FALLBACK = "🥵"
INJURED_EMOJI_FALLBACK = "🤕"

# Team emoji (a letter in a team-colored ring, images/emoji/team_*.png)
# are uploaded to the application (Developer Portal "Emojis" tab) and
# looked up by name the same way as the exhaust/exhausted emoji above,
# via load_team_emojis below.
TEAM_EMOJI_NAMES = {
    Team.ORANGE: "team_orange",
    Team.TEAL: "team_teal",
    Team.PURPLE: "team_purple",
    Team.SLIME: "team_slime",
}
TEAM_EMOJI_FALLBACKS = {
    Team.ORANGE: "🟠",
    Team.TEAL: "🔵",
    Team.PURPLE: "🟣",
    Team.SLIME: "🟢",
}
EXHAUST_EMOJI_FALLBACK = "😮\u200d💨"


CONDITION_EMOJI_NAMES = {
    "exhaust": EXHAUST_EMOJI_NAME,
    "exhausted": EXHAUSTED_EMOJI_NAME,
}


async def load_condition_emojis(
    bot: commands.Bot,
) -> dict[str, str]:
    """
    Look up the exhaustion-token and exhausted-condition emoji uploaded
    to the application (the Developer Portal's "Emojis" tab), the same
    way load_coin_emojis does.

    Application emoji work in every server the bot is in, but unlike
    guild emoji they are not part of discord.py's `client.emojis`
    cache, so they have to be fetched explicitly.

    Anything that goes wrong here just leaves a condition out of the
    mapping and callers fall back to a plain emoji.
    """
    try:
        emojis = await bot.fetch_application_emojis()
    except Exception as error:
        print(f"Could not load the D12 Ball condition emoji: {error}")
        return {}

    emojis_by_name = {emoji.name: emoji for emoji in emojis}
    condition_emojis: dict[str, str] = {}
    missing: list[str] = []

    for key, name in CONDITION_EMOJI_NAMES.items():
        emoji = emojis_by_name.get(name)

        if emoji is None:
            missing.append(name)
        else:
            condition_emojis[key] = str(emoji)

    if missing:
        print(
            "This application has no condition emoji named "
            f"{', '.join(missing)}; those conditions will show their "
            "fallback emoji instead."
        )

    return condition_emojis


def get_exhaust_emoji(condition_emojis: dict[str, str]) -> str:
    return condition_emojis.get("exhaust", EXHAUST_EMOJI_FALLBACK)


def get_exhausted_emoji(condition_emojis: dict[str, str]) -> str:
    return condition_emojis.get("exhausted", EXHAUSTED_EMOJI_FALLBACK)


async def load_team_emojis(
    bot: commands.Bot,
) -> dict[Team, str]:
    """
    Look up the team-letter emoji uploaded to the application (the
    Developer Portal's "Emojis" tab), the same way load_coin_emojis
    and load_condition_emojis do.
    """
    try:
        emojis = await bot.fetch_application_emojis()
    except Exception as error:
        print(f"Could not load the D12 Ball team emoji: {error}")
        return {}

    emojis_by_name = {emoji.name: emoji for emoji in emojis}
    team_emojis: dict[Team, str] = {}
    missing: list[str] = []

    for team, name in TEAM_EMOJI_NAMES.items():
        emoji = emojis_by_name.get(name)

        if emoji is None:
            missing.append(name)
        else:
            team_emojis[team] = str(emoji)

    if missing:
        print(
            "This application has no team emoji named "
            f"{', '.join(missing)}; those teams will show a colored "
            "circle instead."
        )

    return team_emojis


def get_team_emoji(team_emojis: dict[Team, str], team: Team) -> str:
    return team_emojis.get(team, TEAM_EMOJI_FALLBACKS[team])


def format_ai_name(ai_opponent: Optional[AIOpponent]) -> str:
    return AI_OPPONENT_NAMES[ai_opponent or AIOpponent.DINKY]


def format_role_bracket(
    player: PlayerDefinition,
    team_emojis: dict[Team, str],
) -> str:
    initials = ROLE_INITIALS[player.role.value]
    team_emoji = get_team_emoji(team_emojis, player.team)
    return f"{team_emoji} {player.name} [{initials}]"


def destination_display_name(destination: str) -> str:
    if destination in BENCH_DESTINATIONS:
        return destination.replace("_", " ").title()
    return Zone(destination).value.replace("_", " ").title()


def format_team_side_label(setup) -> str:
    return f"{setup.team.value.title()} ({setup.side.value.title()})"


def space_label(zone: Zone, space_index: int) -> str:
    return f"{ZONE_LETTERS[zone]}{space_index + 1}"


def space_choices(match: MatchState) -> list[tuple[str, str]]:
    """
    (value, label) pairs for every board space, e.g. ("home_goal:0", "H1").
    """
    return [
        (f"{zone.value}:{space_index}", space_label(zone, space_index))
        for zone in Zone
        for space_index in range(len(match.board.spaces[zone]))
    ]


def parse_space_value(value: str) -> tuple[Zone, int]:
    zone_value, _, space_index = value.partition(":")
    if not space_index:
        raise ValueError(f"\"{value}\" is not a valid board space.")
    try:
        return Zone(zone_value), int(space_index)
    except ValueError as error:
        raise ValueError(f"\"{value}\" is not a valid board space.") from error


def resolve_adjustable_value(
    raw: Optional[str],
    current: int,
    minimum: int,
    maximum: int,
) -> int:
    """
    Interpret a speed/score/time-style value field: a plain integer sets
    the value directly, "+N"/"-N" adjusts it relative to the current
    value, and leaving it blank bumps it by one. The result is clamped
    to [minimum, maximum].
    """
    if raw is None or not raw.strip():
        target = current + 1
    else:
        raw = raw.strip()
        try:
            delta_or_value = int(raw)
        except ValueError as error:
            raise ValueError(
                f"\"{raw}\" is not a whole number."
            ) from error
        target = (
            current + delta_or_value
            if raw[0] in "+-"
            else delta_or_value
        )

    return max(minimum, min(maximum, target))


def filter_choices(
    current: str,
    options: list[tuple[str, str]],
) -> list[app_commands.Choice[str]]:
    """
    Narrow (value, label) autocomplete options to those matching the
    text typed so far, capped at Discord's 25-choice limit.
    """
    needle = current.strip().casefold()
    matches = [
        (value, label)
        for value, label in options
        if needle in label.casefold()
    ]
    return [
        app_commands.Choice(name=label, value=value)
        for value, label in matches[:25]
    ]


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
            f"a random team will be assigned to {format_ai_name(game.ai_opponent)} "
            "of the remaining teams."
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
            return format_ai_name(game.ai_opponent)
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

        if game.is_solo_game and game.coin_winner_player_number == 2:
            ai_side = "Home" if game.home_player_number == 2 else "Visiting"
            text += (
                f"\n\n{format_ai_name(game.ai_opponent)} has chosen to "
                f"play as **{ai_side}**."
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


async def send_error_fallback(
    interaction: discord.Interaction,
    message: str,
) -> None:
    """
    Best-effort ephemeral notice for an interaction that failed with an
    unexpected exception (e.g. a dropped connection), so a player sees
    something instead of their click or command silently doing nothing.
    """
    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(
                message,
                ephemeral=True,
            )
    except discord.HTTPException:
        pass


class SafeView(discord.ui.View):
    """
    Base class for every D12 Ball view. discord.py's default behavior
    for an uncaught exception in a button/select callback is to log it
    and otherwise do nothing, which leaves the click looking like it
    had no effect at all. This surfaces a message instead.
    """

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
        item: discord.ui.Item,
    ) -> None:
        print(f"Unhandled error in {self!r} for {item!r}: {error!r}")
        traceback.print_exception(type(error), error, error.__traceback__)
        await send_error_fallback(
            interaction,
            "Something went wrong handling that click. Please try again.",
        )


class GameConfigurationView(SafeView):
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

        if game is None or not game.is_solo_game:
            return

        selected_ai = game.ai_opponent or AIOpponent.DINKY

        for ai_type, label in AI_OPPONENT_NAMES.items():
            button = discord.ui.Button(
                label=label,
                style=(
                    discord.ButtonStyle.secondary
                    if ai_type == selected_ai
                    else discord.ButtonStyle.primary
                ),
                custom_id=(
                    f"d12ball:ai_opponent:{self.game_id}:{ai_type.value}"
                ),
                disabled=configuration_closed or ai_type == selected_ai,
                row=3,
            )

            async def ai_opponent_callback(
                interaction: discord.Interaction,
                selected_ai_type: AIOpponent = ai_type,
            ) -> None:
                await self.select_ai_opponent(interaction, selected_ai_type)

            button.callback = ai_opponent_callback
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

    async def select_ai_opponent(
        self,
        interaction: discord.Interaction,
        selected_ai_type: AIOpponent,
    ) -> None:
        game = await self.validate_configuration_change(interaction)
        if game is None:
            return

        if selected_ai_type == AIOpponent.DECENT:
            await interaction.response.send_message(
                "Decent AI is not yet ready, please play against Dinky AI.",
                ephemeral=True,
            )
            return

        game.ai_opponent = AIOpponent.DINKY
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
            ai_choice = self.cog.get_ai_strategy(
                game,
            ).choose_home_or_visiting()
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


class HomeAwaySelectionView(SafeView):
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


class BallHandlerSelectionView(SafeView):
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


class PlayerActionView(SafeView):
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

        if action == "shoot":
            match.pending_action = "shoot"
            game.match_state = match.to_dict()
            save_games(self.cog.games)

            refresh_player_names(game, interaction.guild)
            handler = self.cog.get_player_definition(match.active_player_id)
            offense_number = self.cog.possession_player_number(game, match)
            offense_display = format_player_with_team(game, offense_number)

            await interaction.response.edit_message(
                content=(
                    f"{offense_display} has chosen to {action_label} with "
                    f"{format_role_bracket(handler, self.cog.team_emojis)}."
                ),
                view=None,
            )
            await self.cog.begin_score_attempt(interaction, game, match)
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
        offense_number = self.cog.possession_player_number(game, match)

        if game.is_solo_game and defender_number == 2:
            challenger_id = self.cog.get_ai_strategy(game).choose_challenger(
                match
            )
            distance = match.choose_challenger(challenger_id)
            game.match_state = match.to_dict()
            save_games(self.cog.games)

            refresh_player_names(game, interaction.guild)
            offense_display = format_player_with_team(game, offense_number)

            await interaction.response.edit_message(
                content=(
                    f"{offense_display} has chosen to {action_label} with "
                    f"{format_role_bracket(handler, self.cog.team_emojis)}."
                ),
                view=None,
            )
            await interaction.followup.send(
                self.cog.build_challenge_announcement(
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
        offense_display = format_player_with_team(game, offense_number)
        defender_mention = format_player_with_team(
            game,
            defender_number,
            mention=True,
        )

        await interaction.response.edit_message(
            content=(
                f"{offense_display} has chosen to {action_label} with "
                f"{format_role_bracket(handler, self.cog.team_emojis)}.\n\n"
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


class ManeuverChallengeView(SafeView):
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


class ManeuverActionPromptView(SafeView):
    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
    ):
        super().__init__(timeout=None)

        self.cog = cog
        self.game_id = game_id

        button = discord.ui.Button(
            label="Choose Your Maneuver",
            style=discord.ButtonStyle.primary,
            custom_id=f"d12ball:maneuver_prompt:{game_id}",
        )
        button.callback = self.open_action_menu
        self.add_item(button)

    async def open_action_menu(
        self,
        interaction: discord.Interaction,
    ) -> None:
        """
        One shared button for both sides: which ephemeral menu opens
        depends only on who clicked, so nobody has to pick "which
        button is mine" first.
        """
        game = self.cog.games.get(self.game_id)
        if game is None or game.match_state is None:
            await interaction.response.send_message(
                "I could not find the saved data for this game.",
                ephemeral=True,
            )
            return

        match = self.cog.load_match_state(game)
        is_offense_player = self.cog.user_controls_possession(
            interaction.user.id,
            game,
            match,
        )
        is_defense_player = self.cog.user_controls_defense(
            interaction.user.id,
            game,
            match,
        )

        if match.offense_maneuver is None and is_offense_player:
            side = "offense"
        elif match.defense_maneuver is None and is_defense_player:
            side = "defense"
        elif is_offense_player or is_defense_player:
            await interaction.response.send_message(
                "You have already chosen your maneuver.",
                ephemeral=True,
            )
            return
        else:
            await interaction.response.send_message(
                "Only a player in this game can choose a maneuver.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            content="Pick your maneuver — see the reference image above.",
            view=ManeuverActionSelectView(self.cog, self.game_id, side),
            ephemeral=True,
        )


class ManeuverActionSelectView(SafeView):
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
            await self.cog.resolve_maneuver(interaction, game, match)


class SkillTestView(SafeView):
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
            modifier_note = f" + {modifier} (ball speed modifier)"

        breakdown = (
            f"**{format_role_bracket(offense_player, self.cog.team_emojis)}** (offense): "
            f"rolled {offense_roll} + {offense_skill} (offensive skill "
            f"modifier) = {offense_total}\n"
            f"**{format_role_bracket(defense_player, self.cog.team_emojis)}** (defense): "
            f"rolled {defense_roll} + {defense_skill} (defensive skill "
            f"modifier){modifier_note} = {defense_total}"
        )
        dice_file = discord.File(
            render_dice_row(
                [
                    (
                        offense_roll,
                        TEAM_COLORS[offense_player.team],
                        offense_player.team.value.title(),
                    ),
                    (
                        defense_roll,
                        TEAM_COLORS[defense_player.team],
                        defense_player.team.value.title(),
                    ),
                ]
            ),
            filename="skill_test_dice.png",
        )

        if offense_total == defense_total:
            match.add_exhaustion(match.active_player_id, 1)
            match.add_exhaustion(match.challenger_id, 1)
            game.match_state = match.to_dict()
            save_games(self.cog.games)

            exhaustion_text = "\n".join(
                [
                    self.cog.describe_exhaustion_gain(
                        match,
                        match.active_player_id,
                        1,
                    ),
                    self.cog.describe_exhaustion_gain(
                        match,
                        match.challenger_id,
                        1,
                    ),
                ]
            )
            await interaction.response.edit_message(
                content=(
                    f"{breakdown}\n\n"
                    f"Another tie!\n{exhaustion_text}\n\nRoll again:"
                ),
                attachments=[dice_file],
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

        exhausted_participants = [
            player
            for player in (offense_player, defense_player)
            if player.player_id in match.exhausted
        ]

        match.reset_maneuver()
        game.match_state = match.to_dict()
        save_games(self.cog.games)

        await interaction.response.edit_message(
            content=(
                f"{breakdown}\n\n"
                f"**{winner_name}** wins the skill test! {winner_mention}, "
                f"resolve the effect:\n{winner_definition.effect}"
            ),
            attachments=[dice_file],
            view=None,
        )
        await self.cog.refresh_match_image(interaction, game)

        for player in exhausted_participants:
            await self.cog.run_injury_test(interaction, game, match, player)


class ScoreAttemptView(SafeView):
    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
    ):
        super().__init__(timeout=None)

        self.cog = cog
        self.game_id = game_id

        button = discord.ui.Button(
            label="Roll the score attempt",
            style=discord.ButtonStyle.danger,
            custom_id=f"d12ball:score_attempt:{game_id}",
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
        if match.pending_action != "shoot" or match.active_player_id is None:
            await interaction.response.send_message(
                "This score attempt is no longer active.",
                ephemeral=True,
            )
            return

        participant_ids = {game.player_1_id}
        if game.player_2_id is not None:
            participant_ids.add(game.player_2_id)

        if interaction.user.id not in participant_ids:
            await interaction.response.send_message(
                "Only a player in this game can roll the score attempt.",
                ephemeral=True,
            )
            return

        shooter = self.cog.get_player_definition(match.active_player_id)
        offense_skill = self.cog.player_catalog.effective_profile(
            shooter,
        ).offense
        speed_modifier = match.ball.speed // 2
        defenders = self.cog.intervening_defenders(match)
        defense_skill_total = sum(skill for _, skill in defenders)

        attacking_setup = match.setup_for_side(match.ball.possession)
        defending_setup = match.setup_for_side(match.defending_side())

        # Two dice, one per human: the attacker adds the shooting
        # player's offensive skill and the ball-speed modifier, the
        # defence adds the defensive skill of every meeple in the way.
        attack_roll = random.randint(1, 12)
        defense_roll = random.randint(1, 12)
        attack_total = attack_roll + offense_skill + speed_modifier
        defense_total = defense_roll + defense_skill_total

        speed_note = ""
        if speed_modifier:
            speed_note = f" + {speed_modifier} (ball speed modifier)"
        defense_source = (
            f"{defense_skill_total} (defensive skill in the way)"
            if defenders
            else "0 (nobody in the way)"
        )
        breakdown = (
            f"**{format_role_bracket(shooter, self.cog.team_emojis)}** "
            f"(attack): rolled {attack_roll} + {offense_skill} (offensive "
            f"skill modifier){speed_note} = {attack_total}\n"
            f"**{format_team_side_label(defending_setup)}** (defense): "
            f"rolled {defense_roll} + {defense_source} = {defense_total}"
        )
        dice_file = discord.File(
            render_dice_row(
                [
                    (
                        attack_roll,
                        TEAM_COLORS[attacking_setup.team],
                        attacking_setup.team.value.title(),
                    ),
                    (
                        defense_roll,
                        TEAM_COLORS[defending_setup.team],
                        defending_setup.team.value.title(),
                    ),
                ]
            ),
            filename="score_attempt_dice.png",
        )

        scored = attack_total >= defense_total
        if scored:
            match.award_goal()
            verdict = (
                f"**GOAL!** "
                f"{format_role_bracket(shooter, self.cog.team_emojis)} scores "
                f"for {format_team_side_label(attacking_setup)}!\n"
                f"{match.home.team.value.title()} "
                f"{match.scoreboard.home_score}:"
                f"{match.scoreboard.visiting_score} "
                f"{match.visiting.team.value.title()}"
            )
        else:
            verdict = (
                "**Missed attempt.** "
                f"{format_team_side_label(defending_setup)} keeps the goal "
                "intact."
            )
        cleanup = self.cog.build_score_attempt_cleanup(match, scored)

        # A plain score attempt costs no exhaustion and owes no injury
        # check: the author has confirmed only a shot taken off a set-up
        # gains a token, and injury checks stay exclusive to skill
        # tests. Set-ups are not built yet, so nothing accrues here.
        match.reset_maneuver()
        game.match_state = match.to_dict()
        save_games(self.cog.games)

        await interaction.response.edit_message(
            content=f"{breakdown}\n\n{verdict}\n\n{cleanup}",
            attachments=[dice_file],
            view=None,
        )
        await self.cog.refresh_match_image(interaction, game)


class D12Ball(commands.GroupCog, group_name="d12ball"):
    ball_group = app_commands.Group(
        name="ball",
        description="Move the ball and manage possession, speed.",
    )
    meeple_group = app_commands.Group(
        name="meeple",
        description="Move meeples on the board.",
    )

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.games = load_games()
        self.player_catalog = load_player_catalog()
        self.basic_ruleset = load_basic_ruleset()
        self.maneuver_catalog = load_maneuver_catalog()
        self.maneuver_reference_image_bytes = render_maneuver_reference_image(
            self.maneuver_catalog
        ).read()
        self.coin_emojis: dict[CoinFace, str] = {}
        self.condition_emojis: dict[str, str] = {}
        self.team_emojis: dict[Team, str] = {}
        self.ai_strategies = build_ai_strategies(
            self.player_catalog,
            self.maneuver_catalog,
        )

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
                elif match.pending_action == "shoot":
                    turn_view = ScoreAttemptView(self, game.game_id)
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
        self.condition_emojis = await load_condition_emojis(self.bot)
        self.team_emojis = await load_team_emojis(self.bot)

    async def cog_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        """
        Catch-all for exceptions raised anywhere in a /d12ball command
        (including group subcommands like /d12ball ball move) that
        weren't already handled as an expected ValueError, e.g. a
        dropped connection to Discord. Without this, discord.py just
        logs it and the command looks like it silently did nothing.
        """
        original = getattr(error, "original", error)
        command_name = (
            interaction.command.qualified_name
            if interaction.command is not None
            else "unknown command"
        )
        print(f"Unhandled error in /{command_name}: {original!r}")
        traceback.print_exception(
            type(original), original, original.__traceback__,
        )
        await send_error_fallback(
            interaction,
            "Something went wrong running that command. Please try again.",
        )

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

    def game_for_channel(self, channel_id: int) -> Optional[D12BallGame]:
        for game in self.games.values():
            if game.channel_id == channel_id:
                return game
        return None

    def side_for_user(
        self,
        game: D12BallGame,
        user_id: int,
    ) -> Optional[TeamSide]:
        """
        Which side (home/visiting) a Discord user controls in this
        game, or None if they are not one of its two players, or the
        home/visiting assignment has not been made yet.
        """
        if not game.home_and_visiting_selected:
            return None

        if user_id == game.player_1_id:
            player_number = 1
        elif game.player_2_id is not None and user_id == game.player_2_id:
            player_number = 2
        else:
            return None

        if player_number == game.home_player_number:
            return TeamSide.HOME
        if player_number == game.visiting_player_number:
            return TeamSide.VISITING
        return None

    async def defer_and_get_match(
        self,
        interaction: discord.Interaction,
    ) -> Optional[tuple[D12BallGame, MatchState]]:
        """
        Defer the interaction and load the game/match tied to the
        current channel, replying with an ephemeral error and
        returning None when there isn't one to work with.
        """
        await interaction.response.defer()

        game = self.game_for_channel(interaction.channel_id)
        if game is None or game.match_state is None:
            await interaction.followup.send(
                "There is no D12 Ball match in progress in this channel.",
                ephemeral=True,
            )
            return None

        match = self.load_match_state(game)
        return game, match

    def get_player_definition(
        self,
        player_id: str,
    ) -> PlayerDefinition:
        return self.player_catalog.player_by_id(player_id)

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

    def get_ai_strategy(self, game: D12BallGame) -> AIStrategy:
        return self.ai_strategies[game.ai_opponent or AIOpponent.DINKY]

    def build_maneuver_reference_file(self) -> discord.File:
        return discord.File(
            io.BytesIO(self.maneuver_reference_image_bytes),
            filename="maneuver_reference.png",
        )

    def intervening_defenders(
        self,
        match: MatchState,
    ) -> list[tuple[PlayerDefinition, int]]:
        """
        Every defending player between the ball and the goal it is being
        shot at, each paired with the defensive skill they add to the
        defence's side of a score attempt.
        """
        defenders = []
        for player_id in match.defenders_between_ball_and_goal():
            player = self.get_player_definition(player_id)
            defense = self.player_catalog.effective_profile(player).defense
            defenders.append((player, defense))
        return defenders

    async def begin_score_attempt(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        Post what the score attempt is made of, then the roll prompt.
        The composition is a permanent message of its own so the numbers
        that fed the roll survive the prompt being edited into a result.
        """
        shooter = self.get_player_definition(match.active_player_id)
        offense_skill = self.player_catalog.effective_profile(
            shooter,
        ).offense
        speed_modifier = match.ball.speed // 2
        defenders = self.intervening_defenders(match)
        defense_skill_total = sum(skill for _, skill in defenders)
        defending_setup = match.setup_for_side(match.defending_side())

        attack_line = f"offensive skill {offense_skill}"
        if speed_modifier:
            attack_line += (
                f", plus {speed_modifier} for a ball speed of "
                f"{match.ball.speed}"
            )

        if defenders:
            defense_line = (
                ", ".join(
                    f"{format_role_bracket(player, self.team_emojis)} "
                    f"{skill}"
                    for player, skill in defenders
                )
                + f" -- {defense_skill_total} in total"
            )
        else:
            defense_line = (
                "nobody is in the way, so the defence rolls a bare d12"
            )

        await interaction.followup.send(
            "**Score attempt** -- "
            f"{format_role_bracket(shooter, self.team_emojis)} shoots from "
            f"{space_label(match.ball.zone, match.ball.space_index)} at the "
            f"{format_team_side_label(defending_setup)} goal.\n\n"
            f"Attack: {attack_line}\n"
            f"Defence: {defense_line}\n\n"
            "Both sides roll one d12. The attacker scores on a total equal "
            "to or higher than the defence.",
            allowed_mentions=discord.AllowedMentions(
                users=False,
                roles=False,
                everyone=False,
            ),
        )

        prompt_message = await interaction.followup.send(
            "Either player can roll:",
            view=ScoreAttemptView(self, game.game_id),
            wait=True,
        )
        game.turn_message_id = prompt_message.id
        save_games(self.games)

    def build_score_attempt_cleanup(
        self,
        match: MatchState,
        scored: bool,
    ) -> str:
        """
        The cleanup a resolved score attempt still calls for, as
        instructions rather than state changes. A goal itself is applied
        -- it is a bare increment with no threshold behind it -- but the
        clock advance wants deciding for maneuvers at the same time, and
        the restart is gated on the run back, so those stay with the
        players. Maneuver effects are hand-applied the same way.
        """
        defending_setup = match.setup_for_side(match.defending_side())
        space_minutes = match.spaces_to_goal()
        minute_word = "minute" if space_minutes == 1 else "minutes"

        steps = [
            f"The clock advances {space_minutes} space {minute_word} "
            "-- `/d12ball time`"
        ]

        if scored:
            # The restart space follows the same board-size rule as the
            # kickoff: the middle of the board on 7 and 9, and on a
            # 6-board the midfield space nearer the restarting team's
            # own goal.
            if match.board.layout.board_size == 6:
                restart = "on the midfield space nearer their own goal"
            else:
                restart = "in the middle of the board"
        else:
            restart = "on the space closest to their own goal"
        steps.append(
            f"Turnover to {format_team_side_label(defending_setup)}, "
            f"restarting with the ball {restart} "
            "-- `/d12ball ball move`"
        )
        steps.append(
            "Players run back to their assigned zones, no more than one "
            "per space per team, gaining one exhaust token per space "
            "traveled -- `/d12ball meeple move`"
        )

        return (
            "Cleanup -- apply by hand:\n"
            + "\n".join(f"- {step}" for step in steps)
            + "\n\nThen `/d12ball offensive_choice` for the next turn."
        )

    async def begin_maneuver_action_selection(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        Kick off the simultaneous maneuver-action choice once a
        challenger has been chosen: the AI opponent rolls immediately,
        and any human side gets a prompt to open their private
        maneuver menu.
        """
        if game.is_solo_game:
            ai_strategy = self.get_ai_strategy(game)

            if self.possession_player_number(game, match) == 2:
                match.choose_offense_maneuver(
                    ai_strategy.choose_maneuver_action("offense")
                )
            if self.defending_player_number(game, match) == 2:
                match.choose_defense_maneuver(
                    ai_strategy.choose_maneuver_action("defense")
                )

        game.match_state = match.to_dict()
        save_games(self.games)

        if (
            match.offense_maneuver is not None
            and match.defense_maneuver is not None
        ):
            await self.resolve_maneuver(interaction, game, match)
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
            f"{' and '.join(waiting_on)}, both sides will now choose a "
            "maneuver privately. See the reference below for all six "
            "maneuvers, then use the button to make your pick.",
            file=self.build_maneuver_reference_file(),
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

    async def resolve_maneuver(
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

        # This reveal is a permanent message, separate from the roll
        # prompt below, so it survives every re-roll intact instead of
        # being edited away.
        await interaction.followup.send(
            f"{reveal}\n\n"
            f"**{offense_name}** ties with **{defense_name}** — skill "
            "test!\n\n"
            f"{format_role_bracket(offense_player, self.team_emojis)}: offense skill "
            f"{offense_skill}\n"
            f"{format_role_bracket(defense_player, self.team_emojis)}: defense skill "
            f"{defense_skill}\n\n"
            + self.describe_exhaustion_gain(
                match, match.active_player_id, 1,
            )
            + "\n"
            + self.describe_exhaustion_gain(
                match, match.challenger_id, 1,
            ),
            allowed_mentions=discord.AllowedMentions(
                users=False,
                roles=False,
                everyone=False,
            ),
        )
        await self.refresh_match_image(interaction, game)

        test_message = await interaction.followup.send(
            "Either player can roll:",
            view=SkillTestView(self, game.game_id),
            wait=True,
        )
        game.turn_message_id = test_message.id
        save_games(self.games)

    async def run_injury_test(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        player: PlayerDefinition,
    ) -> None:
        """
        Automatic injury test for a player who was already exhausted
        going into a skill test they just took part in: roll a d12,
        and if it doesn't beat their current exhaustion token count,
        they become injured.
        """
        roll = random.randint(1, 12)
        current_tokens = match.exhaustion.get(player.player_id, 0)
        dice_file = discord.File(
            render_dice_row(
                [
                    (
                        roll,
                        TEAM_COLORS[player.team],
                        player.team.value.title(),
                    )
                ]
            ),
            filename="injury_test_die.png",
        )

        if roll > current_tokens:
            content = (
                f"{format_role_bracket(player, self.team_emojis)} is exhausted and rolls "
                f"an injury test: {roll} beats their {current_tokens} "
                "exhaustion tokens — safe."
            )
        else:
            match.mark_injured(player.player_id)
            game.match_state = match.to_dict()
            save_games(self.games)

            content = (
                f"{format_role_bracket(player, self.team_emojis)} is exhausted and rolls "
                f"an injury test: {roll} does not beat their "
                f"{current_tokens} exhaustion tokens — injury! "
                f"{format_role_bracket(player, self.team_emojis)} now has the condition "
                f"**injured** {INJURED_EMOJI_FALLBACK}."
            )
            await self.refresh_match_image(interaction, game)

        await interaction.followup.send(content, file=dice_file)

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

    def describe_exhaustion_gain(
        self,
        match: MatchState,
        player_id: str,
        amount: int,
    ) -> str:
        """
        Text describing an exhaustion-token gain that has already been
        applied to `match` — the running total, plus a line the moment
        it pushes the player's token count past their defense skill.
        """
        player = self.get_player_definition(player_id)
        exhaust_emoji = get_exhaust_emoji(self.condition_emojis)
        total = match.exhaustion.get(player_id, 0)
        token_word = "token" if amount == 1 else "tokens"
        text = (
            f"{format_role_bracket(player, self.team_emojis)} gains {amount} exhaustion "
            f"{token_word} {exhaust_emoji * amount} (now {total} total)."
        )

        defense_skill = self.player_catalog.effective_profile(player).defense
        if match.mark_exhausted_if_needed(player_id, defense_skill):
            exhausted_emoji = get_exhausted_emoji(self.condition_emojis)
            text += (
                f"\n{format_role_bracket(player, self.team_emojis)} now has the condition "
                f"**exhausted** {exhausted_emoji} — {total} exhaustion "
                f"tokens exceeds their defense skill of {defense_skill}."
            )
        return text

    def build_challenge_announcement(
        self,
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
            f"{format_role_bracket(defender, self.team_emojis)} to challenge "
            f"{format_role_bracket(handler, self.team_emojis)} from the other team "
            "who is handling the ball."
        )

        if distance > 0:
            space_word = "space" if distance == 1 else "spaces"
            announcement += (
                f"\n\n{defender.name} has moved {distance} {space_word}."
                f"\n{self.describe_exhaustion_gain(match, defender_id, distance)}"
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

    def format_roster_player_with_team(self, player_id: str) -> str:
        player = self.get_player_definition(player_id)
        initials = ROLE_INITIALS[player.role.value]
        return f"{player.name} ({player.team.value.title()}, {initials})"

    def format_team_roster_entry(
        self,
        match: MatchState,
        setup: TeamSetup,
        player_id: str,
    ) -> str:
        player = self.get_player_definition(player_id)
        position = match.board.meeple_position(player_id)
        if position is not None:
            zone, space_index = position
            location = (
                f"{destination_display_name(zone.value)} "
                f"({space_label(zone, space_index)})"
            )
        elif player_id in setup.player_board.bench:
            location = destination_display_name("bench")
        else:
            location = destination_display_name("back_bench")

        tokens = match.exhaustion.get(player_id, 0)
        token_word = "token" if tokens == 1 else "tokens"

        conditions = []
        if player_id in match.exhausted:
            conditions.append(
                f"exhausted {get_exhausted_emoji(self.condition_emojis)}"
            )
        if player_id in match.injured:
            conditions.append(f"injured {INJURED_EMOJI_FALLBACK}")

        entry = (
            f"{format_role_bracket(player, self.team_emojis)} — {location} — "
            f"{tokens} exhaustion {token_word} "
            f"{get_exhaust_emoji(self.condition_emojis)}"
        )
        if conditions:
            entry += f" — {', '.join(conditions)}"
        return entry

    def build_team_roster_section(
        self,
        match: MatchState,
        setup: TeamSetup,
    ) -> str:
        roster = self.player_catalog.teams[setup.team].players
        lines = [
            self.format_team_roster_entry(
                match, setup, player.player_id,
            )
            for player in roster
        ]
        return f"**{format_team_side_label(setup)}**\n" + "\n".join(lines)

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
        Play out the AI opponent's turn with possession: pick a ball
        handler, then shoot if the ball is already on the space
        closest to the opponent's goal, otherwise always maneuver.
        """
        ai_name = format_ai_name(game.ai_opponent)
        ai_strategy = self.get_ai_strategy(game)
        handler_id = ai_strategy.choose_ball_handler(match)
        match.select_ball_handler(handler_id)
        handler = self.get_player_definition(handler_id)
        action = ai_strategy.choose_action(match)

        if action == "shoot":
            match.pending_action = "shoot"
            game.match_state = match.to_dict()
            save_games(self.games)

            await interaction.followup.send(
                f"{ai_name} has chosen to shoot to score with "
                f"{format_role_bracket(handler, self.team_emojis)}.",
            )
            await self.begin_score_attempt(interaction, game, match)
            return

        eligible_challengers = match.eligible_challengers()
        if not eligible_challengers:
            game.match_state = match.to_dict()
            save_games(self.games)

            turn_message = await interaction.followup.send(
                f"{ai_name} has chosen to maneuver with "
                f"{format_role_bracket(handler, self.team_emojis)}, "
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
            f"{ai_name} has chosen to maneuver with "
            f"{format_role_bracket(handler, self.team_emojis)}.\n\n"
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

    async def announce_board_update(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        message: str,
    ) -> None:
        """
        Confirm a manual board correction (/coach, /ref, /meeple move,
        /ball move/possession/speed, /score, /time) with a fresh
        snapshot attached directly to the reply, in addition to
        keeping the persistent board message in sync.
        """
        await interaction.followup.send(
            message,
            file=self.build_match_file(game),
        )
        await self.refresh_match_image(interaction, game)

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
            ai_opponent=None if player_2 else AIOpponent.DINKY,
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

    @app_commands.command(
        name="show_game",
        description="Post a fresh snapshot of the full board.",
    )
    @app_commands.guild_only()
    async def show_game(
        self,
        interaction: discord.Interaction,
    ) -> None:
        game = self.game_for_channel(interaction.channel_id)
        if game is None or game.match_state is None:
            await interaction.response.send_message(
                "There is no D12 Ball match in progress in this channel.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()
        await interaction.followup.send(file=self.build_match_file(game))

    @app_commands.command(
        name="team_roster",
        description=(
            "List a team's players, positions, exhaustion, and conditions."
        ),
    )
    @app_commands.describe(
        all_teams="Show both teams' rosters instead of just your own.",
    )
    @app_commands.guild_only()
    async def team_roster(
        self,
        interaction: discord.Interaction,
        all_teams: bool = False,
    ) -> None:
        result = await self.defer_and_get_match(interaction)
        if result is None:
            return
        game, match = result

        if all_teams:
            setups = [match.home, match.visiting]
        else:
            side = self.side_for_user(game, interaction.user.id)
            if side is None:
                await interaction.followup.send(
                    "You are not one of the players in this game. Use "
                    "all_teams:true to see both rosters.",
                    ephemeral=True,
                )
                return
            setups = [match.setup_for_side(side)]

        for setup in setups:
            await interaction.followup.send(
                self.build_team_roster_section(match, setup)
            )

    @app_commands.command(
        name="maneuver_reference",
        description=(
            "Post the maneuver reference image showing all six maneuvers."
        ),
    )
    @app_commands.guild_only()
    async def maneuver_reference(
        self,
        interaction: discord.Interaction,
    ) -> None:
        await interaction.response.send_message(
            file=self.build_maneuver_reference_file(),
        )

    @app_commands.command(
        name="offensive_choice",
        description=(
            "(Re-)post the ball-handler and shoot/maneuver choice for "
            "the team in possession."
        ),
    )
    @app_commands.guild_only()
    async def offensive_choice(
        self,
        interaction: discord.Interaction,
    ) -> None:
        result = await self.defer_and_get_match(interaction)
        if result is None:
            return
        game, match = result

        if match.pending_action == "maneuver":
            await interaction.followup.send(
                "A maneuver challenge is already in progress for this "
                "turn.",
                ephemeral=True,
            )
            return

        if match.pending_action == "shoot":
            await interaction.followup.send(
                "A score attempt is already in progress for this turn.",
                ephemeral=True,
            )
            return

        # A ball handler or a maneuver choice may already be recorded
        # from a prior offensive choice whose effect was never resolved
        # into a state change (e.g. an uncontested maneuver). Nothing
        # else advances the match to its next turn, so this command
        # always starts fresh: clear that stale choice and re-derive the
        # ball handler from the board's current occupancy.
        match.reset_maneuver()
        game.match_state = match.to_dict()
        save_games(self.games)

        try:
            await self.send_turn_prompt(interaction, game)
        except ValueError as error:
            await interaction.followup.send(str(error), ephemeral=True)

    @app_commands.command(
        name="coach",
        description=(
            "Move one of your own player cards between zones and benches."
        ),
    )
    @app_commands.describe(
        player_card="One of your team's player cards.",
        destination="Where to move the card: a zone or a bench.",
    )
    @app_commands.guild_only()
    async def coach(
        self,
        interaction: discord.Interaction,
        player_card: str,
        destination: str,
    ) -> None:
        result = await self.defer_and_get_match(interaction)
        if result is None:
            return
        game, match = result

        side = self.side_for_user(game, interaction.user.id)
        if side is None:
            await interaction.followup.send(
                "You are not one of the players in this game. Use "
                "/d12ball ref to move a specific team's card instead.",
                ephemeral=True,
            )
            return

        try:
            match.move_card(side, player_card, destination)
        except ValueError as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return

        game.match_state = match.to_dict()
        save_games(self.games)

        player = self.get_player_definition(player_card)
        await self.announce_board_update(
            interaction,
            game,
            f"{format_role_bracket(player, self.team_emojis)} moved to "
            f"{destination_display_name(destination)}.",
        )

    @coach.autocomplete("player_card")
    async def coach_player_card_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        game = self.game_for_channel(interaction.channel_id)
        if game is None or game.match_state is None:
            return []
        side = self.side_for_user(game, interaction.user.id)
        if side is None:
            return []
        match = self.load_match_state(game)
        setup = match.setup_for_side(side)
        roster_ids = (
            setup.field_players
            + setup.player_board.bench
            + setup.player_board.back_bench
        )
        options = [
            (player_id, self.format_roster_player(player_id))
            for player_id in roster_ids
        ]
        return filter_choices(current, options)

    @coach.autocomplete("destination")
    async def coach_destination_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        options = [
            (value, destination_display_name(value))
            for value in (
                Zone.HOME_GOAL.value,
                Zone.MIDFIELD.value,
                Zone.VISITORS_GOAL.value,
                *BENCH_DESTINATIONS,
            )
        ]
        return filter_choices(current, options)

    @app_commands.command(
        name="ref",
        description=(
            "Move a player card (either team) between its team's zones "
            "and benches."
        ),
    )
    @app_commands.describe(
        player_card="Any player card from either team.",
        destination="Where to move the card: a team's zone or bench.",
    )
    @app_commands.guild_only()
    async def ref(
        self,
        interaction: discord.Interaction,
        player_card: str,
        destination: str,
    ) -> None:
        result = await self.defer_and_get_match(interaction)
        if result is None:
            return
        game, match = result

        try:
            player = self.get_player_definition(player_card)
        except ValueError as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return

        card_side = (
            TeamSide.HOME
            if player.team == match.home.team
            else TeamSide.VISITING
        )

        dest_side_value, _, dest_target = destination.partition(":")
        try:
            dest_side = TeamSide(dest_side_value)
        except ValueError:
            await interaction.followup.send(
                f"\"{destination}\" is not a valid destination.",
                ephemeral=True,
            )
            return

        if dest_side != card_side:
            team_label = format_team_side_label(
                match.setup_for_side(card_side),
            )
            await interaction.followup.send(
                f"{player.name} plays for {team_label}; move them to "
                f"one of {team_label}'s zones or benches instead.",
                ephemeral=True,
            )
            return

        try:
            match.move_card(card_side, player_card, dest_target)
        except ValueError as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return

        game.match_state = match.to_dict()
        save_games(self.games)

        await self.announce_board_update(
            interaction,
            game,
            f"{format_role_bracket(player, self.team_emojis)} moved to "
            f"{destination_display_name(dest_target)}.",
        )

    @ref.autocomplete("player_card")
    async def ref_player_card_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        game = self.game_for_channel(interaction.channel_id)
        if game is None or game.match_state is None:
            return []
        match = self.load_match_state(game)
        options = [
            (player_id, self.format_roster_player_with_team(player_id))
            for setup in (match.home, match.visiting)
            for player_id in (
                setup.field_players
                + setup.player_board.bench
                + setup.player_board.back_bench
            )
        ]
        return filter_choices(current, options)

    @ref.autocomplete("destination")
    async def ref_destination_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        game = self.game_for_channel(interaction.channel_id)
        if game is None or game.match_state is None:
            return []
        match = self.load_match_state(game)
        options = [
            (
                f"{setup.side.value}:{target}",
                f"{format_team_side_label(setup)} - "
                f"{destination_display_name(target)}",
            )
            for setup in (match.home, match.visiting)
            for target in (
                Zone.HOME_GOAL.value,
                Zone.MIDFIELD.value,
                Zone.VISITORS_GOAL.value,
                *BENCH_DESTINATIONS,
            )
        ]
        return filter_choices(current, options)

    @meeple_group.command(
        name="move",
        description="Move a fielded player's meeple to another space.",
    )
    @app_commands.describe(
        meeple="A currently fielded player.",
        destination="The board space to move them to, e.g. H1.",
    )
    @app_commands.guild_only()
    async def meeple_move(
        self,
        interaction: discord.Interaction,
        meeple: str,
        destination: str,
    ) -> None:
        result = await self.defer_and_get_match(interaction)
        if result is None:
            return
        game, match = result

        try:
            zone, space_index = parse_space_value(destination)
            match.move_meeple(meeple, zone, space_index)
        except ValueError as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return

        game.match_state = match.to_dict()
        save_games(self.games)

        player = self.get_player_definition(meeple)
        await self.announce_board_update(
            interaction,
            game,
            f"{format_role_bracket(player, self.team_emojis)} moved to "
            f"{space_label(zone, space_index)}.",
        )

    @meeple_move.autocomplete("meeple")
    async def meeple_move_meeple_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        game = self.game_for_channel(interaction.channel_id)
        if game is None or game.match_state is None:
            return []
        match = self.load_match_state(game)
        options = [
            (player_id, self.format_roster_player_with_team(player_id))
            for setup in (match.home, match.visiting)
            for player_id in setup.field_players
        ]
        return filter_choices(current, options)

    @meeple_move.autocomplete("destination")
    async def meeple_move_destination_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        game = self.game_for_channel(interaction.channel_id)
        if game is None or game.match_state is None:
            return []
        match = self.load_match_state(game)
        return filter_choices(current, space_choices(match))

    @ball_group.command(
        name="move",
        description="Place the ball on any board space.",
    )
    @app_commands.describe(
        destination="The board space to move the ball to, e.g. H1.",
    )
    @app_commands.guild_only()
    async def ball_move(
        self,
        interaction: discord.Interaction,
        destination: str,
    ) -> None:
        result = await self.defer_and_get_match(interaction)
        if result is None:
            return
        game, match = result

        try:
            zone, space_index = parse_space_value(destination)
            match.move_ball(zone, space_index)
        except ValueError as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return

        game.match_state = match.to_dict()
        save_games(self.games)

        possession_team = match.setup_for_side(match.ball.possession).team
        await self.announce_board_update(
            interaction,
            game,
            f"The ball moved to {space_label(zone, space_index)}. "
            f"{possession_team.value.title()} has possession.",
        )

    @ball_move.autocomplete("destination")
    async def ball_move_destination_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        game = self.game_for_channel(interaction.channel_id)
        if game is None or game.match_state is None:
            return []
        match = self.load_match_state(game)
        return filter_choices(current, space_choices(match))

    @ball_group.command(
        name="possession",
        description="Set which team has possession of the ball.",
    )
    @app_commands.describe(team="The team to give possession to.")
    @app_commands.guild_only()
    async def ball_possession(
        self,
        interaction: discord.Interaction,
        team: str,
    ) -> None:
        result = await self.defer_and_get_match(interaction)
        if result is None:
            return
        game, match = result

        try:
            side = TeamSide(team)
            match.set_possession(side)
        except ValueError as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return

        game.match_state = match.to_dict()
        save_games(self.games)

        await interaction.followup.send(
            f"{match.setup_for_side(side).team.value.title()} now has "
            "possession."
        )
        await self.refresh_match_image(interaction, game)

    @ball_possession.autocomplete("team")
    async def ball_possession_team_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        game = self.game_for_channel(interaction.channel_id)
        if game is None or game.match_state is None:
            return []
        match = self.load_match_state(game)
        options = [
            (setup.side.value, format_team_side_label(setup))
            for setup in (match.home, match.visiting)
        ]
        return filter_choices(current, options)

    @ball_group.command(
        name="speed",
        description="Set or adjust the ball's speed (1-12).",
    )
    @app_commands.describe(
        value=(
            "A number to set the speed to, or +1/-1 to adjust it. "
            "Leave blank to increase it by one."
        ),
    )
    @app_commands.guild_only()
    async def ball_speed(
        self,
        interaction: discord.Interaction,
        value: Optional[str] = None,
    ) -> None:
        result = await self.defer_and_get_match(interaction)
        if result is None:
            return
        game, match = result

        try:
            match.ball.speed = resolve_adjustable_value(
                value, match.ball.speed, 1, 12,
            )
        except ValueError as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return

        game.match_state = match.to_dict()
        save_games(self.games)

        await interaction.followup.send(
            f"Ball speed is now {match.ball.speed}."
        )
        await self.refresh_match_image(interaction, game)

    @app_commands.command(
        name="score",
        description="Set or adjust a team's score.",
    )
    @app_commands.describe(
        team="The team to adjust. Defaults to your own team.",
        value=(
            "A number to set the score to, or +1/-1 to adjust it. "
            "Leave blank to increase it by one."
        ),
    )
    @app_commands.guild_only()
    async def score(
        self,
        interaction: discord.Interaction,
        team: Optional[str] = None,
        value: Optional[str] = None,
    ) -> None:
        result = await self.defer_and_get_match(interaction)
        if result is None:
            return
        game, match = result

        if team is not None:
            try:
                side = TeamSide(team)
            except ValueError:
                await interaction.followup.send(
                    f"\"{team}\" is not a valid team.",
                    ephemeral=True,
                )
                return
        else:
            side = self.side_for_user(game, interaction.user.id)
            if side is None:
                await interaction.followup.send(
                    "You are not one of the players in this game; "
                    "specify a team.",
                    ephemeral=True,
                )
                return

        current = (
            match.scoreboard.home_score
            if side == TeamSide.HOME
            else match.scoreboard.visiting_score
        )
        try:
            new_value = resolve_adjustable_value(value, current, 0, 999)
        except ValueError as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return

        if side == TeamSide.HOME:
            match.scoreboard.home_score = new_value
        else:
            match.scoreboard.visiting_score = new_value

        game.match_state = match.to_dict()
        save_games(self.games)

        team_name = match.setup_for_side(side).team.value.title()
        await interaction.followup.send(
            f"{team_name}'s score is now {new_value} "
            f"({match.scoreboard.home_score}:"
            f"{match.scoreboard.visiting_score})."
        )
        await self.refresh_match_image(interaction, game)

    @score.autocomplete("team")
    async def score_team_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        game = self.game_for_channel(interaction.channel_id)
        if game is None or game.match_state is None:
            return []
        match = self.load_match_state(game)
        options = [
            (setup.side.value, format_team_side_label(setup))
            for setup in (match.home, match.visiting)
        ]
        return filter_choices(current, options)

    @app_commands.command(
        name="time",
        description="Set or adjust the game clock (00-15) and half.",
    )
    @app_commands.describe(
        value=(
            "A number to set the clock to, or +1/-1 to adjust it. "
            "Leave blank to increase it by one."
        ),
        period="Switch to the first or second half.",
    )
    @app_commands.choices(
        period=[
            app_commands.Choice(name="First Half", value="first_half"),
            app_commands.Choice(name="Second Half", value="second_half"),
        ],
    )
    @app_commands.guild_only()
    async def time(
        self,
        interaction: discord.Interaction,
        value: Optional[str] = None,
        period: Optional[str] = None,
    ) -> None:
        result = await self.defer_and_get_match(interaction)
        if result is None:
            return
        game, match = result

        try:
            match.scoreboard.time = resolve_adjustable_value(
                value, match.scoreboard.time, 0, 15,
            )
        except ValueError as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return

        if period is not None:
            match.scoreboard.period = MatchPeriod(period)

        game.match_state = match.to_dict()
        save_games(self.games)

        period_label = (
            "First Half"
            if match.scoreboard.period == MatchPeriod.FIRST_HALF
            else "Second Half"
        )
        await interaction.followup.send(
            f"The clock is now {match.scoreboard.time:02d} "
            f"({period_label})."
        )
        await self.refresh_match_image(interaction, game)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(D12Ball(bot))
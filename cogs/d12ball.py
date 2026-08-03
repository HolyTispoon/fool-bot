import io
import logging
import random
import re
import uuid
from typing import Optional

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from d12ball.ai import build_ai_strategies, AIStrategy
from d12ball.components import (
    MatchPeriod,
    MatchState,
    PlayerDefinition,
    PlayerRole,
    TeamSetup,
    TeamSide,
    Zone,
    kickoff_space_index,
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
    render_skill_test_dice,
)

from gamesaves.d12ball.storage import (
    load_games,
    save_games,
)


LOGGER = logging.getLogger(__name__)

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
FULL_IMAGE_BUTTON_LABEL = "View full image"

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
        LOGGER.warning(
            "Could not load the D12 Ball condition emoji: %s", error,
        )
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
        LOGGER.info(
            "This application has no condition emoji named %s; those "
            "conditions will show their fallback emoji instead.",
            ", ".join(missing),
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
        LOGGER.warning("Could not load the D12 Ball team emoji: %s", error)
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
        LOGGER.info(
            "This application has no team emoji named %s; those teams "
            "will show a colored circle instead.",
            ", ".join(missing),
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
        LOGGER.warning("Could not load the D12 Ball coin emoji: %s", error)
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
        LOGGER.info(
            "This application has no coin emoji named %s; coin tosses "
            "will show %s instead.",
            ", ".join(missing),
            COIN_EMOJI_FALLBACK,
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


def build_full_image_button(
    message: discord.Message,
) -> Optional[discord.ui.Button]:
    """
    A link straight to the file Discord stored for a posted image.

    Discord's Android client draws an attachment from a resized copy on
    media.discordapp.net and keeps showing that copy when you zoom in,
    so the ability text on the player cards is unreadable on a phone.
    iOS hands out the original, so only some of the table sees the
    problem. This opens the unresized upload in a browser instead.

    Attachment URLs are signed, and Discord stops honouring a signature
    24 hours after it was issued, so the button is rebuilt from the
    message every time the image is posted or replaced. A board nobody
    has touched for a day has a dead link until the next update
    replaces it.
    """
    if not message.attachments:
        return None

    return discord.ui.Button(
        label=FULL_IMAGE_BUTTON_LABEL,
        style=discord.ButtonStyle.link,
        url=message.attachments[0].url,
    )


async def add_full_image_button(
    message: discord.Message,
    view: Optional[discord.ui.View] = None,
) -> None:
    """
    Put the full-image link on a message that has already gone out.

    The URL only exists once Discord has stored the file, so this is
    always a second round trip. Editing a message's view replaces it
    wholesale, so `view` has to carry the message's own buttons too --
    discord.py routes clicks against the components in the payload, and
    dropping them would leave a message that looks interactive and
    is not.
    """
    button = build_full_image_button(message)

    if button is None:
        return

    view = discord.ui.View(timeout=None) if view is None else view
    view.add_item(button)

    try:
        await message.edit(view=view)
    except (discord.HTTPException, aiohttp.ClientError):
        # The image itself is already posted, so a missing link is
        # worth less than the game action it would take down with it.
        # aiohttp.ClientError (connection reset, a bad SSL record, a
        # timeout) covers a dropped connection below discord.py's own
        # exception types -- equally not worth losing the rest of the
        # turn over.
        pass


async def add_full_image_button_to_response(
    interaction: discord.Interaction,
    view: Optional[discord.ui.View] = None,
) -> None:
    """
    The same, for an image posted as the interaction response itself,
    which has to be fetched back before its attachment URL is known.
    """
    try:
        message = await interaction.original_response()
    except (discord.HTTPException, aiohttp.ClientError):
        return

    await add_full_image_button(message, view)


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
        LOGGER.error(
            "Unhandled error in %r for %r: %r",
            self, item, error, exc_info=error,
        )
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

        await add_full_image_button(choice_message, refreshed_view)

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

        await add_full_image_button_to_response(interaction, refreshed_view)

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
            initials = ROLE_INITIALS[player.role.value]
            button = discord.ui.Button(
                label=f"{player.name} [{initials}]",
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

        # Role abilities -- Midfielder: +3 on a Dribble Advance skill
        # test; Playmaker: +3 on either pass's skill test. Both are
        # offense-only since those maneuvers only exist on that side.
        offense_ability_note = ""
        offense_ability_detail = ""
        if (
            offense_player.role == PlayerRole.MIDFIELDER
            and match.offense_maneuver == "Dribble Advance"
        ):
            offense_total += 3
            offense_ability_note = " + 3 (Midfielder ability)"
            offense_ability_detail = "+3 Midfielder ability"
        elif (
            offense_player.role == PlayerRole.PLAYMAKER
            and match.offense_maneuver in ("Low Pass", "High Pass")
        ):
            offense_total += 3
            offense_ability_note = " + 3 (Playmaker ability)"
            offense_ability_detail = "+3 Playmaker ability"

        modifier_note = ""
        modifier_detail = ""
        if match.defense_maneuver == "Steal Intercept":
            modifier = match.ball.speed // 2
            defense_total += modifier
            modifier_note = f" + {modifier} (ball speed modifier)"
            modifier_detail = f"+{modifier} ball speed modifier"

        breakdown = (
            f"**{format_role_bracket(offense_player, self.cog.team_emojis)}** (offense): "
            f"rolled {offense_roll} + {offense_skill} (offensive skill "
            f"modifier){offense_ability_note} = {offense_total}\n"
            f"**{format_role_bracket(defense_player, self.cog.team_emojis)}** (defense): "
            f"rolled {defense_roll} + {defense_skill} (defensive skill "
            f"modifier){modifier_note} = {defense_total}"
        )
        offense_detail = [
            f"{offense_player.name} [{ROLE_INITIALS[offense_player.role.value]}]",
            f"Offensive skill +{offense_skill}",
        ]
        if offense_ability_detail:
            offense_detail.append(offense_ability_detail)
        defense_detail = [
            f"{defense_player.name} [{ROLE_INITIALS[defense_player.role.value]}]",
            f"Defensive skill +{defense_skill}",
        ]
        if modifier_detail:
            defense_detail.append(modifier_detail)
        dice_file = discord.File(
            render_skill_test_dice(
                [
                    (
                        offense_roll,
                        TEAM_COLORS[offense_player.team],
                        offense_player.team.value.title(),
                        offense_detail,
                        offense_total,
                    ),
                    (
                        defense_roll,
                        TEAM_COLORS[defense_player.team],
                        defense_player.team.value.title(),
                        defense_detail,
                        defense_total,
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
                    f"**It's a tie ({offense_total}-{defense_total})!** "
                    f"The skill test must be rolled again.\n"
                    f"{exhaustion_text}\n\nRoll again:"
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

        await interaction.response.edit_message(
            content=(
                f"{breakdown}\n\n"
                f"**{winner_name}** wins the skill test! {winner_mention} "
                "resolves the effect:"
            ),
            attachments=[dice_file],
            view=None,
        )
        await self.cog.refresh_match_image(interaction, game)

        for player in exhausted_participants:
            await self.cog.run_injury_test(interaction, game, match, player)

        await self.cog.begin_effect_resolution(interaction, game, match, winner_name)


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

        # Role ability -- Striker: +3 on any scoring attempt off a
        # set-up.
        striker_note = ""
        if match.pending_shot_is_set_up and shooter.role == PlayerRole.STRIKER:
            attack_total += 3
            striker_note = " + 3 (Striker ability)"

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
            f"skill modifier){speed_note}{striker_note} = {attack_total}\n"
            f"**{format_team_side_label(defending_setup)}** (defense): "
            f"rolled {defense_roll} + {defense_source} = {defense_total}"
        )
        attack_detail = [
            f"{shooter.name} [{ROLE_INITIALS[shooter.role.value]}]",
            f"Offensive skill +{offense_skill}",
        ]
        if speed_modifier:
            attack_detail.append(f"+{speed_modifier} ball speed modifier")
        if striker_note:
            attack_detail.append("+3 Striker ability")

        if defenders:
            defense_detail = [
                f"{player.name} [{ROLE_INITIALS[player.role.value]}] +{skill}"
                for player, skill in defenders
            ]
            if len(defenders) > 1:
                defense_detail.append(
                    f"Total defensive skill +{defense_skill_total}"
                )
        else:
            defense_detail = ["No one in the way"]

        dice_file = discord.File(
            render_skill_test_dice(
                [
                    (
                        attack_roll,
                        TEAM_COLORS[attacking_setup.team],
                        attacking_setup.team.value.title(),
                        attack_detail,
                        attack_total,
                    ),
                    (
                        defense_roll,
                        TEAM_COLORS[defending_setup.team],
                        defending_setup.team.value.title(),
                        defense_detail,
                        defense_total,
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

        # A plain score attempt costs no exhaustion and owes no injury
        # check -- only a shot taken off a set-up gains a token, taken
        # after the roll regardless of outcome, and injury checks stay
        # exclusive to skill tests either way.
        set_up_note = ""
        if match.pending_shot_is_set_up:
            match.add_exhaustion(shooter.player_id, 1)
            set_up_note = "\n\n" + self.cog.describe_exhaustion_gain(
                match, shooter.player_id, 1,
            )

        # Every score attempt is a turnover, win or miss: the clock
        # cost is the shot's own distance to goal, captured before the
        # restart moves the ball, and the team that just defended
        # restarts play -- in the middle of the midfield on a goal
        # (the same kickoff rule as the start of a half), or at the
        # space closest to their own goal on a miss.
        space_minutes = match.spaces_to_goal()
        new_possession_side = defending_setup.side
        if scored:
            kickoff_index = kickoff_space_index(
                len(match.board.spaces[Zone.MIDFIELD]),
                new_possession_side,
            )
            match.set_ball_space(Zone.MIDFIELD, kickoff_index)
        else:
            restart_zone, restart_index = match.own_goal_restart_space(
                new_possession_side,
            )
            match.set_ball_space(restart_zone, restart_index)
        match.ball.possession = new_possession_side
        match.ball.speed = 1

        # active_player_id/pending_action stay set -- like a maneuver,
        # reset_maneuver() only happens once finish_maneuver_resolution
        # is reached, so a bot restart mid-run-back reconstructs
        # correctly (build_run_back_view is checked before
        # pending_action == "shoot" in the view-rebuild cascade).
        #
        # pending_run_back has to be set (matching begin_run_back)
        # before the state is saved, not after: the shooter no longer
        # shares the restarted ball's space or side, and validate()
        # only allows a stale active_player_id while a maneuver effect
        # is in progress or pending_run_back is set -- a score attempt
        # has neither until this line.
        match.pending_run_back = True
        match.pending_run_back_distance = space_minutes
        match.pending_run_back_turnover = True
        game.match_state = match.to_dict()
        save_games(self.cog.games)

        await interaction.response.edit_message(
            content=f"{breakdown}\n\n{verdict}{set_up_note}",
            attachments=[dice_file],
            view=None,
        )
        await self.cog.refresh_match_image(interaction, game)
        await self.cog.continue_run_back(interaction, game, match)


class LowPassChoiceView(SafeView):
    """
    Direction x distance for a won Low Pass, chosen together as one
    prompt. Reconstructible on restart purely from match state (see
    D12Ball.build_effect_choice_view), the same pattern every other
    persistent view in this cog follows.
    """

    def __init__(self, cog: "D12Ball", game_id: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id

        for direction in ("forward", "backward"):
            for distance in (1, 2):
                button = discord.ui.Button(
                    label=f"{direction.title()} {distance}",
                    style=discord.ButtonStyle.primary,
                    custom_id=(
                        f"d12ball:low_pass:{game_id}:{direction}:{distance}"
                    ),
                )

                async def callback(
                    interaction: discord.Interaction,
                    chosen_direction: str = direction,
                    chosen_distance: int = distance,
                ) -> None:
                    await self.choose(
                        interaction, chosen_direction, chosen_distance,
                    )

                button.callback = callback
                self.add_item(button)

    async def choose(
        self,
        interaction: discord.Interaction,
        direction: str,
        distance: int,
    ) -> None:
        game = self.cog.games.get(self.game_id)
        if game is None or game.match_state is None:
            await interaction.response.send_message(
                "I could not find the saved data for this game.",
                ephemeral=True,
            )
            return
        match = self.cog.load_match_state(game)

        if not self.cog.user_controls_possession(
            interaction.user.id, game, match,
        ):
            await interaction.response.send_message(
                "Only the player resolving this effect can choose.",
                ephemeral=True,
            )
            return

        await interaction.response.edit_message(
            content=f"Chose **{direction} {distance}**.",
            view=None,
        )
        await self.cog.apply_low_pass(
            interaction, game, match, direction, distance,
        )


class HighPassChoiceView(SafeView):
    def __init__(self, cog: "D12Ball", game_id: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id

        for distance in (2, 3):
            button = discord.ui.Button(
                label=f"{distance} spaces",
                style=discord.ButtonStyle.primary,
                custom_id=f"d12ball:high_pass:{game_id}:{distance}",
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
        game = self.cog.games.get(self.game_id)
        if game is None or game.match_state is None:
            await interaction.response.send_message(
                "I could not find the saved data for this game.",
                ephemeral=True,
            )
            return
        match = self.cog.load_match_state(game)

        if not self.cog.user_controls_possession(
            interaction.user.id, game, match,
        ):
            await interaction.response.send_message(
                "Only the player resolving this effect can choose.",
                ephemeral=True,
            )
            return

        await interaction.response.edit_message(
            content=f"Chose **{distance} spaces**.",
            view=None,
        )
        await self.cog.apply_high_pass(interaction, game, match, distance)


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
        skill_type: str,
    ):
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id
        self.player_id = player_id
        self.skill_type = skill_type

        game = cog.games.get(game_id)
        if game is None or game.match_state is None:
            return
        match = cog.load_match_state(game)
        profile = cog.player_catalog.effective_profile(
            cog.get_player_definition(player_id),
        )
        skill = profile.offense if skill_type == "offense" else profile.defense
        current = match.ball.speed

        seen_targets: set[int] = set()
        for delta in range(-skill, skill + 1):
            target = max(1, min(12, current + delta))
            if target in seen_targets:
                continue
            seen_targets.add(target)

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
        game = self.cog.games.get(self.game_id)
        if game is None or game.match_state is None:
            await interaction.response.send_message(
                "I could not find the saved data for this game.",
                ephemeral=True,
            )
            return
        match = self.cog.load_match_state(game)

        controller_id = self.cog.controlling_user_id(
            game, match, self.player_id,
        )
        if interaction.user.id != controller_id:
            await interaction.response.send_message(
                "Only the player resolving this effect can choose.",
                ephemeral=True,
            )
            return

        # Steal Intercept has already flipped possession by the time
        # this view is shown; Dribble Advance never flips it.
        after_turnover = match.defense_maneuver == "Steal Intercept" and (
            self.skill_type == "defense"
        )

        await interaction.response.edit_message(
            content=f"Chose speed **{target_speed}**.",
            view=None,
        )
        await self.cog.apply_speed_choice(
            interaction, game, match, target_speed, after_turnover,
        )


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
            player = cog.get_player_definition(player_id)
            initials = ROLE_INITIALS[player.role.value]
            button = discord.ui.Button(
                label=f"{player.name} [{initials}]",
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
        game = self.cog.games.get(self.game_id)
        if game is None or game.match_state is None:
            await interaction.response.send_message(
                "I could not find the saved data for this game.",
                ephemeral=True,
            )
            return
        match = self.cog.load_match_state(game)

        if not self.cog.user_controls_possession(
            interaction.user.id, game, match,
        ):
            await interaction.response.send_message(
                "Only the player resolving this effect can choose.",
                ephemeral=True,
            )
            return

        shooter = self.cog.get_player_definition(shooter_id)
        await interaction.response.edit_message(
            content=(
                f"{format_role_bracket(shooter, self.cog.team_emojis)} "
                "takes the shot."
            ),
            view=None,
        )
        await self.cog.start_set_up_shot(interaction, game, match, shooter_id)


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

        game = cog.games.get(game_id)
        if game is None or game.match_state is None:
            return
        match = cog.load_match_state(game)
        side = (
            TeamSide.HOME
            if player_id in match.home.field_players
            else TeamSide.VISITING
        )
        zone = match.setup_for_side(side).assigned_zone(player_id)

        for space_index in match.open_spaces_in_zone(side, zone):
            button = discord.ui.Button(
                label=space_label(zone, space_index),
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
        game = self.cog.games.get(self.game_id)
        if game is None or game.match_state is None:
            await interaction.response.send_message(
                "I could not find the saved data for this game.",
                ephemeral=True,
            )
            return
        match = self.cog.load_match_state(game)

        controller_id = self.cog.controlling_user_id(
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

        match.add_exhaustion(self.player_id, distance)
        game.match_state = match.to_dict()
        save_games(self.cog.games)

        player = self.cog.get_player_definition(self.player_id)
        await interaction.response.edit_message(
            content=(
                f"{format_role_bracket(player, self.cog.team_emojis)} "
                f"runs back to {space_label(zone, space_index)}.\n"
                + self.cog.describe_exhaustion_gain(
                    match, self.player_id, distance,
                )
            ),
            view=None,
        )
        await self.cog.refresh_match_image(interaction, game)
        await self.cog.continue_run_back(interaction, game, match)


class LooseBallChoiceView(SafeView):
    """
    One combined prompt for whichever side(s) still need a real human
    pick of who contests a loose ball -- entries is a list of
    (side, candidates) for only the sides that still need one.
    """

    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
        entries: list[tuple[str, list[str]]],
    ):
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id

        for side, candidates in entries:
            for player_id in candidates:
                player = cog.get_player_definition(player_id)
                initials = ROLE_INITIALS[player.role.value]
                button = discord.ui.Button(
                    label=f"{player.name} [{initials}] ({side})",
                    style=(
                        discord.ButtonStyle.primary
                        if side == "offense"
                        else discord.ButtonStyle.danger
                    ),
                    custom_id=(
                        f"d12ball:loose_ball:{game_id}:{side}:{player_id}"
                    ),
                )

                async def callback(
                    interaction: discord.Interaction,
                    chosen_side: str = side,
                    chosen_player_id: str = player_id,
                ) -> None:
                    await self.choose(
                        interaction, chosen_side, chosen_player_id,
                    )

                button.callback = callback
                self.add_item(button)

    async def choose(
        self,
        interaction: discord.Interaction,
        side: str,
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

        if side == "offense":
            authorized = self.cog.user_controls_possession(
                interaction.user.id, game, match,
            )
            already_chosen = match.loose_ball_offense_player is not None
        else:
            authorized = self.cog.user_controls_defense(
                interaction.user.id, game, match,
            )
            already_chosen = match.loose_ball_defense_player is not None

        if already_chosen:
            await interaction.response.send_message(
                "A player has already been chosen for that side.",
                ephemeral=True,
            )
            return
        if not authorized:
            await interaction.response.send_message(
                "Only the player on that side can choose.",
                ephemeral=True,
            )
            return

        if side == "offense":
            match.choose_loose_ball_offense_player(player_id)
        else:
            match.choose_loose_ball_defense_player(player_id)
        game.match_state = match.to_dict()
        save_games(self.cog.games)

        player = self.cog.get_player_definition(player_id)
        refreshed_view = self.cog.build_loose_ball_view(
            self.game_id, match,
        )
        await interaction.response.edit_message(view=refreshed_view)
        await interaction.followup.send(
            f"{format_role_bracket(player, self.cog.team_emojis)} "
            f"contests the loose ball ({side})."
        )

        offense_ready, defense_ready = self.cog.loose_ball_sides_ready(
            match,
        )
        if offense_ready and defense_ready:
            await self.cog.resolve_loose_ball(interaction, game, match)


class LooseBallSkillTestView(SafeView):
    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
    ):
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id

        button = discord.ui.Button(
            label="Roll for the loose ball",
            style=discord.ButtonStyle.primary,
            custom_id=f"d12ball:loose_ball_test:{game_id}",
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
        if (
            not match.pending_loose_ball
            or match.loose_ball_offense_player is None
            or match.loose_ball_defense_player is None
        ):
            await interaction.response.send_message(
                "This loose ball is no longer active.",
                ephemeral=True,
            )
            return

        participant_ids = {game.player_1_id}
        if game.player_2_id is not None:
            participant_ids.add(game.player_2_id)
        if interaction.user.id not in participant_ids:
            await interaction.response.send_message(
                "Only a player in this game can roll for the loose ball.",
                ephemeral=True,
            )
            return

        offense_player = self.cog.get_player_definition(
            match.loose_ball_offense_player,
        )
        defense_player = self.cog.get_player_definition(
            match.loose_ball_defense_player,
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

        breakdown = (
            f"**{format_role_bracket(offense_player, self.cog.team_emojis)}** "
            f"(offense): rolled {offense_roll} + {offense_skill} "
            f"(offensive skill modifier) = {offense_total}\n"
            f"**{format_role_bracket(defense_player, self.cog.team_emojis)}** "
            f"(defense): rolled {defense_roll} + {defense_skill} "
            f"(defensive skill modifier) = {defense_total}"
        )
        dice_file = discord.File(
            render_skill_test_dice(
                [
                    (
                        offense_roll,
                        TEAM_COLORS[offense_player.team],
                        offense_player.team.value.title(),
                        [
                            f"{offense_player.name} "
                            f"[{ROLE_INITIALS[offense_player.role.value]}]",
                            f"Offensive skill +{offense_skill}",
                        ],
                        offense_total,
                    ),
                    (
                        defense_roll,
                        TEAM_COLORS[defense_player.team],
                        defense_player.team.value.title(),
                        [
                            f"{defense_player.name} "
                            f"[{ROLE_INITIALS[defense_player.role.value]}]",
                            f"Defensive skill +{defense_skill}",
                        ],
                        defense_total,
                    ),
                ]
            ),
            filename="loose_ball_dice.png",
        )

        if offense_total == defense_total:
            match.add_exhaustion(match.loose_ball_offense_player, 1)
            match.add_exhaustion(match.loose_ball_defense_player, 1)
            game.match_state = match.to_dict()
            save_games(self.cog.games)

            exhaustion_text = "\n".join(
                [
                    self.cog.describe_exhaustion_gain(
                        match, match.loose_ball_offense_player, 1,
                    ),
                    self.cog.describe_exhaustion_gain(
                        match, match.loose_ball_defense_player, 1,
                    ),
                ]
            )
            await interaction.response.edit_message(
                content=(
                    f"{breakdown}\n\n"
                    f"**It's a tie ({offense_total}-{defense_total})!** "
                    f"The skill test must be rolled again.\n"
                    f"{exhaustion_text}\n\nRoll again:"
                ),
                attachments=[dice_file],
                view=LooseBallSkillTestView(self.cog, self.game_id),
            )
            await self.cog.refresh_match_image(interaction, game)
            return

        outcome = "offense" if offense_total > defense_total else "defense"
        winner_side = (
            match.ball.possession
            if outcome == "offense"
            else match.defending_side()
        )
        turnover_occurred = winner_side != match.ball.possession
        winner_number = (
            self.cog.possession_player_number(game, match)
            if outcome == "offense"
            else self.cog.defending_player_number(game, match)
        )
        winner_mention = format_player_with_team(
            game, winner_number, mention=True,
        )
        winner_player = (
            offense_player if outcome == "offense" else defense_player
        )

        exhausted_participants = [
            player
            for player in (offense_player, defense_player)
            if player.player_id in match.exhausted
        ]
        distance_moved = match.pending_loose_ball_distance

        match.ball.possession = winner_side
        if turnover_occurred:
            match.ball.speed = 1
        match.pending_loose_ball = False
        match.loose_ball_offense_player = None
        match.loose_ball_defense_player = None
        game.match_state = match.to_dict()
        save_games(self.cog.games)

        turnover_line = "\n\n# Turnover!" if turnover_occurred else ""
        await interaction.response.edit_message(
            content=(
                f"{breakdown}{turnover_line}\n\n"
                f"{format_role_bracket(winner_player, self.cog.team_emojis)} "
                f"wins the loose ball! {winner_mention} has possession."
            ),
            attachments=[dice_file],
            view=None,
        )
        await self.cog.refresh_match_image(interaction, game)

        for player in exhausted_participants:
            await self.cog.run_injury_test(interaction, game, match, player)

        await self.cog.begin_run_back(
            interaction, game, match,
            distance_moved=distance_moved,
            turnover_occurred=turnover_occurred,
        )


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
                try:
                    match = self.load_match_state(game)
                except ValueError as error:
                    # Saved state that no longer passes validate() (e.g.
                    # a crash that saved state mid-effect, before the
                    # rest of the pipeline could finish) shouldn't take
                    # every other game's button views down with it on
                    # startup -- log it so it reaches #logs and needs
                    # fixing, and move on to the next game.
                    LOGGER.error(
                        "Could not restore views for game %s: %s",
                        game.game_id, error,
                    )
                    continue
                if match.active_player_id is None:
                    turn_view = BallHandlerSelectionView(self, game.game_id)
                elif match.pending_run_back:
                    turn_view = self.build_run_back_view(
                        game.game_id, match,
                    ) or PlayerActionView(self, game.game_id)
                elif match.pending_loose_ball:
                    if (
                        match.loose_ball_offense_player is not None
                        and match.loose_ball_defense_player is not None
                    ):
                        turn_view = LooseBallSkillTestView(
                            self, game.game_id,
                        )
                    else:
                        turn_view = self.build_loose_ball_view(
                            game.game_id, match,
                        ) or PlayerActionView(self, game.game_id)
                elif match.pending_action == "shoot":
                    turn_view = ScoreAttemptView(self, game.game_id)
                elif (
                    match.pending_action == "maneuver"
                    and match.challenger_id is None
                ):
                    turn_view = ManeuverChallengeView(self, game.game_id)
                elif (
                    match.challenger_id is not None
                    and (
                        match.offense_maneuver is None
                        or match.defense_maneuver is None
                    )
                ):
                    # challenger_id is only ever set while a maneuver is
                    # in progress and cleared by reset_maneuver(), so
                    # it alone disambiguates this from any other phase
                    # -- pending_action itself is cleared to None by
                    # choose_challenger() right when the challenger is
                    # picked, so it can't be relied on from here on.
                    turn_view = ManeuverActionPromptView(self, game.game_id)
                elif (
                    match.challenger_id is not None
                    and match.offense_maneuver is not None
                    and match.defense_maneuver is not None
                ):
                    if self.maneuver_catalog.resolve(
                        match.offense_maneuver, match.defense_maneuver,
                    ) == "tie":
                        turn_view = SkillTestView(self, game.game_id)
                    else:
                        turn_view = self.build_effect_choice_view(
                            game.game_id, match,
                        ) or PlayerActionView(self, game.game_id)
                else:
                    turn_view = PlayerActionView(self, game.game_id)
                self.bot.add_view(
                    turn_view,
                    message_id=game.turn_message_id,
                )
                restored_views += 1

        LOGGER.info(
            "Loaded %d saved D12 Ball games and restored %d button "
            "views.",
            len(self.games),
            restored_views,
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
        LOGGER.error(
            "Unhandled error in /%s: %r",
            command_name, original, exc_info=original,
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
        if match.pending_shot_is_set_up and shooter.role == PlayerRole.STRIKER:
            attack_line += ", plus 3 for the Striker ability"

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

        prompt_view = ManeuverActionPromptView(self, game.game_id)
        prompt_message = await interaction.followup.send(
            f"{' and '.join(waiting_on)}, both sides will now choose a "
            "maneuver privately. See the reference below for all six "
            "maneuvers, then use the button to make your pick.",
            file=self.build_maneuver_reference_file(),
            view=prompt_view,
            wait=True,
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False,
            ),
        )
        game.turn_message_id = prompt_message.id
        save_games(self.games)

        await add_full_image_button(prompt_message, prompt_view)

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

            await interaction.followup.send(
                f"{reveal}\n\n"
                f"**{winner_name}** wins! {winner_mention}, resolving the "
                f"effect:\n{winner_definition.effect}",
                allowed_mentions=discord.AllowedMentions(
                    users=True,
                    roles=False,
                    everyone=False,
                ),
            )
            await self.begin_effect_resolution(interaction, game, match, winner_name)
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

    def controlling_user_id(
        self,
        game: D12BallGame,
        match: MatchState,
        player_id: str,
    ) -> Optional[int]:
        """
        The Discord user controlling whichever team `player_id` belongs
        to, independent of ball possession -- safe to call right after
        a turnover flips possession, unlike possession_user_id.
        """
        side = (
            TeamSide.HOME
            if player_id in match.home.field_players
            else TeamSide.VISITING
        )
        number = (
            game.home_player_number
            if side == TeamSide.HOME
            else game.visiting_player_number
        )
        if number == 1:
            return game.player_1_id
        if number == 2:
            return game.player_2_id
        return None

    def side_controlled_by_ai(
        self,
        game: D12BallGame,
        match: MatchState,
        side: str,
    ) -> bool:
        if not game.is_solo_game:
            return False
        number = (
            self.possession_player_number(game, match)
            if side == "offense"
            else self.defending_player_number(game, match)
        )
        return number == 2

    def build_effect_choice_view(
        self,
        game_id: str,
        match: MatchState,
    ) -> Optional[discord.ui.View]:
        """
        Reconstruct whichever initial effect-choice prompt is pending
        for a decisively-won maneuver, purely from match state -- used
        both to restore it on a bot restart and (implicitly, by the
        same logic) to post it the first time. Returns None for a
        maneuver that needs no choice (Block Deflect, Pressure) or an
        unrecognized winner -- those resolve synchronously and should
        never actually leave this state persisted except in a narrow
        crash window, which falls back to PlayerActionView.
        """
        outcome = self.maneuver_catalog.resolve(
            match.offense_maneuver, match.defense_maneuver,
        )
        if outcome == "tie":
            return None
        winner_name = (
            match.offense_maneuver
            if outcome == "offense"
            else match.defense_maneuver
        )
        if winner_name == "Low Pass":
            return LowPassChoiceView(self, game_id)
        if winner_name == "High Pass":
            return HighPassChoiceView(self, game_id)
        if winner_name == "Dribble Advance":
            return SpeedDeltaChoiceView(
                self, game_id, match.active_player_id, "offense",
            )
        if winner_name == "Steal Intercept":
            return SpeedDeltaChoiceView(
                self, game_id, match.challenger_id, "defense",
            )
        return None

    def build_run_back_view(
        self,
        game_id: str,
        match: MatchState,
    ) -> Optional[discord.ui.View]:
        """
        Reconstruct the run-back prompt for whichever displaced player
        still needs a real choice. Any forced placements are always
        applied immediately in continue_run_back, before a message is
        ever posted, so anyone still displaced by the time this is
        called needs an actual choice.
        """
        for side in (TeamSide.HOME, TeamSide.VISITING):
            displaced = match.displaced_players(side)
            if displaced:
                return RunBackChoiceView(self, game_id, displaced[0])
        return None

    async def begin_effect_resolution(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        winner_name: str,
    ) -> None:
        """
        Dispatch a decisively-won maneuver to its effect.
        `offense_maneuver`/`defense_maneuver`/`active_player_id`/
        `challenger_id` all stay set until the whole pipeline (effect,
        any run-back, time) finishes -- reset_maneuver() only happens
        at the very end, in finish_maneuver_resolution -- so a bot
        restart mid-choice can still reconstruct exactly where things
        left off (see build_effect_choice_view).
        """
        handlers = {
            "Low Pass": self.resolve_low_pass,
            "Dribble Advance": self.resolve_dribble_advance,
            "High Pass": self.resolve_high_pass,
            "Block Deflect": self.resolve_block_deflect,
            "Steal Intercept": self.resolve_steal_intercept,
            "Pressure": self.resolve_pressure,
        }
        handler = handlers.get(winner_name)
        if handler is None:
            # Unrecognized maneuver name (future data) -- nothing to
            # automate; leave it to a human, same as before this pass.
            await self.finish_maneuver_resolution(interaction, game, match)
            return
        await handler(interaction, game, match)

    # -- Low Pass --------------------------------------------------

    async def resolve_low_pass(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        if self.side_controlled_by_ai(game, match, "offense"):
            direction, distance = self.get_ai_strategy(
                game
            ).choose_low_pass(match)
            await self.apply_low_pass(
                interaction, game, match, direction, distance
            )
            return

        mention = format_player_with_team(
            game,
            self.possession_player_number(game, match),
            mention=True,
        )
        prompt_message = await interaction.followup.send(
            f"{mention}, choose your Low Pass:",
            view=LowPassChoiceView(self, game.game_id),
            wait=True,
            allowed_mentions=discord.AllowedMentions(
                users=True, roles=False, everyone=False,
            ),
        )
        game.turn_message_id = prompt_message.id
        save_games(self.games)

    async def apply_low_pass(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        direction: str,
        distance: int,
    ) -> None:
        offense_side = match.ball.possession
        signed_distance = distance if direction == "forward" else -distance

        # An "overshoot" is the deflection/pass being clamped short of
        # the requested distance, i.e. it would have pushed the ball
        # past the space closest to a goal (there's no space beyond
        # that one to land on) -- own-goal risk backward, a scoring
        # opportunity forward.
        origin_flat = match.board.flat_index(
            match.ball.zone, match.ball.space_index,
        )
        target_flat = match.relative_flat_index(
            origin_flat, offense_side, signed_distance,
        )
        overshot = abs(target_flat - origin_flat) < distance

        actual_distance = match.move_ball_relative(offense_side, signed_distance)
        match.ball.speed = min(12, match.ball.speed + 1)
        game.match_state = match.to_dict()
        save_games(self.games)

        space_word = "space" if actual_distance == 1 else "spaces"
        content = (
            f"**Low Pass:** the ball moves {actual_distance} {space_word} "
            f"{direction}. Ball speed is now {match.ball.speed}."
        )

        if direction == "backward" and overshot:
            await interaction.followup.send(
                f"{content}\n\nThat overshoots toward their own goal!",
            )
            await self.refresh_match_image(interaction, game)
            await self.run_own_goal_roll(interaction, game, match)
            return

        # Role ability -- Winger: can also set up a scoring opportunity
        # with a Low Pass, same overshoot-and-occupied-space rule as a
        # High Pass normally uses.
        handler = self.get_player_definition(match.active_player_id)
        candidates = []
        if direction == "forward" and overshot and handler.role == PlayerRole.WINGER:
            candidates = self.scoring_opportunity_candidates(
                match, offense_side,
            )

        if not candidates:
            await self.refresh_match_image(interaction, game)
            if self.is_landing_space_empty(match):
                await self.begin_loose_ball(
                    interaction,
                    game,
                    match,
                    actual_distance,
                    lead_in=content,
                )
            else:
                await self.finish_maneuver_resolution(
                    interaction,
                    game,
                    match,
                    distance_moved=actual_distance,
                    lead_in=content,
                )
            return

        await self.refresh_match_image(interaction, game)
        await self.begin_shooter_choice(
            interaction,
            game,
            match,
            candidates,
            lead_in=(
                f"{content} That overshoots the field -- "
                f"{format_role_bracket(handler, self.team_emojis)}'s Winger "
                "ability sets up a scoring opportunity!"
            ),
        )

    # -- Dribble Advance ---------------------------------------------

    async def resolve_dribble_advance(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        offense_side = match.ball.possession
        match.move_player_relative(match.active_player_id, offense_side, 1)
        match.set_ball_space(
            *match.board.meeple_position(match.active_player_id)
        )
        game.match_state = match.to_dict()
        save_games(self.games)

        handler = self.get_player_definition(match.active_player_id)
        await self.refresh_match_image(interaction, game)

        await self.offer_speed_choice(
            interaction,
            game,
            match,
            player_id=match.active_player_id,
            skill_type="offense",
            after_turnover=False,
            lead_in=(
                f"**Dribble Advance:** "
                f"{format_role_bracket(handler, self.team_emojis)} and the "
                "ball move forward 1 space."
            ),
        )

    # -- High Pass -----------------------------------------------------

    async def resolve_high_pass(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        if self.side_controlled_by_ai(game, match, "offense"):
            distance = self.get_ai_strategy(game).choose_high_pass_distance(
                match
            )
            await self.apply_high_pass(interaction, game, match, distance)
            return

        mention = format_player_with_team(
            game,
            self.possession_player_number(game, match),
            mention=True,
        )
        prompt_message = await interaction.followup.send(
            f"{mention}, choose your High Pass distance:",
            view=HighPassChoiceView(self, game.game_id),
            wait=True,
            allowed_mentions=discord.AllowedMentions(
                users=True, roles=False, everyone=False,
            ),
        )
        game.turn_message_id = prompt_message.id
        save_games(self.games)

    async def apply_high_pass(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        distance: int,
    ) -> None:
        offense_side = match.ball.possession
        origin_flat = match.board.flat_index(
            match.ball.zone, match.ball.space_index
        )
        target_flat = match.relative_flat_index(
            origin_flat, offense_side, distance
        )
        overshot = abs(target_flat - origin_flat) < distance

        actual_distance = match.move_ball_relative(offense_side, distance)
        game.match_state = match.to_dict()
        save_games(self.games)

        space_word = "space" if actual_distance == 1 else "spaces"
        content = (
            f"**High Pass:** the ball moves {actual_distance} {space_word} "
            "forward."
        )

        candidates = []
        if overshot:
            candidates = self.scoring_opportunity_candidates(
                match, offense_side,
            )

        if not candidates:
            await self.refresh_match_image(interaction, game)
            if self.is_landing_space_empty(match):
                await self.begin_loose_ball(
                    interaction,
                    game,
                    match,
                    actual_distance,
                    lead_in=content,
                )
            else:
                await self.finish_maneuver_resolution(
                    interaction,
                    game,
                    match,
                    distance_moved=actual_distance,
                    lead_in=content,
                )
            return

        await self.refresh_match_image(interaction, game)
        await self.begin_shooter_choice(
            interaction,
            game,
            match,
            candidates,
            lead_in=f"{content} That overshoots the field -- a scoring "
            "opportunity!",
        )

    def scoring_opportunity_candidates(
        self,
        match: MatchState,
        offense_side: TeamSide,
    ) -> list[str]:
        """
        Offensive players occupying the ball's current (overshot)
        space -- the field of shooter candidates a set-up offers,
        shared by High Pass and a Winger's Low Pass.
        """
        offense_setup = match.setup_for_side(offense_side)
        occupants = match.board.spaces[match.ball.zone][
            match.ball.space_index
        ]
        return [
            player_id
            for player_id in occupants
            if player_id in offense_setup.field_players
        ]

    # -- Loose ball (a pass landing on an empty space) -----------------

    def is_landing_space_empty(self, match: MatchState) -> bool:
        return not match.board.spaces[match.ball.zone][match.ball.space_index]

    def loose_ball_candidates(
        self,
        match: MatchState,
        side: TeamSide,
    ) -> list[str]:
        zone_candidates = match.fielded_players_in_zone(side, match.ball.zone)
        if zone_candidates:
            return zone_candidates

        # "Out of bounds": neither side has anyone in the landing
        # zone. The defense always gains possession in that case, and
        # must send a player from anywhere on the field to reach the
        # ball -- offense never gets this fallback, since they're the
        # side losing possession.
        if side == match.defending_side() and not match.fielded_players_in_zone(
            match.ball.possession, match.ball.zone,
        ):
            return match.setup_for_side(side).field_players
        return []

    def loose_ball_sides_ready(
        self,
        match: MatchState,
    ) -> tuple[bool, bool]:
        """
        Whether the offense/defense pick is settled -- either made, or
        moot because that side has nobody in the zone to send.
        """
        offense_candidates = self.loose_ball_candidates(
            match, match.ball.possession,
        )
        defense_candidates = self.loose_ball_candidates(
            match, match.defending_side(),
        )
        offense_ready = (
            match.loose_ball_offense_player is not None
            or not offense_candidates
        )
        defense_ready = (
            match.loose_ball_defense_player is not None
            or not defense_candidates
        )
        return offense_ready, defense_ready

    def auto_resolve_loose_ball_picks(
        self,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        Settle whichever side doesn't need (or can't get) a real human
        choice: AI-controlled, or exactly one candidate. A side with no
        candidates at all is left unset -- resolve_loose_ball reads
        that as "nobody available", not "still deciding".
        """
        for side, skill_type, choose in (
            (
                match.ball.possession,
                "offense",
                match.choose_loose_ball_offense_player,
            ),
            (
                match.defending_side(),
                "defense",
                match.choose_loose_ball_defense_player,
            ),
        ):
            already_picked = (
                match.loose_ball_offense_player
                if skill_type == "offense"
                else match.loose_ball_defense_player
            ) is not None
            if already_picked:
                continue

            candidates = self.loose_ball_candidates(match, side)
            if not candidates:
                continue
            if len(candidates) == 1:
                choose(candidates[0])
            elif self.side_controlled_by_ai(game, match, skill_type):
                choose(
                    self.get_ai_strategy(game).choose_loose_ball_player(
                        candidates, skill_type,
                    )
                )

    def build_loose_ball_view(
        self,
        game_id: str,
        match: MatchState,
    ) -> Optional[discord.ui.View]:
        """
        Reconstruct the loose-ball pick prompt for whichever side(s)
        still need a real human choice (2+ candidates, not yet picked)
        -- purely from match state, so a bot restart mid-pick
        reconstructs correctly, same as build_run_back_view.
        """
        entries: list[tuple[str, list[str]]] = []
        if match.loose_ball_offense_player is None:
            candidates = self.loose_ball_candidates(
                match, match.ball.possession,
            )
            if len(candidates) > 1:
                entries.append(("offense", candidates))
        if match.loose_ball_defense_player is None:
            candidates = self.loose_ball_candidates(
                match, match.defending_side(),
            )
            if len(candidates) > 1:
                entries.append(("defense", candidates))
        if not entries:
            return None
        return LooseBallChoiceView(self, game_id, entries)

    async def begin_loose_ball(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        distance_moved: int,
        lead_in: str = "",
    ) -> None:
        """
        `distance_moved` (the pass's own clamped travel) is stashed on
        `match` by begin_loose_ball() -- the pick and, if it comes to
        one, the skill test both span later interactions that can't
        see a Python-level parameter from this call, so everything
        downstream reads it back from match state instead.

        `lead_in` is narration from the pass that hasn't been posted
        yet -- it rides along on this function's own first message.
        """
        match.begin_loose_ball(distance_moved)
        self.auto_resolve_loose_ball_picks(game, match)
        game.match_state = match.to_dict()
        save_games(self.games)

        prefix = f"{lead_in}\n\n" if lead_in else ""
        await interaction.followup.send(
            f"{prefix}**Loose ball!** The pass lands in an empty space -- "
            "each side may send a nearby player to contest it."
        )

        offense_ready, defense_ready = self.loose_ball_sides_ready(match)
        if offense_ready and defense_ready:
            await self.resolve_loose_ball(interaction, game, match)
            return

        waiting_on = []
        if not offense_ready:
            waiting_on.append(
                format_player_with_team(
                    game,
                    self.possession_player_number(game, match),
                    mention=True,
                )
            )
        if not defense_ready:
            waiting_on.append(
                format_player_with_team(
                    game,
                    self.defending_player_number(game, match),
                    mention=True,
                )
            )

        prompt_message = await interaction.followup.send(
            f"{' and '.join(waiting_on)}, choose who contests it:",
            view=self.build_loose_ball_view(game.game_id, match),
            wait=True,
            allowed_mentions=discord.AllowedMentions(
                users=True, roles=False, everyone=False,
            ),
        )
        game.turn_message_id = prompt_message.id
        save_games(self.games)

    async def resolve_loose_ball(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        offense_player_id = match.loose_ball_offense_player
        defense_player_id = match.loose_ball_defense_player
        distance_moved = match.pending_loose_ball_distance

        if offense_player_id is None and defense_player_id is None:
            # Degenerate edge case only: the defense fallback in
            # loose_ball_candidates() means this shouldn't happen while
            # the defending side has any fielded players at all.
            match.pending_loose_ball = False
            game.match_state = match.to_dict()
            save_games(self.games)
            await interaction.followup.send(
                "Nobody is nearby to contest it -- the ball stays where "
                "it landed."
            )
            await self.begin_run_back(
                interaction, game, match,
                distance_moved=distance_moved, turnover_occurred=False,
            )
            return

        if defense_player_id is None:
            player = self.get_player_definition(offense_player_id)
            recovery_distance = match.distance_to_ball(offense_player_id)
            match.move_meeple(
                offense_player_id, match.ball.zone, match.ball.space_index,
            )
            match.add_exhaustion(offense_player_id, recovery_distance)
            match.pending_loose_ball = False
            game.match_state = match.to_dict()
            save_games(self.games)

            await interaction.followup.send(
                f"{format_role_bracket(player, self.team_emojis)} "
                "recovers the loose ball uncontested.\n"
                + self.describe_exhaustion_gain(
                    match, offense_player_id, recovery_distance,
                )
            )
            await self.refresh_match_image(interaction, game)
            await self.begin_run_back(
                interaction, game, match,
                distance_moved=distance_moved, turnover_occurred=False,
            )
            return

        if offense_player_id is None:
            # "Out of bounds" if the defense pick came from the
            # whole-team fallback rather than a real zone-mate -- there
            # was nobody from either side in the zone at all.
            out_of_bounds = not match.fielded_players_in_zone(
                match.ball.possession, match.ball.zone,
            ) and not match.fielded_players_in_zone(
                match.defending_side(), match.ball.zone,
            )

            player = self.get_player_definition(defense_player_id)
            recovery_distance = match.distance_to_ball(defense_player_id)
            match.move_meeple(
                defense_player_id, match.ball.zone, match.ball.space_index,
            )
            match.add_exhaustion(defense_player_id, recovery_distance)
            match.ball.possession = match.defending_side()
            match.ball.speed = 1
            match.pending_loose_ball = False
            game.match_state = match.to_dict()
            save_games(self.games)

            headline = (
                "**Out of bounds!**" if out_of_bounds
                else f"{format_role_bracket(player, self.team_emojis)} "
                "recovers the loose ball uncontested."
            )
            await interaction.followup.send(
                "# Turnover!\n"
                f"{headline} "
                f"{format_team_side_label(match.setup_for_side(match.ball.possession))} "
                f"now has possession -- {format_role_bracket(player, self.team_emojis)} "
                "gets to the ball.\n"
                + self.describe_exhaustion_gain(
                    match, defense_player_id, recovery_distance,
                )
            )
            await self.refresh_match_image(interaction, game)
            await self.begin_run_back(
                interaction, game, match,
                distance_moved=distance_moved, turnover_occurred=True,
            )
            return

        # Both sides have a candidate -- move them both in and run the
        # actual skill test.
        match.move_meeple(
            offense_player_id, match.ball.zone, match.ball.space_index,
        )
        match.move_meeple(
            defense_player_id, match.ball.zone, match.ball.space_index,
        )
        game.match_state = match.to_dict()
        save_games(self.games)
        await self.refresh_match_image(interaction, game)

        offense_player = self.get_player_definition(offense_player_id)
        defense_player = self.get_player_definition(defense_player_id)
        offense_skill = self.player_catalog.effective_profile(
            offense_player,
        ).offense
        defense_skill = self.player_catalog.effective_profile(
            defense_player,
        ).defense

        test_message = await interaction.followup.send(
            f"{format_role_bracket(offense_player, self.team_emojis)} "
            f"(offense skill {offense_skill}) and "
            f"{format_role_bracket(defense_player, self.team_emojis)} "
            f"(defense skill {defense_skill}) both reach the loose "
            "ball -- skill test!\n\nEither player can roll:",
            view=LooseBallSkillTestView(self, game.game_id),
            wait=True,
        )
        game.turn_message_id = test_message.id
        save_games(self.games)

    async def begin_shooter_choice(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        candidates: list[str],
        lead_in: str = "",
    ) -> None:
        """
        `lead_in` is narration from the pass that set this scoring
        opportunity up -- it rides along on the "choose who takes the
        shot" prompt when a human has to pick. When the pick is
        automatic there's no prompt to attach it to, so it's posted on
        its own instead of being dropped.
        """
        if len(candidates) == 1 or self.side_controlled_by_ai(
            game, match, "offense",
        ):
            if len(candidates) == 1:
                shooter_id = candidates[0]
            else:
                shooter_id = self.get_ai_strategy(game).choose_shooter(
                    candidates, match,
                )
            if lead_in:
                await interaction.followup.send(lead_in)
            await self.start_set_up_shot(interaction, game, match, shooter_id)
            return

        mention = format_player_with_team(
            game,
            self.possession_player_number(game, match),
            mention=True,
        )
        prefix = f"{lead_in}\n\n" if lead_in else ""
        prompt_message = await interaction.followup.send(
            f"{prefix}{mention}, choose who takes the shot:",
            view=ShooterChoiceView(self, game.game_id, candidates),
            wait=True,
            allowed_mentions=discord.AllowedMentions(
                users=True, roles=False, everyone=False,
            ),
        )
        game.turn_message_id = prompt_message.id
        save_games(self.games)

    async def start_set_up_shot(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        shooter_id: str,
    ) -> None:
        match.active_player_id = shooter_id
        match.pending_action = "shoot"
        match.pending_shot_is_set_up = True
        game.match_state = match.to_dict()
        save_games(self.games)

        shooter = self.get_player_definition(shooter_id)
        await interaction.followup.send(
            f"{format_role_bracket(shooter, self.team_emojis)} takes the "
            "shot off the set-up."
        )
        await self.begin_score_attempt(interaction, game, match)

    # -- Block Deflect -------------------------------------------------

    async def resolve_block_deflect(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        offense_side = match.ball.possession

        # Overshoot: the deflection is clamped short of the full 2
        # spaces, i.e. it would have pushed the ball past the space
        # closest to the offense's own goal -- that's the own-goal
        # risk, not merely landing on that space.
        origin_flat = match.board.flat_index(
            match.ball.zone, match.ball.space_index,
        )
        target_flat = match.relative_flat_index(origin_flat, offense_side, -2)
        overshot = abs(target_flat - origin_flat) < 2

        actual_distance = match.move_ball_relative(offense_side, -2)
        match.ball.speed = max(1, match.ball.speed - 1)
        game.match_state = match.to_dict()
        save_games(self.games)

        space_word = "space" if actual_distance == 1 else "spaces"
        content = (
            f"**Block Deflect:** the ball moves {actual_distance} "
            f"{space_word} back. Ball speed is now {match.ball.speed}."
        )

        if overshot:
            await interaction.followup.send(
                f"{content}\n\nThat overshoots toward their own goal!",
            )
            await self.refresh_match_image(interaction, game)
            await self.run_own_goal_roll(interaction, game, match)
            return

        await self.refresh_match_image(interaction, game)
        # Block Deflect's time cost is a fixed 2 space minutes per the
        # rules table, not "distance traveled" like Low/High Pass, so
        # this doesn't shrink if the move was clamped at the edge.
        await self.finish_maneuver_resolution(
            interaction, game, match, distance_moved=2, lead_in=content,
        )

    # -- Steal Intercept -------------------------------------------------

    async def resolve_steal_intercept(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        new_possession_side = match.defending_side()
        challenger_id = match.challenger_id

        # The turnover happens first, then both the interceptor and the
        # ball fall back 1 space -- toward the *new* possessing side's
        # own goal, not the old side's. Moving the challenger's meeple
        # (not just the ball) and re-deriving the ball's space from it
        # keeps the two in the same space, so possession can be assigned
        # directly without set_possession's occupancy check.
        match.ball.possession = new_possession_side
        # Every turnover drops the ball's speed back to 1 -- the
        # defender's manipulate-speed choice below applies to that
        # reset value, not whatever the speed was before the steal.
        match.ball.speed = 1
        actual_distance = match.move_player_relative(
            challenger_id, new_possession_side, -1,
        )
        match.set_ball_space(*match.board.meeple_position(challenger_id))
        game.match_state = match.to_dict()
        save_games(self.games)

        space_word = "space" if actual_distance == 1 else "spaces"
        challenger = self.get_player_definition(challenger_id)
        new_possession = match.setup_for_side(match.ball.possession)
        await self.refresh_match_image(interaction, game)

        await self.offer_speed_choice(
            interaction,
            game,
            match,
            player_id=challenger_id,
            skill_type="defense",
            after_turnover=True,
            lead_in=(
                "**Steal Intercept:**\n"
                "# Turnover!\n"
                f"{format_role_bracket(challenger, self.team_emojis)} "
                f"steals the ball. "
                f"{format_team_side_label(new_possession)} now has "
                f"possession, then falls back {actual_distance} "
                f"{space_word} toward their own goal with the ball."
            ),
        )

    # -- Pressure --------------------------------------------------------

    async def resolve_pressure(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        offense_side = match.ball.possession
        defense_side = match.defending_side()

        actual_distance = match.move_player_relative(
            match.active_player_id, offense_side, -1,
        )
        match.set_ball_space(
            *match.board.meeple_position(match.active_player_id)
        )
        match.move_player_relative(match.challenger_id, defense_side, 1)

        handler = self.get_player_definition(match.active_player_id)
        defender = self.get_player_definition(match.challenger_id)
        space_word = "space" if actual_distance == 1 else "spaces"
        content = (
            f"**Pressure:** "
            f"{format_role_bracket(handler, self.team_emojis)} and the "
            f"ball go back {actual_distance} {space_word}. "
            f"{format_role_bracket(defender, self.team_emojis)} moves "
            "forward."
        )

        # Role ability -- Defender: also steals the ball on a Pressure
        # win, on top of the normal effect above.
        stolen = defender.role == PlayerRole.DEFENDER
        if stolen:
            match.ball.possession = defense_side
            match.ball.speed = 1
            content += (
                "\n\n# Turnover!\n"
                f"{format_role_bracket(defender, self.team_emojis)} "
                "steals the ball (Defender ability)! "
                f"{format_team_side_label(match.setup_for_side(defense_side))} "
                "now has possession."
            )

        game.match_state = match.to_dict()
        save_games(self.games)

        await self.refresh_match_image(interaction, game)

        # Fixed 1 space minute per the rules table, independent of
        # clamping, same reasoning as Block Deflect above.
        if stolen:
            await self.begin_run_back(interaction, game, match, lead_in=content)
        else:
            await self.finish_maneuver_resolution(
                interaction, game, match, distance_moved=1, lead_in=content,
            )

    # -- Ball-speed manipulation (Dribble Advance / Steal Intercept) --

    async def offer_speed_choice(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        player_id: str,
        skill_type: str,
        after_turnover: bool,
        lead_in: str = "",
    ) -> None:
        """
        `lead_in` is narration from the maneuver that led here -- it
        rides along on the speed-choice prompt when a human picks, or
        gets forwarded to apply_speed_choice to ride along on its own
        message when the pick is automatic.
        """
        skill = self.player_catalog.effective_profile(
            self.get_player_definition(player_id),
        )
        skill_value = skill.offense if skill_type == "offense" else skill.defense

        controller_id = self.controlling_user_id(game, match, player_id)
        is_ai = game.is_solo_game and controller_id == game.player_2_id

        if is_ai:
            delta = self.get_ai_strategy(game).choose_speed_delta(skill_value)
            target_speed = max(1, min(12, match.ball.speed + delta))
            await self.apply_speed_choice(
                interaction,
                game,
                match,
                target_speed,
                after_turnover,
                lead_in=lead_in,
            )
            return

        mention = f"<@{controller_id}>" if controller_id else "Someone"
        prefix = f"{lead_in}\n\n" if lead_in else ""
        prompt_message = await interaction.followup.send(
            f"{prefix}{mention}, manipulate the ball's speed (up to "
            f"{skill_value}):",
            view=SpeedDeltaChoiceView(
                self, game.game_id, player_id, skill_type,
            ),
            wait=True,
            allowed_mentions=discord.AllowedMentions(
                users=True, roles=False, everyone=False,
            ),
        )
        game.turn_message_id = prompt_message.id
        save_games(self.games)

    async def apply_speed_choice(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        target_speed: int,
        after_turnover: bool,
        lead_in: str = "",
    ) -> None:
        match.ball.speed = target_speed
        game.match_state = match.to_dict()
        save_games(self.games)

        prefix = f"{lead_in}\n\n" if lead_in else ""
        await interaction.followup.send(
            f"{prefix}Ball speed is now **{target_speed}**."
        )
        await self.refresh_match_image(interaction, game)

        if after_turnover:
            await self.begin_run_back(interaction, game, match)
        else:
            await self.finish_maneuver_resolution(
                interaction, game, match, distance_moved=1,
            )

    # -- Own goal ----------------------------------------------------

    async def run_own_goal_roll(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        Automatic: 2d12 at a disadvantage (take the lower), plus the
        ball-handler's offensive skill, safe on 7+. No button -- there's
        no opposing roll to wait for.

        Role ability -- Fullback: exempt from the disadvantage, so they
        roll a single d12 instead.
        """
        offense_player = self.get_player_definition(match.active_player_id)
        offense_skill = self.player_catalog.effective_profile(
            offense_player,
        ).offense
        is_fullback = offense_player.role == PlayerRole.FULLBACK

        if is_fullback:
            rolls = (random.randint(1, 12),)
        else:
            rolls = (random.randint(1, 12), random.randint(1, 12))
        taken = min(rolls)
        total = taken + offense_skill

        offense_setup = match.setup_for_side(match.ball.possession)
        dice_file = discord.File(
            render_dice_row(
                [
                    (value, TEAM_COLORS[offense_setup.team], "Rolled")
                    for value in rolls
                ]
            ),
            filename="own_goal_dice.png",
        )

        if is_fullback:
            roll_description = (
                f"rolls without disadvantage (Fullback ability): {taken}"
            )
        else:
            roll_description = (
                f"rolls at a disadvantage: lower of {rolls[0]}/{rolls[1]} "
                f"is {taken}"
            )

        safe = total >= 7
        if safe:
            content = (
                f"**Own goal risk!** "
                f"{format_role_bracket(offense_player, self.team_emojis)} "
                f"{roll_description}, + {offense_skill} (offensive skill) "
                f"= {total} -- safe."
            )
        else:
            match.concede_own_goal()
            content = (
                f"**Own goal risk!** "
                f"{format_role_bracket(offense_player, self.team_emojis)} "
                f"{roll_description}, + {offense_skill} (offensive skill) "
                f"= {total} -- **OWN GOAL!**\n"
                f"{match.home.team.value.title()} {match.scoreboard.home_score}:"
                f"{match.scoreboard.visiting_score} "
                f"{match.visiting.team.value.title()}"
            )

        game.match_state = match.to_dict()
        save_games(self.games)

        await interaction.followup.send(content, file=dice_file)
        await self.refresh_match_image(interaction, game)
        await self.finish_maneuver_resolution(interaction, game, match)

    # -- Run-back (after a turnover) ----------------------------------

    def run_back_side_is_ai(
        self,
        game: D12BallGame,
        side: TeamSide,
    ) -> bool:
        if not game.is_solo_game:
            return False
        number = (
            game.home_player_number
            if side == TeamSide.HOME
            else game.visiting_player_number
        )
        return number == 2

    async def begin_run_back(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        distance_moved: int = 1,
        turnover_occurred: bool = True,
        lead_in: str = "",
    ) -> None:
        """
        `distance_moved`/`turnover_occurred` describe the maneuver that
        triggered this run-back, stashed on `match` so they survive the
        multi-turn choice flow and reach finish_maneuver_resolution
        correctly once run-back itself (which only ever costs
        exhaustion, never time) is done.

        `lead_in` is narration from the triggering effect that hasn't
        been posted yet -- it rides along on whichever message this
        run-back sends first (see continue_run_back).
        """
        match.pending_run_back = True
        match.pending_run_back_distance = distance_moved
        match.pending_run_back_turnover = turnover_occurred
        game.match_state = match.to_dict()
        save_games(self.games)
        await self.continue_run_back(interaction, game, match, lead_in=lead_in)

    async def continue_run_back(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        lead_in: str = "",
    ) -> None:
        """
        Auto-place every forced run-back (no real choice: the open
        spaces in a zone exactly match the players who need one) right
        away, then either present a choice for the next player who has
        a real one, or finish once nobody is displaced.

        `lead_in` only ever applies to the first message this call (or
        its chain of recursive/resumed calls) sends -- every call site
        that already consumed it passes none, including this method's
        own recursion and the human-choice resumption in
        RunBackChoiceView.
        """
        applied_forced = True
        while applied_forced:
            applied_forced = False
            for side in (TeamSide.HOME, TeamSide.VISITING):
                by_zone: dict[Zone, list[str]] = {}
                for player_id in match.displaced_players(side):
                    zone = match.setup_for_side(side).assigned_zone(
                        player_id
                    )
                    by_zone.setdefault(zone, []).append(player_id)

                for zone, players in by_zone.items():
                    open_spaces = match.open_spaces_in_zone(side, zone)
                    if len(open_spaces) != len(players):
                        continue
                    for player_id, space_index in zip(players, open_spaces):
                        distance = match.run_back_player(
                            player_id, zone, space_index,
                        )
                        match.add_exhaustion(player_id, distance)
                    applied_forced = True

        game.match_state = match.to_dict()
        save_games(self.games)

        for side in (TeamSide.HOME, TeamSide.VISITING):
            displaced = match.displaced_players(side)
            if not displaced:
                continue

            player_id = displaced[0]
            zone = match.setup_for_side(side).assigned_zone(player_id)
            open_spaces = match.open_spaces_in_zone(side, zone)
            player = self.get_player_definition(player_id)

            if self.run_back_side_is_ai(game, side):
                space_index = self.get_ai_strategy(
                    game
                ).choose_run_back_space(open_spaces)
                distance = match.run_back_player(player_id, zone, space_index)
                match.add_exhaustion(player_id, distance)
                game.match_state = match.to_dict()
                save_games(self.games)

                prefix = f"{lead_in}\n\n" if lead_in else ""
                await interaction.followup.send(
                    f"{prefix}"
                    f"{format_role_bracket(player, self.team_emojis)} runs "
                    f"back to {space_label(zone, space_index)}.\n"
                    + self.describe_exhaustion_gain(
                        match, player_id, distance,
                    )
                )
                await self.refresh_match_image(interaction, game)
                await self.continue_run_back(interaction, game, match)
                return

            controller_number = (
                game.home_player_number
                if side == TeamSide.HOME
                else game.visiting_player_number
            )
            controller_id = (
                game.player_1_id
                if controller_number == 1
                else game.player_2_id
            )
            mention = f"<@{controller_id}>" if controller_id else "Someone"
            prefix = f"{lead_in}\n\n" if lead_in else ""
            prompt_message = await interaction.followup.send(
                f"{prefix}{mention}, choose where "
                f"{format_role_bracket(player, self.team_emojis)} runs "
                "back to:",
                view=RunBackChoiceView(self, game.game_id, player_id),
                wait=True,
                allowed_mentions=discord.AllowedMentions(
                    users=True, roles=False, everyone=False,
                ),
            )
            game.turn_message_id = prompt_message.id
            save_games(self.games)
            return

        # Nobody is displaced on either side -- run-back is done.
        match.pending_run_back = False
        distance_moved = match.pending_run_back_distance
        turnover_occurred = match.pending_run_back_turnover
        game.match_state = match.to_dict()
        save_games(self.games)
        # Run-back itself only ever costs exhaustion, not time -- the
        # time cost is whatever the triggering maneuver's own ball
        # movement was, stashed by begin_run_back.
        await self.finish_maneuver_resolution(
            interaction,
            game,
            match,
            distance_moved=distance_moved,
            turnover_occurred=turnover_occurred,
            lead_in=lead_in,
        )

    # -- Clock, period transitions, and the turn loop -----------------

    async def finish_maneuver_resolution(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        distance_moved: int = 1,
        turnover_occurred: bool = False,
        lead_in: str = "",
    ) -> None:
        """
        The tail of every maneuver-effect path once movement, speed,
        any turnover, and run-back are all settled: advance the clock,
        end the period if this turnover closes out last possession,
        clear the maneuver state, and hand the offensive choice back to
        whoever now has the ball.

        `lead_in`, if given, is narration from earlier in the same
        effect that hasn't been posted yet -- it rides along on this
        function's own first message instead of being sent separately,
        so a deterministic effect (no further human choice in between)
        reads as one message rather than a chain of them.
        """
        entered_last_possession = match.advance_time(distance_moved)
        if entered_last_possession:
            prefix = f"{lead_in}\n\n" if lead_in else ""
            await interaction.followup.send(
                f"{prefix}The clock reaches 15 -- this is now **last "
                "possession**. Play continues until the ball turns over, "
                "which ends the period."
            )
            lead_in = ""

        if turnover_occurred and match.scoreboard.last_possession:
            await self.end_period(interaction, game, match, lead_in=lead_in)
            return

        match.reset_maneuver()
        game.match_state = match.to_dict()
        save_games(self.games)

        # One last board refresh with everything settled (run-back,
        # speed choice, own-goal, etc. may have landed after the last
        # refresh inside the effect itself), right before the
        # offensive choice comes back up.
        await self.refresh_match_image(interaction, game)

        prefix = f"{lead_in}\n\n" if lead_in else ""
        snapshot = await interaction.followup.send(
            content=(
                f"{prefix}Ball is now "
                f"{space_label(match.ball.zone, match.ball.space_index)}, "
                f"{format_team_side_label(match.setup_for_side(match.ball.possession))} "
                f"has possession. Time has advanced {distance_moved}, now "
                f"at {match.scoreboard.time:02d}."
            ),
            file=self.build_match_file(game),
            wait=True,
        )
        await add_full_image_button(snapshot)

        try:
            await self.send_turn_prompt(interaction, game)
        except ValueError as error:
            await interaction.followup.send(str(error), ephemeral=True)

    async def end_period(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        lead_in: str = "",
    ) -> None:
        """
        The turnover that closes out last possession: transition to the
        second half, or end the game at full time. Halftime recovery,
        formation changes, substitutions, and the extreme shootout are
        all out of scope here -- announced as hand-apply instructions,
        the same way score-attempt cleanup already defers its own
        unautomated pieces.
        """
        prefix = f"{lead_in}\n\n" if lead_in else ""

        if match.scoreboard.period == MatchPeriod.FIRST_HALF:
            match.scoreboard.period = MatchPeriod.SECOND_HALF
            match.scoreboard.time = 0
            match.scoreboard.last_possession = False
            kickoff_index = kickoff_space_index(
                len(match.board.spaces[Zone.MIDFIELD]),
                TeamSide.VISITING,
            )
            match.set_ball_space(Zone.MIDFIELD, kickoff_index)
            match.ball.possession = TeamSide.VISITING
            match.ball.speed = 1
            match.reset_maneuver()
            game.match_state = match.to_dict()
            save_games(self.games)

            await interaction.followup.send(
                f"{prefix}**End of the first half!** The clock reaches 15 "
                "and the ball turns over -- the period ends.\n\n"
                "Cleanup -- apply by hand:\n"
                "- Fielded players lose 1 exhaustion token\n"
                "- One player of the coach's choice loses an extra "
                "exhaustion token\n"
                "- Formations may be changed, and players may need "
                "repositioning to their assigned zones\n\n"
                "The second half kicks off with "
                f"{format_team_side_label(match.visiting)} in "
                "possession."
            )
            await self.refresh_match_image(interaction, game)

            try:
                await self.send_turn_prompt(interaction, game)
            except ValueError as error:
                await interaction.followup.send(str(error), ephemeral=True)
            return

        match.reset_maneuver()
        game.match_state = match.to_dict()
        save_games(self.games)
        game.finish_game()
        save_games(self.games)

        home_score = match.scoreboard.home_score
        visiting_score = match.scoreboard.visiting_score
        result = (
            "It's a tie! This would go to an extreme shootout, which "
            "isn't implemented yet."
            if home_score == visiting_score
            else "Full time."
        )
        await interaction.followup.send(
            f"{prefix}**Full time!** The clock reaches 15 and the ball "
            "turns over -- the game ends.\n\n"
            f"Final score: {match.home.team.value.title()} {home_score}:"
            f"{visiting_score} {match.visiting.team.value.title()}\n\n"
            f"{result}"
        )
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

        This is a nicety layered on top of state that has already been
        saved, not the thing carrying the turn forward -- a dropped
        connection here (aiohttp.ClientError, e.g. a reset or a bad SSL
        record on a flaky link) shouldn't abort the caller and strand
        the turn before it reaches the next prompt, any more than a 404
        or a Discord-side HTTP error already doesn't.
        """
        if game.message_id is None or interaction.channel is None:
            return

        try:
            board_message = interaction.channel.get_partial_message(
                game.message_id,
            )
            updated_message = await board_message.edit(
                attachments=[self.build_match_file(game)],
            )
        except (discord.NotFound, discord.HTTPException, aiohttp.ClientError):
            return

        # The link has to be re-cut because the edit above uploaded a
        # new file, and setting a view replaces the one already there,
        # so the message's own home/visiting buttons get rebuilt with
        # it. Those are inert once the assignment is made, which is the
        # only state a board refresh runs in; before it, this message
        # is still the team/coin prompt and its buttons are live.
        if game.home_and_visiting_selected:
            await add_full_image_button(
                updated_message,
                HomeAwaySelectionView(cog=self, game_id=game.game_id),
            )

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
        snapshot = await interaction.followup.send(
            message,
            file=self.build_match_file(game),
            wait=True,
        )
        await add_full_image_button(snapshot)
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
                # An error rather than a warning: a finished game whose
                # channel stays in the games category is a permission
                # problem that needs someone to fix it, and nothing else
                # reports it.
                LOGGER.error(
                    "Could not archive finished D12 Ball game %s: %s",
                    game.game_id,
                    error,
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
        snapshot = await interaction.followup.send(
            file=self.build_match_file(game),
            wait=True,
        )
        await add_full_image_button(snapshot)

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
        await add_full_image_button_to_response(interaction)

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
"""
Module-level constants and free functions shared by cogs/d12ball.py and
cogs/d12ball_views.py: emoji lookups, player/team/coin formatting, and
the misc board/interaction helpers that don't need cog state.
"""

import logging
import re
from typing import Optional

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from d12ball.components import (
    MatchState,
    PlayerDefinition,
    Zone,
)
from d12ball.game import (
    AIOpponent,
    CoinFace,
    D12BallGame,
    Team,
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

# A High Pass reuses the loose-ball contest (see begin_loose_ball) even
# when the landing space isn't empty -- a 3+ space pass, or a declined
# 2-space one, always makes the receiver win a skill test to keep the
# ball. This headline replaces begin_loose_ball's default "lands in an
# empty space" framing, which wouldn't be true here. It doesn't mention
# either side sending someone to contest: the receiver is always
# already there, and the defense only gets a pick of their own when
# they don't already have someone on that same space (see
# apply_high_pass's forced_defense_player).
HIGH_PASS_CONTEST_HEADLINE = (
    "**High Pass:** the receiving player must win a skill test to keep "
    "possession."
)

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
        if game.test_game:
            return "Player 1"
        if mention:
            return f"<@{game.player_1_id}>"
        return game.player_1_name or "Player 1"

    if player_number == 2:
        if game.test_game:
            return "Player 2"
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
    if guild is None or game.test_game:
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



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
    GoalRecord,
    MatchState,
    PlayerCatalog,
    PlayerDefinition,
    Zone,
)
from d12ball.formatting import (
    AI_OPPONENT_NAMES,
    BENCH_DESTINATIONS,
    ROLE_INITIALS,
    ZONE_LETTERS,
    ball_space_label,
    contest_noun,
    destination_display_name,
    format_ai_name,
    format_player,
    format_player_with_team,
    format_team_side_label,
    space_label,
    travel_space_label,
)
from d12ball.game import (
    AIOpponent,
    CoinFace,
    D12BallGame,
    Team,
    team_display_name,
)
from discord_emoji_cache import EMOJI_REFETCH_INTERVAL


LOGGER = logging.getLogger(__name__)

# Game channels are "d12ball-pbd<number>", optionally followed by the
# game's name or its players (see build_game_channel_name). The suffix
# is decoration -- the number is the part anything matching this cares
# about -- so it has to stay optional for channels named before there
# was one.
CHANNEL_NAME_PATTERN = re.compile(r"^d12ball-pbd(\d+)(?:-.*)?$")
# Discord's limit on a channel name.
CHANNEL_NAME_MAX_LENGTH = 100
PBD_GAMES_CATEGORY_NAME = "PBD Games"
PBD_ARCHIVE_CATEGORY_NAME = "PBD Archive"
# ROLE_INITIALS, ZONE_LETTERS and BENCH_DESTINATIONS are imported above
# from d12ball.formatting, which is also where space_label -- the
# reader of ZONE_LETTERS -- now lives.
COIN_EMOJI_NAMES = {
    CoinFace.FORTUNE: "3_gold_fortune",
    CoinFace.DOOM: "3_gold_doom",
}
COIN_EMOJI_FALLBACK = "🪙"
FULL_IMAGE_BUTTON_LABEL = "View full image"
# Every board upload is named for its game, which is also how a pinned
# board is told apart from anything else somebody pinned in the channel.
BOARD_IMAGE_FILENAME_PREFIX = "d12ball-pbd"
# The field-only image sent under a coach's maneuver cards. It is
# deliberately *not* named for its game: that prefix is what marks a
# pinned board as ours to roll off, and this one is an ephemeral
# attachment that must never be mistaken for one.
FIELD_IMAGE_FILENAME = "d12ball-field.png"
# Discord caps a channel at 50 pins and answers the 51st with this
# error code.
MAX_PINNED_MESSAGES = 50
MAX_PINS_ERROR_CODE = 30003

# A High Pass *is* the loose-ball contest (see begin_loose_ball) -- a
# 3+ space pass, or a declined 2-space one, makes the receiver win a
# skill test to keep the ball, and since 2026-08-18 that is the
# ordinary rule rather than this maneuver's own: they contest because
# they are standing on the ball. This headline replaces the wording
# build_loose_ball_headline would give it, which says the ball is loose
# -- true, but not what either coach watched happen. It mentions
# nobody being sent because both sides usually have their contestant
# standing there already.
HIGH_PASS_CONTEST_HEADLINE = (
    "**High Pass:** the receiving player must win a skill test to keep "
    "possession."
)

# contest_noun is imported above, from d12ball.formatting.


# AI_OPPONENT_NAMES is imported above, from d12ball.formatting.

# The exhaustion token emoji is uploaded to the application (via the
# Developer Portal's "Emojis" tab, from images/emoji/exhaust.png) and
# looked up here by name using load_condition_emojis below.
EXHAUST_EMOJI_NAME = "exhaust"
# Same deal for the "exhausted" and "injured" conditions, from
# images/emoji/exhausted.png and images/emoji/injured.png -- the same
# art the board draws those conditions with, so a line of text and the
# badge on a card show the player the same icon. The plain emoji below
# are only reached when an application has no upload by that name.
EXHAUSTED_EMOJI_NAME = "exhausted"
EXHAUSTED_EMOJI_FALLBACK = "🥵"
INJURED_EMOJI_NAME = "injured"
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
    Team.FIRE_DEMONS: "team_fire_demons",
    Team.CYBORGS: "team_cyborgs",
    Team.TELEKINETICS: "team_telekinetics",
    Team.OOZES: "team_oozes",
}
TEAM_EMOJI_FALLBACKS = {
    Team.ORANGE: "🟠",
    Team.TEAL: "🔵",
    Team.PURPLE: "🟣",
    Team.SLIME: "🟢",
    # A species team shares its paired color team's ring (see "Team
    # colors" in CLAUDE.md), so its fallback has to read differently
    # from a plain colored circle before the real upload replaces it.
    Team.FIRE_DEMONS: "🔥",
    Team.CYBORGS: "🤖",
    Team.TELEKINETICS: "🔮",
    Team.OOZES: "🫧",
}
EXHAUST_EMOJI_FALLBACK = "😮\u200d💨"


# EMOJI_REFETCH_INTERVAL now lives in discord_emoji_cache.py, imported
# above and re-exported here -- the value, and the retry-cache shape it
# times, are shared with cogs/coins.py. Every existing `from
# cogs.d12ball_helpers import EMOJI_REFETCH_INTERVAL` keeps working.


CONDITION_EMOJI_NAMES = {
    "exhaust": EXHAUST_EMOJI_NAME,
    "exhausted": EXHAUSTED_EMOJI_NAME,
    "injured": INJURED_EMOJI_NAME,
}


async def fetch_application_emojis(
    bot: commands.Bot,
) -> Optional[dict[str, discord.Emoji]]:
    """
    Every emoji uploaded to the application (the Developer Portal's
    "Emojis" tab), keyed by name -- or None when the lookup failed.

    Application emoji work in every server the bot is in, but unlike
    guild emoji they are not part of discord.py's `client.emojis`
    cache, so they have to be fetched over HTTP. That is one request
    that answers every question anyone asks of it, which is why it is
    a function of its own: the three loaders below each used to make
    their own call, so a startup asked Discord for the same list three
    times, and a coin toss on an application with no emoji uploaded
    asked again every time it was flipped.

    Deliberately broad in what it catches: the emoji are decoration,
    and no failure to fetch them should stop anyone playing.
    """
    try:
        emojis = await bot.fetch_application_emojis()
    except Exception as error:
        LOGGER.warning("Could not load the application emoji: %s", error)
        return None

    return {emoji.name: emoji for emoji in emojis}


async def load_condition_emojis(
    bot: commands.Bot,
    emojis_by_name: Optional[dict[str, discord.Emoji]] = None,
) -> dict[str, str]:
    """
    Look up the condition emoji -- the exhaustion token, and the
    exhausted and injured conditions -- among the application's emoji,
    the same way load_coin_emojis does.

    `emojis_by_name` is an already-fetched application emoji list, from
    a caller that is looking several things up out of the same one.
    Fetched here when it is not given.

    A name with no application upload falls back to a guild emoji of
    the same name before it falls back to a plain one: the art for
    these conditions has been uploaded to a server by hand at least as
    often as to the application, and a condition that reads as a
    picture on the board should not read as a stock emoji in the text
    beside it.

    Anything that goes wrong here just leaves a condition out of the
    mapping and callers fall back to a plain emoji.
    """
    if emojis_by_name is None:
        emojis_by_name = await fetch_application_emojis(bot) or {}

    guild_emojis_by_name = {emoji.name: emoji for emoji in bot.emojis}
    condition_emojis: dict[str, str] = {}
    missing: list[str] = []

    for key, name in CONDITION_EMOJI_NAMES.items():
        emoji = emojis_by_name.get(name) or guild_emojis_by_name.get(name)

        if emoji is None:
            missing.append(name)
        else:
            condition_emojis[key] = str(emoji)

    if missing:
        LOGGER.info(
            "No condition emoji named %s on this application or in any "
            "of its servers; those conditions will show their fallback "
            "emoji instead.",
            ", ".join(missing),
        )

    return condition_emojis


def get_exhaust_emoji(condition_emojis: dict[str, str]) -> str:
    return condition_emojis.get("exhaust", EXHAUST_EMOJI_FALLBACK)


def get_exhausted_emoji(condition_emojis: dict[str, str]) -> str:
    return condition_emojis.get("exhausted", EXHAUSTED_EMOJI_FALLBACK)


def get_injured_emoji(condition_emojis: dict[str, str]) -> str:
    return condition_emojis.get("injured", INJURED_EMOJI_FALLBACK)


async def load_team_emojis(
    bot: commands.Bot,
    emojis_by_name: Optional[dict[str, discord.Emoji]] = None,
) -> dict[Team, str]:
    """
    Look up the team-letter emoji among the application's emoji, the
    same way load_coin_emojis and load_condition_emojis do.

    `emojis_by_name` is an already-fetched list -- see
    fetch_application_emojis.
    """
    if emojis_by_name is None:
        emojis_by_name = await fetch_application_emojis(bot) or {}

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


def slugify_channel_part(text: str) -> str:
    """
    Turn free text into something Discord will keep verbatim in a
    channel name.

    Discord lowercases a text channel's name and rewrites spaces as
    dashes itself, so doing it here only means the name we save and the
    name the server shows are the same string. Punctuation is dropped
    rather than kept, because Discord's own rewriting of it is not
    worth predicting. Letters outside ASCII survive -- they are legal
    in a channel name, and a display name that is entirely non-Latin
    would otherwise slugify to nothing.
    """
    return re.sub(r"[^\w]+", "-", text, flags=re.UNICODE).strip("-_").casefold()


def build_game_channel_name(
    game_number: int,
    player_1_name: str,
    player_2_name: str,
    game_name: Optional[str] = None,
) -> str:
    """
    What a game's channel is called: "d12ball-pbd7-cup-final", or
    "d12ball-pbd7-tomer-vs-dinky-ai" when the game was created without
    a name.

    The number is what the bot itself reads back off a channel, so it
    stays immediately after the prefix and the rest is truncated to fit
    Discord's 100-character limit around it.
    """
    prefix = f"d12ball-pbd{game_number}"

    if game_name and game_name.strip():
        suffix = slugify_channel_part(game_name)
    else:
        suffix = "-vs-".join(
            part
            for part in (
                slugify_channel_part(player_1_name),
                slugify_channel_part(player_2_name),
            )
            if part
        )

    if not suffix:
        return prefix

    return f"{prefix}-{suffix}"[:CHANNEL_NAME_MAX_LENGTH].rstrip("-")


def format_role_bracket(
    player: PlayerDefinition,
    team_emojis: dict[Team, str],
    team: Team,
) -> str:
    """
    "🟠 Hellguard [FB]" -- the emoji names which of a player's two
    rosters this card is being shown as, since `PlayerDefinition` no
    longer carries a team of its own. Every caller already has a match
    or a setup in scope to read it off (`match.team_for_player(...)`,
    or `setup.team` when the player is known to be on that side).
    """
    initials = ROLE_INITIALS[player.role.value]
    team_emoji = get_team_emoji(team_emojis, team)
    return f"{team_emoji} {player.name} [{initials}]"


# destination_display_name, format_team_side_label, space_label,
# travel_space_label and ball_space_label are imported above, from
# d12ball.formatting.


def ball_location_line(match: MatchState) -> str:
    """
    Where the ball has come to rest, in a sentence, with the zone
    spelled out beside the space code -- a coach who is about to be
    asked whether to send somebody after it is being asked about a
    distance, and "M2" alone means nothing to anyone who is not
    already looking at the board.
    """
    zone = destination_display_name(match.ball.zone.value)
    return f"The ball is at **{ball_space_label(match)}** ({zone})."


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


def format_goal_time(goal: GoalRecord) -> str:
    """
    The minute a goal was scored, as a coach reads it back.

    **(FH) is the whole of what the clock cannot say by itself.** It
    runs past a period's last minute and the second half then starts at
    16, so a first-half goal in the 17th minute and a second-half goal
    in the 17th are the same number -- the marker is on the one that
    cannot be reached again. `GoalRecord.in_first_half_overrun` is the
    rule; this is only the wording.
    """
    return f"{goal.time:02d}" + (
        " (FH)" if goal.in_first_half_overrun else ""
    )


def format_goal_scorer(goal: GoalRecord, catalog: PlayerCatalog) -> str:
    """
    Who put it in, with **(OG)** where that is not who it counts for.
    The name carries no team emoji: every line of the log is already
    under the heading of the side the goal counts for, which for an own
    goal is not the scorer's own -- so an emoji here would be the one
    thing on the line contradicting it.
    """
    player = catalog.player_by_id(goal.player_id)
    name = f"{player.name} [{ROLE_INITIALS[player.role.value]}]"
    return f"{name} (OG)" if goal.own_goal else name


def build_goal_log(
    match: MatchState,
    catalog: PlayerCatalog,
    team_emojis: dict[Team, str],
) -> str:
    """
    The scoresheet at full time: every goal of the game, under the side
    it counts for, in the order it was scored.

    **A column per side, not one list.** A goal log read as a running
    order says who was ahead and when; read as two columns it says who
    scored, which is the question a coach asks afterwards. An own goal
    is under the side it counted for and marked (OG), which is the one
    line where the name and the heading disagree -- deliberately, since
    that is exactly what an own goal is.

    **The shootout is listed apart.** Its goals go on the scoreboard
    like any other (see `award_shootout_goal`), but they have no minute
    and no run of play, so listing them among the game's would put six
    goals at whatever the clock stopped on.

    **A game older than the log says so.** The log was added mid-life
    and a game already under way keeps loading with an empty one, so
    the count is checked against the scoreboard rather than trusted:
    two goals on the board and none in the log is a game that predates
    this, not a bug in it.
    """
    # A blank line between the blocks, which is what makes them read as
    # columns down a phone rather than as one list with headings in it.
    sections = ["## Goals"]
    for setup in (match.home, match.visiting):
        heading = (
            f"**{get_team_emoji(team_emojis, setup.team)} "
            f"{format_team_side_label(setup)}**"
        )
        scored = [
            goal
            for goal in match.goals_for(setup.side)
            if not goal.shootout
        ]
        if not scored:
            sections.append(f"{heading} -- none")
            continue
        sections.append(
            "\n".join(
                [heading]
                + [
                    f"`{format_goal_time(goal)}`  "
                    f"{format_goal_scorer(goal, catalog)}"
                    for goal in scored
                ]
            )
        )

    shootout = [goal for goal in match.goals if goal.shootout]
    if shootout:
        lines = ["**Extreme shootout**"]
        for setup in (match.home, match.visiting):
            scorers = [
                format_goal_scorer(goal, catalog)
                for goal in shootout
                if goal.side == setup.side
            ]
            lines.append(
                f"{get_team_emoji(team_emojis, setup.team)} "
                f"{team_display_name(setup.team)}: "
                + (", ".join(scorers) if scorers else "none")
            )
        sections.append("\n".join(lines))

    logged = len(match.goals)
    scored_total = (
        match.scoreboard.home_score + match.scoreboard.visiting_score
    )
    if logged < scored_total:
        sections.append(
            f"-# {scored_total - logged} earlier goal(s) were scored "
            "before this game kept a log of them."
        )

    return "\n\n".join(sections)


def build_full_time_summary(
    game: D12BallGame,
    match: MatchState,
) -> str:
    """
    The final score and who won it, for the full-time announcement.

    Called twice for a game that goes to the
    [extreme shootout](docs/living-rules.md): once at the whistle,
    where a level score is not a result but the thing that sends the
    game there, and again when the shootout has settled it. There is
    no third reading -- a shootout always produces a winner, and its
    goals go on the scoreboard, so the second call takes the ordinary
    branch below and only the parenthetical says how it was won.
    """
    home_score = match.scoreboard.home_score
    visiting_score = match.scoreboard.visiting_score
    score_line = (
        f"Final score: {team_display_name(match.home.team)} {home_score}:"
        f"{visiting_score} {team_display_name(match.visiting.team)}"
    )

    shootout = match.shootout_score_line()
    if shootout:
        score_line = f"{score_line}\n{shootout}"

    if home_score == visiting_score:
        return (
            f"{score_line}\n\n"
            "**It's a tie!** The game goes to the "
            "**extreme shootout**."
        )

    home_won = home_score > visiting_score
    winning_setup = match.home if home_won else match.visiting
    winning_player_number = (
        game.home_player_number if home_won else game.visiting_player_number
    )
    winner = format_player(game, winning_player_number, mention=True)

    return (
        f"{score_line}\n\n"
        f"# {team_display_name(winning_setup.team)} wins!\n"
        f"Congratulations, {winner}!"
    )


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


# format_player and format_player_with_team are imported above, from
# d12ball.formatting.


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
    emojis_by_name: Optional[dict[str, discord.Emoji]] = None,
) -> dict[CoinFace, str]:
    """
    Look up the coin emoji among the application's emoji, and keep
    them as ready-to-post <:name:id> strings.

    `emojis_by_name` is an already-fetched list -- see
    fetch_application_emojis.

    Anything that goes wrong here leaves a face out of the mapping and
    the coin toss falls back to a plain coin. An app that has not had
    the emoji uploaded yet is the expected case, not an error.
    """
    if emojis_by_name is None:
        emojis_by_name = await fetch_application_emojis(bot) or {}

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


# What an unexpected exception leaves a coach to do, in the order
# worth trying it. Retrying is first because a dropped connection is a
# real failure mode and does clear on a second click -- but it used to
# be the whole of the advice, and it is no help at all against a bug in
# the flow, which is reached identically every time and leaves the turn
# where it stranded it. `/d12ball resume` is the recovery for that one:
# it puts the prompt back up from the match's own state, which a failed
# click has not changed. Anything resume cannot fix is a bug, and the
# person running the bot is the only one who can see the traceback --
# see "Recovering a stuck game".
ERROR_RECOVERY_ADVICE = (
    "If trying again doesn't work, use `/d12ball resume` to resume the "
    "game. If that doesn't help either, let the bot developer know."
)


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

    return full_image_link_button(message.attachments[0].url)


def full_image_link_button(url: str) -> discord.ui.Button:
    """
    The same button, built from a URL that was read off an upload
    earlier rather than from the message it is going onto.

    The board's link is re-cut a beat after the upload it points at
    (see `settle_board_link`), by which time nothing is holding the
    message it came back on -- only the URL, which is the whole of
    what the button needs.
    """
    return discord.ui.Button(
        label=FULL_IMAGE_BUTTON_LABEL,
        style=discord.ButtonStyle.link,
        url=url,
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


def board_image_filename(game_number: int) -> str:
    return f"{BOARD_IMAGE_FILENAME_PREFIX}{game_number}.png"


def is_board_image_message(message: discord.Message) -> bool:
    """
    Whether a message is one of the bot's board posts, judged by the
    attachment's filename. Used to decide which pin may be rolled off,
    so it has to be narrow: anything a person pinned is not ours to
    remove.
    """
    return any(
        attachment.filename.startswith(BOARD_IMAGE_FILENAME_PREFIX)
        for attachment in message.attachments
    )


async def pin_board_message(message: discord.Message) -> None:
    """
    Pin a board posted at a new play, so the channel keeps a jump list
    of the boards worth going back to.

    Only new-play boards are pinned -- kickoff, halftime, and each
    restart after a goal, an own goal, a missed shot or a ball out of
    bounds -- not the several boards a single turn puts out. A pin is
    an extra request and Discord posts a "pinned a message" notice for
    each one, so this is deliberately rare; see "Discord's rate limits"
    in CLAUDE.md.

    A channel holds 50 pins. At the cap, the oldest pinned *board* is
    unpinned to make room -- a pin somebody else put there is left
    alone, and if there is no board of ours to roll off, the new one
    simply goes unpinned. Failing to pin is never worth losing the turn
    over, so every error here is swallowed the way
    add_full_image_button's are.
    """
    try:
        await message.pin()
        return
    except discord.HTTPException as error:
        if error.code != MAX_PINS_ERROR_CODE:
            return
    except aiohttp.ClientError:
        return

    try:
        oldest = await anext(
            (
                pinned
                async for pinned in message.channel.pins(
                    limit=MAX_PINNED_MESSAGES, oldest_first=True,
                )
                if pinned.id != message.id
                and is_board_image_message(pinned)
            ),
            None,
        )
        if oldest is None:
            return
        await oldest.unpin()
        await message.pin()
    except (discord.HTTPException, aiohttp.ClientError):
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



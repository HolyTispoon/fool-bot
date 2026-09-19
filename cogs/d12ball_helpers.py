"""
Module-level constants and free functions shared by cogs/d12ball.py and
cogs/d12ball_views.py: emoji lookups, player/team/coin formatting, and
the misc board/interaction helpers that don't need cog state.
"""

import logging
import re
from dataclasses import dataclass
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
    PlayerRole,
    Zone,
)
from d12ball.formatting import (
    AI_OPPONENT_NAMES,
    BENCH_DESTINATIONS,
    TEAM_EMOJI_FALLBACKS,
    ZONE_LETTERS,
    ball_space_label,
    challenger_prompt_ask,
    contest_noun,
    destination_display_name,
    format_ai_name,
    format_player,
    format_player_with_team,
    format_team_side_label,
    get_team_emoji,
    player_with_role,
    space_label,
    travel_space_label,
    travel_space_phrase,
)
from d12ball.game import (
    AIOpponent,
    COLOR_TEAMS,
    CoinFace,
    D12BallGame,
    GameMode,
    Team,
    paired_team,
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
# ZONE_LETTERS and BENCH_DESTINATIONS are imported above from
# d12ball.formatting, which is also where space_label -- the reader
# of ZONE_LETTERS -- now lives. ROLE_INITIALS is not re-exported:
# `role_initials` is its one reader outside the drawing modules,
# and `player_with_role` is the only thing that should be building
# a name out of it -- see "Naming a player" in docs/design/naming-and-wording.md.
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

# What a maneuver row is called in the prompt above it. The colours
# are the buttons' own (ManeuverActionPromptView builds an offense row
# `danger` and a defense row `success`) and the cards' -- one name for
# both, so the wording cannot come to disagree with what a coach is
# looking at.
MANEUVER_ROW_COLOURS = {
    "offense": "red",
    "defense": "green",
}

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
# TEAM_EMOJI_FALLBACKS and get_team_emoji are imported above from
# d12ball.formatting, where format_player_with_team reads them.
EXHAUST_EMOJI_FALLBACK = "😮\u200d💨"

# Role emoji (the two initials in a white rounded square,
# images/emoji/role_*.png, drawn by scripts/render_role_emoji.py) are
# uploaded to the application the same way and looked up by
# load_role_emojis below. Where one is loaded it stands in for the
# `[FB]` after a player's name in every *message*; a button label and
# an autocomplete choice are plain text and keep the brackets. There
# is no fallback table: the fallback is the brackets themselves, which
# `d12ball.formatting.role_badge` spells when the dict has no entry.
ROLE_EMOJI_NAMES = {
    PlayerRole.FULLBACK: "role_fullback",
    PlayerRole.DEFENDER: "role_defender",
    PlayerRole.MIDFIELDER: "role_midfielder",
    PlayerRole.PLAYMAKER: "role_playmaker",
    PlayerRole.WINGER: "role_winger",
    PlayerRole.STRIKER: "role_striker",
}

# The same badge with its edge in a team's colour -- `role_fullback`
# and `role_fullback_orange` differ by the edge and by nothing else,
# which is the whole of the design (see scripts/render_role_emoji.py).
# A message names the side the card is being fielded as, so it is the
# form a message gets; the plain badge above is what a *side-less*
# naming falls back to, which is the goal log and nothing else.
#
# **Keyed by every team, filled from four files.** A species team
# shares its colour team's hex, so Orange and Fire Demons are the same
# upload -- the pairing is resolved once, here, exactly as
# `TEAM_COLORS` resolves it once (see "Team colors" in docs/design/teams-and-players.md), so
# nothing downstream has to know that a Cyborg is drawn teal.
ROLE_TEAM_EMOJI_NAMES = {
    (role, team): f"{name}_{colour.value}"
    for role, name in ROLE_EMOJI_NAMES.items()
    for colour in COLOR_TEAMS
    for team in (colour, paired_team(colour))
}


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


async def load_role_emojis(
    bot: commands.Bot,
    emojis_by_name: Optional[dict[str, discord.Emoji]] = None,
) -> dict[tuple[PlayerRole, Optional[Team]], str]:
    """
    Look up the role-badge emoji among the application's emoji, the
    same way load_team_emojis does.

    `emojis_by_name` is an already-fetched list -- see
    fetch_application_emojis.

    **One dict for both cuts, keyed by `(role, team)`.** The plain
    badge is filed under `(role, None)` and each colour cut under
    `(role, team)` for both teams sharing that colour, so a caller
    that has a side and a caller that has none ask the same dict and
    `role_badge` is one lookup chain rather than two dicts threaded
    through ninety call sites.

    Anything with no upload is simply left out, and `role_badge` falls
    back on its own -- colour cut, then plain badge, then the
    brackets. So an application holding the six plain badges and none
    of the twenty-four reads exactly as it did before this landed,
    which is what it was doing until somebody uploads the rest.
    """
    if emojis_by_name is None:
        emojis_by_name = await fetch_application_emojis(bot) or {}

    role_emojis: dict[tuple[PlayerRole, Optional[Team]], str] = {}
    missing: list[str] = []

    for role, name in ROLE_EMOJI_NAMES.items():
        emoji = emojis_by_name.get(name)

        if emoji is None:
            missing.append(name)
        else:
            role_emojis[(role, None)] = str(emoji)

    # The colour cuts are reported separately: an application with the
    # plain six and none of these is the ordinary state on the way to
    # uploading them, and listing twenty-four names beside the six
    # would read as something being wrong with both.
    missing_colours: list[str] = []

    for (role, team), name in ROLE_TEAM_EMOJI_NAMES.items():
        emoji = emojis_by_name.get(name)

        if emoji is None:
            # Once per file rather than once per team -- the four
            # colours are eight keys, and naming each twice would say
            # there are twice as many uploads owed as there are.
            if name not in missing_colours:
                missing_colours.append(name)
        else:
            role_emojis[(role, team)] = str(emoji)

    if missing:
        LOGGER.info(
            "This application has no role emoji named %s; those roles "
            "will show their bracketed initials instead.",
            ", ".join(missing),
        )

    if missing_colours:
        LOGGER.info(
            "This application has no team-coloured role emoji named "
            "%s; players on those teams will show the plain badge "
            "instead.",
            ", ".join(missing_colours),
        )

    return role_emojis


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


# --- Who may act on a game -------------------------------------------
#
# Every gate in the flow -- a lobby setting, a roll button, a maneuver
# pick, a coaching menu -- comes through one of the three predicates
# below, so "who may press this" is answered in one place rather than at
# the eighty-odd sites that ask it.
#
# The rule is: **the coach it belongs to, or a game helper.** A game
# helper is anyone the server trusts with `manage_channels` -- the same
# permission `/d12ball resume`, `/d12ball abandon_game` and the
# full-time Archive button were already gated on, and the same one
# `/debug reset_channels` uses. It is the permission a playtest
# organiser has and an ordinary coach does not, which is exactly the
# line wanted here: somebody helping a new player into a game can flip
# Tutorial on in their lobby, press the buttons they are stuck on, and
# start the game for them, without being a player in it.
#
# There is deliberately no second gate anywhere. A check written at a
# call site is a check that drifts from this one, which is how the
# lobby came to refuse a helper the tutorial toggle while letting them
# abandon the whole game with a slash command.


def game_participant_ids(game: D12BallGame) -> set[int]:
    """
    The Discord ids of the game's coaches -- never the AI, which has no
    user id to be. A test game has both sides set to the same person, so
    this is a one-element set for it.
    """
    participant_ids = {game.player_1_id}
    if game.player_2_id is not None:
        participant_ids.add(game.player_2_id)
    return participant_ids


def is_game_helper(user) -> bool:
    """
    Whether this person may act on a game they are not playing in:
    anyone the server trusts with `manage_channels`.

    Read off `guild_permissions`, so a `discord.User` (a DM, or a member
    Discord handed us uncached) answers False rather than raising -- the
    same tolerant shape every other optional lookup in this file has.
    Deliberately a permission and not a role: a role would have to be
    created per server and found by name, where every server already
    has somebody holding this.

    **`is True`, not a truthiness test**, and that is about the suite
    rather than about Discord: a permission is a bool, and nearly every
    person in `tests/` is a `MagicMock(spec=discord.Member)`, whose
    `guild_permissions.manage_channels` is a Mock and therefore truthy.
    Under a plain `bool(...)` every mocked click in the game would read
    as a helper's, which turns every gate in this file into a no-op and
    does it silently -- the tests still pass, because a gate that lets
    everyone through refuses nobody. A test that means to grant this
    says so, with `SimpleNamespace(manage_channels=True)`.
    """
    permissions = getattr(user, "guild_permissions", None)
    return getattr(permissions, "manage_channels", False) is True


def may_act_for_coach(user, coach_id: Optional[int]) -> bool:
    """
    Whether this person may press a button that belongs to the coach
    `coach_id` -- that coach, or a game helper.

    `coach_id` is None for a side the AI is playing, and a helper may
    act there too: nothing ever puts a prompt to Dinky, so the only way
    to reach one is a game that has gone wrong, which is precisely when
    somebody has to be able to answer it. A coach who is not a helper
    still matches on their own id alone, so this is exactly the old
    check for everybody it was already about.
    """
    return user.id == coach_id or is_game_helper(user)


def may_act_in_game(user, game: D12BallGame) -> bool:
    """
    Whether this person may press a button either coach may press -- a
    roll, the maneuver reference -- which is either coach, or a game
    helper. See "Every roll is a coach's" in docs/design/maneuvers.md.
    """
    return user.id in game_participant_ids(game) or is_game_helper(user)


# The key on `Interaction.extras` that says a helper's click has been
# confirmed. Set by `HelperConfirmationView.confirm` on the click that
# answers the confirmation, before it re-runs the button that asked
# for it -- so the gate that raised the first time reads it and lets
# the same click through. It is on the interaction rather than on the
# match or the view because it is a fact about *this click* and
# nothing else: the next click the helper makes for somebody else is
# asked again.
HELPER_CONFIRMED_EXTRA = "d12ball_helper_confirmed"


def helper_click_confirmed(interaction) -> bool:
    """Whether this click already carries a helper's confirmation."""
    extras = getattr(interaction, "extras", None)
    return bool(extras) and extras.get(HELPER_CONFIRMED_EXTRA) is True


class HelperConfirmationRequired(Exception):
    """
    Raised by `SafeView.may_act_for` and `SafeView.may_act_in_game`
    when the click is a game helper's, is for somebody other than
    themselves, and has not been confirmed -- see "Who may act on a
    game" in docs/design/permissions.md.

    It is an exception rather than a third return value because the
    gates are called from fifty-odd callbacks as `if not
    self.may_act_for(...)`, every one of which has yet to respond or
    change anything when it asks. Raising lets the click leave the
    callback untouched and reach `SafeView.on_error`, which is the one
    place that knows the button it came from and can put the
    confirmation up in its place. `coach_ids` is who the click would
    act for -- one coach, or both for a button either may press -- and
    is only ever used to word the confirmation.
    """

    def __init__(self, coach_ids: tuple[Optional[int], ...]):
        super().__init__(
            "A game helper's click for somebody else needs confirming."
        )
        self.coach_ids = coach_ids


def format_role_bracket(
    player: PlayerDefinition,
    team_emojis: dict[Team, str],
    team: Team,
    role_emojis: Optional[dict[tuple[PlayerRole, Optional[Team]], str]] = None,
) -> str:
    """
    "🟠 Hellguard [FB]" -- `player_with_role` with the team emoji in
    front, which is the form every *message* names a player in. The
    emoji says which of a player's two rosters this card is being shown
    as, since `PlayerDefinition` no longer carries a team of its own;
    every caller already has a match or a setup in scope to read it off
    (`match.team_for_player(...)`, or `setup.team` when the player is
    known to be on that side).

    `role_emojis` is the role's own badge in place of the brackets
    (see `load_role_emojis`); a message is the one place custom emoji
    render, so this is the form that takes it and `player_with_role`
    on its own is the form that does not. **The team is passed on to
    the badge as well as read for the emoji in front**, so the badge
    is drawn with that side's own colour on its edge -- one team
    argument answering both, which is what stops the ring and the
    badge on one line ever naming two different sides.

    **A button gets the position instead of the emoji**, which is the
    only place the two forms differ -- see `player_with_role` and
    "Naming a player" in docs/design/naming-and-wording.md.
    """
    team_emoji = get_team_emoji(team_emojis, team)
    return f"{team_emoji} {player_with_role(player, role_emojis, team)}"


# destination_display_name, format_team_side_label, space_label,
# travel_space_label, travel_space_phrase and ball_space_label are
# imported above, from d12ball.formatting.


def ball_location_line(match: MatchState) -> str:
    """
    Where the ball has come to rest, in a sentence, with the zone
    spelled out beside the space code -- a coach who is about to be
    asked whether to send somebody after it is being asked about a
    distance, and "M2" alone means nothing to anyone who is not
    already looking at the board.
    """
    zone = destination_display_name(
        match.ball.zone.value, match.board.layout.board_size
    )
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


def format_goal_scorer(
    goal: GoalRecord,
    catalog: PlayerCatalog,
    role_emojis: Optional[dict[tuple[PlayerRole, Optional[Team]], str]] = None,
) -> str:
    """
    Who put it in, with **(OG)** where that is not who it counts for.
    The name carries no team emoji: every line of the log is already
    under the heading of the side the goal counts for, which for an own
    goal is not the scorer's own -- so an emoji here would be the one
    thing on the line contradicting it. The *role* emoji says nothing
    about a side, so it stays -- **the plain cut of it**, which is why
    this is the one message in the game that names a player and passes
    `role_badge` no team. A team-coloured badge says exactly what the
    team emoji would have said, and would contradict the heading in
    exactly the same way.
    """
    player = catalog.player_by_id(goal.player_id)
    name = player_with_role(player, role_emojis)
    return f"{name} (OG)" if goal.own_goal else name


def build_goal_log(
    match: MatchState,
    catalog: PlayerCatalog,
    team_emojis: dict[Team, str],
    role_emojis: Optional[dict[tuple[PlayerRole, Optional[Team]], str]] = None,
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
                    f"{format_goal_scorer(goal, catalog, role_emojis)}"
                    for goal in scored
                ]
            )
        )

    shootout = [goal for goal in match.goals if goal.shootout]
    if shootout:
        lines = ["**Extreme shootout**"]
        for setup in (match.home, match.visiting):
            scorers = [
                format_goal_scorer(goal, catalog, role_emojis)
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


# -- The two halves of advanced mode -------------------------------
#
# Advanced mode is one switch over two modules -- the advanced
# maneuvers and the species abilities -- and a game may take just one
# of them (see "Species abilities in the bot"). The switch is what a
# coach picks; these are what an advanced game leaves behind, which is
# why they are opt-*outs* on the game record and why nothing here is
# offered in a basic game.
#
# The table is keyed by the word a button carries in its custom_id, and
# names the field it toggles and what a coach reads on the button. Both
# the setup settings block and the lobby build their buttons out of it
# and toggle through `toggle_advanced_module`, so the two screens
# cannot come to offer different modules or disagree about which of
# them may be turned off.
ADVANCED_MODULES: dict[str, tuple[str, str]] = {
    "maneuvers": ("advanced_maneuvers", "Maneuvers"),
    "species": ("species_abilities", "Species"),
}
# What each module is, for the setup and lobby messages -- a button
# reading "Maneuvers: on" says which half is on and nothing about what
# it does.
ADVANCED_MODULE_DESCRIPTIONS: dict[str, str] = {
    "maneuvers": "six maneuvers a side",
    "species": "species abilities",
}


def advanced_module_label(game: D12BallGame, key: str) -> str:
    field, name = ADVANCED_MODULES[key]
    return f"{name}: {'on' if getattr(game, field) else 'off'}"


def toggle_advanced_module(game: D12BallGame, key: str) -> Optional[str]:
    """
    Turn one half of advanced mode off or back on, or say why not.

    Both halves off is a basic game reached the long way round, and the
    mode buttons are right there -- so the last one still on is refused
    rather than quietly leaving a coach in an advanced game with
    nothing advanced in it.
    """
    field, _ = ADVANCED_MODULES[key]

    turning_off = getattr(game, field)
    others_on = any(
        getattr(game, other)
        for other_key, (other, _) in ADVANCED_MODULES.items()
        if other_key != key
    )
    if turning_off and not others_on:
        return (
            "An advanced game plays at least one of its two modules. "
            "Pick Basic if you want neither."
        )

    setattr(game, field, not turning_off)
    return None


def describe_game_mode(game: D12BallGame) -> str:
    """
    What this game's mode means, in the coach's own terms: the cards a
    basic game deals, and for an advanced one the modules it is
    actually playing. Read off the modules rather than off the mode
    alone, or a game that opted the maneuvers out would still be
    advertised as six cards a side.
    """
    if game.mode == GameMode.BASIC:
        return "three maneuvers a side"

    return ", ".join(
        description
        for key, description in ADVANCED_MODULE_DESCRIPTIONS.items()
        if getattr(game, ADVANCED_MODULES[key][0])
    )


def build_setup_message(
    game: D12BallGame,
    team_emojis: dict[Team, str],
    mention_players: bool = True,
) -> str:
    player_1 = format_player_with_team(
        game,
        1,
        team_emojis,
        mention=mention_players,
    )
    player_2 = format_player_with_team(
        game,
        2,
        team_emojis,
        mention=mention_players,
    )

    text = (
        "## D12 Ball game setup\n\n"
        "### Choose your teams\n\n"
        f"**Player 1:** {player_1}\n\n"
        f"**Player 2:** {player_2}\n\n"
        "### Game settings\n\n"
        f"Game Mode: {game.mode.value.title()} "
        f"-- {describe_game_mode(game)}\n"
        f"Board size: {game.board_size}\n\n"
    )

    if game.mode == GameMode.ADVANCED:
        text += (
            "It is recommended to play advanced mode on a board size "
            "of 9.\n\n"
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


# The names of the application emoji uploaded through the Developer
# Portal for D12 Ball -- both a d12 (see "The game-creation hub and the
# lobby" in docs/design/hub-and-lobby.md). `d12dice` is the one that sits in message text
# (the hub message and the lobby heading); `d12dicecream` is a
# lighter-inked cut used only on the hub button, whose blue Discord fill
# swallowed the darker die. Everything degrades to the other name, then
# to no emoji, when an upload is missing.
D12_EMOJI_NAME = "d12dice"
D12_BUTTON_EMOJI_NAME = "d12dicecream"


async def load_d12_emoji(
    bot: commands.Bot,
    emojis_by_name: Optional[dict] = None,
    name: str = D12_EMOJI_NAME,
) -> Optional[str]:
    """
    The `<:name:id>` string for a D12 Ball d12 emoji, or None when it has
    not been uploaded -- the same shape as `load_coin_emojis` and
    friends. A guild emoji of the same name is accepted as a fallback.
    """
    if emojis_by_name is None:
        emojis_by_name = await fetch_application_emojis(bot) or {}

    emoji = emojis_by_name.get(name) or next(
        (e for e in bot.emojis if e.name == name), None,
    )
    if emoji is None:
        LOGGER.info(
            "No application emoji named %r; D12 Ball's hub and lobby will "
            "fall back for it.",
            name,
        )
        return None
    return str(emoji)


async def load_d12_button_emoji(
    bot: commands.Bot,
    emojis_by_name: Optional[dict] = None,
) -> Optional[str]:
    """
    The emoji for the hub's buttons: the lighter `d12dicecream` cut, or
    None when it has not been uploaded. Deliberately no fallback to the
    plain `d12dice` -- a blue die on a green button is exactly what the
    cream cut exists to avoid, so a missing upload leaves the button
    bare (and an INFO line saying which name was missed) rather than
    quietly putting the wrong die on it.
    """
    return await load_d12_emoji(
        bot, emojis_by_name, name=D12_BUTTON_EMOJI_NAME,
    )


def build_hub_message(d12_emoji: Optional[str] = None) -> str:
    """
    The single message the game-creation hub channel carries. `/d12ball
    setup_hub` posts it (or edits the existing one) behind a
    `NewGameHubView`: a welcome, then one titled block per game -- name,
    button, and the game's own description -- with only D12 Ball for now
    and room to grow. The description text is the author's own copy; keep
    it verbatim.
    """
    d12 = f"{d12_emoji} " if d12_emoji else ""
    return (
        "## Prophetic Fools Games\n\n"
        "Hello! This is the game-creation channel of the Prophetic Fools "
        "Games server. We'd love for you to try our games! Use the buttons "
        "below to start a new game.\n\n"
        f"### {d12}D12 Ball\n\n"
        "D12 Ball is a fast playing fantasy sports game with tense "
        "last-ditch efforts and dramatic comebacks, where two teams of "
        "fantasy creatures compete by maneuvering around the field, "
        "manipulating the ball and outwitting the other team on their way "
        "to score epic goals."
    )


@dataclass(frozen=True)
class HubRole:
    """
    One role the hub's roles message offers a button for. `key` is what
    the button's custom_id carries (`d12ball:hub:role:<key>`), so it is
    the one field that must never change once a message is posted;
    `role_name` is how the role is found on the server (by name,
    case-insensitively -- the bot creates nothing); `label` is the
    button, and `description` is the line under the role in the message.
    """

    key: str
    role_name: str
    label: str
    description: str
    # Whether the button carries the d12 emoji beside its label -- for a
    # role that is about D12 Ball, so its button reads as the games
    # button's sibling. A role for something else leaves it off.
    d12_emoji: bool = False


# The roles the hub offers, in the order their buttons appear. Adding a
# role is one entry here: the view builds a button per entry, the
# message lists one line per entry, and `toggle_hub_role` looks the
# click up by key. The role itself has to exist on the server --
# `/d12ball setup_hub` says which it could not find.
HUB_ROLES: tuple[HubRole, ...] = (
    HubRole(
        key="playtester",
        role_name="D12ball playtester",
        label="D12ball playtester",
        d12_emoji=True,
        description=(
            "Get pinged when a D12 Ball playtest is being organised, and "
            "for news about the game."
        ),
    ),
)

HUB_ROLE_CUSTOM_ID_PREFIX = "d12ball:hub:role:"


def hub_role_by_key(key: str) -> Optional[HubRole]:
    """The `HUB_ROLES` entry a button's key names, or None."""
    return next((role for role in HUB_ROLES if role.key == key), None)


def find_guild_role(
    guild: discord.Guild, hub_role: HubRole,
) -> Optional[discord.Role]:
    """
    The server's role for a `HubRole`, matched on name with case and
    surrounding whitespace ignored -- a role is typed by hand in the
    server settings, and "d12ball Playtester" is the same role.
    """
    wanted = hub_role.role_name.strip().casefold()
    return next(
        (
            role for role in guild.roles
            if role.name.strip().casefold() == wanted
        ),
        None,
    )


def build_hub_roles_message(
    hub_roles: tuple[HubRole, ...] = HUB_ROLES,
) -> str:
    """
    The hub channel's second message, carrying a `HubRolesView`: what
    the buttons do, then one line per role. Kept apart from
    `build_hub_message` so the games message can change without the
    roles message being re-edited, and the other way round.
    """
    lines = [
        "### Roles",
        "",
        "Press a button to give yourself that role, and press it again "
        "to take it off.",
        "",
    ]
    for hub_role in hub_roles:
        lines.append(f"- **{hub_role.role_name}** -- {hub_role.description}")
    return "\n".join(lines)


def build_lobby_message(
    game: D12BallGame,
    d12_emoji: Optional[str] = None,
) -> str:
    """
    What a lobby channel's message says while players are still joining
    and picking settings. Plain text in the style of `build_setup_message`.

    Player 2 is worded by hand rather than through `format_player`: a
    lobby has `player_2_id = None` even for a game two humans will play,
    so `format_player` would call it a game against Dinky.
    """
    if game.tutorial:
        player_2 = (
            f"**{format_ai_name(game.ai_opponent)}** _(guided tutorial -- "
            "the first turns are scripted)_"
        )
    elif game.test_game:
        player_2 = f"<@{game.player_1_id}> _(test game -- you play both sides)_"
    elif game.player_2_id is not None:
        player_2 = f"<@{game.player_2_id}>"
    else:
        player_2 = (
            "_open -- press **Join**, or **Start Game** to play "
            f"**{format_ai_name(game.ai_opponent)}**_"
        )

    d12 = f"{d12_emoji} " if d12_emoji else ""
    heading = (
        f"## {d12}{game.game_name} -- D12 Ball"
        if game.game_name
        else f"## {d12}D12 Ball -- game lobby"
    )

    text = (
        f"{heading}\n\n"
        "Anyone in the server can look in here. **Join** to take the "
        "second seat, **Observe** to keep watching once the game locks "
        "to its players, **Name** to give it a title, or set it up and "
        "press **Start Game**.\n\n"
        f"**Player 1:** <@{game.player_1_id}>\n"
        f"**Player 2:** {player_2}\n"
    )

    if game.observer_ids:
        watchers = ", ".join(f"<@{oid}>" for oid in game.observer_ids)
        text += f"**Observers:** {watchers}\n"

    text += (
        "\n### Settings\n\n"
        f"Mode: **{game.mode.value.title()}** "
        f"-- {describe_game_mode(game)}\n"
        f"Board size: **{game.board_size}** spaces\n"
    )

    if game.mode == GameMode.ADVANCED:
        # Shown the whole time Advanced is on, not only once the board is
        # off 9 -- picking Advanced defaults the board to 9, and this note
        # is what tells a coach why it moved.
        text += (
            "\n_It is recommended to play advanced mode on a board size "
            "of 9._\n"
        )

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


def build_home_choice_message(
    game: D12BallGame,
    team_emojis: dict[Team, str],
) -> str:
    winner = format_player_with_team(
        game,
        game.coin_winner_player_number,
        team_emojis,
    )

    if (
        game.coin_face is not None
        and game.coin_flipped_by_player_number is not None
    ):
        flipper = format_player_with_team(
            game,
            game.coin_flipped_by_player_number,
            team_emojis,
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
            team_emojis,
        )
        visiting_player = format_player_with_team(
            game,
            game.visiting_player_number,
            team_emojis,
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
            team_emojis,
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
    (see `BoardRefresher.settle_link`), by which time nothing is holding the
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
    row: Optional[int] = None,
) -> None:
    """
    Put the full-image link on a message that has already gone out.

    The URL only exists once Discord has stored the file, so this is
    always a second round trip. Editing a message's view replaces it
    wholesale, so `view` has to carry the message's own buttons too --
    discord.py routes clicks against the components in the payload, and
    dropping them would leave a message that looks interactive and
    is not.

    `row` pins the link to a specific action row. Without it discord.py
    drops the button into the first row with space, which on a prompt
    whose rows are not packed to five (the advanced maneuver prompt)
    leaves it wedged between a side's basic and advanced cards.
    """
    button = build_full_image_button(message)

    if button is None:
        return

    view = discord.ui.View(timeout=None) if view is None else view
    if row is not None:
        button.row = row
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
    in docs/design/rate-limits.md.

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



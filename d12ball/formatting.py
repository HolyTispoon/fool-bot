"""
Pure text formatting over D12 Ball's domain objects -- zone/space
codes, player and team names, AI opponent names -- with no Discord
dependency and no cog state. Moved out of cogs/d12ball_helpers.py so
d12ball/engine.py's RulesEngine can build prompt text without cogs
importing from d12ball, never the other way around: a helper that only
formats a Zone or a MatchState belongs down here, next to the things
it formats, and cogs/d12ball_helpers.py re-imports every name below
for the many call sites (and other cog-level helpers, like
format_role_bracket) that already read them from there.

What stayed behind in cogs/d12ball_helpers.py either needs live
Discord data (condition_emojis) or touches discord.py directly --
format_role_bracket needs an emoji dict this module has no business
*fetching*, which is the whole difference between the two files. A
dict of `Team -> "<:team_purple:id>"` strings, once fetched, is plain
data, and `format_player_with_team` takes one the way
`format_role_bracket` does: the engine's prompt builders name a coach
with their team emoji, so the fallbacks and the lookup live here.
"""

from typing import Optional

from d12ball.components import MatchState, PlayerRole, Zone
from d12ball.game import AIOpponent, D12BallGame, Team, team_display_name


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

# The 9-space board is the only one whose three areas (H/M/V) are equal, which
# is what earns its outer two the more literal "Third" -- see "The field" in
# the living rules and the 2026-08-24 entry in the rules log. Midfield's name
# never changes, so it carries no entry here.
OUTER_ZONE_WORD_BY_BOARD_SIZE = {
    6: "Zone",
    7: "Zone",
    9: "Third",
}

AI_OPPONENT_NAMES = {
    AIOpponent.DINKY: "Dinky AI",
    AIOpponent.DECENT: "Decent AI",
}

# What a team is drawn as before its application emoji has been
# fetched, or when the upload is missing. The uploaded emoji (a letter
# in a team-coloured ring) are looked up by name in
# cogs/d12ball_helpers.py's load_team_emojis; this is the half that
# needs no Discord.
TEAM_EMOJI_FALLBACKS = {
    Team.ORANGE: "🟠",
    Team.TEAL: "🔵",
    Team.PURPLE: "🟣",
    Team.SLIME: "🟢",
    # A species team shares its paired color team's ring (see "Team
    # colors" in docs/design/teams-and-players.md), so its fallback has to read differently
    # from a plain colored circle before the real upload replaces it.
    Team.FIRE_DEMONS: "🔥",
    Team.CYBORGS: "🤖",
    Team.TELEKINETICS: "🔮",
    Team.OOZES: "🫧",
}


def get_team_emoji(team_emojis: dict[Team, str], team: Team) -> str:
    return team_emojis.get(team, TEAM_EMOJI_FALLBACKS[team])


def contest_noun(match: MatchState) -> str:
    """
    What to call the ball currently being fought over -- "high pass",
    "loose ball", or plain "ball".

    Three positions share this machinery and nothing else.

    - A **loose ball** is the ball lying on a space nobody is standing
      on, and it is the only one of the three that word may be used
      for (the author, 2026-08-26). Each side may send a player after
      it, and whoever wins it takes possession from where it lies.
    - Otherwise the ball came down on somebody. Where both sides are
      standing there it is a **contest** between them, and the plain
      noun is what the sentences around it want: a coach "contests the
      ball", not "contests the contest". Where only one side is
      standing there nobody contests anything -- it is simply theirs,
      and no prompt is built at all.
    - A **High Pass** is a completed pass to a player already standing
      there, defending the ball they just received; losing it is a
      turnover, winning it changes nothing.

    Calling one by another's name in front of a coach who is deciding
    what to do misreads the position, so every message on the shared
    path asks for the noun rather than assuming.

    It reads the flag recorded when the ball arrived rather than the
    board, because by the time a roll or a result is worded the
    contestants have been walked onto the space and the position that
    decided the word is gone.
    """
    if match.pending_loose_ball_is_high_pass:
        return "high pass"
    return (
        "loose ball" if match.pending_loose_ball_on_empty_space else "ball"
    )


def challenger_prompt_ask(match: MatchState) -> str:
    """
    What the defending coach is being asked when they pick a
    challenger, which is two different questions.

    Ordinarily the choice includes not making one: a walk-in costs a
    token a space, so keeping everybody back is a real option
    (may_decline_challenge). Where the candidates are defenders already
    standing on the ball it is not -- they pay nothing to challenge and
    their side may not withhold them -- so the question narrows to
    which of them goes. The prompt must not offer what the view does
    not build; see MatchState.challenge_candidates.
    """
    if match.may_decline_challenge():
        return (
            "choose which player will maneuver to challenge for the "
            "ball, or send nobody and let the maneuver through."
        )
    return (
        "these players are already on the ball, so one of them has to "
        "challenge -- choose which."
    )


def format_ai_name(ai_opponent: Optional[AIOpponent]) -> str:
    return AI_OPPONENT_NAMES[ai_opponent or AIOpponent.DINKY]


def zone_display_name(zone: Zone, board_size: int) -> str:
    """
    "Home Zone", "Midfield", "Visitors Third" -- whichever a board's own
    size calls the outer two areas. See the module-level comment on
    OUTER_ZONE_WORD_BY_BOARD_SIZE for why the 9-space board differs.
    """
    if zone is Zone.MIDFIELD:
        return "Midfield"
    side = "Home" if zone is Zone.HOME_GOAL else "Visitors"
    return f"{side} {OUTER_ZONE_WORD_BY_BOARD_SIZE[board_size]}"


def destination_display_name(destination: str, board_size: int) -> str:
    if destination in BENCH_DESTINATIONS:
        return destination.replace("_", " ").title()
    return zone_display_name(Zone(destination), board_size)


def format_team_side_label(setup) -> str:
    return f"{team_display_name(setup.team)} ({setup.side.value.title()})"


def space_label(zone: Zone, space_index: int) -> str:
    return f"{ZONE_LETTERS[zone]}{space_index + 1}"


def travel_space_label(zone: Zone, space_index: int, distance: int) -> str:
    """
    A destination with what reaching it costs -- "H1 (2 spaces)".

    A run back is charged a token a space, so the distance *is* the
    price, and a coach picking between the spaces of a zone is picking
    between prices. The number is on the button as well as in the
    sentence beside it, because the button is the thing being pressed.
    """
    unit = "space" if distance == 1 else "spaces"
    return f"{space_label(zone, space_index)} ({distance} {unit})"


def travel_space_phrase(zone: Zone, space_index: int, distance: int) -> str:
    """
    The same destination and the same price, worded for a sentence
    rather than for a button -- "H1 (2 spaces away)".

    The two differ by that one word and deliberately. A button is a
    label, so it is as short as it can be and still name the price; the
    line above the buttons is read as prose, and "2 spaces" there reads
    as a quantity of spaces rather than as a distance. Both are built
    from the same `distance`, so what the sentence offers and what the
    button charges cannot drift apart.
    """
    unit = "space" if distance == 1 else "spaces"
    return f"{space_label(zone, space_index)} ({distance} {unit} away)"


def ball_space_label(match: MatchState) -> str:
    """Where the ball is standing, as a space code -- e.g. "M2"."""
    return space_label(match.ball.zone, match.ball.space_index)


def role_initials(player) -> str:
    """
    A role's two letters -- the `FB` in "Hellguard [FB]".

    The one reader of `ROLE_INITIALS` outside the modules that *draw*
    it (the meeple tokens, the card header badges, the printed cards),
    which index it for a glyph rather than for a name. Everything that
    puts a role into text comes through here, so the two spellings
    below cannot come to disagree about what a Fullback is called.
    """
    return ROLE_INITIALS[player.role.value]


def role_badge(
    player,
    role_emojis: Optional[dict[tuple[PlayerRole, Optional[Team]], str]] = None,
    team: Optional[Team] = None,
) -> str:
    """
    The role as it is written after a name: the application's emoji
    for it where one has been loaded, and `[FB]` otherwise.

    `role_emojis` is `(role, team) -> "<:role_fullback_orange:123>"`,
    loaded by `cogs.d12ball_helpers.load_role_emojis` from the PNGs
    `scripts/render_role_emoji.py` draws -- the plain badge under
    `(role, None)` and a colour cut under each team. It is optional
    because the text form is right in two places the emoji cannot go:
    a button label and an autocomplete choice are plain text, and
    custom emoji markup in either shows as the raw `<:...:>`. So a
    caller passes the dict for a *message* and nothing for a button,
    which is the same split as the team emoji -- see "Naming a player"
    in docs/design/naming-and-wording.md.

    **`team` is which of the player's two rosters this card is being
    fielded as**, and passing it is what asks for the coloured badge.
    Every message names a player through `format_role_bracket`, which
    already takes a team for the emoji in front, so the team is in
    hand wherever the badge is coloured -- and the one caller with no
    team to give is the one that must not have a colour at all: the
    goal log lists an own goal under the side it counted for, which is
    not the scorer's, so a coloured badge there would be the one thing
    on the line contradicting the heading over it. See
    `format_goal_scorer`.

    **Three steps down, not two.** The colour cut, then the plain
    badge, then the brackets: an application that has uploaded the six
    and none of the twenty-four reads exactly as it did before the
    colours existed, and one that has uploaded three colours of six
    roles shows those three and falls back for the rest, rather than
    showing blanks.
    """
    if role_emojis:
        emoji = role_emojis.get((player.role, team))
        if emoji is None and team is not None:
            emoji = role_emojis.get((player.role, None))
        if emoji:
            return emoji
    return f"[{role_initials(player)}]"


def player_with_role(
    player,
    role_emojis: Optional[dict[tuple[PlayerRole, Optional[Team]], str]] = None,
    team: Optional[Team] = None,
) -> str:
    """
    A card named the way every card in this game is named -- "Hellguard
    [FB]", or "Hellguard <:role_fullback:123>" in a message once the
    role emoji are uploaded.

    **A player is never named without their role.** Nine of them are on
    the field at once and a coach is choosing between them on what they
    do, so a bare name is the one thing a label can say that does not
    help: the role initials are what the meeple, the card on the board
    and the printed card all carry, so this is the name a coach can
    match to what they are looking at. See "Naming a player" in
    docs/design/naming-and-wording.md.

    This is the whole of the spelling, and the two things that add to
    it build on it: `format_role_bracket` puts the team emoji in front
    for a *message*, and a button adds the position instead. Nothing
    may spell the brackets out for itself -- that is how the run back's
    own buttons came to be the one place in the game that named a
    player and left the role off. `role_emojis` and `team` are
    `role_badge`'s, and are passed only where the text is going into a
    message -- the team being what asks for the badge in that side's
    own colour.

    It takes a `PlayerDefinition` rather than an id because the caller
    that has an id has a catalog to resolve it with, and this module
    has neither.
    """
    return f"{player.name} {role_badge(player, role_emojis, team)}"


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
    team_emojis: dict[Team, str],
    mention: bool = False,
) -> str:
    """
    "🟣 @coach" -- a coach named with their side's emoji in front, which
    is how every message names one: the turn prompt, the maneuver
    picks, the coin toss, the loose-ball send.

    It read "@coach (Purple)" until 2026-09-16, the team spelled out in
    parentheses. The emoji is the same mark the board draws that side's
    meeples in and the same one every *player* label already carries
    (`format_role_bracket`, "🟠 Hellguard [FB]"), so a coach and their
    cards now read as one side at a glance rather than by matching a
    word to a colour. Same position -- in front -- for the same reason:
    one rule for "whose is this", not two.

    A coach with no team yet (setup, before the picker) is named bare:
    "(Unknown team)" was answering a question nobody asked.
    """
    player = format_player(game, player_number, mention=mention)
    team = (
        game.player_1_team
        if player_number == 1
        else game.player_2_team
    )
    if team is None:
        return player
    return f"{get_team_emoji(team_emojis, team)} {player}"

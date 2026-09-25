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
Discord data (the emoji it fetches) or touches discord.py directly.
Nothing here holds an emoji or a mention any more: a sentence that
names a team, a role badge, a condition mark or the coach it is put
to writes a token for it (`d12ball/tokens.py`) and the frontend
renders the token once, at its door -- step 9 of
docs/architecture-migration.md.
"""

from typing import Optional

from d12ball.components import (
    GoalRecord,
    MatchState,
    PlayerCatalog,
    PlayerDefinition,
    PlayerRole,
    Zone,
)
from d12ball import tokens
from d12ball.space_numbering import (
    FLAT_SPACE_NUMBERING,
    flat_space_number,
)
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
    7: "Zone",
    9: "Third",
}

AI_OPPONENT_NAMES = {
    AIOpponent.DINKY: "Dinky AI",
    AIOpponent.DECENT: "Decent AI",
}

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
            "choose which player will move to challenge the maneuver, "
            "or send nobody and let it through."
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


def space_label(zone: Zone, space_index: int, board=None) -> str:
    """
    What a space is called in a sentence or on a button -- "H1", or
    "space 1" while the numbering experiment is on.

    The word goes with the number because a bare number sits beside
    counts, distances, minutes and scores everywhere a space is named
    ("Ball is now in 3 ... now at 37", "2 spaces (4-...)"), and nothing
    else says which one is the space. It is lowercase because a space
    is named mid-sentence far more often than at the start; a caller
    that opens a label or a sentence with it runs it through
    `capitalized`.

    `board` is the live `BoardState` (or a bare `BoardLayout` where
    there is no game, as on the printed sheets), and it is read only
    by the experiment, which needs the zone sizes to count across
    them -- see `d12ball/space_numbering.py`. Passing nothing gives
    the 7-space board's numbering. **Drop the parameter when the
    experiment is reverted**; the letter form never needed it.
    """
    if FLAT_SPACE_NUMBERING:
        return f"space {flat_space_number(zone, space_index, board)}"
    return f"{ZONE_LETTERS[zone]}{space_index + 1}"


def capitalized(text: str) -> str:
    """`text` with its first letter raised -- for a label or a sentence
    that opens on a space's name ("space 4 - free"). A no-op on the
    letter form, which is already a capital."""
    return text[:1].upper() + text[1:]


def travel_space_label(
    zone: Zone,
    space_index: int,
    distance: int,
    board=None,
) -> str:
    """
    A destination with what reaching it costs -- "H1 (2 spaces)".

    A run back is charged a token a space, so the distance *is* the
    price, and a coach picking between the spaces of a zone is picking
    between prices. The number is on the button as well as in the
    sentence beside it, because the button is the thing being pressed.
    """
    if FLAT_SPACE_NUMBERING:
        return capitalized(
            f"{space_label(zone, space_index, board)} ({distance} away)"
        )
    unit = "space" if distance == 1 else "spaces"
    return f"{space_label(zone, space_index, board)} ({distance} {unit})"


def travel_space_phrase(
    zone: Zone,
    space_index: int,
    distance: int,
    board=None,
) -> str:
    """
    The same destination and the same price, worded for a sentence
    rather than for a button -- "H1 (2 spaces away)".

    The two differ by that one word and deliberately. A button is a
    label, so it is as short as it can be and still name the price; the
    line above the buttons is read as prose, and "2 spaces" there reads
    as a quantity of spaces rather than as a distance. Both are built
    from the same `distance`, so what the sentence offers and what the
    button charges cannot drift apart.

    Under the flat numbering both read "space 4 (3 away)": a bare
    number beside a count of spaces ("4 (3 spaces)") is two numbers
    with nothing to say which is the space, so the word goes on the
    space and the count keeps only "away". The button capitalises it.
    """
    if FLAT_SPACE_NUMBERING:
        return f"{space_label(zone, space_index, board)} ({distance} away)"
    unit = "space" if distance == 1 else "spaces"
    return (
        f"{space_label(zone, space_index, board)} "
        f"({distance} {unit} away)"
    )


def ball_space_label(match: MatchState) -> str:
    """Where the ball is standing, as a space code -- e.g. "M2"."""
    return space_label(
        match.ball.zone, match.ball.space_index, match.board,
    )


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


def role_brackets(role: PlayerRole) -> str:
    """`[FB]` -- the text form of a role, the one spelling of the
    brackets. `role_badge` writes it for a button, and the Discord
    resolver for a `{role:...}` token it has no upload for."""
    return f"[{ROLE_INITIALS[PlayerRole(role).value]}]"


def role_badge(
    player,
    badge: bool = False,
    team: Optional[Team] = None,
) -> str:
    """
    The role as it is written after a name: `[FB]`, or the mark of
    the badge for a frontend to draw where `badge` is asked for.

    The badge is a token, `{role:fullback:orange}`, rendered by the
    frontend from the application's emoji where one has been
    uploaded and as `[FB]` otherwise (`d12ball/tokens.py`). It is
    asked for rather than always written because the text form is
    right in two places the emoji cannot go: a button label and an
    autocomplete choice are plain text, and custom emoji markup in
    either shows as the raw `<:...:>`. So a caller asks for the badge
    in a *message* and not on a button, which is the same split as
    the team emoji -- see "Naming a player" in
    docs/design/naming-and-wording.md.

    **`team` is which of the player's two rosters this card is being
    fielded as**, and passing it is what asks for the coloured badge.
    Every message names a player through `format_player_label`,
    which already takes a team for the emoji in front, so the team is
    in hand wherever the badge is coloured -- and the one caller with
    no team to give is the one that must not have a colour at all:
    the goal log lists an own goal under the side it counted for,
    which is not the scorer's, so a coloured badge there would be the
    one thing on the line contradicting the heading over it. See
    `format_goal_scorer`.

    The three-step fallback -- the colour cut, then the plain badge,
    then the brackets -- is the Discord resolver's
    (`cogs.d12ball_helpers.DiscordTokens`): an application that has
    uploaded the six and none of the twenty-four reads exactly as it
    did before the colours existed.
    """
    if badge:
        return tokens.role(player.role, team)
    return role_brackets(player.role)


def player_with_role(
    player,
    badge: bool = False,
    team: Optional[Team] = None,
) -> str:
    """
    A card named the way every card in this game is named -- "Hellguard
    [FB]", or "Hellguard {role:fullback:orange}" in a message, which a
    frontend draws with the role emoji once they are uploaded.

    **A player is never named without their role.** Nine of them are on
    the field at once and a coach is choosing between them on what they
    do, so a bare name is the one thing a label can say that does not
    help: the role initials are what the meeple, the card on the board
    and the printed card all carry, so this is the name a coach can
    match to what they are looking at. See "Naming a player" in
    docs/design/naming-and-wording.md.

    This is the whole of the spelling, and the two things that add to
    it build on it: `RulesEngine.format_player_label` puts the team
    mark in front for a *message*, and a button adds the position
    instead. Nothing may spell the brackets out for itself -- that is
    how the run back's own buttons came to be the one place in the
    game that named a player and left the role off. `badge` and
    `team` are `role_badge`'s, and are asked for only where the text
    is going into a message -- the team being what asks for the badge
    in that side's own colour.

    It takes a `PlayerDefinition` rather than an id because the caller
    that has an id has a catalog to resolve it with, and this module
    has neither.
    """
    return f"{player.name} {role_badge(player, badge, team)}"


def coach_name(
    game: D12BallGame,
    player_number: Optional[int],
) -> str:
    """
    A coach *named*, as plain text: what the record calls them, "Player
    1" where it calls them nothing (or in a test game, where it must
    not), and the AI's name for the AI. The one reading of a coach's
    name off the record, which is why the Discord resolver renders
    `{coach:n}` through it for everybody it cannot mention.
    """
    if player_number == 1:
        if game.test_game:
            return "Player 1"
        return game.player_1_name or "Player 1"

    if player_number == 2:
        if game.test_game:
            return "Player 2"
        if game.player_2_id is None:
            return format_ai_name(game.ai_opponent)
        return game.player_2_name or "Player 2"

    return "Unknown player"


def format_player(
    game: D12BallGame,
    player_number: Optional[int],
    mention: bool = False,
) -> str:
    """
    A coach in a sentence: named (`coach_name`), or **addressed** where
    `mention` is asked for -- the token `{coach:1}`, which Discord
    renders as a mention of the account and the AI's name for the AI
    (`d12ball/tokens.py`). It built `<@id>` itself until step 9 of
    docs/architecture-migration.md, which is the model speaking
    Discord; a coach with no player number is "Unknown player" on
    either path, since nothing can be addressed to nobody.
    """
    if mention and player_number in (1, 2):
        return tokens.coach(player_number)
    return coach_name(game, player_number)


def address_coach(player_number: Optional[int]) -> str:
    """
    The bare address of a coach -- `{coach:1}` -- for the questions
    that open with one and nothing else: a speed choice, an own-goal
    roll, an injury test, a run back. "Someone" where no coach holds
    the side yet, which no position past the coin reaches.

    Until step 9 of docs/architecture-migration.md this was
    `f"<@{controller_id}>"` at five sites, and every one of them read
    "Someone" for the AI, which has no account: the token names the
    coach by number, so the AI is addressed by its name like anyone.
    """
    if player_number in (1, 2):
        return tokens.coach(player_number)
    return "Someone"


def format_player_with_team(
    game: D12BallGame,
    player_number: Optional[int],
    mention: bool = False,
) -> str:
    """
    "🟣 @coach" -- a coach named with their side's mark in front, which
    is how every message names one: the turn prompt, the maneuver
    picks, the coin toss, the loose-ball send.

    It read "@coach (Purple)" until 2026-09-16, the team spelled out in
    parentheses. The mark is the same one the board draws that side's
    meeples in and the same one every *player* label already carries
    (`RulesEngine.format_player_label`, "🟠 Hellguard [FB]"), so a
    coach and their cards now read as one side at a glance rather
    than by matching a word to a colour. Same position -- in front --
    for the same reason: one rule for "whose is this", not two. The
    mark is the token `{team:purple}`, drawn by the frontend.

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
    return f"{tokens.team(team)} {player}"


def format_player_with_team_name(
    game: D12BallGame,
    player_number: Optional[int],
) -> str:
    """
    "Dinky AI (Fire Demons)" -- a coach named with their team spelled
    out in words, for the one place a team emoji can't stand in for
    it: the board image's title, which Pillow draws as literal
    characters rather than resolving Discord's custom-emoji markup
    (see `render_match_png`). Every other surface names a team with
    its emoji, through `format_player_with_team`; this is the title's
    own fallback, not a second way to name a coach in a message.
    """
    player = format_player(game, player_number)
    team = (
        game.player_1_team
        if player_number == 1
        else game.player_2_team
    )
    if team is None:
        return player
    return f"{player} ({team_display_name(team)})"


def format_goal_time(goal: GoalRecord) -> str:
    """
    The minute a goal was scored, as a coach reads it back.

    **(FH) is the whole of what the clock cannot say by itself.** The
    second half starts at 15 and the clock runs past a period's last
    minute, so a first-half goal in the 17th minute and a second-half
    goal in the 17th are the same number -- and so are the two 15s.
    The marker is on the one that cannot be reached again.
    `GoalRecord.minute_repeated_in_second_half` is the rule; this is
    only the wording.
    """
    return f"{goal.time:02d}" + (
        " (FH)" if goal.minute_repeated_in_second_half else ""
    )


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


def ball_space_phrase(match: MatchState) -> str:
    """
    Where the ball is, as a phrase a sentence can be built around --
    "**M2** (Midfield)".

    The zone is spelled out beside the space code because "M2" alone
    means nothing to anyone who is not already looking at the board.
    This is the half `ball_location_line` puts a sentence around, split
    out so a caller with a sentence of its own does not have to
    swallow one whole -- Smooth's and Mind Pull's take-over lines each
    read "... takes the ball over on The ball is at **V1** (Visitors
    Third).." until 2026-09-20, which is what a sentence-shaped helper
    used mid-sentence gets you. The two are one wording in two shapes
    for `travel_space_label` and `travel_space_phrase`'s reason: what
    the two say about a space cannot drift apart.
    """
    zone = destination_display_name(
        match.ball.zone.value, match.board.layout.board_size
    )
    return f"**{ball_space_label(match)}** ({zone})"


def ball_location_line(match: MatchState) -> str:
    """
    Where the ball has come to rest, in a sentence -- a coach who is
    about to be asked whether to send somebody after it is being asked
    about a distance. Use `ball_space_phrase` where the sentence is
    already somebody else's.
    """
    return f"The ball is at {ball_space_phrase(match)}."


def format_goal_scorer(
    goal: GoalRecord,
    catalog: PlayerCatalog,
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
    name = player_with_role(player, badge=True)
    return f"{name} (OG)" if goal.own_goal else name


def build_goal_log(
    match: MatchState,
    catalog: PlayerCatalog,
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
            f"**{tokens.team(setup.team)} "
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
                f"{tokens.team(setup.team)} "
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
        f"**Final score:** {team_display_name(match.home.team)} "
        f"{home_score}:{visiting_score} "
        f"{team_display_name(match.visiting.team)}"
    )

    shootout = match.shootout_score_line()
    if shootout:
        score_line = f"{score_line}\n{shootout}"

    if home_score == visiting_score:
        return (
            f"{score_line}\n\n"
            "# It's a tie! The game goes to the extreme shootout."
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


def contestant_detail(
    player: PlayerDefinition,
    skill_word: str,
    skill: int,
    injured: bool = False,
    cyborg: bool = False,
) -> list[str]:
    """
    The lines naming one side of a contest on the dice image: who is
    rolling, and what they add to it.

    `injured` is only ever passed by the contests injury actually bites
    in -- the loose ball, the long High Pass and the shootout, where an
    injured contestant's own skill stays off the roll and nothing else
    does. A maneuver's skill test and a score attempt are untouched by
    it and pass nothing, which is the rule rather than an omission; see
    "Injured players" in docs/living-rules.md.

    `cyborg` only ever changes the word, to Damaged -- a Cyborg's own
    name for Injured (see "Lithium Powered" in docs/living-rules.md).
    Drawn text cannot carry a Discord emoji, so unlike a message this
    has no icon to swap; the caller answers it off
    `RulesEngine.has_species_ability` the same way it already answers
    `injured`.
    """
    return [
        player_with_role(player),
        ("Damaged" if cyborg else "Injured") + " — no skill modifier"
        if injured
        else f"{skill_word} skill +{skill}",
    ]

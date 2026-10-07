"""
The rendering briefs over a roll's numbers and a matchup's players:
what `render.py` is handed, worked out from the model's own values.

**Both used to be the cog's**, and neither was Discord's. The skill
test's dice (`render_contest_dice`) turn a `ContestDice` side into the
tuple `render_skill_test_dice` draws, and a matchup's side
(`challenge_side`) turns a player into the `ChallengeSide` the
challenge and shot images draw. Each reads only the model and the
catalog; the cog wrapped one in a `discord.File` and the other sat on
the mixin because that is where its callers were. A second frontend
may not import `cogs/`, so the picture of a roll could not be the same
picture on both until they moved below the renderer (step 7 of
docs/web-app-next.md). What is left on the Discord side is the file
and the worker thread.

**So did the two matchups' whole briefs** (step 8): who is drawn on
each side of a challenge and a shot, with what, over which caption --
`maneuver_challenge_brief` and `score_attempt_brief`, which the cog's
`build_maneuver_challenge_file` and `build_score_attempt_file` wrap in
a file and the web app serves, so the two frontends draw one picture.

It imports `render.py`, and so Pillow: it is the drawing side of the
model, never under the engine. See "What it may not do" in
docs/design/web-app.md, and the purity ratchets in
tests/test_model_purity.py.
"""

from __future__ import annotations

from dataclasses import replace
from io import BytesIO
from typing import TYPE_CHECKING, Optional, Sequence

from d12ball.bearings import BEARINGS, Bearing, special_reminder
from d12ball.components import MatchState, PlayerRole, TeamSide
from d12ball import tokens
from d12ball.formatting import (
    ball_space_label,
    capitalized,
    coach_name,
    format_team_side_label,
    player_with_role,
    role_brackets,
    role_initials,
    side_display_name,
)
from d12ball.game import D12BallGame, Team, team_display_name
from d12ball.special_abilities import SpecialAbility
from d12ball.render import (
    TEAM_COLORS,
    ChallengeSide,
    IgnitionDie,
    MatchupNote,
    render_skill_test_dice,
    zone_labels,
)

if TYPE_CHECKING:
    from d12ball.engine import RulesEngine


def render_contest_dice(
    contestants: list[
        tuple[int, Team, list[str], int, bool, list[tuple[str, int]]]
    ],
    ignitions: Sequence[tuple[int, IgnitionDie]] = (),
) -> BytesIO:
    """
    The dice image behind every two-sided roll in the game -- a skill
    test, a loose ball, a score attempt, a shootout test -- as
    `(roll, team, detail lines, total, overdriven, merge contributors)`
    a side, which is `ContestDice.contestants` exactly.

    The image carries the whole arithmetic, which is why no message
    that posts one repeats it in text. Rendering is Pillow and pure
    CPU, so every caller runs this in a worker thread; see "Discord's
    rate limits" in docs/design/rate-limits.md.

    `ignitions` is the ignites drawn beside the dice, each keyed on its
    side's index in `contestants` -- the Discord frontend's alone for
    now; see "The ignition die" in docs/design/species-abilities.md.
    """
    return render_skill_test_dice(
        [
            (
                roll,
                TEAM_COLORS[team],
                team_display_name(team),
                [drawn_line(line) for line in detail],
                total,
                overdriven,
                merge,
            )
            for roll, team, detail, total, overdriven, merge in contestants
        ],
        ignitions,
    )


def drawn_line(line: str) -> str:
    """
    A detail line as the dice picture draws it. A line that names a
    player -- a defender in the shot's wall, an Ooze adding by Merge --
    names them as every message does, with the team's mark and the
    role badge as tokens (`d12ball/tokens.py`), because the same line
    is the working the web page writes under its headline. A picture
    cannot draw a badge, so here the mark is left off and the badge is
    its text form, "Dravox [DD]" -- what `player_with_role` writes. A
    line with no token in it is drawn exactly as it always was.
    """
    if not tokens.find(line):
        return line

    def plain(kind: str, arguments: tuple[str, ...]) -> Optional[str]:
        if kind == "team":
            return ""
        if kind == "role":
            return role_brackets(PlayerRole(arguments[0]))
        return None

    return " ".join(tokens.render(line, plain).split())


def challenge_side(
    engine: RulesEngine,
    player_id: str,
    team: Team,
    attacking: bool,
    modifiers: tuple[str, ...] = (),
    contribution: Optional[int] = None,
    halved: bool = False,
    game: Optional[D12BallGame] = None,
    passed: bool = False,
    as_on_ball: bool = False,
    merging: bool = False,
    bearing: Optional[Bearing] = None,
    side: Optional[TeamSide] = None,
) -> ChallengeSide:
    """
    A player as a matchup image draws them. The ability is the
    short form: this is a caption under a portrait, next to
    another player's, and the sentence version wrapped to three
    lines and set the height of the whole image. The full text is
    still what the roster and the rules listing show.

    `contribution`, `halved`, `passed` and `as_on_ball` are a score
    attempt's defenders only -- everyone else adds their whole skill and is drawn
    without a word about it -- but for `merging`, an Ooze on the ball
    whose `contribution` is what they add by Merge (`merging_sides`). `team` is which of the player's two
    rosters this match is fielding them as -- read by both callers
    off `match.team_for_player`, since a player's own definition no
    longer carries one.

    A rendering brief: it was `RulesEngine.challenge_side` until step
    9 of docs/architecture-migration.md, and the one thing that made
    the engine import `d12ball/render.py` -- and Pillow with it, in
    every process that loaded the model -- and then the cog's until
    step 7 of docs/web-app-next.md. The numbers it reads are the
    catalog's; the colour is `TEAM_COLORS`'s, which lives with the
    renderer that draws it. The skill is the game's
    (`RulesEngine.skills`), so an advanced score is drawn as the dice
    add it.

    `bearing` is which part of which roll the player is in, and so
    which of their special abilities the image reminds of
    (`bearings.special_reminder`); `None` reminds of none.

    `side` is the end the player's side plays from, which the two
    briefs below give a group's lead: the image's heading then names
    the side, with the team's emoji in front and its coach after
    (`side_coach`), in place of the team's name.
    """
    player = engine.get_player_definition(player_id)
    profile = engine.player_catalog.effective_profile(player)
    skills = engine.skills(game, player_id)
    return ChallengeSide(
        name=player.name,
        role=role_initials(player),
        team_color=TEAM_COLORS[Team(team)],
        team_label=team_display_name(team),
        skill_name="Offensive" if attacking else "Defensive",
        skill=skills.offense if attacking else skills.defense,
        ability=profile.short_ability,
        modifiers=modifiers,
        contribution=contribution,
        halved=halved,
        passed=passed,
        as_on_ball=as_on_ball,
        merging=merging,
        special=(
            special_reminder(engine, game, player_id, bearing)
            if bearing is not None
            else ""
        ),
        side_label="" if side is None else side_display_name(side),
        team=None if side is None else Team(team),
        coach="" if side is None else side_coach(engine, game, side),
    )


def side_coach(
    engine: RulesEngine,
    game: Optional[D12BallGame],
    side: TeamSide,
) -> str:
    """Who coaches `side`, as a matchup image names them beside their
    team: the record's name (`coach_name`) -- the account's display
    name, the AI's name for the AI, "Player 1" in a test game -- or
    `""` with no record, or before the coin has seated anybody."""
    if game is None:
        return ""
    number = engine.side_player_number(game, side)
    if number is None:
        return ""
    return coach_name(game, number)


def merging_sides(
    engine: RulesEngine,
    match: MatchState,
    side: TeamSide,
    rolling: Sequence[Optional[str]],
    skill: str,
    game: Optional[D12BallGame] = None,
) -> list[ChallengeSide]:
    """
    Every Ooze on the ball Merging into `side` (Law 20.5), as a matchup
    draws them: part of the side, beside the player they merge into,
    with what each adds as their `contribution`. Who Merges and for how
    much is `RulesEngine.merge_contributions`, asked as the roll asks
    it -- `rolling` struck out, `skill` "offense" on the attack and
    "defense" on the defence -- so the picture's sum is the dice's.
    Glompex once he has stepped on is one of them, and so is every
    other Ooze standing there.
    """
    if game is None:
        return []
    return [
        challenge_side(
            engine,
            player_id,
            match.team_for_player(player_id),
            attacking=skill == "offense",
            contribution=value,
            game=game,
            merging=True,
            bearing=BEARINGS["merge"],
        )
        for player_id, value in engine.merge_contributions(
            game, match, side, rolling, skill,
        )
    ]


def maneuver_challenge_brief(
    engine: RulesEngine,
    match: MatchState,
    defender_id: str,
    game: Optional[D12BallGame] = None,
) -> tuple[list[ChallengeSide], list[ChallengeSide], str]:
    """
    The matchup about to be contested, as `render_maneuver_challenge`
    takes it: the player on the ball, the challenger `defender_id`
    names, and where on the field it is. It stands in for the two lines
    of prose that used to announce a challenge: the players' skills and
    abilities are what a coach weighs while choosing a maneuver, and
    neither was in the text.

    Each side is a list: its player first, then every Ooze on the
    ball Merging into them (`merging_sides`), because an Ooze who adds
    to the skill test is part of the maneuver -- Glompex once he has
    joined, and any other (the author, 2026-09-30).

    The challenger is handed in rather than read off the match: by the
    time a frontend draws it the match may have moved on, and the walk-in
    that named them carries the id (`Narration.arguments`).
    """
    rolling = (match.active_player_id, defender_id)
    return (
        [
            challenge_side(
                engine,
                match.active_player_id,
                match.team_for_player(match.active_player_id),
                attacking=True,
                game=game,
                bearing=BEARINGS["skill_test_attack"],
                side=match.ball.possession,
            ),
            *merging_sides(
                engine, match, match.ball.possession, rolling, "offense", game,
            ),
        ],
        [
            challenge_side(
                engine,
                defender_id,
                match.team_for_player(defender_id),
                attacking=False,
                game=game,
                bearing=BEARINGS["skill_test_defence"],
                side=match.defending_side(),
            ),
            *merging_sides(
                engine, match, match.defending_side(), rolling, "defense",
                game,
            ),
        ],
        capitalized(
            f"{ball_space_label(match)}"
            f" — {zone_labels(match.board.layout.board_size)[match.ball.zone].title()}"
        ),
    )


def challenge_noted(
    engine: RulesEngine,
    match: MatchState,
    game: Optional[D12BallGame] = None,
) -> list[str]:
    """
    Who has a special ability that bears on the maneuver challenge
    without being in it: Quantor, while a teammate is on the ball,
    since he may run onto their High Pass or Cross and the coach is
    choosing the card (`pass_runner_on_field`; the author, 2026-09-28
    on the page, 2026-10-02 on Discord). Both frontends say it -- the
    page's window as a note, the bot's image in its notes row.
    """
    runner = engine.pass_runner_on_field(game, match)
    return [runner] if runner is not None else []


def maneuver_challenge_notes(
    engine: RulesEngine,
    match: MatchState,
    game: Optional[D12BallGame] = None,
) -> list[MatchupNote]:
    """`challenge_noted` as `render_maneuver_challenge` draws it: each
    player with their role, their team's colour and their card's own
    sentence (`special_ability_text`)."""
    if game is None:
        return []
    notes = []
    for player_id in challenge_noted(engine, match, game):
        text = engine.special_ability_text(game, player_id)
        if not text:
            continue
        notes.append(MatchupNote(
            who=player_with_role(engine.get_player_definition(player_id)),
            team_color=TEAM_COLORS[match.team_for_player(player_id)],
            text=text,
        ))
    return notes


def score_attempt_brief(
    engine: RulesEngine,
    match: MatchState,
    game: Optional[D12BallGame] = None,
    ability_note: bool = True,
) -> tuple[list[ChallengeSide], list[ChallengeSide], str]:
    """
    What the shot is made of, as `render_score_attempt` takes it: the
    shooter with the modifiers this particular attempt earns them, and
    every defender between them and the goal. The attack is a list:
    the shooter, then any Ooze on the ball Merging into the attack --
    the attack alone, since the wall already counts a defending one
    (Law 20.5.3; `merging_sides`).

    The two modifiers are listed on the shooter rather than folded
    into their skill, because both are conditions of this attempt
    and not of the player -- the ball speed is spent on the shot,
    and the Striker's +3 only applies off a set-up.

    The defenders are the other way round: what each one adds is
    folded in, as their `contribution`, because a coach counting
    the wall is asking what it comes to and not what it would come
    to somewhere else on the field. A defender Flickerwing's shot
    passes is still drawn, at 0, and the shooter carries the ability's
    line (`RulesEngine.clear_shot_note`) as a condition of this
    attempt like the other two -- unless `ability_note` is off, for a
    frontend that reminds of abilities its own way (the web page's
    chip), so the ability is said once. Who they are is
    `RulesEngine.intervening_defenders`, the reading the roll adds.

    Where the attack adds two numbers or more, the shooter carries
    their sum as `total_modifier`, which the image draws bold under the
    modifiers -- the number the shot's dice will add.

    Each side carries the special abilities that bear on the shot
    (`ChallengeSide.special`, off `BEARINGS`), the shooter's without
    the clear shot where the modifier already says it, and a
    defender's without Goopkeeper's block unless it is what puts them
    on the ball.
    """
    shooter = engine.get_player_definition(match.active_player_id)
    speed_modifier = match.shot_speed_modifier()
    defenders = engine.intervening_defenders(match, game)
    defending_setup = match.setup_for_side(match.defending_side())

    modifiers = []
    if speed_modifier:
        modifiers.append(
            f"{speed_modifier:+d} ball speed ({match.ball.speed}"
            + (", halved from midfield" if match.shot_speed_halved() else "")
            + ")"
        )
    striker = (
        3 if match.pending_shot_is_set_up
        and shooter.role == PlayerRole.STRIKER else 0
    )
    if striker:
        modifiers.append(f"{striker:+d} Striker ability")
    clear_shot = engine.clear_shot_note(game, shooter.player_id, defenders)
    shooter_bearing = BEARINGS["shot_attack"]
    if clear_shot and ability_note:
        modifiers.append(clear_shot)
        # Said once: the modifier already is the sentence.
        shooter_bearing = _without(shooter_bearing, SpecialAbility.CLEAR_SHOT)

    attack = [
        challenge_side(
            engine,
            shooter.player_id,
            match.team_for_player(shooter.player_id),
            attacking=True,
            game=game,
            modifiers=tuple(modifiers),
            bearing=shooter_bearing,
            side=match.ball.possession,
        ),
        *merging_sides(
            engine, match, match.ball.possession, (shooter.player_id,),
            "offense", game,
        ),
    ]
    # Every number the attack adds before the dice -- the skill, each
    # Ooze's merge, the ball speed, the Striker's +3 -- summed in bold
    # where there are two or more (the author, 2026-10-06), as the dice
    # image sums them after the roll. Zero adds nothing and is not one.
    addends = [
        value
        for value in (
            *(side.value for side in attack), speed_modifier, striker,
        )
        if value
    ]
    if len(addends) > 1:
        attack[0] = replace(attack[0], total_modifier=sum(addends))

    return (
        attack,
        [
            challenge_side(
                engine,
                defender.player.player_id,
                match.team_for_player(defender.player.player_id),
                attacking=False,
                contribution=defender.value,
                halved=defender.halved,
                passed=defender.passed,
                as_on_ball=defender.as_on_ball,
                game=game,
                # Goopkeeper's block only where it changes the shot:
                # beyond the ball. On it, they are on it anyway (the
                # author, 2026-09-30).
                bearing=(
                    BEARINGS["shot_defence"]
                    if defender.as_on_ball
                    else _without(
                        BEARINGS["shot_defence"], SpecialAbility.FULL_BLOCK,
                    )
                ),
                side=match.defending_side(),
            )
            for defender in defenders
        ],
        capitalized(
            f"{ball_space_label(match)}"
            f" → {format_team_side_label(defending_setup)} goal"
        ),
    )


def _without(bearing: Bearing, ability: SpecialAbility) -> Bearing:
    """A bearing with one special ability struck out of it."""
    return replace(bearing, special=bearing.special - {ability})

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

from io import BytesIO
from typing import TYPE_CHECKING, Optional

from d12ball.components import MatchState, PlayerRole
from d12ball.formatting import (
    ball_space_label,
    capitalized,
    format_team_side_label,
    role_initials,
)
from d12ball.game import D12BallGame, Team, team_display_name
from d12ball.render import (
    TEAM_COLORS,
    ChallengeSide,
    render_skill_test_dice,
    zone_labels,
)

if TYPE_CHECKING:
    from d12ball.engine import RulesEngine


def render_contest_dice(
    contestants: list[
        tuple[int, Team, list[str], int, bool, list[tuple[str, int]]]
    ],
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
    """
    return render_skill_test_dice(
        [
            (
                roll,
                TEAM_COLORS[team],
                team_display_name(team),
                detail,
                total,
                overdriven,
                merge,
            )
            for roll, team, detail, total, overdriven, merge in contestants
        ],
    )


def challenge_side(
    engine: RulesEngine,
    player_id: str,
    team: Team,
    attacking: bool,
    modifiers: tuple[str, ...] = (),
    contribution: Optional[int] = None,
    halved: bool = False,
    game: Optional[D12BallGame] = None,
) -> ChallengeSide:
    """
    A player as a matchup image draws them. The ability is the
    short form: this is a caption under a portrait, next to
    another player's, and the sentence version wrapped to three
    lines and set the height of the whole image. The full text is
    still what the roster and the rules listing show.

    `contribution` and `halved` are a score attempt's defenders
    only -- everyone else adds their whole skill and is drawn
    without a word about it. `team` is which of the player's two
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
    )


def maneuver_challenge_brief(
    engine: RulesEngine,
    match: MatchState,
    defender_id: str,
    game: Optional[D12BallGame] = None,
) -> tuple[ChallengeSide, ChallengeSide, str]:
    """
    The matchup about to be contested, as `render_maneuver_challenge`
    takes it: the player on the ball, the challenger `defender_id`
    names, and where on the field it is. It stands in for the two lines
    of prose that used to announce a challenge: the players' skills and
    abilities are what a coach weighs while choosing a maneuver, and
    neither was in the text.

    The challenger is handed in rather than read off the match: by the
    time a frontend draws it the match may have moved on, and the walk-in
    that named them carries the id (`Narration.arguments`).
    """
    return (
        challenge_side(
            engine,
            match.active_player_id,
            match.team_for_player(match.active_player_id),
            attacking=True,
            game=game,
        ),
        challenge_side(
            engine,
            defender_id,
            match.team_for_player(defender_id),
            attacking=False,
            game=game,
        ),
        capitalized(
            f"{ball_space_label(match)}"
            f" — {zone_labels(match.board.layout.board_size)[match.ball.zone].title()}"
        ),
    )


def score_attempt_brief(
    engine: RulesEngine,
    match: MatchState,
    game: Optional[D12BallGame] = None,
) -> tuple[ChallengeSide, list[ChallengeSide], str]:
    """
    What the shot is made of, as `render_score_attempt` takes it: the
    shooter with the modifiers this particular attempt earns them, and
    every defender between them and the goal.

    The two modifiers are listed on the shooter rather than folded
    into their skill, because both are conditions of this attempt
    and not of the player -- the ball speed is spent on the shot,
    and the Striker's +3 only applies off a set-up.

    The defenders are the other way round: what each one adds is
    folded in, as their `contribution`, because a coach counting
    the wall is asking what it comes to and not what it would come
    to somewhere else on the field. Who they are is
    `RulesEngine.intervening_defenders`, the reading the roll adds.
    """
    shooter = engine.get_player_definition(match.active_player_id)
    speed_modifier = match.ball_speed_modifier()
    defenders = engine.intervening_defenders(match, game)
    defending_setup = match.setup_for_side(match.defending_side())

    modifiers = []
    if speed_modifier:
        modifiers.append(
            f"{speed_modifier:+d} ball speed ({match.ball.speed})"
        )
    if match.pending_shot_is_set_up and shooter.role == PlayerRole.STRIKER:
        modifiers.append("+3 Striker ability")

    return (
        challenge_side(
            engine,
            shooter.player_id,
            match.team_for_player(shooter.player_id),
            attacking=True,
            game=game,
            modifiers=tuple(modifiers),
        ),
        [
            challenge_side(
                engine,
                defender.player.player_id,
                match.team_for_player(defender.player.player_id),
                attacking=False,
                contribution=defender.value,
                halved=defender.halved,
                game=game,
            )
            for defender in defenders
        ],
        capitalized(
            f"{ball_space_label(match)}"
            f" → {format_team_side_label(defending_setup)} goal"
        ),
    )

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

It imports `render.py`, and so Pillow: it is the drawing side of the
model, never under the engine. See "What it may not do" in
docs/design/web-app.md, and the purity ratchets in
tests/test_model_purity.py.
"""

from __future__ import annotations

from io import BytesIO
from typing import TYPE_CHECKING, Optional

from d12ball.formatting import role_initials
from d12ball.game import D12BallGame, Team, team_display_name
from d12ball.render import (
    TEAM_COLORS,
    ChallengeSide,
    render_skill_test_dice,
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

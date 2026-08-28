"""
The pieces every other view module needs: `SafeView`, which nearly
every view in the game subclasses, and the two helpers that render a
contest.

It imports from no sibling, which is what keeps the package a DAG.
"""

import asyncio
import discord
from typing import Optional

from d12ball.components import (
    MatchState,
    PlayerDefinition,
)
from d12ball.game import (
    D12BallGame,
    Team,
    team_display_name,
)
from d12ball.render import (
    TEAM_COLORS,
    render_skill_test_dice,
)
from cogs.d12ball_helpers import (
    ERROR_RECOVERY_ADVICE,
    LOGGER,
    ROLE_INITIALS,
    send_error_fallback,
)


def contestant_detail(
    player: PlayerDefinition,
    skill_word: str,
    skill: int,
    injured: bool = False,
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
    """
    return [
        f"{player.name} [{ROLE_INITIALS[player.role.value]}]",
        "Injured — no skill modifier"
        if injured
        else f"{skill_word} skill +{skill}",
    ]


async def render_contest_dice(
    contestants: list[tuple[int, Team, list[str], int]],
    filename: str,
) -> discord.File:
    """
    The dice image behind every two-sided roll in the game -- a skill
    test, a loose ball, a score attempt, a shootout test -- as
    `(roll, team, detail lines, total)` a side.

    The image carries the whole arithmetic, which is why no message
    that posts one repeats it in text. Rendering is Pillow and pure
    CPU, so it goes to a worker thread; see "Discord's rate limits" in
    CLAUDE.md.
    """
    return discord.File(
        await asyncio.to_thread(
            render_skill_test_dice,
            [
                (
                    roll,
                    TEAM_COLORS[team],
                    team_display_name(team),
                    detail,
                    total,
                )
                for roll, team, detail, total in contestants
            ],
        ),
        filename=filename,
    )


class SafeView(discord.ui.View):
    """
    Base class for every D12 Ball view. discord.py's default behavior
    for an uncaught exception in a button/select callback is to log it
    and otherwise do nothing, which leaves the click looking like it
    had no effect at all. This surfaces a message instead.

    Every subclass carries `self.cog` and `self.game_id`, set in
    `__init__` before anything below is ever called -- that is what
    lets `load_match`/`require_match` read them rather than take them
    as parameters.
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
            "Something went wrong handling that click. "
            f"{ERROR_RECOVERY_ADVICE}",
        )

    def load_match(
        self,
    ) -> tuple[Optional[D12BallGame], Optional[MatchState]]:
        """
        `(game, match)` for `self.game_id`, or `(None, None)` when the
        game is gone or has no match state yet -- the lookup nearly
        every view opens with, in `__init__` and in most of its
        callbacks. Silent: `__init__` has no interaction to reply to,
        which is why this doesn't reply and `require_match` does.
        """
        game = self.cog.games.get(self.game_id)
        if game is None or game.match_state is None:
            return None, None
        return game, self.cog.engine.load_match_state(game)

    async def require_match(
        self,
        interaction: discord.Interaction,
    ) -> tuple[Optional[D12BallGame], Optional[MatchState]]:
        """
        Same lookup as `load_match`, replying "I could not find the
        saved data for this game." and returning `(None, None)` when it
        comes up empty -- the shape nearly every callback opens with,
        once there is an interaction to answer.
        """
        game, match = self.load_match()
        if game is None:
            await interaction.response.send_message(
                "I could not find the saved data for this game.",
                ephemeral=True,
            )
        return game, match

    def is_game_participant(self, game: D12BallGame, user_id: int) -> bool:
        """
        Whether `user_id` is one of the two coaches in `game` -- never
        the AI, which has no user id to be. See "Every roll is a
        coach's" in CLAUDE.md: any coach in the game may press a roll
        button, not only the one it happens to be about, so this is
        the whole of the check and callers word their own refusal.
        """
        participant_ids = {game.player_1_id}
        if game.player_2_id is not None:
            participant_ids.add(game.player_2_id)
        return user_id in participant_ids


    def pay_skill_test_tie(
        self,
        game: D12BallGame,
        match: MatchState,
        first_player_id: str,
        second_player_id: str,
        offense_total: int,
        defense_total: int,
    ) -> str:
        """
        Charge both contestants the re-roll's exhaustion token, save,
        and word the tie -- shared by the maneuver skill test and the
        loose ball (which the long High Pass also comes through).

        The token counts towards Exhausted straight away, so whoever it
        pushes over is already flagged when the test finally resolves
        and hands out its injury checks.

        The edit that posts this stays with the caller: one of the two
        has deferred and answers on `edit_original_response`, the other
        has not and answers on `interaction.response.edit_message`, and
        a flag here would hide a difference that is real.
        """
        exhaustion_text = "\n".join(
            [
                self.cog.apply_exhaustion(match, first_player_id, 1),
                self.cog.apply_exhaustion(match, second_player_id, 1),
            ]
        )
        self.cog.persist(game, match)

        # Headed like the outcome it is: a tie is one of the four ways
        # a skill test lands, and every other one is announced at `##`
        # (see SkillTestView.roll). Left as bold body text it read as a
        # footnote to the dice rather than the result of them.
        return (
            f"## **It's a tie ({offense_total}-{defense_total})!**\n"
            f"The skill test must be rolled again.\n"
            f"{exhaustion_text}\n\nRoll again:"
        )

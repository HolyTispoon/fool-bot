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
    OVERDRIVE_BONUS,
    OVERDRIVE_DRAIN_COST,
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
    game_participant_ids,
    # Aliased because `SafeView` carries methods of these two names --
    # the interaction-shaped front door onto the same two functions.
    # One rule either way; the alias is only so a method body does not
    # read as a recursive call.
    may_act_for_coach as user_may_act_for_coach,
    may_act_in_game as user_may_act_in_game,
    player_with_role,
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
        player_with_role(player),
        "Injured — no skill modifier"
        if injured
        else f"{skill_word} skill +{skill}",
    ]


async def render_contest_dice(
    contestants: list[
        tuple[int, Team, list[str], int, bool, list[tuple[str, int]]]
    ],
    filename: str,
) -> discord.File:
    """
    The dice image behind every two-sided roll in the game -- a skill
    test, a loose ball, a score attempt, a shootout test -- as
    `(roll, team, detail lines, total, overdriven, merge contributors)`
    a side.

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
                    overdriven,
                    merge,
                )
                for roll, team, detail, total, overdriven, merge in contestants
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
        the AI, which has no user id to be.

        This is a fact about the game and is **not** the authorization
        check: a game helper is not a participant and may still press
        the button. Ask `may_act_in_game` or `may_act_for` for that --
        see "Who may act on a game" in CLAUDE.md.
        """
        return user_id in game_participant_ids(game)

    def may_act_in_game(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
    ) -> bool:
        """
        Whether this click may press a button either coach may press --
        a roll, the maneuver reference. Either coach, or a game helper.

        See "Every roll is a coach's" in CLAUDE.md: any coach in the
        game may press a roll button, not only the one it happens to be
        about, so this is the whole of the check and callers word their
        own refusal.
        """
        return user_may_act_in_game(interaction.user, game)

    def may_act_for(
        self,
        interaction: discord.Interaction,
        coach_id: Optional[int],
    ) -> bool:
        """
        Whether this click may press a button that belongs to one
        particular coach -- that coach, or a game helper. `coach_id` is
        whatever named them: `side_controller_id`, `controlling_user_id`,
        `possession_user_id`, `defending_user_id`.
        """
        return user_may_act_for_coach(interaction.user, coach_id)

    def may_act_for_possession(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> bool:
        """
        `may_act_for` the coach whose team has the ball -- the gate on
        every offensive choice and every effect the winner resolves.
        Replaces `engine.user_controls_possession` at a callback: the
        engine answers who that coach is, and this answers whether the
        click may act for them.
        """
        return self.may_act_for(
            interaction,
            self.cog.engine.possession_user_id(game, match),
        )

    def may_act_for_defense(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> bool:
        """
        `may_act_for` the coach defending this turn -- the challenge,
        the defensive pick, and the effects a won defense resolves. The
        other half of `may_act_for_possession`.
        """
        return self.may_act_for(
            interaction,
            self.cog.engine.defending_user_id(game, match),
        )

    def add_overdrive_buttons(
        self,
        game: D12BallGame,
        match: MatchState,
        player_ids,
    ) -> None:
        """
        Put an Overdrive button on this roll prompt for every Cyborg
        about to roll on it -- **the one way Lithium Powered's
        declaration reaches a coach**, shared by all six roll prompts
        so a seventh gets it with one line.

        Overdrive is the only thing in the game declared *before* a
        roll, and every roll already sits behind a button any coach may
        press (see "Every roll is a coach's"). So it is a second button
        on the same message rather than a step of its own: the coach
        whose Cyborg it is presses it, the message says so, and
        whoever was going to press Roll still does. `player_ids` is
        whoever is rolling here, which only the prompt knows.

        The button is **not** built for a Cyborg who has already
        declared -- "once per roll" -- so a message that has been
        clicked comes back with one fewer button, which is also how a
        coach can see the declaration took.
        """
        for player_id in self.cog.engine.overdrive_candidates(
            game, match, player_ids,
        ):
            player = self.cog.engine.get_player_definition(player_id)
            button = discord.ui.Button(
                label=(
                    f"⚡ Overdrive: {player_with_role(player)} "
                    f"({OVERDRIVE_DRAIN_COST} drain, +{OVERDRIVE_BONUS})"
                )[:80],
                style=discord.ButtonStyle.secondary,
                # The player is in the custom_id as well as the match's
                # own list, so a coach who scrolls back to an older
                # prompt cannot declare for somebody else's roll -- the
                # same reason the injury test's button carries one.
                custom_id=(
                    f"d12ball:overdrive:{self.game_id}:{player_id}"
                ),
            )
            button.callback = self.declare_overdrive
            self.add_item(button)

    async def declare_overdrive(
        self, interaction: discord.Interaction,
    ) -> None:
        """
        Answer an Overdrive button: charge the 3 drain, record the
        declaration, and edit the prompt so it says so.

        Only the coach whose side that Cyborg is on may press it --
        unlike the roll itself, which either coach may throw. A
        declaration is a decision about someone's own player and a
        commitment of their tokens, so it is theirs alone.
        """
        game, match = await self.require_match(interaction)
        if game is None:
            return

        player_id = interaction.data["custom_id"].rsplit(":", 1)[-1]
        if not self.may_act_for(
            interaction,
            self.cog.engine.controlling_user_id(game, match, player_id),
        ):
            await interaction.response.send_message(
                "Only the coach whose player that is can declare "
                "Overdrive for them.",
                ephemeral=True,
            )
            return

        # Re-checked rather than trusted: this prompt may have been
        # sitting in the channel since before the roll it was built
        # for, and the candidate list is what says the declaration is
        # still available.
        if not self.cog.engine.overdrive_candidates(
            game, match, [player_id],
        ):
            await interaction.response.send_message(
                "That Overdrive is no longer available.",
                ephemeral=True,
            )
            return

        match.declare_overdrive(
            player_id,
            self.cog.engine.exhaustion_threshold(game, player_id),
        )
        self.cog.persist(game, match)

        player = self.cog.engine.get_player_definition(player_id)
        await interaction.response.send_message(
            f"⚡ **Overdrive** — {self.cog.player_label(match, player)} "
            f"takes {OVERDRIVE_DRAIN_COST} drain for "
            f"+{OVERDRIVE_BONUS} on this roll.",
        )


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
                self.cog.apply_exhaustion(game, match, first_player_id, 1),
                self.cog.apply_exhaustion(game, match, second_player_id, 1),
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

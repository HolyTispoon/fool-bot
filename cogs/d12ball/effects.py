"""
The entry points into a maneuver's effect, and the dice a coach is
shown.

**Nothing here decides anything.** Every method below is one of two
shapes: it calls one flow step in `d12ball/flow/` and hands the result
to the dispatcher, or it names one step by its `FollowOnStep` and hands
*that* to the dispatcher -- `D12Ball.run_step`. The decisions those
steps used to be interleaved with (does anybody choose, what Dinky
picks, what a card with nowhere to go does) are the `offer_*` steps in
`d12ball/flow/effects.py` since Phase 6 of docs/design/model-discord-split.md.

What is left that is genuinely Discord's: the two dice images the
own-goal roll and the Mind Pull put between their two sentences.
"""

import asyncio
import discord

from d12ball.flow import FollowOnStep
from d12ball.flow.effects import own_goal_roll_step
from d12ball.components import MatchState
from d12ball.game import D12BallGame, team_display_name
from d12ball.render import (
    TEAM_COLORS,
    render_mind_pull_die,
    render_own_goal_dice,
)
from gamesaves.d12ball.service import GameResult
from cogs.d12ball_helpers import send_new_prompt


class ManeuverEffectsMixin:
    """
    The entry points into a maneuver's effect, and the dice a coach is
    shown.
    """

    # -- Low Pass --------------------------------------------------


    # -- Dribble Advance ---------------------------------------------


    # -- High Pass -----------------------------------------------------


    # -- The arrival gates' exits -------------------------------------


    async def post_mind_pull_die(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        result: GameResult,
    ) -> None:
        """
        The die a Mind Pull rolled, where the offer was, and then what
        it came to.

        **The die goes between the offer and the result.** A message's
        attachments render below its content, so a result written on
        the same message would be read before the roll that decided
        it. The offer becomes the die and what it came to is said in
        the message after -- the same way round as every other roll in
        the game; see `SkillTestView.roll`. A player injured between
        being queued and answering rolls nothing (`roll` is None), and
        the queue simply carries on.

        `match` is the position the offer was asked over, for the
        die's colours; the service has already saved what the roll
        settled and run what followed.
        """
        roll = result.detail
        if roll is None:
            await self.present(interaction, game, result)
            return

        player = self.engine.get_player_definition(roll.player_id)
        player_team = match.team_for_player(roll.player_id)
        dice_file = discord.File(
            await asyncio.to_thread(
                render_mind_pull_die,
                roll.roll,
                TEAM_COLORS[player_team],
                team_display_name(player_team),
                player.name,
                roll.pulled,
            ),
            filename="mind_pull_die.png",
        )
        await interaction.edit_original_response(
            content=None,
            attachments=[dice_file],
            view=None,
        )
        # Asked for the reason the ignite is asked at all: Volatile is
        # a Fire Demon's and this is a Telekinetic's roll, so this
        # posts nothing today -- and the day a card carries both, the
        # second die is shown here rather than being the one roll in
        # the game that swallows it.
        await self.post_volatile_ignition(
            interaction, match, (roll.player_id, roll.ignite),
        )

        if not roll.pulled:
            await send_new_prompt(interaction, result.answer[0])
            await self.present(interaction, game, result)
            return

        # A landed pull reads like the turnover it is, and its lines
        # open the run back's own message rather than standing above
        # it -- one message and one board refresh, which is the
        # batching every resolved maneuver already gets.
        await self.present(interaction, game, result)


    # -- Loose ball ----------------------------------------------------


    # -- Deflect -------------------------------------------------


    # -- Steal ----------------------------------------------------------


    # -- Pressure --------------------------------------------------------


    # -- Ball-speed manipulation (Dribble Advance / Steal) --


    # -- Own goal ----------------------------------------------------


    async def own_goal_roll_file(
        self,
        match: MatchState,
        rolls: tuple[int, int],
        safe: bool,
        overdrive: int = 0,
    ) -> discord.File:
        """
        The two dice an own-goal roll produced, drawn.

        **The arithmetic that produced them is not here any more**: it
        is `own_goal_roll_step`'s narration, because it is a sentence
        about the position and the wording rules are rules (principle
        5). This is the picture alone, which is the one half a web app
        would not want.

        Drawn in a worker thread for the same reason the board is.
        """
        offense_setup = match.setup_for_side(match.ball.possession)
        return discord.File(
            await asyncio.to_thread(
                render_own_goal_dice,
                list(rolls),
                TEAM_COLORS[offense_setup.team],
                safe,
                bool(overdrive),
            ),
            filename="own_goal_dice.png",
        )

    async def post_own_goal_dice(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        result: GameResult,
    ) -> None:
        """
        The own-goal roll's dice, between its two lines.

        **Bespoke, because the image goes between the two lines.** The
        step hands back its arithmetic and its verdict in order; a
        message's attachments render below its content, so a verdict
        written above the roll would be read before it. The prompt
        becomes the dice, taking its own explanation with it once the
        roll it was asking for has happened -- the same trade a score
        attempt makes. See `SkillTestView.roll`.
        """
        roll = result.detail
        offense_player = self.engine.get_player_definition(
            match.active_player_id,
        )
        dice_file = await self.own_goal_roll_file(
            match, roll.rolls, roll.safe, roll.overdrive,
        )
        breakdown, verdict = result.answer

        await interaction.edit_original_response(
            content=breakdown,
            attachments=[dice_file],
            view=None,
        )
        # The die kept is the only one of the two that can ignite, and
        # its second die goes up between the roll and the verdict like
        # every other -- see post_volatile_ignition.
        await self.post_volatile_ignition(
            interaction, match, (offense_player.player_id, roll.ignite),
        )
        await send_new_prompt(interaction, verdict)
        await self.present(interaction, game, result)


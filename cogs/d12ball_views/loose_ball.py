"""
A ball nobody is holding, the pickup after one goes out, and the
contest that settles either -- which the long High Pass borrows. See
"Where the ball comes to rest" in docs/design/loose-balls.md.
"""

import asyncio
import discord
from typing import Optional, TYPE_CHECKING

from d12ball.components import (
    MatchState,
)
from d12ball.flow.driver import Action
from d12ball.prompts import PromptKind, SendOptions
from d12ball.game import (
    D12BallGame,
)
from gamesaves.d12ball.service import GameResult
from cogs.d12ball_helpers import (
    contest_noun,
    player_with_role,
    send_new_prompt,
    space_label,
)

from d12ball.dice_brief import render_contest_dice
from cogs.d12ball_views.base import SafeView

if TYPE_CHECKING:
    from cogs.d12ball import D12Ball


class LooseBallChoiceView(SafeView):
    """
    Who one side sends after a loose ball, plus the option of sending
    nobody. The candidates are the nearest player either side of the
    ball, from any zone (see "Sending a player" in
    docs/living-rules.md).

    One side at a time, the team that last had possession first: they
    are the ones losing the ball, and offering both at once let
    whoever clicked second answer the first's pick. Once this side
    settles, the cog rebuilds the prompt for the other.

    "Send nobody" is a real move, not a way out of the prompt -- with
    neither side contesting, the ball goes out of bounds and the side
    that last held it loses it (see resolve_loose_ball). It is
    offered even when there's only one candidate, which is why a lone
    candidate isn't auto-picked the way a forced run back is.

    **It is not offered to a side with somebody standing on the ball**
    (may_decline_loose_ball): they contest for nothing, so there is no
    walk-in for that coach to refuse to pay. Such a prompt is only ever
    a pick between two or more of them -- one is settled without asking.
    Built, not disabled: there is nothing a coach could do to enable it.
    """

    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
        side: str,
        options: SendOptions,
        match: MatchState,
    ):
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id
        self.side = side

        for player_id, distance in zip(options.player_ids, options.distances):
            player = cog.engine.get_player_definition(player_id)
            zone, space_index = match.board.meeple_position(player_id)
            space_word = "space" if distance == 1 else "spaces"

            location_note = (
                f"({space_label(zone, space_index, match.board)}, {distance} "
                f"{space_word} from the ball)"
            )
            button = discord.ui.Button(
                label=f"{player_with_role(player)} {location_note}"[:80],
                style=(
                    discord.ButtonStyle.primary
                    if side == "offense"
                    else discord.ButtonStyle.danger
                ),
                custom_id=(
                    f"d12ball:loose_ball:{game_id}:{side}:{player_id}"
                ),
            )

            async def callback(
                interaction: discord.Interaction,
                chosen_player_id: str = player_id,
            ) -> None:
                await self.choose(interaction, chosen_player_id)

            button.callback = callback
            self.add_item(button)

        if options.may_decline:
            decline = discord.ui.Button(
                label="Send nobody",
                style=discord.ButtonStyle.secondary,
                custom_id=f"d12ball:loose_ball_decline:{game_id}:{side}",
                row=4,
                # Railed during the tutorial. Waving the ball through
                # would not derail the story -- Dinky takes it either
                # way -- but the lesson beside this prompt is that both
                # sides send somebody, and a greyed button is the one
                # way to say so on the prompt itself.
                disabled=options.decline_railed,
            )
            decline.callback = self.decline
            self.add_item(decline)

    async def claim(
        self,
        interaction: discord.Interaction,
    ) -> tuple[Optional[D12BallGame], Optional[MatchState]]:
        """The game and match if this click may settle this side's
        pick, or (None, None) after replying with why it may not."""
        game, match = await self.require_match(interaction)
        if game is None:
            return None, None

        authorized = (
            self.may_act_for_possession(interaction, game, match)
            if self.side == "offense"
            else self.may_act_for_defense(interaction, game, match)
        )
        if not authorized:
            await interaction.response.send_message(
                "Only the player on that side can choose.",
                ephemeral=True,
            )
            return None, None
        return game, match

    async def choose(
        self,
        interaction: discord.Interaction,
        player_id: str,
    ) -> None:
        game, match = await self.claim(interaction)
        if game is None or match is None:
            return

        # Which side is on the clock is the prompt's, and a side that
        # has already answered is a stale click the driver refuses.
        # This view's side goes with the action so the other side's
        # prompt, still in the channel, cannot answer for this one.
        result = await self.apply(
            interaction,
            game,
            Action(
                PromptKind.LOOSE_BALL_PICK,
                "send",
                {"player_id": player_id, "skill_type": self.side},
            ),
        )
        if result is None:
            return
        await self.settled(interaction, game, result)

    async def decline(self, interaction: discord.Interaction) -> None:
        game, match = await self.claim(interaction)
        if game is None or match is None:
            return

        # **Both refusals are the model's** -- a side with somebody on
        # the ball may not decline (a stale click on a prompt a restart
        # re-attached from before the ball got there), and the
        # tutorial's rail -- and the driver asks them before anything
        # is applied.
        result = await self.apply(
            interaction,
            game,
            Action(
                PromptKind.LOOSE_BALL_PICK, "decline", {"skill_type": self.side},
            ),
        )
        if result is None:
            return
        await self.settled(interaction, game, result)

    async def settled(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        result: GameResult,
    ) -> None:
        """
        Save this side's answer, then either put the prompt up for the
        other side or resolve.

        **Which of the two it is is the step's answer** since Phase 6
        (`d12ball.flow.arrivals`): the announcement is its narration and
        the other side's pick, or the settling, is its `next`. What is
        left here is that the announcement *replaces* the question it
        answers rather than standing above the next one, which is a
        Discord economy and therefore the frontend's (principle 8).
        """
        await interaction.response.edit_message(
            content=" ".join(result.answer), view=None,
        )
        # The other side's pick, or the settling: either way the
        # presenter puts up what the service ran to.
        await self.cog.present(interaction, game, result)


class BallRecoveryView(SafeView):
    """
    Which player goes and picks up an out-of-bounds ball or one a
    time out left behind,
    offered to the side that won it once everyone is back on their
    arrangement -- the nearest either side of it, from any zone, at one
    exhaustion token per space traveled (see "Sending a player" in
    docs/living-rules.md, and D12Ball.begin_ball_recovery).
    """

    def __init__(self, cog: "D12Ball", game_id: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id

        game, match = self.load_match()
        options = self.prompt_options(game, match, PromptKind.BALL_RECOVERY)
        if options is None:
            return

        for player_id, distance in zip(options.player_ids, options.distances):
            player = cog.engine.get_player_definition(player_id)
            space_word = "space" if distance == 1 else "spaces"

            button = discord.ui.Button(
                label=(
                    f"{player_with_role(player)} ({distance} {space_word} "
                    "away)"
                )[:80],
                style=discord.ButtonStyle.primary,
                custom_id=(
                    f"d12ball:ball_recovery:{game_id}:{player_id}"
                ),
            )

            async def callback(
                interaction: discord.Interaction,
                chosen_player_id: str = player_id,
            ) -> None:
                await self.choose(interaction, chosen_player_id)

            button.callback = callback
            self.add_item(button)

    async def choose(
        self,
        interaction: discord.Interaction,
        player_id: str,
    ) -> None:
        game, match = await self.require_match(interaction)
        if game is None:
            return

        if not self.may_act_for_possession(interaction, game, match):
            await interaction.response.send_message(
                "Only the side that won the ball can choose.",
                ephemeral=True,
            )
            return

        # A ball already picked up is a stale click the driver refuses
        # by kind. The adapter names the step, so the pickup comes
        # back as a group of its own -- its own message, an event,
        # with the maneuver's tail behind it the next one -- whoever
        # sent the player, this button or the AI.
        result = await self.apply(
            interaction,
            game,
            Action(PromptKind.BALL_RECOVERY, "", {"player_id": player_id}),
        )
        if result is None:
            return
        await interaction.response.edit_message(view=None)
        await self.cog.present(interaction, game, result)


class LooseBallSkillTestView(SafeView):
    """
    The roll that settles a loose ball -- or a High Pass, which runs
    the same contest for an entirely different reason (see
    contest_noun). The custom_id stays `loose_ball_test` either way,
    since it's what already-posted messages are keyed on.
    """

    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
    ):
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id

        game = cog.games.get(game_id)
        noun = "loose ball"
        if game is not None and game.match_state is not None:
            noun = contest_noun(cog.engine.load_match_state(game))

        button = discord.ui.Button(
            label=f"Roll for the {noun}",
            style=discord.ButtonStyle.primary,
            custom_id=f"d12ball:loose_ball_test:{game_id}",
        )
        button.callback = self.roll
        self.add_item(button)

        # Overdrive, for whichever contestant is a Cyborg.
        game, match = self.load_match()
        options = self.prompt_options(
            game, match, PromptKind.LOOSE_BALL_SKILL_TEST,
        )
        if options is not None:
            self.add_overdrive_buttons(
                game, match, options,
            )

    async def roll(self, interaction: discord.Interaction) -> None:
        game, match = await self.require_match(interaction)
        if game is None:
            return

        if not self.may_act_in_game(interaction, game):
            await interaction.response.send_message(
                "Only a player in this game can roll for the "
                f"{contest_noun(match)}.",
                ephemeral=True,
            )
            return

        # **The rule is `d12ball.flow.rolls.loose_ball_test_step`**
        # since Phase 6: the roll, what injury withholds, the ball
        # speed modifier a High Pass adds, Merge, the tie's two tokens
        # and who comes away with the ball are all the model's, and the
        # whole of them used to be in this method and the two above it.
        # What is left here is the picture and where it goes; a contest
        # no longer active is the driver's to refuse, by kind.
        result = await self.apply(
            interaction,
            game,
            Action(PromptKind.LOOSE_BALL_SKILL_TEST, "roll"),
            carry_from=1,
        )
        if result is None:
            return
        dice = result.detail
        # The ignition dice are drawn on the roll they settled, and
        # said above it -- see `dice_file_with_ignitions`.
        dice_file, ignition = await self.cog.dice_file_with_ignitions(
            match,
            await asyncio.to_thread(
                render_contest_dice, dice.contestants,
            ),
            "loose_ball_dice.png",
            *dice.ignites,
        )

        following = result.prompt
        # A tie is the step handing back this same question, worded by
        # what happened -- read by kind and not by "is it a prompt",
        # because the settled path ends on a prompt too: the injury
        # test this contest owes. See `SkillTestView.roll`.
        if (
            not result.groups
            and following is not None
            and following.kind is PromptKind.LOOSE_BALL_SKILL_TEST
        ):
            # The service saved the two tokens the tie charged before
            # anything here was drawn. The ignites that produced the tie
            # are still shown -- see SkillTestView.roll's own tie.
            await interaction.response.edit_message(
                content="\n\n".join(filter(None, (ignition, following.ask))),
                attachments=[dice_file],
                view=self.cog.view_for_prompt(
                    self.game_id, result.match, following,
                ),
            )
            await self.cog.refresh_match_image(interaction, game)
            return

        # The service saved before anything here is posted: the
        # contest is settled, possession has flipped and Overdrive is
        # spent, and the dice upload below is a render and a request
        # that can fail.

        # The result follows the dice in its own message, the way every
        # other skill test announces itself -- a message's attachments
        # render below its content, so writing the outcome into this
        # one would put it above the roll that decided it. The tie
        # above is the exception, since that message carries the
        # roll-again button. See SkillTestView.roll.
        await interaction.response.edit_message(
            content=ignition,
            attachments=[dice_file],
            view=None,
        )
        await send_new_prompt(
            interaction,
            result.answer[0],
            # The edit this replaced never pinged the winner, and the
            # prompt that follows does; one ping per turn is plenty.
            allowed_mentions=discord.AllowedMentions(
                users=False, roles=False, everyone=False,
            ),
        )
        await self.cog.refresh_match_image(interaction, game)

        # Winning a live ball off the other side -- a loose ball or a
        # long High Pass -- is a steal however it was contested, so no
        # substitution window either way. The run back waits behind
        # whatever injury tests this contest owes; the service ran what
        # the roll handed back.
        await self.cog.present(interaction, game, result)

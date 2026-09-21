"""
A ball nobody is holding, the pickup after one goes out, and the
contest that settles either -- which the long High Pass borrows. See
"Where the ball comes to rest" in docs/design/loose-balls.md.
"""

import discord
from typing import Optional, TYPE_CHECKING

from d12ball import tutorial
from d12ball.components import (
    MatchState,
)
from d12ball.flow import FollowOn, StepResult
from d12ball.flow.arrivals import (
    choose_loose_ball_contestant,
    decline_loose_ball_contest,
    loose_ball_decline_refusal,
)
from d12ball.flow.rolls import loose_ball_test_step
from d12ball.prompts import PendingPrompt, PromptKind
from d12ball.game import (
    D12BallGame,
)
from gamesaves.d12ball.storage import save_games
from cogs.d12ball_helpers import (
    contest_noun,
    player_with_role,
    send_new_prompt,
    space_label,
)

from cogs.d12ball_views.base import (
    SafeView,
    render_contest_dice,
)

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
        candidates: list[str],
        match: MatchState,
    ):
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id
        self.side = side

        ball_flat = match.board.flat_index(
            match.ball.zone, match.ball.space_index,
        )

        for player_id in candidates:
            player = cog.engine.get_player_definition(player_id)
            zone, space_index = match.board.meeple_position(player_id)
            distance = abs(
                match.board.flat_index(zone, space_index) - ball_flat
            )
            space_word = "space" if distance == 1 else "spaces"
            location_note = (
                f"({space_label(zone, space_index)}, {distance} "
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

        if match.may_decline_loose_ball(
            match.ball.possession
            if side == "offense"
            else match.defending_side()
        ):
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
                disabled=cog.tutorial_railed_option(
                    cog.games.get(game_id),
                    "loose_ball_decline",
                    ("never",),
                ) == "never",
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

        if self.cog.engine.loose_ball_side_on_the_clock(match) != self.side:
            await interaction.response.send_message(
                "That side has already answered.",
                ephemeral=True,
            )
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

        await self.settled(
            interaction,
            game,
            match,
            choose_loose_ball_contestant(
                self.cog.engine,
                game,
                match,
                skill_type=self.side,
                player_id=player_id,
            ),
        )

    async def decline(self, interaction: discord.Interaction) -> None:
        game, match = await self.claim(interaction)
        if game is None or match is None:
            return

        # **Both refusals come before anything is applied**, and in
        # this order, which is the one this method has always had. The
        # button is not built for a side with somebody on the ball, so
        # reaching that branch means a stale click -- a prompt a
        # restart re-attached from before the ball got there. Same
        # reason ManeuverChallengeView.decline re-checks its own.
        refusal = loose_ball_decline_refusal(match, self.side)
        if refusal is not None:
            await interaction.response.send_message(
                refusal, ephemeral=True,
            )
            return

        if self.cog.tutorial_railed_option(
            game, "loose_ball_decline", ("never",),
        ) == "never":
            await interaction.response.send_message(
                "This step of the tutorial is about fighting for a "
                "loose ball -- send somebody after it.",
                ephemeral=True,
            )
            return

        await self.settled(
            interaction,
            game,
            match,
            decline_loose_ball_contest(
                self.cog.engine, game, match, skill_type=self.side,
            ),
        )

    async def settled(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
        result: StepResult,
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
        self.cog.persist(game, match)

        await interaction.response.edit_message(
            content=" ".join(result.narration), view=None,
        )

        following = result.next
        if isinstance(following, FollowOn):
            await self.cog.dispatch_step_result(
                interaction, game, match, StepResult(next=following),
            )
            return

        prompt_message = await send_new_prompt(
            interaction,
            following.ask,
            view=self.cog.view_for_prompt(self.game_id, match, following),
            allowed_mentions=discord.AllowedMentions(
                users=True, roles=False, everyone=False,
            ),
        )
        game.turn_message_id = prompt_message.id
        save_games(self.cog.games)


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
        if game is None:
            return
        side = match.ball.possession

        for player_id in match.contest_candidates(side):
            player = cog.engine.get_player_definition(player_id)
            distance = match.distance_to_ball(player_id)
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

        if not match.pending_ball_recovery:
            await interaction.response.send_message(
                "The ball has already been picked up.",
                ephemeral=True,
            )
            return
        if not self.may_act_for_possession(interaction, game, match):
            await interaction.response.send_message(
                "Only the side that won the ball can choose.",
                ephemeral=True,
            )
            return

        await interaction.response.edit_message(view=None)
        await self.cog.apply_ball_recovery(
            interaction, game, match, player_id,
        )


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
        if game is not None and match is not None:
            self.add_overdrive_buttons(
                game,
                match,
                [
                    match.loose_ball_offense_player,
                    match.loose_ball_defense_player,
                ],
            )

    async def roll(self, interaction: discord.Interaction) -> None:
        game, match = await self.require_match(interaction)
        if game is None:
            return

        if (
            not match.pending_loose_ball
            or match.loose_ball_offense_player is None
            or match.loose_ball_defense_player is None
        ):
            await interaction.response.send_message(
                f"This {contest_noun(match)} is no longer active.",
                ephemeral=True,
            )
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
        # What is left here is the picture and where it goes.
        dice, result = loose_ball_test_step(self.cog.engine, game, match)
        dice_file = await render_contest_dice(
            dice.contestants, filename="loose_ball_dice.png",
        )

        following = result.next
        # A tie is the step handing back this same question, worded by
        # what happened -- read by kind and not by "is it a prompt",
        # because the settled path ends on a prompt too: the injury
        # test this contest owes. See `SkillTestView.roll`.
        if (
            isinstance(following, PendingPrompt)
            and following.kind is PromptKind.LOOSE_BALL_SKILL_TEST
        ):
            # **The save is here and not in the dispatcher**, because
            # this branch never reaches one: the tie charged both
            # contestants a token and the next click reloads the match
            # out of the file.
            self.cog.persist(game, match)
            await interaction.response.edit_message(
                content=following.ask,
                attachments=[dice_file],
                view=self.cog.view_for_prompt(
                    self.game_id, match, following,
                ),
            )
            # A tie is re-rolled, and the ignites that produced it are
            # still worth showing -- see SkillTestView.roll's own tie.
            await self.cog.post_volatile_ignition(
                interaction, match, *dice.ignites,
            )
            await self.cog.refresh_match_image(interaction, game)
            return

        # **Before anything is posted**, which is the point of it: the
        # contest is settled, possession has flipped and Overdrive is
        # spent, and the dice upload below is a render and a request
        # that can fail. Without this the channel could show the result
        # while the file still said the contest was pending, and the
        # next click would re-roll it. The dispatcher writes again at
        # the end of the click; both write the same state. The fourth
        # of the paths principle 9 names -- see the own-goal roll.
        self.cog.persist(game, match)

        # The result follows the dice in its own message, the way every
        # other skill test announces itself -- a message's attachments
        # render below its content, so writing the outcome into this
        # one would put it above the roll that decided it. The tie
        # above is the exception, since that message carries the
        # roll-again button. See SkillTestView.roll.
        await interaction.response.edit_message(
            content=None,
            attachments=[dice_file],
            view=None,
        )
        # The ignition dice sit between the roll and the result, which
        # is where they belong: they are what settled it.
        await self.cog.post_volatile_ignition(
            interaction, match, *dice.ignites,
        )
        await send_new_prompt(
            interaction,
            result.narration[0],
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
        # whatever injury tests this contest owes; the step queued
        # them, and what it handed back is dispatched here. The board
        # is already written above, so the flag is not passed on.
        await self.cog.dispatch_step_result(
            interaction,
            game,
            match,
            StepResult(
                narration=result.narration[1:],
                # Passed on rather than dropped -- see
                # `SkillTestView.roll`, which rebuilds the same way.
                board_changed=result.board_changed,
                next=result.next,
            ),
        )

"""
The rolls a coach presses for: a maneuver's skill test, an injury
test, an own goal, and a score attempt. See "Every roll is a coach's"
in docs/design/maneuvers.md -- nothing in the game rolls on its own.
"""

import asyncio
import discord
from typing import TYPE_CHECKING, Optional

from d12ball.flow import StepResult
from d12ball.flow.rolls import (
    retract_shot_step,
    score_attempt_step,
    skill_test_step,
)
from d12ball.prompts import PendingPrompt, PromptKind
from d12ball.render import render_player_portrait
from cogs.d12ball_helpers import (
    send_new_prompt,
)

from cogs.d12ball_views.base import (
    SafeView,
    render_contest_dice,
)
from cogs.d12ball_views.turn import PlayerActionView

if TYPE_CHECKING:
    from cogs.d12ball import D12Ball


class SkillTestView(SafeView):
    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
    ):
        super().__init__(timeout=None)

        self.cog = cog
        self.game_id = game_id

        button = discord.ui.Button(
            label="Roll the skill test",
            style=discord.ButtonStyle.primary,
            custom_id=f"d12ball:skill_test:{game_id}",
        )
        button.callback = self.roll
        self.add_item(button)

        # Overdrive, for whichever of the two rollers is a Cyborg --
        # declared before the die and on this same message. Both sides
        # may be, and each is their own coach's to press.
        game, match = self.load_match()
        if game is not None and match is not None:
            self.add_overdrive_buttons(
                game, match, [match.active_player_id, match.challenger_id],
            )

    async def roll(self, interaction: discord.Interaction) -> None:
        game, match = await self.require_match(interaction)
        if game is None:
            return

        if match.offense_maneuver is None or match.defense_maneuver is None:
            await interaction.response.send_message(
                "This skill test is no longer active.",
                ephemeral=True,
            )
            return

        if not self.may_act_in_game(interaction, game):
            await interaction.response.send_message(
                "Only a player in this game can roll the skill test.",
                ephemeral=True,
            )
            return

        # Acknowledge immediately, before the dice image is rendered.
        # Discord invalidates the interaction token if the first
        # response doesn't arrive within 3 seconds, which turns into a
        # NotFound("Unknown interaction") on edit_message farther down
        # if rendering (or anything else on the way there) is slow --
        # deferring buys the rest of this method the usual 15 minutes.
        await interaction.response.defer()

        # **The rule is `d12ball.flow.rolls.skill_test_step`** since
        # Phase 6: the roll, the Midfielder's +3, Merge, Double Team's
        # partner, the event, Volatile's tier rider and the tie's two
        # tokens are all the model's, and the whole of them used to be
        # in this method and the one above it. What is left here is the
        # picture and where it goes.
        dice, result = skill_test_step(self.cog.engine, game, match)
        dice_file = await render_contest_dice(
            dice.contestants, filename="skill_test_dice.png",
        )

        following = result.next
        # **A tie is the step handing back this same question**, worded
        # by what happened -- the two tokens are charged and the test
        # is rolled again, which leaves the match in exactly the state
        # `pending_prompt` reads as `SKILL_TEST`. Read by kind and not
        # by "is it a prompt", because the win path ends on a prompt
        # too: the injury test the contest owes.
        if (
            isinstance(following, PendingPrompt)
            and following.kind is PromptKind.SKILL_TEST
        ):
            # A tie: the same question again, worded by what happened.
            # It keeps its text on *this* message rather than posting
            # it below the dice, because this message also carries the
            # roll-again button.
            #
            # **The save is here and not in the dispatcher**, because
            # this branch never reaches one: the tie charged both
            # contestants a token and the next click reloads the match
            # out of the file.
            self.cog.persist(game, match)
            await interaction.edit_original_response(
                content=following.ask,
                attachments=[dice_file],
                view=self.cog.view_for_prompt(
                    self.game_id, match, following,
                ),
            )
            # A tie is re-rolled, so the ignition dice go up here too:
            # they are what made these two totals equal, and the next
            # roll is a fresh one that may ignite again.
            await self.cog.post_volatile_ignition(
                interaction, match, *dice.ignites,
            )
            await self.cog.refresh_match_image(interaction, game)
            return

        # Result after the dice, not above them: a message's
        # attachments render below its content, so the winner announced
        # in this message would be read before the roll that decided
        # it. The tie above keeps its text here instead, because that
        # message also carries the roll-again button.
        await interaction.edit_original_response(
            content=None,
            attachments=[dice_file],
            view=None,
        )
        # Between the dice and the verdict, which is where the ignite
        # itself happened: the second die is what took one of those two
        # totals past the other, and the tier rider announced below is
        # read off the same two dice.
        await self.cog.post_volatile_ignition(
            interaction, match, *dice.ignites,
        )
        await send_new_prompt(interaction, result.narration[0])
        await self.cog.refresh_match_image(interaction, game)

        # The effect is on the far side of the injury tests now that
        # each of those is a click of its own, so what the step handed
        # back is dispatched rather than awaited here -- with nobody
        # exhausted it still resolves in the same breath as the roll.
        # The board is already written above, so the flag is not passed
        # on; see principle 8 in CLAUDE.md.
        await self.cog.dispatch_step_result(
            interaction,
            game,
            match,
            StepResult(
                narration=result.narration[1:], next=result.next,
            ),
        )


class InjuryTestView(SafeView):
    """
    The injury test one exhausted participant owes after a contest.
    Posted one at a time by `continue_injury_tests`, which is also what
    the click hands the turn back to.

    The player is in the custom_id as well as the queue, so a coach who
    scrolls back to the first of two prompts and clicks it again cannot
    roll the second player's test with it.
    """

    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
        player_id: str,
    ):
        super().__init__(timeout=None)

        self.cog = cog
        self.game_id = game_id
        self.player_id = player_id

        button = discord.ui.Button(
            label="Roll the injury test",
            style=discord.ButtonStyle.primary,
            custom_id=f"d12ball:injury_test:{game_id}:{player_id}",
        )
        button.callback = self.roll
        self.add_item(button)

        # Overdrive is legal on an injury check -- "any d12 the Cyborg
        # themselves rolls" -- which is the one roll where spending
        # drain to pass is also three more drain to have passed with.
        # That trade is the coach's to make.
        game, match = self.load_match()
        if game is not None and match is not None:
            self.add_overdrive_buttons(game, match, [player_id])

    async def roll(self, interaction: discord.Interaction) -> None:
        game, match = await self.require_match(interaction)
        if game is None:
            return

        if self.player_id not in match.pending_injury_tests:
            await interaction.response.send_message(
                "This injury test is no longer active.",
                ephemeral=True,
            )
            return

        if not self.may_act_in_game(interaction, game):
            await interaction.response.send_message(
                "Only a player in this game can roll the injury test.",
                ephemeral=True,
            )
            return

        # Deferred before the die is rendered, for the reason spelled
        # out in SkillTestView.roll.
        await interaction.response.defer()

        await self.cog.run_injury_test(
            interaction,
            game,
            match,
            self.cog.engine.get_player_definition(self.player_id),
        )


class OwnGoalRollView(SafeView):
    """
    The roll that decides an own goal Pressure has pushed a side into.
    One roll, by one player, but any coach in the game may press it --
    the same as the skill test and the score attempt, and what keeps a
    solo game moving when the risk is the AI's.
    """

    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
    ):
        super().__init__(timeout=None)

        self.cog = cog
        self.game_id = game_id

        button = discord.ui.Button(
            label="Roll for the own goal",
            style=discord.ButtonStyle.danger,
            custom_id=f"d12ball:own_goal:{game_id}",
        )
        button.callback = self.roll
        self.add_item(button)

        # Overdrive, for the handler who has to survive the roll.
        game, match = self.load_match()
        if game is not None and match is not None:
            self.add_overdrive_buttons(
                game, match, [match.active_player_id],
            )

    async def roll(self, interaction: discord.Interaction) -> None:
        game, match = await self.require_match(interaction)
        if game is None:
            return

        if not match.pending_own_goal or match.active_player_id is None:
            await interaction.response.send_message(
                "This own goal roll is no longer active.",
                ephemeral=True,
            )
            return

        if not self.may_act_in_game(interaction, game):
            await interaction.response.send_message(
                "Only a player in this game can roll for the own goal.",
                ephemeral=True,
            )
            return

        # Deferred before the dice are rendered, for the reason spelled
        # out in SkillTestView.roll.
        await interaction.response.defer()

        await self.cog.run_own_goal_roll(interaction, game, match)


class ScoreAttemptView(SafeView):
    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
        composition_message_id: Optional[int] = None,
    ):
        super().__init__(timeout=None)

        self.cog = cog
        self.game_id = game_id
        # Only known on the live view `begin_score_attempt` just built --
        # a restart rebuilds this view from the cog and the game id alone
        # (see PLAIN_PROMPT_VIEWS), so a resumed "Back" leaves that image
        # as the harmless remnant it always was.
        self.composition_message_id = composition_message_id

        button = discord.ui.Button(
            label="Roll the score attempt",
            style=discord.ButtonStyle.danger,
            custom_id=f"d12ball:score_attempt:{game_id}",
        )
        button.callback = self.roll
        self.add_item(button)

        # Overdrive, for the shooter alone. A score attempt's second
        # die is the defensive wall's and belongs to no card, so there
        # is nobody on that side to declare it.
        game, match = self.load_match()
        if game is not None and match is not None:
            self.add_overdrive_buttons(
                game, match, [match.active_player_id],
            )

        # A shot not yet rolled always has somewhere to walk back to --
        # see `MatchState.may_cancel_pending_shot` -- and only the side
        # that chose it may reconsider. No `possession_user_id` means
        # Dinky is the one shooting, which is not a choice a human
        # standing in for its rolls gets to undo either (see "Every
        # roll is a coach's" in docs/design/maneuvers.md).
        if (
            game is not None
            and match is not None
            and match.may_cancel_pending_shot()
            and cog.engine.possession_user_id(game, match) is not None
        ):
            back = discord.ui.Button(
                label="Back",
                style=discord.ButtonStyle.secondary,
                custom_id=f"d12ball:score_attempt_back:{game_id}",
                # Built disabled, never absent, exactly like
                # SetUpAttemptChoiceView's own decline button -- a
                # tutorial beat that rails a set-up shot to "attempt"
                # is railing this same choice (Back leads straight back
                # to that view's decline), and the scripted goal at the
                # end of beat 5 depends on nobody reaching it.
                disabled=(
                    match.pending_shot_is_set_up
                    and cog.tutorial_railed_option(
                        game, "setup_attempt", ("attempt", "decline"),
                    ) == "attempt"
                ),
            )
            back.callback = self.back
            self.add_item(back)

    async def roll(self, interaction: discord.Interaction) -> None:
        game, match = await self.require_match(interaction)
        if game is None:
            return

        if match.pending_action != "shoot" or match.active_player_id is None:
            await interaction.response.send_message(
                "This score attempt is no longer active.",
                ephemeral=True,
            )
            return

        if not self.may_act_in_game(interaction, game):
            await interaction.response.send_message(
                "Only a player in this game can roll the score attempt.",
                ephemeral=True,
            )
            return

        # **The rule is `d12ball.flow.rolls.score_attempt_step`** since
        # Phase 6: the roll, the wall's price, Merge, the Striker's +3,
        # the event, the goal or the miss and the restart behind it are
        # all the model's. What is left here is the picture, the
        # portrait, and where each goes.
        dice, result = score_attempt_step(self.cog.engine, game, match)
        # **Before anything is posted**, which is the point of it: the
        # goal is credited and the restart written, and the portrait
        # upload below is a render and a request that can fail. The
        # dispatcher writes again at the end of the click; both write
        # the same state, and this is the own-goal roll's deliberate
        # second write for the own-goal roll's reason.
        self.cog.persist(game, match)
        dice_file = await render_contest_dice(
            dice.contestants, filename="score_attempt_dice.png",
        )
        # The dice image carries the maths that produced it, and the
        # verdict follows in its own message. A message's attachments
        # always render *below* its content, so a verdict written into
        # this one would be read before the roll it is announcing.
        await interaction.response.edit_message(
            content=None,
            attachments=[dice_file],
            view=None,
        )
        # The shooter's own die, if it ignited -- between the dice and
        # the verdict, so a goal that a surge bought is read in the
        # order it happened.
        await self.cog.post_volatile_ignition(
            interaction, match, *dice.ignites,
        )
        await send_new_prompt(interaction, result.narration[0])
        if dice.scored:
            # The scorer, posted under the announcement -- its own
            # message rather than an attachment on it, which would put
            # the portrait above the "GOAL!" it belongs to. Who they
            # are comes back with the dice: by now the step has cleared
            # `active_player_id`, which was the only thing naming them.
            scorer = self.cog.engine.get_player_definition(
                dice.shooter_id,
            )
            portrait = await asyncio.to_thread(
                render_player_portrait, scorer.name,
            )
            if portrait is not None:
                await send_new_prompt(
                    interaction,
                    file=discord.File(
                        portrait,
                        filename=f"{scorer.player_id}_goal.png",
                    ),
                )
        # No board refresh here: every path out of `begin_run_back`
        # puts one up within the same click, over a position this one
        # would draw a moment before. A new play goes to
        # `announce_new_play_reset`, which restores both arrangements
        # and posts the settled board through `post_new_play_board`;
        # last possession goes to `end_period`, which refreshes in both
        # of its own branches. So this drew a board nobody reads -- the
        # restarted ball without the reset behind it -- and, worse, it
        # took the game's write window. The step reports the board
        # moved and `follow_on_draws_the_board` is what suppresses the
        # write, which is the same answer for every caller rather than
        # this one's comment. See "Discord's rate limits" in
        # docs/design/rate-limits.md.
        await self.cog.dispatch_step_result(
            interaction, game, match, StepResult(next=result.next),
        )

    async def back(self, interaction: discord.Interaction) -> None:
        """
        Walk an unrolled "shoot" choice back to wherever it was chosen.
        The composition image already posted is deleted with it, when
        this view is the one that just posted it -- see
        `composition_message_id`. A view rebuilt on restart has no
        message id to delete, so a resumed "Back" leaves that image as
        a harmless remnant, the same tradeoff a picked maneuver's hand
        image makes.

        An ordinary turn's shot and a set-up's are two different
        choices with two different ways back, so they split here:
        `retract_pending_shot` undoes the former (the turn prompt's own
        "Shoot to score" button) and `back_from_set_up_shot` the latter
        (`SetUpAttemptChoiceView`'s "attempt" button). Both are real
        choices a coach made a moment ago and neither has happened to
        anything else in between, which is what makes either safe to
        undo -- see `MatchState.may_cancel_pending_shot`.
        """
        game, match = await self.require_match(interaction)
        if game is None:
            return

        if not match.may_cancel_pending_shot():
            await interaction.response.send_message(
                "This score attempt is no longer active.",
                ephemeral=True,
            )
            return

        if not self.may_act_for_possession(interaction, game, match):
            await interaction.response.send_message(
                "Only the player who chose to shoot can change their "
                "mind.",
                ephemeral=True,
            )
            return

        if (
            self.composition_message_id is not None
            and interaction.channel is not None
        ):
            try:
                await interaction.channel.get_partial_message(
                    self.composition_message_id,
                ).delete()
            except (discord.NotFound, discord.HTTPException):
                pass

        # **The rule is `d12ball.flow.rolls.retract_shot_step`** since
        # Phase 6: which of the two shots is being undone, what undoing
        # each one costs, and the offer a set-up's shot puts back up
        # are all the model's. What is left here is that the answer
        # *replaces* the message it was asked on.
        result = retract_shot_step(self.cog.engine, game, match)
        self.cog.persist(game, match)

        prompt = result.next
        if prompt is not None:
            # A set-up's shot, walked back to the offer that earned it
            # -- the same prompt a restart here now restores, through
            # the same table.
            await interaction.response.edit_message(
                content=prompt.ask,
                view=self.cog.view_for_prompt(self.game_id, match, prompt),
            )
            return

        # An ordinary turn's shot: the position is the turn's own
        # again, and what goes over it is the turn prompt the engine
        # already builds.
        await interaction.response.edit_message(
            content=self.cog.engine.build_turn_prompt(game, match),
            view=PlayerActionView(self.cog, self.game_id),
        )

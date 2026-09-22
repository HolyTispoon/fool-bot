"""
A turn as the coach drives it -- picking the handler, picking the
action, ceding, answering a challenge, and the public maneuver prompt
both sides pick off. See "The maneuver prompt" in docs/design/maneuver-prompt.md.
"""

import discord
from math import ceil
from typing import Optional, TYPE_CHECKING

from d12ball.flow import FollowOn, FollowOnStep
from d12ball.flow.driver import Action
from d12ball.flow.turn import turn_action_refusal
from d12ball.prompts import PromptKind
from d12ball.components import MatchState
from d12ball.game import (
    D12BallGame,
)
from gamesaves.d12ball.service import GameResult
from cogs.d12ball_helpers import (
    add_full_image_button_to_response,
    player_with_role,
    refresh_player_names,
    send_new_prompt,
)

from cogs.d12ball_views.base import SafeView

if TYPE_CHECKING:
    from cogs.d12ball import D12Ball


class BallHandlerSelectionView(SafeView):
    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
    ):
        super().__init__(timeout=None)

        self.cog = cog
        self.game_id = game_id
        game, match = self.load_match()
        options = self.prompt_options(
            game, match, PromptKind.BALL_HANDLER_SELECTION,
        )
        if options is None:
            return

        # The prompt's candidates -- `turn_handler_candidates`, not
        # `eligible_ball_handlers`: a ball carrier narrows this to
        # one button, which is the rule showing up as a menu with no
        # choice in it. send_turn_prompt normally skips the view
        # entirely in that case; this is the restore path. A
        # Telekinetic standing on the ball gets a button of their own
        # -- see "Mind Pull (Telekinetic)" in the living rules.
        for player_id in options.player_ids:
            player = self.cog.engine.get_player_definition(player_id)
            button = discord.ui.Button(
                label=player_with_role(player)[:80],
                style=discord.ButtonStyle.primary,
                custom_id=(
                    f"d12ball:ball_handler:{game_id}:{player_id}"
                ),
            )

            async def callback(
                interaction: discord.Interaction,
                selected_player_id: str = player_id,
            ) -> None:
                await self.select_handler(
                    interaction,
                    selected_player_id,
                )

            button.callback = callback
            self.add_item(button)

    async def select_handler(
        self,
        interaction: discord.Interaction,
        player_id: str,
    ) -> None:
        game, match = await self.require_match(interaction)
        if game is None:
            return

        if not self.may_act_for_possession(interaction, game, match):
            await interaction.response.send_message(
                "Only the player whose team has possession can "
                "choose the ball handler.",
                ephemeral=True,
            )
            return

        # A handler already picked is a stale click on this prompt,
        # and the driver refuses it by kind -- the position reads as
        # the turn's own question by then.
        result = await self.apply(
            interaction,
            game,
            Action(
                PromptKind.BALL_HANDLER_SELECTION, "", {"player_id": player_id},
            ),
        )
        if result is None:
            return
        prompt = result.prompt
        # An **edit**, not a new message: the kickoff question becomes
        # the turn question in place, which is a request the gate
        # counts. What is asked and how it is worded is the step's.
        await interaction.response.edit_message(
            content=prompt.ask,
            view=self.cog.view_for_prompt(self.game_id, result.match, prompt),
        )


class PlayerActionView(SafeView):
    """
    The turn's choice: shoot, maneuver, or call a time out.
    **Shooting is only offered from within shooting range and a time
    out only from outside it**, so a coach never sees both -- see
    `MatchState.can_attempt_score`, `MatchState.may_call_time_out`,
    and `D12Ball.build_turn_prompt`, which says why whichever one is
    missing is missing. Rebuilt from match state on every restart like
    every other persistent view here, so the ball's position always
    decides afresh.
    """

    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
    ):
        super().__init__(timeout=None)

        self.cog = cog
        self.game_id = game_id

        game, match = self.load_match()
        options = self.prompt_options(game, match, PromptKind.PLAYER_ACTION)
        # The prompt's `TurnOptions`: which of the three the position
        # offers, in its order, and which the tutorial leaves live. A
        # view built with no position to read gets the turn's two.
        offered = options.actions if options is not None else (
            "maneuver", "shoot",
        )
        live = options.live if options is not None else offered

        # Grey, and last, for the time out: it is what a coach does
        # when there is nothing worth playing, and it should never sit
        # beside Maneuver as an equal.
        buttons = {
            "maneuver": ("Maneuver", discord.ButtonStyle.primary),
            "shoot": ("Shoot to score", discord.ButtonStyle.danger),
            "time_out": ("Time out", discord.ButtonStyle.secondary),
        }

        # A tutorial beat names the one action it wants pressed, and
        # the rest are built **disabled** rather than left out: a coach
        # should see that shooting and the time out exist and read in
        # the lesson why neither is theirs yet. See d12ball/tutorial.py.
        for action in offered:
            label, style = buttons[action]
            button = discord.ui.Button(
                label=label,
                style=style,
                custom_id=f"d12ball:action:{game_id}:{action}",
                disabled=action not in live,
            )

            async def callback(
                interaction: discord.Interaction,
                selected_action: str = action,
            ) -> None:
                await self.choose_action(interaction, selected_action)

            button.callback = callback
            self.add_item(button)

    async def choose_action(
        self,
        interaction: discord.Interaction,
        action: str,
    ) -> None:
        game, match = await self.require_match(interaction)
        if game is None:
            return

        if not self.may_act_for_possession(interaction, game, match):
            await interaction.response.send_message(
                "Only the player whose team has possession can "
                "choose this action.",
                ephemeral=True,
            )
            return

        if action == "time_out":
            # Confirmed rather than taken -- see `TimeOutConfirmView`.
            # Nothing is answered until the confirmation, so the
            # position is read here only to word the confirmation.
            await self.begin_time_out_action(interaction, game, match)
            return

        # **The refusals are `turn_action_refusal`'s and the check
        # against the position is the driver's**: every one of them is
        # a stale click -- the buttons are only built for the actions
        # the position allows -- and what each says is a fact about
        # the position (principle 5 in CLAUDE.md). Who may press is a
        # fact about a person and stays above.
        result = await self.apply(
            interaction,
            game,
            Action(PromptKind.PLAYER_ACTION, action),
            # A challenger nobody was asked for walks in over the
            # challenge image, and the answer's own line opens it; on
            # every other route the line is this view's to place.
            carry_from=lambda answered: (
                0
                if isinstance(answered.result.next, FollowOn)
                and answered.result.next.step
                is FollowOnStep.AUTO_RESOLVE_CHALLENGER
                else None
            ),
        )
        if result is None:
            return
        refresh_player_names(game, interaction.guild)

        if action == "shoot":
            # The answer replaces the prompt; the composition and the
            # roll prompt follow, off the kind (`render_prompt`).
            await interaction.response.edit_message(
                content=result.answer[0], view=None,
            )
            await self.cog.present(interaction, game, result)
            return

        await self.begin_maneuver_action(interaction, game, result)

    async def begin_time_out_action(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        Put what a time out costs in front of the coach before anything
        happens. It spends a minute and the side's one time out for the
        half, and it sits one button along from Maneuver, so it is
        confirmed rather than taken -- see TimeOutConfirmView.
        """
        # A stale prompt: the button was built for a position that has
        # moved on. The confirmation would be refused the same way
        # through the driver, but there is no reason to open it -- and
        # the sentence is the model's (`turn_action_refusal`, the
        # predicate the driver applies), because it says what the
        # position is.
        refusal = turn_action_refusal(self.cog.engine, game, match, "time_out")
        if refusal is not None:
            await interaction.response.send_message(refusal, ephemeral=True)
            return

        await interaction.response.edit_message(
            content=self.cog.engine.time_out_confirmation(game, match),
            view=TimeOutConfirmView(
                self.cog, self.game_id, interaction.message.content,
            ),
        )

    async def begin_maneuver_action(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        result: GameResult,
    ) -> None:
        """
        Start a maneuver, which reaches the offense's pick by one of
        three routes: nobody to challenge at all, a challenger settled
        without asking, or the defending coach's own choice.

        **The rule is `d12ball.flow.turn.begin_maneuver_step`** since
        Phase 6, answered above. What is left here is what each route
        *shows* -- and two of the three drop the turn prompt rather
        than editing it down to who chose what, because the challenge
        image and the unchallenged notice each say a good deal more.
        See D12Ball.drop_turn_prompt.
        """
        await interaction.response.defer()
        await self.cog.drop_turn_prompt(interaction, game)

        if (
            not result.groups
            and result.prompt is not None
            and result.prompt.kind is PromptKind.MANEUVER_CHALLENGE
        ):
            # The defending coach is genuinely being asked: the prompt
            # goes up on a fresh message, through `render_prompt`.
            await self.cog.present(interaction, game, result)
            return

        if (
            result.groups
            and result.groups[0].step is FollowOnStep.AUTO_RESOLVE_CHALLENGER
        ):
            # A challenger nobody was asked for: the challenge image is
            # what goes up, and the answer's own line was carried into
            # it (see `choose_action`).
            await self.cog.present(interaction, game, result)
            return

        # Nobody left to challenge with at all, which reads as its own
        # message: the pick that follows is a prompt of its own.
        lines = " ".join(result.answer)
        if lines:
            await send_new_prompt(interaction, lines)
        await self.cog.present(interaction, game, result)


class TimeOutConfirmView(SafeView):
    """
    "Are you sure?" for the one turn action that buys something
    instead of playing the ball -- see `d12ball.flow.windows.begin_time_out`. Every
    other choice a coach makes can be argued with afterwards; this one
    spends a minute and the side's one time out for the half, and it
    sits one button along from Maneuver.

    **It replaces the turn prompt in place rather than posting a
    second message**, so Back is genuinely a way out (it puts the
    prompt back, word for word, which is why `prompt` is carried
    rather than rebuilt -- `build_turn_prompt` can no longer tell
    whether the handler was carrying the ball) and the confirmed click
    can drop the prompt the ordinary way. It is an
    `interaction.response.edit_message` at both ends, so unlike a board
    write it costs nothing out of the channel's edit bucket.

    A restart between opening this and answering it leaves the buttons
    dead -- a restart re-arms the message with `PlayerActionView`, this
    view being nothing the match records. The coach is one `/d12ball
    resume` from the turn prompt they started at, and nothing has
    happened to the match in the meantime.
    """

    def __init__(self, cog: "D12Ball", game_id: str, prompt: str):
        super().__init__(timeout=None)

        self.cog = cog
        self.game_id = game_id
        self.prompt = prompt

        confirm = discord.ui.Button(
            label="Take the time out",
            style=discord.ButtonStyle.danger,
            custom_id=f"d12ball:time_out_confirm:{game_id}",
        )
        confirm.callback = self.confirm
        self.add_item(confirm)

        back = discord.ui.Button(
            label="Back",
            style=discord.ButtonStyle.secondary,
            custom_id=f"d12ball:time_out_cancel:{game_id}",
        )
        back.callback = self.back
        self.add_item(back)

    async def claim(
        self,
        interaction: discord.Interaction,
    ) -> tuple[Optional[D12BallGame], Optional[MatchState]]:
        """The game and match, if this click may act on them."""
        game, match = await self.require_match(interaction)
        if game is None:
            return None, None

        if not self.may_act_for_possession(interaction, game, match):
            await interaction.response.send_message(
                "Only the team with the ball can call a time out.",
                ephemeral=True,
            )
            return None, None
        return game, match

    async def back(self, interaction: discord.Interaction) -> None:
        game, match = await self.claim(interaction)
        if game is None or match is None:
            return

        await interaction.response.edit_message(
            content=self.prompt,
            view=PlayerActionView(self.cog, self.game_id),
        )

    async def confirm(self, interaction: discord.Interaction) -> None:
        game, match = await self.claim(interaction)
        if game is None or match is None:
            return

        # **The time out is the `time_out` answer to the turn prompt**
        # (`driver._answer_player_action`), asked again here rather
        # than trusted from the click that opened this: the prompt
        # underneath is a live message and the match can have moved on
        # under it, and `turn_action_refusal` is what says so.
        result = await self.apply(
            interaction, game, Action(PromptKind.PLAYER_ACTION, "time_out"),
        )
        if result is None:
            return

        # The prompt becomes the announcement -- the answer's own line,
        # which the window's menu used to carry as its heading -- and
        # the window follows it.
        await interaction.response.edit_message(
            content=result.answer[0], view=None,
        )
        await self.cog.present(interaction, game, result)


class ManeuverChallengeView(SafeView):
    """
    Who the defense puts up against the maneuver -- or nobody. The
    candidates are `MatchState.challenge_candidates`: the nearest
    defender either side of the ball, from any zone (see "Sending a
    player" in docs/living-rules.md), or the defenders already standing
    on the ball wherever there are any. Walking in costs 1 token per
    space, and the author's 2026-08-12 ruling is that a defense may
    refuse to pay it and let the maneuver through; a defender on the
    ball pays nothing, so that challenge is not theirs to refuse and no
    Send nobody button is built.

    **One defender on the ball never reaches this prompt** -- there is
    nothing to choose. Two or more do, since which of them challenges
    is the coach's call (the author, 2026-08-17) and a challenge is
    settled on defensive skill.
    """

    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
    ):
        super().__init__(timeout=None)

        self.cog = cog
        self.game_id = game_id

        game, match = self.load_match()
        options = self.prompt_options(
            game, match, PromptKind.MANEUVER_CHALLENGE,
        )
        if options is None:
            return

        for player_id, distance in zip(options.player_ids, options.distances):
            player = self.cog.engine.get_player_definition(player_id)
            button = discord.ui.Button(
                label=f"{player_with_role(player)} ({distance})"[:80],

                style=discord.ButtonStyle.primary,
                custom_id=(
                    f"d12ball:challenger:{game_id}:{player_id}"
                ),
            )

            async def callback(
                interaction: discord.Interaction,
                selected_player_id: str = player_id,
            ) -> None:
                await self.select_challenger(
                    interaction,
                    selected_player_id,
                )

            button.callback = callback
            self.add_item(button)

        # The prompt says whether the challenge is the defense's to
        # refuse: this view is normally only built where the choice is
        # real, but a restart can re-attach it to a prompt saved with a
        # defender standing on the ball, and `may_decline` is false
        # there. The driver refuses off the same reading.
        if options.may_decline:
            decline = discord.ui.Button(
                label="Send nobody",
                style=discord.ButtonStyle.secondary,
                custom_id=f"d12ball:challenge_decline:{game_id}",
                row=4,
                # Railed during the tutorial's beat 3: the coach has
                # nobody standing near the ball there, and letting
                # Dinky's maneuver through unchallenged would leave
                # nothing for the lesson's Pressure to defend against.
                disabled=options.decline_railed,
            )
            decline.callback = self.decline
            self.add_item(decline)

    async def claim(
        self,
        interaction: discord.Interaction,
    ) -> tuple[Optional[D12BallGame], Optional[MatchState]]:
        """
        The game and match if this click may still settle the
        challenge, or (None, None) after replying with why it may not.
        Both answers come through here, because either one closes the
        question: a challenger walks in, or the defense sends nobody
        and the maneuver goes unchallenged.
        """
        game, match = await self.require_match(interaction)
        if game is None:
            return None, None

        if not self.may_act_for_defense(interaction, game, match):
            await interaction.response.send_message(
                "Only the player whose team is defending can make "
                "this choice.",
                ephemeral=True,
            )
            return None, None

        return game, match

    async def select_challenger(
        self,
        interaction: discord.Interaction,
        player_id: str,
    ) -> None:
        game, match = await self.claim(interaction)
        if game is None or match is None:
            return

        # **The rule is `d12ball.flow.turn.auto_resolve_challenger`**
        # since Phase 6, and it always was: a defender already sharing
        # the ball's space comes through that step, and this button
        # and the AI's answer are the other ways to make the same
        # pick. The adapter names the step, so the walk-in comes back
        # as a group of its own and `present` draws the challenge
        # image over it. A challenger already chosen, or a maneuver
        # already gone unchallenged, is a stale click the driver
        # refuses by kind.
        result = await self.apply(
            interaction,
            game,
            Action(
                PromptKind.MANEUVER_CHALLENGE, "send", {"player_id": player_id},
            ),
        )
        if result is None:
            return

        # The prompt goes rather than being edited down to "has chosen
        # their challenger" -- the challenge image below says who was
        # picked, and a good deal more. See D12Ball.drop_turn_prompt.
        await interaction.response.defer()
        await self.cog.drop_turn_prompt(interaction, game)
        await self.cog.present(interaction, game, result)

    async def decline(self, interaction: discord.Interaction) -> None:
        """
        Send nobody: the maneuver goes unchallenged, exactly as it does
        when the defense has nobody to send at all. Nothing moves
        and nobody is charged, so there is no board to refresh -- the
        one thing a challenge would have cost is the walk-in this
        refuses to pay.
        """
        game, match = await self.claim(interaction)
        if game is None or match is None:
            return

        # **The rule is `d12ball.flow.turn.decline_challenge_step`**
        # since Phase 6: sending nobody and saying so are one answer,
        # and the second half of it was already the model's.
        result = await self.apply(
            interaction, game, Action(PromptKind.MANEUVER_CHALLENGE, "decline"),
        )
        if result is None:
            return

        await interaction.response.defer()
        await self.cog.drop_turn_prompt(interaction, game)
        # Sending nobody is its own message; the pick that follows is
        # a prompt of its own.
        lines = " ".join(result.answer)
        if lines:
            await send_new_prompt(interaction, lines)
        await self.cog.present(interaction, game, result)


# Discord's own component limits: five rows to a message, five buttons
# to a row.
MAX_BUTTON_ROWS = 5
MAX_BUTTONS_PER_ROW = 5


def even_button_rows(
    buttons: list[discord.ui.Button],
) -> list[list[discord.ui.Button]]:
    """
    Split one side's maneuver buttons into as few rows as Discord
    allows, and then **evenly** across them.

    Six gambits do not fit a row, and chunking at the limit
    would lay them out five and one -- which reads as a row plus an
    afterthought rather than as one hand. Two rows of three is the same
    number of rows and says what it is.
    """
    if not buttons:
        return []
    rows = ceil(len(buttons) / MAX_BUTTONS_PER_ROW)
    per_row = ceil(len(buttons) / rows)
    return [
        buttons[start:start + per_row]
        for start in range(0, len(buttons), per_row)
    ]


class ManeuverActionPromptView(SafeView):
    """
    The maneuver pick, on **one public message carrying both sides'
    buttons**.

    It used to be two steps: a public prompt with a single "Choose Your
    Maneuver" button that opened an ephemeral menu of the clicking
    coach's own cards. The ephemeral menu was never about privacy of
    the *cards* -- the twelve of them and the defeat cycle are public
    information either coach may ask for at any time. What has to stay
    hidden is the **pick**, and that is hidden by the reply to the
    click being ephemeral, not by the menu being private. Discord tells
    nobody else who pressed what, so a coach reading this message
    cannot tell whether the other side has clicked, and the message is
    never edited to say (see `D12Ball.close_maneuver_prompt`).

    So the extra click bought nothing but the round trip. It existed
    because an ephemeral message must answer *that coach's own*
    interaction, and only one of the two coaches is ever holding a live
    interaction when a maneuver begins -- whoever picked Maneuver, or
    picked the challenger. Putting the buttons on the message removes
    the need for either coach to hold one.

    Two things follow, and both are improvements:

    - **A restart re-attaches this like any other view.** It is on a
      real message recorded in `turn_message_id`, so `on_ready` handles
      it through `pending_turn_view` and the message-agnostic
      `add_view` registration the ephemeral menu needed is gone. (The
      shootout's two menus are still ephemeral and still need it -- see
      `D12Ball.restore_shootout_menus`.)
    - **The uploads halve.** One public hand image and one public field
      strip, against a hand and a field to each of two coaches.

    **Every side on the prompt keeps its buttons for the whole
    maneuver**, picked or not. The message is deliberately never
    edited, so the buttons a restored view dispatches have to match the
    buttons sitting on the message; taking a picked side's row away
    would leave those clicks answered by nothing. `pick` refuses the
    second click instead. Which sides are on it at all is
    `RulesEngine.maneuver_pick_sides`.
    """

    def __init__(
        self,
        cog: "D12Ball",
        game_id: str,
        timeout: Optional[float] = None,
    ):
        super().__init__(timeout=timeout)

        self.cog = cog
        self.game_id = game_id

        game, match = self.load_match()
        options = self.prompt_options(game, match, PromptKind.MANEUVER_ACTION)
        # The prompt's `ManeuverOptions`: a hand per side on it, picked
        # or not. A view built with no position to read builds nothing,
        # like every other view over a prompt.
        hands = options.hands if options is not None else ()
        self.sides = tuple(hand.side for hand in hands)

        rows: list[list[discord.ui.Button]] = []


        for hand in hands:
            side = hand.side
            # **The hand is the engine's answer, not the whole
            # catalog**, and it is asked **per side**: a basic game is
            # three cards, an unchallenged maneuver is basic whatever
            # the mode, and a gambit is held only by a coach whose team
            # is behind -- so one row here can be six buttons and the
            # other three. See `RulesEngine.maneuver_tiers`, which the
            # prompt's options are built from -- what keeps these
            # buttons, the hand image above them and the driver's own
            # check from disagreeing about what a coach may play.
            #
            # A tutorial beat rails the coach onto one card
            # (`hand.railed`), and the others are built **disabled**
            # rather than left out -- the whole point of the lesson is
            # reading what the hand holds. Dinky's side is never on
            # this prompt at all, so this only ever narrows a human's.
            buttons = []
            for key in hand.maneuver_keys:
                maneuver = cog.maneuver_catalog.definition(key)
                button = discord.ui.Button(
                    label=maneuver.name,
                    # The cards' own two colours, so a coach picks their
                    # row out of a prompt holding both without reading
                    # the labels: offense red, defense green, exactly as
                    # `d12ball/cards.py` and the reference hexagon draw
                    # them.
                    style=(
                        discord.ButtonStyle.danger
                        if side == "offense"
                        else discord.ButtonStyle.success
                    ),
                    custom_id=(
                        f"d12ball:maneuver_pick:{game_id}:{side}:"
                        f"{maneuver.key}"
                    ),
                    disabled=(
                        hand.railed is not None and key != hand.railed
                    ),
                )

                async def callback(
                    interaction: discord.Interaction,
                    chosen_side: str = side,
                    chosen_key: str = key,
                ) -> None:
                    await self.pick(interaction, chosen_side, chosen_key)

                button.callback = callback
                buttons.append(button)

            rows.extend(even_button_rows(buttons))

        # Its own row where there is one, so a grey button does not read
        # as the tail of a coloured row. Its custom_id carries the game
        # like the picks do but no side: the hexagon is the same picture
        # for both coaches.
        reference = discord.ui.Button(
            label="Maneuver Reference",
            style=discord.ButtonStyle.secondary,
            custom_id=f"d12ball:maneuver_reference:{game_id}",
        )
        reference.callback = self.show_reference
        if len(rows) < MAX_BUTTON_ROWS:
            rows.append([reference])
        else:
            # Only reachable if a side ever grows past what four rows
            # hold. Falling back to the first row with space keeps the
            # reference reachable rather than raising on view build.
            next(row for row in rows if len(row) < MAX_BUTTONS_PER_ROW).append(
                reference
            )

        for index, row in enumerate(rows):
            for button in row:
                button.row = index
                self.add_item(button)

        # The full-image link is added after the message is posted (the
        # URL does not exist until then -- see `add_full_image_button`),
        # and discord.py drops a rowless button into the *first* row with
        # space. A side holding gambits has a hand of two rows of
        # three, so that first gap is between its basic cards and
        # its gambits. Point it at the reference's row instead, so it lands
        # after every maneuver button. None where the fallback above
        # packed the reference onto a maneuver row -- that row may be
        # full, and the default placement is fine there anyway.
        self.full_image_row = (
            reference.row if reference in rows[-1] else None
        )

    async def show_reference(self, interaction: discord.Interaction) -> None:
        """
        The defeat cycle, ephemeral to the coach who asked.

        Ephemeral for the pick's own reason rather than its own:
        answering in the channel would tell the other side that this
        coach is still choosing. The image is public information either
        coach may ask for at any time, so nothing is hidden by it --
        only the timing.
        """
        await interaction.response.send_message(
            file=self.cog.build_maneuver_reference_file(
                self.cog.reference_tier(self.cog.games.get(self.game_id))
            ),
            ephemeral=True,
        )
        # The hexagon's labels are small print at the size Discord shows
        # an image inline, the same reason the hand carries a link. No
        # view goes with it, so there are no buttons for the edit to
        # drop. Webhook route -- see "Discord's rate limits".
        await add_full_image_button_to_response(interaction)

    def pick_refusal(
        self,
        game: D12BallGame,
        match: MatchState,
        side: str,
        interaction: discord.Interaction,
    ) -> Optional[str]:
        """
        Why this click cannot be taken as a pick, or None.

        **Authorization is answered first**, and that ordering is a
        rule rather than a habit: the other coach's row is sitting on
        the same message, so replying "that side has already chosen"
        to a click on it would say whether they had. It is the half
        that stays here -- whose Discord account may press a button is
        a fact about a person (see docs/design/permissions.md) -- and
        every rule about the pick is
        `d12ball.flow.turn.maneuver_pick_refusal`'s.


        It takes the interaction rather than the clicker's id because a
        game helper may pick for either side and the permission is on
        the member -- see "Who may act on a game" in docs/design/permissions.md.
        """
        authorized = (
            self.may_act_for_possession(interaction, game, match)
            if side == "offense"
            else self.may_act_for_defense(interaction, game, match)
        )
        if not authorized:
            return "Only the player on that side can choose this maneuver."
        return None

    async def pick(
        self,
        interaction: discord.Interaction,
        side: str,
        maneuver_key: str,
    ) -> None:
        """
        One coach's pick, answered **ephemerally** -- which is the whole
        of what keeps it secret now that the buttons are public. The
        prompt itself is untouched, so the other coach sees no change of
        any kind.
        """
        game, match = await self.require_match(interaction)
        if game is None:
            return

        refusal = self.pick_refusal(game, match, side, interaction)

        if refusal is not None:
            await interaction.response.send_message(refusal, ephemeral=True)
            return

        # **The rule is `d12ball.flow.turn.maneuver_pick_step`** since
        # Phase 6: writing the pick down, whether "someone has picked"
        # is worth saying at all, and whether both sides have answered
        # -- and `maneuver_pick_refusal`'s three reasons, asked by the
        # driver after the authorisation above.
        result = await self.apply(
            interaction,
            game,
            Action(
                PromptKind.MANEUVER_ACTION,
                "",
                {"side": side, "maneuver_key": maneuver_key},
            ),
        )
        if result is None:
            return

        await interaction.response.send_message(
            "You chose "
            f"**{self.cog.engine.maneuver_name(maneuver_key)}**.",
            ephemeral=True,
        )

        for line in result.answer:
            await send_new_prompt(interaction, line)

        await self.cog.close_maneuver_prompt(interaction, game, result.match)

        await self.cog.present(interaction, game, result)

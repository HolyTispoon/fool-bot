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
from d12ball.flow.driver import STEP_OWED, Action
from d12ball.formatting import contestant_detail  # noqa: F401 -- re-exported
from d12ball.prompts import pending_prompt
from gamesaves.d12ball.service import CarryFrom, GameResult
from cogs.d12ball_helpers import (
    ERROR_RECOVERY_ADVICE,
    HELPER_CONFIRMED_EXTRA,
    LOGGER,
    HelperConfirmationRequired,
    format_player,
    format_player_with_team,
    game_participant_ids,
    helper_click_confirmed,
    # Aliased because `SafeView` carries methods of these two names --
    # the interaction-shaped front door onto the same two functions.
    # One rule either way; the alias is only so a method body does not
    # read as a recursive call.
    may_act_for_coach as user_may_act_for_coach,
    may_act_in_game as user_may_act_in_game,
    player_with_role,
    send_error_fallback,
)


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
    docs/design/rate-limits.md.
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

    # Whether a game helper's click for somebody else is put behind a
    # confirmation before it acts. True for every view in a game;
    # `LobbyView` turns it off, because a lobby is exactly where a
    # helper is expected to be pressing things for people -- see "Who
    # may act on a game" in docs/design/permissions.md.
    confirms_helper_clicks = True

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
        item: discord.ui.Item,
    ) -> None:
        if isinstance(error, HelperConfirmationRequired):
            await self.ask_helper_confirmation(interaction, item, error)
            return

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
        see "Who may act on a game" in docs/design/permissions.md.
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

        See "Every roll is a coach's" in docs/design/maneuvers.md: any coach in the
        game may press a roll button, not only the one it happens to be
        about, so this is the whole of the check and callers word their
        own refusal.

        A helper who is not one of the coaches is let through only once
        they have confirmed -- see `require_helper_confirmation`.
        """
        if interaction.user.id in game_participant_ids(game):
            return True
        if not user_may_act_in_game(interaction.user, game):
            return False
        self.require_helper_confirmation(
            interaction,
            tuple(
                coach_id
                for coach_id in (game.player_1_id, game.player_2_id)
                if coach_id is not None
            ),
        )
        return True

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

        **The coach it belongs to is answered first, and without a
        confirmation**, whether or not they are also a helper: a coach
        holding `manage_channels` is pressing their own buttons like
        anybody else, and only a click for the *other* coach is a
        helper's. See `require_helper_confirmation`.
        """
        if interaction.user.id == coach_id:
            return True
        if not user_may_act_for_coach(interaction.user, coach_id):
            return False
        self.require_helper_confirmation(interaction, (coach_id,))
        return True

    def require_helper_confirmation(
        self,
        interaction: discord.Interaction,
        coach_ids: tuple[Optional[int], ...],
    ) -> None:
        """
        Raise `HelperConfirmationRequired` unless this helper's click
        for somebody else has already been confirmed, or this view is
        one that asks for no confirmation (the lobby).

        A helper's click is a real one: it moves the game for a coach
        who is not pressing anything. So it is put behind an "are you
        sure" the first time -- `on_error` catches the raise and swaps
        the prompt's buttons for Confirm/Cancel -- and the click that
        confirms carries `HELPER_CONFIRMED_EXTRA` on its own
        `interaction.extras`, which is what lets it through here the
        second time. Every click is asked on its own; nothing is
        remembered between them.
        """
        if not self.confirms_helper_clicks:
            return
        if helper_click_confirmed(interaction):
            return
        raise HelperConfirmationRequired(coach_ids)

    async def ask_helper_confirmation(
        self,
        interaction: discord.Interaction,
        item: discord.ui.Item,
        required: HelperConfirmationRequired,
    ) -> None:
        """
        Put Confirm/Cancel in place of the prompt's buttons for a
        helper's click, and tell the helper why ephemerally.

        **The confirmation replaces the prompt's view in place rather
        than being a second message**, the way `TimeOutConfirmView`
        does: the click that confirms is then a click *on the prompt*,
        so a callback that answers with `edit_message` -- nearly all of
        them -- edits the message it always did. An ephemeral
        confirmation would hand the callback an interaction on the
        ephemeral message, and a coaching flow or a run back would
        carry on inside a message only the helper can see. Both edits
        here are the interaction-callback route, so they cost nothing
        out of the channel's edit bucket (see "Discord's rate limits").
        """
        game = self.cog.games.get(self.game_id)
        names = describe_coaches(
            game, required.coach_ids, self.cog.team_emojis,
        )
        label_names = describe_coaches(game, required.coach_ids, {})

        if interaction.response.is_done() or interaction.message is None:
            # Nothing of ours responds before it gates, so this is a
            # gate asked somewhere it should not have been; refuse
            # rather than leave the click hanging.
            await send_error_fallback(
                interaction,
                f"That click would act for {names}, and it cannot be "
                "confirmed from here. Press the button on the prompt "
                "itself.",
            )
            return

        confirmation = HelperConfirmationView(
            prompt_view=self,
            item=item,
            helper_id=interaction.user.id,
            message=interaction.message,
            label=f"Confirm: act for {label_names}"[:80],
        )
        await interaction.response.edit_message(view=confirmation)
        try:
            await interaction.followup.send(
                f"You are not {names}, but you hold Manage Channels, so "
                "you may press this for them. **Confirm** on the prompt "
                "to go ahead, or **Cancel** to put its buttons back.",
                ephemeral=True,
            )
        except discord.HTTPException:
            # The buttons are already up; the explanation is the part
            # that can be lost.
            pass

    async def refuse(
        self,
        interaction: discord.Interaction,
        reason: str,
    ) -> None:
        """
        Tell the person who clicked why nothing happened, privately --
        whether or not the click has been acknowledged yet.
        """
        done = getattr(interaction.response, "is_done", None)
        if done is not None and done():
            await interaction.followup.send(reason, ephemeral=True)
        else:
            await interaction.response.send_message(reason, ephemeral=True)

    async def apply(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        action: Action,
        *,
        carry_from: CarryFrom = None,
    ) -> Optional[GameResult]:
        """
        Apply what the person did, through `GameService` -- **the one
        door every click goes through** (ARCHITECTURE.md, part 3).

        The service loads the match, answers the question it is
        waiting on, runs everything that follows, saves once and hands
        back a `GameResult`; the view renders the answer's own lines
        as it likes (an edit of the prompt they replace, the dice
        between two of them) and calls `cog.present` for the rest. A
        refusal -- the match is waiting on a different question, the
        answer is not one the prompt offers, or the position refuses
        what was chosen -- is reported to the person who clicked and
        `None` comes back, so a caller reads `if result is None:
        return`. `carry_from` is which of the answer's lines the view
        will show itself; the rest open the next step -- see
        `GameService.apply_action`.

        **Authorisation is not here** and comes before this: whose
        Discord account may press the button is `may_act_for`'s, and
        every reason a refusal can give is a rule about the position.
        """
        try:
            result = self.cog.apply_action(
                game, action, carry_from=carry_from,
            )
        except ValueError as error:
            # A step refusing a position it should never have been
            # handed; what ran before it is written down.
            await send_error_fallback(interaction, str(error))
            return None
        if result.refused:
            await self.refuse(interaction, result.refusal)
            return None
        return result

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

        # **The rule is
        # `d12ball.flow.rolls.declare_overdrive_step`** since Phase 6:
        # which roll this is, who is in it, whether the declaration is
        # still available and what it costs. It is the `overdrive`
        # choice on whichever of the six roll prompts the match is
        # waiting on, so the kind is read off the position rather than
        # off this view -- a prompt may have been sitting in the
        # channel since before the roll it was built for, and the
        # driver refuses it by kind.
        waiting = pending_prompt(self.cog.engine, game, match)
        if waiting is None:
            # No roll is being asked for: the bot owes a step of its
            # own here, and the driver would refuse the same way.
            await self.refuse(interaction, STEP_OWED)
            return
        result = await self.apply(
            interaction,
            game,
            Action(waiting.kind, "overdrive", {"player_id": player_id}),
        )
        if result is None:
            return

        await interaction.response.send_message(result.answer[0])


# How long a helper's Confirm/Cancel stays in place of the prompt's own
# buttons before they are put back on their own. Long enough to read
# the ephemeral explanation and decide; short enough that a helper who
# walked away does not leave a coach without their buttons.
HELPER_CONFIRMATION_TIMEOUT = 120


def describe_coaches(
    game: Optional[D12BallGame],
    coach_ids: tuple[Optional[int], ...],
    team_emojis: dict[Team, str],
) -> str:
    """
    The coach or coaches a helper's click would act for, named the way
    every message names one -- "🟠 One", or "🟠 One or 🟣 Two" for a
    button either coach may press. `None` is an AI side, named as
    `format_player` names it. With an empty emoji dict this is the
    plain form a button label can carry.
    """
    if game is None:
        return "the other coach"
    numbers = []
    for coach_id in coach_ids:
        if coach_id is not None and coach_id == game.player_1_id:
            numbers.append(1)
        else:
            numbers.append(2)
    names = []
    for number in dict.fromkeys(numbers):
        if team_emojis:
            names.append(format_player_with_team(game, number, team_emojis))
        else:
            names.append(format_player(game, number))
    return " or ".join(names)


class HelperConfirmationView(discord.ui.View):
    """
    Confirm/Cancel over a prompt a game helper is about to answer for
    a coach who is not them -- see `SafeView.ask_helper_confirmation`
    for why it stands in for the prompt's own buttons rather than
    being a message of its own.

    **Confirm re-runs the button that asked**, with the confirming
    click marked on its `interaction.extras`, so the gate that raised
    lets it through and the callback runs exactly as it would have.
    Only the helper who asked may confirm; anyone in the game may
    cancel, since while this is up the prompt's own buttons are not.
    A timeout puts them back on its own for the same reason.

    Not restart-safe, and deliberately not registered: a restart
    re-arms the prompt's own view on the message, so the buttons a
    coach sees are these and the clicks they send are answered by
    nothing -- `/d12ball resume` puts the prompt back, the same as any
    other stuck prompt.
    """

    def __init__(
        self,
        prompt_view: SafeView,
        item: discord.ui.Item,
        helper_id: int,
        message: discord.Message,
        label: str,
    ):
        super().__init__(timeout=HELPER_CONFIRMATION_TIMEOUT)
        self.prompt_view = prompt_view
        self.item = item
        self.helper_id = helper_id
        self.message = message

        confirm = discord.ui.Button(
            label=label,
            style=discord.ButtonStyle.danger,
            custom_id=f"d12ball:helper_confirm:{prompt_view.game_id}",
        )
        confirm.callback = self.confirm
        self.add_item(confirm)

        cancel = discord.ui.Button(
            label="Cancel",
            style=discord.ButtonStyle.secondary,
            custom_id=f"d12ball:helper_cancel:{prompt_view.game_id}",
        )
        cancel.callback = self.cancel
        self.add_item(cancel)

    async def confirm(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.helper_id:
            await interaction.response.send_message(
                "Only the helper who asked can confirm this. Cancel puts "
                "the prompt's buttons back.",
                ephemeral=True,
            )
            return

        self.stop()
        interaction.extras[HELPER_CONFIRMED_EXTRA] = True
        try:
            await self.item.callback(interaction)
        except Exception as error:
            # The prompt's own catch-all, exactly as discord.py would
            # have reached it had the click come in the ordinary way.
            await self.prompt_view.on_error(interaction, error, self.item)

        # A callback that answered by editing the prompt has already
        # replaced these buttons. One that answered with a message of
        # its own -- the maneuver pick's ephemeral reply -- has left
        # them up, so the prompt's own go back by hand. That is the one
        # channel-route edit here, and only a helper's confirmed click
        # on such a prompt pays it.
        if interaction.response.type not in (
            discord.InteractionResponseType.message_update,
            discord.InteractionResponseType.deferred_message_update,
        ):
            await self.restore_prompt(interaction.message)

    async def cancel(self, interaction: discord.Interaction) -> None:
        game = self.prompt_view.cog.games.get(self.prompt_view.game_id)
        if (
            interaction.user.id != self.helper_id
            and not (game is not None and user_may_act_in_game(
                interaction.user, game,
            ))
        ):
            await interaction.response.send_message(
                "Only a coach in this game, or a game helper, can cancel "
                "this.",
                ephemeral=True,
            )
            return

        self.stop()
        await interaction.response.edit_message(view=self.prompt_view)

    async def on_timeout(self) -> None:
        await self.restore_prompt(self.message)

    async def restore_prompt(
        self, message: Optional[discord.Message],
    ) -> None:
        try:
            await message.edit(view=self.prompt_view)
        except (discord.HTTPException, AttributeError):
            # An ephemeral prompt cannot be edited through the channel,
            # and a deleted one is gone; either way the buttons are not
            # worth more than the turn they sit under.
            pass


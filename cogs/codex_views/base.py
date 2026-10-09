"""
`SafeView`, which every Codex view subclasses: the game's lock around a
click's whole answer (`botkit.views.GameLockedView`'s, shared with D12
Ball), the error surfaced instead of swallowed, the lookups, the gates,
and `apply` -- the one call a click makes, through `GameService`
(modelled on `cogs/d12ball_views/base.py`; docs/codex-bot.md, decision
2).

It imports from no sibling, which keeps the package a DAG.

**The helper's confirmation** is D12 Ball's shape
(`cogs/d12ball_views/base.py`): a game helper's click for a player is
put behind Confirm/Cancel in place of the view's own buttons, and the
click that confirms carries `HELPER_CONFIRMED_EXTRA` and re-runs the
button. In the Codex bot only one button is a helper's to press for
somebody -- the opponent's agreement to an undo to the previous turn
(`UndoConfirmView`) -- since the panel is ephemeral to the player who
opened it, so nobody else can see it to press it. The lobby asks no
confirmation (`confirms_helper_clicks = False`).
"""

import logging
from typing import Optional

import discord

from codex.components import MatchState
from codex.game import CodexGame, RuleRefusal
from codex.prompts import Action
from cogs.game_auth import (
    HELPER_CONFIRMED_EXTRA,
    HelperConfirmationRequired,
    helper_click_confirmed,
    is_game_helper,
)
from cogs.game_auth import may_act_in_game as user_may_act_in_game
from botkit.views import GameLockedView
from gamesaves.codex.service import GameResult

LOGGER = logging.getLogger(__name__)

#: How long a helper's Confirm/Cancel stays up.
HELPER_CONFIRMATION_TIMEOUT = 300

#: What a click that failed is told, beside what went wrong.
ERROR_RECOVERY_ADVICE = (
    "If trying again doesn't work, `/codex resume` puts the table back up. "
    "If that doesn't help either, let the bot developer know."
)


async def send_ephemeral(interaction: discord.Interaction, message: str) -> None:
    """Tell the person who clicked, privately, whether or not the click
    has been answered yet; a failure to say so is swallowed."""
    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except discord.HTTPException:
        pass


class SafeView(GameLockedView):
    """
    Base class for every Codex view. Every subclass carries `self.cog`
    and `self.game_id`, set before anything below is called.
    """

    #: `game_id` and the game's lock around every click are
    #: `botkit.views.GameLockedView`'s, shared with D12 Ball.
    #: Whether a game helper's click for a player is put behind a
    #: confirmation; the lobby turns it off. Until step 4 builds the
    #: confirmation, a view that would ask lets the players alone through.
    confirms_helper_clicks = True

    async def on_error(self, interaction: discord.Interaction, error: Exception,
                       item: discord.ui.Item) -> None:
        if isinstance(error, HelperConfirmationRequired):
            await self.ask_helper_confirmation(interaction, item)
            return
        # The view's class, the item's kind and the game -- never the
        # item itself, whose repr carries its label, and a panel's
        # labels name the cards in a hand (docs/design/codex.md,
        # "Nothing hidden in a log line").
        LOGGER.error(
            "Unhandled error in %s (a %s) on Codex game %s: %r",
            type(self).__name__, type(item).__name__, self.game_id, error, exc_info=error,
        )
        await send_ephemeral(
            interaction, f"Something went wrong handling that click. {ERROR_RECOVERY_ADVICE}",
        )

    def load_match(self) -> tuple[Optional[CodexGame], Optional[MatchState]]:
        """`(game, match)`, or `(game, None)` before Start, or
        `(None, None)` when the game is gone. Silent."""
        game = self.cog.games.get(self.game_id)
        if game is None:
            return None, None
        if game.match_state is None:
            return game, None
        return game, self.cog.service.load(game)

    async def require_match(self, interaction: discord.Interaction) -> tuple[Optional[CodexGame], Optional[MatchState]]:
        game, match = self.load_match()
        if match is None:
            await send_ephemeral(interaction, "I could not find the saved data for this game.")
            return None, None
        return game, match

    def seat_of(self, interaction: discord.Interaction, game: CodexGame) -> Optional[int]:
        """The seat the clicker holds, or None."""
        return game.seat_of(interaction.user.id)

    def may_act_in_game(self, interaction: discord.Interaction, game: CodexGame) -> bool:
        """Either player -- or, where this view asks no confirmation, a
        game helper (`cogs.game_auth.may_act_in_game`)."""
        if game.seat_of(interaction.user.id) is not None:
            return True
        return not self.confirms_helper_clicks and user_may_act_in_game(interaction.user, game)

    def require_helper_confirmation(self, interaction: discord.Interaction,
                                    player_ids: tuple[Optional[int], ...]) -> None:
        """
        Raise `HelperConfirmationRequired` for a game helper's click for
        somebody else that has not been confirmed yet; `on_error` puts
        Confirm/Cancel up in the view's place. Nothing is remembered
        between clicks.
        """
        if not self.confirms_helper_clicks or helper_click_confirmed(interaction):
            return
        raise HelperConfirmationRequired(player_ids)

    def may_act_for(self, interaction: discord.Interaction, game: CodexGame,
                    seat: int) -> bool:
        """The player in `seat`, or a game helper behind a confirmation
        (`cogs.game_auth.may_act_for_coach`, with `is True`)."""
        player_id = game.player_1_id if seat == 1 else game.player_2_id
        if interaction.user.id == player_id:
            return True
        if not is_game_helper(interaction.user):
            return False
        self.require_helper_confirmation(interaction, (player_id,))
        return True

    async def ask_helper_confirmation(self, interaction: discord.Interaction,
                                      item: discord.ui.Item) -> None:
        """Confirm/Cancel in place of this view's buttons -- the click's
        own response, so nothing out of the channel's edit bucket."""
        if interaction.response.is_done() or interaction.message is None:
            await send_ephemeral(interaction, "That click acts for a player and cannot be confirmed from here.")
            return
        await interaction.response.edit_message(
            view=HelperConfirmationView(self, item, interaction.user.id),
        )
        try:
            await interaction.followup.send(
                "You are not this game's player, but you hold Manage Channels, so you may "
                "press this for them. **Confirm** to go ahead, or **Cancel** to put the "
                "buttons back.",
                ephemeral=True,
            )
        except discord.HTTPException:
            pass

    async def refuse(self, interaction: discord.Interaction, reason: str) -> None:
        await send_ephemeral(interaction, reason)

    async def apply(self, interaction: discord.Interaction, game: CodexGame,
                    action: Action) -> Optional[GameResult]:
        """
        Apply what the person did, through `GameService` -- **the one
        door every click goes through**. A refusal is told to the person
        who clicked and `None` comes back. Authorisation comes before
        this and is not here.
        """
        try:
            result = self.cog.service.apply_action(game.game_id, action)
        except RuleRefusal as error:
            await send_ephemeral(interaction, str(error))
            return None
        if result.refused:
            await self.refuse(interaction, self.cog.render_text(result.refusal, game))
            return None
        return result

    async def answer(self, interaction: discord.Interaction, game: CodexGame,
                     action: Action) -> Optional[GameResult]:
        """`apply`, then what it changed put up by `cog.present`."""
        result = await self.apply(interaction, game, action)
        if result is not None:
            await self.cog.present(game, result)
        return result


class HelperConfirmationView(discord.ui.View):
    """
    Confirm/Cancel over a view a game helper is about to answer for a
    player (`cogs.d12ball_views.base.HelperConfirmationView`, cut to what
    the Codex bot needs). **Confirm re-runs the button that asked**, the
    click marked confirmed on its `interaction.extras`; only that helper
    may confirm, and Cancel -- anybody's -- puts the view back.
    """

    def __init__(self, prompt_view: SafeView, item: discord.ui.Item, helper_id: int) -> None:
        super().__init__(timeout=HELPER_CONFIRMATION_TIMEOUT)
        self.prompt_view = prompt_view
        self.item = item
        self.helper_id = helper_id
        confirm = discord.ui.Button(label="Confirm: act for the player", style=discord.ButtonStyle.danger)
        confirm.callback = self.confirm
        cancel = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary)
        cancel.callback = self.cancel
        self.add_item(confirm)
        self.add_item(cancel)

    async def confirm(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.helper_id:
            await send_ephemeral(interaction, "Only the helper who asked can confirm this.")
            return
        self.stop()
        interaction.extras[HELPER_CONFIRMED_EXTRA] = True
        try:
            await self.item.callback(interaction)
        except Exception as error:
            await self.prompt_view.on_error(interaction, error, self.item)

    async def cancel(self, interaction: discord.Interaction) -> None:
        self.stop()
        await interaction.response.edit_message(view=self.prompt_view)

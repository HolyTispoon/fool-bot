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

import asyncio
import contextlib
import contextvars
import hashlib
import io
import logging
import time
from typing import Optional, Sequence, Union

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
from gamelocks import GameLocks
from gamesaves.codex.service import GameResult

LOGGER = logging.getLogger(__name__)

#: How long a helper's Confirm/Cancel stays up.
HELPER_CONFIRMATION_TIMEOUT = 300

#: What a click that failed is told, beside what went wrong.
ERROR_RECOVERY_ADVICE = (
    "If trying again doesn't work, `/codex resume` puts the table back up. "
    "If that doesn't help either, let the bot developer know."
)


def picture_file(webp: bytes, stem: str) -> discord.File:
    """
    A picture -- a hand, a codex view, the tech picker -- as a file
    **named by what it shows**: `<stem>-<digest>.webp`, the digest its
    bytes'. The same picture is the same name, which is how an edit in
    place knows the message already carries it (`kept_pictures`).
    """
    digest = hashlib.sha256(webp).hexdigest()[:12]
    return discord.File(io.BytesIO(webp), filename=f"{stem}-{digest}.webp")


def kept_pictures(files: Sequence[discord.File],
                  message) -> list[Union[discord.Attachment, discord.File]]:
    """
    `files` for an edit of `message`, a picture the message already
    carries under the same name (`picture_file`) kept rather than
    uploaded again: no upload, and the client shows the picture it
    already has instead of fetching the same one anew. A panel edited in
    place for a target, an attacker or a menu shows the same hand it
    did.
    """
    carried = {attachment.filename: attachment
               for attachment in getattr(message, "attachments", None) or ()}
    return [carried.get(file.filename, file) for file in files]


async def acknowledge(interaction: discord.Interaction) -> None:
    """Defer the click, unless it was answered already -- by the lock,
    where it found its game busy (`acknowledges_while_waiting`)."""
    if not interaction.response.is_done():
        await interaction.response.defer()


async def edit_clicked(interaction: discord.Interaction, **fields) -> None:
    """Edit the message clicked: the click's own response, or, on a
    click answered already, the interaction's original message -- which
    for a button is the message it is on. A new picture in an ephemeral
    message is drawn again a moment later (`redraw_pictures`)."""
    if interaction.response.is_done():
        message = await interaction.edit_original_response(**fields)
    else:
        message = _resource(await interaction.response.edit_message(**fields))
    redraw_pictures(interaction, message, fields)


async def send_answer(interaction: discord.Interaction, content: Optional[str], **fields) -> None:
    """A message of the click's own: its response, or a follow-up on a
    click answered already. A new picture in an ephemeral message is
    drawn again a moment later (`redraw_pictures`)."""
    if interaction.response.is_done():
        message = await interaction.followup.send(content, **fields)
        redraw_pictures(interaction, message, fields, followup=True)
    else:
        message = _resource(await interaction.response.send_message(content, **fields))
        redraw_pictures(interaction, message, fields)


#: How long after an ephemeral message goes up with a new picture it is
#: edited again with the attachments it already carries. Discord's apps
#: show a new picture in an ephemeral message as a grey box of its size
#: and never fetch it, for everybody, whatever the format or the size --
#: while the same picture in a public message loads -- until the message
#: is drawn again, which an edit that keeps the picture does (seen by
#: both developers, 2026-10-15). A guess at how long Discord needs
#: before a second drawing loads; tune it from what the players see.
#: 1 s did not show the picture reliably (2026-10-16), where a click
#: seconds later always had: 3 s, to learn whether it is the wait.
PICTURE_REDRAW_DELAY = 3.0

#: The game's lock around the click being answered, so a redraw it
#: schedules waits behind any click after it (`SafeView._scheduled_task`).
_CLICK_LOCK: contextvars.ContextVar[Optional[asyncio.Lock]] = contextvars.ContextVar(
    "codex_click_lock", default=None,
)

#: The one redraw waiting on each ephemeral message, by the message's
#: id -- **the record of what the message carries**: while it waits,
#: nothing has been written to the message since its picture went up,
#: because every write that changes an ephemeral message's pictures is
#: `edit_clicked`'s or `send_answer`'s, and each drops the redraw
#: waiting on the message it writes. Held here, too, so the event loop
#: does not lose the task.
_PENDING: dict[int, asyncio.Task] = {}


def _resource(callback) -> Optional[discord.Message]:
    """The message a response made or edited, off discord.py's
    `InteractionCallbackResponse` -- `None` where there is none."""
    return getattr(callback, "resource", None)


def _uploads(fields: dict) -> bool:
    """Whether a write uploads a picture rather than keeping one."""
    sent = [fields.get("file"), *(fields.get("files") or ()), *(fields.get("attachments") or ())]
    return any(isinstance(one, discord.File) for one in sent)


def redraw_pictures(interaction: discord.Interaction, message: Optional[discord.Message],
                    fields: dict, *, followup: bool = False) -> None:
    """
    After `message` was written with `fields`. The redraw waiting on it,
    if any, is dropped: what this write put up is the message's now, and
    a write that keeps the picture is itself a redraw. Where the message
    is ephemeral and this write uploaded a picture, it is edited again
    `PICTURE_REDRAW_DELAY` later with the attachments it carries and
    nothing else, so Discord's apps draw it again and load the picture.
    `followup`: the message is a follow-up of the click rather than its
    original. Never waits: the redraw is a task of its own.
    """
    message_id = getattr(message, "id", None)
    if message_id is None:
        if _uploads(fields):
            # Discord handed no message back: no redraw, and the picture
            # may stay grey. Said, so the console can tell this from a
            # redraw that ran and did not help.
            LOGGER.info("A picture went up with no message handed back: nothing to redraw")
        return
    waiting = _PENDING.pop(message_id, None)
    # `cancel()` is True only for a redraw still to come, not one that
    # finished before its `forget` ran.
    if waiting is not None and waiting.cancel():
        LOGGER.info("A picture's redraw dropped: its message was written again first")
    # `is True`: a test's Mock message is truthy everywhere.
    ephemeral = getattr(getattr(message, "flags", None), "ephemeral", None)
    if ephemeral is not True or not _uploads(fields):
        return
    task = asyncio.create_task(
        _redraw(interaction, message, followup, _CLICK_LOCK.get(), time.perf_counter()))
    _PENDING[message_id] = task

    def forget(done: asyncio.Task) -> None:
        if _PENDING.get(message_id) is done:
            del _PENDING[message_id]

    task.add_done_callback(forget)


async def _redraw(interaction: discord.Interaction, message: discord.Message,
                  followup: bool, lock: Optional[asyncio.Lock], went_up: float) -> None:
    """
    The redraw itself: one edit, with the attachments `message` went up
    with, under the game's lock where a click scheduled it -- so no click
    can write the message between the redraw's turn coming and its edit
    landing, and put up a picture the edit would take back. A write
    since cancels it (`redraw_pictures`). Each one made is a console
    line, when it landed and what its edit took, so a picture still grey
    can be told from a redraw that never ran. Anything that goes wrong is
    a console warning: the picture is shown or it is not.
    """
    await asyncio.sleep(PICTURE_REDRAW_DELAY)
    try:
        async with lock if lock is not None else contextlib.nullcontext():
            started = time.perf_counter()
            if followup:
                await interaction.followup.edit_message(message.id, attachments=message.attachments)
            else:
                await interaction.edit_original_response(attachments=message.attachments)
        done = time.perf_counter()
        LOGGER.info("An ephemeral picture redrawn %.1f s after it went up (the edit %d ms)",
                    done - went_up, round((done - started) * 1000))
    except discord.NotFound as error:
        # Dismissed since, the click's token expired, or its webhook
        # unknown: nothing to draw, and nobody to act -- INFO, with the
        # code that tells the three apart.
        LOGGER.info("An ephemeral picture's redraw found its message gone (%s)", error.code)
    except Exception as error:  # noqa: BLE001 -- a redraw is best effort
        LOGGER.warning("Could not redraw an ephemeral picture: %r", error)


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

    async def _scheduled_task(self, item: discord.ui.Item, interaction: discord.Interaction) -> None:
        """`GameLockedView`'s dispatch, with the game's lock named for a
        redraw the click schedules to wait on (`redraw_pictures`)."""
        locks = getattr(self.cog, "locks", None)
        held = locks.hold(self.game_id) if isinstance(locks, GameLocks) and self.game_id else None
        token = _CLICK_LOCK.set(held)
        try:
            await super()._scheduled_task(item, interaction)
        finally:
            _CLICK_LOCK.reset(token)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Every click on a game played in a thread first takes the
        thread out of the archive, where Discord archived it after a
        week idle (`Codex.wake_thread`). Never refuses the click."""
        thread = interaction.channel
        if isinstance(thread, discord.Thread) and thread.archived:
            await self.cog.wake_thread(thread, self.cog.games.get(self.game_id))
        return True

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
        player_id = game.seat_user_id(seat)
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

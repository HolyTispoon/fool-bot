"""
The redraw of a new picture in an ephemeral message (`redraw_pictures`):
Discord's apps leave one a grey box until the message is drawn again, so
the bot edits it once more with the attachments it carries -- one edit,
under the click's game lock, and none where the message has been written
since.
"""

import asyncio
import io
import itertools
import unittest
from types import SimpleNamespace
from unittest import mock

import discord

from cogs.codex_views import base
from cogs.codex_views.base import SafeView, edit_clicked, send_answer
from gamelocks import GameLocks

MESSAGE_IDS = itertools.count(500)


def message(*attachment_ids: int, ephemeral: bool = True, message_id=None):
    return SimpleNamespace(
        id=next(MESSAGE_IDS) if message_id is None else message_id,
        flags=SimpleNamespace(ephemeral=ephemeral),
        attachments=[SimpleNamespace(id=one) for one in attachment_ids],
    )


def picture() -> discord.File:
    return discord.File(io.BytesIO(b"webp"), filename="codex-hand-0123.webp")


class FakeInteraction:
    """A click whose writes come back as `sent`, logged in order."""

    def __init__(self, sent, done: bool = False) -> None:
        self.log: list = []
        self.channel = None
        self.data: dict = {}
        interaction = self

        class Response:
            def is_done(self) -> bool:
                return done

            async def edit_message(self, **fields):
                interaction.log.append(("response.edit", fields))
                return SimpleNamespace(resource=sent)

            async def send_message(self, content=None, **fields):
                interaction.log.append(("response.send", fields))
                return SimpleNamespace(resource=sent)

        class Followup:
            async def send(self, content=None, **fields):
                interaction.log.append(("followup.send", fields))
                return sent

            async def edit_message(self, message_id, **fields):
                interaction.log.append(("followup.edit", fields))

        self.response = Response()
        self.followup = Followup()

    async def edit_original_response(self, **fields):
        self.log.append(("original.edit", fields))


async def redraws_done() -> None:
    while base._PENDING:
        await asyncio.gather(*list(base._PENDING.values()), return_exceptions=True)


class RedrawTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        patcher = mock.patch.object(base, "PICTURE_REDRAW_DELAY", 0)
        patcher.start()
        self.addCleanup(patcher.stop)

    def kinds(self, interaction) -> list[str]:
        return [kind for kind, _ in interaction.log]

    async def test_a_new_picture_in_a_panel_is_drawn_again_with_what_it_carries(self) -> None:
        """One edit, the attachments the panel went up with and nothing
        else -- no read of the message first."""
        sent = message(7)
        interaction = FakeInteraction(sent)
        await edit_clicked(interaction, content="Your turn", attachments=[picture()])
        await redraws_done()
        self.assertEqual(self.kinds(interaction), ["response.edit", "original.edit"])
        self.assertEqual(interaction.log[-1][1], {"attachments": sent.attachments})

    async def test_a_new_hand_is_drawn_again(self) -> None:
        interaction = FakeInteraction(message(7))
        await send_answer(interaction, "Your hand", file=picture(), ephemeral=True)
        await redraws_done()
        self.assertEqual(self.kinds(interaction), ["response.send", "original.edit"])

    async def test_a_follow_up_is_drawn_again_as_a_follow_up(self) -> None:
        interaction = FakeInteraction(message(7), done=True)
        await send_answer(interaction, "Your deck", file=picture(), ephemeral=True)
        await redraws_done()
        self.assertEqual(self.kinds(interaction), ["followup.send", "followup.edit"])

    async def test_a_kept_picture_is_not_drawn_again(self) -> None:
        sent = message(7)
        interaction = FakeInteraction(sent)
        await edit_clicked(interaction, attachments=list(sent.attachments))
        await redraws_done()
        self.assertEqual(self.kinds(interaction), ["response.edit"])

    async def test_a_public_message_is_not_drawn_again(self) -> None:
        interaction = FakeInteraction(message(7, ephemeral=False))
        await send_answer(interaction, "The board", file=picture())
        await redraws_done()
        self.assertEqual(self.kinds(interaction), ["response.send"])

    async def test_a_message_written_since_is_left_alone(self) -> None:
        """The click after keeps the picture: that edit drew the message
        again already, and the redraw waiting on it is dropped."""
        sent = message(7)
        first = FakeInteraction(sent)
        await edit_clicked(first, attachments=[picture()])
        second = FakeInteraction(sent)
        await edit_clicked(second, attachments=list(sent.attachments))
        await redraws_done()
        self.assertEqual(self.kinds(first), ["response.edit"])
        self.assertEqual(self.kinds(second), ["response.edit"])

    async def test_pictures_put_up_one_after_another_are_drawn_again_once(self) -> None:
        """Five pictures in a row on one panel wait as one redraw, the
        last picture's."""
        sent = message(7)
        clicks = [FakeInteraction(sent) for _ in range(5)]
        for click in clicks:
            await edit_clicked(click, attachments=[picture()])
        self.assertEqual(len(base._PENDING), 1)
        await redraws_done()
        self.assertEqual([self.kinds(click)[-1] for click in clicks],
                         ["response.edit"] * 4 + ["original.edit"])

    async def test_another_message_keeps_its_own_redraw(self) -> None:
        hand, deck = FakeInteraction(message(7)), FakeInteraction(message(8))
        await edit_clicked(hand, attachments=[picture()])
        await send_answer(deck, "Your deck", file=picture(), ephemeral=True)
        await redraws_done()
        self.assertEqual(self.kinds(hand)[-1], "original.edit")
        self.assertEqual(self.kinds(deck)[-1], "original.edit")

    async def test_a_message_gone_says_nothing(self) -> None:
        interaction = FakeInteraction(message(7))

        async def gone(**fields):
            raise discord.NotFound(SimpleNamespace(status=404, reason="Not Found"), "Unknown Message")

        interaction.edit_original_response = gone
        with self.assertNoLogs("cogs.codex_views.base", level="WARNING"):
            await edit_clicked(interaction, attachments=[picture()])
            await redraws_done()

    async def test_any_other_failure_is_a_console_warning_and_never_escapes(self) -> None:
        """Not a discord.py `HTTPException` either -- `ClientException`,
        say: a task that died with it would be asyncio's ERROR, which
        reaches #logs."""
        interaction = FakeInteraction(message(7))

        async def broken(**fields):
            raise discord.ClientException("Channel for message could not be resolved")

        interaction.edit_original_response = broken
        with self.assertLogs("cogs.codex_views.base", level="WARNING") as logs:
            await edit_clicked(interaction, attachments=[picture()])
            tasks = list(base._PENDING.values())
            await redraws_done()
        self.assertIn("ClientException", logs.output[0])
        self.assertTrue(all(task.exception() is None for task in tasks))


class Panel(SafeView):
    """A view of one game whose one button puts a new picture up."""

    def __init__(self, cog, game_id: str) -> None:
        super().__init__(timeout=None)
        self.cog, self.game_id = cog, game_id

    @discord.ui.button(label="Show", custom_id="panel:show")
    async def show(self, interaction, button) -> None:
        await edit_clicked(interaction, attachments=[picture()])


class ClickLockTests(unittest.IsolatedAsyncioTestCase):
    """The redraw a real click schedules waits on that game's lock --
    the one `GameLockedView` holds around every click on the game."""

    async def test_the_redraw_waits_behind_the_games_lock(self) -> None:
        with mock.patch.object(base, "PICTURE_REDRAW_DELAY", 0):
            cog = SimpleNamespace(locks=GameLocks(), games={})
            view = Panel(cog, "g1")
            interaction = FakeInteraction(message(7))
            interaction.data = {"custom_id": "panel:show", "component_type": 2}
            await view._scheduled_task(view.show, interaction)
            self.assertEqual(self.kinds(interaction), ["response.edit"])
            async with cog.locks.hold("g1"):
                await asyncio.sleep(0.01)
                self.assertEqual(self.kinds(interaction), ["response.edit"])
            await redraws_done()
            self.assertEqual(self.kinds(interaction), ["response.edit", "original.edit"])

    async def test_another_games_lock_does_not_hold_it(self) -> None:
        with mock.patch.object(base, "PICTURE_REDRAW_DELAY", 0):
            cog = SimpleNamespace(locks=GameLocks(), games={})
            view = Panel(cog, "g1")
            interaction = FakeInteraction(message(7))
            interaction.data = {"custom_id": "panel:show", "component_type": 2}
            await view._scheduled_task(view.show, interaction)
            async with cog.locks.hold("g2"):
                await asyncio.sleep(0.01)
                self.assertEqual(self.kinds(interaction), ["response.edit", "original.edit"])

    def kinds(self, interaction) -> list[str]:
        return [kind for kind, _ in interaction.log]


if __name__ == "__main__":
    unittest.main()

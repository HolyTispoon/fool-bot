"""
The redraw of a new picture in an ephemeral message (`redraw_pictures`):
Discord's apps leave one a grey box until the message is drawn again, so
the bot edits it once more with the attachments it carries -- and only
where nothing has been put up over it since.
"""

import asyncio
import io
import unittest
from types import SimpleNamespace
from unittest import mock

import discord

from cogs.codex_views import base
from cogs.codex_views.base import _CLICK_LOCK, edit_clicked, send_answer


def message(*attachment_ids: int, ephemeral: bool = True, message_id: int = 500):
    return SimpleNamespace(
        id=message_id,
        flags=SimpleNamespace(ephemeral=ephemeral),
        attachments=[SimpleNamespace(id=one) for one in attachment_ids],
    )


def picture() -> discord.File:
    return discord.File(io.BytesIO(b"webp"), filename="codex-hand-0123.webp")


class FakeInteraction:
    """A click whose writes come back as messages, logged in order."""

    def __init__(self, sent, now=None, done: bool = False) -> None:
        self.log: list = []
        self._original_response = None
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

            async def fetch_message(self, message_id):
                interaction.log.append(("followup.fetch", message_id))
                return now or sent

            async def edit_message(self, message_id, **fields):
                interaction.log.append(("followup.edit", fields))

        self.response = Response()
        self.followup = Followup()
        self.now = now or sent

    async def original_response(self):
        self.log.append(("original.fetch", None))
        return self._original_response or self.now

    async def edit_original_response(self, **fields):
        self.log.append(("original.edit", fields))
        return self.now


async def redraws_done() -> None:
    while base._REDRAWS:
        await asyncio.gather(*list(base._REDRAWS))


class RedrawTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        patcher = mock.patch.object(base, "PICTURE_REDRAW_DELAY", 0)
        patcher.start()
        self.addCleanup(patcher.stop)

    def kinds(self, interaction) -> list[str]:
        return [kind for kind, _ in interaction.log]

    async def test_a_new_picture_in_a_panel_is_drawn_again_with_what_it_carries(self) -> None:
        sent = message(7)
        interaction = FakeInteraction(sent)
        await edit_clicked(interaction, content="Your turn", attachments=[picture()])
        await redraws_done()
        self.assertEqual(self.kinds(interaction), ["response.edit", "original.fetch", "original.edit"])
        self.assertEqual(interaction.log[-1][1], {"attachments": sent.attachments})

    async def test_the_original_is_read_from_discord_not_discord_pys_memory(self) -> None:
        interaction = FakeInteraction(message(7))
        interaction._original_response = message(1)
        await edit_clicked(interaction, attachments=[picture()])
        await redraws_done()
        self.assertEqual(self.kinds(interaction)[-1], "original.edit")

    async def test_a_new_hand_is_drawn_again(self) -> None:
        interaction = FakeInteraction(message(7))
        await send_answer(interaction, "Your hand", file=picture(), ephemeral=True)
        await redraws_done()
        self.assertEqual(self.kinds(interaction), ["response.send", "original.fetch", "original.edit"])

    async def test_a_follow_up_is_drawn_again_as_a_follow_up(self) -> None:
        interaction = FakeInteraction(message(7), done=True)
        await send_answer(interaction, "Your deck", file=picture(), ephemeral=True)
        await redraws_done()
        self.assertEqual(self.kinds(interaction), ["followup.send", "followup.fetch", "followup.edit"])

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

    async def test_a_panel_changed_since_is_left_alone(self) -> None:
        interaction = FakeInteraction(message(7), now=message(8))
        await edit_clicked(interaction, attachments=[picture()])
        await redraws_done()
        self.assertEqual(self.kinds(interaction), ["response.edit", "original.fetch"])

    async def test_a_panel_gone_is_logged_and_nothing_raised(self) -> None:
        interaction = FakeInteraction(message(7))

        async def gone():
            raise discord.NotFound(SimpleNamespace(status=404, reason="Not Found"), "Unknown Message")

        interaction.original_response = gone
        with self.assertLogs("cogs.codex_views.base", level="WARNING"):
            await edit_clicked(interaction, attachments=[picture()])
            await redraws_done()

    async def test_the_redraw_waits_behind_the_clicks_lock(self) -> None:
        lock = asyncio.Lock()
        interaction = FakeInteraction(message(7))
        token = _CLICK_LOCK.set(lock)
        try:
            await edit_clicked(interaction, attachments=[picture()])
        finally:
            _CLICK_LOCK.reset(token)
        async with lock:
            await asyncio.sleep(0.01)
            self.assertEqual(self.kinds(interaction), ["response.edit"])
        await redraws_done()
        self.assertEqual(self.kinds(interaction)[-1], "original.edit")


if __name__ == "__main__":
    unittest.main()

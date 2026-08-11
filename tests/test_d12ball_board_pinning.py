"""
Pinning the board at a new play.

A pinned board is a jump list of the moments worth going back to --
kickoff, halftime, and each restart after a goal, an own goal, a missed
shot or a ball out of bounds. Discord caps a channel at 50 pins, so the
interesting behaviour is at the cap: the bot rolls off the oldest board
it pinned and leaves anything a person pinned alone.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

import discord

from cogs.d12ball import D12Ball
from cogs.d12ball_helpers import (
    MAX_PINS_ERROR_CODE,
    board_image_filename,
    is_board_image_message,
    pin_board_message,
)


class FakeResponse:
    status = 400
    reason = "Bad Request"


def max_pins_error() -> discord.HTTPException:
    return discord.HTTPException(
        FakeResponse(), {"code": MAX_PINS_ERROR_CODE, "message": "Max pins"},
    )


def other_error() -> discord.HTTPException:
    return discord.HTTPException(
        FakeResponse(), {"code": 50013, "message": "Missing Permissions"},
    )


class FakeMessage:
    def __init__(
        self,
        message_id: int = 1,
        filenames: list[str] = None,
        channel=None,
        pin_errors: list[Exception] = None,
    ) -> None:
        self.id = message_id
        self.attachments = [
            SimpleNamespace(filename=name) for name in (filenames or [])
        ]
        self.channel = channel
        self.pin_errors = list(pin_errors or [])
        self.pins = 0
        self.unpins = 0

    async def pin(self, **_) -> None:
        self.pins += 1
        if self.pin_errors:
            raise self.pin_errors.pop(0)

    async def unpin(self, **_) -> None:
        self.unpins += 1


class FakeChannel:
    """A channel whose pin list is whatever the test hands it."""

    def __init__(self, pinned: list[FakeMessage]) -> None:
        self.pinned = pinned
        self.pin_queries: list[dict] = []

    def pins(self, **kwargs):
        self.pin_queries.append(kwargs)
        pinned = self.pinned

        async def iterate():
            for message in pinned:
                yield message

        return iterate()


BOARD = board_image_filename(7)


class BoardPinTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_board_is_pinned(self) -> None:
        message = FakeMessage(filenames=[BOARD])

        await pin_board_message(message)

        self.assertEqual(message.pins, 1)

    async def test_the_oldest_board_rolls_off_at_the_cap(self) -> None:
        oldest = FakeMessage(message_id=10, filenames=[BOARD])
        newer = FakeMessage(message_id=11, filenames=[BOARD])
        channel = FakeChannel([oldest, newer])
        message = FakeMessage(
            message_id=99,
            filenames=[BOARD],
            channel=channel,
            pin_errors=[max_pins_error()],
        )

        await pin_board_message(message)

        self.assertEqual(oldest.unpins, 1)
        self.assertEqual(newer.unpins, 0)
        self.assertEqual(message.pins, 2)
        self.assertTrue(channel.pin_queries[0]["oldest_first"])

    async def test_somebody_else_s_pin_is_never_rolled_off(self) -> None:
        theirs = FakeMessage(message_id=10, filenames=["notes.txt"])
        channel = FakeChannel([theirs])
        message = FakeMessage(
            message_id=99,
            filenames=[BOARD],
            channel=channel,
            pin_errors=[max_pins_error()],
        )

        await pin_board_message(message)

        # Nothing of ours to make room with, so the board simply goes
        # unpinned rather than displacing a pin we did not make.
        self.assertEqual(theirs.unpins, 0)
        self.assertEqual(message.pins, 1)

    async def test_any_other_failure_is_swallowed_whole(self) -> None:
        channel = FakeChannel([FakeMessage(message_id=10, filenames=[BOARD])])
        message = FakeMessage(
            message_id=99,
            filenames=[BOARD],
            channel=channel,
            pin_errors=[other_error()],
        )

        await pin_board_message(message)

        # A permissions failure is not something a roll-off fixes, so
        # the pin list is not even read.
        self.assertEqual(channel.pin_queries, [])
        self.assertEqual(message.pins, 1)

    def test_a_board_is_recognised_by_its_filename(self) -> None:
        self.assertTrue(
            is_board_image_message(FakeMessage(filenames=[BOARD]))
        )
        self.assertFalse(
            is_board_image_message(FakeMessage(filenames=["dice.png"]))
        )
        self.assertFalse(is_board_image_message(FakeMessage()))


class NewPlayBoardTests(unittest.IsolatedAsyncioTestCase):
    def build(self):
        cog = object.__new__(D12Ball)
        cog.games = {}
        cog.render_match_png = mock.AsyncMock(return_value=b"png")
        cog.match_file_from_png = mock.Mock(side_effect=lambda game, png: png)
        cog.refresh_match_image = mock.AsyncMock()
        snapshot = FakeMessage(message_id=5, filenames=[BOARD])
        interaction = SimpleNamespace(
            followup=SimpleNamespace(
                send=mock.AsyncMock(return_value=snapshot),
            ),
        )
        game = SimpleNamespace(game_id="g", game_number=7)
        return cog, interaction, game, snapshot

    async def test_the_board_is_drawn_once_and_uploaded_twice(self) -> None:
        cog, interaction, game, _ = self.build()

        with mock.patch("cogs.d12ball.add_full_image_button", mock.AsyncMock()), \
                mock.patch("cogs.d12ball.pin_board_message", mock.AsyncMock()):
            await cog.post_new_play_board(interaction, game, "# New play")

        cog.render_match_png.assert_awaited_once()
        self.assertEqual(
            cog.refresh_match_image.await_args.kwargs["png"], b"png",
        )
        self.assertEqual(
            interaction.followup.send.await_args.args[0], "# New play",
        )

    async def test_the_snapshot_is_the_message_that_gets_pinned(
        self,
    ) -> None:
        cog, interaction, game, snapshot = self.build()
        pin = mock.AsyncMock()

        with mock.patch("cogs.d12ball.add_full_image_button", mock.AsyncMock()), \
                mock.patch("cogs.d12ball.pin_board_message", pin):
            await cog.post_new_play_board(interaction, game, "# New play")

        pin.assert_awaited_once_with(snapshot)


if __name__ == "__main__":
    unittest.main()

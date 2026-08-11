"""
How often the persistent board message is written.

Every 429 the bot collected in a session of play was a PATCH on the
board message. `message_id` is not one of Discord's major rate-limit
parameters, so those edits share a single per-*channel* bucket with
every other channel-sourced edit in the game -- roughly five requests
in five seconds, and a refresh spends two of them. Fifty-odd call sites
ask for one, so what has to be held down is how often the board is
actually written, and whether the write says anything new.
"""

import asyncio
import itertools
import logging
import time
import unittest
from types import SimpleNamespace
from unittest import mock

import discord

from cogs.d12ball import (
    BOARD_REFRESH_BACKOFF_CEILING,
    BOARD_REFRESH_INTERVAL,
    LOGGER,
    D12Ball,
)


class FakeAttachment:
    def __init__(self, url: str) -> None:
        self.url = url


class FakeMessage:
    def __init__(self) -> None:
        self.edits = 0
        self.fields: list[dict] = []
        self.attachments = [FakeAttachment(ATTACHMENT_URL)]

    async def edit(self, **fields):
        self.edits += 1
        self.fields.append(fields)
        return self


class FakeChannel:
    """
    Counts the edits landing on the one message a game's board lives
    in, which is the bucket the 429s were coming from.
    """

    def __init__(self) -> None:
        self.message = FakeMessage()

    def get_partial_message(self, message_id: int) -> FakeMessage:
        return self.message


# What a board upload comes back as. The signature is what the link
# button needs and the only thing an edit changes about it.
ATTACHMENT_URL = (
    "https://cdn.discordapp.com/attachments/1/2/d12ball-pbd17.png?ex=1&hm=a"
)


def build_cog() -> D12Ball:
    cog = object.__new__(D12Ball)
    cog.games = {}
    cog.board_refreshed_at = {}
    cog.board_refresh_tasks = {}
    cog.board_png_digests = {}
    cog.board_link_owed = {}
    cog.board_refresh_locks = {}
    cog.board_writes_refused = {}
    cog.board_refresh_wanted = set()
    # Every render differs, so these tests see the write path. The
    # identical-board case has its own class below.
    cog.render_match_png = mock.AsyncMock(
        side_effect=lambda game: f"png{next(RENDERS)}".encode(),
    )
    cog.match_file_from_png = mock.Mock(return_value=object())
    return cog


RENDERS = itertools.count()


def build_game(game_id: str = "g") -> SimpleNamespace:
    return SimpleNamespace(
        game_id=game_id,
        message_id=1234,
        game_number=17,
        # The full-image button is a second edit on the same message;
        # switched off here so the counts read as "refreshes".
        home_and_visiting_selected=False,
    )


class BoardRefreshCoalescingTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_first_refresh_is_immediate(self) -> None:
        cog, game, channel = build_cog(), build_game(), FakeChannel()
        interaction = SimpleNamespace(channel=channel)

        await cog.refresh_match_image(interaction, game)

        self.assertEqual(channel.message.edits, 1)

    async def test_a_burst_collapses_to_one_trailing_refresh(self) -> None:
        # The shape of a single click: several steps, each of which
        # wants the board up to date. Only the last board is worth
        # looking at, and Discord charges for every one of them.
        cog, game, channel = build_cog(), build_game(), FakeChannel()
        interaction = SimpleNamespace(channel=channel)

        with mock.patch("cogs.d12ball.asyncio.sleep", new=mock.AsyncMock()):
            for _ in range(8):
                await cog.refresh_match_image(interaction, game)

            self.assertEqual(channel.message.edits, 1)
            self.assertIn(game.game_id, cog.board_refresh_tasks)
            await asyncio.gather(*cog.board_refresh_tasks.values())

        # One immediate, one trailing -- not eight.
        self.assertEqual(channel.message.edits, 2)

    async def test_the_trailing_refresh_draws_when_it_runs(self) -> None:
        # It re-renders rather than reusing a png handed to it earlier,
        # because by the time it fires the state has moved on. This is
        # what makes one pending refresh enough for any number of
        # requests behind it.
        cog, game, channel = build_cog(), build_game(), FakeChannel()
        interaction = SimpleNamespace(channel=channel)

        await cog.refresh_match_image(interaction, game, png=b"first")
        cog.render_match_png.reset_mock()

        with mock.patch("cogs.d12ball.asyncio.sleep", new=mock.AsyncMock()):
            await cog.refresh_match_image(interaction, game, png=b"second")
            await asyncio.gather(*cog.board_refresh_tasks.values())

        cog.render_match_png.assert_awaited_once_with(game)

    async def test_a_second_burst_does_not_stack_up_tasks(self) -> None:
        cog, game, channel = build_cog(), build_game(), FakeChannel()
        interaction = SimpleNamespace(channel=channel)

        with mock.patch("cogs.d12ball.asyncio.sleep", new=mock.AsyncMock()):
            await cog.refresh_match_image(interaction, game)
            for _ in range(5):
                await cog.refresh_match_image(interaction, game)
            self.assertEqual(len(cog.board_refresh_tasks), 1)
            await asyncio.gather(*cog.board_refresh_tasks.values())

        self.assertEqual(cog.board_refresh_tasks, {})

    async def test_games_are_gated_separately(self) -> None:
        # The bucket is the channel, so two games in two channels do
        # not have to wait for each other.
        cog = build_cog()
        one, two = build_game("one"), build_game("two")
        first, second = FakeChannel(), FakeChannel()

        await cog.refresh_match_image(SimpleNamespace(channel=first), one)
        await cog.refresh_match_image(SimpleNamespace(channel=second), two)

        self.assertEqual(first.message.edits, 1)
        self.assertEqual(second.message.edits, 1)
        self.assertEqual(cog.board_refresh_tasks, {})

    async def test_the_window_reopens(self) -> None:
        cog, game, channel = build_cog(), build_game(), FakeChannel()
        interaction = SimpleNamespace(channel=channel)

        await cog.refresh_match_image(interaction, game)
        # A turn later, well outside the window.
        cog.board_refreshed_at[game.game_id] -= BOARD_REFRESH_INTERVAL + 1
        await cog.refresh_match_image(interaction, game)

        self.assertEqual(channel.message.edits, 2)
        self.assertEqual(cog.board_refresh_tasks, {})

    async def test_a_game_with_no_board_message_is_left_alone(self) -> None:
        cog, channel = build_cog(), FakeChannel()
        game = build_game()
        game.message_id = None

        await cog.refresh_match_image(SimpleNamespace(channel=channel), game)

        self.assertEqual(channel.message.edits, 0)
        self.assertEqual(cog.board_refresh_tasks, {})

    async def test_unloading_drops_a_pending_refresh(self) -> None:
        cog, game, channel = build_cog(), build_game(), FakeChannel()
        interaction = SimpleNamespace(channel=channel)

        await cog.refresh_match_image(interaction, game)
        await cog.refresh_match_image(interaction, game)
        task = cog.board_refresh_tasks[game.game_id]

        await cog.cog_unload()
        await asyncio.gather(task, return_exceptions=True)

        self.assertTrue(task.cancelled())
        # The immediate one, and nothing from the cancelled task.
        self.assertEqual(channel.message.edits, 1)


class GatedMessage(FakeMessage):
    """
    A board message whose edit does not land until the test lets it,
    which is what a real one is like: drawing and uploading a 2200px
    board is most of a second, and everything the interval is protecting
    happens inside that second.

    `duration` is the other half of the same fact -- an edit that takes
    a measurable time to land rather than one held open indefinitely.
    """

    def __init__(self, duration: float = 0.0) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.duration = duration
        self.in_flight = 0
        self.most_in_flight = 0

    async def edit(self, **fields):
        self.in_flight += 1
        self.most_in_flight = max(self.most_in_flight, self.in_flight)
        self.started.set()
        await self.release.wait()
        if self.duration:
            await asyncio.sleep(self.duration)
        self.in_flight -= 1
        return await super().edit(**fields)


class WriteInFlightTests(unittest.IsolatedAsyncioTestCase):
    """
    What happens to a refresh asked for while the board is being
    written. The interval alone answered this wrongly in both
    directions -- it could drop the request, and it could let a second
    edit into the air alongside the first.
    """

    def build(self):
        cog, game, channel = build_cog(), build_game(), FakeChannel()
        channel.message = GatedMessage()
        return cog, game, channel, SimpleNamespace(channel=channel)

    async def test_a_request_during_a_write_is_not_dropped(self) -> None:
        # A trailing pass puts up a board it drew before this request
        # arrived, so it does not stand in for it. This used to be lost:
        # the pass was still registered in `board_refresh_tasks`, so the
        # request scheduled nothing, and the board kept a state the
        # click had already moved past until somebody clicked again.
        cog, game, channel, interaction = self.build()
        message = channel.message

        with mock.patch("cogs.d12ball.asyncio.sleep", new=mock.AsyncMock()):
            # The immediate write, straight through.
            message.release.set()
            await cog.refresh_match_image(interaction, game)
            message.release.clear()
            message.started.clear()

            # A second request in the same window, which becomes the
            # trailing pass -- and hangs mid-upload.
            await cog.refresh_match_image(interaction, game)
            trailing = cog.board_refresh_tasks[game.game_id]
            await message.started.wait()

            # A third, while that upload is still in the air.
            await cog.refresh_match_image(interaction, game)

            message.release.set()
            await trailing

        self.assertEqual(message.edits, 3)

    async def test_two_writes_are_never_in_the_air_at_once(self) -> None:
        # An upload slower than the window -- which a 2200px board on a
        # bad connection is -- used to let the trailing pass start while
        # the immediate write was still going. Two PATCHes in the same
        # instant is the one thing the interval cannot space out, and
        # every 429 in three sessions of play was a PATCH on this
        # message.
        cog, game, channel, interaction = self.build()
        message, real_sleep = channel.message, asyncio.sleep

        with mock.patch("cogs.d12ball.asyncio.sleep", new=mock.AsyncMock()):
            writing = asyncio.create_task(
                cog.refresh_match_image(interaction, game),
            )
            await message.started.wait()

            await cog.refresh_match_image(interaction, game)
            trailing = cog.board_refresh_tasks[game.game_id]

            # The trailing pass's window is up (its sleep is mocked), so
            # this is where it would join the write already in flight.
            for _ in range(4):
                await real_sleep(0)

            self.assertEqual(message.most_in_flight, 1)

            message.release.set()
            await writing
            await trailing

        self.assertEqual(message.most_in_flight, 1)

    async def test_a_write_being_retried_does_not_open_the_window(self) -> None:
        # The amplifier, and the shape of the third batch of warnings.
        # discord.py handles a 429 *inside* the single await this code
        # makes: it sleeps and retries up to five times, so one throttled
        # PATCH can sit in flight for twenty-odd seconds. The lock keeps
        # a second write from joining it -- but the trailing pass's own
        # wait runs alongside that write rather than after it, so when
        # the lock finally frees the wait is already spent and the next
        # write goes out in the same instant, into the bucket that was
        # refusing the last one.
        #
        # So the window is measured from when a write *lands*: however
        # long Discord holds one, the next is still an interval behind
        # it. Real sleeps and a short interval here, because what is
        # being asserted is the spacing itself.
        cog, game, channel, interaction = self.build()
        message = channel.message
        interval = 0.3

        with mock.patch("cogs.d12ball.BOARD_REFRESH_INTERVAL", interval):
            writing = asyncio.create_task(
                cog.refresh_match_image(interaction, game),
            )
            await message.started.wait()
            message.started.clear()

            # Refreshes keep arriving while Discord refuses that PATCH.
            for _ in range(4):
                await cog.refresh_match_image(interaction, game)
            await asyncio.sleep(interval * 4)

            # None of them went out alongside it, or behind it.
            self.assertEqual(message.edits, 0)

            message.release.set()
            await writing
            landed = time.monotonic()

            await message.started.wait()
            gap = time.monotonic() - landed

            await asyncio.gather(*cog.board_refresh_tasks.values())

        # The state that arrived mid-retry still reaches the message,
        # a full window after the write it was queued behind landed.
        self.assertEqual(message.most_in_flight, 1)
        self.assertGreaterEqual(gap, interval)

    async def test_a_slow_write_still_spaces_the_next_one(self) -> None:
        # The same hole without a 429 in it. A board is nearly a
        # megabyte of PNG, so the write is seconds long on an ordinary
        # connection -- and timed from when it was *sent*, an interval
        # of six seconds spent on a four-second upload spaces the next
        # write by two. Timed from when it lands, six means six.
        cog, game, channel, interaction = self.build()
        interval = 0.3
        # An upload that takes longer than the window it is spending.
        channel.message = GatedMessage(duration=interval * 2)
        message = channel.message
        message.release.set()

        with mock.patch("cogs.d12ball.BOARD_REFRESH_INTERVAL", interval):
            await cog.refresh_match_image(interaction, game)
            landed = time.monotonic()

            # Started rather than awaited: what is being timed is when
            # the next write reaches the message, not when it lands.
            message.started.clear()
            pending = asyncio.create_task(
                cog.refresh_match_image(interaction, game),
            )
            await message.started.wait()
            gap = time.monotonic() - landed

            await pending
            await asyncio.gather(*cog.board_refresh_tasks.values())

        self.assertGreaterEqual(gap, interval)


class UnchangedBoardTests(unittest.IsolatedAsyncioTestCase):
    """
    A board that would come out byte-for-byte identical is not worth
    two requests out of a bucket of five. The render is deterministic,
    so equality of the bytes is the whole test.
    """

    def build(self):
        cog = build_cog()
        cog.render_match_png = mock.AsyncMock(return_value=b"same board")
        game, channel = build_game(), FakeChannel()
        return cog, game, channel, SimpleNamespace(channel=channel)

    async def test_an_unchanged_board_is_not_written(self) -> None:
        cog, game, channel, interaction = self.build()

        await cog.refresh_match_image(interaction, game)
        self.assertEqual(channel.message.edits, 1)

        # A later turn, window wide open, but nothing has moved.
        cog.board_refreshed_at[game.game_id] -= BOARD_REFRESH_INTERVAL + 1
        await cog.refresh_match_image(interaction, game)

        self.assertEqual(channel.message.edits, 1)

    async def test_a_changed_board_is_written(self) -> None:
        cog, game, channel, interaction = self.build()

        await cog.refresh_match_image(interaction, game)
        cog.render_match_png.return_value = b"a meeple moved"
        cog.board_refreshed_at[game.game_id] -= BOARD_REFRESH_INTERVAL + 1
        await cog.refresh_match_image(interaction, game)

        self.assertEqual(channel.message.edits, 2)

    async def test_a_failed_write_is_not_remembered(self) -> None:
        # Otherwise the board Discord rejected would be treated as the
        # one on the message, and the next refresh would skip the fix.
        cog, game, channel, interaction = self.build()
        channel.message.edit = mock.AsyncMock(
            side_effect=discord.HTTPException(
                SimpleNamespace(status=500, reason="nope"), "nope",
            ),
        )

        await cog.refresh_match_image(interaction, game)

        self.assertNotIn(game.game_id, cog.board_png_digests)

    async def test_the_first_refresh_after_a_restart_still_writes(self) -> None:
        # Nothing records what is on the message across a restart, and
        # assuming it matches would leave a stale board up until the
        # next thing that moved.
        cog, game, channel, interaction = self.build()

        await cog.refresh_match_image(interaction, game)

        self.assertEqual(channel.message.edits, 1)


def refused() -> discord.HTTPException:
    """What discord.py raises once it has given up on a 429."""
    return discord.HTTPException(
        SimpleNamespace(status=429, reason="Too Many Requests"),
        "rate limited",
    )


class RefusedWriteBackoffTests(unittest.IsolatedAsyncioTestCase):
    """
    What happens when the budget turns out to be wrong.

    A refused write does not record its digest, so the next refresh
    redraws the same board and asks again. With a fixed interval that
    is a loop with no exit: one logged session spent three quarters of
    an hour asking every six seconds and being refused every time, 61
    uploads, and a restart in the middle of it changed nothing. So a
    refusal widens that game's window until a write lands.
    """

    def setUp(self) -> None:
        # The refusal is announced at WARNING, which is the point of
        # it -- see test_a_refusal_is_announced. A handler of its own
        # keeps logging's last-resort one from printing a run of them
        # through the test output, and leaves assertLogs working.
        # Read off the module rather than named: the cog shares the
        # helpers' logger rather than owning one.
        logger = logging.getLogger(LOGGER.name)
        handler = logging.NullHandler()
        logger.addHandler(handler)
        self.addCleanup(logger.removeHandler, handler)

    def build(self, error=None):
        cog, game, channel = build_cog(), build_game(), FakeChannel()
        if error is not None:
            channel.message.edit = mock.AsyncMock(side_effect=error)
        return cog, game, channel, SimpleNamespace(channel=channel)

    async def test_a_refusal_is_announced(self) -> None:
        # A run of `discord.http` 429s names a channel and a message
        # and nothing else; this is the line that ties one to a game
        # without anybody having to look an id up.
        cog, game, _, interaction = self.build(error=refused())

        with self.assertLogs(LOGGER.name, level="WARNING") as caught:
            await cog.refresh_match_image(interaction, game)

        self.assertIn(game.game_id, caught.output[0])

    async def test_a_settled_board_waits_the_ordinary_interval(self) -> None:
        cog, game, _, _ = self.build()

        self.assertEqual(
            cog.board_refresh_interval(game), BOARD_REFRESH_INTERVAL,
        )

    async def test_each_refusal_doubles_the_window(self) -> None:
        cog, game, channel, interaction = self.build(error=refused())

        widths = []
        for _ in range(3):
            await cog.refresh_match_image(interaction, game)
            widths.append(cog.board_refresh_interval(game))
            # Let the next one through the window rather than the
            # backoff, so what is being measured is the backoff alone.
            cog.board_refreshed_at[game.game_id] -= widths[-1] + 1

        self.assertEqual(widths, [
            BOARD_REFRESH_INTERVAL * 2,
            BOARD_REFRESH_INTERVAL * 4,
            BOARD_REFRESH_INTERVAL * 8,
        ])

    async def test_the_backoff_has_a_ceiling(self) -> None:
        cog, game, _, _ = self.build()
        cog.board_writes_refused[game.game_id] = 40

        self.assertEqual(
            cog.board_refresh_interval(game), BOARD_REFRESH_BACKOFF_CEILING,
        )

    async def test_a_write_that_lands_clears_the_backoff(self) -> None:
        cog, game, channel, interaction = self.build(error=refused())

        await cog.refresh_match_image(interaction, game)
        self.assertEqual(cog.board_writes_refused[game.game_id], 1)

        # Discord lets the next one through.
        channel.message = FakeMessage()
        cog.board_refreshed_at[game.game_id] -= (
            cog.board_refresh_interval(game) + 1
        )
        await cog.refresh_match_image(interaction, game)

        self.assertNotIn(game.game_id, cog.board_writes_refused)
        self.assertEqual(
            cog.board_refresh_interval(game), BOARD_REFRESH_INTERVAL,
        )

    async def test_the_widened_window_actually_holds_a_refresh_back(
        self,
    ) -> None:
        # The counter is only worth having if the gate reads it.
        cog, game, channel, interaction = self.build(error=refused())

        await cog.refresh_match_image(interaction, game)
        self.assertEqual(channel.message.edit.await_count, 1)

        # Far enough past the ordinary interval to have been let
        # through before, and nowhere near the backed-off one.
        cog.board_refreshed_at[game.game_id] -= BOARD_REFRESH_INTERVAL + 1
        await cog.refresh_match_image(interaction, game)

        self.assertEqual(channel.message.edit.await_count, 1)

    async def test_other_failures_do_not_back_off(self) -> None:
        # A 404 or a dropped connection is a one-off, and the next
        # window is the right time to try again. Only a refusal says
        # that the next window is what is too soon.
        cog, game, _, interaction = self.build(
            error=discord.HTTPException(
                SimpleNamespace(status=500, reason="nope"), "nope",
            ),
        )

        await cog.refresh_match_image(interaction, game)

        self.assertEqual(cog.board_writes_refused, {})


def build_assigned_game(game_id: str = "g") -> SimpleNamespace:
    """A game past the home/visiting choice, so the board carries a link."""
    game = build_game(game_id)
    game.home_and_visiting_selected = True
    return game


def link_urls(fields: dict) -> list:
    """The link buttons an edit put on the message, or None for 'left alone'."""
    view = fields.get("view", discord.utils.MISSING)

    if view is discord.utils.MISSING:
        return None

    return [
        item.url for item in view.children
        if getattr(item, "url", None) is not None
    ]


class FullImageLinkTests(unittest.IsolatedAsyncioTestCase):
    """
    What the full-image link costs, which used to be an edit per board.

    Its URL only exists once the upload has landed, so re-cutting it is
    always a second edit -- and the upload has already killed the link
    the message was carrying, so the choice is two edits or no link,
    not one edit or two. An interim write takes the option the bucket
    can afford: strip the dead link in the edit it is already paying
    for, and let the settling write put a live one back once.
    """

    def build(self):
        cog, game, channel = build_cog(), build_assigned_game(), FakeChannel()
        return cog, game, channel, SimpleNamespace(channel=channel)

    async def test_an_interim_write_is_one_edit_without_the_link(self) -> None:
        cog, game, channel, interaction = self.build()

        with mock.patch("cogs.d12ball.asyncio.sleep", new=mock.AsyncMock()):
            await cog.refresh_match_image(interaction, game)

            self.assertEqual(channel.message.edits, 1)
            self.assertEqual(link_urls(channel.message.fields[0]), [])
            # Held against the upload it was read off, for the
            # settling write to spend.
            self.assertEqual(cog.board_link_owed[game.game_id], ATTACHMENT_URL)

            await asyncio.gather(*cog.board_refresh_tasks.values())

    async def test_the_settling_write_puts_the_link_back(self) -> None:
        cog, game, channel, interaction = self.build()

        with mock.patch("cogs.d12ball.asyncio.sleep", new=mock.AsyncMock()):
            await cog.refresh_match_image(interaction, game)
            await asyncio.gather(*cog.board_refresh_tasks.values())

        # The interim write, then the settling board and its link.
        self.assertEqual(channel.message.edits, 3)
        self.assertEqual(link_urls(channel.message.fields[-1]), [ATTACHMENT_URL])
        self.assertNotIn(game.game_id, cog.board_link_owed)

    async def test_an_unchanged_board_still_pays_its_link(self) -> None:
        # The common case: the click's last step moved nothing, so the
        # board the interim write stripped is the final one. The link
        # still has to go back on it, and that is the only request.
        cog, game, channel, interaction = self.build()
        cog.render_match_png = mock.AsyncMock(return_value=b"one board")

        with mock.patch("cogs.d12ball.asyncio.sleep", new=mock.AsyncMock()):
            await cog.refresh_match_image(interaction, game)
            await asyncio.gather(*cog.board_refresh_tasks.values())

        self.assertEqual(channel.message.edits, 2)
        self.assertEqual(link_urls(channel.message.fields[-1]), [ATTACHMENT_URL])
        self.assertEqual(list(channel.message.fields[-1]), ["view"])
        self.assertNotIn(game.game_id, cog.board_link_owed)

    async def test_a_burst_costs_three_edits(self) -> None:
        # The whole point of the split. A turn's refreshes used to be
        # two writes at two edits each; they are now one edit, then the
        # settling write and its link.
        cog, game, channel, interaction = self.build()

        with mock.patch("cogs.d12ball.asyncio.sleep", new=mock.AsyncMock()):
            for _ in range(8):
                await cog.refresh_match_image(interaction, game)
            await asyncio.gather(*cog.board_refresh_tasks.values())

        self.assertEqual(channel.message.edits, 3)

    async def test_a_settled_board_owes_nothing(self) -> None:
        # Nothing stripped a link, so the settling pass has nothing to
        # put back and spends no request finding that out.
        cog, game, channel, interaction = self.build()

        await cog.settle_board_link(channel, game)

        self.assertEqual(channel.message.edits, 0)

    async def test_a_board_with_no_link_on_it_owes_nothing(self) -> None:
        # Before the home/visiting choice this message is still the
        # setup prompt: its buttons are live, it has no link to go
        # stale, and its view must not be replaced.
        cog, game, channel = build_cog(), build_game(), FakeChannel()

        await cog.refresh_match_image(SimpleNamespace(channel=channel), game)

        self.assertEqual(link_urls(channel.message.fields[0]), None)
        self.assertEqual(cog.board_link_owed, {})
        self.assertEqual(cog.board_refresh_tasks, {})

    async def test_a_failed_write_owes_nothing(self) -> None:
        cog, game, channel, interaction = self.build()
        channel.message.edit = mock.AsyncMock(
            side_effect=discord.HTTPException(
                SimpleNamespace(status=500, reason="nope"), "nope",
            ),
        )

        await cog.refresh_match_image(interaction, game)

        self.assertEqual(cog.board_link_owed, {})


if __name__ == "__main__":
    unittest.main()

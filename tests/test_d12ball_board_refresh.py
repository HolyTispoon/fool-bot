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
import unittest
from types import SimpleNamespace
from unittest import mock

import discord

from cogs.d12ball import BOARD_REFRESH_INTERVAL, D12Ball


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

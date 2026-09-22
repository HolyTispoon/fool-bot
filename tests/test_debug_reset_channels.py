"""
/debug reset_channels, and how hard it leans on Discord.

Deleting a channel sits in the channel-modification bucket -- two per
ten minutes, the tightest limit Discord documents -- so a reset of more
than a couple of channels is mostly waiting. discord.py does the
waiting for an ordinary 429 itself; what reaches this command is a
failure it gave up on, or a Cloudflare ban, and the retry loop used to
hit both again immediately, three times per channel.
"""

import itertools
import unittest
from types import SimpleNamespace
from unittest import mock

import discord

from cogs.debug import CHANNEL_DELETE_RETRY_DELAYS, Debug


def build_response(status: int) -> mock.Mock:
    return mock.Mock(status=status, reason="")


def build_channel(name: str, failures: int = 0) -> mock.Mock:
    """
    A PBD text channel whose delete fails `failures` times before it
    works. Specced, so the command's isinstance check accepts it.
    """
    channel = mock.Mock(spec=discord.TextChannel)
    channel.name = name
    channel.category = None
    channel.id = abs(hash(name))

    attempts = itertools.count(1)

    async def delete(reason: str = "") -> None:
        del reason
        if next(attempts) <= failures:
            raise discord.HTTPException(build_response(500), "nope")

    channel.delete = mock.AsyncMock(side_effect=delete)

    return channel


class ResetChannelsBackoffTests(unittest.IsolatedAsyncioTestCase):
    def build_interaction(self, channels: list) -> SimpleNamespace:
        guild = SimpleNamespace(
            id=1,
            channels=channels,
            fetch_channels=mock.AsyncMock(return_value=channels),
        )
        return SimpleNamespace(
            guild=guild,
            user="tester",
            response=SimpleNamespace(
                send_message=mock.AsyncMock(),
                defer=mock.AsyncMock(),
            ),
            followup=SimpleNamespace(send=mock.AsyncMock()),
        )

    async def reset(self, channels: list):
        cog = Debug(mock.Mock())
        d12ball = SimpleNamespace(
            games={},
            service=SimpleNamespace(next_game_number=mock.Mock(return_value=1)),
        )
        cog.bot.get_cog = mock.Mock(return_value=d12ball)
        interaction = self.build_interaction(channels)

        with (
            mock.patch("cogs.debug.save_games"),
            mock.patch("asyncio.sleep", mock.AsyncMock()) as slept,
        ):
            await Debug.reset_channels.callback(cog, interaction, "confirm")

        return interaction, slept

    async def test_defers_before_any_check_so_nothing_ever_races_the_ack(
        self,
    ) -> None:
        """
        Discord invalidates an un-acknowledged interaction after three
        seconds -- see the identical regression test on
        export_archived_games, which hit this live. Every refusal here
        must answer through the followup webhook instead of a fresh
        `response.send_message`.
        """
        cog = Debug(mock.Mock())
        cog.bot.get_cog = mock.Mock(return_value=None)
        interaction = self.build_interaction([])

        await Debug.reset_channels.callback(cog, interaction, "")

        interaction.response.defer.assert_awaited_once()
        interaction.response.send_message.assert_not_awaited()

    async def test_a_clean_delete_never_sleeps(self) -> None:
        channels = [
            build_channel("d12ball-pbd1"), build_channel("d12ball-pbd2"),
        ]

        interaction, slept = await self.reset(channels)

        self.assertEqual([c.delete.await_count for c in channels], [1, 1])
        slept.assert_not_awaited()
        self.assertIn(
            "Deleted 2 PBD channel(s)",
            interaction.followup.send.await_args.args[0],
        )

    async def test_a_refused_delete_backs_off_before_retrying(self) -> None:
        channels = [build_channel("d12ball-pbd1", failures=1)]

        _, slept = await self.reset(channels)

        self.assertEqual(channels[0].delete.await_count, 2)
        self.assertEqual(
            [call.args[0] for call in slept.await_args_list],
            [CHANNEL_DELETE_RETRY_DELAYS[0]],
        )

    async def test_the_backoff_grows_and_then_gives_up(self) -> None:
        channels = [build_channel("d12ball-pbd1", failures=99)]

        interaction, slept = await self.reset(channels)

        self.assertEqual(
            channels[0].delete.await_count,
            len(CHANNEL_DELETE_RETRY_DELAYS) + 1,
        )
        self.assertEqual(
            [call.args[0] for call in slept.await_args_list],
            list(CHANNEL_DELETE_RETRY_DELAYS),
        )
        self.assertIn(
            "could not delete these channels",
            interaction.followup.send.await_args.args[0],
        )

    async def test_the_delays_only_ever_grow(self) -> None:
        self.assertEqual(
            list(CHANNEL_DELETE_RETRY_DELAYS),
            sorted(CHANNEL_DELETE_RETRY_DELAYS),
        )
        self.assertTrue(all(d > 0 for d in CHANNEL_DELETE_RETRY_DELAYS))


if __name__ == "__main__":
    unittest.main()

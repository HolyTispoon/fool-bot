import asyncio
import unittest
from types import SimpleNamespace
from unittest import mock

from cogs.channel_stats import (
    MAX_ROWS,
    ChannelStats,
    format_stats,
    tally_messages,
)


def author(user_id, name, bot=False):
    return SimpleNamespace(id=user_id, display_name=name, bot=bot)


def message(who, content):
    return SimpleNamespace(author=who, content=content)


class FakeChannel:
    name = "general"

    def __init__(self, messages):
        self.messages = messages

    async def history(self, limit=None):
        for item in self.messages:
            yield item


def interaction_in(channel):
    return SimpleNamespace(
        channel=channel,
        response=SimpleNamespace(defer=mock.AsyncMock()),
        followup=SimpleNamespace(send=mock.AsyncMock()),
    )


class TallyTests(unittest.TestCase):
    def test_counts_messages_and_words_per_author_most_messages_first(self):
        ann, bob = author(1, "ann"), author(2, "bob")
        tallies = tally_messages([
            message(bob, "one two three"),
            message(ann, "hi"),
            message(ann, "  hello   there  "),
            message(ann, ""),
        ])

        self.assertEqual(
            [(t.name, t.messages, t.words) for t in tallies],
            [("ann", 3, 3), ("bob", 1, 3)],
        )

    def test_one_row_per_user_id_whatever_their_name(self):
        tallies = tally_messages([
            message(author(1, "newname"), "a"),
            message(author(1, "oldname"), "b"),
        ])

        self.assertEqual(len(tallies), 1)
        self.assertEqual(tallies[0].messages, 2)

    def test_format_shows_totals_and_shares(self):
        text = format_stats("general", tally_messages([
            message(author(1, "ann"), "a b c"),
            message(author(2, "bob"), "d"),
        ]))

        self.assertIn("2 messages, 4 words from 2 users", text)
        self.assertIn("50.0%", text)
        self.assertIn("75.0%", text)

    def test_rows_past_the_cap_are_summed_and_fit_one_message(self):
        messages = [
            message(author(n, f"user_with_a_long_name_{n}"), "word " * n)
            for n in range(1, 61)
        ]
        text = format_stats("general", tally_messages(messages))

        self.assertIn(f"{60 - MAX_ROWS} others", text)
        self.assertLessEqual(len(text), 2000)

    def test_an_empty_channel_says_so(self):
        self.assertEqual(
            format_stats("general", []),
            "#general has no messages to count.",
        )


class CommandTests(unittest.TestCase):
    def run_command(self, channel, **options):
        cog = ChannelStats(bot=None)
        interaction = interaction_in(channel)
        asyncio.run(cog.channel_stats.callback(cog, interaction, **options))
        return interaction

    def test_ephemeral_by_default_and_skips_bots(self):
        interaction = self.run_command(FakeChannel([
            message(author(1, "ann"), "hi"),
            message(author(9, "fool-bot", bot=True), "beep"),
        ]))

        interaction.response.defer.assert_awaited_once_with(
            ephemeral=True, thinking=True,
        )
        text = interaction.followup.send.await_args.args[0]
        self.assertTrue(interaction.followup.send.await_args.kwargs["ephemeral"])
        self.assertIn("1 messages", text)
        self.assertNotIn("fool-bot", text)

    def test_public_and_bots_on_request(self):
        interaction = self.run_command(
            FakeChannel([
                message(author(1, "ann"), "hi"),
                message(author(9, "fool-bot", bot=True), "beep"),
            ]),
            public=True,
            include_bots=True,
        )

        interaction.response.defer.assert_awaited_once_with(
            ephemeral=False, thinking=True,
        )
        text = interaction.followup.send.await_args.args[0]
        self.assertFalse(interaction.followup.send.await_args.kwargs["ephemeral"])
        self.assertIn("fool-bot", text)


if __name__ == "__main__":
    unittest.main()

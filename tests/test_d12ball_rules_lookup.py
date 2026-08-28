import asyncio
import unittest
from types import SimpleNamespace
from unittest import mock

import discord

from cogs.d12ball import D12Ball
from d12ball.rules_doc import (
    DISCORD_MESSAGE_LIMIT,
    chunk_for_discord,
    for_discord,
    load_rules_document,
    parse_rules_document,
    slugify_heading,
)


SAMPLE = """# D12 Ball -- living rules

Intro text.

---

## Contents

- [Overview](#overview)

## Overview

Two coaches. See [the turn](#the-turn).

## Maneuver

Most turns are maneuvers.

### 3. Who wins

Rock, paper, scissors.

## Ball speed

Starts at 0.
"""


class RulesDocumentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.document = parse_rules_document(SAMPLE)

    def test_title_and_sections(self) -> None:
        self.assertEqual(self.document.title, "D12 Ball -- living rules")
        self.assertEqual(
            [section.slug for section in self.document.sections],
            ["overview", "maneuver", "3-who-wins", "ball-speed"],
        )

    def test_contents_is_not_a_section(self) -> None:
        # It is a list of links to everything below it, so offering it
        # as a search result answers nothing.
        self.assertIsNone(self.document.find("Contents"))
        self.assertNotIn(
            "Contents", [section.title for section in self.document.sections]
        )

    def test_a_section_carries_its_subsections(self) -> None:
        maneuver = self.document.find("Maneuver")
        self.assertIsNotNone(maneuver)
        self.assertIn("Most turns are maneuvers.", maneuver.text)
        self.assertIn("### 3. Who wins", maneuver.text)
        self.assertNotIn("Ball speed", maneuver.text)

    def test_a_subsection_is_labelled_by_its_parent(self) -> None:
        who_wins = self.document.find("3-who-wins")
        self.assertEqual(who_wins.label, "Maneuver › 3. Who wins")
        self.assertEqual(who_wins.ancestors, ("Maneuver",))

    def test_a_top_level_section_has_no_ancestors(self) -> None:
        # Every earlier heading used to be read as an ancestor, which
        # labelled "Ball speed" as sitting under the section above it.
        self.assertEqual(self.document.find("Ball speed").label, "Ball speed")

    def test_horizontal_rules_do_not_trail_a_section(self) -> None:
        self.assertFalse(self.document.find("Overview").text.endswith("---"))

    def test_find_accepts_slug_label_and_heading(self) -> None:
        for query in (
            "3-who-wins",
            "#3-who-wins",
            "3. Who wins",
            "maneuver › 3. who wins",
            "who wins",
        ):
            with self.subTest(query=query):
                self.assertEqual(self.document.find(query).slug, "3-who-wins")

    def test_find_refuses_what_it_cannot_pin_down(self) -> None:
        self.assertIsNone(self.document.find("offside"))
        self.assertIsNone(self.document.find(""))

    def test_search_puts_headings_before_body_matches(self) -> None:
        results = [section.slug for section in self.document.search("maneuver")]
        self.assertEqual(results[0], "maneuver")
        self.assertIn("3-who-wins", results)

    def test_search_finds_words_that_are_in_no_heading(self) -> None:
        # And offers the subsection ahead of the parent that carries it.
        self.assertEqual(
            [section.slug for section in self.document.search("scissors")],
            ["3-who-wins", "maneuver"],
        )

    def test_best_match_answers_words_on_one_branch(self) -> None:
        # "scissors" is in the subsection and, through it, in the
        # parent that carries it: one rule, read at two depths.
        self.assertEqual(self.document.best_match("scissors").slug, "3-who-wins")

    def test_best_match_refuses_words_spread_across_the_rules(self) -> None:
        # "turn" is in Overview and in Maneuver, which are not each
        # other's: that is a choice for the coach, not an answer.
        self.assertIsNone(self.document.best_match("turn"))

    def test_search_with_nothing_typed_offers_the_document(self) -> None:
        self.assertEqual(len(self.document.search("")), 4)

    def test_search_is_capped_for_discords_25_choices(self) -> None:
        self.assertLessEqual(len(self.document.search("", limit=2)), 2)


class DiscordMarkdownTests(unittest.TestCase):
    def test_local_links_lose_their_syntax(self) -> None:
        # Discord renders neither an anchor nor a relative path, and
        # shows the raw brackets instead.
        self.assertEqual(
            for_discord("see [the turn](#the-turn) and [log](rules-log.md)"),
            "see the turn and log",
        )

    def test_urls_are_left_alone(self) -> None:
        link = "[Notion](https://example.com/rules)"
        self.assertEqual(for_discord(link), link)

    def test_slugs_match_githubs_anchors(self) -> None:
        self.assertEqual(
            slugify_heading("The clock, halftime and full time"),
            "the-clock-halftime-and-full-time",
        )
        self.assertEqual(
            slugify_heading("4. Skill test, when they tie"),
            "4-skill-test-when-they-tie",
        )


class ChunkingTests(unittest.TestCase):
    def test_a_short_section_is_one_message(self) -> None:
        self.assertEqual(
            chunk_for_discord("## Ball speed\n\nStarts at 0."),
            ["## Ball speed\n\nStarts at 0."],
        )

    def test_each_top_level_section_starts_a_message(self) -> None:
        chunks = chunk_for_discord(SAMPLE)
        for chunk in chunks[1:]:
            self.assertTrue(chunk.startswith("##"), chunk[:40])

    def test_a_table_is_not_split_across_messages(self) -> None:
        # Half a table renders as neither a table nor prose, so a break
        # is taken at the blank line before it instead.
        table = "\n".join(f"| row {index} | value |" for index in range(20))
        chunks = chunk_for_discord(
            f"## Terms\n\n{'Before. ' * 30}\n\n{table}\n\nAfter.", limit=400,
        )
        holding = [chunk for chunk in chunks if "row 0" in chunk]
        self.assertEqual(len(holding), 1)
        self.assertEqual(holding[0].count("| row"), 20)

    def test_an_oversized_block_is_split_by_lines(self) -> None:
        block = "\n".join(f"- bullet number {index}" for index in range(200))
        chunks = chunk_for_discord(block)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), DISCORD_MESSAGE_LIMIT)
            self.assertTrue(chunk.startswith("- bullet"))

    def test_a_single_line_longer_than_a_message_is_cut(self) -> None:
        chunks = chunk_for_discord("x" * 4500)
        self.assertEqual([len(chunk) for chunk in chunks], [2000, 2000, 500])


class LivingRulesFileTests(unittest.TestCase):
    """The real document, since it is what the commands post."""

    def setUp(self) -> None:
        self.document = load_rules_document()

    def test_it_parses_into_sections(self) -> None:
        slugs = [section.slug for section in self.document.sections]
        self.assertIn("choosing-the-handler", slugs)
        self.assertIn("coaching-choice", slugs)
        self.assertEqual(len(slugs), len(set(slugs)), "duplicate anchors")

    def test_every_section_fits_discords_choice_limits(self) -> None:
        for section in self.document.sections:
            self.assertLessEqual(len(section.slug), 100, section.slug)
            self.assertTrue(section.text.strip())

    def test_the_whole_document_chunks_into_postable_messages(self) -> None:
        chunks = chunk_for_discord(self.document.text)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), DISCORD_MESSAGE_LIMIT)

    def test_chunking_loses_no_words(self) -> None:
        chunks = chunk_for_discord(self.document.text)
        rebuilt = "".join("".join(chunk.split()) for chunk in chunks)
        self.assertEqual(
            rebuilt, "".join(for_discord(self.document.text).split()),
        )

    def test_every_section_can_be_found_by_its_own_label(self) -> None:
        for section in self.document.sections:
            with self.subTest(section=section.label):
                self.assertEqual(
                    self.document.find(section.label).slug, section.slug,
                )


class RulesSearchAutocompleteTests(unittest.TestCase):
    """What the section: field offers, against Discord's own limits."""

    def setUp(self) -> None:
        self.cog = object.__new__(D12Ball)
        self.document = load_rules_document()

    def complete(self, current: str) -> list:
        return asyncio.run(
            self.cog.rules_search_section_autocomplete(None, current)
        )

    def test_nothing_typed_offers_the_first_headings(self) -> None:
        choices = self.complete("")
        self.assertEqual(len(choices), 25)
        self.assertEqual(choices[0].value, self.document.sections[0].slug)

    def test_choices_stay_inside_discords_limits(self) -> None:
        for current in ("", "the", "pass", "coach", "exhaust"):
            with self.subTest(current=current):
                choices = self.complete(current)
                self.assertLessEqual(len(choices), 25)
                for choice in choices:
                    self.assertLessEqual(len(choice.name), 100)
                    self.assertLessEqual(len(choice.value), 100)

    def test_what_it_offers_is_what_the_command_can_find(self) -> None:
        for choice in self.complete("pass"):
            with self.subTest(choice=choice.name):
                self.assertIsNotNone(self.document.find(choice.value))

    def test_it_offers_nothing_for_words_the_rules_do_not_use(self) -> None:
        self.assertEqual(self.complete("offside"), [])


class FakeResponse:
    """The interaction's first, and only, answer."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, bool]] = []

    def is_done(self) -> bool:
        return bool(self.sent)

    async def send_message(self, content: str, ephemeral: bool = False) -> None:
        self.sent.append((content, ephemeral))


class FakeFollowup:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, content: str, ephemeral: bool = False) -> None:
        self.sent.append(content)


class FakeThread:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, content: str) -> None:
        self.sent.append(content)


class FakeAnchorMessage:
    def __init__(self, thread=None, error: Exception = None) -> None:
        self.thread = thread
        self.error = error
        self.thread_name = None

    async def create_thread(self, name: str, **_) -> FakeThread:
        if self.error is not None:
            raise self.error
        self.thread_name = name
        return self.thread


def build_interaction(channel, anchor=None) -> SimpleNamespace:
    return SimpleNamespace(
        channel=channel,
        channel_id=99,
        response=FakeResponse(),
        followup=FakeFollowup(),
        original_response=mock.AsyncMock(return_value=anchor),
    )


class RulesSearchCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cog = object.__new__(D12Ball)
        self.document = load_rules_document()

    def run_search(self, section: str) -> SimpleNamespace:
        interaction = build_interaction(SimpleNamespace(name="pbd1"))
        asyncio.run(
            D12Ball.rules_search.callback(self.cog, interaction, section)
        )
        return interaction

    def test_the_section_is_the_response_not_a_deferral(self) -> None:
        interaction = self.run_search("low-pass")
        content, ephemeral = interaction.response.sent[0]
        self.assertTrue(content.startswith("### Low Pass"))
        self.assertFalse(ephemeral)

    def test_a_long_section_continues_in_followups(self) -> None:
        interaction = self.run_search("maneuvers")
        posted = [interaction.response.sent[0][0]] + interaction.followup.sent
        self.assertGreater(len(posted), 1)
        self.assertEqual(
            posted, chunk_for_discord(self.document.find("maneuvers").text)
        )

    def test_words_in_one_section_only_post_that_section(self) -> None:
        # Typed rather than picked, and in no heading at all: only
        # "Winning the shootout" and the section carrying it say this.
        interaction = self.run_search("sudden death")
        self.assertTrue(
            interaction.response.sent[0][0].startswith(
                "### Winning the shootout"
            )
        )

    def test_an_unknown_heading_is_refused_privately(self) -> None:
        interaction = self.run_search("offside trap")
        content, ephemeral = interaction.response.sent[0]
        self.assertIn("No one rules section matches", content)
        self.assertTrue(ephemeral)
        self.assertEqual(interaction.followup.sent, [])

    def test_an_ambiguous_query_suggests_headings(self) -> None:
        interaction = self.run_search("pass")
        content, ephemeral = interaction.response.sent[0]
        self.assertIn("Did you mean", content)
        self.assertIn("Low Pass", content)
        self.assertTrue(ephemeral)


class RulesFullCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cog = object.__new__(D12Ball)
        self.chunks = chunk_for_discord(load_rules_document().text)

    def test_the_rules_go_in_a_thread_off_the_reply(self) -> None:
        thread = FakeThread()
        anchor = FakeAnchorMessage(thread=thread)
        interaction = build_interaction(
            SimpleNamespace(name="pbd1"), anchor=anchor,
        )
        asyncio.run(D12Ball.rules_full.callback(self.cog, interaction))

        self.assertEqual(anchor.thread_name, "D12 Ball rules")
        self.assertEqual(thread.sent, self.chunks)
        # The channel itself gets the one message the thread hangs off.
        self.assertEqual(len(interaction.response.sent), 1)

    def test_inside_a_thread_it_posts_where_it_was_run(self) -> None:
        # Threads do not nest, and the command is already in one.
        thread = mock.MagicMock(spec=discord.Thread)
        posted: list[str] = []
        thread.send = mock.AsyncMock(side_effect=lambda text: posted.append(text))
        interaction = build_interaction(thread)
        asyncio.run(D12Ball.rules_full.callback(self.cog, interaction))

        self.assertEqual(posted, self.chunks)
        interaction.original_response.assert_not_awaited()

    def test_a_thread_it_may_not_open_is_reported(self) -> None:
        error = discord.HTTPException(
            SimpleNamespace(status=403, reason="Forbidden"),
            {"code": 50013, "message": "Missing Permissions"},
        )
        anchor = FakeAnchorMessage(error=error)
        interaction = build_interaction(
            SimpleNamespace(name="pbd1"), anchor=anchor,
        )
        with mock.patch("cogs.d12ball.slash_commands.LOGGER") as logger:
            asyncio.run(D12Ball.rules_full.callback(self.cog, interaction))

        self.assertTrue(logger.error.called)
        self.assertIn("could not open a thread", interaction.followup.sent[0])


if __name__ == "__main__":
    unittest.main()

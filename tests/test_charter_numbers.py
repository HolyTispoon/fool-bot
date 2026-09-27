"""
The Charter's numbers in its source -- "The two rulebooks" in
docs/design/rulebooks.md.

`docs/living-rules.md` carries the printed edition's numbers, written by
`scripts/build_rulebooks.py --renumber`. These fail when a Law, a section
or a paragraph has been added, moved or taken out and the file has not
been renumbered since, which is when its numbers and the book's part.
"""

from __future__ import annotations

import re
import unittest

from d12ball import rulebooks
from d12ball.rules_doc import LIVING_RULES_PATH

RENUMBER = "python3 scripts/build_rulebooks.py --renumber"


class TheFileCarriesTheBooksNumbersTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = LIVING_RULES_PATH.read_text(encoding="utf-8")

    def test_the_file_is_renumbered(self) -> None:
        self.assertEqual(
            rulebooks.renumber(self.text), self.text,
            f"docs/living-rules.md is out of step with its numbers: run `{RENUMBER}`",
        )

    def test_every_link_in_the_file_lands_on_a_heading(self) -> None:
        anchors = set(rulebooks.heading_anchors(self.text).values())
        for target in re.findall(r"\]\(#([^)\s]+)\)", self.text):
            with self.subTest(target):
                self.assertIn(target, anchors)


class RenumberTests(unittest.TestCase):
    SOURCE = "\n".join([
        "# Title",
        "",
        "## Contents",
        "",
        "- [Law 1. The game](#the-game)",
        "",
        "## The game",
        "",
        "Straight under the Law.",
        "",
        "### The field",
        "",
        "The field is [the game](#the-game) itself.",
        "",
        "*Note:* never numbered.",
        "",
        "1. first",
        "2. second",
        "   - nested",
        "",
        "| a | b |",
        "| --- | --- |",
        "| 1 | 2 |",
        "",
        "See [Law 1](#the-game) and [the field](#the-field).",
        "",
    ])

    NUMBERED = "\n".join([
        "# Title",
        "",
        "## Contents",
        "",
        "- [Law 1. The game](#1-the-game)",
        "",
        "## 1. The game",
        "",
        "**1.1** Straight under the Law.",
        "",
        "### 1.2 The field",
        "",
        "**1.2.1** The field is [the game](#1-the-game) (1) itself.",
        "",
        "*Note:* never numbered.",
        "",
        "**1.2.2**",
        "",
        "- **a.** first",
        "- **b.** second",
        "   - nested",
        "",
        "**1.2.3**",
        "",
        "| a | b |",
        "| --- | --- |",
        "| 1 | 2 |",
        "",
        "**1.2.4** See [Law 1](#1-the-game) and [the field](#12-the-field) (1.2).",
        "",
    ])

    def test_it_writes_the_numbers_the_book_prints(self) -> None:
        self.assertEqual(rulebooks.renumber(self.SOURCE), self.NUMBERED)

    def test_renumbering_twice_changes_nothing(self) -> None:
        self.assertEqual(rulebooks.renumber(self.NUMBERED), self.NUMBERED)

    def test_unnumber_gives_back_what_the_book_is_built_from(self) -> None:
        # The one thing not given back is an ordered list's markers:
        # lettered, a list's cases are the letters.
        self.assertEqual(
            rulebooks.unnumber(self.NUMBERED),
            self.SOURCE.replace("1. first\n2. second", "- first\n- second"),
        )

    def test_a_stale_number_is_rewritten(self) -> None:
        stale = self.NUMBERED.replace("## 1. The game", "## 4. The game").replace(
            "**1.2.1**", "**9.9.9**",
        )
        self.assertEqual(rulebooks.renumber(stale), self.NUMBERED)

    def test_anchor_moves_follow_a_heading_to_its_new_number(self) -> None:
        moves = rulebooks.anchor_moves(self.SOURCE, self.NUMBERED)
        self.assertEqual(moves["the-field"], "12-the-field")
        inserted = self.NUMBERED.replace("## 1. The game", "## New law\n\nA rule.\n\n## 1. The game")
        moves = rulebooks.anchor_moves(self.NUMBERED, rulebooks.renumber(inserted))
        self.assertEqual(moves["12-the-field"], "22-the-field")


if __name__ == "__main__":
    unittest.main()

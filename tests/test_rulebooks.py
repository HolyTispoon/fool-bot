"""
The two rulebooks: the markdown subset, the Charter's numbering, the
PDF build, and the figures the outlines show -- see "The two rulebooks"
in docs/design/rulebooks.md.

Builds go to a temporary folder; nothing here touches `data/` or
`print/`.
"""

import pathlib
import re
import tempfile
import unittest

from d12ball import rulebook_figures, rulebooks
from d12ball.components import Zone, load_player_catalog
from d12ball.rulebooks import (
    BOOKS,
    OUTLINE_BOOKS,
    Book,
    CodeBlock,
    Heading,
    ImageBlock,
    ListBlock,
    MarkdownError,
    PageBreakBlock,
    Paragraph_,
    QuoteBlock,
    TableBlock,
    build_book,
    inline_markup,
    number_blocks,
    parse_markdown,
)

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
RULEBOOKS_DIR = PROJECT_ROOT / "docs" / "rulebooks"
FIGURES_DIR = RULEBOOKS_DIR / "figures"
IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
LINK_RE = re.compile(r"\]\(#([^)]+)\)")


class MarkdownSubsetTests(unittest.TestCase):
    """`parse_markdown` reads what the books use and refuses the rest."""

    def test_every_block_kind_parses(self) -> None:
        text = (
            "# Title\n\n## Law\n\nA paragraph\nover two lines.\n\n"
            "- one\n  - nested\n- two\n\n1. first\n2. second\n\n"
            "| A | B |\n| --- | ---: |\n| `x|y` | 2 |\n\n"
            "![Caption](figures/x.png)\n\n> quoted\n> words\n\n"
            "```\ncode here\n```\n\n---\n"
        )
        blocks = parse_markdown(text)
        kinds = [type(block) for block in blocks]
        self.assertEqual(kinds, [
            Heading, Heading, Paragraph_, ListBlock, ListBlock, TableBlock,
            ImageBlock, QuoteBlock, CodeBlock, PageBreakBlock,
        ])
        self.assertEqual(blocks[2].text, "A paragraph over two lines.")
        bullets = blocks[3]
        self.assertFalse(bullets.ordered)
        self.assertEqual([item.text for item in bullets.items], ["one", "two"])
        self.assertEqual(bullets.items[0].children[0].items[0].text, "nested")
        self.assertTrue(blocks[4].ordered)
        table = blocks[5]
        self.assertEqual(table.rows, [["A", "B"], ["`x|y`", "2"]])
        self.assertEqual(table.aligns, ["LEFT", "RIGHT"])
        self.assertEqual((blocks[6].path, blocks[6].caption), ("figures/x.png", "Caption"))
        self.assertEqual(blocks[7].text, "quoted words")
        self.assertEqual(blocks[8].text, "code here")

    def test_html_and_an_open_fence_are_refused(self) -> None:
        with self.assertRaises(MarkdownError):
            parse_markdown("<div>no</div>\n")
        with self.assertRaises(MarkdownError):
            parse_markdown("```\nnever closed\n")

    def test_inline_markup_escapes_and_styles(self) -> None:
        self.assertEqual(
            inline_markup("a **bold** *word* `code` & <x>"),
            "a <b>bold</b> <i>word</i> <b>code</b> &amp; &lt;x&gt;",
        )
        self.assertEqual(
            inline_markup("see [the turn](#the-turn)", lambda text, target: f"{text} ({target})"),
            "see the turn (#the-turn)",
        )


class NumberingTests(unittest.TestCase):
    """Law . section . paragraph, the way the Law of Root numbers them."""

    def test_laws_sections_and_paragraphs(self) -> None:
        blocks = parse_markdown(
            "# T\n\n## Contents\n\n- [x](#x)\n\n## Brief\n\nOne.\n\nTwo.\n\n"
            "## Components\n\nLead.\n\n### The field\n\nP1.\n\n- a\n- b\n\n### Range\n\nP2.\n"
        )
        numbering = number_blocks(blocks)
        self.assertEqual(numbering.headings, {
            "brief": "1", "components": "2", "the-field": "2.2", "range": "2.3",
        })
        numbered = [numbering.blocks[i] for i in sorted(numbering.blocks)]
        self.assertEqual(numbered, ["1.1", "1.2", "2.1", "2.2.1", "2.2.2", "2.3.1"])
        contents_list = next(i for i, b in enumerate(blocks) if isinstance(b, ListBlock))
        self.assertNotIn(contents_list, numbering.blocks)

    def test_the_living_rules_number_cleanly(self) -> None:
        """
        The Charter draft is the living rules numbered: the file is
        inside the subset, and every internal link lands on a heading
        the build can turn into a number.
        """
        source = BOOKS["charter"].source
        assert source is not None
        text = source.read_text(encoding="utf-8")
        blocks = parse_markdown(text)
        numbering = number_blocks(blocks)
        headings = {block.slug for block in blocks if isinstance(block, Heading)}
        dangling = sorted(slug for slug in set(LINK_RE.findall(text)) if slug not in headings)
        self.assertEqual(dangling, [], f"links with no heading: {dangling}")
        self.assertEqual(numbering.headings["appendix-a-quick-reference"], "Appendix A")
        self.assertNotIn("how-to-read-this-document", numbering.headings)

    def test_the_charters_numbers_are_the_ones_the_books_cite(self) -> None:
        """
        The Learn to Play cites Laws by number and the outline maps them,
        so the numbers the build hands out are pinned here: a Law added
        or moved changes every citation, and should have to say so.
        """
        source = BOOKS["charter"].source
        assert source is not None
        numbering = number_blocks(parse_markdown(source.read_text(encoding="utf-8")))
        expected = {
            "the-game-in-brief": "1", "components-and-definitions": "2", "the-turn": "4",
            "score-attempt": "5", "maneuvers": "6", "ball-speed": "7", "sending-a-player": "9",
            "contests-for-the-ball": "10", "own-goal": "11", "turnovers": "12", "time-out": "13",
            "coaching-choice": "14", "exhaustion-and-injury": "15", "the-clock": "16",
            "extreme-shootout": "17", "advanced-mode": "18", "gambits": "19", "species-abilities": "20",
            "choosing-the-handler": "4.2", "what-the-defense-adds": "5.3", "the-skill-test": "6.4",
            "high-pass": "6.7", "where-the-ball-comes-to-rest": "10.1",
            "running-back-after-a-steal": "12.4", "resetting-after-a-new-play": "12.5",
            "finishing-a-coaching-choice": "14.8", "the-injury-check": "15.3", "last-possession": "16.3",
        }
        actual = {slug: numbering.headings[slug] for slug in expected}
        self.assertEqual(actual, expected)

    def test_a_note_is_never_numbered(self) -> None:
        blocks = parse_markdown("# T\n\n## Law\n\nA rule.\n\n*Note.* Why.\n\nAnother rule.\n")
        numbered = [numbering for numbering in number_blocks(blocks).blocks.values()]
        self.assertEqual(numbered, ["1.1", "1.2"])


class BuildTests(unittest.TestCase):
    """A PDF comes out, with the figures in it."""

    def test_a_small_book_builds_with_a_figure(self) -> None:
        figure = FIGURES_DIR / "fig-04-one-turn.png"
        with tempfile.TemporaryDirectory() as folder:
            source = pathlib.Path(folder) / "book.md"
            source.write_text(
                "# T\n\n## One\n\nHello **there**.\n\n- a\n- b\n\n| X | Y |\n| --- | --- |\n| 1 | 2 |\n\n"
                f"![One turn]({figure.as_posix()})\n\n> A quote.\n\n---\n\n## Two\n\nEnd.\n",
                encoding="utf-8",
            )
            book = Book(name="t", title="Test book", sources=(source,), numbered=True, contents=True)
            out = build_book(book, pathlib.Path(folder) / "out" / "t.pdf")
            data = out.read_bytes()
        self.assertTrue(data.startswith(b"%PDF"))
        self.assertGreaterEqual(data.count(b"/Type /Page"), 2)

    def test_both_books_build(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            for book in BOOKS.values():
                out = build_book(book, pathlib.Path(folder) / f"{book.name}.pdf")
                self.assertTrue(out.read_bytes().startswith(b"%PDF"), book.name)

    def test_every_figure_the_books_show_exists(self) -> None:
        for book in BOOKS.values():
            source = book.source
            assert source is not None
            for target in IMAGE_RE.findall(source.read_text(encoding="utf-8")):
                self.assertTrue((source.parent / target).exists(), f"{book.name}: {target}")

    def test_every_book_source_is_in_the_subset(self) -> None:
        """The plan and the outlines parse, so `--outlines` cannot fail on them."""
        for book in OUTLINE_BOOKS.values():
            source = book.source
            self.assertIsNotNone(source, book.name)
            parse_markdown(source.read_text(encoding="utf-8"))


class FigureTests(unittest.TestCase):
    """The committed figures are the registry's, and the outlines show only those."""

    def test_the_committed_figures_are_the_registry(self) -> None:
        on_disk = sorted(path.stem for path in FIGURES_DIR.glob("*.png"))
        self.assertEqual(on_disk, sorted(rulebook_figures.FIGURES))

    def test_every_figure_the_outlines_show_exists(self) -> None:
        for source in RULEBOOKS_DIR.glob("*.md"):
            for target in IMAGE_RE.findall(source.read_text(encoding="utf-8")):
                self.assertTrue((source.parent / target).exists(), f"{source.name}: {target}")

    def test_space_codes_read_left_to_right(self) -> None:
        self.assertEqual(rulebook_figures.parse_space("M2"), (Zone.MIDFIELD, 1))
        match = rulebook_figures.standard_match()
        centres = [rulebook_figures.space_centre_x(match, code) for code in ("H1", "H2", "M1", "M2", "M3", "V1", "V2")]
        self.assertEqual(centres, sorted(centres))

    def test_a_figure_renders(self) -> None:
        image = rulebook_figures.kickoff_figure(load_player_catalog())
        self.assertEqual(image.width, rulebook_figures.FIGURE_WIDTH)
        self.assertGreater(image.height, 0)


if __name__ == "__main__":
    unittest.main()

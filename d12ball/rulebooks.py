"""
The two rulebooks as PDFs -- see "The two rulebooks" in
docs/design/rulebooks.md and the plan in docs/rulebooks/plan.md.

`build_book` reads one markdown file -- the subset the books use:
headings, paragraphs, bold and italic, links, bullet and numbered lists
(nested by indent), tables, images with a caption, fenced code, a quote
and a page break (`---` on its own line) -- and sets it with reportlab
in the printed cards' palette and the bundled fonts. Anything else in
the file is an error, not something dropped on the floor.

**A numbered book is numbered by the builder.** For the Charter, every
level-2 heading is a Law, every level-3 heading a section, and every
paragraph under one carries its own number (`6.4.2`); a `[text](#slug)`
link to a heading becomes `text (6.4)` on the page. `renumber` writes
those same numbers into the source, so the file the bot's rules commands
read and GitHub shows carries the printed edition's numbers; `unnumber`
takes them out again, and the book is always built from the unnumbered
text, so a stale number in the file can never reach the page.

The layout lives here and `scripts/build_rulebooks.py` is the CLI, the
same split `boards.py` and `render_boards.py` make. No discord and no
async, like everything under `d12ball/`.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable, Optional, Sequence, Union
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image as ImageFlowable,
    KeepTogether,
    ListFlowable,
    NextPageTemplate,
    ListItem,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    XPreformatted,
)
from reportlab.platypus.tableofcontents import TableOfContents

from .cards import FACE_COLOR, INK, PANEL_COLOR
from .rules_doc import slugify_heading, split_heading_number

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FONT_DIR = PROJECT_ROOT / "d12ball" / "fonts"
DOCS_DIR = PROJECT_ROOT / "docs"
RULEBOOKS_DIR = DOCS_DIR / "rulebooks"
PRINT_DIR = PROJECT_ROOT / "print"

PAPERS = {"letter": letter, "a4": A4}
DEFAULT_PAPER = "letter"
MARGIN = 0.85 * inch

# The cards' palette, so the books and the components are one family.
INK_COLOR = colors.HexColor(INK)
FACE = colors.HexColor(FACE_COLOR)
PANEL = colors.HexColor(PANEL_COLOR)
RULE_COLOR = colors.HexColor("#c9c1b2")
MUTED_HEX = "#5d6770"
MUTED = colors.HexColor(MUTED_HEX)
ACCENT = colors.HexColor("#b8452b")


# --- The markdown subset ----------------------------------------------------


@dataclass
class Heading:
    level: int
    text: str

    @property
    def slug(self) -> str:
        return slugify_heading(self.text)


@dataclass
class Paragraph_:
    text: str


@dataclass
class ListItemNode:
    text: str
    children: list["ListBlock"] = field(default_factory=list)


@dataclass
class ListBlock:
    ordered: bool
    items: list[ListItemNode]


@dataclass
class TableBlock:
    rows: list[list[str]]
    aligns: list[str]


@dataclass
class ImageBlock:
    path: str
    caption: str


@dataclass
class QuoteBlock:
    text: str


@dataclass
class CodeBlock:
    text: str


@dataclass
class PageBreakBlock:
    pass


Block = Union[
    Heading, Paragraph_, ListBlock, TableBlock, ImageBlock, QuoteBlock,
    CodeBlock, PageBreakBlock,
]

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
LIST_RE = re.compile(r"^(\s*)([-*]|\d+\.)\s+(.*)$")
IMAGE_RE = re.compile(r"^!\[([^\]]*)\]\(([^)]+)\)\s*$")
TABLE_SEPARATOR_RE = re.compile(r"^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")
FENCE_RE = re.compile(r"^```")
PAGE_BREAK_RE = re.compile(r"^-{3,}\s*$")


class MarkdownError(ValueError):
    """A line the books' markdown subset does not cover."""


def parse_markdown(text: str) -> list[Block]:
    """The file as blocks, in order. Raises `MarkdownError` on anything else."""
    return [block for _, block in parse_markdown_lines(text)]


def parse_markdown_lines(text: str) -> list[tuple[int, Block]]:
    """`parse_markdown`, with the line each block starts on."""
    lines = text.splitlines()
    blocks: list[tuple[int, Block]] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        start = index
        if not stripped:
            index += 1
            continue
        if FENCE_RE.match(stripped):
            index += 1
            code: list[str] = []
            while index < len(lines) and not FENCE_RE.match(lines[index].strip()):
                code.append(lines[index])
                index += 1
            if index >= len(lines):
                raise MarkdownError("A code fence was opened and never closed.")
            blocks.append((start, CodeBlock("\n".join(code))))
            index += 1
            continue
        heading = HEADING_RE.match(line)
        if heading:
            blocks.append((start, Heading(len(heading.group(1)), heading.group(2))))
            index += 1
            continue
        if PAGE_BREAK_RE.match(stripped):
            blocks.append((start, PageBreakBlock()))
            index += 1
            continue
        image = IMAGE_RE.match(stripped)
        if image:
            blocks.append((start, ImageBlock(image.group(2), image.group(1))))
            index += 1
            continue
        if stripped.startswith("|"):
            rows: list[str] = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                rows.append(lines[index].strip())
                index += 1
            blocks.append((start, parse_table(rows)))
            continue
        if stripped.startswith(">"):
            quote: list[str] = []
            while index < len(lines) and lines[index].strip().startswith(">"):
                quote.append(lines[index].strip()[1:].strip())
                index += 1
            blocks.append((start, QuoteBlock(" ".join(part for part in quote if part))))
            continue
        if LIST_RE.match(line):
            block, index = parse_list(lines, index)
            blocks.append((start, block))
            continue
        if stripped.startswith("<"):
            raise MarkdownError(f"HTML is not part of the books' markdown: {stripped!r}")
        paragraph: list[str] = []
        while index < len(lines):
            candidate = lines[index]
            if not candidate.strip() or is_block_start(candidate):
                break
            paragraph.append(candidate.strip())
            index += 1
        blocks.append((start, Paragraph_(" ".join(paragraph))))
    return blocks


def is_block_start(line: str) -> bool:
    stripped = line.strip()
    return bool(
        HEADING_RE.match(line)
        or LIST_RE.match(line)
        or IMAGE_RE.match(stripped)
        or FENCE_RE.match(stripped)
        or PAGE_BREAK_RE.match(stripped)
        or stripped.startswith("|")
        or stripped.startswith(">")
    )


def parse_table(rows: list[str]) -> TableBlock:
    cells = [split_row(row) for row in rows if not TABLE_SEPARATOR_RE.match(row)]
    separators = [row for row in rows if TABLE_SEPARATOR_RE.match(row)]
    aligns: list[str] = []
    if separators:
        for cell in split_row(separators[0]):
            cell = cell.strip()
            if cell.endswith(":") and cell.startswith(":"):
                aligns.append("CENTER")
            elif cell.endswith(":"):
                aligns.append("RIGHT")
            else:
                aligns.append("LEFT")
    width = max(len(row) for row in cells)
    if len(aligns) < width:
        aligns.extend(["LEFT"] * (width - len(aligns)))
    padded = [row + [""] * (width - len(row)) for row in cells]
    return TableBlock(padded, aligns[:width])


def split_row(row: str) -> list[str]:
    inner = row.strip()
    if inner.startswith("|"):
        inner = inner[1:]
    if inner.endswith("|"):
        inner = inner[:-1]
    # A pipe inside inline code is content, not a column boundary.
    parts: list[str] = []
    current = ""
    in_code = False
    for char in inner:
        if char == "`":
            in_code = not in_code
        if char == "|" and not in_code:
            parts.append(current.strip())
            current = ""
        else:
            current += char
    parts.append(current.strip())
    return parts


def parse_list(lines: list[str], index: int, indent: int = -1) -> tuple[ListBlock, int]:
    """One list at `indent`, and every deeper list nested under its items."""
    first = LIST_RE.match(lines[index])
    assert first is not None
    own_indent = len(first.group(1))
    ordered = first.group(2)[0].isdigit()
    items: list[ListItemNode] = []
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            # A blank line inside a list is allowed; the list goes on if
            # the next non-blank line is still a list item at this depth.
            probe = index + 1
            while probe < len(lines) and not lines[probe].strip():
                probe += 1
            after = LIST_RE.match(lines[probe]) if probe < len(lines) else None
            if after and len(after.group(1)) > own_indent:
                index = probe
                continue
            if after and len(after.group(1)) == own_indent \
                    and after.group(2)[0].isdigit() == ordered:
                index = probe
                continue
            break
        match = LIST_RE.match(line)
        if match is None:
            # A continuation line of the current item, indented past its marker.
            if items and len(line) - len(line.lstrip()) > own_indent:
                items[-1].text += " " + line.strip()
                index += 1
                continue
            break
        item_indent = len(match.group(1))
        if item_indent < own_indent:
            break
        if item_indent == own_indent and match.group(2)[0].isdigit() != ordered:
            break
        if item_indent > own_indent:
            child, index = parse_list(lines, index, own_indent)
            if not items:
                raise MarkdownError("A nested list has no item to hang under.")
            items[-1].children.append(child)
            continue
        items.append(ListItemNode(match.group(3).strip()))
        index += 1
    return ListBlock(ordered, items), index


# --- Inline markup ----------------------------------------------------------

LinkResolver = Callable[[str, str], str]

BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
ITALIC_RE = re.compile(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])")
CODE_RE = re.compile(r"`([^`]+)`")
LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def plain_link(text: str, target: str) -> str:
    return text


def inline_markup(text: str, resolve_link: LinkResolver = plain_link) -> str:
    """Markdown inline syntax as reportlab paragraph markup."""
    # Links first, on the raw text, so a resolver sees the words as written.
    text = LINK_RE.sub(lambda m: resolve_link(m.group(1), m.group(2)), text)
    text = escape(text)
    text = CODE_RE.sub(r"<b>\1</b>", text)
    text = BOLD_RE.sub(r"<b>\1</b>", text)
    text = ITALIC_RE.sub(r"<i>\1</i>", text)
    return text


# --- Numbering --------------------------------------------------------------


@dataclass
class Numbering:
    """
    The numbers a Charter build hands out: a heading's, by slug, and a
    number for every block that gets one, by position in the block list.
    `cases` is every list or table that belongs to the paragraph just
    before it and so shares its number, by position: a list's items are
    that paragraph's cases, lettered (`6.4.2b`).
    """

    headings: dict[str, str] = field(default_factory=dict)
    blocks: dict[int, str] = field(default_factory=dict)
    cases: dict[int, str] = field(default_factory=dict)


NUMBERED_BLOCKS = (Paragraph_, ListBlock, TableBlock, QuoteBlock)
# A section that is a table of contents in the source is dropped from a
# numbered build: the builder generates its own.
DROPPED_SECTIONS = frozenset({"contents"})
# Level-2 headings that are not Laws: the preface, and any heading that
# opens a Part or an Appendix. Their blocks carry no numbers either.
FRONT_MATTER_SECTIONS = frozenset({"how-to-read-this-document"})
UNNUMBERED_PREFIXES = ("Part ", "Appendix ")
# A paragraph that opens with *Note* explains a rule and is never one,
# so it is never numbered -- see "How to read this document".
NOTE_PREFIX = "*Note"
# "Appendix A. Quick reference" -> a cross-reference reads "(Appendix A)".
APPENDIX_RE = re.compile(r"^Appendix ([A-Z])\b")


def is_unnumbered_heading(block: "Heading") -> bool:
    return block.slug in FRONT_MATTER_SECTIONS or block.text.startswith(UNNUMBERED_PREFIXES)


def is_note(block: "Block") -> bool:
    return isinstance(block, Paragraph_) and block.text.startswith(NOTE_PREFIX)


def number_blocks(blocks: Sequence[Block]) -> Numbering:
    """
    Law . section . paragraph. A paragraph straight under a Law, before
    any section, takes the second position itself (`1.3`), as the Law of
    Root numbers them, so sections and such paragraphs share one count.
    A list or table straight after a numbered paragraph is that
    paragraph's -- the cases it lists, the table it introduces -- and
    takes no number of its own (the author, 2026-09-26); one straight
    after a heading, with no paragraph to belong to, is numbered.
    """
    numbering = Numbering()
    law = 0
    second = 0
    third = 0
    in_section = False
    skipping = False
    for position, block in enumerate(blocks):
        if isinstance(block, Heading):
            if block.level == 2:
                skipping = block.slug in DROPPED_SECTIONS or is_unnumbered_heading(block)
                if skipping:
                    appendix = APPENDIX_RE.match(block.text)
                    if appendix:
                        numbering.headings[block.slug] = f"Appendix {appendix.group(1)}"
                    continue
                law += 1
                second = 0
                third = 0
                in_section = False
                numbering.headings[block.slug] = f"{law}"
            elif block.level == 3 and not skipping:
                second += 1
                third = 0
                in_section = True
                numbering.headings[block.slug] = f"{law}.{second}"
            elif block.level >= 4 and not skipping:
                numbering.headings[block.slug] = f"{law}.{second}"
            continue
        if skipping or law == 0 or not isinstance(block, NUMBERED_BLOCKS) or is_note(block):
            continue
        owner = numbering.blocks.get(position - 1)
        if isinstance(block, (ListBlock, TableBlock)) and owner \
                and isinstance(blocks[position - 1], Paragraph_):
            numbering.cases[position] = owner
            continue
        if in_section:
            third += 1
            numbering.blocks[position] = f"{law}.{second}.{third}"
        else:
            second += 1
            numbering.blocks[position] = f"{law}.{second}"
    return numbering


def dropped_positions(blocks: Sequence[Block]) -> set[int]:
    """Every block inside a section a numbered build leaves out."""
    dropped: set[int] = set()
    skipping = False
    for position, block in enumerate(blocks):
        if isinstance(block, Heading) and block.level <= 2:
            skipping = block.level == 2 and block.slug in DROPPED_SECTIONS
        if skipping:
            dropped.add(position)
    return dropped


def cites_itself(text: str, number: str) -> bool:
    """A link whose words already are the number -- `[Law 18](#...)`,
    `[Appendix B](#...)` -- which a `(18)` after it would only repeat."""
    return re.search(rf"(?<![\w.]){re.escape(number)}$", text.strip()) is not None


# --- The numbers in the source ----------------------------------------------
#
# `renumber` writes the build's numbers into the Charter's own markdown,
# the way the page prints them: `## 6. Maneuvers`, `### 6.4 The skill
# test`, a paragraph opening `**6.4.2**`, a numbered list or table under
# its number on a line of its own with the list's cases lettered
# (`- **a.**`), and a cross-reference as the link followed by its number,
# `[the skill test](#64-the-skill-test) (6.4)`. A list that is a
# paragraph's cases goes straight under it, lettered, with no number of
# its own, and a table a paragraph introduces likewise. Each link is pointed at
# the anchor GitHub gives the numbered heading, so the links still work
# there. `unnumber` takes every one of those out again, and the two are
# inverses: `renumber(unnumber(text))` is `text` for a file that has
# been renumbered, which is what the test suite checks.

BLOCK_NUMBER = r"\*\*\d+(?:\.\d+)+\*\*"
PARAGRAPH_NUMBER_RE = re.compile(rf"^(\s*(?:>\s*)?){BLOCK_NUMBER}\s+")
LONE_NUMBER_RE = re.compile(rf"^\s*{BLOCK_NUMBER}\s*$")
CASE_LETTER_RE = re.compile(r"^(\s*[-*]\s+)\*\*[a-z]\.\*\*\s+")
CROSS_REFERENCE_RE = re.compile(r"(\]\(#[^)\s]+\)) \((?:\d+(?:\.\d+)*|Appendix [A-Z])\)")
ANCHOR_LINK_RE = re.compile(r"\]\(#([^)\s]+)\)")
CONTENTS_LAW_RE = re.compile(r"^Law \d+\. ")
STALE_ANCHOR_RE = re.compile(r"^\d+-(.+)$")
CASE_LETTERS = "abcdefghijklmnopqrstuvwxyz"


def heading_anchors(text: str) -> dict[str, str]:
    """Every heading's anchor as written, by the slug of its name
    without a number: `{"the-skill-test": "64-the-skill-test"}`."""
    anchors: dict[str, str] = {}
    for _, block in parse_markdown_lines(text):
        if isinstance(block, Heading):
            _, bare = split_heading_number(block.level, block.text)
            anchors[slugify_heading(bare)] = block.slug
    return anchors


def unnumber(text: str) -> str:
    """The markdown with every number `renumber` writes taken out, and
    every link pointed back at the anchor of the unnumbered heading."""
    anchors = heading_anchors(text)
    to_bare = {written: bare for bare, written in anchors.items()}

    def bare_anchor(target: str) -> str:
        if target in to_bare:
            return to_bare[target]
        # A link still pointing at an old number's anchor (`#64-...`)
        # after the heading's number was changed by hand.
        stale = STALE_ANCHOR_RE.match(target)
        if stale and stale.group(1) in anchors:
            return stale.group(1)
        return target

    lines = text.split("\n")
    kept: list[str] = []
    in_code = False
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        if FENCE_RE.match(line.strip()):
            in_code = not in_code
        if in_code or FENCE_RE.match(line.strip()):
            kept.append(line)
            continue
        if LONE_NUMBER_RE.match(line):
            # The number a list or a table is set under, and the blank
            # line `renumber` put after it.
            if index < len(lines) and not lines[index].strip():
                index += 1
            continue
        heading = HEADING_RE.match(line)
        if heading:
            level = len(heading.group(1))
            line = f"{heading.group(1)} {split_heading_number(level, heading.group(2))[1]}"
        line = PARAGRAPH_NUMBER_RE.sub(r"\1", line, count=1)
        line = CASE_LETTER_RE.sub(r"\1", line, count=1)
        line = CROSS_REFERENCE_RE.sub(r"\1", line)
        line = ANCHOR_LINK_RE.sub(lambda m: f"](#{bare_anchor(m.group(1))})", line)
        kept.append(line)
    return "\n".join(kept)


def renumber(text: str) -> str:
    """The markdown with the printed edition's numbers written in."""
    text = unnumber(text)
    positioned = parse_markdown_lines(text)
    blocks = [block for _, block in positioned]
    numbering = number_blocks(blocks)
    lines = text.split("\n")
    before: dict[int, list[str]] = {}
    anchors: dict[str, str] = {}

    for position, (start, block) in enumerate(positioned):
        if isinstance(block, Heading):
            number = numbering.headings.get(block.slug)
            written = block.text
            if number and not number.startswith("Appendix"):
                if block.level == 2:
                    written = f"{number}. {block.text}"
                elif block.level == 3:
                    written = f"{number} {block.text}"
            lines[start] = f"{'#' * block.level} {written}"
            anchors[block.slug] = slugify_heading(written)
            continue
        number = numbering.blocks.get(position)
        if number is None:
            number = numbering.cases.get(position)
            if number is not None and isinstance(block, ListBlock):
                letter_cases(lines, positioned, position, number)
            continue
        if isinstance(block, (Paragraph_, QuoteBlock)):
            lines[start] = re.sub(r"^(\s*(?:>\s*)?)", rf"\g<1>**{number}** ", lines[start], count=1)
            continue
        # A list or a table goes under its number, on a line of its own.
        before[start] = [f"**{number}**", ""]
        if isinstance(block, ListBlock):
            letter_cases(lines, positioned, position, number)

    def cross_reference(found: re.Match) -> str:
        words, target = found.group(1), found.group(2)
        link = f"[{words}](#{anchors.get(target, target)})"
        number = numbering.headings.get(target)
        if number is None:
            return link
        if in_contents:
            return link.replace(words, CONTENTS_LAW_RE.sub(f"Law {number}. ", words), 1)
        if cites_itself(words, number):
            return link
        return f"{link} ({number})"

    written: list[str] = []
    in_code = False
    in_contents = False
    for index, line in enumerate(lines):
        written.extend(before.get(index, ()))
        if FENCE_RE.match(line.strip()):
            in_code = not in_code
        elif not in_code:
            heading = HEADING_RE.match(line)
            if heading and len(heading.group(1)) == 2:
                in_contents = slugify_heading(heading.group(2)) in DROPPED_SECTIONS
            line = re.sub(r"\[([^\]]+)\]\(#([^)\s]+)\)", cross_reference, line)
        written.append(line)
    return "\n".join(written)


def letter_cases(
    lines: list[str], positioned: list[tuple[int, Block]], position: int, number: str,
) -> None:
    """A numbered list's own items as `- **a.**`, `- **b.**`, in place;
    a list nested under one of them keeps its bullets."""
    start = positioned[position][0]
    end = positioned[position + 1][0] if position + 1 < len(positioned) else len(lines)
    own_indent = len(LIST_RE.match(lines[start]).group(1))
    letters = iter(CASE_LETTERS)
    for index in range(start, end):
        item = LIST_RE.match(lines[index])
        if item and len(item.group(1)) == own_indent:
            letter = next(letters, None)
            if letter is None:
                raise MarkdownError(f"{number} lists more cases than there are letters")
            lines[index] = f"{item.group(1)}- **{letter}.** {item.group(3)}"


def anchor_moves(before: str, after: str) -> dict[str, str]:
    """Where each heading's anchor went, old anchor to new, for a link
    into the file from outside it. A link written to the unnumbered
    heading's anchor is moved as well."""
    old = heading_anchors(before)
    new = heading_anchors(after)
    moves: dict[str, str] = {}
    for bare, anchor in new.items():
        for previous in (bare, old.get(bare, bare)):
            if previous != anchor:
                moves[previous] = anchor
    return moves


# --- The book ---------------------------------------------------------------


@dataclass(frozen=True)
class Cover:
    """
    What a book's cover says: its title, broken where the author broke
    it, and the lines under the rule. The words are here once; the PDF's
    first page draws them and so does the picture of the cover the
    landing page shows (`landing/covers.py`), both through
    `cover_layout`.
    """

    title_lines: tuple[str, ...]
    lines: tuple[str, ...]


@dataclass(frozen=True)
class Book:
    """One book to build: where its text is and how it is set."""

    name: str
    title: str
    sources: tuple[Path, ...]
    # Law/section/paragraph numbers, and a generated contents page.
    numbered: bool = False
    contents: bool = False
    subtitle: str = ""
    # A book with a cover opens on it rather than on its title line.
    cover: Optional[Cover] = None

    @property
    def source(self) -> Optional[Path]:
        """The first source that exists, or None."""
        for path in self.sources:
            if path.exists():
                return path
        return None


BOOKS: dict[str, Book] = {
    "charter": Book(
        name="charter",
        title="The D12Ball Charter: Laws of the Game",
        # The Charter is the living rules renumbered (see the plan), so
        # until docs/charter.md exists the build numbers the living
        # rules themselves: that is what the numbered draft looks like.
        sources=(DOCS_DIR / "charter.md", DOCS_DIR / "living-rules.md"),
        numbered=True,
        contents=True,
        # The cover's words are the author's (on the landing pages'
        # canvas, 2026-09-27).
        cover=Cover(
            title_lines=("The D12Ball", "Charter"),
            lines=("Laws of the Game.", "Comprehensive rules reference for the game."),
        ),
    ),
    "learn-to-play": Book(
        name="learn-to-play",
        title="D12 Ball: Learn to Play",
        sources=(DOCS_DIR / "learn-to-play.md",),
        cover=Cover(
            title_lines=("D12 Ball:", "Learn to Play"),
            lines=(
                "Learn the fundamentals quickly with a beautifully illustrated "
                "guide for the training mode.",
            ),
        ),
    ),
}

OUTLINE_BOOKS: dict[str, Book] = {
    "plan": Book(
        name="plan",
        title="The two rulebooks: a plan",
        sources=(RULEBOOKS_DIR / "plan.md",),
        contents=True,
    ),
    "charter-outline": Book(
        name="charter-outline",
        title="The D12Ball Charter: outline",
        sources=(RULEBOOKS_DIR / "charter-outline.md",),
        contents=True,
    ),
    "learn-to-play-outline": Book(
        name="learn-to-play-outline",
        title="Learn to Play: outline",
        sources=(RULEBOOKS_DIR / "learn-to-play-outline.md",),
        contents=True,
    ),
}


# --- The cover ----------------------------------------------------------------

# The cover as shares of the page -- sizes of its width, heights of its
# height -- so the PDF's first page and the landing page's picture of it
# are one layout at any size. As the author reviewed it on the canvas
# (2026-09-27): cream paper, a gold band at the head, the title, a gold
# rule, the lines under it, the d12 low right, the publisher at the foot.
COVER_BAND = 0.025
COVER_MARGIN = 0.09
COVER_TITLE_TOP = 0.13
COVER_TITLE_SIZE = 0.1
COVER_TITLE_LEADING = 1.2
COVER_RULE_GAP = 0.42  # of the title's size, from its last baseline
COVER_RULE_WEIGHT = 0.004
COVER_TEXT_SIZE = 0.037
COVER_TEXT_LEADING = 1.45
COVER_DIE_SIZE = 0.31
COVER_DIE_CENTRE = (0.745, 0.76)
COVER_PUBLISHER_SIZE = 0.029
COVER_PUBLISHER_BASELINE = 0.915

# The three faces a cover sets, which each drawing maps to its own
# handle on the one bundled file: Racing Sans One, Roboto Slab, Roboto Slab
# Bold.
COVER_FACES = {
    "display": "RacingSansOne-Regular.ttf",
    "text": "RobotoSlab-Regular.ttf",
    "bold": "RobotoSlab-Bold.ttf",
}

# How wide a run of text is in a face at a size, in the drawing's units.
Measure = Callable[[str, str, float], float]


@dataclass(frozen=True)
class CoverText:
    text: str
    face: str  # a key of COVER_FACES
    size: float
    x: float
    baseline: float  # from the top of the page
    colour: str


@dataclass(frozen=True)
class CoverLayout:
    """A cover laid out on a page `width` by `height`, measured from the
    top left, for a drawing to put down as it is."""

    width: float
    height: float
    ground: str
    gold: str
    band: float
    rule: tuple[float, float, float, float]  # x0, x1, y, weight
    die: tuple[float, float, float]  # left, top, size
    texts: tuple[CoverText, ...]


def wrap_words(text: str, fits: Callable[[str], bool]) -> list[str]:
    lines: list[str] = []
    for word in text.split():
        candidate = f"{lines[-1]} {word}" if lines else word
        if lines and fits(candidate):
            lines[-1] = candidate
        else:
            lines.append(word)
    return lines


def cover_layout(cover: Cover, width: float, height: float, measure: Measure) -> CoverLayout:
    """
    Where everything on `cover` goes on a page `width` by `height`.
    `measure` is the drawing's own, so a line wraps where that drawing's
    font says it runs out of room.
    """
    from .box_art import NIGHT_COVER, PUBLISHER

    left = width * COVER_MARGIN
    right = width - left
    texts: list[CoverText] = []

    title_size = width * COVER_TITLE_SIZE
    baseline = height * COVER_TITLE_TOP
    for line in cover.title_lines:
        baseline += title_size * (COVER_TITLE_LEADING if texts else 1.0)
        texts.append(CoverText(line, "display", title_size, left, baseline, INK))

    rule_y = baseline + title_size * COVER_RULE_GAP
    text_size = width * COVER_TEXT_SIZE
    baseline = rule_y + text_size * 1.8
    first = True
    for paragraph in cover.lines:
        fits = lambda run: measure(run, "text", text_size) <= right - left  # noqa: E731
        for line in wrap_words(paragraph, fits):
            if not first:
                baseline += text_size * COVER_TEXT_LEADING
            first = False
            texts.append(CoverText(line, "text", text_size, left, baseline, MUTED_HEX))

    texts.append(CoverText(
        PUBLISHER.upper(), "bold", width * COVER_PUBLISHER_SIZE, left,
        height * COVER_PUBLISHER_BASELINE, MUTED_HEX,
    ))
    die = width * COVER_DIE_SIZE
    centre_x, centre_y = width * COVER_DIE_CENTRE[0], height * COVER_DIE_CENTRE[1]
    return CoverLayout(
        width=width,
        height=height,
        ground=FACE_COLOR,
        # The jumbotron's gold: a band and a rule, never text, which is
        # what box_art says it cannot carry on paper.
        gold=NIGHT_COVER.accent,
        band=height * COVER_BAND,
        rule=(left, right, rule_y, width * COVER_RULE_WEIGHT),
        die=(centre_x - die / 2, centre_y - die / 2, die),
        texts=tuple(texts),
    )


# The die is drawn at print resolution whatever the page is scaled to.
COVER_DIE_DPI = 300


def draw_cover(canvas, cover: Cover, pagesize) -> None:
    """The cover as the PDF's first page, drawn straight onto the canvas."""
    from reportlab.lib.utils import ImageReader

    from .box_art import d12_art

    width, height = pagesize
    faces = {"display": "Display", "text": "RobotoSlab", "bold": "RobotoSlab-Bold"}
    layout = cover_layout(
        cover, width, height,
        lambda text, face, size: pdfmetrics.stringWidth(text, faces[face], size),
    )
    canvas.saveState()
    canvas.setFillColor(colors.HexColor(layout.ground))
    canvas.rect(0, 0, width, height, stroke=0, fill=1)
    canvas.setFillColor(colors.HexColor(layout.gold))
    canvas.rect(0, height - layout.band, width, layout.band, stroke=0, fill=1)
    x0, x1, y, weight = layout.rule
    canvas.setStrokeColor(colors.HexColor(layout.gold))
    canvas.setLineWidth(weight)
    canvas.line(x0, height - y, x1, height - y)
    for text in layout.texts:
        canvas.setFillColor(colors.HexColor(text.colour))
        canvas.setFont(faces[text.face], text.size)
        canvas.drawString(text.x, height - text.baseline, text.text)
    left, top, size = layout.die
    die = d12_art(round(size / inch * COVER_DIE_DPI))
    canvas.drawImage(
        ImageReader(die), left, height - top - size, width=size, height=size, mask="auto",
    )
    canvas.restoreState()


_fonts_registered = False


def register_fonts() -> None:
    """The bundled fonts, by absolute path, as everywhere else in the bot."""
    global _fonts_registered
    if _fonts_registered:
        return
    pdfmetrics.registerFont(TTFont("RobotoSlab", str(FONT_DIR / "RobotoSlab-Regular.ttf")))
    pdfmetrics.registerFont(TTFont("RobotoSlab-Bold", str(FONT_DIR / "RobotoSlab-Bold.ttf")))
    pdfmetrics.registerFont(TTFont("Display", str(FONT_DIR / "RacingSansOne-Regular.ttf")))
    # No italic face is bundled, so italic falls back to the regular
    # face; the words are still there. Roboto Slab has no italic of its
    # own, so the fix would be a second family for emphasis.
    pdfmetrics.registerFontFamily(
        "RobotoSlab", normal="RobotoSlab", bold="RobotoSlab-Bold", italic="RobotoSlab", boldItalic="RobotoSlab-Bold",
    )
    _fonts_registered = True


def styles() -> dict[str, ParagraphStyle]:
    body = ParagraphStyle(
        "Body", fontName="RobotoSlab", fontSize=10, leading=14, textColor=INK_COLOR, spaceAfter=6,
    )
    return {
        "Title": ParagraphStyle("Title", fontName="Display", fontSize=34, leading=40, textColor=INK_COLOR, spaceAfter=10),
        "Subtitle": ParagraphStyle("Subtitle", parent=body, fontSize=12, leading=16, textColor=MUTED, spaceAfter=24),
        "Law": ParagraphStyle("Law", fontName="Display", fontSize=20, leading=24, textColor=INK_COLOR, spaceBefore=20, spaceAfter=8, keepWithNext=True),
        "Section": ParagraphStyle("Section", fontName="RobotoSlab-Bold", fontSize=13, leading=17, textColor=INK_COLOR, spaceBefore=12, spaceAfter=5, keepWithNext=True),
        "Sub": ParagraphStyle("Sub", fontName="RobotoSlab-Bold", fontSize=11, leading=15, textColor=INK_COLOR, spaceBefore=8, spaceAfter=4, keepWithNext=True),
        "Body": body,
        "Numbered": ParagraphStyle("Numbered", parent=body, leftIndent=40, firstLineIndent=-40),
        "Item": ParagraphStyle("Item", parent=body, spaceAfter=2),
        "Cell": ParagraphStyle("Cell", parent=body, fontSize=8.5, leading=11, spaceAfter=0),
        "CellHead": ParagraphStyle("CellHead", parent=body, fontName="RobotoSlab-Bold", fontSize=8.5, leading=11, spaceAfter=0),
        "Caption": ParagraphStyle("Caption", parent=body, fontSize=8.5, leading=11, textColor=MUTED, alignment=TA_CENTER, spaceBefore=3, spaceAfter=10),
        "Quote": ParagraphStyle("Quote", parent=body, leftIndent=18, textColor=MUTED, borderPadding=(2, 6, 2, 6)),
        "Note": ParagraphStyle("Note", parent=body, fontSize=9, leading=12.5, leftIndent=40, textColor=MUTED, spaceAfter=8),
        "Code": ParagraphStyle("Code", fontName="RobotoSlab", fontSize=8, leading=10.5, textColor=INK_COLOR, backColor=PANEL, borderPadding=6, leftIndent=6, spaceBefore=4, spaceAfter=10),
        "TOCHeading": ParagraphStyle("TOCHeading", fontName="Display", fontSize=20, leading=24, textColor=INK_COLOR, spaceAfter=10),
        "TOC1": ParagraphStyle("TOC1", parent=body, fontName="RobotoSlab-Bold", spaceBefore=4),
        "TOC2": ParagraphStyle("TOC2", parent=body, leftIndent=16, spaceAfter=0),
        "Footer": ParagraphStyle("Footer", parent=body, fontSize=8, textColor=MUTED),
    }


class BookTemplate(BaseDocTemplate):
    """One frame a page, a running footer, and the contents entries."""

    def __init__(self, path, book_title: str, pagesize, cover: Optional[Cover] = None, **kwargs) -> None:
        super().__init__(path, pagesize=pagesize, leftMargin=MARGIN, rightMargin=MARGIN,
                         topMargin=MARGIN, bottomMargin=MARGIN, title=book_title, **kwargs)
        self.book_title = book_title
        frame = Frame(self.leftMargin, self.bottomMargin, self.width, self.height, id="page")
        templates = [PageTemplate(id="page", frames=[frame], onPage=self.draw_footer)]
        if cover is not None:
            # The first template is the first page's: the cover, drawn
            # whole by `draw_cover`, with no footer and nothing flowed.
            templates.insert(0, PageTemplate(
                id="cover",
                frames=[Frame(0, 0, pagesize[0], pagesize[1], id="cover")],
                onPage=lambda canvas, doc: draw_cover(canvas, cover, pagesize),
            ))
        self.addPageTemplates(templates)

    def draw_footer(self, canvas, doc) -> None:
        canvas.saveState()
        canvas.setFont("RobotoSlab", 8)
        canvas.setFillColor(MUTED)
        y = self.bottomMargin - 0.4 * inch
        canvas.drawString(self.leftMargin, y, self.book_title)
        canvas.drawRightString(self.leftMargin + self.width, y, str(doc.page))
        canvas.setStrokeColor(RULE_COLOR)
        canvas.line(self.leftMargin, y + 12, self.leftMargin + self.width, y + 12)
        canvas.restoreState()

    def afterFlowable(self, flowable) -> None:
        if not isinstance(flowable, Paragraph):
            return
        level = {"Law": 0, "Section": 1}.get(flowable.style.name)
        if level is None:
            return
        text = flowable.getPlainText()
        key = f"h{self.seq.nextf('heading')}"
        self.canv.bookmarkPage(key)
        self.canv.addOutlineEntry(text, key, level=level, closed=level > 0)
        self.notify("TOCEntry", (level, text, self.page, key))


def source_label(source: Optional[Path]) -> str:
    """The source as the book names it: repo-relative where it can be."""
    if source is None:
        return "?"
    try:
        return str(source.relative_to(PROJECT_ROOT))
    except ValueError:
        return source.name


def image_flowable(path: Path, available_width: float):
    from PIL import Image as PILImage

    with PILImage.open(path) as image:
        width, height = image.size
    scale = min(available_width / width, 1.0)
    # A figure taller than a page is scaled to fit one, so it never
    # spills into a page of its own with nothing under it.
    max_height = 8.2 * inch
    if height * scale > max_height:
        scale = max_height / height
    return ImageFlowable(str(path), width=width * scale, height=height * scale)


def build_story(book: Book, blocks: Sequence[Block], available_width: float) -> list:
    register_fonts()
    style = styles()
    numbering = number_blocks(blocks) if book.numbered else Numbering()
    dropped = dropped_positions(blocks) if book.numbered else set()
    base_dir = book.source.parent if book.source else PROJECT_ROOT

    def resolve_link(text: str, target: str) -> str:
        number = numbering.headings.get(target[1:]) if target.startswith("#") else None
        if number is None or cites_itself(text, number):
            return text
        return f"{text} ({number})"

    edition = Paragraph(
        escape(book.subtitle or f"Built {date.today().isoformat()} from {source_label(book.source)}"),
        style["Subtitle"],
    )
    if book.cover is not None:
        # The cover carries the title; the page after it opens on the
        # edition line.
        story: list = [NextPageTemplate("page"), PageBreak(), edition]
    else:
        story = [Paragraph(escape(book.title), style["Title"]), edition]
    if book.contents:
        toc = TableOfContents()
        toc.levelStyles = [style["TOC1"], style["TOC2"]]
        toc.dotsMinLevel = 0
        story.append(Paragraph("Contents", style["TOCHeading"]))
        story.append(toc)
        story.append(PageBreak())

    for position, block in enumerate(blocks):
        if position in dropped:
            continue
        number = numbering.blocks.get(position)
        if isinstance(block, Heading):
            if block.level == 1:
                continue  # The book's title is the Book's, not the file's.
            text = escape(block.text.replace("*", ""))
            if block.level == 2:
                if book.numbered and block.slug in numbering.headings:
                    text = f"{numbering.headings[block.slug]}. {text}"
                story.append(Paragraph(text, style["Law"]))
            elif block.level == 3:
                if book.numbered and block.slug in numbering.headings:
                    text = f"{numbering.headings[block.slug]} {text}"
                story.append(Paragraph(text, style["Section"]))
            else:
                story.append(Paragraph(text, style["Sub"]))
        elif isinstance(block, Paragraph_):
            markup = inline_markup(block.text, resolve_link)
            if is_note(block):
                story.append(Paragraph(markup, style["Note"]))
            elif number:
                story.append(Paragraph(f"<b>{number}</b>&nbsp;&nbsp;{markup}", style["Numbered"]))
            else:
                story.append(Paragraph(markup, style["Body"]))
        elif isinstance(block, ListBlock):
            if number:
                story.append(Paragraph(f"<b>{number}</b>", style["Body"]))
            lettered = bool(number) or position in numbering.cases
            story.append(list_flowable(block, style, resolve_link, lettered=lettered))
            story.append(Spacer(1, 4))
        elif isinstance(block, TableBlock):
            if number:
                story.append(Paragraph(f"<b>{number}</b>", style["Body"]))
            story.append(table_flowable(block, style, resolve_link, available_width))
            story.append(Spacer(1, 8))
        elif isinstance(block, ImageBlock):
            path = (base_dir / block.path).resolve()
            if not path.exists():
                raise FileNotFoundError(f"{book.source}: image {block.path} is missing")
            parts = [image_flowable(path, available_width)]
            if block.caption:
                parts.append(Paragraph(inline_markup(block.caption), style["Caption"]))
            story.append(KeepTogether(parts))
        elif isinstance(block, QuoteBlock):
            markup = inline_markup(block.text, resolve_link)
            if number:
                markup = f"<b>{number}</b>&nbsp;&nbsp;{markup}"
            story.append(quote_flowable(markup, style, available_width))
        elif isinstance(block, CodeBlock):
            story.append(XPreformatted(escape(block.text), style["Code"]))
        elif isinstance(block, PageBreakBlock):
            story.append(PageBreak())
        else:  # pragma: no cover - the parser only makes the types above
            raise MarkdownError(f"Unknown block {block!r}")
    return story


def list_flowable(
    block: ListBlock,
    style: dict,
    resolve_link: LinkResolver,
    depth: int = 0,
    lettered: bool = False,
) -> ListFlowable:
    """
    A list. Under a numbered paragraph its items are lettered (a., b.)
    whatever marker the source used, so a case can be cited as `6.4.2b`;
    anywhere else the source's own bullets or numbers stand.
    """
    items = []
    for item in block.items:
        parts: list = [Paragraph(inline_markup(item.text, resolve_link), style["Item"])]
        for child in item.children:
            parts.append(list_flowable(child, style, resolve_link, depth + 1))
        items.append(ListItem(parts, leftIndent=18))
    if lettered:
        kwargs = dict(bulletType="a", bulletFormat="%s.")
    elif block.ordered:
        kwargs = dict(bulletType="1", bulletFormat="%s.")
    else:
        kwargs = dict(bulletType="bullet", start="\u2022")
    return ListFlowable(
        items, bulletFontName="RobotoSlab", bulletFontSize=9, leftIndent=18, spaceAfter=2, **kwargs,
    )


def table_flowable(block: TableBlock, style: dict, resolve_link: LinkResolver, available_width: float) -> Table:
    columns = len(block.rows[0])
    # Columns share the width by how much text they carry, within
    # bounds, so a one-word column does not take a fifth of the page.
    weights = []
    for column in range(columns):
        longest = max(len(row[column]) for row in block.rows)
        weights.append(min(max(longest, 18), 60))
    total = sum(weights)
    widths = [available_width * weight / total for weight in weights]
    data = []
    for row_index, row in enumerate(block.rows):
        cell_style = style["CellHead"] if row_index == 0 else style["Cell"]
        data.append([
            Paragraph(inline_markup(cell, resolve_link), ParagraphStyle(
                f"cell{row_index}{column}", parent=cell_style, alignment={"LEFT": 0, "CENTER": 1, "RIGHT": 2}[block.aligns[column]],
            ))
            for column, cell in enumerate(row)
        ])
    table = Table(data, colWidths=widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PANEL),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, INK_COLOR),
        ("LINEBELOW", (0, 1), (-1, -1), 0.4, RULE_COLOR),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def quote_flowable(markup: str, style: dict, available_width: float) -> Table:
    table = Table([[Paragraph(markup, style["Quote"])]], colWidths=[available_width])
    table.setStyle(TableStyle([
        ("LINEBEFORE", (0, 0), (0, -1), 2, ACCENT),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return table


def book_bytes(book: Book, paper: str = DEFAULT_PAPER) -> bytes:
    """
    Set the book into memory and return the PDF's bytes. `build_book`
    writes these; the web app serves them without a file in `print/`
    (docs/design/rulebooks.md).
    """
    source = book.source
    if source is None:
        raise FileNotFoundError(
            f"{book.name}: none of its sources exist yet ({', '.join(str(p) for p in book.sources)})"
        )
    text = source.read_text(encoding="utf-8")
    # The numbers written into the source are the build's own; it
    # numbers the text without them, so a stale one never prints.
    blocks = parse_markdown(unnumber(text) if book.numbered else text)
    pagesize = PAPERS[paper]
    available_width = pagesize[0] - 2 * MARGIN
    story = build_story(book, blocks, available_width)
    buffer = io.BytesIO()
    document = BookTemplate(buffer, book.title, pagesize, cover=book.cover)
    if book.contents:
        document.multiBuild(story)
    else:
        document.build(story)
    return buffer.getvalue()


def build_book(book: Book, out_path: Path, paper: str = DEFAULT_PAPER) -> Path:
    """Set the book and write the PDF. Returns the path written."""
    data = book_bytes(book, paper)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data)
    return out_path

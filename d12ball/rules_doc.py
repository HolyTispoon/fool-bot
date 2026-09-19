"""Serving docs/living-rules.md to Discord.

The living rules are the one statement of the ruleset -- see "The rules"
in docs/design/rules-and-data.md -- so the two lookup commands read that file rather than
keeping a second copy of the text anywhere in the bot. Everything here
is about getting markdown written for GitHub into a chat client that
cannot render half of it, and into messages of 2000 characters.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# Resolved from this file rather than the working directory, the same
# way gamesaves/d12ball/storage.py resolves the save file: the bot is
# started from wherever its host feels like starting it.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
LIVING_RULES_PATH = PROJECT_ROOT / "docs" / "living-rules.md"

# Discord's hard ceiling on one message.
DISCORD_MESSAGE_LIMIT = 2000

# The table of contents is a list of links to the sections below it, so
# it answers no question anyone would ask a search command; the level-1
# heading is the document's title rather than a section of it. Both are
# still part of the full text, which is posted verbatim.
UNLISTED_SLUGS = frozenset({"contents"})

HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.*?)\s*$")

# A markdown link whose target is not a URL: every link in the living
# rules is one of these, either an anchor within the document or a
# neighbouring file. Discord renders neither, and shows the raw
# `[text](#anchor)` instead -- so the syntax is dropped and the words
# kept. Links to http(s) are left alone.
LOCAL_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\((?!https?://)[^)]*\)")

# GitHub's anchor rules, which is what the document's own links use:
# lowercase, punctuation dropped, spaces to hyphens.
SLUG_STRIP_PATTERN = re.compile(r"[^\w\s-]")
SLUG_SPACE_PATTERN = re.compile(r"[\s_]+")


def slugify_heading(title: str) -> str:
    """The anchor GitHub would give this heading."""
    text = title.replace("*", "").replace("`", "").strip().lower()
    text = SLUG_STRIP_PATTERN.sub("", text)
    return SLUG_SPACE_PATTERN.sub("-", text).strip("-")


def for_discord(text: str) -> str:
    """The markdown, with what Discord cannot render taken out."""
    return LOCAL_LINK_PATTERN.sub(r"\1", text)


@dataclass(frozen=True)
class RulesSection:
    """One heading of the living rules, and what sits under it."""

    level: int
    title: str
    slug: str
    # Enclosing headings, outermost first. Empty for a level-2 section.
    ancestors: tuple[str, ...]
    # The heading and everything under it, subsections included. This is
    # what a lookup posts: asking about "Maneuver" means the four steps
    # as well.
    text: str

    @property
    def path(self) -> tuple[str, ...]:
        return self.ancestors + (self.title,)

    @property
    def label(self) -> str:
        """How the section is named in the autocomplete."""
        return " › ".join(self.path)

    @property
    def searchable(self) -> str:
        return f"{self.label}\n{self.text}".lower()


@dataclass(frozen=True)
class RulesDocument:
    """The living rules, parsed into sections."""

    title: str
    text: str
    sections: tuple[RulesSection, ...]

    def find(self, query: str) -> Optional[RulesSection]:
        """The section a `section:` argument names, if it names one.

        Discord lets a coach submit whatever they typed rather than a
        choice from the autocomplete, so this accepts the slug the
        autocomplete sends, the label it displayed, and a plain heading
        typed by hand.
        """
        wanted = query.strip().lstrip("#").strip()
        if not wanted:
            return None
        folded = wanted.lower()
        slug = slugify_heading(wanted)

        for section in self.sections:
            if section.slug == folded or section.slug == slug:
                return section
        for section in self.sections:
            if folded in (section.title.lower(), section.label.lower()):
                return section

        partial = [
            section
            for section in self.sections
            if folded in section.label.lower()
        ]
        if len(partial) == 1:
            return partial[0]
        return None

    def best_match(self, query: str) -> Optional[RulesSection]:
        """The one section a query names, heading or not.

        Free-typed words are answered when they can only mean one part
        of the ruleset: either they name a heading, or every section
        that mentions them is on a single branch -- a subsection and the
        parents that carry its text, which are all the same rule read at
        different depths. Anything wider is a choice, not an answer.
        """
        found = self.find(query)
        if found is not None:
            return found

        matches = self.search(query)
        if not matches:
            return None
        deepest = matches[0]
        if all(match.title in deepest.path for match in matches[1:]):
            return deepest
        return None

    def search(self, query: str, limit: int = 25) -> list[RulesSection]:
        """Sections to offer for what has been typed so far.

        Headings first, in document order, then sections whose body
        mentions the words -- so a coach who knows the rule but not what
        it is filed under still finds it.
        """
        folded = query.strip().lower()
        if not folded:
            return list(self.sections[:limit])

        by_heading = [
            section
            for section in self.sections
            if folded in section.label.lower()
        ]
        # A section carries its subsections, so words in a subsection
        # match its parent as well. The deeper match is the more
        # specific answer to the same question, so it is offered first.
        by_body = sorted(
            (
                section
                for section in self.sections
                if section not in by_heading and folded in section.searchable
            ),
            key=lambda section: -section.level,
        )
        return (by_heading + by_body)[:limit]


def parse_rules_document(markdown: str) -> RulesDocument:
    lines = markdown.splitlines()
    headings: list[tuple[int, int, str]] = []  # line index, level, title
    for index, line in enumerate(lines):
        match = HEADING_PATTERN.match(line)
        if match is not None:
            headings.append((index, len(match.group(1)), match.group(2)))

    title = next(
        (text for _, level, text in headings if level == 1),
        "D12 Ball -- living rules",
    )

    sections: list[RulesSection] = []
    for position, (start, level, heading) in enumerate(headings):
        if level < 2:
            continue
        slug = slugify_heading(heading)
        if slug in UNLISTED_SLUGS:
            continue

        # A section runs to the next heading at its own level or above:
        # a level-2 section carries its level-3 subsections with it.
        end = len(lines)
        for later_start, later_level, _ in headings[position + 1:]:
            if later_level <= level:
                end = later_start
                break

        # The headings still open at this point, innermost last: every
        # earlier heading closes the ones at its own level or deeper,
        # and this heading closes the rest.
        open_levels: list[tuple[int, str]] = []
        for earlier_start, earlier_level, earlier_title in headings:
            if earlier_start >= start:
                break
            while open_levels and open_levels[-1][0] >= earlier_level:
                open_levels.pop()
            open_levels.append((earlier_level, earlier_title))
        while open_levels and open_levels[-1][0] >= level:
            open_levels.pop()
        ancestors = [
            open_title
            for open_level, open_title in open_levels
            if open_level > 1
        ]

        body = "\n".join(lines[start:end]).strip("\n")
        # The horizontal rules that separate the document's top-level
        # sections belong to the page, not to the section above them.
        body = body.rstrip("-\n ") if body.endswith("---") else body
        sections.append(
            RulesSection(
                level=level,
                title=heading,
                slug=slug,
                ancestors=tuple(ancestors),
                text=body.rstrip(),
            )
        )

    return RulesDocument(
        title=title,
        text=markdown.strip(),
        sections=tuple(sections),
    )


# The parse is cheap but it is asked for on every autocomplete
# keystroke, so it is cached against the file's timestamp -- which also
# means an edited ruleset is served without restarting the bot. The
# render fonts are the counter-example; see "Fonts" in docs/design/board-image.md.
_CACHE: dict[Path, tuple[int, RulesDocument]] = {}


def load_rules_document(path: Path = LIVING_RULES_PATH) -> RulesDocument:
    """The living rules, parsed. Raises OSError when the file is gone."""
    resolved = Path(path).resolve()
    stamp = resolved.stat().st_mtime_ns
    cached = _CACHE.get(resolved)
    if cached is not None and cached[0] == stamp:
        return cached[1]

    document = parse_rules_document(resolved.read_text(encoding="utf-8"))
    _CACHE[resolved] = (stamp, document)
    return document


def chunk_for_discord(
    text: str,
    limit: int = DISCORD_MESSAGE_LIMIT,
) -> list[str]:
    """Split markdown into messages Discord will accept.

    Breaks are taken at blank lines, so a table or a list arrives whole
    rather than in two halves that render as neither. A new top-level
    section always starts a new message: a chunk boundary is a visible
    seam in the channel and a section heading is where a seam belongs.
    """
    chunks: list[str] = []
    current: list[str] = []
    length = 0

    def flush() -> None:
        nonlocal current, length
        if current:
            chunks.append("\n\n".join(current).strip())
            current = []
            length = 0

    def add(block: str) -> None:
        nonlocal length
        current.append(block)
        length += len(block) + (2 if len(current) > 1 else 0)

    for block in re.split(r"\n\s*\n", for_discord(text)):
        block = block.strip("\n")
        if not block.strip():
            continue
        if block.startswith("## "):
            flush()
        if length and length + len(block) + 2 > limit:
            flush()
        if len(block) <= limit:
            add(block)
            continue

        # A single block over the limit -- the long bullet lists in
        # "Exhaustion and injury" are the only ones -- is split a line
        # at a time, and a line longer than a whole message is cut.
        for line in block.split("\n"):
            while len(line) > limit:
                flush()
                chunks.append(line[:limit])
                line = line[limit:]
            if length and length + len(line) + 1 > limit:
                flush()
            if current:
                current[-1] = f"{current[-1]}\n{line}"
                length += len(line) + 1
            else:
                add(line)

    flush()
    return [chunk for chunk in chunks if chunk]

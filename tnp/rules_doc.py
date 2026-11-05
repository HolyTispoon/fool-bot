"""
docs/tnp-rules.md by section, for `/tnp rules`.

The rules document is the one statement of TNP's rules
(docs/tnp-bot.md, decision 4), so the command reads that file rather
than a copy. A section is a numbered heading -- `## 6. Battle` or
`### 6.7 Damage` -- and its text runs to the next heading; the
unnumbered sections (the change log) are not served. Discord renders
neither a markdown table nor a link to a neighbouring file, so a table
becomes a code block of padded columns and a local link keeps its
words. An answer longer than one message is split at paragraphs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

RULES_PATH = Path(__file__).resolve().parent.parent / "docs" / "tnp-rules.md"

#: Discord's limit on one message.
MESSAGE_LIMIT = 2000

HEADING = re.compile(r"^(#{2,3})\s+(\d+(?:\.\d+)?)\.?\s+(.*?)\s*$")
ANY_HEADING = re.compile(r"^#{1,6}\s")
LOCAL_LINK = re.compile(r"\[([^\]]+)\]\((?!https?://)[^)]*\)")


@dataclass(frozen=True)
class Section:
    number: str
    title: str
    body: str

    @property
    def label(self) -> str:
        return f"TNP {self.number} {self.title}"


def parse(text: str) -> list[Section]:
    sections: list[Section] = []
    current: Optional[tuple[str, str]] = None
    lines: list[str] = []
    for line in text.splitlines():
        if ANY_HEADING.match(line):
            if current:
                sections.append(Section(current[0], current[1], "\n".join(lines).strip()))
            match = HEADING.match(line)
            current = (match.group(2), match.group(3)) if match else None
            lines = []
            continue
        lines.append(line)
    if current:
        sections.append(Section(current[0], current[1], "\n".join(lines).strip()))
    return sections


@lru_cache(maxsize=1)
def sections(path: Path = RULES_PATH) -> tuple[Section, ...]:
    return tuple(parse(path.read_text(encoding="utf-8")))


def find(query: str, path: Path = RULES_PATH) -> Optional[Section]:
    """A section by its number ("6.7", "TNP 6.7") or its title, any case."""
    needle = query.strip().lower().removeprefix("tnp").strip()
    for section in sections(path):
        if needle in (section.number, section.label.lower(), section.title.lower()):
            return section
    for section in sections(path):
        if needle and needle in section.title.lower():
            return section
    return None


def search(query: str, limit: int = 25, path: Path = RULES_PATH) -> list[Section]:
    needle = query.strip().lower()
    return [
        section for section in sections(path)
        if not needle or needle in section.label.lower()
    ][:limit]


def _table_block(rows: list[str]) -> str:
    cells = [
        [cell.strip() for cell in row.strip().strip("|").split("|")]
        for row in rows
        if not re.fullmatch(r"\s*\|?[\s:|-]+\|?\s*", row)
    ]
    widths = [max(len(row[index]) for row in cells if index < len(row)) for index in range(len(cells[0]))]
    out = ["  ".join(cell.ljust(widths[index]) for index, cell in enumerate(row)).rstrip() for row in cells]
    return "```\n" + "\n".join(out) + "\n```"


#: A line that starts something of its own rather than continuing the
#: paragraph above: a list item, a numbered item, a quote.
STARTS_ITEM = re.compile(r"^\s*(?:[-*]\s|\d+\.\s|>)")


def for_discord(body: str) -> str:
    """The section's markdown as Discord shows it: tables as code blocks,
    local links as their words, and the file's hard-wrapped lines joined
    back into their paragraphs and list items, since Discord keeps every
    line break."""
    out: list[str] = []
    table: list[str] = []
    joinable = False
    for line in body.splitlines():
        if line.lstrip().startswith("|"):
            table.append(line)
            joinable = False
            continue
        if table:
            out.append(_table_block(table))
            table = []
        line = LOCAL_LINK.sub(r"\1", line)
        if not line.strip() or line.strip() == ">":
            # A blank line, or a blank line inside a quote: a new paragraph.
            out.append(line.strip())
            joinable = False
            continue
        if joinable and not STARTS_ITEM.match(line):
            out[-1] += " " + line.strip()
        elif joinable and line.lstrip().startswith(">") and out[-1].lstrip().startswith(">"):
            out[-1] += " " + line.lstrip()[1:].strip()
        else:
            out.append(line.rstrip())
        joinable = True
    if table:
        out.append(_table_block(table))
    return "\n".join(out).strip()


def messages(section: Section, path: Path = RULES_PATH) -> list[str]:
    """The section as messages within Discord's limit: its heading, its
    text, and for a Law-level section the titles of the sections under
    it."""
    text = for_discord(section.body)
    if "." not in section.number:
        under = [
            other for other in sections(path)
            if other.number.startswith(section.number + ".")
        ]
        if under:
            text += "\n\n" + "\n".join(f"- {other.label}" for other in under)
    head = f"**{section.label}**"
    chunks: list[str] = []
    current = head
    for paragraph in text.split("\n\n"):
        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if len(candidate) <= MESSAGE_LIMIT:
            current = candidate
            continue
        if current:
            chunks.append(current)
        current = paragraph[:MESSAGE_LIMIT]
    if current:
        chunks.append(current)
    return chunks

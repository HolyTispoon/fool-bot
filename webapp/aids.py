"""
The reading room: the rules, the two rulebooks and the player aids, as
the page is handed them (step 11 of docs/web-app-next.md).

Everything here is something the model already draws or says; what the
web app adds is a place to open it. The rules are `rules_doc`'s
sections -- the same `RulesDocument` `/d12ball rules_search` answers
from -- headed with the Charter's numbers, which `rulebooks` gives at
build time and the Learn to Play cites. The books are
`rulebooks.book_bytes`, the PDF `scripts/build_rulebooks.py` writes.
The aids are the pictures the reference commands post, and which of
them a game gets is the engine's answer, never `game.mode` read here
-- docs/design/web-app.md, "The rules and the player aids".

No rule is decided in this file, and no second copy of the rules text
is kept: the page's HTML is rendered from the living rules each time
the file changes.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Callable, Optional, Sequence

from d12ball import rulebooks
from d12ball.components import (
    MANEUVER_TIER_BASIC,
    MANEUVER_TIER_GAMBIT,
    MANEUVER_TIER_WORDS,
    MANEUVER_TIERS,
    ManeuverCatalog,
    PlayerCatalog,
    load_species_abilities,
)
from d12ball.engine import RulesEngine
from d12ball.game import COLOR_TEAMS, SPECIES_TEAMS, D12BallGame, Team, team_display_name
from d12ball.render import TEAM_COLORS, render_maneuver_reference_image
from d12ball.role_cards import render_role_reference
from d12ball.rules_doc import HEADING_PATTERN, RulesDocument, RulesSection
from d12ball.species_cards import REFERENCE_FACES, render_species_reference_face

#: The two books a page may open, in the order it lists them.
BOOK_NAMES = ("charter", "learn-to-play")

#: Where the Charter's one figure, and every other the books carry, is
#: kept -- committed and regenerated whole (docs/design/rulebooks.md).
FIGURES_DIR = rulebooks.RULEBOOKS_DIR / "figures"
FIGURE_PREFIX = "rulebooks/figures/"

#: What a face of a team's cards is called where a person picks one.
#: The front is the card training and basic mode play; the advanced
#: face is the one `personal_abilities_apply` says an advanced game
#: holds (`player_cards.render_player_card_back`).
FACE_FRONT = "front"
FACE_ADVANCED = "advanced"
FACE_WORDS = {FACE_FRONT: "Training and basic", FACE_ADVANCED: "Advanced"}


# -- The rules ----------------------------------------------------------


@dataclass(frozen=True)
class RulesPage:
    """The living rules as the page reads them: the title, what comes
    before the first Law, and one entry per `RulesSection`."""

    title: str
    intro: str
    sections: tuple[dict, ...]


def charter_numbers(document: RulesDocument) -> dict[str, str]:
    """
    Every heading's number as the Charter's build gives it, by slug:
    `rulebooks.number_blocks` over the same text `rules_doc` parsed.
    The two agree on a slug already (`rulebooks.Heading.slug` is
    `rules_doc.slugify_heading`), which is what lets the page head a
    `RulesSection` with the number the Learn to Play cites.
    """
    blocks = rulebooks.parse_markdown(document.text)
    return rulebooks.number_blocks(blocks).headings


def section_number(section: RulesSection, numbers: dict[str, str]) -> Optional[str]:
    """
    The number a section is headed with: a Law's, or a Law's section's,
    and none where the Charter leaves it unnumbered -- the front
    matter, a Part, an Appendix (which its own title already names),
    and a heading below level 3, which shares its section's number
    rather than having one of its own.
    """
    if section.level not in (2, 3):
        return None
    number = numbers.get(section.slug)
    if number is None or number.startswith("Appendix"):
        return None
    return number


def rules_page(document: RulesDocument) -> RulesPage:
    """The rules, rendered. Every section is only its own text -- up to
    its first subsection -- since a `RulesSection` carries its
    subsections and the page shows each of them after it."""
    numbers = charter_numbers(document)
    link = _link_resolver(numbers)
    sections = tuple(
        {
            "slug": section.slug,
            "title": section.title,
            "level": section.level,
            "label": section.label,
            "number": section_number(section, numbers),
            "html": blocks_html(_own_body(section.text), link),
        }
        for section in document.sections
    )
    return RulesPage(
        title=document.title,
        intro=blocks_html(_intro(document.text), link),
        sections=sections,
    )


_PAGES: dict[int, tuple[RulesDocument, RulesPage]] = {}


def cached_rules_page(document: RulesDocument) -> RulesPage:
    """`rules_page`, once per parse. `rules_doc` re-parses when the file
    changes, which hands back a new document, so an edit to the rules
    is picked up without a restart the way the bot's commands pick it
    up."""
    held = _PAGES.get(id(document))
    if held is not None and held[0] is document:
        return held[1]
    page = rules_page(document)
    _PAGES.clear()
    _PAGES[id(document)] = (document, page)
    return page


def search(document: RulesDocument, query: str) -> list[dict]:
    """`RulesDocument.search` -- the answer `/d12ball rules_search`
    offers -- with each section's number beside its label."""
    numbers = charter_numbers(document)
    return [
        {
            "slug": section.slug,
            "label": section.label,
            "number": section_number(section, numbers),
        }
        for section in document.search(query)
    ]


def _own_body(text: str) -> str:
    lines = text.splitlines()[1:]
    for index, line in enumerate(lines):
        if HEADING_PATTERN.match(line):
            return "\n".join(lines[:index])
    return "\n".join(lines)


def _intro(text: str) -> str:
    """What the document says under its title, before the first
    section."""
    lines = text.splitlines()
    kept: list[str] = []
    for line in lines:
        found = HEADING_PATTERN.match(line)
        if found is None:
            kept.append(line)
        elif len(found.group(1)) >= 2:
            break
    return "\n".join(kept)


# -- The books' markdown, as HTML ---------------------------------------

LinkResolver = Callable[[str, str], str]

CODE = re.compile(r"`([^`]+)`")
PLACEHOLDER = re.compile("\x00(\\d+)\x00")


def _link_resolver(numbers: dict[str, str]) -> LinkResolver:
    """
    A link as the page draws it: to a heading, an anchor on the page
    with the number the book prints beside it (`text (6.4)`, as
    `rulebooks.build_story` resolves one); to the web, a link out; to
    a neighbouring file, the words alone, as the bot posts it.
    """

    def resolve(text: str, target: str) -> str:
        if target.startswith("#"):
            slug = target[1:]
            number = numbers.get(slug)
            suffix = f" ({number})" if number else ""
            return f'<a href="#{html.escape(slug)}">{text}{suffix}</a>'
        if target.startswith(("http://", "https://")):
            href = target.replace('"', "%22")
            return (
                f'<a href="{href}" target="_blank" rel="noopener">'
                f"{text}</a>"
            )
        return text

    return resolve


def inline_html(text: str, link: LinkResolver) -> str:
    """
    One line of the books' inline markup as HTML: escaped first, so
    nothing in the rules can be markup, then code, links, bold and
    italic -- the subset `rulebooks.inline_markup` reads, with its own
    patterns. A code span is held aside while the rest is read, so an
    asterisk inside one is a character.
    """
    held: list[str] = []

    def hold(found: re.Match) -> str:
        held.append(f"<code>{found.group(1)}</code>")
        return f"\x00{len(held) - 1}\x00"

    escaped = CODE.sub(hold, html.escape(text, quote=False))
    escaped = rulebooks.LINK_RE.sub(
        lambda found: link(found.group(1), found.group(2)), escaped,
    )
    escaped = rulebooks.BOLD_RE.sub(r"<strong>\1</strong>", escaped)
    escaped = rulebooks.ITALIC_RE.sub(r"<em>\1</em>", escaped)
    return PLACEHOLDER.sub(lambda found: held[int(found.group(1))], escaped)


def blocks_html(markdown: str, link: LinkResolver) -> str:
    """
    A stretch of the rules as HTML, read by `rulebooks.parse_markdown`
    -- the books' own subset, which raises on a line outside it rather
    than showing it wrong, so the page and the printed Charter fail on
    the same line.
    """
    return "".join(
        _block_html(block, link)
        for block in rulebooks.parse_markdown(markdown)
    )


ALIGN = {"LEFT": "left", "CENTER": "center", "RIGHT": "right"}


def _block_html(block, link: LinkResolver) -> str:
    if isinstance(block, rulebooks.Paragraph_):
        css = ' class="note"' if rulebooks.is_note(block) else ""
        return f"<p{css}>{inline_html(block.text, link)}</p>"
    if isinstance(block, rulebooks.ListBlock):
        return _list_html(block, link)
    if isinstance(block, rulebooks.TableBlock):
        rows = []
        for index, row in enumerate(block.rows):
            cell = "th" if index == 0 else "td"
            rows.append(
                "<tr>"
                + "".join(
                    f'<{cell} style="text-align:{ALIGN[align]}">'
                    f"{inline_html(text, link)}</{cell}>"
                    for text, align in zip(row, block.aligns)
                )
                + "</tr>"
            )
        return f'<div class="rules-table"><table>{"".join(rows)}</table></div>'
    if isinstance(block, rulebooks.QuoteBlock):
        return f"<blockquote>{inline_html(block.text, link)}</blockquote>"
    if isinstance(block, rulebooks.CodeBlock):
        return f"<pre><code>{html.escape(block.text)}</code></pre>"
    if isinstance(block, rulebooks.ImageBlock):
        caption = inline_html(block.caption, link)
        name = figure_name(block.path)
        if name is None:
            return f"<p><em>{caption}</em></p>"
        return (
            f'<figure><img src="/rules/figures/{html.escape(name)}" alt="">'
            f"<figcaption>{caption}</figcaption></figure>"
        )
    if isinstance(block, rulebooks.Heading):
        # A section's own body stops at its first heading, so this is
        # only ever the intro's -- which has none.
        level = min(max(block.level, 2), 6)
        return f"<h{level}>{inline_html(block.text, link)}</h{level}>"
    return ""


def _list_html(block, link: LinkResolver) -> str:
    tag = "ol" if block.ordered else "ul"
    items = "".join(
        "<li>"
        + inline_html(item.text, link)
        + "".join(_list_html(child, link) for child in item.children)
        + "</li>"
        for item in block.items
    )
    return f"<{tag}>{items}</{tag}>"


def figure_name(path: str) -> Optional[str]:
    """A figure the rules link, as the page serves it -- only a file
    in the figures folder, by its listed name."""
    if not path.startswith(FIGURE_PREFIX):
        return None
    name = path[len(FIGURE_PREFIX):]
    return name if name in figure_names() else None


def figure_names() -> set[str]:
    try:
        return {
            entry.name for entry in FIGURES_DIR.iterdir()
            if entry.suffix == ".png"
        }
    except OSError:
        return set()


def figure_path(name: str) -> Optional[Path]:
    return FIGURES_DIR / name if name in figure_names() else None


# -- The books ----------------------------------------------------------


def book_source(name: str) -> Optional[Path]:
    book = rulebooks.BOOKS.get(name)
    return None if book is None else book.source


def book_stamp(name: str) -> Optional[int]:
    """What a set book is kept against: its source's mtime, so an edit
    to the rules is served without a restart."""
    source = book_source(name)
    if source is None:
        return None
    try:
        return source.stat().st_mtime_ns
    except OSError:
        return None


def book_pdf(name: str) -> bytes:
    """One book, set in memory on letter paper -- the PDF
    `scripts/build_rulebooks.py` writes to `print/`, and never
    written there from here."""
    return rulebooks.book_bytes(rulebooks.BOOKS[name])


def books() -> list[dict]:
    return [
        {
            "name": name,
            "title": rulebooks.BOOKS[name].title,
            "url": f"/books/{name}.pdf",
        }
        for name in BOOK_NAMES
    ]


# -- The aids' pictures --------------------------------------------------


def _png(image) -> bytes:
    out = BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def maneuver_reference_png(catalog: ManeuverCatalog, tier: str) -> bytes:
    """The hexagon `/d12ball maneuver_reference` posts, at `tier`."""
    return render_maneuver_reference_image(catalog, tier).read()


def role_reference_png(catalog: PlayerCatalog) -> bytes:
    """The role card `/d12ball role_abilities_reference` posts."""
    return _png(render_role_reference(catalog.role_profiles))


def species_face_png(number: int) -> bytes:
    """One of the two faces `/d12ball species_abilities_reference`
    posts side by side, 1 or 2."""
    return _png(
        render_species_reference_face(
            load_species_abilities(), REFERENCE_FACES[number - 1],
        )
    )


SPECIES_FACE_COUNT = len(REFERENCE_FACES)


# -- What a page is offered ----------------------------------------------


def _maneuver(tier: str) -> dict:
    return {
        "tier": tier,
        "name": f"The {MANEUVER_TIER_WORDS[tier]} hexagon",
        "url": f"/aids/maneuvers/{tier}.png",
    }


def _species() -> list[dict]:
    return [
        {"name": f"Species card, face {number}", "url": f"/aids/species/{number}.png"}
        for number in range(1, SPECIES_FACE_COUNT + 1)
    ]


def team_card_url(team: Team, card_id: str, face: str) -> str:
    return f"/aids/team/{team.value}/{card_id}.png?face={face}"


def _team(catalog: PlayerCatalog, team: Team, faces: Sequence[str]) -> dict:
    players = catalog.teams[team].players
    return {
        "key": team.value,
        "name": team_display_name(team),
        "colour": TEAM_COLORS[team],
        "faces": [
            {
                "face": face,
                "name": FACE_WORDS[face],
                "cards": [
                    team_card_url(team, player.player_id, face)
                    for player in players
                ],
            }
            for face in faces
        ],
    }


def everything(engine: RulesEngine) -> dict:
    """
    The front door's reading room, with no game to ask: both hexagons
    named by tier, the species card, the role card, every team with
    both faces offered, the rules and the books.
    """
    catalog = engine.player_catalog
    return {
        "rules": "/rules",
        "books": books(),
        "maneuvers": [_maneuver(tier) for tier in MANEUVER_TIERS],
        "roles": "/aids/roles.png",
        "species": _species(),
        "teams": [
            _team(catalog, team, (FACE_FRONT, FACE_ADVANCED))
            for team in (*COLOR_TEAMS, *SPECIES_TEAMS)
            if team in catalog.teams
        ],
    }


def for_game(
    engine: RulesEngine, game: D12BallGame, seat: Optional[int],
) -> dict:
    """
    A room's reading room: the aids that game plays, each chosen by the
    model's answer -- the hexagon at `maneuver_reference_tier`, the
    species card only where `species_abilities_apply`, the team cards
    in the face `personal_abilities_apply` says the game holds. The
    three answers are handed over as well, so the page never decides
    one. The seat's own team comes first; an observer's are seat 1's
    and then seat 2's.
    """
    tier = engine.maneuver_reference_tier(game)
    species = engine.species_abilities_apply(game)
    advanced = engine.personal_abilities_apply(game)
    face = FACE_ADVANCED if advanced else FACE_FRONT
    picked = [
        (number, team)
        for number, team in ((1, game.player_1_team), (2, game.player_2_team))
        if team is not None
    ]
    picked.sort(key=lambda one: one[0] != seat)
    teams: list[Team] = []
    own: Optional[Team] = None
    for number, team in picked:
        team = Team(team)
        if number == seat:
            own = team
        if team not in teams and team in engine.player_catalog.teams:
            teams.append(team)
    return {
        "maneuver_tier": tier,
        "species_abilities": species,
        "advanced_cards": advanced,
        "rules": "/rules",
        "books": books(),
        "maneuvers": [_maneuver(tier)],
        "roles": "/aids/roles.png",
        "species": _species() if species else [],
        "teams": [
            dict(_team(engine.player_catalog, team, (face,)), yours=team == own)
            for team in teams
        ],
    }


def valid_tier(tier: str) -> bool:
    return tier in (MANEUVER_TIER_BASIC, MANEUVER_TIER_GAMBIT)


# -- The rules as a page ---------------------------------------------------


def rules_html(page: RulesPage) -> str:
    """
    `/rules`: the Charter's text on a page of its own, in the room's
    colours, with its contents and a search box over `/api/rules`. The
    sections are already HTML (`rules_page`); every title is escaped
    here.
    """
    contents = "".join(
        f'<li class="level-{section["level"]}"><a href="#{section["slug"]}">'
        f'{_numbered(section)}</a></li>'
        for section in page.sections
        if section["level"] <= 3
    )
    body = "".join(
        f'<section class="rules-section level-{section["level"]}" '
        f'id="{section["slug"]}">'
        f'<h{min(section["level"], 6)}>{_numbered(section)}</h{min(section["level"], 6)}>'
        f'{section["html"]}</section>'
        for section in page.sections
    )
    title = html.escape(page.title)
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <meta name="color-scheme" content="dark" />
    <title>{title} · D12 Ball</title>
    <link rel="stylesheet" href="/static/app.css" />
  </head>
  <body class="front rules-page">
    <main class="rules panel">
      <p class="quiet"><a href="/" class="linkish">&lsaquo; D12 Ball</a>
        · <a href="/books/charter.pdf" class="linkish" target="_blank" rel="noopener">The Charter as a PDF</a>
        · <a href="/books/learn-to-play.pdf" class="linkish" target="_blank" rel="noopener">Learn to Play</a></p>
      <h1>{title}</h1>
      <form class="rules-search" role="search" data-rules-search>
        <input class="chat-input" type="search" placeholder="Search the rules"
               aria-label="Search the rules" autocomplete="off" />
        <ol class="rules-results" hidden></ol>
      </form>
      {page.intro}
      <nav class="rules-contents" aria-label="Contents">
        <div class="panel-label">Contents</div>
        <ol>{contents}</ol>
      </nav>
      {body}
    </main>
    <script src="/static/aids.js"></script>
  </body>
</html>
"""


def _numbered(section: dict) -> str:
    title = inline_html(section["title"], lambda text, target: text)
    if section["number"] is None:
        return title
    return f'<span class="rules-number">{section["number"]}</span> {title}'

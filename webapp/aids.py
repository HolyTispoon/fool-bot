"""
The reading room: the rules, the Learn to Play and the player aids, as
the page is handed them (step 11 of docs/web-app-next.md, redrawn as
the Rules tab and the Reading Room in step 10 of
docs/web-app-redesign.md).

Everything here is something the model already draws or says; what the
web app adds is a place to open it. The rules are `rules_doc`'s
sections -- the same `RulesDocument` `/d12ball rules_search` answers
from -- with the Charter's numbers the file carries, the ones
`rulebooks.renumber` writes and the Learn to Play cites, and grouped by
Law. The Learn to Play is the book's own markdown read by the books'
own parser, with its figures. The aids are the pictures and the words the reference
commands post, and which of them a game gets is the engine's answer,
never `game.mode` read here -- docs/design/web-app.md, "The rules and
the player aids".

No rule is decided in this file, and no second copy of the rules text
is kept: the page's HTML is rendered from the living rules each time
the file changes. **No PDF is served** (the author, reviewing the
redesign, 2026-09-26): the books are read in the page.
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
    SPECIES_ORDER,
    ManeuverCatalog,
    PlayerCatalog,
    PlayerRole,
    load_species_abilities,
)
from d12ball.cards import matchup_rank_groups, role_abilities, time_cost
from d12ball.components import ManeuverDefinition
from d12ball.engine import RulesEngine
from d12ball.formatting import role_brackets
from d12ball.game import COLOR_TEAMS, SPECIES_TEAMS, D12BallGame, Team, team_display_name
from d12ball.render import (
    MANEUVER_DEFENSE_COLOR,
    MANEUVER_DEFENSE_COLOR_GAMBIT,
    MANEUVER_OFFENSE_COLOR,
    MANEUVER_OFFENSE_COLOR_GAMBIT,
    TEAM_COLORS,
    render_maneuver_reference_image,
)
from d12ball.role_cards import render_role_reference
from d12ball.rules_doc import HEADING_PATTERN, RulesDocument
from d12ball.species_cards import (
    REFERENCE_FACES,
    SPECIES_TEAM,
    render_species_reference_face,
)

#: Where the Charter's one figure, and every other the books carry, is
#: kept -- committed and regenerated whole (docs/design/rulebooks.md).
FIGURES_DIR = rulebooks.RULEBOOKS_DIR / "figures"
FIGURE_PREFIX = "rulebooks/figures/"

#: What a face of a team's cards is called where a person picks one.
#: The front is the card training and standard mode play; the advanced
#: face is the one `special_abilities_apply` says an advanced game
#: holds (`player_cards.render_player_card_back`).
FACE_FRONT = "front"
FACE_ADVANCED = "advanced"
FACE_WORDS = {FACE_FRONT: "Training and standard", FACE_ADVANCED: "Advanced"}


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
    Every heading's number as the Charter's build gives it -- a Law's,
    a section's, and an Appendix's letter (`Appendix B`) -- by the slug
    of its name without the number: `rulebooks.number_blocks` over the
    file with the numbers `renumber` wrote taken out, which is the text
    the book is built from. `rules_doc` names a section by that same
    slug, so the two agree however often the file is renumbered.
    """
    blocks = rulebooks.parse_markdown(rulebooks.unnumber(document.text))
    return rulebooks.number_blocks(blocks).headings


def page_anchors(document: RulesDocument) -> dict[str, str]:
    """
    Where a link in the file lands on the page: the file's links point
    at the anchor GitHub gives a numbered heading (`#64-the-skill-test`),
    and the page names each section by the slug of its name alone,
    which a renumbering does not move.
    """
    return {section.anchor: section.slug for section in document.sections}


def rules_page(document: RulesDocument) -> RulesPage:
    """The rules, rendered. Every section is only its own text -- up to
    its first subsection -- since a `RulesSection` carries its
    subsections and the page shows each of them after it."""
    link = _link_resolver(page_anchors(document))
    sections = tuple(
        {
            "slug": section.slug,
            "title": section.title,
            "level": section.level,
            "label": section.label,
            "number": section.number,
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
    return [
        {
            "slug": section.slug,
            "label": section.label,
            "number": section.number,
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


def _link_resolver(anchors: dict[str, str]) -> LinkResolver:
    """
    A link as the page draws it: to a heading, an anchor on the page
    (the number the book prints beside it is the file's own words,
    after the link); to the web, a link out; to a neighbouring file,
    the words alone, as the bot posts it.
    """

    def resolve(text: str, target: str) -> str:
        if target.startswith("#"):
            slug = anchors.get(target[1:], target[1:])
            return f'<a href="#{html.escape(slug)}">{text}</a>'
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


# -- The Charter, by Law ------------------------------------------------


def _title_html(title: str) -> str:
    """A heading's own words as HTML: its inline markup, no links."""
    return inline_html(title, lambda text, target: text)


def charter(document: RulesDocument) -> dict:
    """
    The living rules as the Rules tab and the Reading Room list them:
    the 21 Laws by their headings, each with its own text and its
    sections, then the appendices -- `rules_page`'s sections grouped by
    the Charter's own numbering, so what is a Law is what the build
    numbers as one and nothing the page decides. A Part heading is the
    `part` of the Laws under it; a heading below a section is set in
    that section's text, as the book sets it; what comes before the
    first Part (how to read the document) is `front`, and the
    Appendices, which the Charter letters rather than numbers, are
    `appendices` with their letter as their `label`.
    """
    held = _CHARTERS.get(id(document))
    if held is not None and held[0] is document:
        return held[1]
    page = cached_rules_page(document)
    numbers = charter_numbers(document)
    laws: list[dict] = []
    front: list[dict] = []
    appendices: list[dict] = []
    part: Optional[str] = None
    law: Optional[dict] = None
    section: Optional[dict] = None
    for one in page.sections:
        entry = {
            "slug": one["slug"],
            "number": one["number"],
            "title": _title_html(one["title"]),
            "html": one["html"],
        }
        if one["level"] == 2:
            section = None
            label = numbers.get(one["slug"], "")
            if one["number"] is not None:
                law = {**entry, "part": part, "sections": []}
                laws.append(law)
            elif label.startswith("Appendix"):
                law = {**entry, "label": label, "sections": []}
                appendices.append(law)
            elif one["title"].startswith("Part "):
                part = _title_html(one["title"])
                law = None
            else:
                law = {**entry, "sections": []}
                front.append(law)
        elif one["level"] == 3 and law is not None:
            section = entry
            law["sections"].append(section)
        elif law is not None:
            # A heading under a section is part of that section's text.
            held = section if section is not None else law
            level = min(max(one["level"], 4), 6)
            held["html"] += (
                f'<h{level} id="{html.escape(one["slug"])}">'
                f'{entry["title"]}</h{level}><div>{one["html"]}</div>'
            )
    found = {
        "title": html.escape(page.title),
        "intro": page.intro,
        "front": front,
        "laws": laws,
        "appendices": appendices,
    }
    # Once per parse, as `cached_rules_page`: `rules_doc` hands back a
    # new document when the file changes.
    _CHARTERS.clear()
    _CHARTERS[id(document)] = (document, found)
    return found


_CHARTERS: dict[int, tuple[RulesDocument, dict]] = {}


def citation(document: RulesDocument, slug: Optional[str]) -> Optional[dict]:
    """
    Where a refusal's Law points, as the page links it: the heading the
    model named (`RuleRefusal.law`), its Charter number and its title,
    and the Law it is under. `None` for no citation, and for a slug the
    rules no longer have -- a link to nowhere is worse than none, and
    `tests/test_rule_refusal_laws.py` fails first.
    """
    if not slug:
        return None
    found = charter(document)
    for law in (*found["laws"], *found["appendices"], *found["front"]):
        for one in (law, *law["sections"]):
            if one["slug"] == slug:
                return {
                    "slug": slug,
                    "number": one["number"],
                    "title": one["title"],
                    "law": law["slug"],
                    "law_number": law["number"],
                }
    return None


# -- The Learn to Play, in the page ------------------------------------------

#: A Law the Learn to Play cites, as it cites it: *(Law 6.4)*, or several
#: at once, *(Law 2.1, 2.2)*.
LAW_CITE = re.compile(r"\(Law ((?:\d+(?:\.\d+)*)(?:, \d+(?:\.\d+)*)*)\)")
CITED_NUMBER = re.compile(r"\d+(?:\.\d+)*")


def _cite_laws(markup: str, slugs: dict[str, str]) -> str:
    """Each number of a *(Law 6.4)* as a link to that heading in the
    Charter, by the number the build gives it; a number the Charter
    does not give stays words."""

    def link(number: re.Match) -> str:
        slug = slugs.get(number.group(0))
        if slug is None:
            return number.group(0)
        return (
            f'<a href="/rules#{html.escape(slug)}" data-rule="{html.escape(slug)}">'
            f"{number.group(0)}</a>"
        )

    def cite(found: re.Match) -> str:
        return f"(Law {CITED_NUMBER.sub(link, found.group(1))})"

    return LAW_CITE.sub(cite, markup)


def learn_to_play(document: RulesDocument) -> dict:
    """
    `docs/learn-to-play.md` as the page reads it: the book's own
    markdown, read by `rulebooks.parse_markdown` -- the books' subset,
    which raises on a line outside it -- with its figures served from
    the same folder the Charter's is, and every *(Law 6.4)* it cites a
    link into the Charter by the number the build gives. `contents` is
    its chapters, the level-2 headings, for the page to jump between.
    """
    source = rulebooks.BOOKS["learn-to-play"].source
    if source is None:
        raise OSError("docs/learn-to-play.md is missing from this checkout")
    text = source.read_text(encoding="utf-8")
    numbers = charter_numbers(document)
    slugs = {number: slug for slug, number in numbers.items()}
    link = _link_resolver(page_anchors(document))
    title = rulebooks.BOOKS["learn-to-play"].title
    parts: list[str] = []
    contents: list[dict] = []
    for block in rulebooks.parse_markdown(text):
        if isinstance(block, rulebooks.Heading):
            if block.level == 1:
                title = block.text
                continue
            words = inline_html(block.text, link)
            if block.level == 2:
                contents.append({"slug": block.slug, "title": words})
            level = min(block.level, 6)
            parts.append(
                f'<h{level} id="{html.escape(block.slug)}">{words}</h{level}>'
            )
            continue
        parts.append(_block_html(block, link))
    return {
        "title": html.escape(title),
        "contents": contents,
        "html": _cite_laws("".join(parts), slugs),
    }


_LEARN: dict[str, tuple[tuple, dict]] = {}


def cached_learn_to_play(document: RulesDocument) -> dict:
    """`learn_to_play`, again only when the book or the rules it cites
    have changed -- its source's mtime and the parse of the rules."""
    source = rulebooks.BOOKS["learn-to-play"].source
    try:
        stamp = (source.stat().st_mtime_ns if source else None, id(document))
    except OSError:
        stamp = (None, id(document))
    held = _LEARN.get("book")
    if held is not None and held[0] == stamp:
        return held[1]
    book = learn_to_play(document)
    _LEARN["book"] = (stamp, book)
    return book


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


def maneuver_card(
    catalog: ManeuverCatalog,
    players: PlayerCatalog,
    maneuver: ManeuverDefinition,
    side: str,
    tiers: Sequence[str],
) -> dict:
    """
    Everything a maneuver's printed card says, as words and its
    diagram, for the References and the hand's pill
    (`present.maneuver_pill`): the rank as the card's corner prints it
    (`O1`, `D2`), the name, the tier's word, the time it charges, the
    diagram (the card's own, cut from its face:
    `pictures.maneuver_diagram_png`), the effect in the sheet's words,
    never cut down here, and the card's foot and ability rows --

    - **`matchups`**: the opposing cards it beats, ties and loses to,
      by rank (`cards.matchup_rank_groups`, the card's own reading:
      rank alone decides), holding only the tiers asked for;
    - **`abilities`**: the role rows the card prints under its effect
      (`cards.role_abilities`: every role whose ability names the card,
      and the notes placed there by hand; none on a gambit), the card's
      capitals said as words.
    """
    is_offense = side == "offense"
    groups = matchup_rank_groups(catalog, maneuver, is_offense)
    return {
        "key": maneuver.key,
        "name": maneuver.name,
        "rank": f"{'O' if is_offense else 'D'}{maneuver.rank}",
        # The printed card's own colour: its side's, a darker shade for
        # an advanced card (`cards.render_maneuver_card`).
        "colour": CARD_COLOURS[is_offense, maneuver.is_gambit],
        "tier": maneuver.tier,
        "gambit": maneuver.is_gambit,
        # What the tag beside an advanced card says -- the tier's word,
        # never "gambit": the card is an advanced maneuver and a gambit
        # is playing one (the author).
        "tier_word": MANEUVER_TIER_WORDS[maneuver.tier],
        # The card's own pill, "TIME · 1" (`cards.time_cost`): the sheet's number,
        # never its unit -- the unit is just time (the author, 2026-10-01).
        "time": f"Time · {time_cost(maneuver)}",
        "effect": maneuver.effect,
        "diagram": maneuver_diagram_url(maneuver.key),
        "matchups": [
            {
                "said": said,
                "names": [one.name for one in pair if one.tier in tiers],
            }
            for said, (_, pair) in zip(MATCHUP_WORDS, groups)
        ],
        "abilities": [
            {"who": who.capitalize(), "text": text}
            for who, text in role_abilities(players, maneuver)
        ],
    }


#: A maneuver card's colour, by (offense, advanced): the printed card's.
CARD_COLOURS = {
    (True, False): MANEUVER_OFFENSE_COLOR,
    (True, True): MANEUVER_OFFENSE_COLOR_GAMBIT,
    (False, False): MANEUVER_DEFENSE_COLOR,
    (False, True): MANEUVER_DEFENSE_COLOR_GAMBIT,
}

#: The card's foot, as the References and the pill say it.
MATCHUP_WORDS = ("Beats", "Ties", "Loses to")


def maneuver_diagram_url(key: str) -> str:
    """Where a maneuver's diagram is served -- open to anybody, like
    every aid, since it is printed on the card."""
    return f"/aids/maneuver-diagram/{key}.png"


def maneuver_rows(
    catalog: ManeuverCatalog, players: PlayerCatalog, tiers: Sequence[str],
) -> list[dict]:
    """
    The maneuvers as two tables, the offense's and then the defense's,
    each row the whole of a printed card (`maneuver_card`), so the
    References carry every detail the hand's pill leaves to its hover
    and the card face itself (the author, 2026-10-01). The rows are in
    the catalog's order -- by rank, a rank's gambit under its basic card
    -- and hold only the tiers asked for; the matchups name the opposing
    cards of those tiers too, because rank alone decides who wins.
    `beats` is the first of them as one string, as the table read it.
    """
    tables = []
    for side in ("offense", "defense"):
        rows = []
        for maneuver in catalog.side(side):
            if maneuver.tier not in tiers:
                continue
            row = maneuver_card(catalog, players, maneuver, side, tiers)
            row["beats"] = " / ".join(row["matchups"][0]["names"])
            rows.append(row)
        tables.append({"side": side, "name": side.title(), "rows": rows})
    return tables


def roles(catalog: PlayerCatalog) -> list[dict]:
    """
    The six roles as a table, from the numbers the role card is drawn
    from (`role_profiles`): the role's badge (the emoji the bot draws
    it with), its name, its two skills and its ability in the sheet's
    own short column (`short_ability`, never cut down here).
    """
    rows = []
    for role in PlayerRole:
        profile = catalog.role_profiles.get(role)
        if profile is None:
            continue
        rows.append(
            {
                "role": role.value,
                "name": role.value.title(),
                "badge": f"/emoji/role_{role.value}.png",
                "letters": role_brackets(role),
                "offense": profile.offense,
                "defense": profile.defense,
                "ability": profile.short_ability,
            }
        )
    return rows


def species_rows() -> list[dict]:
    """
    The four species abilities as a table, from `species.json` -- the
    same data the species card is drawn from: the species team in its
    colour with the coloured icon, the ability's name and its short
    wording.
    """
    abilities = load_species_abilities()
    rows = []
    for key in SPECIES_ORDER:
        ability = abilities.get(key)
        if ability is None:
            continue
        team = SPECIES_TEAM[key]
        rows.append(
            {
                "key": key,
                "team": team_display_name(team),
                "colour": TEAM_COLORS[team],
                "icon": f"/species/{key}_color.png",
                "name": ability["name"],
                "ability": ability.get("ability_short") or ability["ability"],
            }
        )
    return rows


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
    The Reading Room's aids, with no game to ask: both hexagons named
    by tier, all twelve maneuvers, the role table and card, the species
    table and card, every team with both faces offered, and the rules.
    """
    catalog = engine.player_catalog
    return {
        "rules": "/rules",
        "maneuver_rows": maneuver_rows(
            engine.maneuver_catalog, engine.player_catalog, MANEUVER_TIERS,
        ),
        "role_rows": roles(catalog),
        "species_rows": species_rows(),
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
    in the face `special_abilities_apply` says the game holds. The
    three answers are handed over as well, so the page never decides
    one. The seat's own team comes first; an observer's are seat 1's
    and then seat 2's.
    """
    tier = engine.maneuver_reference_tier(game)
    species = engine.species_abilities_apply(game)
    advanced = engine.special_abilities_apply(game)
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
        # The References in the Rules tab: the maneuvers at the game's
        # tier, the six basic ones always, the role table, and the
        # species table only where the game plays them.
        "maneuver_rows": maneuver_rows(
            engine.maneuver_catalog, engine.player_catalog,
            game_tiers(engine, game),
        ),
        "role_rows": roles(engine.player_catalog),
        "species_rows": species_rows() if species else [],
        "maneuvers": [_maneuver(tier)],
        "roles": "/aids/roles.png",
        "species": _species() if species else [],
        "teams": [
            dict(_team(engine.player_catalog, team, (face,)), yours=team == own)
            for team in teams
        ],
    }


def game_tiers(engine: RulesEngine, game: D12BallGame) -> tuple[str, ...]:
    """The maneuver tiers a game plays: the basic cards always, and the
    advanced ones where `maneuver_reference_tier` says so."""
    tier = engine.maneuver_reference_tier(game)
    if tier == MANEUVER_TIER_BASIC:
        return (MANEUVER_TIER_BASIC,)
    return (MANEUVER_TIER_BASIC, tier)


def valid_tier(tier: str) -> bool:
    return tier in (MANEUVER_TIER_BASIC, MANEUVER_TIER_GAMBIT)


# -- The Reading Room -------------------------------------------------------


def _law_heading(law: dict) -> str:
    # An appendix's title already carries its letter.
    number = law.get("number")
    mark = f'<span class="law-mark">Law {number}</span>' if number else ""
    return f"<h2>{mark}{law['title']}</h2>"


def _law_html(law: dict) -> str:
    """One Law as the Reading Room sets it: its heading, its own text,
    and each section under its number."""
    part = (
        f'<div class="law-part">{law["part"]}</div>' if law.get("part") else ""
    )
    sections = "".join(
        f'<section class="rules-section" id="{html.escape(one["slug"])}">'
        f'<h3>{_numbered_mark(one["number"])}{one["title"]}</h3>{one["html"]}'
        f"</section>"
        for one in law["sections"]
    )
    return (
        f'<article class="law" id="{html.escape(law["slug"])}">{part}'
        f'{_law_heading(law)}{law["html"]}{sections}</article>'
    )


def _numbered_mark(number: Optional[str]) -> str:
    return f'<span class="rules-number">{number}</span>' if number else ""


def _contents_html(found: dict) -> str:
    rows = [
        f'<li><a href="#{html.escape(law["slug"])}" data-rule="{html.escape(law["slug"])}">'
        f'<span class="toc-number">{law["number"]}</span>'
        f'<span>{law["title"]}</span></a></li>'
        for law in found["laws"]
    ]
    rows += [
        f'<li class="appendix"><a href="#{html.escape(law["slug"])}" data-rule="{html.escape(law["slug"])}">'
        f'<span class="toc-number"></span><span>{law["title"]}</span></a></li>'
        for law in found["appendices"]
    ]
    return "".join(rows)


def _maneuver_entry_html(one: dict) -> str:
    """One maneuver in the References: the whole of its printed card,
    as `webapp/static/aids.js` draws it in the Rules tab."""
    tag = (
        f'<span class="tier-tag">{html.escape(one["tier_word"])}</span>'
        if one["gambit"] else ""
    )
    matchups = "".join(
        f'<dt>{html.escape(row["said"])}</dt>'
        f'<dd>{html.escape(" / ".join(row["names"]))}</dd>'
        for row in one["matchups"]
    )
    abilities = "".join(
        f'<p class="ref-ability"><b>{html.escape(row["who"])}</b> '
        f'{html.escape(row["text"])}</p>'
        for row in one["abilities"]
    )
    return (
        f'<div class="ref-maneuver" style="--card: {one["colour"]}">'
        f'<div class="ref-maneuver-head"><span class="pill-rank">{one["rank"]}</span>'
        f'<span class="ref-maneuver-name">{html.escape(one["name"])}</span>{tag}'
        f'<span class="pill-time">{html.escape(one["time"])}</span></div>'
        f'<img class="ref-diagram" src="{one["diagram"]}" alt="" loading="lazy">'
        f'<p class="ref-effect">{html.escape(one["effect"])}</p>'
        f'<dl class="pill-matchups">{matchups}</dl>{abilities}</div>'
    )


def references_html(offered: dict) -> str:
    """
    The References column: the maneuvers table, the roles table and
    the species table -- the Rules tab draws the same three from the
    same dict (`webapp/static/aids.js`).
    """
    maneuvers = "".join(
        f'<div class="ref-maneuvers"><div class="ref-side">{html.escape(table["name"])}</div>'
        + "".join(_maneuver_entry_html(one) for one in table["rows"])
        + "</div>"
        for table in offered["maneuver_rows"]
    )
    roles = "".join(
        f'<tr><td><img class="emoji" src="{one["badge"]}" alt="{html.escape(one["letters"])}"></td>'
        f'<td>{html.escape(one["name"])}</td>'
        f'<td class="num">{one["offense"]}</td><td class="num">{one["defense"]}</td>'
        f'<td class="ability">{html.escape(one["ability"])}</td></tr>'
        for one in offered["role_rows"]
    )
    species = "".join(
        f'<tr><td><img class="emoji" src="{one["icon"]}" alt=""></td>'
        f'<td><span class="species-team" style="color:{one["colour"]}">'
        f'{html.escape(one["team"])}</span>'
        f'<span class="ability-name">{html.escape(one["name"])}</span></td>'
        f'<td class="ability">{html.escape(one["ability"])}</td></tr>'
        for one in offered["species_rows"]
    )
    return (
        '<div class="panel-label">Maneuvers</div>'
        f"{maneuvers}"
        '<div class="panel-label">Roles</div>'
        '<table class="ref-table"><tr><th></th><th>Role</th><th>OFF</th><th>DEF</th><th>Ability</th></tr>'
        f"{roles}</table>"
        + (
            '<div class="panel-label">Species</div>'
            '<table class="ref-table"><tr><th></th><th>Species</th><th>Ability</th></tr>'
            f"{species}</table>"
            if species else ""
        )
    )


def rules_html(document: RulesDocument, offered: dict) -> str:
    """
    `/rules`, the Reading Room (step 10 of docs/web-app-redesign.md):
    the Laws down the left, the Law text in the middle, the References
    on the right, with a search over `/api/rules` and chips for the
    Learn to Play and the rosters, which `aids.js` fetches. The Charter
    and the References are set here, so the page reads without a
    script; every title is escaped, and the text is `rules_page`'s.
    """
    found = charter(document)
    laws = "".join(
        _law_html(law)
        for law in (*found["front"], *found["laws"], *found["appendices"])
    )
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <meta name="color-scheme" content="dark" />
    <title>The Reading Room · D12 Ball</title>
    <link rel="icon" type="image/png" href="/static/favicon.png" />
    <link rel="stylesheet" href="/static/app.css" />
  </head>
  <body class="reading-room" data-view="charter">
    <header class="topbar room-bar">
      <div class="topbar-title">
        <a href="/" class="back" data-back>&lsaquo; Master Lobby</a>
        <span class="topbar-divider" aria-hidden="true"></span>
        <span class="reading-title">The Reading Room</span>
      </div>
      <div class="topbar-end">
        <form class="rules-search" role="search" data-rules-search>
          <input class="search-input" type="search"
                 placeholder="Search everything: High Pass, own goal, Volatile…"
                 aria-label="Search the rules" autocomplete="off" />
          <ol class="rules-results" hidden></ol>
        </form>
        <nav class="chips" aria-label="Read">
          <button type="button" class="chip-tab" data-view="charter">The Charter</button>
          <button type="button" class="chip-tab" data-view="learn">Learn to Play</button>
          <button type="button" class="chip-tab" data-view="references">References</button>
          <button type="button" class="chip-tab" data-view="rosters">Rosters</button>
        </nav>
      </div>
    </header>
    <div class="reading">
      <nav class="reading-contents" aria-label="The Laws">
        <ol>{_contents_html(found)}</ol>
      </nav>
      <main class="reading-text rules">
        <section class="reading-view" data-for="charter">
          <div class="law-eyebrow">{found["title"]}</div>
          <div class="rules-intro">{found["intro"]}</div>
          {laws}
        </section>
        <section class="reading-view" data-for="learn" hidden></section>
        <section class="reading-view" data-for="rosters" hidden></section>
      </main>
      <aside class="reading-refs" id="references" aria-label="References">
        {references_html(offered)}
      </aside>
    </div>
    <script src="/static/aids.js"></script>
  </body>
</html>
"""

"""
`/codex card` and `/codex rules`: a card's picture, its text and
Sirlin's rulings on it, and a keyword's rulings -- the official rules of
the game, read from the imported data (docs/codex-bot.md, decision 12).
No rulebook text is bundled, nothing here is an embed, and both answers
link the card database.
"""

from __future__ import annotations

from typing import Callable

import discord
from discord import app_commands

from codex.cards import Card, Hero, catalog
from codex.rulings import Ruling, keyword_entry, keywords, rulings_for

DATABASE_URL = "http://codexcarddb.com"

#: Discord's limit on a message's text.
MESSAGE_LIMIT = 2000


def card_url(slug: str) -> str:
    return f"{DATABASE_URL}/card/{slug}"


def keyword_url(slug: str) -> str:
    return f"{DATABASE_URL}/ruling/{slug}"


def type_line(card: Card | Hero) -> str:
    """"Neutral Bashing Unit -- Contraption, Tech III"."""
    if isinstance(card, Hero):
        kind = " ".join(part for part in (card.color, card.spec, "Hero") if part)
        return f"{kind} -- {card.subtype}" if card.subtype else kind
    kind = " ".join(part for part in (card.color, card.spec, card.type) if part)
    details = [card.subtype] if card.subtype else []
    if card.tech_level and card.is_unit:
        details.append(f"Tech {'I' * card.tech_level}")
    return f"{kind} -- {', '.join(details)}" if details else kind


def numbers_line(card: Card | Hero) -> str:
    """The cost, and a unit's or building's ATK and HP."""
    parts = [] if card.cost is None else [f"Cost {card.cost}"]
    if isinstance(card, Card):
        if card.atk is not None and card.hp is not None:
            parts.append(f"{card.atk}/{card.hp}")
        elif card.hp is not None:
            parts.append(f"{card.hp} HP")
    else:
        parts.append(f"max level {card.max_level}")
    return " · ".join(parts)


def text_lines(card: Card | Hero) -> list[str]:
    if isinstance(card, Hero):
        lines = []
        for band in card.bands:
            lines.append(f"**Level {band.min_level}+** {band.atk}/{band.hp}")
            lines.extend(f"> {line}" for line in band.text)
        return lines
    return [f"> {line}" for line in card.text]


def ruling_line(ruling: Ruling) -> str:
    who = ", ".join(part for part in (ruling.author, ruling.date) if part)
    return f"- *{who}*: {ruling.text}" if who else f"- {ruling.text}"


def unrendered(text: str) -> str:
    return text


def fit(
    head: list[str],
    rulings: tuple[Ruling, ...],
    tail: str,
    render: Callable[[str], str],
) -> str:
    """
    The answer, its tokens rendered by `render`, with as many rulings as
    fit Discord's limit -- measured after rendering, since an emoji is
    longer than its token; the rest are counted and left to the link.
    """
    lines = [render(line) for line in head]
    if rulings:
        lines.append(f"**Rulings** ({len(rulings)})")
    for shown, ruling in enumerate(rulings):
        candidate = render(ruling_line(ruling))
        rest = len(rulings) - shown
        more = f"- ...and {rest} more at the link."
        if len("\n".join([*lines, candidate, more, tail])) > MESSAGE_LIMIT:
            lines.append(more)
            break
        lines.append(candidate)
    lines.append(tail)
    return "\n".join(lines)[:MESSAGE_LIMIT]


def card_answer(slug: str, render: Callable[[str], str] = unrendered) -> str:
    """`/codex card`'s text, its tokens rendered by `render`."""
    card = catalog().by_slug(slug)
    head = [f"**{card.name}**", type_line(card), numbers_line(card), *text_lines(card)]
    return fit(head, rulings_for(slug), f"<{card_url(slug)}>", render)


def keyword_answer(
    keyword: str, render: Callable[[str], str] = unrendered,
) -> str | None:
    """`/codex rules`'s text, its tokens rendered by `render`, or None
    for a keyword the rulings do not name."""
    entry = keyword_entry(keyword)
    if entry is None:
        return None
    head = [f"**{entry.name}**"]
    if entry.ability_text:
        head.append(f"> {entry.ability_text}")
    head.append("Sirlin's rulings are the official rules of the game.")
    return fit(head, entry.rulings, f"<{keyword_url(entry.slug)}>", render)


class ReferenceMixin:
    @app_commands.command(name="card", description="Show a Codex card, its text and Sirlin's rulings on it.")
    @app_commands.describe(name="The card's name")
    async def card(self, interaction: discord.Interaction, name: str) -> None:
        slug = catalog().find(name)
        if slug is None:
            await interaction.response.send_message(
                f"No card is called {name!r}. Pick one from the list as you type.",
                ephemeral=True,
            )
            return
        await self.tokens.refresh()
        text = card_answer(slug, self.tokens.render)
        picture = catalog().by_slug(slug).picture
        if picture is not None and picture.is_file():
            await interaction.response.send_message(
                text, file=discord.File(picture, filename=f"{slug}.jpg"),
            )
        else:
            await interaction.response.send_message(text)

    @card.autocomplete("name")
    async def card_autocomplete(
        self, interaction: discord.Interaction, current: str,
    ) -> list[app_commands.Choice[str]]:
        names = catalog()
        return [
            app_commands.Choice(name=names.name(slug)[:100], value=slug)
            for slug in names.search(current)
        ]

    @app_commands.command(name="rules", description="Sirlin's official rulings on a Codex keyword.")
    @app_commands.describe(keyword="The keyword, such as Overpower or Flying")
    async def rules(self, interaction: discord.Interaction, keyword: str) -> None:
        await self.tokens.refresh()
        answer = keyword_answer(keyword, self.tokens.render)
        if answer is None:
            await interaction.response.send_message(
                f"No ruling names {keyword!r}. Pick a keyword from the list as you type.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(answer)

    @rules.autocomplete("keyword")
    async def rules_autocomplete(
        self, interaction: discord.Interaction, current: str,
    ) -> list[app_commands.Choice[str]]:
        needle = current.strip().lower()
        return [
            app_commands.Choice(name=entry.name[:100], value=entry.slug)
            for entry in sorted(keywords(), key=lambda entry: entry.name)
            if needle in entry.name.lower()
        ][:25]

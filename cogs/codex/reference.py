"""
`/codex card`, `/codex spec`, `/codex color` and `/codex rules`: a card's picture -- with its text and
Sirlin's rulings on it under the picture, each only when asked for --
and a keyword's reminder text, with its rulings, the official rules of
the game, when asked for; both read from the imported data (docs/codex-bot.md, decision 12). No rulebook text is
bundled, nothing here is an embed, and both answers link the card
database. `/codex spec` and `/codex color` are pictures of many cards
at once -- a spec's hero and its twelve codex cards, and a colour's
starting deck and every spec of it.
"""

from __future__ import annotations

import asyncio
import io
import logging
import time
from typing import Callable

import discord
from discord import app_commands

from codex.cards import COLOR_DECK_NAMES, LANDED_COLORS, Card, Hero, catalog
from codex.render import bundled, bundled_bytes, render_cards
from codex.rulings import Ruling, keyword_entry, keywords, rulings_for
from cogs.codex_helpers import elapsed_ms

LOGGER = logging.getLogger(__name__)

DATABASE_URL = "http://codexcarddb.com"

#: Discord's limit on a message's text.
MESSAGE_LIMIT = 2000


def card_url(slug: str) -> str:
    return f"{DATABASE_URL}/card/{slug}"


def keyword_url(slug: str) -> str:
    return f"{DATABASE_URL}/ruling/{slug}"


def type_line(card: Card | Hero) -> str:
    """"Neutral Bashing Unit (Contraption, Tech III)"."""
    if isinstance(card, Hero):
        kind = " ".join(part for part in (card.color, card.spec, "Hero") if part)
        return f"{kind} ({card.subtype})" if card.subtype else kind
    kind = " ".join(part for part in (card.color, card.spec, card.type) if part)
    details = [card.subtype] if card.subtype else []
    if card.tech_level and card.is_unit:
        details.append(f"Tech {'I' * card.tech_level}")
    return f"{kind} ({', '.join(details)})" if details else kind


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


def card_text(card: Card | Hero) -> list[str]:
    """The card as words: its name, type line, numbers and printed text."""
    return [f"**{card.name}**", type_line(card), numbers_line(card), *text_lines(card)]


def card_answer(
    slug: str,
    render: Callable[[str], str] = unrendered,
    *,
    text: bool,
    rulings: bool,
) -> str | None:
    """
    `/codex card`'s words, its tokens rendered by `render`: the card as
    text where `text` asks for it, Sirlin's rulings where `rulings` does,
    and the database's page under whichever is there. None where neither
    is asked -- the picture alone is the answer.
    """
    if not text and not rulings:
        return None
    head = card_text(catalog().by_slug(slug)) if text else []
    return fit(head, rulings_for(slug) if rulings else (), f"<{card_url(slug)}>", render)


def keyword_answer(
    keyword: str,
    render: Callable[[str], str] = unrendered,
    *,
    rulings: bool,
) -> str | None:
    """
    `/codex rules`'s text, its tokens rendered by `render`: the keyword
    and its reminder text, Sirlin's rulings where `rulings` asks for
    them -- or where the keyword has no reminder text, since a lookup
    that shows nothing answers nothing -- and the database's page under
    it. None for a keyword the rulings do not name.
    """
    entry = keyword_entry(keyword)
    if entry is None:
        return None
    head = [f"**{entry.name}**"]
    if entry.ability_text:
        head.append(f"> {entry.ability_text}")
    shown = entry.rulings if rulings or not entry.ability_text else ()
    if shown:
        head.append("Sirlin's rulings are the official rules of the game.")
    return fit(head, shown, f"<{keyword_url(entry.slug)}>", render)


#: How many cards a row of `/codex spec`'s picture holds: its thirteen
#: in two rows, rather than one too wide to read on a phone.
SPEC_COLUMNS = 7
#: `/codex color`'s: a spec's hero and twelve cards to a row, so each
#: row is one spec and the starting deck the row above them.
COLOR_COLUMNS = 13


def spec_caption(spec: str) -> str | None:
    """`/codex spec`'s line above its picture, or None for a spec no
    landed hero has."""
    for hero in catalog().specs():
        if hero.spec.lower() == spec.strip().lower():
            return f"**{hero.spec}** ({hero.color}): {hero.name} and the spec's twelve codex cards."
    return None


def color_caption(color: str) -> str | None:
    """`/codex color`'s line above its picture, or None for a colour
    that is not landed."""
    key = color.strip().lower()
    if key not in LANDED_COLORS:
        return None
    specs = sorted(hero.spec for hero in catalog().specs() if (hero.color or "").lower() == key)
    named = f"**{key.title()}**" + (f" ({COLOR_DECK_NAMES[key]})" if key in COLOR_DECK_NAMES else "")
    joined = specs[0] if len(specs) == 1 else ", ".join(specs[:-1]) + f" and {specs[-1]}"
    return f"{named}: the starting deck, then {joined}, each its hero first."


COLOR_CHOICES = [
    app_commands.Choice(name=color.title(), value=color) for color in LANDED_COLORS
]


class ReferenceMixin:
    @app_commands.command(
        name="card",
        description="Show a Codex card's picture; its text and Sirlin's rulings on request.",
    )
    @app_commands.describe(
        name="The card's name",
        text="Add the card's text under the picture",
        rulings="Add Sirlin's rulings on the card under the picture",
        public="Post it in the channel for everyone, rather than to you alone",
    )
    async def card(
        self,
        interaction: discord.Interaction,
        name: str,
        text: bool = False,
        rulings: bool = False,
        public: bool = False,
    ) -> None:
        slug = catalog().find(name)
        if slug is None:
            await interaction.response.send_message(
                f"No card is called {name!r}. Pick one from the list as you type.",
                ephemeral=True,
            )
            return
        picture = catalog().by_slug(slug).picture
        if picture is not None and not bundled(picture):
            picture = None
        await self.tokens.refresh()
        # The picture is the answer, and the words go under it. Discord
        # draws a message's text above its attachment, so they are a
        # follow-up to the picture's response -- a second message that
        # sits straight beneath it. A card whose picture is not in the
        # checkout is answered with its text whether or not that was
        # asked for. The answer is the asker's alone unless `public`
        # says otherwise, and its follow-up goes the same way.
        ephemeral = not public
        words = card_answer(
            slug, self.tokens.render, text=text or picture is None, rulings=rulings,
        )
        if picture is None:
            await interaction.response.send_message(words, ephemeral=ephemeral)
            return
        # The file's bytes from memory, or off the event loop the first
        # time: never opened on it (`codex.render.bundled_bytes`).
        started = time.perf_counter()
        data = await asyncio.to_thread(bundled_bytes, picture)
        read = elapsed_ms(started)
        started = time.perf_counter()
        await interaction.response.send_message(
            file=discord.File(io.BytesIO(data), filename=picture.name), ephemeral=ephemeral,
        )
        LOGGER.info("Codex card %s: %d KB read in %d ms, sent in %d ms",
                    slug, len(data) // 1024, read, elapsed_ms(started))
        if words:
            await interaction.followup.send(words, ephemeral=ephemeral)

    @card.autocomplete("name")
    async def card_autocomplete(
        self, interaction: discord.Interaction, current: str,
    ) -> list[app_commands.Choice[str]]:
        names = catalog()
        return [
            app_commands.Choice(name=names.name(slug)[:100], value=slug)
            for slug in names.search(current)
        ]

    async def send_cards(self, interaction: discord.Interaction, caption: str,
                         groups: list[list[str]], columns: int, filename: str,
                         public: bool) -> None:
        """A picture of many cards, its caption above it, the asker's
        alone unless `public` -- drawn off the event loop."""
        started = time.perf_counter()
        data = await asyncio.to_thread(render_cards, groups, columns)
        drawn = elapsed_ms(started)
        started = time.perf_counter()
        await interaction.response.send_message(
            caption, file=discord.File(io.BytesIO(data), filename=filename),
            ephemeral=not public,
        )
        LOGGER.info("Codex %s: %d KB drawn in %d ms, sent in %d ms",
                    filename, len(data) // 1024, drawn, elapsed_ms(started))

    @app_commands.command(
        name="spec",
        description="Show a Codex spec's hero and all twelve of its codex cards.",
    )
    @app_commands.describe(
        spec="The spec, such as Anarchy or Bashing",
        public="Post it in the channel for everyone, rather than to you alone",
    )
    async def spec(
        self, interaction: discord.Interaction, spec: str, public: bool = False,
    ) -> None:
        caption = spec_caption(spec)
        if caption is None:
            await interaction.response.send_message(
                f"No spec is called {spec!r}. Pick one from the list as you type.",
                ephemeral=True,
            )
            return
        key = spec.strip().lower()
        await self.send_cards(interaction, caption, [catalog().spec_sheet(key)],
                              SPEC_COLUMNS, f"codex_spec_{key}.webp", public)

    @spec.autocomplete("spec")
    async def spec_autocomplete(
        self, interaction: discord.Interaction, current: str,
    ) -> list[app_commands.Choice[str]]:
        needle = current.strip().lower()
        return [
            app_commands.Choice(name=f"{hero.spec} ({hero.color})", value=hero.spec.lower())
            for hero in catalog().specs()
            if needle in hero.spec.lower() or needle in (hero.color or "").lower()
        ][:25]

    @app_commands.command(
        name="color",
        description="Show every card of a Codex colour: its starting deck and each spec.",
    )
    @app_commands.describe(
        color="The colour",
        public="Post it in the channel for everyone, rather than to you alone",
    )
    @app_commands.choices(color=COLOR_CHOICES)
    async def color(
        self, interaction: discord.Interaction, color: str, public: bool = False,
    ) -> None:
        caption = color_caption(color)
        if caption is None:
            await interaction.response.send_message(
                f"No colour is called {color!r}.", ephemeral=True,
            )
            return
        key = color.strip().lower()
        await self.send_cards(interaction, caption, catalog().color_sheet(key),
                              COLOR_COLUMNS, f"codex_color_{key}.webp", public)

    @app_commands.command(
        name="rules",
        description="A Codex keyword; Sirlin's official rulings on it on request.",
    )
    @app_commands.describe(
        keyword="The keyword, such as Overpower or Flying",
        rulings="Add Sirlin's rulings on the keyword",
        public="Post it in the channel for everyone, rather than to you alone",
    )
    async def rules(
        self,
        interaction: discord.Interaction,
        keyword: str,
        rulings: bool = False,
        public: bool = False,
    ) -> None:
        await self.tokens.refresh()
        answer = keyword_answer(keyword, self.tokens.render, rulings=rulings)
        if answer is None:
            await interaction.response.send_message(
                f"No ruling names {keyword!r}. Pick a keyword from the list as you type.",
                ephemeral=True,
            )
            return
        # The asker's alone unless `public` says otherwise, as `/codex card`.
        await interaction.response.send_message(answer, ephemeral=not public)

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

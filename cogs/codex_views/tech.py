"""
The tech choice's two views (docs/codex-bot.md, decision 8;
docs/design/codex.md, "The standing prompt"), each **ephemeral to the
choice's owner** and built from the prompt's options alone:

- `TechChoiceView`, for `TECH_CHOICE`: the owner's codex pictured with
  the picks marked (`render_codex`), under **Show...** -- the same views
  the Codex button offers, Everything, one tech level, the spells, in
  the standard game one spec (the engine's `codex_views`), since the
  whole codex at once is too much to pick from (the author, 2026-10-09)
  -- then **one card at a time** (the author, 2026-10-10): a menu of
  the cards the view shows, **each card once** whatever its copies, and
  a pick of it is one copy, so a second copy is the same card picked
  again while the codex has one left. A view of more cards than a menu
  holds is split over as many menus as it needs, a row each, never cut
  short. Then **Save tech**, **Tech nothing** where
  none is allowed (ten workers), **Clear** once anything is picked, and
  **My deck** -- what the picks are added to, sent as a message of its
  own so the picker stays up; the caption counts the deck by tech
  level. **The picks are kept across views**: a card picked in Tech I
  stays picked while Tech II is shown, and the caption lists every
  pick, a second copy as "×2". Which cards a view holds is the engine's
  answer (`codex_view_rows`); the view computes nothing. Offered as the
  follow-up to the owner's own Lock patrol, and reachable all through
  the opponent's turn from **Tech** on the turn message; each save
  replaces the last.
- `TechConfirmView`, for `TECH_CONFIRM`: the hand and the picks
  pictured (the panel's two pictures), **Confirm**, **Change** and
  **My deck**. The ready phase runs on Confirm; Change reopens the
  picker. **My hand** opens it at once where the picks were saved (the
  author, 2026-10-10).
- `TechGateView`, on the hand **My hand** sends while the active
  player's turn waits on a tech choice never made: the hand pictured,
  with **Tech** and **My deck** in place of the turn's actions (the
  author, 2026-10-09: "clicking my hand should always show a player
  their hand"). Tech turns it, in place, into the picker.

Nothing about a tech choice is said publicly while it is made -- not
the cards, not that one was made; the owner's ready phase says how many
cards went into the discard pile (the author, 2026-10-08).
"""

from __future__ import annotations

from collections import Counter

import discord

from codex.formatting import card_label, codex_view_name
from codex.prompts import Action, PromptKind
from cogs.codex_helpers import card_name
from cogs.codex_views.base import kept_pictures
from cogs.codex_views.turn import SELECT_LIMIT, PanelView, _cut
from cogs.codex_views.turn_message import codex_view_menu, deck_button

#: The most menus a view of the codex is split over: rows 1 to 3, the
#: Show menu above and the buttons below. Three specs' thirty-six cards
#: take two.
MENU_ROWS = 3

#: The picks in order, as the ask counts them.
ORDINALS = ("first", "second", "third", "fourth")

TECH_LEVELS = ("tech 0", "tech I", "tech II", "tech III")


def picks_listed(picks) -> str:
    """The picks in words, for their owner's eyes, a card picked twice
    once with its count: "Iron Man ×2, Spark"."""
    if not picks:
        return "no cards"
    counted = Counter(picks)
    return ", ".join(
        card_name(slug) + (f" ×{count}" if count > 1 else "") for slug, count in counted.items()
    )


def deck_counted(engine, match, seat: int) -> str:
    """`seat`'s deck counted by tech level, the spells apart -- "Your
    deck: 12 cards: 10 tech 0, 2 tech I." -- what a tech choice is
    added to (the author, 2026-10-10). Counted over `own_deck`, whose
    cards are already the deck's: a count, no rule."""
    cards = engine.catalog.cards
    by_level: Counter = Counter()
    spells = total = 0
    for slug, copies in engine.own_deck(match, seat).cards:
        total += copies
        if cards[slug].is_spell:
            spells += copies
        else:
            by_level[cards[slug].tech_level or 0] += copies
    parts = [f"{by_level[level]} {TECH_LEVELS[level]}" for level in sorted(by_level)]
    if spells:
        parts.append(f"{spells} spell" + ("s" if spells > 1 else ""))
    return f"Your deck: {total} cards: {', '.join(parts)}." if parts else "Your deck: no cards."


class TechChoiceView(PanelView):
    def __init__(self, cog, game_id: str, prompt, match, picks=None,
                 view: str = "everything") -> None:
        super().__init__(cog, game_id, prompt, match)
        options = prompt.options
        self.picks = list(options.picks if picks is None else picks)
        self.view = view
        engine = cog.engine
        catalog = engine.catalog
        # Row 0: which part of the codex is shown.
        views = codex_view_menu(engine.codex_views(match.player(self.seat)), view, row=0)
        views.callback = self.show
        self.views = views
        self.add_item(views)
        # Rows 1 to 3: the shown cards, each once, while a copy is left
        # beside the picks -- one pick a click.
        picked = Counter(self.picks)
        choices = [
            discord.SelectOption(
                label=_cut(card_label(catalog.cards[slug]), 100), value=slug,
            )
            for slug, copies in engine.codex_view_rows(options.codex, view)
            if copies > picked[slug]
        ]
        self.menus: list[discord.ui.Select] = []
        full = len(self.picks) >= options.maximum
        if full or not choices:
            closed = self.closed_placeholder() if full else "Nothing here to tech"
            self.add_item(discord.ui.Select(
                placeholder=closed, row=1, disabled=True,
                options=[discord.SelectOption(label=closed[:100], value="none")],
            ))
        else:
            chunks = [choices[at:at + SELECT_LIMIT] for at in range(0, len(choices), SELECT_LIMIT)]
            for row, chunk in enumerate(chunks[:MENU_ROWS], start=1):
                placeholder = self.placeholder()
                if len(chunks) > 1:
                    placeholder += f" ({card_name(chunk[0].value)} to {card_name(chunk[-1].value)})"
                menu = discord.ui.Select(placeholder=_cut(placeholder, 150), row=row,
                                         options=chunk, min_values=1, max_values=1)
                menu.callback = self.chooser(menu)
                self.menus.append(menu)
                self.add_item(menu)
        # The last row: save, skip where allowed, clear, and the deck.
        last = len(self.menus) + 1 if self.menus else 2
        save = discord.ui.Button(
            label="Save tech", style=discord.ButtonStyle.success, row=last,
            disabled=not (max(options.minimum, 1) <= len(self.picks) <= options.maximum),
        )
        save.callback = self.save
        self.add_item(save)
        if options.minimum == 0:
            skip = discord.ui.Button(label="Tech nothing", style=discord.ButtonStyle.secondary, row=last)
            skip.callback = self.skip
            self.add_item(skip)
        if self.picks:
            clear = discord.ui.Button(label="Clear", style=discord.ButtonStyle.secondary, row=last)
            clear.callback = self.clear
            self.add_item(clear)
        self.add_item(deck_button(self.open_deck, row=last))

    def placeholder(self) -> str:
        """The menu's ask: which pick this is, of how many."""
        options = self.prompt.options
        count = len(self.picks)
        nth = ORDINALS[count] if count < len(ORDINALS) else f"#{count + 1}"
        if options.maximum == 1:
            return "Choose the card to tech..."
        return f"Choose your {nth} card of {options.maximum}..."

    def closed_placeholder(self) -> str:
        """Why the menu is closed: every pick is made."""
        if self.prompt.options.maximum == 1:
            return "Card chosen: Save tech, or Clear to start over"
        return f"All {self.prompt.options.maximum} cards chosen: Save tech, or Clear to start over"

    def caption(self) -> str:
        deck = deck_counted(self.cog.engine, self.match, self.seat)
        return (f"Showing: {codex_view_name(self.view)}. Picked so far: {picks_listed(self.picks)}.\n"
                f"{deck}")

    def chooser(self, menu: discord.ui.Select):
        async def choose(interaction: discord.Interaction) -> None:
            game, match = await self.mine(interaction)
            if game is None:
                return
            await self.redraw(interaction, game, self.picks + [menu.values[0]], self.view)
        return choose

    async def redraw(self, interaction: discord.Interaction, game, picks, view: str) -> None:
        """The picker again, in place: the picks and the view given,
        the picture narrowed to the view with the picks marked."""
        panel = TechChoiceView(self.cog, self.game_id, self.prompt, self.match, picks, view)
        picture = await self.cog.render_prompt(game, self.prompt, picks=picks, view=view)
        await interaction.response.edit_message(
            content=self.cog.panel_caption(game, self.prompt, panel.caption()),
            attachments=[] if picture is None else kept_pictures([picture], interaction.message),
            view=panel,
        )

    async def show(self, interaction: discord.Interaction) -> None:
        game, match = await self.mine(interaction)
        if game is None:
            return
        await self.redraw(interaction, game, self.picks, self.views.values[0])

    async def clear(self, interaction: discord.Interaction) -> None:
        game, match = await self.mine(interaction)
        if game is None:
            return
        await self.redraw(interaction, game, [], self.view)

    async def save(self, interaction: discord.Interaction) -> None:
        await self.act(interaction, Action(
            PromptKind.TECH_CHOICE, "", {"player": self.seat, "picks": list(self.picks)},
        ))

    async def skip(self, interaction: discord.Interaction) -> None:
        """**Tech nothing**: the choice saved empty, which ten workers
        allow (UMR p. 5)."""
        await self.act(interaction, Action(
            PromptKind.TECH_CHOICE, "", {"player": self.seat, "picks": []},
        ))


class TechConfirmView(PanelView):
    def __init__(self, cog, game_id: str, prompt, match) -> None:
        super().__init__(cog, game_id, prompt, match)
        confirm = discord.ui.Button(label="Confirm", style=discord.ButtonStyle.success)
        confirm.callback = self.confirm
        change = discord.ui.Button(label="Change", style=discord.ButtonStyle.secondary)
        change.callback = self.change
        self.add_item(confirm)
        self.add_item(change)
        self.add_item(deck_button(self.open_deck))

    def caption(self) -> str:
        if not self.prompt.options.picks:
            return "Your tech: no cards."
        return f"Your hand, then your tech: {picks_listed(self.prompt.options.picks)}."

    async def confirm(self, interaction: discord.Interaction) -> None:
        await self.act(interaction, Action(PromptKind.TECH_CONFIRM, "confirm", {"player": self.seat}))

    async def change(self, interaction: discord.Interaction) -> None:
        await self.act(interaction, Action(PromptKind.TECH_CONFIRM, "change", {"player": self.seat}))


class TechGateView(PanelView):
    """**Tech** and **My deck** under the hand's picture, the panel
    while the turn waits on a tech choice its player never made: Tech
    opens the picker in place -- the prompt's own view, `show_panel`'s
    edit. Saved picks skip it: My hand opens their confirmation at once."""

    def __init__(self, cog, game_id: str, prompt, match) -> None:
        super().__init__(cog, game_id, prompt, match)
        tech = discord.ui.Button(label="Tech", style=discord.ButtonStyle.primary)
        tech.callback = self.open_tech
        self.add_item(tech)
        self.add_item(deck_button(self.open_deck))

    def caption(self) -> str:
        return "**Tech** opens it; the turn's actions come after it."

    async def open_tech(self, interaction: discord.Interaction) -> None:
        game, match = await self.mine(interaction)
        if game is None:
            return
        await self.cog.show_panel(interaction, game, match, self.seat, edit=True)

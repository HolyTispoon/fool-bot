"""
The tech choice's two views (docs/codex-bot.md, decision 8;
docs/design/codex.md, "The standing prompt"), each **ephemeral to the
choice's owner** and built from the prompt's options alone:

- `TechChoiceView`, for `TECH_CHOICE`: the owner's codex pictured with
  the picks marked (`render_codex`), opening on the part a choice is
  likeliest made from -- every Tech I card and every spell before a
  Tech II building, the Tech II spec's Tech II and III and every spell
  after it (`TechOptions.opening`; the author, 2026-10-20), with
  **Whole codex** beside the buttons -- under **Show...**, that view
  then the ones the Codex button offers, Everything, one tech level,
  the spells, in the standard game one spec (`TechOptions.views`), since
  the whole codex at once is too much to pick from (the author, 2026-10-09)
  -- a codex of one spec, the basic game's, is shown whole with no
  Show menu (the author, 2026-10-20: "with 1v1 basic game, always show
  ALL the codex") -- then **one card at a time** (the author, 2026-10-10): a menu of
  the cards the view shows, **each card once** whatever its copies, and
  a pick of it is one copy, so a second copy is the same card picked
  again while the codex has one left. A view of more cards than a menu
  holds is split over as many menus as it needs, a row each, never cut
  short. Then **Save tech**, **Tech nothing** where
  none is allowed (ten workers), **Clear** once anything is picked, and
  **My deck** -- what the picks are added to, sent as a message of its
  own so the picker stays up. **The picks are kept across views**: a
  card picked in Tech I stays picked while Tech II is shown, and the
  caption -- "Your pick:" -- lists every pick, a second copy as "×2".
  Which cards a view holds is the engine's answer (`codex_view_rows`); the view computes nothing. Offered as the
  follow-up to the owner's own Lock in patrol zone, and reachable all through
  the opponent's turn from **Tech** on the turn message; each save
  replaces the last. Saved in the owner's own ready phase -- **Tech
  nothing** too -- it is the choice, confirmed as made, and the turn
  begins on it (the author, 2026-10-10).
- `TechSavedView`, for `TECH_CHOICE` once a choice is saved: the
  picks pictured alone, **Change** -- the picker in place, on the saved
  picks -- and **My deck** (the author, 2026-10-12: once tech is
  selected, the codex and Save tech go).
- `TechConfirmView`, for `TECH_CONFIRM`: the hand and the picks
  pictured (the panel's two pictures), **Confirm**, **Change** and
  **My deck**. The ready phase runs on Confirm; Change reopens the
  picker, whose save then begins the turn with no second confirmation. **My hand** opens it at once where the picks were saved (the
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
from cogs.codex_views.base import edit_clicked, kept_pictures
from cogs.codex_views.turn import SELECT_LIMIT, PanelView, _cut, concede_button
from cogs.codex_views.turn_message import board_button, codex_button, codex_view_menu, deck_button

#: The most menus a view of the codex is split over: rows 1 to 3, the
#: Show menu above and the buttons below. Three specs' thirty-six cards
#: take two.
MENU_ROWS = 3

#: The picks in order, as the ask counts them.
ORDINALS = ("first", "second", "third", "fourth")


def picks_listed(picks) -> str:
    """The picks in words, for their owner's eyes, a card picked twice
    once with its count: "Iron Man ×2, Spark"."""
    if not picks:
        return "no cards"
    counted = Counter(picks)
    return ", ".join(
        card_name(slug) + (f" ×{count}" if count > 1 else "") for slug, count in counted.items()
    )


class TechChoiceView(PanelView):
    def __init__(self, cog, game_id: str, prompt, match, picks=None,
                 view: str | None = None) -> None:
        super().__init__(cog, game_id, prompt, match)
        options = prompt.options
        self.picks = list(options.picks if picks is None else picks)
        view = options.opening if view is None else view
        self.view = view
        engine = cog.engine
        catalog = engine.catalog
        # Row 0: which part of the codex is shown, the opening view first
        # -- none where the codex has one view, the basic game's whole.
        views = codex_view_menu(options.views, view, row=0)
        views.callback = self.show
        self.views = views
        if len(options.views) > 1:
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
        # The whole codex a click away from the opening view, and the
        # opening view a click back from any other.
        if options.opening != "everything":
            whole = view == options.opening
            label = "Whole codex" if whole else _cut(codex_view_name(options.opening), 80)
            toggle = discord.ui.Button(label=label, style=discord.ButtonStyle.secondary, row=last)
            toggle.callback = self.show_whole if whole else self.show_opening
            self.add_item(toggle)

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
        return f"Your pick: {picks_listed(self.picks)}."

    def chooser(self, menu: discord.ui.Select):
        async def choose(interaction: discord.Interaction) -> None:
            game, match = await self.mine(interaction)
            if game is None:
                return
            await self.redraw(interaction, game, self.picks + [menu.values[0]], self.view)
        return choose

    async def redraw(self, interaction: discord.Interaction, game, picks, view: str) -> None:
        await _put_picker(self, interaction, game, picks, view)

    async def show(self, interaction: discord.Interaction) -> None:
        game, match = await self.mine(interaction)
        if game is None:
            return
        await self.redraw(interaction, game, self.picks, self.views.values[0])

    async def show_whole(self, interaction: discord.Interaction) -> None:
        """**Whole codex**: every card, the spells and every tech level."""
        game, match = await self.mine(interaction)
        if game is None:
            return
        await self.redraw(interaction, game, self.picks, "everything")

    async def show_opening(self, interaction: discord.Interaction) -> None:
        """Back to the view the picker opened on."""
        game, match = await self.mine(interaction)
        if game is None:
            return
        await self.redraw(interaction, game, self.picks, self.prompt.options.opening)

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


async def _put_picker(clicked: PanelView, interaction: discord.Interaction, game, picks,
                     view: str | None = None) -> None:
    """The picker in place of the panel clicked: the picks and the view
    given, the picture narrowed to the view with the picks marked."""
    panel = TechChoiceView(clicked.cog, clicked.game_id, clicked.prompt, clicked.match, picks, view)
    picture = await clicked.cog.render_prompt(game, clicked.prompt, picks=picks, view=view)
    await edit_clicked(
        interaction,
        content=clicked.cog.panel_caption(game, clicked.prompt, panel.caption()),
        attachments=[] if picture is None else kept_pictures([picture], interaction.message),
        view=panel,
    )


class TechSavedView(PanelView):
    """A tech choice saved, for `TECH_CHOICE` once its owner has saved
    one: the picks pictured alone, **Change** and **My deck** -- no
    codex and no Save tech, since nothing is being picked (the author,
    2026-10-12). Change opens the picker in place on the saved picks;
    nothing is answered until it saves again."""

    def __init__(self, cog, game_id: str, prompt, match) -> None:
        super().__init__(cog, game_id, prompt, match)
        change = discord.ui.Button(label="Change", style=discord.ButtonStyle.secondary)
        change.callback = self.change
        self.add_item(change)
        self.add_item(deck_button(self.open_deck))

    def caption(self) -> str:
        return f"Your tech: {picks_listed(self.prompt.options.picks)}."

    async def change(self, interaction: discord.Interaction) -> None:
        game, match = await self.mine(interaction)
        if game is None:
            return
        await _put_picker(self, interaction, game, list(self.prompt.options.picks))


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
        return f"Your tech: {picks_listed(self.prompt.options.picks)}."

    async def confirm(self, interaction: discord.Interaction) -> None:
        await self.act(interaction, Action(PromptKind.TECH_CONFIRM, "confirm", {"player": self.seat}))

    async def change(self, interaction: discord.Interaction) -> None:
        await self.act(interaction, Action(PromptKind.TECH_CONFIRM, "change", {"player": self.seat}))


class TechGateView(PanelView):
    """**Tech**, **My deck**, **Codex**, **Show board** and **Concede**
    under the hand's picture, the panel
    while the turn waits on a tech choice its player never made: Tech
    opens the picker in place -- the prompt's own view, `show_panel`'s
    edit. Saved picks skip it: My hand opens their confirmation at once.
    Its caption runs on after the ask, on the same line (the author,
    2026-10-20)."""

    caption_runs_on = True

    def __init__(self, cog, game_id: str, prompt, match) -> None:
        super().__init__(cog, game_id, prompt, match)
        tech = discord.ui.Button(label="Tech", style=discord.ButtonStyle.primary)
        tech.callback = self.open_tech
        self.add_item(tech)
        self.add_item(deck_button(self.open_deck))
        self.add_item(codex_button(self.open_codex))
        self.add_item(board_button(self.open_board))
        for button in concede_button(self.open_concede, cog.games.get(game_id)):
            self.add_item(button)

    def caption(self) -> str:
        return "Click *Tech* to open the tech menu."

    async def open_tech(self, interaction: discord.Interaction) -> None:
        game, match = await self.mine(interaction)
        if game is None:
            return
        await self.cog.show_panel(interaction, game, match, self.seat, edit=True)

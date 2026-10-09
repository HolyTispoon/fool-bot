"""
The tech choice's two views (docs/codex-bot.md, decision 8;
docs/design/codex.md, "The standing prompt"), each **ephemeral to the
choice's owner** and built from the prompt's options alone:

- `TechChoiceView`, for `TECH_CHOICE`: the owner's codex pictured with
  the picks marked (`render_codex`), under **Show...** -- the same views
  the Codex button offers, Everything, one tech level, the spells, in
  the standard game one spec (the engine's `codex_views`), since the
  whole codex at once is too much to pick from (the author, 2026-10-09)
  -- then a menu of the cards the view shows, a line per copy still in
  the codex, so two copies of one card can be picked, whose bounds are
  `TechOptions.minimum` and `maximum`, and **Save tech** in its own
  row with **My deck** beside it -- what the picks are added to, sent
  as a message of its own so the picker stays up. **The picks are kept across views**: a card picked in Tech I
  stays picked while Tech II is shown, the caption lists every pick,
  and the shown menu offers only the room the hidden picks leave.
  Which cards a view holds is the engine's answer (`codex_view_rows`);
  the view computes nothing. Offered as the follow-up to the owner's
  own Lock patrol, and reachable all through the opponent's turn from
  **Tech** on the turn message; each save replaces the last.
- `TechConfirmView`, for `TECH_CONFIRM`: the picks pictured as a hand
  (`render_hand`), **Confirm**, **Change** and **My deck**. The ready
  phase runs on Confirm; Change reopens the picker.

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


def picks_listed(picks) -> str:
    """The picks in words, for their owner's eyes: "Iron Man, Iron Man"."""
    return ", ".join(card_name(slug) for slug in picks) if picks else "no cards"


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
        # Row 1: the shown cards, a line per copy left. A pick made in
        # another view is kept, unseen here, and takes a place.
        shown = engine.codex_view_rows(options.codex, view)
        shown_slugs = {slug for slug, _ in shown}
        self.hidden = [slug for slug in self.picks if slug not in shown_slugs]
        chosen = Counter(slug for slug in self.picks if slug in shown_slugs)
        choices = []
        for slug, left in shown:
            for copy in range(1, left + 1):
                choices.append(discord.SelectOption(
                    label=_cut(card_label(catalog.cards[slug]) + (f" -- copy {copy}" if left > 1 else ""), 100),
                    value=f"{slug}#{copy}",
                    default=copy <= chosen.get(slug, 0),
                ))
        choices = choices[:SELECT_LIMIT]
        room = options.maximum - len(self.hidden)
        most = min(room, len(choices))
        self.select = None
        if most > 0:
            # The whole codex shown: the menu holds the choice to its
            # bounds. A part of it: a pick may come from any part, so
            # nothing is forced here, and Save is held to the bounds.
            least = min(options.minimum, most) if view == "everything" else 0
            select = discord.ui.Select(
                placeholder=self.bounds(), row=1, options=choices,
                min_values=least, max_values=most,
            )
            select.callback = self.choose
            self.select = select
            self.add_item(select)
        else:
            empty = self.nothing_to_offer(bool(choices))
            self.add_item(discord.ui.Select(
                placeholder=empty, row=1, disabled=True,
                options=[discord.SelectOption(label=empty[:100], value="none")],
            ))
        save = discord.ui.Button(label="Save tech", style=discord.ButtonStyle.success, row=2)
        save.callback = self.save
        self.add_item(save)
        self.add_item(deck_button(self.open_deck, row=2))

    def bounds(self) -> str:
        options = self.prompt.options
        if options.minimum == options.maximum:
            return f"Choose {options.maximum} cards to tech..."
        return f"Choose {options.minimum} to {options.maximum} cards to tech..."

    def nothing_to_offer(self, cards_shown: bool) -> str:
        """Why the shown menu is closed: the picks already fill the
        choice from other views, or the view holds no card."""
        if cards_shown:
            count = len(self.hidden)
            if count == 1:
                return "Your pick is in another view: change it there"
            return f"Your {count} picks are in other views: change them there"
        return "Nothing here to tech"

    def caption(self) -> str:
        return f"Showing: {codex_view_name(self.view)}. Picked so far: {picks_listed(self.picks)}."

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

    async def choose(self, interaction: discord.Interaction) -> None:
        game, match = await self.mine(interaction)
        if game is None:
            return
        picks = self.hidden + [value.split("#", 1)[0] for value in self.select.values]
        await self.redraw(interaction, game, picks, self.view)

    async def save(self, interaction: discord.Interaction) -> None:
        await self.act(interaction, Action(
            PromptKind.TECH_CHOICE, "", {"player": self.seat, "picks": list(self.picks)},
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
        return f"Your tech: {picks_listed(self.prompt.options.picks)}."

    async def confirm(self, interaction: discord.Interaction) -> None:
        await self.act(interaction, Action(PromptKind.TECH_CONFIRM, "confirm", {"player": self.seat}))

    async def change(self, interaction: discord.Interaction) -> None:
        await self.act(interaction, Action(PromptKind.TECH_CONFIRM, "change", {"player": self.seat}))

"""
The tech choice's two views (docs/codex-bot.md, decision 8;
docs/design/codex.md, "The standing prompt"), each **ephemeral to the
choice's owner** and built from the prompt's options alone:

- `TechChoiceView`, for `TECH_CHOICE`: the owner's codex pictured with
  the picks marked (`render_codex`), under a menu of its cards -- a line
  per copy still in it, so two copies of one card can be picked -- whose
  bounds are `TechOptions.minimum` and `maximum`, and **Save tech**
  alone in its row. Offered as the follow-up to the owner's own Lock
  patrol, and reachable all through the opponent's turn from **Tech**
  on the turn message; each save replaces the last.
- `TechConfirmView`, for `TECH_CONFIRM`: the picks pictured as a hand
  (`render_hand`), **Confirm** and **Change**. The ready phase runs on
  Confirm; Change reopens the picker.

What was picked is never said publicly: the turn message hears "has
chosen their tech", and a count when the cards reach the discard pile.
"""

from __future__ import annotations

from collections import Counter

import discord

from codex.formatting import card_label
from codex.prompts import Action, PromptKind
from cogs.codex_helpers import card_name
from cogs.codex_views.turn import SELECT_LIMIT, PanelView, _cut


def picks_listed(picks) -> str:
    """The picks in words, for their owner's eyes: "Iron Man, Iron Man"."""
    return ", ".join(card_name(slug) for slug in picks) if picks else "no cards"


class TechChoiceView(PanelView):
    def __init__(self, cog, game_id: str, prompt, match, picks=None) -> None:
        super().__init__(cog, game_id, prompt, match)
        options = prompt.options
        self.picks = list(options.picks if picks is None else picks)
        chosen = Counter(self.picks)
        catalog = cog.engine.catalog
        choices = []
        for slug, left in options.codex:
            for copy in range(1, left + 1):
                choices.append(discord.SelectOption(
                    label=_cut(card_label(catalog.cards[slug]) + (f" -- copy {copy}" if left > 1 else ""), 100),
                    value=f"{slug}#{copy}",
                    default=copy <= chosen.get(slug, 0),
                ))
        choices = choices[:SELECT_LIMIT]
        most = min(options.maximum, len(choices))
        if most:
            select = discord.ui.Select(
                placeholder=self.bounds(), row=0, options=choices,
                min_values=min(options.minimum, most), max_values=most,
            )
            select.callback = self.choose
            self.select = select
            self.add_item(select)
        save = discord.ui.Button(label="Save tech", style=discord.ButtonStyle.success, row=1)
        save.callback = self.save
        self.add_item(save)

    def bounds(self) -> str:
        options = self.prompt.options
        if options.minimum == options.maximum:
            return f"Choose {options.maximum} cards to tech..."
        return f"Choose {options.minimum} to {options.maximum} cards to tech..."

    def caption(self) -> str:
        return f"Picked so far: {picks_listed(self.picks)}."

    async def choose(self, interaction: discord.Interaction) -> None:
        game, match = await self.mine(interaction)
        if game is None:
            return
        picks = [value.split("#", 1)[0] for value in self.select.values]
        view = TechChoiceView(self.cog, self.game_id, self.prompt, self.match, picks)
        picture = await self.cog.render_prompt(game, self.prompt, picks=picks)
        await interaction.response.edit_message(
            content=self.cog.panel_caption(game, self.prompt, view.caption()),
            attachments=[] if picture is None else [picture], view=view,
        )

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

    def caption(self) -> str:
        return f"Your tech: {picks_listed(self.prompt.options.picks)}."

    async def confirm(self, interaction: discord.Interaction) -> None:
        await self.act(interaction, Action(PromptKind.TECH_CONFIRM, "confirm", {"player": self.seat}))

    async def change(self, interaction: discord.Interaction) -> None:
        await self.act(interaction, Action(PromptKind.TECH_CONFIRM, "change", {"player": self.seat}))

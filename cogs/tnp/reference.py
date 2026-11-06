"""
`/tnp unit` and `/tnp rules`: a unit's card as words, from the imported
data, and a section of docs/tnp-rules.md. Plain text, no embed, the
asker's alone unless `public` says otherwise. The words are the
model's (`tnp.formatting.unit_lines`, `tnp.rules_doc.messages`); this
only posts them.
"""

from __future__ import annotations

import logging

import discord
from discord import app_commands

from cogs.tnp_helpers import UNAVAILABLE
from tnp import rules_doc
from tnp.formatting import unit_lines

LOGGER = logging.getLogger(__name__)


class ReferenceMixin:
    @app_commands.command(name="unit", description="A TNP unit: cost, ratings as d12 numbers, traits, supply.")
    @app_commands.describe(
        name="The unit's name",
        public="Post it in the channel for everyone, rather than to you alone",
    )
    async def unit(self, interaction: discord.Interaction, name: str, public: bool = False) -> None:
        if self.catalog is None:
            await interaction.response.send_message(UNAVAILABLE, ephemeral=True)
            return
        slug = self.catalog.find_unit(name)
        if slug is None:
            await interaction.response.send_message(
                f"No unit is called {name!r}. Pick one from the list as you type.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            "\n".join(unit_lines(self.catalog, slug)), ephemeral=not public,
        )

    @unit.autocomplete("name")
    async def unit_autocomplete(
        self, interaction: discord.Interaction, current: str,
    ) -> list[app_commands.Choice[str]]:
        if self.catalog is None:
            return []
        return [
            app_commands.Choice(name=self.catalog.name(slug)[:100], value=slug)
            for slug in self.catalog.search_units(current)
        ]

    @app_commands.command(name="rules", description="A section of TNP's rules, by number or title.")
    @app_commands.describe(
        section="The section, such as 6.7 or Damage",
        public="Post it in the channel for everyone, rather than to you alone",
    )
    async def rules(self, interaction: discord.Interaction, section: str, public: bool = False) -> None:
        try:
            found = rules_doc.find(section)
        except OSError:
            LOGGER.exception("docs/tnp-rules.md could not be read")
            await interaction.response.send_message(UNAVAILABLE, ephemeral=True)
            return
        if found is None:
            await interaction.response.send_message(
                f"No section of TNP's rules is {section!r}. Pick one from the list as you type.",
                ephemeral=True,
            )
            return
        first, *rest = rules_doc.messages(found)
        await interaction.response.send_message(first, ephemeral=not public)
        for message in rest:
            await interaction.followup.send(message, ephemeral=not public)

    @rules.autocomplete("section")
    async def rules_autocomplete(
        self, interaction: discord.Interaction, current: str,
    ) -> list[app_commands.Choice[str]]:
        try:
            found = rules_doc.search(current)
        except OSError:
            return []
        return [
            app_commands.Choice(name=section.label[:100], value=section.number)
            for section in found
        ]

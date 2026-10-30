"""
`/codex debug`: a helper's corrections by hand to this channel's board,
for a position a bug left wrong -- `patrol`, a unit or hero into a slot,
between slots or out of the patrol zone; `damage`, added to or removed
from a unit, hero or building card; and `rune`, +1/+1, -1/-1, time or a
named rune added to or removed from any card in play or hero. The
corrections and their rules are the model's (`codex.flow.edits`), made
through `GameService.correct`; the line each says joins the turn's lines
and the board is redrawn, as an action's are (`present`). Helpers alone
(Manage Channels), read at run time as `/codex admin`'s gate is
(docs/design/codex.md, "Corrections by hand").
"""

from __future__ import annotations

import logging

import discord
from discord import app_commands

from codex.flow import edits
from codex.formatting import SLOT_NAMES
from codex.game import GameStatus, RuleRefusal
from cogs.codex.ending import HELPERS_ONLY
from cogs.codex_helpers import is_game_helper
from cogs.codex_views import send_ephemeral

LOGGER = logging.getLogger(__name__)

NO_GAME_HERE = "No Codex game is being played in this channel."

#: What a patrol correction may name: each slot, and out of the zone.
SLOT_CHOICES = [
    *(app_commands.Choice(name=name.capitalize(), value=slot) for slot, name in SLOT_NAMES.items()),
    app_commands.Choice(name="Out of the patrol zone", value=edits.OFF),
]

#: Which way a damage or rune correction goes.
ADD, REMOVE = "add", "remove"
CHANGE_CHOICES = [app_commands.Choice(name="Add", value=ADD), app_commands.Choice(name="Remove", value=REMOVE)]

#: Every rune a rune correction may name, by what a line calls it.
RUNE_CHOICES = [
    app_commands.Choice(name=word.capitalize(), value=kind) for kind, word in edits.RUNE_WORDS.items()
]


class DebugMixin:
    debug = app_commands.Group(
        name="debug",
        description="Helpers: correct this channel's Codex board by hand.",
        guild_only=True,
    )

    @debug.command(name="patrol", description="Move a unit or hero into a patrol slot, or out of the patrol zone.")
    @app_commands.describe(unit="The unit or hero", slot="The slot, or out of the patrol zone")
    @app_commands.choices(slot=SLOT_CHOICES)
    async def debug_patrol(self, interaction: discord.Interaction, unit: str,
                           slot: app_commands.Choice[str]) -> None:
        await self.correct_board(interaction, unit, lambda seat, ref: edits.patrol(seat, ref, slot.value))

    @debug.command(name="damage", description="Add damage to a unit, hero or building card, or remove it.")
    @app_commands.describe(unit="The unit, hero or building card", change="Add or remove",
                           amount="How much damage")
    @app_commands.choices(change=CHANGE_CHOICES)
    async def debug_damage(self, interaction: discord.Interaction, unit: str,
                           change: app_commands.Choice[str], amount: app_commands.Range[int, 1, 99]) -> None:
        signed = amount if change.value == ADD else -amount
        await self.correct_board(interaction, unit, lambda seat, ref: edits.damage(seat, ref, signed))

    @debug.command(name="rune", description="Add runes to a card in play or a hero, or remove them.")
    @app_commands.describe(card="The card or hero", rune="Which rune", change="Add or remove",
                           amount="How many runes")
    @app_commands.choices(rune=RUNE_CHOICES, change=CHANGE_CHOICES)
    async def debug_rune(self, interaction: discord.Interaction, card: str, rune: app_commands.Choice[str],
                         change: app_commands.Choice[str], amount: app_commands.Range[int, 1, 99]) -> None:
        signed = amount if change.value == ADD else -amount
        await self.correct_board(interaction, card, lambda seat, ref: edits.rune(seat, ref, rune.value, signed))

    @debug_patrol.autocomplete("unit")
    async def debug_patrol_autocomplete(self, interaction: discord.Interaction,
                                        current: str) -> list[app_commands.Choice[str]]:
        return self.debug_choices(interaction, current, edits.PATROL)

    @debug_damage.autocomplete("unit")
    async def debug_damage_autocomplete(self, interaction: discord.Interaction,
                                        current: str) -> list[app_commands.Choice[str]]:
        return self.debug_choices(interaction, current, edits.DAMAGE)

    @debug_rune.autocomplete("card")
    async def debug_rune_autocomplete(self, interaction: discord.Interaction,
                                      current: str) -> list[app_commands.Choice[str]]:
        return self.debug_choices(interaction, current, edits.RUNE)

    def debug_choices(self, interaction: discord.Interaction, current: str,
                      edit: str) -> list[app_commands.Choice[str]]:
        """What the correction `edit` may name in this channel's game,
        filtered by what has been typed -- for a helper alone."""
        game = self.game_for_channel(interaction.channel_id)
        if game is None or game.status is not GameStatus.PLAYING or not is_game_helper(interaction.user):
            return []
        try:
            match = self.service.load(game)
        except RuleRefusal:
            return []
        needle = current.strip().casefold()
        choices = []
        for target in edits.targets(self.engine, match, edit):
            label = self.debug_label(game, target)
            if needle in label.casefold():
                choices.append(app_commands.Choice(name=label[:100], value=f"{target.seat}|{target.ref}"))
        return choices[:25]

    def debug_label(self, game, target: edits.EditTarget) -> str:
        """A card or hero as the autocomplete lists it: whose, what, its
        HP, where it patrols and its runes -- "kime: Hardened Mox, 1/1 HP,
        elite, exhausted", "ann: Might of Leaf and Claw, 3 growth"."""
        whose = game.seat_name(target.seat) or f"Player {target.seat}"
        where = [] if target.max_hp is None else [f"{target.hp}/{target.max_hp} HP"]
        if target.slot is not None:
            where.append(SLOT_NAMES[target.slot])
        if target.exhausted:
            where.append("exhausted")
        where += [f"{count} {edits.RUNE_WORDS.get(kind, kind)}" for kind, count in target.runes]
        return ", ".join([f"{whose}: {self.engine.catalog.name(target.slug)}", *where])

    async def correct_board(self, interaction: discord.Interaction, unit: str, make) -> None:
        """The one path of every command: the gate, the card named by the
        autocomplete's value, the correction through the service under
        the game's lock, and the result presented as an action's."""
        game = self.game_for_channel(interaction.channel_id)
        if game is None or game.status is not GameStatus.PLAYING:
            await send_ephemeral(interaction, NO_GAME_HERE)
            return
        if not is_game_helper(interaction.user):
            await send_ephemeral(interaction, HELPERS_ONLY)
            return
        seat, _, ref = unit.partition("|")
        if not seat.isdigit() or not ref:
            await send_ephemeral(interaction, "Pick it from the list.")
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with self.locks.hold(game.game_id):
            try:
                result = self.service.correct(game.game_id, make(int(seat), ref))
            except RuleRefusal as refused:
                await interaction.followup.send(str(refused), ephemeral=True)
                return
            await interaction.followup.send(self.render_text(result.narration[0], game), ephemeral=True)
            await self.present(game, result)

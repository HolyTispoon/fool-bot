"""
`PatrolView`, the view for `PATROL`: the patrol lock that ends the main
phase (UMR p. 10), in the panel, from `PatrolOptions` and nothing else.

**Two menus rather than five.** A message carries at most five rows of
components, and five slot menus would leave no row for **Lock patrol**,
which stands alone in its row so it is never pressed by mistake
(decision 11). So the first menu picks a slot -- each named with what
holds it so far -- and the second what patrols it: the candidates not
placed in another slot, or nobody. Choosing moves on to the next empty
slot. **Clear** empties all five, and **Undo...** beside it offers the
same undos as the main phase's panel -- to the start of the turn, which
reopens the main phase, or of the previous one -- with **Back** to the
patrol as it was. The assignment is the view's alone
until **Lock patrol** answers with it; nothing is applied before then.
"""

from __future__ import annotations

import discord

from codex.formatting import slot_name
from codex.prompts import Action, PromptKind
from cogs.codex_views.turn import SELECT_LIMIT, PanelView, _cut, _open_undo

EMPTY = "__empty__"


def next_empty(slots, assignment: dict, after: str | None = None) -> str | None:
    """The first slot after `after`, round the five, that nothing holds."""
    slots = list(slots)
    start = slots.index(after) + 1 if after in slots else 0
    for slot in slots[start:] + slots[:start]:
        if slot not in assignment and slot != after:
            return slot
    return None


class PatrolView(PanelView):
    def __init__(self, cog, game_id: str, prompt, match,
                 assignment: dict | None = None, slot: str | None = None) -> None:
        super().__init__(cog, game_id, prompt, match)
        options = prompt.options
        self.assignment = dict(assignment or {})
        self.slot = slot or next_empty(options.slots, self.assignment) or options.slots[0]

        slots = discord.ui.Select(
            placeholder="Choose a slot...", row=0,
            options=[
                discord.SelectOption(
                    label=_cut(f"{slot_name(slot).capitalize()}: {self.holder(slot)}", 100),
                    value=slot, default=slot == self.slot,
                )
                for slot in options.slots
            ],
        )
        slots.callback = self.choose_slot
        self.slots = slots
        self.add_item(slots)

        taken = {ref for held, ref in self.assignment.items() if held != self.slot}
        free = [ref for ref in options.candidates if ref not in taken][: SELECT_LIMIT - 1]
        patrollers = discord.ui.Select(
            placeholder=f"Who patrols as {slot_name(self.slot)}?", row=1,
            options=[
                discord.SelectOption(
                    label=_cut(self.label(ref), 100), value=ref,
                    default=self.assignment.get(self.slot) == ref,
                )
                for ref in free
            ] + [discord.SelectOption(label="Nobody", value=EMPTY)],
        )
        patrollers.callback = self.choose_patroller
        self.patrollers = patrollers
        self.add_item(patrollers)

        clear = discord.ui.Button(label="Clear", style=discord.ButtonStyle.secondary, row=2)
        clear.callback = self.clear
        self.add_item(clear)
        undo = discord.ui.Button(label="Undo...", style=discord.ButtonStyle.secondary, row=2)
        undo.callback = self.open_undo
        self.add_item(undo)
        lock = discord.ui.Button(label="Lock patrol", style=discord.ButtonStyle.danger, row=3)
        lock.callback = self.lock
        self.add_item(lock)

    def holder(self, slot: str) -> str:
        ref = self.assignment.get(slot)
        return self.label(ref) if ref is not None else "empty"


    def caption(self) -> str:
        """The assignment so far, slot by slot, under the ask."""
        rows = [
            f"**{slot_name(slot).capitalize()}**: {self.holder(slot)}"
            for slot in self.prompt.options.slots
        ]
        return "\n".join(rows)

    async def redraw(self, interaction: discord.Interaction, assignment: dict,
                     slot: str | None) -> None:
        game, match = await self.mine(interaction)
        if game is None:
            return
        view = PatrolView(self.cog, self.game_id, self.prompt, self.match, assignment, slot)
        await interaction.response.edit_message(
            content=self.cog.panel_caption(game, self.prompt, view.caption()), view=view,
        )

    async def choose_slot(self, interaction: discord.Interaction) -> None:
        await self.redraw(interaction, self.assignment, self.slots.values[0])

    async def choose_patroller(self, interaction: discord.Interaction) -> None:
        chosen = self.patrollers.values[0]
        assignment = dict(self.assignment)
        if chosen == EMPTY:
            assignment.pop(self.slot, None)
            following = self.slot
        else:
            assignment[self.slot] = chosen
            following = next_empty(self.prompt.options.slots, assignment, self.slot) or self.slot
        await self.redraw(interaction, assignment, following)

    async def clear(self, interaction: discord.Interaction) -> None:
        await self.redraw(interaction, {}, None)

    async def open_undo(self, interaction: discord.Interaction) -> None:
        await _open_undo(self, interaction, back_to=PatrolView(
            self.cog, self.game_id, self.prompt, self.match, self.assignment, self.slot,
        ))

    async def lock(self, interaction: discord.Interaction) -> None:
        await self.act(interaction, Action(
            PromptKind.PATROL, "", {"assignment": dict(self.assignment)},
        ))

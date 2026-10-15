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

**A free-for-all lends through the same two menus** (Rulebook p. 14;
docs/design/codex.md, "Lending is a control change"). Where the options
carry `zones` -- each opponent's open slots, the engine's reading --
those follow the owner's five in the slot menu as destinations,
"<name>'s elite: empty", and the patroller chosen for one is lent: the
second menu asks "Who is lent to <name> as elite?". A card goes to one
destination, the owner's or a borrower's, so a card placed anywhere is
offered nowhere else. **Lock patrol** answers with `lent`,
`{seat: {slot: ref}}`, beside `assignment` where something is lent, and
with `assignment` alone where nothing is, so a duel's answer is as it
was. What lending does -- control to the borrower until their upkeep --
is the model's to say at the lock; the view words only the destination.
"""

from __future__ import annotations

import discord

from codex.formatting import slot_name
from codex.prompts import Action, PromptKind
from cogs.codex_helpers import seat_label
from cogs.codex_views.base import edit_clicked
from cogs.codex_views.turn import SELECT_LIMIT, PanelView, _cut, _open_undo

EMPTY = "__empty__"


def destination_key(seat: int | None, slot: str) -> str:
    """A destination's value in the slot menu: the owner's slot by its
    name, an opponent's open one as `<seat>:<slot>`."""
    return slot if seat is None else f"{seat}:{slot}"


def split_destination(key: str) -> tuple[int | None, str]:
    """The seat and slot a destination key names; `None` for the owner's."""
    seat, _, slot = key.rpartition(":")
    return (int(seat), slot) if seat else (None, slot)


def destinations(options) -> list[tuple[str, int | None, str]]:
    """Every slot a patroller may go to, `(key, seat, slot)`: the owner's
    five, then each opponent's open ones in seat order
    (`PatrolOptions.zones`, a free-for-all's and empty elsewhere)."""
    found = [(slot, None, slot) for slot in options.slots]
    for seat, slots in options.zones:
        found.extend((destination_key(seat, slot), seat, slot) for slot in slots)
    return found


def split_assignment(assignment: dict) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """The view's one map, split as the answer carries it: the owner's
    `assignment` by slot, and `lent`, `{seat: {slot: ref}}` -- the seat
    a string, as a journal written to disk reads it back."""
    own: dict[str, str] = {}
    lent: dict[str, dict[str, str]] = {}
    for key, ref in assignment.items():
        seat, slot = split_destination(key)
        if seat is None:
            own[slot] = ref
        else:
            lent.setdefault(str(seat), {})[slot] = ref
    return own, lent


def next_empty(slots, assignment: dict, after: str | None = None) -> str | None:
    """The first slot after `after`, round the five, that nothing holds.
    `after` not among `slots` -- a borrower's slot -- starts from the
    first."""
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
        #: Destination key to ref: the owner's slots by name, a
        #: borrower's as `<seat>:<slot>` (`destination_key`).
        self.assignment = dict(assignment or {})
        self.destinations = destinations(options)
        #: The destination the second menu asks about.
        self.slot = slot or next_empty(options.slots, self.assignment) or options.slots[0]
        game = cog.games.get(game_id)

        slots = discord.ui.Select(
            placeholder="Choose a slot...", row=0,
            options=[
                discord.SelectOption(
                    label=_cut(f"{self.destination_name(key, game)}: {self.holder(key)}", 100),
                    value=key, default=key == self.slot,
                )
                for key, _, _ in self.destinations
            ][:SELECT_LIMIT],
        )
        slots.callback = self.choose_slot
        self.slots = slots
        self.add_item(slots)

        taken = {ref for held, ref in self.assignment.items() if held != self.slot}
        free = [ref for ref in options.candidates if ref not in taken][: SELECT_LIMIT - 1]
        borrower, slot_named = split_destination(self.slot)
        patrollers = discord.ui.Select(
            placeholder=(
                f"Who patrols as {slot_name(slot_named)}?" if borrower is None
                else f"Who is lent to {seat_label(game, borrower)} as {slot_name(slot_named)}?"
            ),
            row=1,
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

    @staticmethod
    def destination_name(key: str, game) -> str:
        """A destination in the slot menu: "Elite" for the owner's,
        "<name>'s elite" for an opponent's (`seat_label`)."""
        seat, slot = split_destination(key)
        if seat is None:
            return slot_name(slot).capitalize()
        return f"{seat_label(game, seat)}'s {slot_name(slot)}"

    def holder(self, key: str) -> str:
        ref = self.assignment.get(key)
        return self.label(ref) if ref is not None else "empty"


    def caption(self) -> str:
        """The assignment so far under the ask: the owner's five slot by
        slot, then each patroller lent, by whom to and as what."""
        game = self.cog.games.get(self.game_id)
        rows = [
            f"**{slot_name(slot).capitalize()}**: {self.holder(slot)}"
            for slot in self.prompt.options.slots
        ]
        rows.extend(
            f"**Lent to {seat_label(game, seat)} as {slot_name(slot)}**: {self.holder(key)}"
            for key, seat, slot in self.destinations
            if seat is not None and key in self.assignment
        )
        return "\n".join(rows)

    async def redraw(self, interaction: discord.Interaction, assignment: dict,
                     slot: str | None) -> None:
        game, match = await self.mine(interaction)
        if game is None:
            return
        view = PatrolView(self.cog, self.game_id, self.prompt, self.match, assignment, slot)
        await edit_clicked(
            interaction, content=self.cog.panel_caption(game, self.prompt, view.caption()), view=view,
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
        assignment, lent = split_assignment(self.assignment)
        arguments: dict = {"assignment": assignment}
        if lent:
            arguments["lent"] = lent
        await self.act(interaction, Action(PromptKind.PATROL, "", arguments))

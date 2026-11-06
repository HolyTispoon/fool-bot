"""
A seat's panel: the controls under its board, ephemeral, to its player
alone (docs/design/tnp.md, "The turn on Discord"). One view a prompt
kind of the turn's -- `PlanPanelView` (Infrastructure and Deployment),
`TradePanelView` (Production and Trade's trade), `ConquerPanelView` and
`HarvestPanelView` (March's two questions) -- each built from
`PendingPrompt.options` and nothing else, and `panel_view` the one
mapping from a prompt to its view.

**Buttons, not menus** (the author, 2026-11-06), but for the one list
too long for a row: an attack's target, or a defense spot's territory,
whose menu puts the territories with a path now first. **The plan is two
steps**, Infrastructure and Deployment, each with its own picture -- the
player board, then the seat's attack board -- and **Lock in** asks once
more where a step is empty.

**Every change is an answer through the service.** A plan or a trade is
saved on the match with each change (`save`), checked as it is saved,
and locked in by **Lock in** (`lock`), so a restart keeps it and the
model refuses what the rules do not allow -- the panel shows the
refusal and keeps what was saved. What a panel holds itself is only
which step and pile are being changed and a choice not yet an answer
(the unit a count is for, a spot's territory before any unit is in it,
a harvest's tokens before **Take**).

Not persistent: a panel answers clicks for `PANEL_TIMEOUT`, and after
that or a restart **My board** opens a fresh one over the plan saved on
the match. No view saves.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, replace
from typing import Callable, Mapping, Optional

import discord

from cogs.tnp_views.base import SafeView, send_ephemeral
from tnp.formatting import TOKEN_WORDS
from tnp.prompts import Action, PendingPrompt, PromptKind
from tnp.turn import area_order, base_of

#: How long a panel answers clicks: a phase, generously. An expired
#: panel is reopened from **My board**, which makes a fresh one over the
#: plan saved on the match.
PANEL_TIMEOUT = 3600

#: Discord's limits: a menu's options, a button's label, a row's buttons.
MENU_OPTIONS = 25
LABEL_LENGTH = 80
ROW_BUTTONS = 5

#: The plan's two steps.
INFRASTRUCTURE, DEPLOYMENT = "infrastructure", "deployment"
STEP_LABELS = {INFRASTRUCTURE: "① Infrastructure", DEPLOYMENT: "② Deployment"}

#: A defense spot the panel is filling, before any unit is in it.
NEW_DEFENSE = "d:new"


@dataclass(frozen=True)
class PanelState:
    """What a panel holds that is not yet an answer."""

    #: The plan's step being changed: `INFRASTRUCTURE` or `DEPLOYMENT`.
    step: str = INFRASTRUCTURE
    #: The unit a count is for: one to build, or one to deploy.
    unit: Optional[str] = None
    #: The pile being changed in Deployment: an attack spot's letter,
    #: "base", "d:<area>" for a defended territory, or `NEW_DEFENSE`.
    pile: Optional[str] = None
    #: A pile's territory chosen before any unit is in it, by pile.
    targets: tuple = ()
    #: Whether the pile's territory menu is up.
    choosing: bool = False
    #: Which page of a row of buttons is shown, by row.
    pages: tuple = ()
    #: **Lock in** pressed with a step empty: the warning is up.
    confirm: bool = False
    #: The token kind a trade's two counts are for.
    kind: Optional[str] = None
    #: A harvest's tokens chosen so far, by kind, before **Take**.
    taken: tuple = ()
    #: A refusal to show above the panel, once.
    notice: Optional[str] = None
    #: What the panel's picture was drawn from (`Tnp.panel_picture_key`).
    drawn: tuple = ()

    def target(self, pile: str) -> Optional[str]:
        return dict(self.targets).get(pile)

    def page(self, row: str) -> int:
        return dict(self.pages).get(row, 0)


def _label(text: str) -> str:
    return text if len(text) <= LABEL_LENGTH else text[: LABEL_LENGTH - 1] + "…"


def _with(pairs: tuple, key, value) -> tuple:
    found = dict(pairs)
    if value is None:
        found.pop(key, None)
    else:
        found[key] = value
    return tuple(sorted(found.items()))


def full_plan(plan: Optional[Mapping]) -> dict:
    """A saved plan with every part present, copied."""
    plan = copy.deepcopy(dict(plan or {}))
    for part, empty in (("build", {}), ("structures", []), ("attacks", {}), ("defense", {})):
        plan.setdefault(part, empty)
    return plan


def empty_steps(plan: Optional[Mapping]) -> list[str]:
    """The plan's steps with nothing in them, which **Lock in** warns of."""
    plan = full_plan(plan)
    empty = []
    if not any(plan["build"].values()) and not plan["structures"]:
        empty.append(INFRASTRUCTURE)
    if not plan["attacks"] and not plan["defense"]:
        empty.append(DEPLOYMENT)
    return empty


@dataclass(frozen=True)
class Choice:
    """One button a row may show: its label, its callback, its style and
    the answer it names (`find_button` reads `choice` in the tests)."""

    label: str
    callback: Callable
    style: discord.ButtonStyle = discord.ButtonStyle.secondary
    choice: tuple = ()
    disabled: bool = False


class PanelView(SafeView):
    """A seat's controls: the clicker must hold the seat."""

    def __init__(self, cog, game_id: str, seat: str, prompt: PendingPrompt,
                 state: PanelState) -> None:
        super().__init__(timeout=PANEL_TIMEOUT)
        self.cog = cog
        self.game_id = game_id
        self.seat = seat
        self.prompt = prompt
        self.options = prompt.options
        self.state = state

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await super().interaction_check(interaction):
            return False
        game = self.game()
        if game is None or self.seat not in game.seats_of(interaction.user.id):
            await send_ephemeral(interaction, "This panel is its seat's player's alone.")
            return False
        return True

    def name(self, slug: str) -> str:
        return self.cog.catalog.name(slug)

    def area_name(self, area: str) -> str:
        return self.cog.area_words(area)

    def button(self, label: str, style: discord.ButtonStyle, callback, *, row: int,
               choice: tuple = (), disabled: bool = False) -> discord.ui.Button:
        item = discord.ui.Button(label=_label(label), style=style, row=row, disabled=disabled)
        item.choice = choice

        async def pressed(interaction: discord.Interaction) -> None:
            await callback(interaction)

        item.callback = pressed
        self.add_item(item)
        return item

    def label(self, text: str, row: int) -> None:
        """A word on a row, as a button nobody can press."""
        self.button(text, discord.ButtonStyle.secondary, self.on_nothing, row=row, disabled=True)

    def buttons(self, choices: list[Choice], rows: tuple[int, ...], key: str) -> None:
        """`choices` across `rows`, a page at a time where they do not
        fit, the last place a **▶** to the next page."""
        room = ROW_BUTTONS * len(rows)
        pages, shown = 1, choices
        if len(choices) > room:
            per = room - 1
            pages = -(-len(choices) // per)
            page = self.state.page(key) % pages
            shown = choices[page * per:(page + 1) * per]
        for index, one in enumerate(shown):
            self.button(one.label, one.style, one.callback, row=rows[index // ROW_BUTTONS],
                        choice=one.choice, disabled=one.disabled)
        if pages > 1:
            page = self.state.page(key) % pages
            self.button(f"▶ {page + 1}/{pages}", discord.ButtonStyle.secondary, self.pager(key, pages),
                        row=rows[-1], choice=("page", key))

    def pager(self, key: str, pages: int):
        async def turned(interaction) -> None:
            page = (self.state.page(key) + 1) % pages
            await self.answer(interaction, None, replace(self.state, pages=_with(self.state.pages, key, page)))
        return turned

    def counter_row(self, caption: str, current: int, most: int, apply, row: int, *,
                    all_label: str = "All", choice: tuple = ()) -> None:
        """A count's row: what it is now, then −1, +1, all of it, none."""
        self.label(caption, row)

        def set_to(value: int):
            async def pressed(interaction) -> None:
                await apply(interaction, max(0, min(most, value)))
            return pressed

        for text, value, off in (
            ("−1", current - 1, current <= 0), ("+1", current + 1, current >= most),
            (all_label, most, current >= most), ("0", 0, current <= 0),
        ):
            self.button(text, discord.ButtonStyle.secondary, set_to(value), row=row,
                        choice=(*choice, text), disabled=off)

    async def on_nothing(self, interaction) -> None:
        await self.answer(interaction, None)

    async def answer(self, interaction: discord.Interaction, action: Optional[Action],
                     state: Optional[PanelState] = None) -> None:
        """An answer through the service, or with `action` `None` the
        panel shown again with `state` -- either way the panel redrawn
        in place, through the click's own response."""
        await self.cog.answer_panel(interaction, self, action, replace(state or self.state, notice=None))


# -- Infrastructure and Deployment -------------------------------------------------


class PlanPanelView(PanelView):
    """
    The plan (TNP 5.2, 5.3), in two steps. **① Infrastructure**: a button
    a unit to build and a row for its count, a button a facility or
    upgrade to place or take back. **② Deployment**: a button a pile --
    each attack spot, the base's, the three defense spots -- its
    territory from a menu, a button a unit at the base and a row for its
    count. **Clear** empties the step shown; **Lock in plan** locks the
    whole plan, asking once more where a step is empty. Every change
    saves the whole plan.
    """

    def __init__(self, *args) -> None:
        super().__init__(*args)
        self.plan = full_plan(self.options.plan)
        if self.state.confirm:
            empty = empty_steps(self.plan)
            self.button(f"Back to {STEP_LABELS[empty[0]]}" if empty else "Back",
                        discord.ButtonStyle.primary, self.on_back, row=0, choice=("back",))
            self.button("Lock in anyway", discord.ButtonStyle.success, self.on_lock_anyway, row=0,
                        choice=("lock", "anyway"))
            return
        step = self.state.step if self.state.step in STEP_LABELS else INFRASTRUCTURE
        for one in (INFRASTRUCTURE, DEPLOYMENT):
            self.button(STEP_LABELS[one],
                        discord.ButtonStyle.primary if one == step else discord.ButtonStyle.secondary,
                        self.stepper(one), row=0, choice=("step", one))
        self.button("Clear Infrastructure" if step == INFRASTRUCTURE else "Clear Deployment",
                    discord.ButtonStyle.danger, self.on_clear, row=0, choice=("clear",))
        self.button("Lock in plan", discord.ButtonStyle.success, self.on_lock, row=0, choice=("lock",))
        if step == INFRASTRUCTURE:
            self.infrastructure()
        else:
            self.deployment()

    # -- What the plan holds ---------------------------------------------

    def defended(self) -> list[str]:
        """The territories the plan defends, in number order: defense
        spots 1, 2 and 3."""
        return sorted((area for area in self.plan["defense"] if area != base_of(self.seat)), key=area_order)

    def spot_label(self, pile: str) -> str:
        """The attack board's name of a pile: "A", "1", "base"."""
        if pile == "base":
            return "base"
        if pile.startswith("d:"):
            defended = self.defended()
            if pile[2:] in defended:
                return str(defended.index(pile[2:]) + 1)
            return str(len(defended) + 1)
        return pile

    def pile_units(self, pile: str) -> dict:
        if pile == "base":
            return dict(self.plan["defense"].get(base_of(self.seat), {}))
        if pile.startswith("d:"):
            return dict(self.plan["defense"].get(pile[2:], {}))
        return dict((self.plan["attacks"].get(pile) or {}).get("units", {}))

    def pile_area(self, pile: str) -> Optional[str]:
        """The territory a pile's card names: saved, or chosen and not
        yet an answer."""
        if pile == "base":
            return base_of(self.seat)
        if pile == NEW_DEFENSE:
            return self.state.target(pile)
        if pile.startswith("d:"):
            return pile[2:]
        attack = self.plan["attacks"].get(pile)
        return attack["target"] if attack else self.state.target(pile)

    def left(self, slug: str) -> int:
        """How many of a unit are at the base and in no pile."""
        going = sum(attack["units"].get(slug, 0) for attack in self.plan["attacks"].values())
        going += sum(units.get(slug, 0) for units in self.plan["defense"].values())
        return max(0, int(self.options.available.get(slug, 0)) - going)

    # -- ① Infrastructure ------------------------------------------------

    def infrastructure(self) -> None:
        build = list(self.options.build)
        if build:
            chosen = self.state.unit if self.state.unit in {one.unit for one in build} else build[0].unit
            self.buttons([
                Choice(
                    self.name(one.unit) + (f" · {self.plan['build'][one.unit]}"
                                           if self.plan["build"].get(one.unit) else ""),
                    self.build_picker(one.unit),
                    discord.ButtonStyle.primary if one.unit == chosen else discord.ButtonStyle.secondary,
                    ("build", one.unit),
                )
                for one in build
            ], rows=(1,), key="build")
            offer = next(one for one in build if one.unit == chosen)
            current = int(self.plan["build"].get(chosen, 0))
            self.counter_row(f"{self.name(chosen)}: {current} of {offer.most}", current, offer.most,
                             self.build_count(chosen), row=2, all_label=f"Max ({offer.most})",
                             choice=("count",))
        placed = set(self.plan["structures"])
        structures = [
            Choice(
                ("✓ " if one.structure in placed else "")
                + f"{self.name(one.structure)} · {self.cog.cost_words(one.materials, one.gold)}",
                self.structure_toggle(one.structure),
                discord.ButtonStyle.success if one.structure in placed else discord.ButtonStyle.secondary,
                ("structure", one.structure),
            )
            for one in self.options.structures
        ]
        if structures:
            self.buttons(structures, rows=(3, 4), key="structures")

    def build_picker(self, unit: str):
        async def pressed(interaction) -> None:
            await self.answer(interaction, None, replace(self.state, unit=unit))
        return pressed

    def build_count(self, unit: str):
        async def apply(interaction, value: int) -> None:
            plan = copy.deepcopy(self.plan)
            plan["build"][unit] = value
            await self.answer(interaction, self.save(plan), replace(self.state, unit=unit))
        return apply

    def structure_toggle(self, structure: str):
        async def pressed(interaction) -> None:
            plan = copy.deepcopy(self.plan)
            if structure in plan["structures"]:
                plan["structures"] = [one for one in plan["structures"] if one != structure]
            else:
                plan["structures"] = [*plan["structures"], structure]
            await self.answer(interaction, self.save(plan))
        return pressed

    # -- ② Deployment ----------------------------------------------------

    def territories_to_defend(self, pile: Optional[str] = None) -> list[str]:
        """The held territories a defense spot may take: joined to the
        base (`options.defenses`), and whose card is in no other spot
        (`options.cards`, TNP 2.5)."""
        own = pile[2:] if pile and pile.startswith("d:") else None
        return [
            area for area in self.options.defenses
            if area != base_of(self.seat) and (area == own or area not in self.options.cards)
        ]

    def piles(self) -> tuple[list[str], list[str]]:
        """The board's piles, as its two rows: the attack spots and the
        base's; then the defense spots -- each defended territory, and one
        spot more while fewer than three are defended and a territory is
        left to defend."""
        defended = self.defended()
        defenses = [f"d:{area}" for area in defended]
        if len(defended) < self.options.defense_spots and self.territories_to_defend():
            defenses.append(NEW_DEFENSE)
        return [*self.options.spots, "base"], defenses

    def pile_button_label(self, pile: str) -> str:
        if pile == "base":
            return "Base defense"
        area = self.pile_area(pile)
        if pile.startswith("d:"):
            spot = self.spot_label(pile)
            return f"Defense {spot} · {self.area_name(area)}" if area else f"Defense {spot} · empty"
        return f"Attack {pile} · {self.area_name(area)}" if area else f"Attack {pile}"

    def deployment(self) -> None:
        attacks, defenses = self.piles()
        every = attacks + defenses
        pile = self.state.pile if self.state.pile in every else every[0]
        self.state = replace(self.state, pile=pile)
        for row, group in ((1, attacks), (2, defenses)):
            for one in group:
                self.button(self.pile_button_label(one),
                            discord.ButtonStyle.primary if one == pile else discord.ButtonStyle.secondary,
                            self.pile_picker(one), row=row, choice=("pile", one))
        if pile != "base" and (self.pile_area(pile) is None or self.state.choosing):
            self.territory_menu(pile, row=3)
            return
        units = [
            slug for slug, count in self.options.available.items()
            if count and (pile == "base" or slug not in self.options.base_only)
        ]
        if not units:
            self.label("Nothing at your base to deploy here", row=3)
            return
        here = self.pile_units(pile)
        chosen = self.state.unit if self.state.unit in units else units[0]
        choices = [
            Choice(f"{self.name(slug)} · {self.left(slug)} left", self.deploy_picker(slug),
                   discord.ButtonStyle.primary if slug == chosen else discord.ButtonStyle.secondary,
                   ("unit", slug))
            for slug in units
        ]
        if pile != "base":
            choices.append(Choice("Change territory…", self.on_choose_territory, choice=("territory",)))
        self.buttons(choices, rows=(3,), key="units")
        current = int(here.get(chosen, 0))
        where = ("the base defense" if pile == "base"
                 else f"defense {self.spot_label(pile)}" if pile.startswith("d:") else f"attack {pile}")
        self.counter_row(f"{self.name(chosen)} in {where}: {current}", current,
                         current + self.left(chosen), self.deploy_count(pile, chosen), row=4,
                         choice=("count",))

    def territory_menu(self, pile: str, row: int) -> None:
        """A pile's territory: for an attack, every target whose card is
        in no other spot, those with a path now first; for a defense,
        the held territories joined to the base whose card is free."""
        current = self.pile_area(pile)
        if pile.startswith("d:"):
            offered = [
                discord.SelectOption(label=_label(self.area_name(area)), value=area, default=area == current)
                for area in self.territories_to_defend(pile)
            ]
            placeholder = f"Defense {self.spot_label(pile)}'s territory"
        else:
            targets = [one for one in self.options.targets if self.options.cards.get(one.area, pile) == pile]
            targets.sort(key=lambda one: not one.path)
            offered = []
            for one in targets[:MENU_OPTIONS]:
                held = "" if one.area.endswith("_base") else (
                    "neutral" if one.held_by is None else one.held_by.title()
                )
                offered.append(discord.SelectOption(
                    label=_label(self.area_name(one.area) + (f" — {held}" if held else "")),
                    description=None if one.path else "No current path",
                    value=one.area, default=one.area == current,
                ))
            placeholder = f"Attack {pile}'s target"
        if not offered:
            self.label("No territory to choose", row=row)
            return
        select = discord.ui.Select(placeholder=placeholder, options=offered, row=row)

        async def chosen(interaction: discord.Interaction) -> None:
            await self.on_territory(interaction, pile, select.values[0])

        select.callback = chosen
        self.add_item(select)

    def pile_picker(self, pile: str):
        async def pressed(interaction) -> None:
            await self.answer(interaction, None, replace(self.state, pile=pile, choosing=False))
        return pressed

    def deploy_picker(self, unit: str):
        async def pressed(interaction) -> None:
            await self.answer(interaction, None, replace(self.state, unit=unit))
        return pressed

    async def on_choose_territory(self, interaction) -> None:
        await self.answer(interaction, None, replace(self.state, choosing=True))

    async def on_territory(self, interaction, pile: str, area: str) -> None:
        """A pile's territory chosen: saved where the pile has units -- an
        attack's target changed, a defense moved -- or held by the panel
        until a unit goes in."""
        state = replace(self.state, choosing=False)
        if not self.pile_units(pile):
            await self.answer(interaction, None, replace(state, targets=_with(state.targets, pile, area)))
            return
        plan = copy.deepcopy(self.plan)
        if pile.startswith("d:"):
            plan["defense"][area] = plan["defense"].pop(pile[2:], {})
            state = replace(state, pile=f"d:{area}")
        else:
            plan["attacks"][pile]["target"] = area
        await self.answer(interaction, self.save(plan), state)

    def deploy_count(self, pile: str, unit: str):
        async def apply(interaction, value: int) -> None:
            plan = copy.deepcopy(self.plan)
            area = self.pile_area(pile)
            state = replace(self.state, unit=unit)
            if area is None:
                await self.answer(interaction, None, replace(state, choosing=True))
                return
            if pile == "base" or pile.startswith("d:"):
                plan["defense"].setdefault(area, {})[unit] = value
                if pile == NEW_DEFENSE:
                    state = replace(state, pile=f"d:{area}", targets=_with(state.targets, pile, None))
            else:
                attack = plan["attacks"].get(pile) or {"target": area, "units": {}}
                attack["units"][unit] = value
                plan["attacks"][pile] = attack
            await self.answer(interaction, self.save(plan), state)
        return apply

    # -- The step, Clear and Lock in ---------------------------------------

    def save(self, plan: dict) -> Action:
        return Action(PromptKind.PLAN, "save", {"plan": plan}, seat=self.seat)

    def stepper(self, step: str):
        async def pressed(interaction) -> None:
            await self.answer(interaction, None, replace(self.state, step=step, unit=None, choosing=False))
        return pressed

    async def on_clear(self, interaction) -> None:
        plan = copy.deepcopy(self.plan)
        state = self.state
        if state.step == DEPLOYMENT:
            plan["attacks"], plan["defense"] = {}, {}
            state = replace(state, targets=(), pile=None, choosing=False)
        else:
            plan["build"], plan["structures"] = {}, []
        await self.answer(interaction, self.save(plan), state)

    async def on_lock(self, interaction) -> None:
        """**Lock in plan** -- but where a step is empty, the warning
        first (the author, 2026-11-06)."""
        if empty_steps(self.plan):
            await self.answer(interaction, None, replace(self.state, confirm=True))
            return
        await self.answer(interaction, Action(PromptKind.PLAN, "lock", seat=self.seat))

    async def on_lock_anyway(self, interaction) -> None:
        await self.answer(interaction, Action(PromptKind.PLAN, "lock", seat=self.seat),
                          replace(self.state, confirm=False))

    async def on_back(self, interaction) -> None:
        empty = empty_steps(self.plan)
        await self.answer(interaction, None, replace(
            self.state, confirm=False, step=empty[0] if empty else self.state.step,
        ))


# -- Production and Trade -------------------------------------------------------------


class TradePanelView(PanelView):
    """The trade (TNP 5.9): a token kind, then how many of it for
    materials and how many for gold; **Clear trade** and **Lock in**.
    Each change saves the whole trade."""

    def __init__(self, *args) -> None:
        super().__init__(*args)
        held = [kind for kind, count in self.options.tokens.items() if count]
        trade = copy.deepcopy(dict(self.options.trade or {}))
        trade.setdefault("materials", {})
        trade.setdefault("gold", {})
        self.trade = trade
        kind = self.state.kind if self.state.kind in held else (held[0] if held else None)
        self.state = replace(self.state, kind=kind)
        for one in held:
            self.button(self.cog.token_words(one, self.options.tokens[one]),
                        discord.ButtonStyle.primary if one == kind else discord.ButtonStyle.secondary,
                        self.kind_picker(one), row=0, choice=("kind", one))
        if kind is not None:
            most = int(self.options.tokens[kind])
            for row, into, other in ((1, "materials", "gold"), (2, "gold", "materials")):
                current = int(trade[into].get(kind, 0))
                room = most - int(trade[other].get(kind, 0))
                self.counter_row(f"For {into}: {current}", current, room, self.counter(into), row=row,
                                 choice=(into,))
        self.button("Clear trade", discord.ButtonStyle.danger, self.on_clear, row=3, choice=("clear",))
        self.button("Lock in", discord.ButtonStyle.success, self.on_lock, row=3, choice=("lock",))

    def kind_picker(self, kind: str):
        async def pressed(interaction) -> None:
            await self.answer(interaction, None, replace(self.state, kind=kind))
        return pressed

    def counter(self, into: str):
        async def apply(interaction, value: int) -> None:
            trade = copy.deepcopy(self.trade)
            trade[into][self.state.kind] = value
            await self.answer(interaction, Action(PromptKind.TRADE, "save", {"trade": trade}, seat=self.seat))
        return apply

    async def on_lock(self, interaction) -> None:
        await self.answer(interaction, Action(PromptKind.TRADE, "lock", seat=self.seat))

    async def on_clear(self, interaction) -> None:
        await self.answer(interaction, Action(PromptKind.TRADE, "save", {"trade": {}}, seat=self.seat))


# -- March's questions -----------------------------------------------------------------


class ConquerPanelView(PanelView):
    """Which ground unit is revealed to take a neutral territory (TNP 5.5):
    a button each."""

    def __init__(self, *args) -> None:
        super().__init__(*args)
        self.buttons([
            Choice(f"Reveal a {self.name(unit)}", self.revealer(unit), discord.ButtonStyle.primary,
                   ("reveal", unit))
            for unit in self.options.units
        ], rows=(0, 1), key="reveal")

    def revealer(self, unit: str):
        async def pressed(interaction) -> None:
            await self.answer(interaction, Action(PromptKind.CONQUER, "", {"unit": unit}, seat=self.seat))
        return pressed


class HarvestPanelView(PanelView):
    """Which tokens the Workers take (TNP 5.8): a row for each kind left,
    then **Take** -- the model refuses a total that is not one a Worker."""

    def __init__(self, *args) -> None:
        super().__init__(*args)
        taken = dict(self.state.taken)
        count = int(self.options.count)
        for row, (kind, left) in enumerate(self.options.left.items()):
            current = int(taken.get(kind, 0))
            room = min(int(left), count - sum(n for one, n in taken.items() if one != kind))
            words = TOKEN_WORDS.get(kind, (kind, kind))[1]
            self.counter_row(f"{words[:1].upper()}{words[1:]}: {current}", current, max(0, room),
                             self.counter(kind), row=row, choice=(kind,))
        self.button(f"Take {count}", discord.ButtonStyle.success, self.on_take,
                    row=min(len(self.options.left), 4), choice=("take",))

    def counter(self, kind: str):
        async def apply(interaction, value: int) -> None:
            await self.answer(interaction, None, replace(self.state, taken=_with(self.state.taken, kind, value)))
        return apply

    async def on_take(self, interaction) -> None:
        await self.answer(interaction, Action(
            PromptKind.HARVEST, "", {"tokens": dict(self.state.taken)}, seat=self.seat,
        ))


#: The turn's prompt kinds, each to its panel. A battle's are step 7's.
PANELS = {
    PromptKind.PLAN: PlanPanelView,
    PromptKind.TRADE: TradePanelView,
    PromptKind.CONQUER: ConquerPanelView,
    PromptKind.HARVEST: HarvestPanelView,
}


def panel_view(cog, game_id: str, seat: str, prompt: Optional[PendingPrompt],
               state: PanelState) -> Optional[PanelView]:
    """**The one place a prompt kind becomes a panel**: `None` where the
    seat is asked nothing, or a battle's question, which step 7 puts on
    Discord."""
    if prompt is None or prompt.kind not in PANELS:
        return None
    return PANELS[prompt.kind](cog, game_id, seat, prompt, state)


__all__ = [
    "ConquerPanelView", "DEPLOYMENT", "HarvestPanelView", "INFRASTRUCTURE", "PANELS", "PANEL_TIMEOUT",
    "PanelState", "PanelView", "PlanPanelView", "TradePanelView", "empty_steps", "panel_view",
]

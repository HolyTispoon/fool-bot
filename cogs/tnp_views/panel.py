"""
A seat's panel: the controls under its board, ephemeral, to its player
alone (docs/design/tnp.md, "The turn on Discord"). One view a prompt
kind of the turn's -- `PlanPanelView` (Infrastructure and Deployment),
`TradePanelView` (Production and Trade's trade), `ConquerPanelView` and
`HarvestPanelView` (March's two questions) -- each built from
`PendingPrompt.options` and nothing else, and `panel_view` the one
mapping from a prompt to its view.

**Every change is an answer through the service.** A plan or a trade is
saved on the match with each change (`save`), checked as it is saved,
and locked in by **Lock in** (`lock`), so a restart keeps it and the
model refuses what the rules do not allow -- the panel shows the
refusal and keeps what was saved. What a panel holds itself is only
which part of the plan is being changed and a choice not yet an answer
(the unit a count is for, an attack's target before any unit is in it,
a harvest's tokens before **Take**).

Not persistent: a panel answers clicks for `PANEL_TIMEOUT`, and after
that or a restart **My board** opens a fresh one over the plan saved on
the match. No view saves.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, replace
from typing import Optional

import discord

from cogs.tnp_views.base import SafeView, send_ephemeral
from tnp.formatting import TOKEN_WORDS
from tnp.prompts import Action, PendingPrompt, PromptKind
from tnp.turn import base_of

#: How long a panel answers clicks: a phase, generously. An expired
#: panel is reopened from **My board**, which makes a fresh one over the
#: plan saved on the match.
PANEL_TIMEOUT = 3600

#: Discord's limits on a menu: its options and a label's length.
MENU_OPTIONS = 25
LABEL_LENGTH = 100


@dataclass(frozen=True)
class PanelState:
    """What a panel holds that is not yet an answer."""

    #: The plan's part being changed: "build", "structures",
    #: "attack:<spot>" or "defense:<area>".
    section: str = "build"
    #: The unit a count menu is for.
    unit: Optional[str] = None
    #: An attack's target chosen before any unit is in it, by spot.
    targets: tuple = ()
    #: The token kind a trade's two counts are for.
    kind: Optional[str] = None
    #: A harvest's tokens chosen so far, by kind, before **Take**.
    taken: tuple = ()
    #: A refusal or a word to show above the panel, once.
    notice: Optional[str] = None
    #: The turn and phase the panel's board was drawn at.
    drawn: tuple = ()

    def target(self, spot: str) -> Optional[str]:
        return dict(self.targets).get(spot)


def _label(text: str) -> str:
    return text if len(text) <= LABEL_LENGTH else text[: LABEL_LENGTH - 1] + "…"


def _counts(most: int, current: int) -> list[discord.SelectOption]:
    """0 to `most`, the current count marked -- 25 at most, the last of
    them `most` itself where it is more."""
    values = list(range(0, most + 1))
    if len(values) > MENU_OPTIONS:
        values = values[: MENU_OPTIONS - 1] + [most]
    return [
        discord.SelectOption(label=str(value), value=str(value), default=value == current)
        for value in values
    ]


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

    def menu(self, placeholder: str, options: list[discord.SelectOption], callback, *,
             row: int, low: int = 1, high: int = 1, disabled: bool = False) -> discord.ui.Select:
        if not options:
            options = [discord.SelectOption(label="Nothing to choose", value="-")]
            disabled = True
        select = discord.ui.Select(
            placeholder=placeholder, options=options[:MENU_OPTIONS], row=row,
            min_values=low, max_values=min(high, len(options[:MENU_OPTIONS])), disabled=disabled,
        )

        async def chosen(interaction: discord.Interaction) -> None:
            await callback(interaction, select.values)

        select.callback = chosen
        self.add_item(select)
        return select

    def button(self, label: str, style: discord.ButtonStyle, callback, *, row: int = 4) -> None:
        item = discord.ui.Button(label=label, style=style, row=row)
        item.callback = callback
        self.add_item(item)

    async def answer(self, interaction: discord.Interaction, action: Optional[Action],
                     state: Optional[PanelState] = None) -> None:
        """An answer through the service, or with `action` `None` the
        panel shown again with `state` -- either way the panel redrawn
        in place by the click's own response."""
        await self.cog.answer_panel(interaction, self, action, state or replace(self.state, notice=None))


# -- Infrastructure and Deployment -------------------------------------------------


class PlanPanelView(PanelView):
    """
    The plan (TNP 5.2, 5.3): which part to change -- the units to build,
    the facilities and upgrades, attack spots A and B, each defense --
    then that part's menus; **Lock in** and **Clear**. Every change saves
    the whole plan, as the model keeps it.
    """

    def __init__(self, *args) -> None:
        super().__init__(*args)
        options = self.options
        self.plan = copy.deepcopy(dict(options.plan or {}))
        for part, empty in (("build", {}), ("structures", []), ("attacks", {}), ("defense", {})):
            self.plan.setdefault(part, empty)
        sections = [discord.SelectOption(label="Build units", value="build")]
        if options.structures:
            sections.append(discord.SelectOption(label="Facilities and upgrades", value="structures"))
        sections += [
            discord.SelectOption(label=f"Attack {spot}", value=f"attack:{spot}") for spot in options.spots
        ]
        sections += [
            discord.SelectOption(label=_label(f"Defend {self.area_name(area)}"), value=f"defense:{area}")
            for area in options.defenses
        ]
        section = self.state.section
        if section not in {one.value for one in sections}:
            section = "build"
            self.state = replace(self.state, section=section, unit=None)
        for one in sections:
            one.default = one.value == section
        self.menu("What to change", sections, self.on_section, row=0)
        if section == "build":
            self.build_menus()
        elif section == "structures":
            self.structure_menu()
        elif section.startswith("attack:"):
            self.attack_menus(section.split(":", 1)[1])
        else:
            self.defense_menus(section.split(":", 1)[1])
        self.button("Lock in", discord.ButtonStyle.success, self.on_lock)
        self.button("Clear plan", discord.ButtonStyle.danger, self.on_clear)

    # -- The menus ---------------------------------------------------

    def unit_menu(self, placeholder: str, offered: list[tuple[str, str]], row: int) -> Optional[str]:
        """A menu of units, `(slug, label)`; the one chosen, or the first."""
        chosen = self.state.unit if self.state.unit in {slug for slug, _ in offered} else None
        if chosen is None and offered:
            chosen = offered[0][0]
        self.menu(placeholder, [
            discord.SelectOption(label=_label(label), value=slug, default=slug == chosen)
            for slug, label in offered
        ], self.on_unit, row=row)
        return chosen

    def build_menus(self) -> None:
        offered = [
            (one.unit, f"{self.name(one.unit)} -- {self.cog.cost_words(one.materials, one.gold)}, up to {one.most}")
            for one in self.options.build
        ]
        unit = self.unit_menu("Unit to build", offered, row=1)
        if unit is None:
            return
        most = next(one.most for one in self.options.build if one.unit == unit)
        self.menu(f"How many {self.name(unit)} to build", _counts(most, self.plan["build"].get(unit, 0)),
                  self.on_build, row=2)

    def structure_menu(self) -> None:
        chosen = set(self.plan["structures"])
        offered = [
            discord.SelectOption(
                label=_label(f"{self.name(one.structure)} -- {self.cog.cost_words(one.materials, one.gold)}"),
                value=one.structure, default=one.structure in chosen,
            )
            for one in self.options.structures
        ]
        self.menu("Facilities and upgrades to place", offered, self.on_structures, row=1,
                  low=0, high=len(offered))

    def deployable(self, base: bool) -> list[tuple[str, str]]:
        """The units at the base, each with how many are there; a Base
        Defense unit only for the base's own defense spot (TNP 7)."""
        return [
            (slug, f"{self.name(slug)} -- {count} at your base")
            for slug, count in self.options.available.items()
            if count and (base or slug not in self.options.base_only)
        ]

    def attack_menus(self, spot: str) -> None:
        attack = self.plan["attacks"].get(spot)
        target = attack["target"] if attack else self.state.target(spot)
        offered = []
        for one in self.options.targets:
            held = "neutral" if one.held_by is None else f"held by {one.held_by.title()}"
            path = "a path now" if one.path else "no path now"
            offered.append(discord.SelectOption(
                label=_label(f"{self.area_name(one.area)} -- {held}, {path}"),
                value=one.area, default=one.area == target,
            ))
        self.menu(f"Attack {spot}'s target", offered, self.on_target, row=1)
        unit = self.unit_menu(f"Unit for attack {spot}", self.deployable(base=False), row=2)
        if unit is None:
            return
        current = (attack or {}).get("units", {}).get(unit, 0)
        self.menu(f"How many {self.name(unit)} in attack {spot}",
                  _counts(self.options.available.get(unit, 0), current), self.on_attack_count, row=3)

    def defense_menus(self, area: str) -> None:
        unit = self.unit_menu(f"Unit to defend {self.area_name(area)}",
                              self.deployable(base=area == base_of(self.seat)), row=1)
        if unit is None:
            return
        current = self.plan["defense"].get(area, {}).get(unit, 0)
        self.menu(f"How many {self.name(unit)} defend {self.area_name(area)}",
                  _counts(self.options.available.get(unit, 0), current), self.on_defense_count, row=2)

    # -- The callbacks -------------------------------------------------

    def save(self, plan: dict) -> Action:
        return Action(PromptKind.PLAN, "save", {"plan": plan}, seat=self.seat)

    async def on_section(self, interaction, values) -> None:
        await self.answer(interaction, None, replace(self.state, section=values[0], unit=None, notice=None))

    async def on_unit(self, interaction, values) -> None:
        await self.answer(interaction, None, replace(self.state, unit=values[0], notice=None))

    async def on_build(self, interaction, values) -> None:
        unit = self.current_unit()
        plan = copy.deepcopy(self.plan)
        plan["build"][unit] = int(values[0])
        await self.answer(interaction, self.save(plan), replace(self.state, unit=unit, notice=None))

    async def on_structures(self, interaction, values) -> None:
        plan = copy.deepcopy(self.plan)
        plan["structures"] = [value for value in values if value != "-"]
        await self.answer(interaction, self.save(plan))

    async def on_target(self, interaction, values) -> None:
        spot = self.state.section.split(":", 1)[1]
        target = values[0]
        if spot in self.plan["attacks"]:
            plan = copy.deepcopy(self.plan)
            plan["attacks"][spot]["target"] = target
            await self.answer(interaction, self.save(plan))
            return
        targets = dict(self.state.targets)
        targets[spot] = target
        await self.answer(interaction, None, replace(self.state, targets=tuple(sorted(targets.items())), notice=None))

    async def on_attack_count(self, interaction, values) -> None:
        spot = self.state.section.split(":", 1)[1]
        unit = self.current_unit()
        plan = copy.deepcopy(self.plan)
        attack = plan["attacks"].get(spot)
        target = attack["target"] if attack else self.state.target(spot)
        if target is None:
            await self.answer(interaction, None, replace(
                self.state, unit=unit, notice=f"Choose attack {spot}'s target first.",
            ))
            return
        attack = attack or {"target": target, "units": {}}
        attack["units"][unit] = int(values[0])
        plan["attacks"][spot] = attack
        await self.answer(interaction, self.save(plan), replace(self.state, unit=unit, notice=None))

    async def on_defense_count(self, interaction, values) -> None:
        area = self.state.section.split(":", 1)[1]
        unit = self.current_unit()
        plan = copy.deepcopy(self.plan)
        plan["defense"].setdefault(area, {})[unit] = int(values[0])
        await self.answer(interaction, self.save(plan), replace(self.state, unit=unit, notice=None))

    def current_unit(self) -> str:
        """The unit the count menu on the panel is for -- the one the
        unit menu shows chosen."""
        for item in self.children:
            if isinstance(item, discord.ui.Select) and (item.placeholder or "").startswith(("Unit ",)):
                for option in item.options:
                    if option.default:
                        return option.value
        return self.state.unit

    async def on_lock(self, interaction) -> None:
        await self.answer(interaction, Action(PromptKind.PLAN, "lock", seat=self.seat))

    async def on_clear(self, interaction) -> None:
        await self.answer(interaction, self.save({}), replace(self.state, targets=(), notice=None))


# -- Production and Trade -------------------------------------------------------------


class TradePanelView(PanelView):
    """The trade (TNP 5.9): a token kind, how many of it for materials
    and how many for gold; **Lock in** and **Clear**. Each change saves
    the whole trade."""

    def __init__(self, *args) -> None:
        super().__init__(*args)
        held = [kind for kind, count in self.options.tokens.items() if count]
        trade = copy.deepcopy(dict(self.options.trade or {}))
        trade.setdefault("materials", {})
        trade.setdefault("gold", {})
        self.trade = trade
        kind = self.state.kind if self.state.kind in held else (held[0] if held else None)
        self.state = replace(self.state, kind=kind)
        self.menu("Token to trade", [
            discord.SelectOption(label=self.cog.token_words(one, self.options.tokens[one]),
                                 value=one, default=one == kind)
            for one in held
        ], self.on_kind, row=0)
        if kind is not None:
            most = int(self.options.tokens[kind])
            for row, into in ((1, "materials"), (2, "gold")):
                self.menu(f"How many for {into}", _counts(most, trade[into].get(kind, 0)),
                          self.counter(into), row=row)
        self.button("Lock in", discord.ButtonStyle.success, self.on_lock)
        self.button("Clear trade", discord.ButtonStyle.danger, self.on_clear)

    def counter(self, into: str):
        async def chosen(interaction, values) -> None:
            trade = copy.deepcopy(self.trade)
            trade[into][self.state.kind] = int(values[0])
            await self.answer(interaction, Action(PromptKind.TRADE, "save", {"trade": trade}, seat=self.seat),
                              replace(self.state, notice=None))
        return chosen

    async def on_kind(self, interaction, values) -> None:
        await self.answer(interaction, None, replace(self.state, kind=values[0], notice=None))

    async def on_lock(self, interaction) -> None:
        await self.answer(interaction, Action(PromptKind.TRADE, "lock", seat=self.seat))

    async def on_clear(self, interaction) -> None:
        await self.answer(interaction, Action(PromptKind.TRADE, "save", {"trade": {}}, seat=self.seat))


# -- March's questions -----------------------------------------------------------------


class ConquerPanelView(PanelView):
    """Which ground unit is revealed to take a neutral territory (TNP 5.5)."""

    def __init__(self, *args) -> None:
        super().__init__(*args)
        self.menu("Ground unit to reveal", [
            discord.SelectOption(label=self.name(unit), value=unit) for unit in self.options.units
        ], self.on_unit, row=0)

    async def on_unit(self, interaction, values) -> None:
        await self.answer(interaction, Action(PromptKind.CONQUER, "", {"unit": values[0]}, seat=self.seat))


class HarvestPanelView(PanelView):
    """Which tokens the Workers take (TNP 5.8): a count of each kind
    left, then **Take** -- the model refuses a total that is not one a
    Worker."""

    def __init__(self, *args) -> None:
        super().__init__(*args)
        taken = dict(self.state.taken)
        for row, (kind, left) in enumerate(self.options.left.items()):
            most = min(int(left), int(self.options.count))
            self.menu(f"How many {TOKEN_WORDS.get(kind, (kind, kind))[1]}",
                      _counts(most, taken.get(kind, 0)), self.counter(kind), row=row)
        self.button(f"Take {self.options.count}", discord.ButtonStyle.success, self.on_take)

    def counter(self, kind: str):
        async def chosen(interaction, values) -> None:
            taken = dict(self.state.taken)
            taken[kind] = int(values[0])
            await self.answer(interaction, None, replace(self.state, taken=tuple(sorted(taken.items())), notice=None))
        return chosen

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
    "ConquerPanelView", "HarvestPanelView", "PANELS", "PANEL_TIMEOUT", "PanelState", "PanelView",
    "PlanPanelView", "TradePanelView", "panel_view",
]

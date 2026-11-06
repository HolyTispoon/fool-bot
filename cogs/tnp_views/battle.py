"""
A battle's controls, on the battle's own message (docs/design/tnp.md,
"Battles on Discord"): one view a battle prompt kind, each built from
`PendingPrompt.options` and nothing else, and `battle_view` the one
mapping from a prompt to its view.

A battle reveals every unit in it (TNP 6.1), so its question is public:
the controls sit on the public message, under the battle's picture, and
**only the asked seat's player may use them** -- both seats', in a test
game. Every click is an answer through the service, and the message is
redrawn by the click's own response, which spends nothing from the
channel's bucket (docs/design/rate-limits.md).

**Persistent, and right after a restart.** Each item's `custom_id` is
fixed by the game and the item's part, so the startup sweep re-arms the
view by the message's id. Every menu's value is a whole answer -- a
force and its slot, a force and its target, a count and what it is of --
so a menu clicked on a message drawn before a restart answers what it
shows. What a view holds that is not yet an answer (`BattleHeld`: the
force a slot or target menu is for, the counts a retreat, a repair or an
emergency defense is made of) is lost with a restart, so a button that
would send it shows the question afresh instead (`restored`).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Optional

import discord

from cogs.tnp_views.base import SafeView, send_ephemeral
from tnp.formatting import (
    battle_force_text, cost_text, slot_text, target_reason, target_text,
)
from tnp import tokens
from tnp.catalog import Cost
from tnp.prompts import Action, PendingPrompt, PromptKind

#: Discord's limits on a menu: its options, a label's length and an
#: option's description.
MENU_OPTIONS = 25
LABEL_LENGTH = 100

#: What an emergency defense's trades are called (TNP 6.2), by the key
#: `answer_emergency` reads.
TRADE_WORDS = {
    "blue": "Blue minerals for materials",
    "orange": "Orange minerals for materials",
    "gems_materials": "Gems for materials",
    "gems_gold": "Gems for gold",
}
#: Which pool count each trade spends.
TRADE_POOL = {"blue": "blue", "orange": "orange", "gems_materials": "gems", "gems_gold": "gems"}

#: Told after a restart, where a button would send what the view held.
RESTORED = "The bot restarted since this was drawn, so here is the question afresh."


@dataclass(frozen=True)
class BattleHeld:
    """What a battle view holds that is not yet an answer."""

    #: The force a slot or target menu is for.
    force: Optional[str] = None
    #: Counts chosen so far, `(key, count)`: a force carried, Workers
    #: given, a unit produced (`unit:<slug>`) or a trade (`trade:<kind>`).
    counts: tuple = ()
    #: An emergency defense's part shown: "units" or "trade".
    section: str = "units"
    #: Shown at the message's head once, by `Tnp.redraw_battle`.
    notice: Optional[str] = None

    def count(self, key: str) -> int:
        return int(dict(self.counts).get(key, 0))

    def with_count(self, key: str, count: int) -> "BattleHeld":
        counts = dict(self.counts)
        counts[key] = int(count)
        return replace(self, counts=tuple(sorted(counts.items())), notice=None)


def _label(text: str) -> str:
    return text if len(text) <= LABEL_LENGTH else text[: LABEL_LENGTH - 1] + "…"


def _counts(most: int, current: int, key: str) -> list[discord.SelectOption]:
    """0 to `most`, each value `<key>|<count>`, the current one marked --
    25 at most, the last of them `most` itself where it is more."""
    values = list(range(0, max(0, most) + 1))
    if len(values) > MENU_OPTIONS:
        values = values[: MENU_OPTIONS - 1] + [most]
    return [
        discord.SelectOption(label=str(value), value=f"{key}|{value}", default=value == current)
        for value in values
    ]


def _split(value: str) -> tuple[str, str]:
    one, _, two = value.partition("|")
    return one, two


class BattleView(SafeView):
    """A battle's controls: the clicker must hold the asked seat."""

    def __init__(self, cog, game_id: str, prompt: PendingPrompt, battle,
                 held: BattleHeld = BattleHeld(), restored: bool = False) -> None:
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id
        self.prompt = prompt
        self.options = prompt.options
        self.battle = battle
        self.held = held
        self.restored = restored
        self.build()

    def build(self) -> None:  # pragma: no cover - every kind builds its own
        raise NotImplementedError

    # -- The gate -------------------------------------------------------------

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await super().interaction_check(interaction):
            return False
        game = self.game()
        seat = self.prompt.asked_seat
        if game is None or seat not in game.seats_of(interaction.user.id):
            who = self.cog.render_text(f"{{seat:{seat}}}", game) if game is not None and seat else "a player"
            await send_ephemeral(
                interaction, f"This battle question is {who}'s to answer.",
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return False
        return True

    # -- Building ---------------------------------------------------------------

    def custom_id(self, part: str) -> str:
        return f"tnp:battle:{self.game_id}:{part}"[:100]

    def words(self, text: str) -> str:
        """A token string as a label's plain words."""
        return self.cog.plain_words(text)

    def force_words(self, ident: str) -> str:
        return self.words(battle_force_text(self.battle, ident))

    def menu(self, part: str, placeholder: str, options: list[discord.SelectOption], callback, *,
             row: int, high: int = 1) -> discord.ui.Select:
        disabled = False
        if not options:
            options = [discord.SelectOption(label="Nothing to choose", value="-")]
            disabled = True
        options = options[:MENU_OPTIONS]
        select = discord.ui.Select(
            custom_id=self.custom_id(part), placeholder=_label(placeholder), options=options,
            row=row, min_values=1, max_values=min(high, len(options)), disabled=disabled,
        )

        async def chosen(interaction: discord.Interaction) -> None:
            await callback(interaction, select.values)

        select.callback = chosen
        self.add_item(select)
        return select

    def button(self, part: str, label: str, style: discord.ButtonStyle, callback, *,
               row: int = 4) -> None:
        item = discord.ui.Button(custom_id=self.custom_id(part), label=_label(label), style=style, row=row)
        item.callback = callback
        self.add_item(item)

    # -- Answering --------------------------------------------------------------

    async def answer(self, interaction: discord.Interaction, action: Action) -> None:
        await self.cog.answer_battle(interaction, self, action)

    async def redraw(self, interaction: discord.Interaction, held: BattleHeld) -> None:
        """The same question, with what the view holds changed."""
        await self.cog.redraw_battle(interaction, self, held)

    async def held_answer(self, interaction: discord.Interaction, action: Action) -> None:
        """An answer made of what the view holds -- shown afresh instead
        where a restart lost it (`restored`)."""
        if self.restored:
            await self.redraw(interaction, BattleHeld(notice=RESTORED))
            return
        await self.answer(interaction, action)

    def act(self, choice: str = "", **arguments) -> Action:
        return Action(self.prompt.kind, choice, arguments, seat=self.prompt.asked_seat)

    def counter(self, key: str):
        async def chosen(interaction, values) -> None:
            _, count = _split(values[0])
            await self.redraw(interaction, self.held.with_count(key, int(count)))
        return chosen


class RoleView(BattleView):
    """The scouting advantage's choice of side (TNP 6.1)."""

    def build(self) -> None:
        self.button("role:attack", "Attack", discord.ButtonStyle.danger, self.on_attack)
        self.button("role:defend", "Defend", discord.ButtonStyle.primary, self.on_defend)

    async def on_attack(self, interaction) -> None:
        await self.answer(interaction, self.act("attack"))

    async def on_defend(self, interaction) -> None:
        await self.answer(interaction, self.act("defend"))


class EmergencyView(BattleView):
    """A base's emergency defense (TNP 6.2): how many of each base
    defense unit, and what to trade at the emergency rates to pay for
    them -- two parts, since the menus outnumber a message's rows."""

    def build(self) -> None:
        options = self.options
        if self.held.section == "trade" and getattr(options, "advanced", False):
            self.card_menus()
            self.button("emergency:section", "Back to the units", discord.ButtonStyle.secondary,
                        self.on_section)
        elif self.held.section == "trade":
            for row, kind in enumerate(options.trades[:4]):
                most = int(options.pool.get(TRADE_POOL.get(kind, kind), 0))
                key = f"trade:{kind}"
                self.menu(key, f"{TRADE_WORDS.get(kind, kind)} (of {most})",
                          _counts(most, self.held.count(key), key), self.counter(key), row=row)
            self.button("emergency:section", "Back to the units", discord.ButtonStyle.secondary,
                        self.on_section)
        else:
            for row, unit in enumerate(options.units[:4]):
                key = f"unit:{unit.unit}"
                cost = cost_text(Cost(unit.materials, unit.gold))
                self.menu(key, f"How many {self.cog.catalog.name(unit.unit)} ({cost} each)",
                          _counts(unit.most, self.held.count(key), key), self.counter(key), row=row)
            self.button("emergency:section", "Choose what to trade", discord.ButtonStyle.secondary,
                        self.on_section)
        self.button("emergency:build", "Produce these", discord.ButtonStyle.success, self.on_build)
        self.button("emergency:none", "Produce none", discord.ButtonStyle.secondary, self.on_none)

    def card_menus(self) -> None:
        """The advanced game's trade (TNP 6.2, 8.1): the defender's cards,
        each one chosen for materials or -- a gem card only -- for gold."""
        for row, into in enumerate(("materials", "gold")):
            offered = []
            for one in self.options.cards:
                if into == "gold" and one.deck != "gems":
                    continue
                chosen = self.held.count(f"{into}:{one.card}")
                for index in range(min(one.count, 10)):
                    offered.append(discord.SelectOption(
                        label=_label(self.cog.catalog.name(one.card) + (f" (#{index + 1})" if one.count > 1 else "")),
                        value=f"{one.card}#{index}", default=index < chosen,
                    ))
            word = "Cards for materials" if into == "materials" else "Gem cards for gold"
            select = self.menu(f"emergency:cards:{into}", word, offered, self.card_counter(into),
                               row=row, high=len(offered))
            select.min_values = 0

    def card_counter(self, into: str):
        async def chosen(interaction, values) -> None:
            counts = {key: count for key, count in self.held.counts if not key.startswith(f"{into}:")}
            for value in values:
                if value == "-":
                    continue
                card = value.partition("#")[0]
                counts[f"{into}:{card}"] = counts.get(f"{into}:{card}", 0) + 1
            await self.redraw(interaction, replace(self.held, counts=tuple(sorted(counts.items())), notice=None))
        return chosen

    async def on_section(self, interaction) -> None:
        section = "units" if self.held.section == "trade" else "trade"
        await self.redraw(interaction, replace(self.held, section=section, notice=None))

    async def on_build(self, interaction) -> None:
        held = dict(self.held.counts)
        units = {key.split(":", 1)[1]: count for key, count in held.items() if key.startswith("unit:") and count}
        if getattr(self.options, "advanced", False):
            trade = {
                into: {key.split(":", 1)[1]: count for key, count in held.items()
                       if key.startswith(f"{into}:") and count}
                for into in ("materials", "gold")
            }
        else:
            trade = {key.split(":", 1)[1]: count for key, count in held.items() if key.startswith("trade:") and count}
        await self.held_answer(interaction, self.act("build", units=units, trade=trade))

    async def on_none(self, interaction) -> None:
        await self.answer(interaction, self.act("none"))


class RepositionView(BattleView):
    """Keep the flanking forces where they stand, or take some out to be
    placed again (TNP 6.5)."""

    def build(self) -> None:
        self.menu("reposition:forces", "Flanking forces to reposition", [
            discord.SelectOption(
                label=_label(self.force_words(one.force)), value=one.force,
                description=_label(f"behind {self.force_words(one.behind)}"),
            )
            for one in self.options.flankers
        ], self.on_move, row=0, high=len(self.options.flankers))
        self.button("reposition:keep", "Keep them where they stand", discord.ButtonStyle.primary,
                    self.on_keep)

    async def on_move(self, interaction, values) -> None:
        await self.answer(interaction, self.act("move", forces=list(values)))

    async def on_keep(self, interaction) -> None:
        await self.answer(interaction, self.act("keep"))


class PlaceView(BattleView):
    """One force into the line (TNP 6.5): which, where there is more
    than one, then where."""

    def build(self) -> None:
        forces = self.options.forces
        chosen = next((one for one in forces if one.force == self.held.force), forces[0] if forces else None)
        if len(forces) > 1:
            self.menu("place:force", "Force to place", [
                discord.SelectOption(
                    label=_label(self.force_words(one.force)), value=one.force,
                    default=chosen is not None and one.force == chosen.force,
                )
                for one in forces
            ], self.on_force, row=0)
        if chosen is not None:
            self.menu("place:slot", f"Where {self.force_words(chosen.force)} go", [
                discord.SelectOption(
                    label=_label(self.words(slot_text(self.battle, self.prompt.asked_seat, slot))),
                    value=f"{chosen.force}|{slot}",
                )
                for slot in chosen.slots
            ], self.on_slot, row=1)

    async def on_force(self, interaction, values) -> None:
        await self.redraw(interaction, replace(self.held, force=values[0], notice=None))

    async def on_slot(self, interaction, values) -> None:
        force, slot = _split(values[0])
        await self.answer(interaction, self.act(force=force, slot=slot))


class RetreatView(BattleView):
    """Retreat or fight on (TNP 6.6). With no path home the air units go
    and the Chopper Carriers take what the menus say (TNP 7)."""

    def build(self) -> None:
        options = self.options
        if not options.path_home:
            for row, carry in enumerate(options.carry[:3]):
                key = carry.force
                self.menu(
                    f"retreat:carry:{carry.force}",
                    f"Carry how many {self.cog.catalog.name(carry.unit)} "
                    f"({carry.per_carrier} a Chopper Carrier)",
                    _counts(carry.count, self.held.count(key), key), self.counter(key), row=row,
                )
        self.button("retreat:fight", "Fight on", discord.ButtonStyle.primary, self.on_fight)
        self.button("retreat:go", "Retreat", discord.ButtonStyle.danger, self.on_retreat)

    async def on_fight(self, interaction) -> None:
        await self.answer(interaction, self.act("fight"))

    async def on_retreat(self, interaction) -> None:
        if self.options.path_home or not self.options.carry:
            await self.answer(interaction, self.act("retreat"))
            return
        carried = {key: count for key, count in dict(self.held.counts).items() if count}
        await self.held_answer(interaction, self.act("retreat", carried=carried))


class TargetView(BattleView):
    """A force's target, which rolls its dice in the same click (TNP 6.7,
    decision 8): which force, where more than one may roll, then at
    what -- each target with its dice, what a die must show and why."""

    def build(self) -> None:
        forces = self.options.forces
        chosen = next((one for one in forces if one.force == self.held.force), forces[0] if forces else None)
        if len(forces) > 1:
            self.menu("target:force", "Force to roll", [
                discord.SelectOption(
                    label=_label(self.force_words(one.force)), value=one.force,
                    default=chosen is not None and one.force == chosen.force,
                )
                for one in forces
            ], self.on_force, row=0)
        if chosen is not None:
            self.menu("target:target", f"Target for {self.force_words(chosen.force)} -- rolls at once", [
                discord.SelectOption(
                    label=_label(self.words(target_text(self.battle, option))),
                    description=_label(target_reason(option)),
                    value=f"{chosen.force}|{option.target}",
                )
                for option in chosen.targets
            ], self.on_target, row=1)

    async def on_force(self, interaction, values) -> None:
        await self.redraw(interaction, replace(self.held, force=values[0], notice=None))

    async def on_target(self, interaction, values) -> None:
        force, target = _split(values[0])
        await self.answer(interaction, self.act(force=force, target=target))


class RepairView(BattleView):
    """Workers beside a hit Mechanical force, each ignoring one hit
    (TNP 6.8)."""

    def build(self) -> None:
        for row, worker in enumerate(self.options.workers[:4]):
            key = worker.force
            self.menu(f"repair:{worker.force}", f"Workers from {self.force_words(worker.force)}",
                      _counts(worker.available, self.held.count(key), key), self.counter(key), row=row)
        self.button("repair:go", "Repair", discord.ButtonStyle.success, self.on_repair)
        self.button("repair:no", "Don't repair", discord.ButtonStyle.secondary, self.on_decline)

    async def on_repair(self, interaction) -> None:
        workers = {key: count for key, count in dict(self.held.counts).items() if count}
        await self.held_answer(interaction, self.act("repair", workers=workers))

    async def on_decline(self, interaction) -> None:
        await self.answer(interaction, self.act("decline"))


class SplashView(BattleView):
    """Splash: an infantry unit from a force beside the one hit (TNP 6.8)."""

    def build(self) -> None:
        self.menu("splash:force", "Force to splash", [
            discord.SelectOption(label=_label(self.force_words(one)), value=one)
            for one in self.options.forces
        ], self.on_splash, row=0)
        self.button("splash:no", "Don't splash", discord.ButtonStyle.secondary, self.on_decline)

    async def on_splash(self, interaction, values) -> None:
        await self.answer(interaction, self.act("splash", force=values[0]))

    async def on_decline(self, interaction) -> None:
        await self.answer(interaction, self.act("decline"))


class DestroyView(BattleView):
    """What a base card's two hits destroy (TNP 6.9)."""

    def build(self) -> None:
        self.menu("destroy:thing", "What is destroyed", [
            discord.SelectOption(label=_label(self.words(tokens.thing(thing))), value=thing)
            for thing in self.options.things
        ], self.on_destroy, row=0)

    async def on_destroy(self, interaction, values) -> None:
        await self.answer(interaction, self.act(thing=values[0]))


class RerollView(BattleView):
    """Ammo Depos (TNP 8.4): how many of a roll's missed dice to roll
    again, or keep the roll."""

    def build(self) -> None:
        options = self.options
        self.menu("reroll:count", f"Roll again (up to {options.most} of {options.missed} missed)", [
            discord.SelectOption(label=f"Roll {count} again", value=str(count))
            for count in range(1, options.most + 1)
        ], self.on_reroll, row=0)
        self.button("reroll:keep", "Keep the roll", discord.ButtonStyle.secondary, self.on_keep)

    async def on_reroll(self, interaction, values) -> None:
        await self.answer(interaction, self.act("reroll", count=int(values[0])))

    async def on_keep(self, interaction) -> None:
        await self.answer(interaction, self.act("decline"))


class TacticalCommandView(BattleView):
    """
    Tactical Command (TNP 6.3) on the battle message: the cards are
    secret until both seats have chosen, so each is chosen on its seat's
    own panel -- **My tactic card** opens it, privately, for whichever
    seat the clicker holds that is still choosing.
    """

    def build(self) -> None:
        self.button("tactic:open", "My tactic card", discord.ButtonStyle.primary, self.on_open)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await SafeView.interaction_check(self, interaction):
            return False
        game = self.game()
        if game is None or not self.cog.tactic_seats(game, interaction.user.id):
            await send_ephemeral(interaction, "Only a seat still choosing a tactic card may open this.")
            return False
        return True

    async def on_open(self, interaction) -> None:
        game = self.game()
        await self.cog.send_panels(interaction, game, self.cog.tactic_seats(game, interaction.user.id))


#: Each battle prompt kind to its view.
BATTLE_VIEWS = {
    PromptKind.CHOOSE_ROLE: RoleView,
    PromptKind.EMERGENCY_DEFENSE: EmergencyView,
    PromptKind.REPOSITION_FLANKERS: RepositionView,
    PromptKind.PLACE_FORCE: PlaceView,
    PromptKind.DECLARE_RETREAT: RetreatView,
    PromptKind.CHOOSE_TARGET: TargetView,
    PromptKind.REPAIR: RepairView,
    PromptKind.SPLASH: SplashView,
    PromptKind.DESTROY: DestroyView,
    PromptKind.REROLL: RerollView,
    PromptKind.TACTIC: TacticalCommandView,
}


def battle_view(cog, game_id: str, prompt: Optional[PendingPrompt], battle,
                held: BattleHeld = BattleHeld(), restored: bool = False) -> Optional[BattleView]:
    """**The one place a battle prompt kind becomes a view**: `None` where
    the battle asks nothing now."""
    if prompt is None or prompt.kind not in BATTLE_VIEWS or battle is None:
        return None
    return BATTLE_VIEWS[prompt.kind](cog, game_id, prompt, battle, held, restored)


__all__ = [
    "BATTLE_VIEWS", "BattleHeld", "BattleView", "DestroyView", "EmergencyView", "PlaceView",
    "RepairView", "RepositionView", "RerollView", "RetreatView", "RoleView", "SplashView",
    "TacticalCommandView", "TargetView",
    "battle_view",
]

"""
`TurnPanelView`, the active player's control panel (docs/codex-bot.md,
decision 4; docs/design/codex.md, "The panel"): **one ephemeral message
edited in place by its own interactions**, the cards in the hand
pictured above it, the main phase's actions under it. The view for
`MAIN_ACTION` and `CHOOSE_DEFENDER`, for the three choices an attack
asks inside itself -- obliterate's tie, sparkshot's neighbour and
overpower's excess -- and for the questions an effect asks as it
resolves: a target (`TARGET`), Appel Stomp's place (`APPEL_STOMP_TOP`)
and the upkeep's order (`UPKEEP_ORDER`), each a menu of what the prompt
offers.

Every control is built from the prompt's options and nothing else --
`MainActionOptions` for the actions, `DefenderOptions` for the defender
-- and every click answers through `SafeView.apply`, so the driver
refuses whatever the options did not offer. Two modes are the view's
own and change nothing: **Hire worker** opens a menu of the hand's
cards to hire with, **Undo** the undos `history.undo_targets` says are
open (`GameService.undo_targets`).

`UndoConfirmView` is the one public prompt of a turn besides the turn
message: the opponent's agreement to an undo to the previous turn,
which unwinds their turn as well (decision 11).
"""

from __future__ import annotations

import discord

from codex import effects, history
from codex.engine import TECH_BUILDINGS, building_name
from codex.formatting import ref_label
from codex.prompts import Action, PromptKind
from cogs.codex_helpers import card_name
from cogs.codex_views.base import SafeView, send_ephemeral

#: How long a panel answers clicks: a turn, generously. An expired panel
#: is reopened from **My hand**, which makes a fresh one.
PANEL_TIMEOUT = 3600

#: A Discord select holds at most this many options.
SELECT_LIMIT = 25

NOT_YOUR_PANEL = "This panel is the active player's: only they can act from it."


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."


def building_label(building: str) -> str:
    """A building in a menu: "Tech II", or the add-on's own name."""
    if building in TECH_BUILDINGS:
        return building_name(building)
    return card_name(building)


def hand_numbers(options) -> dict[str, int]:
    """Each slug's number in the panel's picture -- its first place in
    the hand, counted from 1, as `render_hand` numbers it."""
    numbers: dict[str, int] = {}
    for index, row in enumerate(options.hand, start=1):
        numbers.setdefault(row.slug, index)
    return numbers


class PanelView(SafeView):
    """What the panel's views share: the prompt they were built from,
    the seat it asks, and the one gate -- that seat's player alone."""

    def __init__(self, cog, game_id: str, prompt, match) -> None:
        super().__init__(timeout=PANEL_TIMEOUT)
        self.cog = cog
        self.game_id = game_id
        self.prompt = prompt
        self.seat = prompt.asked_player
        self.match = match

    def label(self, ref: str, seat: int | None = None) -> str:
        return ref_label(self.cog.engine, self.match, self.seat if seat is None else seat, ref)

    async def mine(self, interaction: discord.Interaction):
        """`(game, match)` for a click by this panel's player, or
        `(None, None)` -- told why -- for anybody else's."""
        game, match = await self.require_match(interaction)
        if game is None:
            return None, None
        # `seats_of`, so the one person holding both seats of a test game
        # acts from either side's panel.
        if self.seat not in game.seats_of(interaction.user.id):
            await send_ephemeral(interaction, NOT_YOUR_PANEL)
            return None, None
        return game, match

    async def act(self, interaction: discord.Interaction, action: Action) -> None:
        """Answer through the service; the panel edited in place with
        what is asked next; then the turn message, through the gate."""
        game, match = await self.mine(interaction)
        if game is None:
            return
        before = (match.turn, match.phase)
        result = await self.apply(interaction, game, action)
        if result is None:
            return
        await self.cog.answer_panel(interaction, game, self.seat, result, action.kind)
        await self.cog.present(game, result, before)

    async def show(self, interaction: discord.Interaction, view: discord.ui.View,
                   content: str | None = None) -> None:
        """Change the panel's mode in place: the click's own response."""
        if content is None:
            await interaction.response.edit_message(view=view)
        else:
            await interaction.response.edit_message(content=content, view=view)


class TurnPanelView(PanelView):
    """
    The main phase, from `MainActionOptions`: a row of buttons -- **Hire
    worker**, **Summon hero** or **Level up**, **Undo**, **End main
    phase** -- and the menus **Play a card** (the playable cards by their
    number in the picture), **Build**, **Attack with**, and the levels
    to buy. A control the engine says no to is disabled with its reason
    as its label. For `CHOOSE_DEFENDER`, the legal defenders, each with
    why it is legal, and **Cancel**.
    """

    def __init__(self, cog, game_id: str, prompt, match, mode: str = "actions",
                 undo_targets: dict | None = None) -> None:
        super().__init__(cog, game_id, prompt, match)
        self.mode = mode
        options = prompt.options
        if prompt.kind is PromptKind.CHOOSE_DEFENDER:
            self.build_defenders(options)
        elif prompt.kind is PromptKind.OBLITERATE_CHOICE:
            self.build_obliterate(options)
        elif prompt.kind is PromptKind.SPARKSHOT_TARGET:
            self.build_sparkshot(options)
        elif prompt.kind is PromptKind.OVERPOWER_TARGET:
            self.build_overpower(options)
        elif prompt.kind is PromptKind.TARGET:
            self.build_target(options)
        elif prompt.kind is PromptKind.APPEL_STOMP_TOP:
            self.build_appel(options)
        elif prompt.kind is PromptKind.UPKEEP_ORDER:
            self.build_upkeep(options)
        elif mode == "hire":
            self.build_hire(options)
        elif mode == "detect":
            self.build_detect(options)
        elif mode == "undo":
            self.build_undo(undo_targets or {})
        else:
            self.build_actions(options)

    # -- The actions -------------------------------------------------------

    def build_actions(self, options) -> None:
        hire = options.hire
        self.button(
            "Hire worker" if hire.allowed else _cut(f"Hire: {hire.why_not}", 80),
            discord.ButtonStyle.primary, self.open_hire, row=0, disabled=not hire.allowed,
        )
        hero = options.hero
        name = card_name(hero.slug)
        levels = hero.action == "level" and not hero.why_not and hero.max_levels
        if hero.action == "summon":
            self.button(
                _cut(f"Summon {name} ({hero.cost} gold)" if not hero.why_not
                     else f"Summon: {hero.why_not}", 80),
                discord.ButtonStyle.primary, self.summon, row=0, disabled=bool(hero.why_not),
            )
        elif not levels:
            why = hero.why_not or "nothing to do"
            self.button(_cut(f"{name}: {why}", 80), discord.ButtonStyle.secondary,
                        None, row=0, disabled=True)
        # The hero's levels and the abilities share the last row: a
        # message has five, and the other four are taken.
        choices = []
        if levels:
            choices += [
                discord.SelectOption(
                    label=f"Level up {name} {count} ({count * hero.cost} gold)",
                    value=f"level:{count}",
                )
                for count in range(1, hero.max_levels + 1)
            ]
        choices += [
            discord.SelectOption(label=_cut(self.ability_label(ability), 100),
                                 value=f"ability:{ability.effect}:{ability.source}")
            for ability in options.abilities if ability.allowed
        ]
        if choices:
            usable = any(choice.value.startswith("ability:") for choice in choices)
            placeholder = (
                "Level up or use an ability..." if levels and usable
                else "Use an ability..." if usable else f"Level up {name}..."
            )
            select = discord.ui.Select(placeholder=placeholder, row=4,
                                       options=choices[:SELECT_LIMIT])
            select.callback = self.level
            self.level_select = select
            self.add_item(select)
        self.button("Undo...", discord.ButtonStyle.secondary, self.open_undo, row=0)
        self.button("End main phase", discord.ButtonStyle.danger, self.end_main, row=0)
        detect = options.detect
        if detect.tower:
            # Only a player with a finished tower is offered its
            # detection at all; the engine says whether it may be used.
            self.button(
                "Detect..." if detect.allowed else _cut(f"Detect: {detect.why_not}", 80),
                discord.ButtonStyle.secondary, self.open_detect, row=0,
                disabled=not detect.allowed,
            )

        numbers = hand_numbers(options)
        playable = [row for row in options.playable if row.allowed][:SELECT_LIMIT]
        self.menu(
            "Play a card...", "No card in your hand can be played now", 1,
            [
                discord.SelectOption(
                    label=_cut(f"{numbers.get(row.slug, '?')}. {card_name(row.slug)} "
                               f"-- {row.cost} gold", 100),
                    value=row.slug,
                )
                for row in playable
            ],
            self.play,
        )
        buildable = [row for row in options.buildings if row.allowed]
        self.menu(
            "Build...", "Nothing can be built now", 2,
            [
                discord.SelectOption(
                    label=_cut(f"{building_label(row.building)} -- {row.cost} gold", 100),
                    value=row.building,
                )
                for row in buildable
            ],
            self.build,
        )
        self.menu(
            "Attack with...", "Nothing of yours can attack now", 3,
            [
                discord.SelectOption(label=_cut(self.label(ref), 100), value=ref)
                for ref in options.attackers[:SELECT_LIMIT]
            ],
            self.attack,
        )

    def button(self, label: str, style, callback, *, row: int, disabled: bool = False) -> None:
        button = discord.ui.Button(label=label, style=style, row=row, disabled=disabled)
        if callback is not None:
            button.callback = callback
        self.add_item(button)

    def menu(self, placeholder: str, empty: str, row: int, options: list, callback) -> None:
        """A select, or -- where it would offer nothing -- a disabled one
        saying why, so the panel keeps its shape."""
        if not options:
            select = discord.ui.Select(
                placeholder=empty, row=row, disabled=True,
                options=[discord.SelectOption(label=empty[:100], value="none")],
            )
        else:
            select = discord.ui.Select(placeholder=placeholder, row=row, options=options)
            select.callback = self._select(callback, select)
        self.add_item(select)

    def _select(self, callback, select):
        async def run(interaction: discord.Interaction) -> None:
            await callback(interaction, select.values[0])
        return run

    async def summon(self, interaction: discord.Interaction) -> None:
        await self.act(interaction, Action(PromptKind.MAIN_ACTION, "summon"))

    def ability_label(self, ability) -> str:
        """An ability in the menu: what offers it and what it does, in the
        card's own words (`codex.effects.EFFECTS`)."""
        if ability.effect == "stop_the_music":
            return f"Sacrifice {card_name(effects.HARMONY)}: stop the music"
        says = effects.EFFECTS[ability.effect].parts[0].says
        return f"{self.label(ability.source)}: exhaust to {says}"

    async def level(self, interaction: discord.Interaction) -> None:
        """The last row's menu: a number of levels, or an ability."""
        kind, _, rest = self.level_select.values[0].partition(":")
        if kind == "ability":
            effect, _, source = rest.partition(":")
            await self.act(interaction, Action(
                PromptKind.MAIN_ACTION, "ability", {"ability": effect, "source": source},
            ))
            return
        await self.act(interaction, Action(PromptKind.MAIN_ACTION, "level", {"levels": int(rest)}))

    async def play(self, interaction: discord.Interaction, slug: str) -> None:
        await self.act(interaction, Action(PromptKind.MAIN_ACTION, "play", {"slug": slug}))

    async def build(self, interaction: discord.Interaction, building: str) -> None:
        await self.act(interaction, Action(PromptKind.MAIN_ACTION, "build", {"building": building}))

    async def attack(self, interaction: discord.Interaction, ref: str) -> None:
        await self.act(interaction, Action(PromptKind.MAIN_ACTION, "attack", {"attacker": ref}))

    async def end_main(self, interaction: discord.Interaction) -> None:
        await self.act(interaction, Action(PromptKind.MAIN_ACTION, "end_main"))

    # -- Hiring: which card goes -------------------------------------------

    async def open_hire(self, interaction: discord.Interaction) -> None:
        game, _ = await self.mine(interaction)
        if game is None:
            return
        await self.show(interaction, TurnPanelView(
            self.cog, self.game_id, self.prompt, self.match, mode="hire",
        ))

    def build_hire(self, options) -> None:
        """The hand, card by card by its number in the picture: the one
        hired with is trashed unseen (UMR p. 6)."""
        seen = []
        choices = []
        for index, row in enumerate(options.hand, start=1):
            if row.slug in seen:
                continue
            seen.append(row.slug)
            choices.append(discord.SelectOption(
                label=_cut(f"{index}. {card_name(row.slug)}", 100), value=row.slug,
            ))
        self.menu(
            f"Hire a worker for {options.hire.cost} gold: which card goes?",
            "There is no card in hand to hire with", 0, choices[:SELECT_LIMIT], self.hire,
        )
        self.button("Back", discord.ButtonStyle.secondary, self.back, row=1)

    async def hire(self, interaction: discord.Interaction, slug: str) -> None:
        await self.act(interaction, Action(PromptKind.MAIN_ACTION, "hire", {"slug": slug}))

    # -- The tower's detection ---------------------------------------------

    async def open_detect(self, interaction: discord.Interaction) -> None:
        game, _ = await self.mine(interaction)
        if game is None:
            return
        await self.show(interaction, TurnPanelView(
            self.cog, self.game_id, self.prompt, self.match, mode="detect",
        ))

    def build_detect(self, options) -> None:
        """What the tower may detect, as the engine offers it (UMR p. 9)."""
        other = 2 if self.seat == 1 else 1
        self.menu(
            "Detect with your tower...", "Nothing of theirs is hidden", 0,
            [
                discord.SelectOption(label=_cut(self.label(ref, other), 100), value=ref)
                for ref in options.detect.candidates[:SELECT_LIMIT]
            ],
            self.detect,
        )
        self.button("Back", discord.ButtonStyle.secondary, self.back, row=1)

    async def detect(self, interaction: discord.Interaction, ref: str) -> None:
        await self.act(interaction, Action(PromptKind.MAIN_ACTION, "detect", {"card": ref}))

    async def back(self, interaction: discord.Interaction) -> None:
        game, match = await self.mine(interaction)
        if game is None:
            return
        await self.cog.show_panel(interaction, game, match, self.seat, edit=True)

    # -- The defender ------------------------------------------------------

    def build_defenders(self, options) -> None:
        other = 2 if self.seat == 1 else 1
        self.menu(
            f"{self.label(options.attacker)} attacks...", "Nothing can be attacked", 0,
            [
                discord.SelectOption(
                    label=_cut(f"{self.label(ref, other)} -- {why}", 100), value=ref,
                )
                for ref, why in zip(options.defenders, options.why or ("",) * len(options.defenders))
            ][:SELECT_LIMIT],
            self.defend,
        )
        self.button("Cancel the attack", discord.ButtonStyle.secondary, self.cancel_attack, row=1)

    async def defend(self, interaction: discord.Interaction, ref: str) -> None:
        await self.act(interaction, Action(PromptKind.CHOOSE_DEFENDER, "", {"defender": ref}))

    async def cancel_attack(self, interaction: discord.Interaction) -> None:
        await self.act(interaction, Action(PromptKind.CHOOSE_DEFENDER, "cancel"))

    # -- The choices inside an attack ----------------------------------------

    def build_obliterate(self, options) -> None:
        """Which of the equally low-tech units obliterate takes."""
        other = 2 if self.seat == 1 else 1
        self.menu(
            f"Obliterate {options.left}: which unit goes?", "Nothing to obliterate", 0,
            [
                discord.SelectOption(label=_cut(self.label(ref, other), 100), value=ref)
                for ref in options.units[:SELECT_LIMIT]
            ],
            self.obliterate,
        )

    async def obliterate(self, interaction: discord.Interaction, ref: str) -> None:
        await self.act(interaction, Action(PromptKind.OBLITERATE_CHOICE, "", {"unit": ref}))

    def build_sparkshot(self, options) -> None:
        """Which patroller beside the one attacked takes sparkshot's 1."""
        other = 2 if self.seat == 1 else 1
        placeholder = "Sparkshot hits..."
        if options.left > 1 or options.placed:
            placeholder = f"Sparkshot hits... ({options.left} of its damage left to place)"
        self.menu(
            placeholder, "No patroller is beside it", 0,
            [
                discord.SelectOption(label=_cut(self.label(ref, other), 100), value=ref)
                for ref in options.patrollers[:SELECT_LIMIT]
            ],
            self.sparkshot,
        )

    async def sparkshot(self, interaction: discord.Interaction, ref: str) -> None:
        await self.act(interaction, Action(PromptKind.SPARKSHOT_TARGET, "", {"patroller": ref}))

    def build_overpower(self, options) -> None:
        """Where overpower's excess goes."""
        other = 2 if self.seat == 1 else 1
        self.menu(
            f"Overpower carries {options.excess} over to...", "Nothing can take it", 0,
            [
                discord.SelectOption(label=_cut(self.label(ref, other), 100), value=ref)
                for ref in options.targets[:SELECT_LIMIT]
            ],
            self.overpower,
        )

    async def overpower(self, interaction: discord.Interaction, ref: str) -> None:
        await self.act(interaction, Action(PromptKind.OVERPOWER_TARGET, "", {"target": ref}))

    # -- The questions an effect asks -----------------------------------------

    def target_label(self, row) -> str:
        """A target in the menu: whose, what, and what it costs -- its
        resist -- or why it is forced (the flagbearer)."""
        whose = "Your" if row.seat == self.seat else "Their"
        label = f"{whose} {self.label(row.ref, row.seat)}"
        if row.resist:
            label += f" -- resist: pay {row.resist} gold"
        if row.flagbearer:
            label += " -- flagbearer"
        return label

    def build_target(self, options) -> None:
        """What the part being resolved may choose, as the engine offers
        it: the flagbearers alone where the rule forces one."""
        self.menu(
            _cut(f"{options.says[:1].upper()}{options.says[1:]}...", 150),
            "Nothing can be chosen", 0,
            [
                discord.SelectOption(label=_cut(self.target_label(row), 100), value=row.key)
                for row in options.targets[:SELECT_LIMIT]
            ],
            self.target,
        )
        if options.cancellable:
            self.button("Cancel", discord.ButtonStyle.secondary, self.cancel_cast, row=1)

    async def target(self, interaction: discord.Interaction, key: str) -> None:
        await self.act(interaction, Action(PromptKind.TARGET, "", {"target": key}))

    async def cancel_cast(self, interaction: discord.Interaction) -> None:
        """Take the spell or ability back, as the model offers it: its
        gold, its card, its exhaust, and anything it already did."""
        await self.act(interaction, Action(PromptKind.TARGET, "cancel"))

    def build_appel(self, options) -> None:
        self.button("On top of my draw pile", discord.ButtonStyle.primary, self.appel_top, row=0)
        self.button("Into my discard pile", discord.ButtonStyle.secondary, self.appel_discard, row=0)

    async def appel_top(self, interaction: discord.Interaction) -> None:
        await self.act(interaction, Action(PromptKind.APPEL_STOMP_TOP, "top"))

    async def appel_discard(self, interaction: discord.Interaction) -> None:
        await self.act(interaction, Action(PromptKind.APPEL_STOMP_TOP, "discard"))

    UPKEEP_LABELS = {
        "healing": "Heal first",
        "starlet": "Star-Crossed Starlet takes her damage first",
    }

    def build_upkeep(self, options) -> None:
        for effect in options.effects:
            self.button(
                self.UPKEEP_LABELS.get(effect, effect), discord.ButtonStyle.primary,
                self._upkeep(effect), row=0,
            )

    def _upkeep(self, effect: str):
        async def run(interaction: discord.Interaction) -> None:
            await self.act(interaction, Action(PromptKind.UPKEEP_ORDER, "", {"first": effect}))
        return run

    # -- Undo ----------------------------------------------------------------

    async def open_undo(self, interaction: discord.Interaction) -> None:
        game, _ = await self.mine(interaction)
        if game is None:
            return
        targets = self.cog.service.undo_targets(game.game_id)
        await self.show(interaction, TurnPanelView(
            self.cog, self.game_id, self.prompt, self.match, mode="undo", undo_targets=targets,
        ))

    def build_undo(self, targets: dict) -> None:
        """The undos open on this position, as `history.undo_targets`
        names them, and **Back**."""
        if history.TURN_START in targets:
            self.button("To the start of my turn", discord.ButtonStyle.danger,
                        self.undo_turn_start, row=0)
        if history.PREVIOUS_TURN in targets:
            self.button("To the start of the previous turn (asks your opponent)",
                        discord.ButtonStyle.danger, self.undo_previous_turn, row=0)
        if not targets:
            self.button("Nothing to undo", discord.ButtonStyle.secondary, None, row=0, disabled=True)
        self.button("Back", discord.ButtonStyle.secondary, self.back, row=1)

    async def undo_turn_start(self, interaction: discord.Interaction) -> None:
        game, _ = await self.mine(interaction)
        if game is None:
            return
        await self.cog.undo_to_turn_start(interaction, game, self.seat)

    async def undo_previous_turn(self, interaction: discord.Interaction) -> None:
        game, match = await self.mine(interaction)
        if game is None:
            return
        await self.cog.ask_undo_to_previous_turn(interaction, game, self.seat, match.turn)


class UndoConfirmView(SafeView):
    """
    The opponent's agreement to an undo to the previous turn, posted
    publicly: **Agree** is the opponent's -- or a game helper's, behind
    the helper's confirmation -- and never the asker's; **Refuse** is
    either player's. It holds the turn it was asked on, so a game that
    has moved on since refuses it. Not persistent: after a restart the
    asker asks again.
    """

    def __init__(self, cog, game_id: str, asker: int, turn: int) -> None:
        super().__init__(timeout=PANEL_TIMEOUT)
        self.cog = cog
        self.game_id = game_id
        self.asker = asker
        self.turn = turn
        agree = discord.ui.Button(label="Agree: undo my turn too", style=discord.ButtonStyle.danger)
        agree.callback = self.agree
        refuse = discord.ui.Button(label="Refuse", style=discord.ButtonStyle.secondary)
        refuse.callback = self.refuse_undo
        self.add_item(agree)
        self.add_item(refuse)

    @property
    def opponent(self) -> int:
        return 2 if self.asker == 1 else 1

    async def agree(self, interaction: discord.Interaction) -> None:
        game, match = await self.require_match(interaction)
        if game is None:
            return
        seats = game.seats_of(interaction.user.id)
        # The opponent's seat first: in a test game one person holds both,
        # and agrees with themselves.
        seat = self.opponent if self.opponent in seats else (seats[0] if seats else None)
        if seat == self.asker:
            await send_ephemeral(interaction, "Your opponent has to agree to this: it undoes their turn too.")
            return
        if not self.may_act_for(interaction, game, self.opponent):
            await send_ephemeral(interaction, "Only the opponent, or a helper with Manage Channels, can agree to this.")
            return
        if match.turn != self.turn or match.active != self.asker:
            await interaction.response.edit_message(
                content="That undo was asked on a turn the game has moved on from.", view=None,
            )
            return
        await self.cog.undo_to_previous_turn(interaction, game, seat)

    async def refuse_undo(self, interaction: discord.Interaction) -> None:
        game, _ = await self.require_match(interaction)
        if game is None:
            return
        seats = game.seats_of(interaction.user.id)
        if not seats:
            await send_ephemeral(interaction, "Only the players can refuse this.")
            return
        self.stop()
        name = game.seat_name(seats[0]) or "A player"
        await interaction.response.edit_message(
            content=f"The undo to the start of the previous turn was refused by {name}.", view=None,
        )


__all__ = [
    "NOT_YOUR_PANEL", "PANEL_TIMEOUT", "PanelView", "TurnPanelView",
    "UndoConfirmView", "building_label", "hand_numbers",
]

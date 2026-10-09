"""
`TurnPanelView`, the active player's control panel (docs/codex-bot.md,
decision 4; docs/design/codex.md, "The panel"): **one ephemeral message
edited in place by its own interactions**, the cards in the hand
pictured above it, the main phase's actions under it. The view for
`MAIN_ACTION` and `CHOOSE_DEFENDER`, for the three choices an attack
asks inside itself -- obliterate's tie, sparkshot's neighbour and
overpower's excess -- and for the questions an effect asks as it
resolves: a target (`TARGET`), Appel Stomp's place (`APPEL_STOMP_TOP`),
the upkeep's order (`UPKEEP_ORDER`) and which hero gains a kill's levels
(`LEVEL_GAIN`), each buttons for what the prompt offers.

Every control is built from the prompt's options and nothing else --
`MainActionOptions` for the actions, `DefenderOptions` for the defender
-- and every click answers through `SafeView.apply`, so the driver
refuses whatever the options did not offer. **The main phase is rows
of buttons, not menus** (the author, 2026-10-09): a card in the hand
is a button, a building is a button, each hero is one button on a row of
their own that summons it or buys one level, and **Attack...** opens the
attackers as buttons.
Three modes are the view's own and change nothing: **Attack...** opens
what may attack, **Hire worker** the hand's cards to hire with, **Undo**
the undos `history.undo_targets` says are open
(`GameService.undo_targets`); a mode's question, and the attacker over
the defender's buttons, go under the prompt's ask (`caption`), where the
menus' placeholders used to carry them.

`UndoConfirmView` is the one public prompt of a turn besides the turn
message: the opponent's agreement to an undo to the previous turn,
which unwinds their turn as well (decision 11).
"""

from __future__ import annotations

import asyncio

import discord

from codex import effects, history
from codex.engine import TECH_BUILDINGS, building_name
from codex.formatting import deck_name, ref_label
from codex.prompts import Action, PromptKind
from cogs.codex_helpers import card_name
from cogs.codex_views.base import SafeView, send_ephemeral

#: How long a panel answers clicks: a turn, generously. An expired panel
#: is reopened from **My hand**, which makes a fresh one.
PANEL_TIMEOUT = 3600

#: A Discord select holds at most this many options.
SELECT_LIMIT = 25

#: A message carries five rows of components, five buttons a row.
ROWS = 5
BUTTONS_PER_ROW = 5

#: The hand's buttons take at most this many rows, so the board's row
#: -- what may be built, the tower, the abilities -- always has two
#: left after the actions row and the hand.
HAND_ROWS = 2

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


class PanelButton(discord.ui.Button):
    """A button on the panel, carrying `choice` -- what it answers with
    off the prompt's options: `("play", slug)`, `("build", building)`,
    `("attack", ref)`, `("ability", effect, source)`, `("summon", hero)`,
    `("level", hero)`, `("level_gain", ref)`, `("hire", slug)`, `("defend", ref)`, `("target", key)`,
    `("detect", ref)`, `("obliterate", ref)`, `("sparkshot", ref)`,
    `("overpower", ref)`, or `None` for a button that is not one choice
    among several -- so a test finds it by what it chooses rather than
    by its label."""

    def __init__(self, choice: tuple | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.choice = choice


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
        """
        Answer through the service. Where the answer puts something in
        public, the click is deferred, the turn message posted again at
        the foot of the channel, and the panel sent afresh under it, the
        one clicked deleted; where it puts nothing in public, the panel
        is edited in place and the channel is left alone
        (docs/design/codex.md, "The turn message, posted again").
        """
        game, match = await self.mine(interaction)
        if game is None:
            return
        before = (match.turn, match.phase)
        result = await self.apply(interaction, game, action)
        if result is None:
            return
        if not self.cog.goes_public(result):
            await self.cog.answer_panel(interaction, game, self.seat, result, action.kind)
            await self.cog.present(game, result, before)
            return
        # The acknowledgement and the board go out together: the defer
        # is a round trip of its own that neither the board's render nor
        # its post waits on, and the panel is sent after both.
        await asyncio.gather(interaction.response.defer(), self.cog.present(game, result, before))
        await self.cog.answer_panel(interaction, game, self.seat, result, action.kind, replace=True)

    async def open_deck(self, interaction: discord.Interaction) -> None:
        """**My deck**: every card this panel's player owns, in an
        ephemeral message of its own; the panel stays as it is."""
        game, match = await self.mine(interaction)
        if game is None:
            return
        await self.cog.send_deck(interaction, game, match, self.seat)

    async def show(self, interaction: discord.Interaction, view: discord.ui.View,
                   content: str | None = None) -> None:
        """Change the panel's mode in place: the click's own response."""
        if content is None:
            await interaction.response.edit_message(view=view)
        else:
            await interaction.response.edit_message(content=content, view=view)


class TurnPanelView(PanelView):
    """
    The main phase, from `MainActionOptions`, as rows of buttons (the
    author, 2026-10-09): the actions row -- **Hire worker**,
    **Attack...**, then a button per hero that summons it or levels it
    up by one level a click -- then the hand, a button per card numbered
    as the picture numbers it and disabled where it may not be played,
    then the board's row -- **Build** per building that may be built,
    **Detect...** where there is a tower, and each ability that may be
    used -- and always last, in this order, **My deck**, **Undo...** and
    **End main phase** (the author, 2026-10-09). A control the engine says no to is disabled with its
    reason as its label. **Attack...** turns the panel into what may
    attack, one button each, and **Back**; **Hire worker** into the
    hand, a button per card. For `CHOOSE_DEFENDER`, a button per legal
    defender, each with why it is legal, and **Cancel**.
    """

    def __init__(self, cog, game_id: str, prompt, match, mode: str = "actions",
                 undo_targets: dict | None = None, building: str | None = None,
                 spec: str | None = None, slug: str | None = None) -> None:
        super().__init__(cog, game_id, prompt, match)
        self.mode = mode
        #: The spec choice's building, and the Tech II spec chosen so far
        #: where a tech lab waits on its own (`build_spec`).
        self.building = building
        self.spec = spec
        #: The card the boost choice is about (`build_boost`).
        self.slug = slug
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
        elif prompt.kind is PromptKind.LEVEL_GAIN:
            self.build_level_gain(options)
        elif prompt.kind is PromptKind.DIVIDE_DAMAGE:
            self.build_divide(options)
        elif prompt.kind is PromptKind.MODE_CHOICE:
            self.build_mode(options)
        elif mode == "attack":
            self.build_attack(options)
        elif mode == "hire":
            self.build_hire(options)
        elif mode == "detect":
            self.build_detect(options)
        elif mode == "undo":
            self.build_undo(undo_targets or {})
        elif mode == "spec":
            self.build_spec(options)
        elif mode == "boost":
            self.build_boost(options)
        else:
            self.build_actions(options)

    # -- The actions -------------------------------------------------------

    def build_actions(self, options) -> None:
        """The actions row with the heroes on it, the hand's rows, then
        the board's row and the three that always end the panel -- each
        group starting a row of its own, five buttons a row. **Hire
        worker** and every **Build** are green, **Attack...** red (the
        author, 2026-10-09)."""
        hire = options.hire
        actions = [
            self.make_button(
                "Hire worker" if hire.allowed else f"Hire: {hire.why_not}",
                discord.ButtonStyle.success, self.open_hire, disabled=not hire.allowed,
            ),
            self.make_button(
                "Attack..." if options.attackers else "Attack: nothing of yours can attack now",
                discord.ButtonStyle.danger, self.open_attack, disabled=not options.attackers,
            ),
        ] + [self.hero_button(hero) for hero in options.heroes]
        # The hand, every card once in the hand's order (`playable`), by
        # its number in the picture: a card that may not be played now
        # is there and disabled, as the picture greys it.
        numbers = hand_numbers(options)
        hand = [
            self.make_button(
                f"{numbers.get(row.slug, '?')}. {card_name(row.slug)} ({row.cost} gold)",
                discord.ButtonStyle.primary if row.allowed else discord.ButtonStyle.secondary,
                self._answer(self.open_boost, row.slug) if row.boostable
                else self._answer(self.play, row.slug),
                disabled=not row.allowed, choice=("play", row.slug),
            )
            for row in options.playable
        ] or [self.make_button("Your hand is empty", discord.ButtonStyle.secondary, None,
                               disabled=True)]
        board = [
            self.make_button(
                f"Build {building_label(row.building)} ({row.cost} gold)"
                + ("..." if row.specs else ""),
                discord.ButtonStyle.success,
                self._answer(self.open_spec, row.building) if row.specs
                else self._answer(self.build, row.building),
                choice=("build", row.building),
            )
            for row in options.buildings if row.allowed
        ] or [self.make_button("Nothing can be built now", discord.ButtonStyle.secondary, None,
                               disabled=True)]
        detect = options.detect
        if detect.tower:
            # Only a player with a finished tower is offered its
            # detection at all; the engine says whether it may be used.
            board.append(self.make_button(
                "Detect..." if detect.allowed else f"Detect: {detect.why_not}",
                discord.ButtonStyle.secondary, self.open_detect, disabled=not detect.allowed,
            ))
        board += [
            self.make_button(
                self.ability_label(ability), discord.ButtonStyle.primary,
                self._answer(self.ability, ability.effect, ability.source),
                choice=("ability", ability.effect, ability.source),
            )
            for ability in options.abilities if ability.allowed
        ]
        # **My deck**, **Undo...** and **End main phase** are always the
        # panel's last three buttons, in that order (the author,
        # 2026-10-09), after the board's row, and always placed.
        last = [
            self.make_button("My deck", discord.ButtonStyle.secondary, self.open_deck),
            self.make_button("Undo...", discord.ButtonStyle.secondary, self.open_undo),
            self.make_button("End main phase", discord.ButtonStyle.danger, self.end_main),
        ]
        row = self.place(actions, 0)
        row = self.place(hand, row, until=row + HAND_ROWS)
        self.place(board, row, last=last)

    def hero_button(self, hero) -> PanelButton:
        """**Summon Jaina (2 gold)**, or **Level up Jaina (1 gold)** -- a
        level a click (the author, 2026-10-09) -- disabled with its reason
        where the engine says no: the hero limit, the runes, the gold,
        the maximum."""
        name = card_name(hero.slug)
        if hero.action == "summon":
            return self.make_button(
                f"Summon {name} ({hero.cost} gold)" if not hero.why_not
                else f"Summon {name}: {hero.why_not}",
                discord.ButtonStyle.primary, self._answer(self.summon, hero.slug),
                disabled=bool(hero.why_not), choice=("summon", hero.slug),
            )
        if hero.action == "level" and not hero.why_not and hero.max_levels:
            return self.make_button(
                f"Level up {name} ({hero.cost} gold)", discord.ButtonStyle.primary,
                self._answer(self.level, hero.slug), choice=("level", hero.slug),
            )
        return self.make_button(f"{name}: {hero.why_not or 'nothing to do'}",
                                discord.ButtonStyle.secondary, None, disabled=True)

    def make_button(self, label: str, style, callback, *, disabled: bool = False,
                    choice: tuple | None = None) -> PanelButton:
        """A button not yet placed: `place` gives it its row."""
        button = PanelButton(choice, label=_cut(label, 80), style=style, disabled=disabled)
        if callback is not None:
            button.callback = callback
        return button

    def place(self, buttons: list, row: int, until: int = ROWS, last: list = ()) -> int:
        """
        Add `buttons` five a row from `row`, before row `until`; the next
        free row. What does not fit is left out: a message carries five
        rows, and the groups placed first have the earlier claim. `last`
        goes after them, in its order, and is never left out: buttons of
        `buttons` give up their places to it where they would fill the
        rows.
        """
        until = min(until, ROWS)
        if last:
            room = max(until - row, 0) * BUTTONS_PER_ROW
            buttons = list(buttons)[: max(room - len(last), 0)] + list(last)
        placed = 0
        for button in buttons:
            at = row + placed // BUTTONS_PER_ROW
            if at >= until:
                break
            button.row = at
            self.add_item(button)
            placed += 1
        return row + -(-placed // BUTTONS_PER_ROW)

    def button(self, label: str, style, callback, *, row: int, disabled: bool = False) -> None:
        """A button placed on `row` at once."""
        button = self.make_button(label, style, callback, disabled=disabled)
        button.row = row
        self.add_item(button)

    def choices(self, items, label, callback, kind: str, empty: str) -> list:
        """A button per `ref` in `items`, labelled by `label(ref)`,
        answering `callback(interaction, ref)` and carrying `(kind, ref)`
        -- or, with nothing to offer, one disabled button saying why, so
        the panel keeps its shape."""
        return [
            self.make_button(label(ref), discord.ButtonStyle.primary,
                             self._answer(callback, ref), choice=(kind, ref))
            for ref in items
        ] or [self.make_button(empty, discord.ButtonStyle.secondary, None, disabled=True)]

    def _answer(self, callback, *args):
        async def run(interaction: discord.Interaction) -> None:
            await callback(interaction, *args)
        return run

    def caption(self) -> str:
        """What the panel says under the prompt's ask (`panel_caption`
        reads it): the attacker, for the defender's question, and what a
        mode of the view's own asks -- the menus' placeholders used to
        carry both. Empty where the ask says it all."""
        options = self.prompt.options
        if self.prompt.kind is PromptKind.CHOOSE_DEFENDER:
            return f"**{self.label(options.attacker)} attacks.**"
        if self.prompt.kind is PromptKind.OBLITERATE_CHOICE:
            return f"**Obliterate {options.left}**: which unit goes?"
        if self.prompt.kind is PromptKind.SPARKSHOT_TARGET:
            if options.left > 1 or options.placed:
                return f"**Sparkshot**: {options.left} of its damage left to place."
            return ""
        if self.prompt.kind is PromptKind.OVERPOWER_TARGET:
            return f"**Overpower** carries {options.excess} over."
        if self.mode == "detect":
            return "**Detect with your tower**: which of theirs?"
        if self.mode == "hire":
            return (f"**Hire a worker** for {self.prompt.options.hire.cost} gold: "
                    "which card goes? It is trashed unseen.")
        if self.mode == "attack":
            return "**Attack** with which?"
        if self.mode == "boost":
            return f"**{card_name(self.slug)}**: pay its boost?"
        if self.mode == "spec":
            row = self.build_row()
            if row is not None and row.lab_specs:
                return ("**Build Tech II**: choose its spec, then your tech lab's -- "
                        "a different one.")
            what = "Tech II" if self.building == "tech2" else "your tech lab"
            return f"**Build {what}**: which spec does it unlock?"
        return ""

    async def open_mode(self, interaction: discord.Interaction, mode: str) -> None:
        """Change the panel's mode in place -- the click's own response
        -- with the mode's question under the prompt's ask."""
        game, _ = await self.mine(interaction)
        if game is None:
            return
        view = TurnPanelView(self.cog, self.game_id, self.prompt, self.match, mode=mode)
        caption = view.caption()
        await self.show(interaction, view,
                        self.cog.panel_caption(game, self.prompt, caption) if caption else None)

    async def summon(self, interaction: discord.Interaction, hero: str) -> None:
        await self.act(interaction, Action(PromptKind.MAIN_ACTION, "summon", {"hero": hero}))

    def ability_label(self, ability) -> str:
        """An ability's button: what offers it and what it does, in the
        card's own words (`codex.effects.EFFECTS`)."""
        if ability.effect == "stop_the_music":
            return f"Sacrifice {card_name(effects.HARMONY)}: stop the music"
        effect = effects.EFFECTS[ability.effect]
        says = effect.says or effect.parts[0].says
        return f"{self.label(ability.source)}: {ability.pays} to {says}"

    async def level(self, interaction: discord.Interaction, hero: str) -> None:
        """One level for a gold: a level a click."""
        await self.act(interaction, Action(
            PromptKind.MAIN_ACTION, "level", {"levels": 1, "hero": hero},
        ))

    async def ability(self, interaction: discord.Interaction, effect: str, source: str) -> None:
        await self.act(interaction, Action(
            PromptKind.MAIN_ACTION, "ability", {"ability": effect, "source": source},
        ))

    async def play(self, interaction: discord.Interaction, slug: str, boost: bool = False) -> None:
        arguments = {"slug": slug}
        if boost:
            arguments["boost"] = True
        await self.act(interaction, Action(PromptKind.MAIN_ACTION, "play", arguments))

    # -- Boost (UMR p. 16) ---------------------------------------------------

    async def open_boost(self, interaction: discord.Interaction, slug: str) -> None:
        """A card with a boost the player can pay: the panel asks whether
        to pay it, the shape **Attack...** has."""
        game, _ = await self.mine(interaction)
        if game is None:
            return
        view = TurnPanelView(self.cog, self.game_id, self.prompt, self.match, mode="boost", slug=slug)
        await self.show(interaction, view, self.cog.panel_caption(game, self.prompt, view.caption()))

    def build_boost(self, options) -> None:
        """**Play** and **Play boosted**, each with what it costs, as the
        card's row in the options says, and **Back**."""
        row = next((one for one in options.playable if one.slug == self.slug), None)
        if row is not None and row.allowed:
            name = card_name(row.slug)
            self.button(f"Play {name} ({row.cost} gold)", discord.ButtonStyle.primary,
                        self._answer(self.play, row.slug), row=0)
            boosted = self.make_button(
                f"Play {name} boosted ({row.cost + row.boost} gold)" if row.boostable
                else f"Boost: {row.boost_why_not}",
                discord.ButtonStyle.success, self._answer(self.play, row.slug, True),
                disabled=not row.boostable, choice=("boost", row.slug),
            )
            boosted.row = 0
            self.add_item(boosted)
        self.button("Back", discord.ButtonStyle.secondary, self.back, row=1)

    async def build(self, interaction: discord.Interaction, building: str,
                    spec: str | None = None, lab_spec: str | None = None) -> None:
        arguments = {"building": building}
        if spec is not None:
            arguments["spec"] = spec
        if lab_spec is not None:
            arguments["lab_spec"] = lab_spec
        await self.act(interaction, Action(PromptKind.MAIN_ACTION, "build", arguments))

    # -- The spec a building chooses (UMR pp. 8-9) ----------------------------

    def build_row(self):
        return next((row for row in self.prompt.options.buildings
                     if row.building == self.building), None)

    async def open_spec(self, interaction: discord.Interaction, building: str) -> None:
        """Build Tech II in a standard game, or Build Tech lab where the
        Tech II's spec is chosen: the panel turns into the spec choice,
        a button per spec the options offer, and **Back** -- the shape
        Attack... has."""
        game, _ = await self.mine(interaction)
        if game is None:
            return
        view = TurnPanelView(self.cog, self.game_id, self.prompt, self.match,
                             mode="spec", building=building)
        await self.show(interaction, view, self.cog.panel_caption(game, self.prompt, view.caption()))

    def build_spec(self, options) -> None:
        """
        A button per spec the building may choose; where a tech lab
        waits on its spec, the Tech II's first -- marked once chosen --
        and then a row for the lab's, a different one, whose button
        builds. **Back** on the last row.
        """
        row = self.build_row()
        if row is None:
            self.button("Back", discord.ButtonStyle.secondary, self.back, row=0)
            return
        name = "Tech II" if row.building == "tech2" else "Tech lab"
        if not row.lab_specs:
            buttons = [
                self.make_button(
                    f"{name}: {deck_name((spec,))}", discord.ButtonStyle.primary,
                    self._answer(self.build, row.building, spec),
                    choice=("spec", row.building, spec),
                )
                for spec in row.specs
            ]
            at = self.place(buttons, 0, until=ROWS - 1)
            self.button("Back", discord.ButtonStyle.secondary, self.back, row=at)
            return
        firsts = [
            self.make_button(
                f"Tech II: {deck_name((spec,))}",
                discord.ButtonStyle.success if spec == self.spec else discord.ButtonStyle.primary,
                self._answer(self.choose_tech2_spec, spec), choice=("spec", "tech2", spec),
            )
            for spec in row.specs
        ]
        at = self.place(firsts, 0, until=ROWS - 2)
        labs = [
            self.make_button(
                f"Tech lab: {deck_name((spec,))}", discord.ButtonStyle.primary,
                self._answer(self.build, row.building, self.spec, spec),
                disabled=self.spec is None or spec == self.spec,
                choice=("lab_spec", spec),
            )
            for spec in row.lab_specs
        ]
        at = self.place(labs, at, until=ROWS - 1)
        self.button("Back", discord.ButtonStyle.secondary, self.back, row=at)

    async def choose_tech2_spec(self, interaction: discord.Interaction, spec: str) -> None:
        """The Tech II's spec, marked; the lab's row is pressed next. The
        panel's own edit -- nothing is applied until the lab's button."""
        game, _ = await self.mine(interaction)
        if game is None:
            return
        await self.show(interaction, TurnPanelView(
            self.cog, self.game_id, self.prompt, self.match, mode="spec",
            building=self.building, spec=spec,
        ))

    async def attack(self, interaction: discord.Interaction, ref: str) -> None:
        await self.act(interaction, Action(PromptKind.MAIN_ACTION, "attack", {"attacker": ref}))

    async def end_main(self, interaction: discord.Interaction) -> None:
        await self.act(interaction, Action(PromptKind.MAIN_ACTION, "end_main"))

    # -- Attacking: with what ------------------------------------------------

    async def open_attack(self, interaction: discord.Interaction) -> None:
        await self.open_mode(interaction, "attack")

    def build_attack(self, options) -> None:
        """What may attack, one button each (the engine's `attackers`),
        and **Back**; the defender is asked next, in the same panel."""
        attackers = [
            self.make_button(self.label(ref), discord.ButtonStyle.primary,
                             self._answer(self.attack, ref), choice=("attack", ref))
            for ref in options.attackers
        ]
        row = self.place(attackers, 0, until=ROWS - 1)
        self.button("Back", discord.ButtonStyle.secondary, self.back, row=row)

    # -- Hiring: which card goes -------------------------------------------

    async def open_hire(self, interaction: discord.Interaction) -> None:
        await self.open_mode(interaction, "hire")

    def build_hire(self, options) -> None:
        """The hand, a button per card by its number in the picture
        (`hand_numbers`): the one hired with is trashed unseen (UMR
        p. 6). **Back** on the row after."""
        numbers = hand_numbers(options)
        cards = [
            self.make_button(
                f"{numbers.get(row.slug, '?')}. {card_name(row.slug)}",
                discord.ButtonStyle.primary, self._answer(self.hire, row.slug),
                choice=("hire", row.slug),
            )
            for row in options.playable
        ] or [self.make_button("There is no card in hand to hire with",
                               discord.ButtonStyle.secondary, None, disabled=True)]
        row = self.place(cards, 0, until=ROWS - 1)
        self.button("Back", discord.ButtonStyle.secondary, self.back, row=row)

    async def hire(self, interaction: discord.Interaction, slug: str) -> None:
        await self.act(interaction, Action(PromptKind.MAIN_ACTION, "hire", {"slug": slug}))

    # -- The tower's detection ---------------------------------------------

    async def open_detect(self, interaction: discord.Interaction) -> None:
        await self.open_mode(interaction, "detect")

    def build_detect(self, options) -> None:
        """What the tower may detect, a button each as the engine offers
        it (UMR p. 9), and **Back**."""
        other = 2 if self.seat == 1 else 1
        candidates = self.choices(
            options.detect.candidates, lambda ref: self.label(ref, other), self.detect,
            "detect", "Nothing of theirs is hidden",
        )
        row = self.place(candidates, 0, until=ROWS - 1)
        self.button("Back", discord.ButtonStyle.secondary, self.back, row=row)

    async def detect(self, interaction: discord.Interaction, ref: str) -> None:
        await self.act(interaction, Action(PromptKind.MAIN_ACTION, "detect", {"card": ref}))

    async def back(self, interaction: discord.Interaction) -> None:
        game, match = await self.mine(interaction)
        if game is None:
            return
        await self.cog.show_panel(interaction, game, match, self.seat, edit=True)

    # -- The defender ------------------------------------------------------

    def build_defenders(self, options) -> None:
        """The legal defenders, a button each labelled with why it is
        legal (`DefenderOptions.why`, the engine's), and **Cancel**."""
        other = 2 if self.seat == 1 else 1
        whys = options.why or ("",) * len(options.defenders)
        defenders = [
            self.make_button(
                f"{self.label(ref, other)} -- {why}" if why else self.label(ref, other),
                discord.ButtonStyle.primary, self._answer(self.defend, ref),
                choice=("defend", ref),
            )
            for ref, why in zip(options.defenders, whys)
        ] or [self.make_button("Nothing can be attacked", discord.ButtonStyle.secondary,
                               None, disabled=True)]
        row = self.place(defenders, 0, until=ROWS - 1)
        self.button("Cancel the attack", discord.ButtonStyle.secondary, self.cancel_attack, row=row)

    async def defend(self, interaction: discord.Interaction, ref: str) -> None:
        await self.act(interaction, Action(PromptKind.CHOOSE_DEFENDER, "", {"defender": ref}))

    async def cancel_attack(self, interaction: discord.Interaction) -> None:
        await self.act(interaction, Action(PromptKind.CHOOSE_DEFENDER, "cancel"))

    # -- The choices inside an attack ----------------------------------------

    def build_obliterate(self, options) -> None:
        """Which of the equally low-tech units obliterate takes, a
        button each."""
        other = 2 if self.seat == 1 else 1
        self.place(self.choices(
            options.units, lambda ref: self.label(ref, other), self.obliterate,
            "obliterate", "Nothing to obliterate",
        ), 0)

    async def obliterate(self, interaction: discord.Interaction, ref: str) -> None:
        await self.act(interaction, Action(PromptKind.OBLITERATE_CHOICE, "", {"unit": ref}))

    def build_sparkshot(self, options) -> None:
        """Which patroller beside the one attacked takes sparkshot's 1, a
        button each; how much is left to place is the caption's."""
        other = 2 if self.seat == 1 else 1
        self.place(self.choices(
            options.patrollers, lambda ref: self.label(ref, other), self.sparkshot,
            "sparkshot", "No patroller is beside it",
        ), 0)

    async def sparkshot(self, interaction: discord.Interaction, ref: str) -> None:
        await self.act(interaction, Action(PromptKind.SPARKSHOT_TARGET, "", {"patroller": ref}))

    def build_overpower(self, options) -> None:
        """Where overpower's excess goes, a button each; how much it is
        is the caption's."""
        other = 2 if self.seat == 1 else 1
        self.place(self.choices(
            options.targets, lambda ref: self.label(ref, other), self.overpower,
            "overpower", "Nothing can take it",
        ), 0)

    async def overpower(self, interaction: discord.Interaction, ref: str) -> None:
        await self.act(interaction, Action(PromptKind.OVERPOWER_TARGET, "", {"target": ref}))

    # -- The questions an effect asks -----------------------------------------

    def target_label(self, row) -> str:
        """A target in the menu: whose, what, and what it costs -- its
        resist -- or why it is forced (the flagbearer)."""
        if row.ref.startswith(("hand:", "codex:")):
            return self.label(row.ref, row.seat)
        whose = "Your" if row.seat == self.seat else "Their"
        label = f"{whose} {self.label(row.ref, row.seat)}"
        if row.resist:
            label += f" -- resist: pay {row.resist} gold"
        if row.flagbearer:
            label += " -- flagbearer"
        return label

    def build_target(self, options) -> None:
        """What the part being resolved may choose, a button each as the
        engine offers it -- the flagbearers alone where the rule forces
        one -- under the ask, which says what the part does; and
        **Cancel** where the model offers it."""
        targets = [
            self.make_button(
                self.target_label(row), discord.ButtonStyle.primary,
                self._answer(self.target, row.key), choice=("target", row.key),
            )
            for row in options.targets
        ] or [self.make_button("Nothing can be chosen", discord.ButtonStyle.secondary,
                               None, disabled=True)]
        last = options.cancellable or options.done
        row = self.place(targets, 0, until=ROWS - 1 if last else ROWS)
        if options.done:
            self.button("Done", discord.ButtonStyle.success, self.done_choosing, row=row)
        if options.cancellable:
            self.button("Cancel", discord.ButtonStyle.secondary, self.cancel_cast, row=row)

    async def done_choosing(self, interaction: discord.Interaction) -> None:
        """**Done**: the part chooses nothing more -- "up to", "you may"."""
        await self.act(interaction, Action(PromptKind.TARGET, "done"))

    # -- Divided damage and "choose one" (step 11) -----------------------------

    def build_divide(self, options) -> None:
        """A button per target chosen, each adding a point of the damage
        to it, with what it has so far; **Cancel** where offered."""
        buttons = []
        for key, amount in options.split:
            seat, _, ref = key.partition(":")
            buttons.append(self.make_button(
                f"+1 to {self.label(ref, int(seat))} (has {amount})", discord.ButtonStyle.primary,
                self._answer(self.divide, key), choice=("divide", key),
            ))
        row = self.place(buttons, 0, until=ROWS - 1 if options.cancellable else ROWS)
        if options.cancellable:
            self.button("Cancel", discord.ButtonStyle.secondary, self.cancel_divide, row=row)

    async def divide(self, interaction: discord.Interaction, key: str) -> None:
        await self.act(interaction, Action(PromptKind.DIVIDE_DAMAGE, "", {"target": key}))

    async def cancel_divide(self, interaction: discord.Interaction) -> None:
        await self.act(interaction, Action(PromptKind.DIVIDE_DAMAGE, "cancel"))

    def build_mode(self, options) -> None:
        """A button per mode, in the card's words; **Cancel** where offered."""
        buttons = [
            self.make_button(says[0].upper() + says[1:], discord.ButtonStyle.primary,
                             self._answer(self.mode_choice, key), choice=("mode", key))
            for key, says in options.modes
        ]
        row = self.place(buttons, 0, until=ROWS - 1 if options.cancellable else ROWS)
        if options.cancellable:
            self.button("Cancel", discord.ButtonStyle.secondary, self.cancel_mode, row=row)

    async def mode_choice(self, interaction: discord.Interaction, key: str) -> None:
        await self.act(interaction, Action(PromptKind.MODE_CHOICE, "", {"mode": key}))

    async def cancel_mode(self, interaction: discord.Interaction) -> None:
        await self.act(interaction, Action(PromptKind.MODE_CHOICE, "cancel"))

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

    def upkeep_label(self, effect: str) -> str:
        """An upkeep effect's button: the two the basic set orders by
        their own words, and red and green's by the card whose it is."""
        if effect in self.UPKEEP_LABELS:
            return self.UPKEEP_LABELS[effect]
        kind, _, ident = effect.partition(":")
        if ident:
            return f"{self.label(f'unit:{ident}')} first"
        return effect

    def build_upkeep(self, options) -> None:
        for effect in options.effects:
            self.button(
                self.upkeep_label(effect), discord.ButtonStyle.primary,
                self._upkeep(effect), row=0,
            )

    def _upkeep(self, effect: str):
        async def run(interaction: discord.Interaction) -> None:
            await self.act(interaction, Action(PromptKind.UPKEEP_ORDER, "", {"first": effect}))
        return run

    def build_level_gain(self, options) -> None:
        """Which hero gains the kill's two levels, a button each (UMR
        p. 10)."""
        self.place(self.choices(
            options.heroes, lambda ref: self.label(ref, options.owner), self.level_gain,
            "level_gain", "No hero is in play",
        ), 0)

    async def level_gain(self, interaction: discord.Interaction, ref: str) -> None:
        await self.act(interaction, Action(PromptKind.LEVEL_GAIN, "", {"hero": ref}))

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
    "NOT_YOUR_PANEL", "PANEL_TIMEOUT", "PanelButton", "PanelView", "TurnPanelView",
    "UndoConfirmView", "building_label", "hand_numbers",
]

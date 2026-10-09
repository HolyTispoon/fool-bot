"""
`TurnPanelView`, the active player's control panel (docs/codex-bot.md,
decision 4; docs/design/codex.md, "The panel"): **one ephemeral message
edited in place by its own interactions**, the cards in the hand
pictured above it, the main phase's actions under it. The view for
`MAIN_ACTION` and `CHOOSE_DEFENDER`, for the three choices an attack
asks inside itself -- obliterate's tie, sparkshot's neighbour and
overpower's excess -- and for the questions an effect asks as it
resolves: a target (`TARGET`), Appel Stomp's place (`APPEL_STOMP_TOP`)
and the upkeep's order (`UPKEEP_ORDER`), each buttons for what the
prompt offers.

Every control is built from the prompt's options and nothing else --
`MainActionOptions` for the actions, `DefenderOptions` for the defender
-- and every click answers through `SafeView.apply`, so the driver
refuses whatever the options did not offer. **The main phase is rows
of buttons, not menus** (the author, 2026-10-09): a card in the hand
is a button, a building is a button, the hero's level is one button
that buys one level, and **Attack...** opens the attackers as buttons.
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

#: A message carries five rows of components, five buttons a row.
ROWS = 5
BUTTONS_PER_ROW = 5

#: The hand's buttons take at most this many rows, so the board's row
#: -- what may be built, the tower, the abilities -- always has one
#: left after the actions row and the hand.
HAND_ROWS = 3

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
    `("attack", ref)`, `("ability", effect, source)`, `("level",)`,
    `("hire", slug)`, `("defend", ref)`, `("target", key)`,
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
        await interaction.response.defer()
        await self.cog.present(game, result, before)
        await self.cog.answer_panel(interaction, game, self.seat, result, action.kind, replace=True)

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
    author, 2026-10-09): the actions row -- **Hire worker**, **Summon**
    or **Level up** the hero (one level a click), **Attack...**,
    **Undo...** -- then the hand, a button per card numbered as the
    picture numbers it and disabled where it may not be played, then the
    board's row -- **Build** per building that may be built, **Detect...**
    where there is a tower, and each ability that may be used -- and
    **End main phase** last of all. A control the engine says no to is disabled with its
    reason as its label. **Attack...** turns the panel into what may
    attack, one button each, and **Back**; **Hire worker** into the
    hand, a button per card. For `CHOOSE_DEFENDER`, a button per legal
    defender, each with why it is legal, and **Cancel**.
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
        elif mode == "attack":
            self.build_attack(options)
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
        """The actions row, the hand's rows, then the board's row -- each
        group starting a row of its own, five buttons a row."""
        hire = options.hire
        actions = [
            self.make_button(
                "Hire worker" if hire.allowed else f"Hire: {hire.why_not}",
                discord.ButtonStyle.primary, self.open_hire, disabled=not hire.allowed,
            ),
            self.hero_button(options.hero),
            self.make_button(
                "Attack..." if options.attackers else "Attack: nothing of yours can attack now",
                discord.ButtonStyle.primary, self.open_attack, disabled=not options.attackers,
            ),
            self.make_button("Undo...", discord.ButtonStyle.secondary, self.open_undo),
        ]
        # The hand, every card once in the hand's order (`playable`), by
        # its number in the picture: a card that may not be played now
        # is there and disabled, as the picture greys it.
        numbers = hand_numbers(options)
        hand = [
            self.make_button(
                f"{numbers.get(row.slug, '?')}. {card_name(row.slug)} ({row.cost} gold)",
                discord.ButtonStyle.primary if row.allowed else discord.ButtonStyle.secondary,
                self._answer(self.play, row.slug), disabled=not row.allowed,
                choice=("play", row.slug),
            )
            for row in options.playable
        ] or [self.make_button("Your hand is empty", discord.ButtonStyle.secondary, None,
                               disabled=True)]
        board = [
            self.make_button(
                f"Build {building_label(row.building)} ({row.cost} gold)",
                discord.ButtonStyle.primary, self._answer(self.build, row.building),
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
        # **End main phase** is always the panel's last button (the
        # author, 2026-10-09), after the board's row, and always placed.
        end = self.make_button("End main phase", discord.ButtonStyle.danger, self.end_main)
        row = self.place(actions, 0)
        row = self.place(hand, row, until=row + HAND_ROWS)
        self.place(board, row, last=end)

    def hero_button(self, hero) -> PanelButton:
        """**Summon** for its cost, or **Level up** by one level -- a
        level a click (the author, 2026-10-09) -- or why neither."""
        name = card_name(hero.slug)
        if hero.action == "summon":
            return self.make_button(
                f"Summon {name} ({hero.cost} gold)" if not hero.why_not
                else f"Summon: {hero.why_not}",
                discord.ButtonStyle.primary, self.summon, disabled=bool(hero.why_not),
            )
        if hero.action == "level" and not hero.why_not and hero.max_levels:
            return self.make_button(
                f"Level up {name} ({hero.cost} gold)", discord.ButtonStyle.primary,
                self.level, choice=("level",),
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

    def place(self, buttons: list, row: int, until: int = ROWS, last=None) -> int:
        """
        Add `buttons` five a row from `row`, before row `until`; the next
        free row. What does not fit is left out: a message carries five
        rows, and the groups placed first have the earlier claim. `last`
        goes after them and is never left out: a button of `buttons`
        gives up its place to it where they would fill the rows.
        """
        until = min(until, ROWS)
        if last is not None:
            room = max(until - row, 0) * BUTTONS_PER_ROW
            buttons = list(buttons)[: max(room - 1, 0)] + [last]
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

    async def summon(self, interaction: discord.Interaction) -> None:
        await self.act(interaction, Action(PromptKind.MAIN_ACTION, "summon"))

    def ability_label(self, ability) -> str:
        """An ability's button: what offers it and what it does, in the
        card's own words (`codex.effects.EFFECTS`)."""
        if ability.effect == "stop_the_music":
            return f"Sacrifice {card_name(effects.HARMONY)}: stop the music"
        says = effects.EFFECTS[ability.effect].parts[0].says
        return f"{self.label(ability.source)}: exhaust to {says}"

    async def level(self, interaction: discord.Interaction) -> None:
        """One level for a gold: a level a click."""
        await self.act(interaction, Action(PromptKind.MAIN_ACTION, "level", {"levels": 1}))

    async def ability(self, interaction: discord.Interaction, effect: str, source: str) -> None:
        await self.act(interaction, Action(
            PromptKind.MAIN_ACTION, "ability", {"ability": effect, "source": source},
        ))

    async def play(self, interaction: discord.Interaction, slug: str) -> None:
        await self.act(interaction, Action(PromptKind.MAIN_ACTION, "play", {"slug": slug}))

    async def build(self, interaction: discord.Interaction, building: str) -> None:
        await self.act(interaction, Action(PromptKind.MAIN_ACTION, "build", {"building": building}))

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
        row = self.place(targets, 0, until=ROWS - 1 if options.cancellable else ROWS)
        if options.cancellable:
            self.button("Cancel", discord.ButtonStyle.secondary, self.cancel_cast, row=row)

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
    "NOT_YOUR_PANEL", "PANEL_TIMEOUT", "PanelButton", "PanelView", "TurnPanelView",
    "UndoConfirmView", "building_label", "hand_numbers",
]

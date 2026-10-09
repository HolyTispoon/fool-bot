"""
The buttons on the current turn's public message (docs/codex-bot.md,
decisions 4 and 5): **My hand**, **My deck**, **Tech**, **Codex**,
**Swap view** and **Concede**
-- persistent, so a restart re-arms them from `turn_message_id`.

Hidden information is answered **ephemerally**, to the clicker alone and
stored nowhere. **My hand** is one button with two answers by who
clicked (the author, 2026-10-08): the active player gets their hand, a
message of its own, and under it the control panel for whatever the
match asks them -- the actions, the defender, the patrol lock, the tech
confirmation -- made afresh each time, the hand brought up to date in
place as the turn goes (docs/design/codex.md, "The panel"); the other
player gets their hand pictured and their discard pile listed, with
**My deck** under it, kept up to date the same way. Where the active
player's turn waits on their tech, **My hand** still sends the hand,
and the panel under it is a **Tech** button rather than the turn's
actions until the tech is confirmed (`TechGateView`). **Tech** answers
the active player with that confirmation -- or the picker, where
nothing was picked -- while their turn waits on it, and the other
player with their standing tech choice, open all through the
opponent's turn; in a test game, where nothing stands
(`codex.prompts.tech_stands`), it says where the choice is made
otherwise. **Codex** pictures the clicker's own
codex through a menu of views. **My deck** -- on the turn message,
under the hand, on the panel and on the tech picker -- answers with
every card the clicker owns, wherever it is, those in their hand and
their discard pile boxed apart (`send_deck`). What a hand
may play, what a codex still holds and what a deck is are the engine's
answers (`hand_rows`, `codex_remaining`, `own_deck`); the views compute
nothing.
**Concede** gives up the clicker's own side, behind a second click on an
ephemeral confirmation (`ConcedeConfirmView`).
"""

import asyncio
import logging
import time
from collections import Counter

import discord

from codex.formatting import codex_view_name, deck_name
from codex.game import GameStatus, RuleRefusal
from codex.render import render_codex, render_deck, render_hand
from cogs.codex_helpers import card_name, elapsed_ms, pictures_size
from cogs.codex_views.base import SafeView, kept_pictures, picture_file, send_ephemeral

LOGGER = logging.getLogger(__name__)

NOT_YOUR_TABLE = "This table is not yours: only its two players have a hand and a codex here."
TECH_IN_READY_PHASE = (
    "In a test game each side chooses its tech when its own turn begins, from "
    "**Tech** or **My hand** -- nothing is chosen during the other side's turn."
)


def codex_view_menu(views, current: str, row: int | None = None) -> discord.ui.Select:
    """
    The **Show...** menu over a codex -- the engine's `codex_views`, each
    by `codex_view_name`, the one shown marked -- as the Codex browser
    and the tech picker both carry it. The caller binds its callback.
    """
    return discord.ui.Select(
        placeholder="Show...", row=row,
        options=[
            discord.SelectOption(label=codex_view_name(view), value=view, default=view == current)
            for view in views
        ],
    )


def swap_label(layout: str) -> str:
    """The layout the button would switch to."""
    return "View: side by side" if layout == "stacked" else "View: stacked"


class TurnMessageView(SafeView):
    def __init__(self, cog, game_id: str) -> None:
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id
        game = cog.games.get(game_id)
        layout = game.board_layout if game is not None else "stacked"
        for label, action, style in (
            ("My hand", "hand", discord.ButtonStyle.primary),
            ("My deck", "deck", discord.ButtonStyle.secondary),
            ("Tech", "tech", discord.ButtonStyle.secondary),
            ("Codex", "codex", discord.ButtonStyle.secondary),
            (swap_label(layout), "swap", discord.ButtonStyle.secondary),
            ("Concede", "concede", discord.ButtonStyle.danger),
        ):
            button = discord.ui.Button(
                label=label, style=style, custom_id=f"codex:turn:{action}:{game_id}",
            )
            button.callback = getattr(self, action)
            self.add_item(button)

    async def _seat(self, interaction: discord.Interaction):
        game, match = await self.require_match(interaction)
        if game is None:
            return None, None, None
        seat = game.seat_for(interaction.user.id, match.active)
        if seat is None:
            await send_ephemeral(interaction, NOT_YOUR_TABLE)
            return None, None, None
        return game, match, seat

    async def hand(self, interaction: discord.Interaction) -> None:
        """The hand and the panel under it for the active player, the
        hand for the other."""
        game, match, seat = await self._seat(interaction)
        if seat is None:
            return
        if seat == match.active and match.winner is None:
            await self.cog.show_panel(interaction, game, match, seat, edit=False)
            return
        await self.cog.send_hand(interaction, game, match, seat)

    async def deck(self, interaction: discord.Interaction) -> None:
        """Every card the clicker owns, to them alone, whoever's turn it
        is."""
        game, match, seat = await self._seat(interaction)
        if seat is None:
            return
        await self.cog.send_deck(interaction, game, match, seat)

    async def tech(self, interaction: discord.Interaction) -> None:
        """The clicker's tech, to them alone: the active player's
        confirmation or picker where their turn waits on it, else the
        other player's standing choice."""
        game, match, seat = await self._seat(interaction)
        if seat is None:
            return
        if seat == match.active and match.winner is None and self.cog.tech_asked(game, match, seat):
            # The turn opens on its player's tech: the confirmation, or
            # the picker where nothing was picked -- or in a test game.
            await self.cog.show_panel(interaction, game, match, seat, edit=False, open_tech=True)
            return
        if game.test_game:
            # The one person holds both seats and nothing stands for
            # either: each side's tech is the pending prompt in its own
            # ready phase, from My hand.
            await send_ephemeral(interaction, TECH_IN_READY_PHASE)
            return
        if seat == match.active:
            await send_ephemeral(
                interaction,
                "Tech is chosen at the end of your turn and changed during your "
                "opponent's: it is not yours to press now.",
            )
            return
        if self.cog.standing_for(game, match, seat) is None:
            await send_ephemeral(interaction, "You have no tech choice open.")
            return
        await self.cog.show_panel(interaction, game, match, seat, edit=False, standing=True)

    async def codex(self, interaction: discord.Interaction) -> None:
        game, match, seat = await self._seat(interaction)
        if seat is None:
            return
        view = CodexBrowser(self.cog, game.game_id, seat, side=side_label(game, match, seat))
        started = time.perf_counter()
        file = await view.picture(match, "everything")
        drawn = elapsed_ms(started)
        started = time.perf_counter()
        await interaction.response.send_message(
            view.caption("everything"), file=file, view=view, ephemeral=True,
        )
        LOGGER.info("Codex game #%s: the codex drawn in %d ms (%d KB), sent in %d ms",
                    game.game_number, drawn, pictures_size([file]) // 1024, elapsed_ms(started))

    async def concede(self, interaction: discord.Interaction) -> None:
        """The clicker's own side given up, behind a second click
        (`ConcedeConfirmView`) -- in a test game, the side whose turn
        it is."""
        await self.cog.ask_concede(interaction, self.cog.games.get(self.game_id))

    async def swap(self, interaction: discord.Interaction) -> None:
        game = self.cog.games.get(self.game_id)
        if game is None or game.status is not GameStatus.PLAYING:
            await send_ephemeral(interaction, "This game is not being played.")
            return
        if not self.may_act_in_game(interaction, game):
            await send_ephemeral(interaction, "Only the players can swap the board's view.")
            return
        layout = "side_by_side" if game.board_layout == "stacked" else "stacked"
        try:
            self.cog.service.set_board_layout(game.game_id, layout)
        except RuleRefusal as refused:
            await send_ephemeral(interaction, str(refused))
            return
        # Acknowledged with nothing to show: the board itself is the
        # answer, and it goes up through the gate like every other write.
        await interaction.response.defer()
        await self.cog.refresh_match_image(game)


def side_label(game, match, seat: int) -> str:
    """" (Bashing)" -- which side a picture is of, said only in a test
    game, where one person holds both and the turn decides which."""
    if not game.test_game:
        return ""
    return f" ({deck_name(match.player(seat).specs)})"


def hand_caption(match, seat: int, side: str = "") -> str:
    """What the hand picture is sent with: its count and the discard
    pile's contents, which is its owner's to know (UMR p. 5)."""
    player = match.player(seat)
    count = len(player.hand)
    lines = [f"Your hand{side}: {count} card" + ("" if count == 1 else "s") + ". Only you can see this."]
    if player.discard:
        counted = Counter(player.discard)
        listed = ", ".join(
            card_name(slug) + (f" x{copies}" if copies > 1 else "")
            for slug, copies in sorted(counted.items(), key=lambda row: card_name(row[0]))
        )
        lines.append(f"Your discard pile ({len(player.discard)}): {listed}.")
    else:
        lines.append("Your discard pile is empty.")
    return "\n".join(lines)


async def hand_file(engine, match, seat: int, rows=None) -> discord.File:
    """`seat`'s hand pictured: the rows given -- a prompt's
    `MainActionOptions.hand` -- or the engine's `hand_rows`."""
    if rows is None:
        rows = engine.hand_rows(match, seat)
    webp = await asyncio.to_thread(
        render_hand, [row.slug for row in rows], [row.allowed for row in rows],
        [row.cost for row in rows], engine.catalog,
    )
    return picture_file(webp, "codex-hand")


def deck_caption(deck, side: str = "") -> str:
    """What the deck picture is sent with: its size alone (the author,
    2026-10-09: "cut down on text") -- where the cards are is the
    picture's."""
    return f"Total cards in deck{side}: {deck.size}."


async def deck_file(engine, deck) -> discord.File:
    """A deck pictured in three parts (`render_deck`): the cards in the
    hand boxed at the top, those in the discard pile boxed under them,
    and the rest under both, each card once per part with its copies
    there on its badge -- the engine's split (`OwnDeck.held`,
    `discarded`, `elsewhere`)."""
    webp = await asyncio.to_thread(
        render_deck, deck.held, deck.discarded, deck.elsewhere, engine.catalog,
    )
    return picture_file(webp, "codex-deck")


def deck_button(callback, row: int | None = None) -> discord.ui.Button:
    """**My deck**: every card the clicker owns, in a message of its own
    beside whatever it was pressed under (`send_deck`)."""
    button = discord.ui.Button(label="My deck", style=discord.ButtonStyle.secondary, row=row)
    button.callback = callback
    return button


class HandView(SafeView):
    """
    Under the hand **My hand** shows the player whose turn it is not:
    **My deck** alone, the hand being nothing to press. Not persistent:
    an ephemeral message dies with the client's session.
    """

    def __init__(self, cog, game_id: str, seat: int) -> None:
        super().__init__(timeout=900)
        self.cog = cog
        self.game_id = game_id
        self.seat = seat
        self.add_item(deck_button(self.deck))

    async def deck(self, interaction: discord.Interaction) -> None:
        game, match = await self.require_match(interaction)
        if game is None:
            return
        await self.cog.send_deck(interaction, game, match, self.seat)


class CodexBrowser(SafeView):
    """
    The clicker's own codex, ephemeral, under a menu of views --
    Everything, Tech I to III, Spells -- the picture re-rendered in place
    on each choice (the author, 2026-10-08: "a lot of cards"). Not
    persistent: an ephemeral message dies with the client's session, and
    **Codex** on the turn message makes a fresh one.
    """

    def __init__(self, cog, game_id: str, seat: int, side: str = "") -> None:
        super().__init__(timeout=900)
        self.cog = cog
        self.game_id = game_id
        self.seat = seat
        self.side = side
        game = cog.games.get(game_id)
        match = cog.service.load(game)
        select = codex_view_menu(cog.engine.codex_views(match.player(seat)), "everything")
        select.callback = self.choose
        self.select = select
        self.add_item(select)

    def caption(self, view: str) -> str:
        return f"Your codex{self.side}: {codex_view_name(view)}. Only you can see this."

    async def picture(self, match, view: str) -> discord.File:
        rows = self.cog.engine.codex_remaining(match, self.seat, view)
        webp = await asyncio.to_thread(
            render_codex, [slug for slug, _ in rows], [count for _, count in rows],
            self.cog.engine.catalog,
        )
        return picture_file(webp, f"codex-{view}")

    async def choose(self, interaction: discord.Interaction) -> None:
        game, match = await self.require_match(interaction)
        if game is None:
            return
        view = self.select.values[0]
        for option in self.select.options:
            option.default = option.value == view
        started = time.perf_counter()
        pictures = kept_pictures([await self.picture(match, view)], interaction.message)
        drawn = elapsed_ms(started)
        started = time.perf_counter()
        await interaction.response.edit_message(
            content=self.caption(view), attachments=pictures, view=self,
        )
        LOGGER.info("Codex game #%s: the codex's %s drawn in %d ms (%d KB), shown in place in %d ms",
                    game.game_number, codex_view_name(view), drawn,
                    pictures_size(pictures) // 1024, elapsed_ms(started))

"""
The buttons on the current turn's public message (docs/codex-bot.md,
decisions 4 and 5): **My hand**, **My deck**, **Tech**, **Codex**,
**Undo** and **Swap view**
-- persistent, so a restart re-arms them from `turn_message_id`.

Hidden information is answered **ephemerally**, to the clicker alone and
stored nowhere. **My hand** is one button with two answers by who
clicked (the author, 2026-10-08): the active player gets the control
panel for whatever the match asks them -- the actions, the defender,
the patrol lock, the tech confirmation -- made afresh each time, their
hand pictured on it; the other player gets their hand pictured and
their discard pile listed, with **My deck** under it. Where the active
player's turn waits on their tech, **My hand** still shows the hand,
with a **Tech** button under the picture rather than the turn's
actions until the tech is confirmed (`TechGateView`). **Tech** answers
the active player with that confirmation -- or the picker, where
nothing was picked -- while their turn waits on it, and the other
player with their standing tech choice, open all through the
opponent's turn; in a test game, where nothing stands
(`codex.prompts.tech_stands`), it says where the choice is made
otherwise. **Codex** -- on the turn message, under the hand and on the
panel -- pictures the clicker's own codex through a menu of views
(`send_codex`). **My deck** -- on the turn message,
under the hand, on the panel and on the tech picker -- answers with
every card the clicker owns, wherever it is, in three frames -- the
hand, the discard pile, the rest (`send_deck`). What a hand
may play, what a codex still holds and what a deck is are the engine's
answers (`hand_rows`, `codex_remaining`, `own_deck`); the views compute
nothing.
**Undo** answers the active player with the undos open on the position
(`UndoView`, the panel's undo mode without a panel), so an undo needs
no panel open -- and the player who ended the turn before, while this
one has done nothing but open, with **Take back the end of my turn**;
anybody else is told it is the active player's.
**Concede** is not on it: it is under the hand menus **My hand** opens
(`concede_button`), so nobody gives up the game from a public message
by a slip (the author, 2026-10-18). It gives up the clicker's own side,
behind a second click on an ephemeral confirmation
(`ConcedeConfirmView`).
"""

import asyncio
import logging
import time

import discord

from codex.formatting import codex_view_name, team_name
from codex.game import GameStatus, RuleRefusal, by_variant
from codex.render import render_codex, render_deck, render_hand
from cogs.codex_helpers import elapsed_ms, pictures_size, seat_label
from cogs.codex_publish import keys
from cogs.codex_views.base import SafeView, edit_clicked, kept_pictures, picture_file, send_ephemeral
from cogs.codex_views.turn import UndoView, concede_button, opponent_started

LOGGER = logging.getLogger(__name__)

#: The link to the game's page on the site, beside **View full image**.
LIVE_BOARD_LABEL = "View live board"

NOT_YOUR_TABLE = "This table is not yours: only its players have a hand and a codex here."
TECH_IN_READY_PHASE = (
    "In a test game each seat chooses its tech when its own turn begins, from "
    "**Tech** or **My hand**."
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


def swapped_layout(layout: str, table: bool = False) -> str:
    """
    The layout **Swap view** switches to: between the two stacked ones,
    the far panel turned to face the near one or both the same way up
    -- and from side by side, which `/codex side_by_side` alone puts up,
    back to stacked. **A table of several has no facing view** (the
    author, 2026-10-14): every panel upright, so it toggles between
    stacked and side by side.
    """
    if table:
        return "stacked" if layout == "side_by_side" else "side_by_side"
    return "stacked_upright" if layout == "stacked" else "stacked"


#: The button's label, by the layout it would switch to.
SWAP_LABELS = {
    "stacked_upright": "View: same way up",
    "stacked": "View: facing",
}


def swap_label(layout: str, table: bool = False) -> str:
    """The layout the button would switch to."""
    if layout == "side_by_side":
        return "View: stacked"
    if table:
        return "View: side by side"
    return SWAP_LABELS[swapped_layout(layout)]


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
            ("Undo", "undo", discord.ButtonStyle.secondary),
            (swap_label(layout, game is not None and game.is_free_for_all), "swap",
             discord.ButtonStyle.secondary),
        ):
            button = discord.ui.Button(
                label=label, style=style, custom_id=f"codex:turn:{action}:{game_id}",
            )
            button.callback = getattr(self, action)
            self.add_item(button)
        if game is not None and getattr(cog, "publisher", None) is not None:
            # The game's page on the site, beside the full-image link the
            # board gate puts after it -- only where this process
            # publishes, since elsewhere the page would not follow this
            # game (docs/design/pbd-site.md, "The hooks"). A link, so it
            # spends nothing and routes no click.
            self.add_item(discord.ui.Button(
                label=LIVE_BOARD_LABEL, style=discord.ButtonStyle.link, url=keys.game_page(game_id),
            ))

    async def _seat(self, interaction: discord.Interaction):
        game, match = await self.require_match(interaction)
        if game is None:
            return None, None, None
        seat = self.cog.acting_seat_for(game, match, interaction.user.id)
        if seat is None:
            await send_ephemeral(interaction, NOT_YOUR_TABLE)
            return None, None, None
        return game, match, seat

    async def hand(self, interaction: discord.Interaction) -> None:
        """The panel for the active player, the hand for the other."""
        game, match, seat = await self._seat(interaction)
        if seat is None:
            return
        await self.cog.send_hand_menu(interaction, game, match, seat)

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
        other player's standing choice -- and in a two-headed dragon,
        after it, the teammate's standing picks, read-only (decision 13;
        `Codex.send_teammate_tech`)."""
        game, match, seat = await self._seat(interaction)
        if seat is None:
            return
        await self._own_tech(interaction, game, match, seat)
        if match.is_dragon and not game.test_game:
            await self.cog.send_teammate_tech(interaction, game, match, seat)

    async def _own_tech(self, interaction: discord.Interaction, game, match, seat: int) -> None:
        if seat in self.cog.engine.turn_seats(match) and match.winner is None and self.cog.tech_asked(game, match, seat):
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
        if seat in self.cog.engine.turn_seats(match):
            await send_ephemeral(
                interaction,
                "Tech is chosen at the end of your turn and changed during "
                + by_variant(match.variant, duel="your opponent's", free_for_all="the others'",
                             dragon="the other team's")
                + ": it is not yours to press now.",
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
        await self.cog.send_codex(interaction, game, match, seat)

    async def undo(self, interaction: discord.Interaction) -> None:
        """The undos open on the position, to the active player alone --
        and taking back the end of the turn before, to the player who
        ended it, while this turn has done nothing but open."""
        game, match, seat = await self._seat(interaction)
        if seat is None:
            return
        # The seat that ended the turn before -- in a dragon either player
        # of the team that did (decision 15).
        mine = game.seats_of(interaction.user.id)
        owner = next((one for one in self.cog.service.end_of_turn_owners(game.game_id) if one in mine), None)
        ended = owner is not None
        if seat in self.cog.engine.turn_seats(match) and match.winner is None:
            targets = self.cog.service.undo_targets(game.game_id)
            points = self.cog.undo_choices(game)
        elif ended:
            # Not their turn, but theirs to take back the end of: in a
            # test game the one person holds both seats.
            seat, targets, points = owner, {}, ()
        elif (match.winner is None and any(
                one in mine for one in self.cog.service.previous_turn_owners(game.game_id))):
            # They ended the turn before -- their own, or their team's --
            # and the other player has acted since: its end is no longer
            # theirs to take back.
            await send_ephemeral(interaction, opponent_started(game, match))
            return
        else:
            await send_ephemeral(interaction, "Only the player whose turn it is can undo.")
            return
        await interaction.response.send_message(
            "Undo: how far back?",
            view=UndoView(self.cog, game.game_id, seat, match.turn, targets, points,
                          end_of_turn=ended),
            ephemeral=True,
        )

    async def swap(self, interaction: discord.Interaction) -> None:
        game = self.cog.games.get(self.game_id)
        if game is None or game.status is not GameStatus.PLAYING:
            await send_ephemeral(interaction, "This game is not being played.")
            return
        if not self.may_act_in_game(interaction, game):
            await send_ephemeral(interaction, "Only the players can swap the board's view.")
            return
        # A dragon's far team flips between facing and the same way up, as
        # a duel's far panel does (decision 14); a free-for-all has no
        # facing view.
        layout = swapped_layout(game.board_layout, game.is_free_for_all)
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
    return f" ({team_name(match.player(seat).specs)})"


def hand_caption(match, seat: int, side: str = "") -> str:
    """What the hand picture is sent with: its count alone. The discard
    pile is not listed beside it -- read under the picture it was taken
    for the hand (the author, 2026-10-11) -- and **My deck** shows it."""
    count = len(match.player(seat).hand)
    return f"Your hand{side}: {count} card" + ("" if count == 1 else "s") + "."


async def hand_files(engine, match, seat: int, rows=None) -> list[discord.File]:
    """`seat`'s hand pictured: the rows given -- a prompt's
    `MainActionOptions.hand` -- or the engine's `hand_rows`. An empty
    hand is no picture at all, never a card-sized "No cards in hand"
    (the author, 2026-10-13): the caption already counts it."""
    if rows is None:
        rows = engine.hand_rows(match, seat)
    if not rows:
        return []
    webp = await asyncio.to_thread(
        render_hand, [row.slug for row in rows], [row.allowed for row in rows],
        [row.cost for row in rows], engine.catalog,
    )
    return [picture_file(webp, "codex-hand")]


async def revealed_files(engine, match, seat: int) -> list[discord.File]:
    """The hands `seat` sees besides their own -- the opponent's, while
    `seat` controls an Eyes of the Chancellor (`RulesEngine.hands_visible_to`,
    step 13) -- pictured as a hand is: shown to `seat` alone, under their
    own, and nowhere else."""
    files = []
    for other in engine.hands_visible_to(match, seat):
        slugs = list(match.player(other).hand)
        if not slugs:
            continue
        webp = await asyncio.to_thread(
            render_hand, slugs, [False] * len(slugs),
            [engine.catalog.cards[slug].cost or 0 for slug in slugs], engine.catalog,
        )
        files.append(picture_file(webp, "codex-revealed-hand"))
    return files


def revealed_caption(engine, match, seat: int, game=None) -> str:
    """The line beneath a hand that shows another's too, or "": a
    dragon's teammate's by name, "<name>'s hand" (decision 13), and an
    opponent's revealed by Eyes of the Chancellor -- "Their hand" in a
    duel, which has one opponent, the player's name at a table."""
    lines = []
    mate = engine.team_sees(match, seat)
    for other in engine.hands_visible_to(match, seat):
        count = len(match.player(other).hand)
        cards = f"{count} card" + ("" if count == 1 else "s") + "."
        name = seat_label(game, other)
        if other == mate:
            lines.append(f"{name}'s hand: {cards}")
        elif match.is_duel:
            lines.append(f"Their hand, revealed by Eyes of the Chancellor: {cards}")
        else:
            lines.append(f"{name}'s hand, revealed by Eyes of the Chancellor: {cards}")
    return "\n".join(lines)


def deck_caption(deck, side: str = "") -> str:
    """What the deck picture is sent with: its size alone (the author,
    2026-10-09: "cut down on text") -- where the cards are is the
    picture's."""
    return f"Total cards in deck{side}: {deck.size}."


async def deck_file(engine, deck) -> discord.File:
    """A deck pictured in four framed parts (`render_deck`): the cards
    in the hand, those in play, those in the discard pile and those in
    the draw pile, each card once per part with its copies there on its
    badge -- the engine's split (`OwnDeck.held`, `played`, `discarded`,
    `pile`)."""
    webp = await asyncio.to_thread(
        render_deck, deck.held, deck.played, deck.discarded, deck.pile, engine.catalog,
    )
    return picture_file(webp, "codex-deck")


def deck_button(callback, row: int | None = None) -> discord.ui.Button:
    """**My deck**: every card the clicker owns, in a message of its own
    beside whatever it was pressed under (`send_deck`)."""
    button = discord.ui.Button(label="My deck", style=discord.ButtonStyle.secondary, row=row)
    button.callback = callback
    return button


def codex_button(callback, row: int | None = None) -> discord.ui.Button:
    """**Codex**: the clicker's own codex, in a message of its own
    beside whatever it was pressed under (`Codex.send_codex`)."""
    button = discord.ui.Button(label="Codex", style=discord.ButtonStyle.secondary, row=row)
    button.callback = callback
    return button


def board_button(callback, row: int | None = None) -> discord.ui.Button:
    """**Show board**: the turn message posted again at the foot of the
    channel and the hand menu sent afresh under it, the one pressed
    deleted (`Codex.show_board`)."""
    button = discord.ui.Button(label="Show board", style=discord.ButtonStyle.secondary, row=row)
    button.callback = callback
    return button


class HandView(SafeView):
    """
    Under the hand **My hand** shows the player whose turn it is not:
    **My deck**, **Codex**, **Show board** and **Concede**, the hand
    being nothing to press. Not persistent: an ephemeral message dies
    with the client's session.
    """

    def __init__(self, cog, game_id: str, seat: int) -> None:
        super().__init__(timeout=900)
        self.cog = cog
        self.game_id = game_id
        self.seat = seat
        self.add_item(deck_button(self.deck))
        self.add_item(codex_button(self.codex))
        self.add_item(board_button(self.board))
        for button in concede_button(self.concede, cog.games.get(game_id)):
            self.add_item(button)

    async def concede(self, interaction: discord.Interaction) -> None:
        await self.cog.ask_concede(interaction, self.cog.games.get(self.game_id))

    async def deck(self, interaction: discord.Interaction) -> None:
        game, match = await self.require_match(interaction)
        if game is None:
            return
        await self.cog.send_deck(interaction, game, match, self.seat)

    async def board(self, interaction: discord.Interaction) -> None:
        game, match = await self.require_match(interaction)
        if game is None:
            return
        await self.cog.show_board(interaction, game, self.seat)

    async def codex(self, interaction: discord.Interaction) -> None:
        game, match = await self.require_match(interaction)
        if game is None:
            return
        await self.cog.send_codex(interaction, game, match, self.seat)


class WaitingView(HandView):
    """
    Under a dragon seat's panel edited where the team's turn asks it
    nothing now -- the teammate's action stands part-way, or this seat has
    locked: **Back to my turn**, which asks the position again and puts
    up whatever it asks this seat, and **My deck**, **Codex**, **Show
    board** and **Concede**.
    """

    def __init__(self, cog, game_id: str, seat: int) -> None:
        super().__init__(cog, game_id, seat)
        back = discord.ui.Button(label="Back to my turn", style=discord.ButtonStyle.primary)
        back.callback = self.back
        self.add_item(back)

    async def back(self, interaction: discord.Interaction) -> None:
        game, match = await self.require_match(interaction)
        if game is None:
            return
        if self.seat not in game.seats_of(interaction.user.id):
            await send_ephemeral(interaction, "This panel is its player's alone.")
            return
        await self.cog.show_panel(interaction, game, match, self.seat, edit=True)


class CodexBrowser(SafeView):
    """
    The clicker's own codex, ephemeral, under a menu of views --
    Everything, Tech I to III, Spells -- the picture re-rendered in place
    on each choice (the author, 2026-10-08: "a lot of cards"). Not
    persistent: an ephemeral message dies with the client's session, and
    **Codex** on the turn message makes a fresh one.
    """

    def __init__(self, cog, game_id: str, seat: int, side: str = "",
                 mate: int | None = None, mate_name: str = "") -> None:
        super().__init__(timeout=900)
        self.cog = cog
        self.game_id = game_id
        self.seat = seat
        self.side = side
        #: A two-headed dragon's teammate, whose codex the menu offers too,
        #: read-only -- "<name>'s codex" in every view they have
        #: (`RulesEngine.team_sees`; decision 13). `None` elsewhere.
        self.mate = mate
        self.mate_name = mate_name
        #: Whose codex is shown: the clicker's own, or the teammate's.
        self.owner = seat
        game = cog.games.get(game_id)
        match = cog.service.load(game)
        select = codex_view_menu(cog.engine.codex_views(match.player(seat)), "everything")
        if mate is not None:
            for view in cog.engine.codex_views(match.player(mate)):
                if len(select.options) >= 25:
                    break
                select.add_option(label=f"{mate_name}'s codex: {codex_view_name(view)}"[:100],
                                  value=f"{mate}:{view}")
        select.callback = self.choose
        self.select = select
        self.add_item(select)

    def caption(self, view: str) -> str:
        if self.owner != self.seat:
            return f"{self.mate_name}'s codex: {codex_view_name(view)}."
        return f"Your codex{self.side}: {codex_view_name(view)}."

    async def picture(self, match, view: str) -> discord.File:
        rows = self.cog.engine.codex_remaining(match, self.owner, view, viewer=self.seat)
        webp = await asyncio.to_thread(
            render_codex, [slug for slug, _ in rows], [count for _, count in rows],
            self.cog.engine.catalog, None, self.cog.engine.codex_places(rows, view),
        )
        return picture_file(webp, f"codex-{view}")

    async def choose(self, interaction: discord.Interaction) -> None:
        game, match = await self.require_match(interaction)
        if game is None:
            return
        picked = self.select.values[0]
        for option in self.select.options:
            option.default = option.value == picked
        # A teammate's view is "<seat>:<view>"; the clicker's own views
        # never start with a digit ("spec:anarchy" among them).
        owner, _, rest = picked.partition(":")
        self.owner, view = (int(owner), rest) if owner.isdigit() else (self.seat, picked)
        started = time.perf_counter()
        pictures = kept_pictures([await self.picture(match, view)], interaction.message)
        drawn = elapsed_ms(started)
        started = time.perf_counter()
        await edit_clicked(interaction, content=self.caption(view), attachments=pictures, view=self)
        LOGGER.info("Codex game #%s: the codex's %s drawn in %d ms (%d KB), shown in place in %d ms",
                    game.game_number, codex_view_name(view), drawn,
                    pictures_size(pictures) // 1024, elapsed_ms(started))

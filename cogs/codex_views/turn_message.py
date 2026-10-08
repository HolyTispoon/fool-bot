"""
The buttons on the current turn's public message (docs/codex-bot.md,
decisions 4 and 5): **My hand**, **Tech**, **Codex** and **Swap view**
-- persistent, so a restart re-arms them from `turn_message_id`.

Hidden information is answered **ephemerally**, to the clicker alone and
stored nowhere. **My hand** is one button with two answers by who
clicked (the author, 2026-10-08): the active player gets the control
panel for whatever the match asks them -- the actions, the defender,
the patrol lock, the tech confirmation -- made afresh each time; the
other player gets their hand pictured and their discard pile listed,
with nothing to press. **Tech** is the other player's alone: their
standing tech choice, open all through the opponent's turn. **Codex**
pictures the clicker's own codex through a menu of views. What a hand
may play and what a codex still holds are the engine's answers
(`hand_rows`, `codex_remaining`); the views compute nothing. Step 7
adds Concede.
"""

import asyncio
import io
from collections import Counter

import discord

from codex.game import GameStatus, RuleRefusal
from codex.render import render_codex, render_hand
from cogs.codex_helpers import card_name
from cogs.codex_views.base import SafeView, send_ephemeral

#: What each codex view is called in the menu.
CODEX_VIEW_LABELS = {
    "everything": "Everything",
    "tech1": "Tech I",
    "tech2": "Tech II",
    "tech3": "Tech III",
    "spells": "Spells",
}

NOT_YOUR_TABLE = "This table is not yours: only its two players have a hand and a codex here."


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
            ("Tech", "tech", discord.ButtonStyle.secondary),
            ("Codex", "codex", discord.ButtonStyle.secondary),
            (swap_label(layout), "swap", discord.ButtonStyle.secondary),
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
        seat = game.seat_of(interaction.user.id)
        if seat is None:
            await send_ephemeral(interaction, NOT_YOUR_TABLE)
            return None, None, None
        return game, match, seat

    async def hand(self, interaction: discord.Interaction) -> None:
        """The panel for the active player, the hand for the other."""
        game, match, seat = await self._seat(interaction)
        if seat is None:
            return
        if seat == match.active and match.winner is None:
            await self.cog.show_panel(interaction, game, match, seat, edit=False)
            return
        await self.cog.send_hand(interaction, game, match, seat)

    async def tech(self, interaction: discord.Interaction) -> None:
        """The other player's standing tech choice, to them alone."""
        game, match, seat = await self._seat(interaction)
        if seat is None:
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
        view = CodexBrowser(self.cog, game.game_id, seat)
        await interaction.response.send_message(
            view.caption("everything"), file=await view.picture(match, "everything"),
            view=view, ephemeral=True,
        )

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


def hand_caption(match, seat: int) -> str:
    """What the hand picture is sent with: its count and the discard
    pile's contents, which is its owner's to know (UMR p. 5)."""
    player = match.player(seat)
    count = len(player.hand)
    lines = [f"Your hand: {count} card" + ("" if count == 1 else "s") + ". Only you can see this."]
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
    png = await asyncio.to_thread(
        render_hand, [row.slug for row in rows], [row.allowed for row in rows],
        [row.cost for row in rows], engine.catalog,
    )
    return discord.File(io.BytesIO(png), filename="codex-hand.png")


class CodexBrowser(SafeView):
    """
    The clicker's own codex, ephemeral, under a menu of views --
    Everything, Tech I to III, Spells -- the picture re-rendered in place
    on each choice (the author, 2026-10-08: "a lot of cards"). Not
    persistent: an ephemeral message dies with the client's session, and
    **Codex** on the turn message makes a fresh one.
    """

    def __init__(self, cog, game_id: str, seat: int) -> None:
        super().__init__(timeout=900)
        self.cog = cog
        self.game_id = game_id
        self.seat = seat
        game = cog.games.get(game_id)
        match = cog.service.load(game)
        views = cog.engine.codex_views(match.player(seat))
        select = discord.ui.Select(
            placeholder="Show...",
            options=[
                discord.SelectOption(label=CODEX_VIEW_LABELS.get(view, view), value=view)
                for view in views
            ],
        )
        select.callback = self.choose
        self.select = select
        self.add_item(select)

    def caption(self, view: str) -> str:
        return f"Your codex: {CODEX_VIEW_LABELS.get(view, view)}. Only you can see this."

    async def picture(self, match, view: str) -> discord.File:
        rows = self.cog.engine.codex_remaining(match, self.seat, view)
        png = await asyncio.to_thread(
            render_codex, [slug for slug, _ in rows], [count for _, count in rows],
            self.cog.engine.catalog,
        )
        return discord.File(io.BytesIO(png), filename=f"codex-{view}.png")

    async def choose(self, interaction: discord.Interaction) -> None:
        game, match = await self.require_match(interaction)
        if game is None:
            return
        view = self.select.values[0]
        await interaction.response.edit_message(
            content=self.caption(view), attachments=[await self.picture(match, view)], view=self,
        )

"""
The buttons on the current turn's public message (docs/codex-bot.md,
decisions 4 and 5): **My hand**, **Codex** and **Swap view** --
persistent, so a restart re-arms them from `turn_message_id`.

Hidden information is answered **ephemerally**, to the clicker alone and
stored nowhere: My hand pictures the clicker's own hand and lists their
discard pile; Codex pictures their own codex through a menu of views.
What a hand may play and what a codex still holds are the engine's
answers (`hand_rows`, `codex_remaining`); the views compute nothing.
Step 4 makes My hand answer the active player with the control panel
and adds Tech for the other; step 7 adds Concede.
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
        seat = game.seat_for(interaction.user.id, match.active)
        if seat is None:
            await send_ephemeral(interaction, NOT_YOUR_TABLE)
            return None, None, None
        return game, match, seat

    async def hand(self, interaction: discord.Interaction) -> None:
        game, match, seat = await self._seat(interaction)
        if seat is None:
            return
        await self.cog.send_hand(interaction, game, match, seat)

    async def codex(self, interaction: discord.Interaction) -> None:
        game, match, seat = await self._seat(interaction)
        if seat is None:
            return
        view = CodexBrowser(self.cog, game.game_id, seat, side=side_label(game, match, seat))
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


def side_label(game, match, seat: int) -> str:
    """" (Bashing)" -- which side a picture is of, said only in a test
    game, where one person holds both and the turn decides which."""
    if not game.test_game:
        return ""
    return f" ({match.player(seat).spec.title()})"


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


async def hand_file(engine, match, seat: int) -> discord.File:
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

    def __init__(self, cog, game_id: str, seat: int, side: str = "") -> None:
        super().__init__(timeout=900)
        self.cog = cog
        self.game_id = game_id
        self.seat = seat
        self.side = side
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
        return f"Your codex{self.side}: {CODEX_VIEW_LABELS.get(view, view)}. Only you can see this."

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

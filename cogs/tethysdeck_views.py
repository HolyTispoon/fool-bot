"""
The discord.ui.View/Modal classes that drive the Tethys deck's
interaction flow. Every view holds a reference to the TethysDeck cog
(as `self.cog`) and calls back into it to run deck logic; the views
themselves are concerned with rendering prompts and turning
button/select/modal input into calls on the cog.
"""

from typing import TYPE_CHECKING, Awaitable, Callable, Optional

import discord

from cogs.tethysdeck_helpers import (
    LOGGER,
    MAX_SELECT_OPTIONS,
    send_error_fallback,
)

if TYPE_CHECKING:
    from cogs.tethysdeck import TethysDeck


class SafeView(discord.ui.View):
    """
    discord.py's default behavior for an uncaught exception in a
    button/select callback is to log it and otherwise do nothing,
    which leaves the click looking like it had no effect at all. This
    surfaces a message instead.
    """

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
        item: discord.ui.Item,
    ) -> None:
        LOGGER.error(
            "Unhandled error in %r for %r: %r",
            self, item, error, exc_info=error,
        )
        await send_error_fallback(
            interaction,
            "Something went wrong handling that click. Please try again.",
        )


class ConfirmView(SafeView):
    """
    A generic Yes/No prompt. `on_yes` runs when confirmed; if `on_no`
    is not given, declining just erases the prompt.
    """

    def __init__(
        self,
        on_yes: Callable[[discord.Interaction], Awaitable[None]],
        on_no: Optional[Callable[[discord.Interaction], Awaitable[None]]] = None,
    ):
        super().__init__(timeout=120)
        self._on_yes = on_yes
        self._on_no = on_no

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.danger)
    async def yes_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await self._on_yes(interaction)

    @discord.ui.button(label="No", style=discord.ButtonStyle.secondary)
    async def no_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if self._on_no is not None:
            await self._on_no(interaction)
            return
        await interaction.response.defer()
        await interaction.delete_original_response()


class DeckStatusView(SafeView):
    """
    Posted under the "Current number of cards..." message for a
    channel's deck. Stateless -- every callback resolves the channel
    from the interaction itself, so one instance is registered as a
    persistent view and reused for every channel's status message.
    """

    def __init__(self, cog: "TethysDeck"):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label="Draw",
        style=discord.ButtonStyle.primary,
        custom_id="tethysdeck:draw",
    )
    async def draw_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await self.cog.prompt_draw_count(interaction)

    @discord.ui.button(
        label="My Hand",
        style=discord.ButtonStyle.secondary,
        custom_id="tethysdeck:my_hand",
    )
    async def my_hand_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await self.cog.show_hand(interaction, interaction.user)

    @discord.ui.button(
        label="Reset",
        style=discord.ButtonStyle.danger,
        custom_id="tethysdeck:reset",
    )
    async def reset_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await self.cog.prompt_reset(interaction)

    @discord.ui.button(
        label="Show Discard",
        style=discord.ButtonStyle.secondary,
        custom_id="tethysdeck:show_discard",
    )
    async def show_discard_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await self.cog.show_discard(interaction)


class HigherNumberModal(discord.ui.Modal, title="Draw cards"):
    count = discord.ui.TextInput(
        label="Number of cards to draw (8 or more)",
        placeholder="e.g. 10",
        max_length=6,
    )

    def __init__(self, cog: "TethysDeck", channel_id: str):
        super().__init__()
        self.cog = cog
        self.channel_id = channel_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        raw = self.count.value.strip()
        state = self.cog.decks.get(self.channel_id)
        deck_size = len(state.deck) if state is not None else 0

        if not raw.isdigit() or int(raw) < 8:
            await interaction.response.send_message(
                "Enter a whole number of 8 or more.", ephemeral=True,
            )
            return

        count = int(raw)
        if count > deck_size:
            await interaction.response.send_message(
                f"The deck only has {deck_size} card"
                f"{'' if deck_size == 1 else 's'} left. Enter a number "
                f"of 8 or more, up to {deck_size}.",
                ephemeral=True,
            )
            return

        await self.cog.draw_cards(interaction, self.channel_id, count)

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
    ) -> None:
        LOGGER.error(
            "Unhandled error in %r: %r", self, error, exc_info=error,
        )
        await send_error_fallback(
            interaction,
            "Something went wrong handling that. Please try again.",
        )


class DrawCountView(SafeView):
    """
    Ephemeral "how many cards?" prompt shown after clicking Draw.
    """

    def __init__(self, cog: "TethysDeck", channel_id: str):
        super().__init__(timeout=120)
        self.cog = cog
        self.channel_id = channel_id

        for count in range(1, 8):
            button = discord.ui.Button(
                label=f"{count} card" if count == 1 else f"{count} cards",
                style=discord.ButtonStyle.primary,
            )

            async def draw_callback(
                interaction: discord.Interaction,
                count: int = count,
            ) -> None:
                # Dismiss this picker before drawing so it can't be
                # clicked again for the same draw.
                await interaction.response.defer()
                await interaction.delete_original_response()
                await self.cog.draw_cards(interaction, self.channel_id, count)

            button.callback = draw_callback
            self.add_item(button)

        higher_button = discord.ui.Button(
            label="Higher number", style=discord.ButtonStyle.secondary,
        )

        async def higher_callback(interaction: discord.Interaction) -> None:
            await interaction.response.send_modal(
                HigherNumberModal(self.cog, self.channel_id)
            )

        higher_button.callback = higher_callback
        self.add_item(higher_button)


class HandView(SafeView):
    """
    Shown alongside any display of a user's own hand, letting them
    discard cards out of it.
    """

    def __init__(self, cog: "TethysDeck", channel_id: str, user_id: str):
        super().__init__(timeout=180)
        self.cog = cog
        self.channel_id = channel_id
        self.user_id = user_id

    @discord.ui.button(label="Discard", style=discord.ButtonStyle.danger)
    async def discard_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        state = self.cog.decks.get(self.channel_id)
        if state is None:
            await interaction.response.send_message(
                "There is no deck in this channel anymore.", ephemeral=True,
            )
            return

        hand = state.hands.get(self.user_id, [])
        if not hand:
            await interaction.response.send_message(
                "You have no cards to discard.", ephemeral=True,
            )
            return

        await interaction.response.send_message(
            "Choose cards to discard:",
            view=DiscardSelectView(
                self.cog, self.channel_id, self.user_id, hand,
            ),
            ephemeral=True,
        )


class DiscardSelectView(SafeView):
    def __init__(
        self,
        cog: "TethysDeck",
        channel_id: str,
        user_id: str,
        hand: list[str],
    ):
        super().__init__(timeout=120)
        self.cog = cog
        self.channel_id = channel_id
        self.user_id = user_id

        options = [
            discord.SelectOption(label=card, value=card)
            for card in hand[:MAX_SELECT_OPTIONS]
        ]
        select = discord.ui.Select(
            placeholder="Select cards to discard",
            min_values=1,
            max_values=len(options),
            options=options,
        )

        async def select_callback(interaction: discord.Interaction) -> None:
            await self.cog.discard_cards(
                interaction, self.channel_id, self.user_id, select.values,
            )

        select.callback = select_callback
        self.add_item(select)

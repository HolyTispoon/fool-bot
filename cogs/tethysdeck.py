import asyncio
import io
import random
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from tethysdeck.strips import Faces

from gamesaves.tethysdeck.storage import (
    ChannelDeck,
    load_decks,
    save_decks,
)

from cogs.tethysdeck_helpers import (
    LOGGER,
    build_deck,
    deck_status_text,
    format_cards,
    format_discard_text,
    format_hand_text,
    parse_card,
    send_error_fallback,
)
from cogs.tethysdeck_views import (
    ConfirmView,
    DeckStatusView,
    DrawCountView,
    HandView,
)


class TethysDeck(commands.GroupCog, group_name="tethyscards"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.decks: dict[str, ChannelDeck] = load_decks()
        self.deck_status_view = DeckStatusView(self)
        # The deck's faces, drawn once as the cog loads; None until then,
        # or if they could not be drawn, and the commands answer in words.
        self.faces: Optional[Faces] = None

    async def cog_load(self) -> None:
        # Stateless, so one instance covers every channel's status
        # message and survives a restart.
        self.bot.add_view(self.deck_status_view)
        try:
            self.faces = await asyncio.to_thread(Faces)
        except Exception:
            LOGGER.exception(
                "Could not draw the Tethys deck's faces; the cards are "
                "shown as text until the bot restarts."
            )

    async def cog_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        original = getattr(error, "original", error)
        command_name = (
            interaction.command.qualified_name
            if interaction.command is not None
            else "unknown command"
        )
        LOGGER.error(
            "Unhandled error in /%s: %r",
            command_name, original, exc_info=original,
        )
        await send_error_fallback(
            interaction,
            "Something went wrong running that command. Please try again.",
        )

    @property
    def pictured(self) -> bool:
        """Whether a reply shows its cards as a picture. While it does, the
        words name only what the picture does not show (the author,
        2026-10-11: "No need to list the cards, just showing them is
        enough"); without the faces every card is named, as before."""
        return self.faces is not None

    # -- shared deck logic, called by both slash commands and views --

    def build_and_save_new_deck(self, channel_id: str) -> ChannelDeck:
        cards = build_deck()
        random.shuffle(cards)
        state = ChannelDeck(deck=cards)
        self.decks[channel_id] = state
        save_decks(self.decks)
        return state

    async def post_deck_status_message(
        self,
        channel: discord.abc.Messageable,
        state: ChannelDeck,
    ) -> None:
        message = await channel.send(
            deck_status_text(state), view=self.deck_status_view,
        )
        state.status_message_id = message.id
        save_decks(self.decks)

        try:
            await message.pin(reason="Tethys deck status message")
        except discord.HTTPException as error:
            LOGGER.warning(
                "Could not pin deck status message in channel %s: %s",
                channel.id, error,
            )

    async def unpin_status_message(
        self,
        channel: discord.abc.Messageable,
        state: ChannelDeck,
    ) -> None:
        if state.status_message_id is None:
            return
        try:
            message = channel.get_partial_message(state.status_message_id)
            await message.unpin()
        except discord.HTTPException as error:
            LOGGER.warning(
                "Could not unpin old deck status message in channel %s: %s",
                channel.id, error,
            )

    async def reply(
        self,
        interaction: discord.Interaction,
        content: str,
        *,
        view: Optional[discord.ui.View] = None,
        cards: Optional[list[str]] = None,
    ) -> None:
        kwargs = {"ephemeral": True}
        if view is not None:
            kwargs["view"] = view
        picture = await self.cards_picture(cards or [])
        if picture is not None:
            kwargs["file"] = picture
        if interaction.response.is_done():
            await interaction.followup.send(content, **kwargs)
        else:
            await interaction.response.send_message(content, **kwargs)

    async def cards_picture(self, cards: list[str]) -> Optional[discord.File]:
        """The cards as a row of the deck's own faces, or None for no cards
        or no faces."""
        if not cards or self.faces is None:
            return None
        png = await asyncio.to_thread(
            self.faces.row_png, [parse_card(card) for card in cards],
        )
        return discord.File(io.BytesIO(png), filename="tethys_cards.png")

    async def update_status_message(
        self,
        channel: discord.abc.Messageable,
        state: ChannelDeck,
    ) -> None:
        if state.status_message_id is None:
            return
        try:
            message = channel.get_partial_message(state.status_message_id)
            await message.edit(
                content=deck_status_text(state), view=self.deck_status_view,
            )
        except discord.HTTPException as error:
            LOGGER.warning(
                "Could not update deck status message in channel %s: %s",
                channel.id, error,
            )

    async def prompt_draw_count(self, interaction: discord.Interaction) -> None:
        channel_id = str(interaction.channel_id)
        if channel_id not in self.decks:
            await self.reply(
                interaction,
                "There is no deck in this channel yet. Use "
                "`/tethyscards new_deck` first.",
            )
            return
        await interaction.response.send_message(
            "How many cards would you like to draw?",
            view=DrawCountView(self, channel_id),
            ephemeral=True,
        )

    async def draw_cards(
        self,
        interaction: discord.Interaction,
        channel_id: str,
        count: int,
    ) -> None:
        state = self.decks.get(channel_id)
        if state is None:
            await self.reply(
                interaction, "There is no deck in this channel anymore.",
            )
            return

        drawn = [
            state.deck.pop() for _ in range(min(count, len(state.deck)))
        ]
        user_id = str(interaction.user.id)
        hand = state.hands.setdefault(user_id, [])
        hand.extend(drawn)
        save_decks(self.decks)

        await self.update_status_message(interaction.channel, state)

        if drawn:
            card_word = "card" if len(drawn) == 1 else "cards"
            # The drawn cards are the last of the hand, so the picture
            # shows them; the words name them only without it.
            header = f"Drew {len(drawn)} {card_word}"
            header += "." if self.pictured else f": {format_cards(drawn)}"
        else:
            header = "The deck is empty -- nothing to draw."

        await self.respond_with_hand(
            interaction, interaction.user, state, header=header,
        )

    async def respond_with_hand(
        self,
        interaction: discord.Interaction,
        target_user: discord.abc.User,
        state: ChannelDeck,
        header: Optional[str] = None,
    ) -> None:
        channel_id = str(interaction.channel_id)
        hand = state.hands.get(str(target_user.id), [])
        text = format_hand_text(
            target_user, hand, header=header, listed=not self.pictured,
        )

        view = None
        if target_user.id == interaction.user.id and hand:
            view = HandView(self, channel_id, str(target_user.id))

        await self.reply(interaction, text, view=view, cards=hand)

    async def show_hand(
        self,
        interaction: discord.Interaction,
        user: discord.abc.User,
    ) -> None:
        channel_id = str(interaction.channel_id)
        state = self.decks.get(channel_id)
        if state is None:
            await interaction.response.send_message(
                "There is no deck in this channel yet.", ephemeral=True,
            )
            return
        await self.respond_with_hand(interaction, user, state)

    async def discard_cards(
        self,
        interaction: discord.Interaction,
        channel_id: str,
        user_id: str,
        cards: list[str],
    ) -> None:
        state = self.decks.get(channel_id)
        if state is None:
            await self.reply(
                interaction, "There is no deck in this channel anymore.",
            )
            return

        hand = state.hands.setdefault(user_id, [])
        discarded = [card for card in cards if card in hand]
        for card in discarded:
            hand.remove(card)
        state.discard.extend(discarded)
        if not hand:
            state.hands.pop(user_id, None)
        save_decks(self.decks)

        await self.update_status_message(interaction.channel, state)

        # The discarded cards are named whatever is shown: the picture
        # under this is the hand they left, not them.
        header = (
            f"Discarded: {format_cards(discarded)}"
            if discarded else "Nothing was discarded."
        )
        await self.respond_with_hand(
            interaction, interaction.user, state, header=header,
        )

    async def show_discard(self, interaction: discord.Interaction) -> None:
        channel_id = str(interaction.channel_id)
        state = self.decks.get(channel_id)
        if state is None:
            await interaction.response.send_message(
                "There is no deck in this channel yet.", ephemeral=True,
            )
            return
        await self.reply(
            interaction,
            format_discard_text(state.discard, listed=not self.pictured),
            cards=state.discard,
        )

    async def prompt_reset(self, interaction: discord.Interaction) -> None:
        channel_id = str(interaction.channel_id)
        if channel_id not in self.decks:
            await interaction.response.send_message(
                "There is no deck in this channel yet.", ephemeral=True,
            )
            return

        async def confirm_reset(confirm_interaction: discord.Interaction) -> None:
            state = self.decks.get(channel_id)
            if state is None:
                await confirm_interaction.response.edit_message(
                    content="There is no deck in this channel anymore.",
                    view=None,
                )
                return

            all_cards = [*state.deck, *state.discard]
            for hand in state.hands.values():
                all_cards.extend(hand)
            random.shuffle(all_cards)

            state.deck = all_cards
            state.discard = []
            state.hands = {}
            save_decks(self.decks)

            await confirm_interaction.response.edit_message(
                content=(
                    "The deck has been reset. All cards have been "
                    "shuffled back in."
                ),
                view=None,
            )
            await self.update_status_message(
                confirm_interaction.channel, state,
            )

        await interaction.response.send_message(
            "Resetting the deck will put all cards in hands and the "
            "discard back into the deck. Are you sure?",
            view=ConfirmView(on_yes=confirm_reset),
            ephemeral=True,
        )

    # -- slash commands --

    @app_commands.command(
        name="new_deck",
        description="Shuffle a new 72-card Foolish style deck in this channel.",
    )
    @app_commands.guild_only()
    async def new_deck(self, interaction: discord.Interaction) -> None:
        channel_id = str(interaction.channel_id)

        if channel_id in self.decks:
            async def confirm_new_deck(
                confirm_interaction: discord.Interaction,
            ) -> None:
                await confirm_interaction.response.edit_message(
                    content="Creating your new deck...", view=None,
                )
                channel = confirm_interaction.channel
                old_state = self.decks.get(channel_id)
                await channel.send(
                    "Shuffled a new Foolish style 72-card deck in "
                    f"channel {channel.mention}."
                )
                state = self.build_and_save_new_deck(channel_id)
                await self.post_deck_status_message(channel, state)
                if old_state is not None:
                    await self.unpin_status_message(channel, old_state)

            await interaction.response.send_message(
                "Creating a new deck in this channel will delete the "
                "previous deck. Are you sure?",
                view=ConfirmView(on_yes=confirm_new_deck),
                ephemeral=True,
            )
            return

        channel = interaction.channel
        await interaction.response.send_message(
            "Shuffled a new Foolish style 72-card deck in "
            f"channel {channel.mention}."
        )
        state = self.build_and_save_new_deck(channel_id)
        await self.post_deck_status_message(channel, state)

    @app_commands.command(
        name="draw",
        description="Draw cards from this channel's deck into your hand.",
    )
    @app_commands.describe(count="How many cards to draw. Defaults to 1.")
    @app_commands.guild_only()
    async def draw(
        self,
        interaction: discord.Interaction,
        count: app_commands.Range[int, 1, None] = 1,
    ) -> None:
        channel_id = str(interaction.channel_id)
        if channel_id not in self.decks:
            await interaction.response.send_message(
                "There is no deck in this channel yet. Use "
                "`/tethyscards new_deck` first.",
                ephemeral=True,
            )
            return
        await self.draw_cards(interaction, channel_id, count)

    @app_commands.command(
        name="hand",
        description="Show a hand of drawn cards in this channel.",
    )
    @app_commands.describe(user="Whose hand to show. Defaults to your own.")
    @app_commands.guild_only()
    async def hand(
        self,
        interaction: discord.Interaction,
        user: Optional[discord.User] = None,
    ) -> None:
        await self.show_hand(interaction, user or interaction.user)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TethysDeck(bot))

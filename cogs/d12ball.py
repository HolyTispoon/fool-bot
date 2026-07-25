import random
import re
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands


CHANNEL_NAME_PATTERN = re.compile(r"^d12ball-pbd(\d+)$")


class CoinFlipView(discord.ui.View):
    def __init__(
        self,
        player_1: discord.Member,
        player_2: Optional[discord.Member],
    ):
        super().__init__(timeout=None)

        self.player_1 = player_1
        self.player_2 = player_2
        self.coin_flipped = False

    @discord.ui.button(
        label="Flip a coin",
        style=discord.ButtonStyle.primary,
        emoji="🪙",
    )
    async def flip_coin(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        allowed_player_ids = {self.player_1.id}

        if self.player_2 is not None:
            allowed_player_ids.add(self.player_2.id)

        if interaction.user.id not in allowed_player_ids:
            await interaction.response.send_message(
                "Only a player in this game can flip the coin.",
                ephemeral=True,
            )
            return

        if self.coin_flipped:
            await interaction.response.send_message(
                "The coin has already been flipped.",
                ephemeral=True,
            )
            return

        self.coin_flipped = True
        button.disabled = True

        if self.player_2 is None:
            competitors = [
                self.player_1.mention,
                "the AI opponent",
            ]
        else:
            competitors = [
                self.player_1.mention,
                self.player_2.mention,
            ]

        winner = random.choice(competitors)

        await interaction.response.edit_message(view=self)

        await interaction.followup.send(
            f"🪙 The coin has been flipped!\n\n"
            f"**{winner} wins the coin toss.**"
        )


class D12Ball(commands.GroupCog, group_name="d12ball"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @staticmethod
    def get_next_game_number(guild: discord.Guild) -> int:
        existing_numbers = []

        for channel in guild.text_channels:
            match = CHANNEL_NAME_PATTERN.fullmatch(channel.name.lower())

            if match:
                existing_numbers.append(int(match.group(1)))

        if not existing_numbers:
            return 1

        return max(existing_numbers) + 1

    @app_commands.command(
        name="create_game",
        description="Create a new D12 Ball game.",
    )
    @app_commands.describe(
        p1="Player 1. Leave blank to make yourself Player 1.",
        p2="Player 2. Leave blank to play against the AI.",
    )
    @app_commands.guild_only()
    async def create_game(
        self,
        interaction: discord.Interaction,
        p1: Optional[discord.Member] = None,
        p2: Optional[discord.Member] = None,
    ):
        guild = interaction.guild

        if guild is None:
            await interaction.response.send_message(
                "This command can only be used inside a server.",
                ephemeral=True,
            )
            return

        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "I could not identify the person creating the game.",
                ephemeral=True,
            )
            return

        # Determine the players.
        if p1 is None and p2 is None:
            player_1 = interaction.user
            player_2 = None

        elif p1 is not None and p2 is None:
            player_1 = interaction.user
            player_2 = p1

        elif p1 is None and p2 is not None:
            player_1 = interaction.user
            player_2 = p2

        else:
            player_1 = p1
            player_2 = p2

        if player_1 is None:
            await interaction.response.send_message(
                "Player 1 could not be identified.",
                ephemeral=True,
            )
            return

        if player_1.bot:
            await interaction.response.send_message(
                "Player 1 cannot be a bot.",
                ephemeral=True,
            )
            return

        if player_2 is not None and player_2.bot:
            await interaction.response.send_message(
                "Player 2 cannot be a bot.",
                ephemeral=True,
            )
            return

        if player_2 is not None and player_1.id == player_2.id:
            await interaction.response.send_message(
                "Player 1 and Player 2 must be different people.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        game_number = self.get_next_game_number(guild)
        channel_name = f"d12ball-pbd{game_number}"

        bot_member = guild.me

        if bot_member is None:
            await interaction.followup.send(
                "I could not find my server account.",
                ephemeral=True,
            )
            return

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=False,
            ),
            player_1: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
            ),
            bot_member: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_channels=True,
            ),
        }

        if player_2 is not None:
            overwrites[player_2] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
            )

        try:
            category = None

            if isinstance(interaction.channel, discord.TextChannel):
                category = interaction.channel.category

            game_channel = await guild.create_text_channel(
                name=channel_name,
                overwrites=overwrites,
                category=category,
                reason=f"D12 Ball game created by {interaction.user}",
            )

        except discord.Forbidden:
            await interaction.followup.send(
                "I do not have permission to create channels.",
                ephemeral=True,
            )
            return

        except discord.HTTPException as error:
            await interaction.followup.send(
                f"Discord could not create the channel: {error}",
                ephemeral=True,
            )
            return

        view = CoinFlipView(
            player_1=player_1,
            player_2=player_2,
        )

        if player_2 is None:
            message = (
                f"{player_1.mention}, start playing in this channel.\n\n"
                f"**Player 1:** {player_1.mention}\n"
                f"**Player 2:** AI opponent"
            )
        else:
            message = (
                f"{player_1.mention} {player_2.mention}, "
                f"start playing in this channel.\n\n"
                f"**Player 1:** {player_1.mention}\n"
                f"**Player 2:** {player_2.mention}"
            )

        await game_channel.send(
            message,
            view=view,
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False,
            ),
        )

        await interaction.followup.send(
            f"Game created: {game_channel.mention}",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(D12Ball(bot))